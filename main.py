import asyncio
import os
import random
import urllib.parse
from mcp_ui_server import create_ui_resource
from mcp_ui_server.core import UIResource
from reboot.aio.external import InitializeContext
from reboot.aio.workflows import at_least_once, at_most_once
from reboot.mcp.server import DurableMCP, DurableContext
from store.backend.src.cart import CartServicer
from store.backend.src.product import ProductCatalogServicer
from store.backend.src.order import OrdersServicer
from store.v1 import store_pb2
from store.v1.store_rbt import ProductCatalog, Cart, Orders

mcp = DurableMCP(path="/mcp")


@mcp.tool()
def show_products(search_query: str = "") -> list[UIResource]:
    """Display products matching the search query in an interactive UI.

    Args:
        search_query: The search term to filter products (e.g., 'shirts', 'pants', 'blue')
    """
    encoded_query = urllib.parse.quote(search_query)
    iframe_url = f"http://localhost:3001/products?query={encoded_query}" if search_query else "http://localhost:3001/products"

    ui_resource = create_ui_resource(
        {
            "uri":
                f"ui://products/search/{encoded_query}"
                if search_query else "ui://products/all",
            "adapters": {
                "apps_sdk": {
                    "enabled": True
                }
            },
            "content": {
                "type": "externalUrl",
                "iframeUrl": iframe_url
            },
            "metadata":
                {
                    'openai/widgetDescription': 'Interactive calculator',
                    'openai/widgetCSP':
                        {
                            "connect_domains": [],
                            "resource_domains": [],
                        },
                    'openai/widgetPrefersBorder': True,
                },
            "encoding":
                "text"
        }
    )
    return [ui_resource]


@mcp.tool()
def show_cart() -> list[UIResource]:
    """Display the shopping cart in an interactive UI."""
    iframe_url = f"http://localhost:3001/cart"

    ui_resource = create_ui_resource(
        {
            "uri": f"ui://cart",
            "content": {
                "type": "externalUrl",
                "iframeUrl": iframe_url
            },
            "encoding": "text"
        }
    )
    return [ui_resource]


@mcp.tool()
def show_orders() -> list[UIResource]:
    """Display past orders in an interactive UI."""
    iframe_url = f"http://localhost:3001/orders"

    ui_resource = create_ui_resource(
        {
            "uri": f"ui://orders",
            "content": {
                "type": "externalUrl",
                "iframeUrl": iframe_url
            },
            "encoding": "text"
        }
    )
    return [ui_resource]


@mcp.tool()
async def add_item_to_cart(
    product_id: str, quantity: int, context: DurableContext
) -> list[UIResource]:
    """Add an item to the shopping cart.

    Args:
        product_id: The ID of the product to add
        quantity: The quantity to add (default: 1)
        catalog_id: The ID of the product catalog (default: "default-catalog")
    """
    cart_id = "default-cart"
    catalog_id = "default-catalog"

    # Verify product exists.
    await ProductCatalog.ref(catalog_id).get_product(
        context,
        catalog_id=catalog_id,
        product_id=product_id,
    )

    await Cart.ref(cart_id).add_item(
        context,
        item=store_pb2.CartItem(
            product_id=product_id,
            quantity=quantity,
        ),
        catalog_id=catalog_id,
    )

    iframe_url = f"http://localhost:3001/cart"

    ui_resource = create_ui_resource(
        {
            "uri": f"ui://cart",
            "content": {
                "type": "externalUrl",
                "iframeUrl": iframe_url
            },
            "encoding": "text"
        }
    )
    return [ui_resource]


# Mock stateless functions for checkout workflow
async def get_shipping_quote(items: list, address: dict) -> dict:
    """Mock function to get shipping quote."""
    total_weight = len(items) * 2  # Mock weight calculation
    base_cost = 500  # $5.00 base
    weight_cost = total_weight * 50  # $0.50 per pound
    total_cost = base_cost + weight_cost

    return {
        "cost_cents": total_cost,
        "carrier": "Mock Shipping Co.",
        "estimated_days": random.randint(3, 7),
    }


async def charge_credit_card(card_info: dict, amount_cents: int) -> dict:
    """Mock function to charge credit card (non-idempotent)."""
    # In real implementation, this would call a payment processor
    return {
        "transaction_id": f"txn_{random.randint(100000, 999999)}",
        "last_four": card_info.get("number", "0000")[-4:],
        "amount_cents": amount_cents,
    }


