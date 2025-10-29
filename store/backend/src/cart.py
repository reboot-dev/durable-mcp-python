import time
from store.v1 import store_pb2
from store.v1.store_rbt import Cart
from reboot.aio.auth.authorizers import allow
from reboot.aio.contexts import ReaderContext, WriterContext


class CartServicer(Cart.Servicer):
    def authorizer(self):
        return allow()

    async def add_item(
        self,
        context: WriterContext,
        request: store_pb2.AddItemRequest,
    ) -> store_pb2.AddItemResponse:
        # Set user_id if not already set
        if not self.state.user_id:
            self.state.user_id = request.user_id

        # Check if item already exists
        for item in self.state.items:
            if item.product_id == request.item.product_id:
                item.quantity += request.item.quantity
                return store_pb2.AddItemResponse()

        # Add new item with timestamp
        new_item = store_pb2.CartItem(
            product_id=request.item.product_id,
            quantity=request.item.quantity,
            added_at=int(time.time() * 1000)
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
        self.state.items[:] = [
            item for item in self.state.items
            if item.product_id != request.product_id
        ]

        return store_pb2.RemoveItemResponse()

    async def empty_cart(
        self,
        context: WriterContext,
        request: store_pb2.EmptyCartRequest,
    ) -> store_pb2.EmptyCartResponse:
        self.state.items[:] = []

        return store_pb2.EmptyCartResponse()
