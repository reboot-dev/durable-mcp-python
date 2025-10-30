import time
from store.v1 import store_pb2
from store.v1.store_rbt import Cart, ProductCatalog
from reboot.aio.auth.authorizers import allow
from reboot.aio.contexts import ReaderContext, WriterContext


class CartServicer(Cart.Servicer):

    def authorizer(self):
        return allow()

    async def create(
        self,
        context: WriterContext,
        request: store_pb2.CreateCartRequest,
    ) -> store_pb2.CreateCartResponse:
        # Initialize the cart with the user_id
        return store_pb2.CreateCartResponse()

    async def add_item(
        self,
        context: WriterContext,
        request: store_pb2.AddItemRequest,
    ) -> store_pb2.AddItemResponse:

        # Fetch product information from catalog
        catalog_id = request.catalog_id or "default-catalog"
        try:
            product = await ProductCatalog.ref(catalog_id).get_product(
                context,
                catalog_id=catalog_id,
                product_id=request.item.product_id,
            )
        except Exception as e:
            raise ValueError(
                f"Failed to fetch product {request.item.product_id}: {str(e)}"
            )

        # Check if item already exists
        for existing_item in self.state.items:
            if existing_item.product_id == request.item.product_id:
                existing_item.quantity += request.item.quantity
                return store_pb2.AddItemResponse()

        # Add new item with timestamp and product info
        new_item = store_pb2.CartItem(
            product_id=request.item.product_id,
            quantity=request.item.quantity,
            added_at=int(time.time() * 1000),
            name=product.name,
            price_cents=product.price_cents,
            picture=product.picture,
        )
        self.state.items.append(new_item)

        return store_pb2.AddItemResponse()

    async def get_items(
        self,
        context: ReaderContext,
        request: store_pb2.GetItemsRequest,
    ) -> store_pb2.GetItemsResponse:
        return store_pb2.GetItemsResponse(items=self.state.items)

    async def update_item_quantity(
        self,
        context: WriterContext,
        request: store_pb2.UpdateItemQuantityRequest,
    ) -> store_pb2.UpdateItemQuantityResponse:
        for item in self.state.items:
            if item.product_id == request.product_id:
                item.quantity = request.quantity
                break

        return store_pb2.UpdateItemQuantityResponse()

    async def remove_item(
        self,
        context: WriterContext,
        request: store_pb2.RemoveItemRequest,
    ) -> store_pb2.RemoveItemResponse:
        new_items = [
            item for item in self.state.items
            if item.product_id != request.product_id
        ]
        del self.state.items[:]
        self.state.items.extend(new_items)

        return store_pb2.RemoveItemResponse()

    async def empty_cart(
        self,
        context: WriterContext,
        request: store_pb2.EmptyCartRequest,
    ) -> store_pb2.EmptyCartResponse:
        self.state.items = []

        return store_pb2.EmptyCartResponse()