async def ship_order(items: list, address: dict, carrier: str) -> dict:
    """Mock function to ship order (non-idempotent)."""
    # In real implementation, this would call a shipping API
    return {
        "tracking_number": f"TRACK{random.randint(1000000000, 9999999999)}",
        "carrier": carrier,
        "status": "shipped",
    }


@mcp.tool()
async def checkout(
    card_number: str, card_cvv: int, card_expiration_month: int,
    card_expiration_year: int, shipping_street_address: str,
    shipping_city: str, shipping_state: str, shipping_country: str,
    shipping_zip_code: str, context: DurableContext
) -> list[UIResource]:
    """Complete the checkout process for items in the cart.

    Args:
        card_number: Credit card number
        card_cvv: Credit card CVV
        card_expiration_month: Credit card expiration month
        card_expiration_year: Credit card expiration year
        shipping_street_address: Shipping street address
        shipping_city: Shipping city
        shipping_state: Shipping state
        shipping_country: Shipping country
        shipping_zip_code: Shipping zip code
    """
    cart_id = "default-cart"

    # Get cart items
    cart_response = await Cart.ref(cart_id).get_items(context)
    items = list(cart_response.items)

    if not items:
        raise ValueError("Cart is empty")

    # Calculate subtotal
    subtotal_cents = sum(item.price_cents * item.quantity for item in items)

    # Prepare address dict
    address = {
        "street_address": shipping_street_address,
        "city": shipping_city,
        "state": shipping_state,
        "country": shipping_country,
        "zip_code": shipping_zip_code,
    }

    # Get shipping quote (idempotent - at_least_once)
    async def get_quote():
        return await get_shipping_quote(items, address)

    shipping_quote = await at_least_once(
        "Get shipping quote",
        context,
        get_quote,
        type=dict,
    )

    total_cents = subtotal_cents + shipping_quote["cost_cents"]

    async def charge_card() -> dict:
        return await charge_credit_card(
            {
                "number": card_number,
                "cvv": card_cvv,
                "expiration_month": card_expiration_month,
                "expiration_year": card_expiration_year,
            },
            total_cents,
        )

    if os.environ.get("FAIL_CHECKOUT"):
        await asyncio.Event().wait()

    charge_result = await at_least_once(
        "Charge credit card",
        context,
        charge_card,
        type=dict,
    )

    # if charge_result.get("error"):
    #     raise ValueError(f"Failed to charge card: {charge_result['error']}")
    async def ship() -> dict:
        return await ship_order(items, address, shipping_quote["carrier"])

    shipping_result = await at_least_once(
        "Ship order",
        context,
        ship,
        type=dict,
    )

    # if shipping_result.get("error"):
    #     raise ValueError(f"Failed to ship order: {shipping_result['error']}")

    # Save order to Orders state.
    order_id = f"order_{random.randint(100000, 999999)}"

    order = store_pb2.Order(
        order_id=order_id,
        items=items,
        transaction_id=charge_result["transaction_id"],
        subtotal_cents=subtotal_cents,
        shipping_cost_cents=shipping_quote["cost_cents"],
        total_cents=total_cents,
        tracking_number=shipping_result["tracking_number"],
        carrier=shipping_result["carrier"],
        created_at=int(asyncio.get_event_loop().time()),
        shipping_address=store_pb2.Address(
            street_address=shipping_street_address,
            city=shipping_city,
            state=shipping_state,
            country=shipping_country,
            zip_code=shipping_zip_code,
        ),
    )

    await Orders.ref("default-orders").add_order(context, order=order)

    # Empty the cart.
    await Cart.ref(cart_id).empty_cart(context)

    # Encode order details for URL
    encoded_order = urllib.parse.quote(
        f"{order_id}|{charge_result}|{subtotal_cents}|{shipping_quote['cost_cents']}|{total_cents}|{shipping_result}"
    )

    iframe_url = f"http://localhost:3001/order?data={encoded_order}"

    ui_resource = create_ui_resource(
        {
            "uri": f"ui://order/{order_id}",
            "content": {
                "type": "externalUrl",
                "iframeUrl": iframe_url
            },
            "encoding": "text"
        }
    )

    return [ui_resource]


