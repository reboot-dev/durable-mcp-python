import { BrowserRouter as Router, Routes, Route, Link } from "react-router-dom";
import Products from "./components/Products";
import Cart from "./components/Cart";

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/products" element={<Products />} />
        <Route path="/cart" element={<Cart />} />
        <Route
          path="/"
          element={
            <div className="flex items-center justify-center min-h-screen bg-gray-50">
              <div className="text-center">
                <h1 className="text-4xl font-bold text-gray-900 mb-4">
                  Welcome to the Store
                </h1>
                <p className="text-gray-600">
                  Navigate to <Link to="/products">/products</Link> or{" "}
                  <Link to="/cart">/cart</Link>
                </p>
              </div>
            </div>
          }
        />
      </Routes>
    </Router>
  );
}

export default App;
