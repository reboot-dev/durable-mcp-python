import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

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
  const [products, setProducts] = useState<Product[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Mock products for now - in production, this would fetch from your backend
    const mockProducts: Product[] = [
      // Shirts
      {
        id: "shirt-001",
        name: "Classic Blue Shirt",
        description: "A comfortable cotton shirt in classic blue",
        picture: "https://pngimg.com/uploads/tshirt/tshirt_PNG5437.png",
        priceCents: 2999,
        categories: ["shirts", "men", "casual"],
        stockQuantity: 50,
      },
      {
        id: "shirt-002",
        name: "White Dress Shirt",
        description: "Elegant white dress shirt for formal occasions",
        picture: "https://pngimg.com/uploads/tshirt/tshirt_PNG5447.png",
        priceCents: 3999,
        categories: ["shirts", "men", "formal"],
        stockQuantity: 30,
      },
      {
        id: "shirt-003",
        name: "Black Polo Shirt",
        description: "Sporty black polo shirt",
        picture: "https://pngimg.com/uploads/tshirt/tshirt_PNG5427.png",
        priceCents: 3499,
        categories: ["shirts", "men", "sports"],
        stockQuantity: 25,
      },
      {
        id: "shirt-004",
        name: "Red Flannel Shirt",
        description: "Cozy red flannel for casual wear",
        picture: "https://pngimg.com/uploads/tshirt/tshirt_PNG5437.png",
        priceCents: 4599,
        categories: ["shirts", "men", "casual"],
        stockQuantity: 20,
      },
      {
        id: "shirt-005",
        name: "Striped Button-Down",
        description: "Navy striped button-down shirt",
        picture: "https://pngimg.com/uploads/tshirt/tshirt_PNG5454.png",
        priceCents: 3899,
        categories: ["shirts", "men", "business"],
        stockQuantity: 15,
      },

      // Pants
      {
        id: "pants-001",
        name: "Denim Jeans",
        description: "Classic blue denim jeans",
        picture: "https://pngimg.com/uploads/jeans/jeans_PNG5763.png",
        priceCents: 4999,
        categories: ["pants", "men", "casual"],
        stockQuantity: 40,
      },
      {
        id: "pants-002",
        name: "Khaki Chinos",
        description: "Versatile khaki chinos",
        picture: "https://pngimg.com/uploads/jeans/jeans_PNG5763.png",
        priceCents: 4499,
        categories: ["pants", "men", "casual"],
        stockQuantity: 35,
      },
      {
        id: "pants-003",
        name: "Black Dress Pants",
        description: "Formal black dress pants",
        picture: "https://pngimg.com/uploads/jeans/jeans_PNG5763.png",
        priceCents: 5999,
        categories: ["pants", "men", "formal"],
        stockQuantity: 25,
      },
      {
        id: "pants-004",
        name: "Gray Joggers",
        description: "Comfortable gray joggers",
        picture: "https://pngimg.com/uploads/jeans/jeans_PNG5763.png",
        priceCents: 4299,
        categories: ["pants", "men", "sports"],
        stockQuantity: 30,
      },

      // Shoes
      {
        id: "shoes-001",
        name: "White Sneakers",
        description: "Classic white leather sneakers",
        picture: "https://pngimg.com/uploads/men_shoes/men_shoes_PNG7476.png",
        priceCents: 7999,
        categories: ["shoes", "casual", "sports"],
        stockQuantity: 45,
      },
      {
        id: "shoes-002",
        name: "Black Running Shoes",
        description: "High-performance running shoes",
        picture: "https://pngimg.com/uploads/men_shoes/men_shoes_PNG7476.png",
        priceCents: 8999,
        categories: ["shoes", "sports", "athletic"],
        stockQuantity: 5,
      },
      {
        id: "shoes-003",
        name: "Brown Leather Boots",
        description: "Rugged brown leather boots",
        picture: "https://pngimg.com/uploads/men_shoes/men_shoes_PNG7476.png",
        priceCents: 12000,
        categories: ["shoes", "boots", "casual"],
        stockQuantity: 18,
      },
      {
        id: "shoes-004",
        name: "Blue Canvas Shoes",
        description: "Lightweight blue canvas shoes",
        picture: "https://pngimg.com/uploads/men_shoes/men_shoes_PNG7476.png",
        priceCents: 5500,
        categories: ["shoes", "casual", "summer"],
        stockQuantity: 28,
      },

      // Jackets
      {
        id: "jacket-001",
        name: "Black Leather Jacket",
        description: "Classic black leather jacket",
        picture: "https://pngimg.com/uploads/jacket/jacket_PNG8047.png",
        priceCents: 14999,
        categories: ["jackets", "outerwear", "casual"],
        stockQuantity: 12,
      },
      {
        id: "jacket-002",
        name: "Navy Windbreaker",
        description: "Lightweight navy windbreaker",
        picture: "https://pngimg.com/uploads/jacket/jacket_PNG8036.png",
        priceCents: 6999,
        categories: ["jackets", "outerwear", "sports"],
        stockQuantity: 22,
      },
      {
        id: "jacket-003",
        name: "Gray Hoodie",
        description: "Cozy gray hooded sweatshirt",
        picture: "https://pngimg.com/uploads/jacket/jacket_PNG8039.png",
        priceCents: 5499,
        categories: ["jackets", "hoodies", "casual"],
        stockQuantity: 35,
      },
      {
        id: "jacket-004",
        name: "Denim Jacket",
        description: "Classic blue denim jacket",
        picture: "https://pngimg.com/uploads/jacket/jacket_PNG8049.png",
        priceCents: 7999,
        categories: ["jackets", "denim", "casual"],
        stockQuantity: 18,
      },

      // Accessories
      {
        id: "acc-001",
        name: "Black Leather Belt",
        description: "Premium black leather belt",
        picture: "https://pngimg.com/uploads/belt/belt_PNG5969.png",
        priceCents: 3500,
        categories: ["accessories", "belts", "leather"],
        stockQuantity: 40,
      },
      {
        id: "acc-002",
        name: "Blue Baseball Cap",
        description: "Casual blue baseball cap",
        picture: "https://pngimg.com/uploads/cap/cap_PNG5674.png",
        priceCents: 2500,
        categories: ["accessories", "hats", "casual"],
        stockQuantity: 50,
      },
      {
        id: "acc-003",
        name: "Sunglasses",
        description: "Stylish black sunglasses",
        picture: "https://pngimg.com/uploads/sunglasses/sunglasses_PNG142.png",
        priceCents: 4599,
        categories: ["accessories", "sunglasses", "summer"],
        stockQuantity: 8,
      },
      {
        id: "acc-004",
        name: "Wool Scarf",
        description: "Warm gray wool scarf",
        picture: "https://pngimg.com/uploads/scarf/scarf_PNG27.png",
        priceCents: 3200,
        categories: ["accessories", "scarves", "winter"],
        stockQuantity: 20,
      },
      {
        id: "acc-005",
        name: "Leather Watch",
        description: "Brown leather strap watch",
        picture: "https://pngimg.com/uploads/watch/watch_PNG9870.png",
        priceCents: 9500,
        categories: ["accessories", "watches", "formal"],
        stockQuantity: 15,
      },

      // Bags
      {
        id: "bag-001",
        name: "Black Backpack",
        description: "Spacious black backpack",
        picture: "https://pngimg.com/uploads/backpack/backpack_PNG7.png",
        priceCents: 6500,
        categories: ["bags", "backpacks", "casual"],
        stockQuantity: 30,
      },
      {
        id: "bag-002",
        name: "Brown Messenger Bag",
        description: "Vintage brown messenger bag",
        picture: "https://pngimg.com/uploads/bag/bag_PNG6399.png",
        priceCents: 8500,
        categories: ["bags", "messenger", "business"],
        stockQuantity: 12,
      },
      {
        id: "bag-003",
        name: "Gym Duffel Bag",
        description: "Large gym duffel bag",
        picture: "https://pngimg.com/uploads/bag/bag_PNG6399.png",
        priceCents: 4899,
        categories: ["bags", "sports", "gym"],
        stockQuantity: 25,
      },
    ];

    // Filter products based on query
    const filtered = query
      ? mockProducts.filter(
          (p) =>
            p.name.toLowerCase().includes(query.toLowerCase()) ||
            p.description.toLowerCase().includes(query.toLowerCase()) ||
            p.categories.some((cat) =>
              cat.toLowerCase().includes(query.toLowerCase())
            )
        )
      : mockProducts;

    setProducts(filtered);
    setLoading(false);
  }, [query]);

  const formatPrice = (priceCents: number) => {
    const dollars = priceCents / 100;
    return `$${dollars.toFixed(2)}`;
  };

  const addToCart = (product: Product) => {
    // Send intent back to parent iframe
    if (window.parent) {
      window.parent.postMessage(
        {
          type: "prompt",
          payload: {
            prompt: `One ${product.name} was added to my cart (product ID: ${product.id})`,
          },
        },
        "*"
      );
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-xs text-gray-600">Loading products...</div>
      </div>
    );
  }

  if (products.length === 0) {
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
              "{query}" - {products.length} items
            </h1>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {products.map((product) => (
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
