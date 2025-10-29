import time
import uuid
from store.v1 import store_pb2
from store.v1.store_rbt import Checkout, Cart, Order
from reboot.aio.auth.authorizers import allow
from reboot.aio.contexts import ReaderContext, TransactionContext, WriterContext


class CheckoutServicer(Checkout.Servicer):
    def authorizer(self):
        return allow()

    async def place_order(
        self,
        context: TransactionContext,
        request: store_pb2.PlaceOrderRequest,
    ) -> store_pb2.PlaceOrderResponse:
        # Get cart items
        cart_ref = Cart.lookup(request.user_id)
        cart_response = await cart_ref.get_items(
            context,
            store_pb2.GetItemsRequest(user_id=request.user_id)
        )

        if not cart_response.items:
            raise ValueError("Cart is empty")

        # Get shipping quote cost
        # In a real implementation, we would fetch the quote from the shipping service
        # For now, use a mock value (e.g., $10.00 = 1000 cents)
        shipping_cost_cents = 1000

        # Create order ID
        order_id = str(uuid.uuid4())

        # Create order items from cart items
        order_items = [
            store_pb2.OrderItem(
                item=item,
                cost_cents=0  # Would need to look up from product catalog
            )
            for item in cart_response.items
        ]

        # Create the order
        order = store_pb2.Order(
            order_id=order_id,
            user_id=request.user_id,
            items=order_items,
            shipping_cost_cents=shipping_cost_cents,
            shipping_address=request.shipping_address,
            status="PENDING",
            created_at=int(time.time() * 1000),
            tracking_number=""
        )

        # Store order in checkout state
        self.state.completed_orders.append(order)

        # Empty the cart
        await cart_ref.empty_cart(
            context,
            store_pb2.EmptyCartRequest(user_id=request.user_id)
        )

        return store_pb2.PlaceOrderResponse(order=order)

    async def get_checkout_session(
        self,
        context: ReaderContext,
        request: store_pb2.GetCheckoutSessionRequest,
    ) -> store_pb2.CheckoutSession:
        # Return a mock checkout session
        # In a real implementation, this would aggregate cart items and calculate totals
        return store_pb2.CheckoutSession(
            session_id=str(uuid.uuid4()),
            user_id="",
            items=[],
            subtotal_cents=0,
            shipping_cost_cents=0,
            total_cents=0,
        )
