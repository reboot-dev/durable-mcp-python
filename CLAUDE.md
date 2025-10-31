# Reboot API Conventions

When working with Reboot protobuf files:

1. **State types** must use `option (rbt.v1alpha1.state) = {};`
2. **State fields** should contain all properties directly (e.g., `repeated CartItem items`)
3. **No lookup_by annotations** - remove `[(rbt.v1alpha1.constructor).lookup_by = true]`
4. **Individual response messages** - each RPC should have its own response message (e.g., `AddItemResponse`, `UpdateItemResponse`) instead of sharing a generic `Empty` message for API evolution

See https://github.com/reboot-dev/reboot-boutique/blob/main/api/boutique/v1/demo.proto for reference.

## Calling Reboot Methods

In Reboot, **do not pass gRPC request objects**. Instead, pass the context and the fields of the request directly:

```python
# ❌ DO NOT DO THIS:
request = MyRequest(field1=value1, field2=value2)
my_state.MyMethod(request)

# ❌ ALSO DO NOT DO THIS:
my_state.MyMethod(context, request)

# ✅ DO THIS:
my_state.MyMethod(context, field1=value1, field2=value2)
```

Example with ProductCatalog:
```python
# ❌ Wrong:
await ProductCatalog.ref(catalog_id).AddProduct(
    store_pb2.AddProductRequest(catalog_id=catalog_id, product=product)
)

# ✅ Correct:
await ProductCatalog.ref(catalog_id).AddProduct(
    context,
    catalog_id=catalog_id,
    product=product,
)
```

## DurableMCP Tools with Context

When defining MCP tools that need to call Reboot methods, the `context` parameter must be defined as the **last parameter** with type `DurableContext`:

```python
from reboot.mcp.server import DurableContext

@mcp.tool()
async def add_item_to_cart(product_id: str, quantity: int = 1, context: DurableContext) -> str:
    """Add an item to the shopping cart."""
    cart_id = "default-cart"

    await Cart.ref(cart_id).add_item(
        context,
        item=store_pb2.CartItem(product_id=product_id, quantity=quantity),
        catalog_id="default-catalog",
    )

    return f"Added {quantity}x product to cart"
```

Key points:
- `DurableContext` must be imported from `reboot.mcp.server` (NOT from `reboot.aio.contexts`).
- Context parameter must be typed as `DurableContext`.
- Context is always the **last parameter** in the tool function signature.
- The context is automatically provided by the MCP framework when the tool is called.

## Implementing Reboot Servicers

When implementing servicer methods for Reboot state machines, **all methods must accept three parameters**:

1. `self` - the servicer instance
2. `context` - `WriterContext` for writers/constructors, `ReaderContext` for readers
3. `request` - the request message object (even if empty)

```python
# ✅ Correct servicer method signature:
async def Create(
    self,
    context: WriterContext,
    request: store_pb2.CreateOrdersRequest,
) -> store_pb2.CreateOrdersResponse:
    # Initialize state.
    self.state.orders[:] = []
    return store_pb2.CreateOrdersResponse()

async def add_order(
    self,
    context: WriterContext,
    request: store_pb2.AddOrderRequest,
) -> store_pb2.AddOrderResponse:
    # Access fields from request object.
    order = request.order
    self.state.orders.append(order)
    return store_pb2.AddOrderResponse()

async def get_orders(
    self,
    context: ReaderContext,
    request: store_pb2.GetOrdersRequest,
) -> store_pb2.GetOrdersResponse:
    return store_pb2.GetOrdersResponse(orders=list(self.state.orders))
```

Key points:
- **Always** include the `request` parameter, even if the request message is empty.
- Access request fields using `request.field_name`.
- Constructor methods are capitalized (e.g., `Create`).
- Non-constructor methods use snake_case (e.g., `add_order`).

## Code Style

- Always end comments with a period.
