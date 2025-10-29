import argparse
import asyncio
from mcp.server.fastmcp import FastMCP
from mcp_ui_server import create_ui_resource
from mcp_ui_server.core import UIResource
from reboot.mcp.server import DurableMCP
from reboot.aio.applications import Application
from store.api.store.v1.store_rbt import OrderServicer, ShippingServicer
from store.backend.src.cart import CartServicer
from store.backend.src.checkout import CheckoutServicer
from store.backend.src.product import ProductCatalogServicer

mcp = DurableMCP(path="/mcp", log_level="DEBUG")


@mcp.tool()
def show_products(search_query: str = "") -> list[UIResource]:
    """Display products matching the search query in an interactive UI.

    Args:
        search_query: The search term to filter products (e.g., 'shirts', 'pants', 'blue')
    """
    import urllib.parse

    # URL encode the search query
    encoded_query = urllib.parse.quote(search_query)
    iframe_url = f"http://localhost:3001/products?query={encoded_query}" if search_query else "http://localhost:3001/products"

    ui_resource = create_ui_resource(
        {
            "uri":
                f"ui://products/search/{encoded_query}"
                if search_query else "ui://products/all",
            "content": {
                "type": "externalUrl",
                "iframeUrl": iframe_url
            },
            "encoding":
                "text"
        }
    )
    return [ui_resource]


@mcp.tool()
def show_cart(cart_id: str) -> list[UIResource]:
    """Display the shopping cart in an interactive UI.

    Args:
        cart_id: The ID of the cart to display
    """
    import urllib.parse

    # URL encode the cart ID
    encoded_cart_id = urllib.parse.quote(cart_id)
    iframe_url = f"http://localhost:3001/cart?cartId={encoded_cart_id}"

    ui_resource = create_ui_resource(
        {
            "uri": f"ui://cart/{encoded_cart_id}",
            "content": {
                "type": "externalUrl",
                "iframeUrl": iframe_url
            },
            "encoding": "text"
        }
    )
    return [ui_resource]


async def main():
    # Reboot application that runs everything necessary for `DurableMCP`.
    await mcp.application(
        servicers=[
            CartServicer,
            CheckoutServicer,
            ProductCatalogServicer,
            OrderServicer,
            ShippingServicer,
        ]
    ).run()


if __name__ == '__main__':
    asyncio.run(main())
