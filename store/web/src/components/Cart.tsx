import { useCart } from "../../api/store/v1/store_rbt_react";

const Cart = () => {
  const { useGetItems, removeItem, updateItemQuantity } = useCart({
    id: "default-cart",
  });

  const { response } = useGetItems();
  console.log(response);

  if (response === undefined) return <>Loading...</>;

  const formatPrice = (priceCents?: number) => {
    if (!priceCents) return "$0.00";
    const dollars = priceCents / 100;
    return `$${dollars.toFixed(2)}`;
  };

  const calculateTotal = () => {
    return (
      response.items.reduce((total, item) => {
        if (!item.priceCents) return total;
        const itemPriceCents = item.priceCents * item.quantity;
        return total + itemPriceCents;
      }, 0) / 100
    );
  };

  const updateQuantity = (productId: string, newQuantity: number) => {
    updateItemQuantity({ productId, quantity: newQuantity });
    if (window.parent) {
      window.parent.postMessage(
        {
          type: "prompt",
          payload: {
            prompt: `Update quantity of product ${productId} to ${newQuantity}`,
          },
        },
        "*"
      );
    }
  };

  const removeCartItem = (productId: string) => {
    removeItem({ productId });

    if (window.parent) {
      window.parent.postMessage(
        {
          type: "prompt",
          payload: {
            prompt: `Remove product ${productId} from my cart`,
          },
        },
        "*"
      );
    }
  };

  const checkout = () => {
    if (window.parent) {
      window.parent.postMessage(
        {
          type: "prompt",
          payload: {
            prompt: `Checkout process started.`,
          },
        },
        "*"
      );
    }
  };

  if (response.items.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <h2 className="text-sm font-bold text-gray-800 mb-1">
            Your cart is empty
          </h2>
          <p className="text-xs text-gray-600">
            Add some products to get started
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-2">
      <div className="max-w-2xl mx-auto">
        <h1 className="text-sm font-bold text-gray-900 mb-2">Shopping Cart</h1>

        <div className="bg-white rounded shadow-sm">
          <div className="divide-y divide-gray-200">
            {response.items.map((item) => (
              <div key={item.productId} className="p-2 flex items-center gap-2">
                {item.picture && (
                  <img
                    src={item.picture}
                    alt={item.name || item.productId}
                    className="w-12 h-16 object-cover rounded"
                  />
                )}

                <div className="flex-1 min-w-0">
                  <h3 className="text-xs font-semibold text-gray-900 line-clamp-1">
                    {item.name || item.productId}
                  </h3>
                  <p className="text-xs text-gray-600">
                    {formatPrice(item.priceCents)}
                  </p>
                  <button
                    onClick={() => removeCartItem(item.productId)}
                    className="text-xs text-red-600 hover:text-red-800 mt-0.5"
                  >
                    Remove
                  </button>
                </div>

                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() =>
                      updateQuantity(item.productId, item.quantity - 1)
                    }
                    className="w-5 h-5 flex items-center justify-center rounded-full bg-gray-200 hover:bg-gray-300 text-gray-800 text-xs font-bold"
                  >
                    −
                  </button>
                  <span className="w-5 text-center text-xs font-medium">
                    {item.quantity}
                  </span>
                  <button
                    onClick={() =>
                      updateQuantity(item.productId, item.quantity + 1)
                    }
                    className="w-5 h-5 flex items-center justify-center rounded-full bg-gray-200 hover:bg-gray-300 text-gray-800 text-xs font-bold"
                  >
                    +
                  </button>
                </div>

                <div className="text-right">
                  <p className="text-sm font-bold text-gray-900">
                    {formatPrice(
                      item.priceCents
                        ? item.priceCents * item.quantity
                        : undefined
                    )}
                  </p>
                </div>
              </div>
            ))}
          </div>

          <div className="border-t border-gray-200 p-2">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-semibold text-gray-900">
                Total:
              </span>
              <span className="text-base font-bold text-gray-900">
                ${calculateTotal().toFixed(2)}
              </span>
            </div>

            <button
              onClick={checkout}
              className="w-full bg-blue-600 hover:bg-blue-700 text-white py-1.5 rounded text-xs font-semibold transition-colors"
            >
              Checkout
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Cart;
