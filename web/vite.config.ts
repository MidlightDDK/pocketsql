import { readFileSync } from "node:fs";
import { getJsDelivrBundles } from "@duckdb/duckdb-wasm";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";
import { VitePWA } from "vite-plugin-pwa";

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

/** The production headers (public/_headers has one `/*` block), so `vite preview` serves the build with the real CSP. */
function productionHeaders(): Record<string, string> {
  const text = readFileSync(
    new URL("public/_headers", import.meta.url),
    "utf8",
  );
  return Object.fromEntries(
    text.split(/\r?\n/).flatMap((line) => {
      const m = /^\s+([\w-]+):\s*(.+)$/.exec(line);
      return m ? [[m[1], m[2]]] : [];
    }),
  );
}

// Every browser with WebAssembly exceptions (all current ones) gets the "eh" bundle;
// its two files are precached so SQL runs offline from the first visit.
const duckdbEh = getJsDelivrBundles().eh;
if (!duckdbEh) throw new Error("no DuckDB-WASM eh bundle");

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    dropOrtWasm,
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: null,
      manifest: {
        name: "PocketSQL",
        short_name: "PocketSQL",
        description:
          "A small fine-tuned text-to-SQL model running offline in your browser.",
        theme_color: "#0f766e",
        background_color: "#ffffff",
        display: "standalone",
        icons: [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml" }],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,json,duckdb}"],
        globIgnores: ["spike.html", "**/spike-*.js"],
        maximumFileSizeToCacheInBytes: 4 * 2 ** 20,
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [/^\/api\//, /^\/spike/],
        additionalManifestEntries: [
          duckdbEh.mainModule,
          duckdbEh.mainWorker,
        ].map(
          // Versioned URLs, so no revision hash is needed.
          (url) => ({ url, revision: null }),
        ),
        runtimeCaching: [
          {
            // ONNX Runtime files (Transformers.js also caches them) and any other
            // pinned npm file; the DuckDB extension repo for Parquet.
            urlPattern: ({ url }) =>
              url.origin === "https://cdn.jsdelivr.net" ||
              url.origin === "https://extensions.duckdb.org",
            handler: "CacheFirst",
            options: {
              cacheName: "cdn",
              expiration: { maxEntries: 40 },
              cacheableResponse: { statuses: [200] },
            },
          },
        ],
      },
    }),
  ],
  // spike.html: the browser speed check (loads the released model, times 3 queries).
  build: { rollupOptions: { input: ["index.html", "spike.html"] } },
  preview: { headers: productionHeaders() },
  server: {
    // `pnpm dev` runs `wrangler dev` (worker/) on its default port alongside Vite.
    // The Worker accepts same-origin POSTs only, so present as its origin.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8787",
        changeOrigin: true,
        headers: { origin: "http://127.0.0.1:8787" },
      },
    },
  },
});
