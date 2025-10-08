import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";
import { RebootClientProvider } from "@reboot-dev/reboot-react";

const url = "http://localhost:9991";

createRoot(document.getElementById("root")!).render(
  <RebootClientProvider url={url}>
    <App />
  </RebootClientProvider>
);
