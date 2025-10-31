import { useSearchParams } from "react-router-dom";
import { useProductCatalog } from "../../api/store/v1/store_rbt_react";

interface Product {
  id: string;
  name: string;
  description: string;
  picture: string;
  priceCents: number;
  categories: string[];
  stockQuantity: number;
}

const Products = () => {
  const [searchParams] = useSearchParams();
  const query = searchParams.get("query") || undefined;

  const { useListProducts } = useProductCatalog({ id: "default-catalog" });
  const { response } = useListProducts();

  if (response === undefined) return <>Loading...</>;
  const products = response.products;

  const filteredProducts = query
    ? products.filter((p) => {
        const queryTerms = query.toLowerCase().split(/\s+/);
        return queryTerms.some(
          (term) =>
            p.name.toLowerCase().includes(term) ||
            p.description.toLowerCase().includes(term) ||
            p.categories.some((cat) => cat.toLowerCase().includes(term))
        );
      })
    : products;

  const formatPrice = (priceCents: number) => {
    const dollars = priceCents / 100;
    return `$${dollars.toFixed(2)}`;
  };

  const addToCart = (product: Product) => {
    if (window.parent) {
      window.parent.postMessage(
        {
          type: "prompt",
          payload: {
            prompt: `Add one ${product.name} to my cart (product ID: ${product.id})`,
          },
        },
        "*"
      );
    }
  };

  if (filteredProducts.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <h2 className="text-sm font-bold text-gray-800 mb-1">
            No products found
          </h2>
          <p className="text-xs text-gray-600">
            Try searching for something else
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-2">
      <div className="max-w-4xl mx-auto">
        {query && (
          <div className="mb-2">
            <h1 className="text-sm font-bold text-gray-900">
              "{query}" - {filteredProducts.length} items
            </h1>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {filteredProducts.map((product) => (
            <div
              key={product.id}
              className="bg-white rounded shadow-sm overflow-hidden hover:shadow-md transition-shadow flex h-32"
            >
              <img
                src={product.picture}
                alt={product.name}
                className="w-32 h-full object-cover flex-none"
              />
              <div className="p-2 flex-1 flex flex-col justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-gray-900 mb-1 line-clamp-1">
                    {product.name}
                  </h3>
                  <p className="text-xs text-gray-600 mb-2 line-clamp-2">
                    {product.description}
                  </p>
                </div>

                <div className="flex items-end justify-between gap-2">
                  <div>
                    <span className="text-sm font-bold text-gray-900">
                      {formatPrice(product.priceCents)}
                    </span>
                    {product.stockQuantity > 0 &&
                      product.stockQuantity < 10 && (
                        <div className="text-xs text-orange-600">
                          {product.stockQuantity} left
                        </div>
                      )}
                  </div>

                  <button
                    onClick={() => addToCart(product)}
                    className="bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded text-xs font-medium transition-colors whitespace-nowrap"
                    disabled={product.stockQuantity === 0}
                  >
                    {product.stockQuantity > 0 ? "Add to Cart" : "Out of Stock"}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default Products;
