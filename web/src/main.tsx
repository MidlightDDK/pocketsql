import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { loadModel, STUB } from "./llm/store";
import { startServiceWorker } from "./pwa";
import "./index.css";

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

startServiceWorker();
// The model downloads right away (examples cover the wait), unless Data Saver is on.
const saveData = (navigator as { connection?: { saveData?: boolean } })
  .connection?.saveData;
if (!saveData) void loadModel();

// The end-to-end tests (stub mode only) compare the in-browser schema reader
// with training's serializer.
if (STUB) {
  void import("./db").then(({ schemaText }) => {
    (window as { __pocketsql?: unknown }).__pocketsql = { schemaText };
  });
}
