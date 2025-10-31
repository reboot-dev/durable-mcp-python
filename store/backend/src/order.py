import time
from store.v1 import store_pb2
from store.v1.store_rbt import Orders
from reboot.aio.auth.authorizers import allow
from reboot.aio.contexts import ReaderContext, WriterContext


class OrdersServicer(Orders.Servicer):

    def authorizer(self):
        return allow()

    async def Create(
        self,
        context: WriterContext,
        request: store_pb2.CreateOrdersRequest,
    ) -> store_pb2.CreateOrdersResponse:
        # State is already initialized with empty orders list.
        return store_pb2.CreateOrdersResponse()

    async def add_order(
        self,
        context: WriterContext,
        request: store_pb2.AddOrderRequest,
    ) -> store_pb2.AddOrderResponse:
        # Add timestamp if not set.
        order = request.order
        if order.created_at == 0:
            order.created_at = int(time.time())

        # Add the order to the list.
        self.state.orders.append(order)

        return store_pb2.AddOrderResponse()

    async def get_orders(
        self,
        context: ReaderContext,
        request: store_pb2.GetOrdersRequest,
    ) -> store_pb2.GetOrdersResponse:
        # Return all orders.
        return store_pb2.GetOrdersResponse(orders=list(self.state.orders))
