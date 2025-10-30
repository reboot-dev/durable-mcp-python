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
