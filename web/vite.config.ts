import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const api = process.env.FW_API ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: api, changeOrigin: false },
      '/files': { target: api, changeOrigin: false },
    },
    fs: { allow: ['..'] },
  },
  worker: { format: 'es' },
  optimizeDeps: { exclude: ['manifold-3d', '@formwright/geom'] },
  build: { target: 'es2022', chunkSizeWarningLimit: 1500 },
});