async def initialize(context: InitializeContext):
    """Initialize the product catalog with mock products."""
    catalog_id = "default-catalog"

    # Define all products from the mockProducts array
    products = [
        # Shirts
        store_pb2.Product(
            id="shirt-001",
            name="Classic Blue Shirt",
            description="A comfortable cotton shirt in classic blue",
            picture="https://pngimg.com/uploads/tshirt/tshirt_PNG5437.png",
            price_cents=2999,
            categories=["shirts", "men", "casual"],
            stock_quantity=50,
        ),
        store_pb2.Product(
            id="shirt-002",
            name="White Dress Shirt",
            description="Elegant white dress shirt for formal occasions",
            picture="https://pngimg.com/uploads/tshirt/tshirt_PNG5447.png",
            price_cents=3999,
            categories=["shirts", "men", "formal"],
            stock_quantity=30,
        ),
        store_pb2.Product(
            id="shirt-003",
            name="Black Polo Shirt",
            description="Sporty black polo shirt",
            picture="https://pngimg.com/uploads/tshirt/tshirt_PNG5427.png",
            price_cents=3499,
            categories=["shirts", "men", "sports"],
            stock_quantity=25,
        ),
        store_pb2.Product(
            id="shirt-004",
            name="Red Flannel Shirt",
            description="Cozy red flannel for casual wear",
            picture="https://pngimg.com/uploads/tshirt/tshirt_PNG5437.png",
            price_cents=4599,
            categories=["shirts", "men", "casual"],
            stock_quantity=20,
        ),
        store_pb2.Product(
            id="shirt-005",
            name="Striped Button-Down",
            description="Navy striped button-down shirt",
            picture="https://pngimg.com/uploads/tshirt/tshirt_PNG5454.png",
            price_cents=3899,
            categories=["shirts", "men", "business"],
            stock_quantity=15,
        ),
        # Pants
        store_pb2.Product(
            id="pants-001",
            name="Denim Jeans",
            description="Classic blue denim jeans",
            picture="https://pngimg.com/uploads/jeans/jeans_PNG5763.png",
            price_cents=4999,
            categories=["pants", "men", "casual"],
            stock_quantity=40,
        ),
        store_pb2.Product(
            id="pants-002",
            name="Khaki Chinos",
            description="Versatile khaki chinos",
            picture="https://pngimg.com/uploads/jeans/jeans_PNG5763.png",
            price_cents=4499,
            categories=["pants", "men", "casual"],
            stock_quantity=35,
        ),
        store_pb2.Product(
            id="pants-003",
            name="Black Dress Pants",
            description="Formal black dress pants",
            picture="https://pngimg.com/uploads/jeans/jeans_PNG5763.png",
            price_cents=5999,
            categories=["pants", "men", "formal"],
            stock_quantity=25,
        ),
        store_pb2.Product(
            id="pants-004",
            name="Gray Joggers",
            description="Comfortable gray joggers",
            picture="https://pngimg.com/uploads/jeans/jeans_PNG5763.png",
            price_cents=4299,
            categories=["pants", "men", "sports"],
            stock_quantity=30,
        ),
        # Shoes
        store_pb2.Product(
            id="shoes-001",
            name="White Sneakers",
            description="Classic white leather sneakers",
            picture=
            "https://pngimg.com/uploads/men_shoes/men_shoes_PNG7476.png",
            price_cents=7999,
            categories=["shoes", "casual", "sports"],
            stock_quantity=45,
        ),
        store_pb2.Product(
            id="shoes-002",
            name="Black Running Shoes",
            description="High-performance running shoes",
            picture=
            "https://pngimg.com/uploads/men_shoes/men_shoes_PNG7476.png",
            price_cents=8999,
            categories=["shoes", "sports", "athletic"],
            stock_quantity=5,
        ),
        store_pb2.Product(
            id="shoes-003",
            name="Brown Leather Boots",
            description="Rugged brown leather boots",
            picture=
            "https://pngimg.com/uploads/men_shoes/men_shoes_PNG7476.png",
            price_cents=12000,
            categories=["shoes", "boots", "casual"],
            stock_quantity=18,
        ),
        store_pb2.Product(
            id="shoes-004",
            name="Blue Canvas Shoes",
            description="Lightweight blue canvas shoes",
            picture=
            "https://pngimg.com/uploads/men_shoes/men_shoes_PNG7476.png",
            price_cents=5500,
            categories=["shoes", "casual", "summer"],
            stock_quantity=28,
        ),
        # Jackets
        store_pb2.Product(
            id="jacket-001",
            name="Black Leather Jacket",
            description="Classic black leather jacket",
            picture="https://pngimg.com/uploads/jacket/jacket_PNG8047.png",
            price_cents=14999,
            categories=["jackets", "outerwear", "casual"],
            stock_quantity=12,
        ),
        store_pb2.Product(
            id="jacket-002",
            name="Navy Windbreaker",
            description="Lightweight navy windbreaker",
            picture="https://pngimg.com/uploads/jacket/jacket_PNG8036.png",
            price_cents=6999,
            categories=["jackets", "outerwear", "sports"],
            stock_quantity=22,
        ),
        store_pb2.Product(
            id="jacket-003",
            name="Gray Hoodie",
            description="Cozy gray hooded sweatshirt",
            picture="https://pngimg.com/uploads/jacket/jacket_PNG8039.png",
            price_cents=5499,
            categories=["jackets", "hoodies", "casual"],
            stock_quantity=35,
        ),
        store_pb2.Product(
            id="jacket-004",
            name="Denim Jacket",
            description="Classic blue denim jacket",
            picture="https://pngimg.com/uploads/jacket/jacket_PNG8049.png",
            price_cents=7999,
            categories=["jackets", "denim", "casual"],
            stock_quantity=18,
        ),
        # Accessories
        store_pb2.Product(
            id="acc-001",
            name="Black Leather Belt",
            description="Premium black leather belt",
            picture="https://pngimg.com/uploads/belt/belt_PNG5969.png",
            price_cents=3500,
            categories=["accessories", "belts", "leather"],
            stock_quantity=40,
        ),
        store_pb2.Product(
            id="acc-002",
            name="Blue Baseball Cap",
            description="Casual blue baseball cap",
            picture="https://pngimg.com/uploads/cap/cap_PNG5674.png",
            price_cents=2500,
            categories=["accessories", "hats", "casual"],
            stock_quantity=50,
        ),
        store_pb2.Product(
            id="acc-003",
            name="Sunglasses",
            description="Stylish black sunglasses",
            picture=
            "https://pngimg.com/uploads/sunglasses/sunglasses_PNG142.png",
            price_cents=4599,
            categories=["accessories", "sunglasses", "summer"],
            stock_quantity=8,
        ),
        store_pb2.Product(
            id="acc-004",
            name="Wool Scarf",
            description="Warm gray wool scarf",
            picture="https://pngimg.com/uploads/scarf/scarf_PNG27.png",
            price_cents=3200,
            categories=["accessories", "scarves", "winter"],
            stock_quantity=20,
        ),
        store_pb2.Product(
            id="acc-005",
            name="Leather Watch",
            description="Brown leather strap watch",
            picture="https://pngimg.com/uploads/watch/watch_PNG9870.png",
            price_cents=9500,
            categories=["accessories", "watches", "formal"],
            stock_quantity=15,
        ),
        # Bags
        store_pb2.Product(
            id="bag-001",
            name="Black Backpack",
            description="Spacious black backpack",
            picture="https://pngimg.com/uploads/backpack/backpack_PNG7.png",
            price_cents=6500,
            categories=["bags", "backpacks", "casual"],
            stock_quantity=30,
        ),
        store_pb2.Product(
            id="bag-002",
            name="Brown Messenger Bag",
            description="Vintage brown messenger bag",
            picture="https://pngimg.com/uploads/bag/bag_PNG6399.png",
            price_cents=8500,
            categories=["bags", "messenger", "business"],
            stock_quantity=12,
        ),
        store_pb2.Product(
            id="bag-003",
            name="Gym Duffel Bag",
            description="Large gym duffel bag",
            picture="https://pngimg.com/uploads/bag/bag_PNG6399.png",
            price_cents=4899,
            categories=["bags", "sports", "gym"],
            stock_quantity=25,
        ),
    ]

    # Add each product to the catalog
    for product in products:
        await ProductCatalog.ref(catalog_id).idempotently(
            f"add-product-{product.id}"
        ).AddProduct(
            context,
            catalog_id=catalog_id,
            product=product,
        )

    await Cart.create(
        context,
        "default-cart",
    )

    await Orders.create(
        context,
        "default-orders",
    )


async def main():
    # Reboot application that runs everything necessary for `DurableMCP`.
    await mcp.application(
        servicers=[
            CartServicer,
            ProductCatalogServicer,
            OrdersServicer,
        ],
        initialize=initialize,
    ).run()


if __name__ == '__main__':
    asyncio.run(main())
