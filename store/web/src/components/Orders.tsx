import { useOrders } from "../../api/store/v1/store_rbt_react";

const Orders = () => {
  const { useGetOrders } = useOrders({ id: "default-orders" });
  const { response } = useGetOrders();

  if (response === undefined) return <>Loading...</>;

  const orders = response.orders;

  const formatPrice = (cents: number) => {
    const dollars = cents / 100;
    return `$${dollars.toFixed(2)}`;
  };

  const formatDate = (timestamp: bigint) => {
    return new Date(Number(timestamp) * 1000).toLocaleDateString("en-US", {
      year: "numeric",
      month: "long",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  if (orders.length === 0) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <div className="text-4xl mb-2">📦</div>
          <h2 className="text-lg font-semibold text-gray-800 mb-2">No orders yet</h2>
          <p className="text-sm text-gray-600">Your order history will appear here</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-4">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-2xl font-bold text-gray-900 mb-6">Order History</h1>

        <div className="space-y-4">
          {orders.map((order) => (
            <div key={order.orderId} className="bg-white rounded shadow-sm p-4">
              <div className="flex justify-between items-start mb-4">
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">
                    Order #{order.orderId}
                  </h2>
                  <p className="text-sm text-gray-600">
                    {formatDate(order.createdAt)}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-lg font-bold text-gray-900">
                    {formatPrice(order.totalCents)}
                  </p>
                </div>
              </div>

              <div className="mb-4">
                <h3 className="text-sm font-semibold text-gray-700 mb-2">Items:</h3>
                <div className="space-y-2">
                  {order.items.map((item, index) => (
                    <div key={index} className="flex items-center gap-3">
                      <img
                        src={item.picture}
                        alt={item.name}
                        className="w-12 h-12 object-cover rounded"
                      />
                      <div className="flex-1">
                        <p className="text-sm font-medium text-gray-900">{item.name}</p>
                        <p className="text-xs text-gray-600">Quantity: {item.quantity}</p>
                      </div>
                      <p className="text-sm font-semibold text-gray-900">
                        {formatPrice((item.priceCents || 0) * item.quantity)}
                      </p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="border-t border-gray-200 pt-3 space-y-1 text-sm">
                <div className="flex justify-between">
                  <span className="text-gray-600">Subtotal:</span>
                  <span className="text-gray-900">{formatPrice(order.subtotalCents)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-gray-600">Shipping:</span>
                  <span className="text-gray-900">{formatPrice(order.shippingCostCents)}</span>
                </div>
                <div className="flex justify-between font-semibold text-base">
                  <span className="text-gray-900">Total:</span>
                  <span className="text-gray-900">{formatPrice(order.totalCents)}</span>
                </div>
              </div>

              <div className="mt-4 pt-3 border-t border-gray-200 text-sm space-y-1">
                <div>
                  <span className="text-gray-600">Tracking Number: </span>
                  <span className="text-gray-900 font-mono text-xs">{order.trackingNumber}</span>
                </div>
                <div>
                  <span className="text-gray-600">Carrier: </span>
                  <span className="text-gray-900">{order.carrier}</span>
                </div>
                <div>
                  <span className="text-gray-600">Shipping Address: </span>
                  <span className="text-gray-900">
                    {order.shippingAddress?.streetAddress}, {order.shippingAddress?.city},{" "}
                    {order.shippingAddress?.state} {order.shippingAddress?.zipCode},{" "}
                    {order.shippingAddress?.country}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default Orders;
