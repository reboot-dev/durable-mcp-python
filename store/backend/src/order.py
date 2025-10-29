from store.v1 import store_pb2
from store.v1.store_rbt import Order
from reboot.aio.auth.authorizers import allow
from reboot.aio.contexts import ReaderContext, WriterContext


class OrderServicer(Order.Servicer):
    def authorizer(self):
        return allow()

    async def get_order(
        self,
        context: ReaderContext,
        request: store_pb2.GetOrderRequest,
    ) -> store_pb2.Order:
        # Return the current state as the order
        return store_pb2.Order(
            order_id=self.state.order_id,
            user_id=self.state.user_id,
            items=self.state.items,
            shipping_cost=self.state.shipping_cost,
            shipping_address=self.state.shipping_address,
            status=self.state.status,
            created_at=self.state.created_at,
            tracking_number=self.state.tracking_number,
        )

    async def list_orders(
        self,
        context: ReaderContext,
        request: store_pb2.ListOrdersRequest,
    ) -> store_pb2.ListOrdersResponse:
        # This method would typically query across multiple order instances
        # For now, return an empty list as this requires cross-state querying
        # which might be handled differently in Reboot
        return store_pb2.ListOrdersResponse(orders=[])

    async def update_order_status(
        self,
        context: WriterContext,
        request: store_pb2.UpdateOrderStatusRequest,
    ) -> store_pb2.UpdateOrderStatusResponse:
        # Update the order status
        self.state.status = request.status

        return store_pb2.UpdateOrderStatusResponse()
