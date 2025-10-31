import { useSearchParams } from "react-router-dom";

const Order = () => {
  const [searchParams] = useSearchParams();
  const data = searchParams.get("data");

  if (!data) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <h2 className="text-sm font-bold text-gray-800 mb-1">
            No order found
          </h2>
        </div>
      </div>
    );
  }

  // Parse order data: orderId|lastFour|subtotalCents|shippingCents|totalCents|trackingNumber
  const [orderId, lastFour, subtotalCents, shippingCents, totalCents, trackingNumber] = data.split("|");

  const formatPrice = (cents: string) => {
    const dollars = parseInt(cents) / 100;
    return `$${dollars.toFixed(2)}`;
  };

  return (
    <div className="min-h-screen bg-gray-50 p-2">
      <div className="max-w-2xl mx-auto">
        <div className="bg-white rounded shadow-sm p-4">
          <div className="text-center mb-4">
            <div className="text-3xl mb-2">✓</div>
            <h1 className="text-lg font-bold text-gray-900 mb-1">
              Order Confirmed!
            </h1>
            <p className="text-xs text-gray-600">Order #{orderId}</p>
          </div>

          <div className="border-t border-b border-gray-200 py-3 my-3">
            <div className="flex justify-between text-sm mb-2">
              <span className="text-gray-600">Subtotal:</span>
              <span className="text-gray-900">{formatPrice(subtotalCents)}</span>
            </div>
            <div className="flex justify-between text-sm mb-2">
              <span className="text-gray-600">Shipping:</span>
              <span className="text-gray-900">{formatPrice(shippingCents)}</span>
            </div>
            <div className="flex justify-between text-base font-bold">
              <span className="text-gray-900">Total:</span>
              <span className="text-gray-900">{formatPrice(totalCents)}</span>
            </div>
          </div>

          <div className="space-y-2 text-sm">
            <div>
              <span className="text-gray-600">Payment Method:</span>
              <span className="ml-2 text-gray-900">
                •••• •••• •••• {lastFour}
              </span>
            </div>
            <div>
              <span className="text-gray-600">Tracking Number:</span>
              <span className="ml-2 text-gray-900 font-mono text-xs">
                {trackingNumber}
              </span>
            </div>
          </div>

          <div className="mt-4 p-3 bg-blue-50 rounded">
            <p className="text-xs text-blue-800">
              Your order has been confirmed and will be shipped soon. You'll receive a shipping notification once your package is on its way.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Order;
