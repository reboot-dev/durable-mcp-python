import uuid
from store.v1 import store_pb2
from store.v1.store_rbt import Shipping
from reboot.aio.auth.authorizers import allow
from reboot.aio.contexts import ReaderContext, WriterContext


class ShippingServicer(Shipping.Servicer):
    def authorizer(self):
        return allow()

    async def get_quote(
        self,
        context: ReaderContext,
        request: store_pb2.GetQuoteRequest,
    ) -> store_pb2.GetQuoteResponse:
        # Calculate shipping cost based on number of items and destination
        # This is a simple mock implementation
        num_items = sum(item.quantity for item in request.items)

        # Generate mock shipping quotes (amounts in cents)
        quotes = [
            store_pb2.ShippingQuote(
                id=str(uuid.uuid4()),
                cost_cents=(5 + num_items * 2) * 100,  # e.g., $5.00 + $2.00 per item
                carrier="Standard Shipping",
                estimated_days=5
            ),
            store_pb2.ShippingQuote(
                id=str(uuid.uuid4()),
                cost_cents=(10 + num_items * 3) * 100,  # e.g., $10.00 + $3.00 per item
                carrier="Express Shipping",
                estimated_days=2
            ),
            store_pb2.ShippingQuote(
                id=str(uuid.uuid4()),
                cost_cents=(20 + num_items * 5) * 100,  # e.g., $20.00 + $5.00 per item
                carrier="Overnight Shipping",
                estimated_days=1
            ),
        ]

        # Store quotes in state
        self.state.quotes.extend(quotes)

        return store_pb2.GetQuoteResponse(quotes=quotes)

    async def ship_order(
        self,
        context: WriterContext,
        request: store_pb2.ShipOrderRequest,
    ) -> store_pb2.ShipOrderResponse:
        # Find the selected quote
        selected_quote = None
        for quote in self.state.quotes:
            if quote.id == request.quote_id:
                selected_quote = quote
                break

        if not selected_quote:
            raise ValueError(f"Quote with ID '{request.quote_id}' not found")

        # Create a shipment
        tracking_number = f"TRK-{uuid.uuid4().hex[:12].upper()}"
        shipment = store_pb2.Shipment(
            tracking_number=tracking_number,
            carrier=selected_quote.carrier,
            status="In Transit",
            address=request.address
        )

        self.state.shipments.append(shipment)

        return store_pb2.ShipOrderResponse(tracking_number=tracking_number)
