import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// Transformers.js loads the ONNX Runtime wasm from jsDelivr (env.backends.onnx.wasm.wasmPaths
// defaults to cdn.jsdelivr.net/npm/onnxruntime-web@<version>/dist/). The copy Vite emits from
// onnxruntime-web's import.meta.url fallback is unused and exceeds the Workers 25 MiB asset limit.
const dropOrtWasm: Plugin = {
  name: "drop-ort-wasm",
  generateBundle(_, bundle) {
    for (const name of Object.keys(bundle)) {
      if (/ort-wasm[^/]*\.wasm$/.test(name)) delete bundle[name];
    }
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss(), dropOrtWasm],
  // spike.html: the browser check page (loads the released model, times 3 queries).
  build: { rollupOptions: { input: ["index.html", "spike.html"] } },
  server: {
    // `pnpm dev` runs `wrangler dev` (worker/) on its default port alongside Vite.
    proxy: { "/api": "http://127.0.0.1:8787" },
  },
});
