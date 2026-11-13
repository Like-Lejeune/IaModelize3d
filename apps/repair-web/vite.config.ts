import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The IaModelize3d API (server/, uvicorn on 8400) serves /api and the uploaded or generated files under /files.
// In development Vite proxies both, so the session cookie stays on this origin.
const API = process.env.FW_API_URL ?? "http://127.0.0.1:8400";

export default defineConfig({
  plugins: [react()],
  // the geometry kernel (packages/geom, TypeScript sources and the manifold WASM) lives outside this app
  worker: { format: "es" },
  optimizeDeps: { exclude: ["@iamodelize3d/geom", "manifold-3d"] },
  server: {
    port: 5410,
    fs: { allow: ["../.."] },
    proxy: {
      "/api": { target: API, changeOrigin: false },
      "/files": { target: API, changeOrigin: false },
    },
  },
});
