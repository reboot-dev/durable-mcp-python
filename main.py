import asyncio
import urllib.parse
from mcp_ui_server import create_ui_resource
from mcp_ui_server.core import UIResource
from reboot.aio.external import InitializeContext
from reboot.mcp.server import DurableMCP
from store.backend.src.cart import CartServicer
from store.backend.src.checkout import CheckoutServicer
from store.backend.src.order import OrderServicer
from store.backend.src.product import ProductCatalogServicer
from store.backend.src.shipping import ShippingServicer
from store.v1 import store_pb2
from store.v1.store_rbt import ProductCatalog, Cart

mcp = DurableMCP(path="/mcp", log_level="DEBUG")


@mcp.tool()
def show_products(search_query: str = "") -> list[UIResource]:
    """Display products matching the search query in an interactive UI.
    Toggle Sidebar
    
    

    Args:
        search_query: The search term to filter products (e.g., 'shirts', 'pants', 'blue')
    """
    # URL encode the search query
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
    """Display the shopping cart in an interactive UI.

    Args:
        cart_id: The ID of the cart to display
    """
    # URL encode the cart ID
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


async def main():
    # Reboot application that runs everything necessary for `DurableMCP`.
    await mcp.application(
        servicers=[
            CartServicer,
            CheckoutServicer,
            OrderServicer,
            ProductCatalogServicer,
            ShippingServicer,
        ],
        initialize=initialize,
    ).run()


if __name__ == '__main__':
    asyncio.run(main())
