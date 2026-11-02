import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

const api = process.env.FW_API ?? 'http://localhost:8400';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    port: 5400,
    // not 'localhost': Node binds that to ::1 alone, Firefox tries 127.0.0.1 first and Windows takes ~2 s to refuse each
    // connection, so pages load slowly or lose modules. dev.ps1 -Lan (--host) still opens every interface.
    host: '127.0.0.1',
    proxy: {
      // xfwd: the API sees the visitor's address (per-IP limits), not this proxy's
      '/api': { target: api, changeOrigin: false, xfwd: true },
      '/files': { target: api, changeOrigin: false, xfwd: true },
    },
    // only the app, the geometry package and the hoisted workspace deps; never the repo's data/ or the key file
    fs: {
      allow: ['.', '../packages/geom', '../node_modules'],
      deny: ['.env', '.env.*', '*.{crt,pem}', '**/.git/**', '**/*.db', '**/*.db-*', '**/data/**'],
    },
  },
  worker: { format: 'es' },
  optimizeDeps: { exclude: ['manifold-3d', '@formwright/geom'] },
  build: { target: 'es2022', chunkSizeWarningLimit: 1500 },
});
