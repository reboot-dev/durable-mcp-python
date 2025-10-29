from store.v1 import store_pb2
from store.v1.store_rbt import ProductCatalog
from reboot.aio.auth.authorizers import allow
from reboot.aio.contexts import ReaderContext, WriterContext


class ProductCatalogServicer(ProductCatalog.Servicer):
    def authorizer(self):
        return allow()

    async def list_products(
        self,
        context: ReaderContext,
        request: store_pb2.ListProductsRequest,
    ) -> store_pb2.ListProductsResponse:
        return store_pb2.ListProductsResponse(products=self.state.products)

    async def get_product(
        self,
        context: ReaderContext,
        request: store_pb2.GetProductRequest,
    ) -> store_pb2.Product:
        for product in self.state.products:
            if request.product_id == product.id:
                return product

        raise ValueError(f"No product found with ID '{request.product_id}'")

    async def search_products(
        self,
        context: ReaderContext,
        request: store_pb2.SearchProductsRequest,
    ) -> store_pb2.SearchProductsResponse:
        query_lower = request.query.lower()
        matching_products = []

        for product in self.state.products:
            # Search in name, description, and categories
            if (query_lower in product.name.lower() or
                query_lower in product.description.lower() or
                any(query_lower in category.lower() for category in product.categories)):
                matching_products.append(product)

        return store_pb2.SearchProductsResponse(products=matching_products)

    async def add_product(
        self,
        context: WriterContext,
        request: store_pb2.AddProductRequest,
    ) -> store_pb2.AddProductResponse:
        # Check if product with same ID already exists
        for product in self.state.products:
            if product.id == request.product.id:
                raise ValueError(f"Product with ID '{request.product.id}' already exists")

        self.state.products.append(request.product)

        return store_pb2.AddProductResponse()

    async def update_product(
        self,
        context: WriterContext,
        request: store_pb2.UpdateProductRequest,
    ) -> store_pb2.UpdateProductResponse:
        for i, product in enumerate(self.state.products):
            if product.id == request.product.id:
                self.state.products[i].CopyFrom(request.product)
                return store_pb2.UpdateProductResponse()

        raise ValueError(f"No product found with ID '{request.product.id}'")
