import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Formwright API (server/, uvicorn on 8400) serves /api and the uploaded or generated files under /files.
// In development Vite proxies both, so the session cookie stays on this origin.
const API = process.env.FW_API_URL ?? "http://127.0.0.1:8400";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5410,
    proxy: {
      "/api": { target: API, changeOrigin: false },
      "/files": { target: API, changeOrigin: false },
    },
  },
});
