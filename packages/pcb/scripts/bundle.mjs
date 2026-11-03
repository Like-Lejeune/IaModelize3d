// node scripts/bundle.mjs -> dist/pcb-worker.mjs (the whole of tscircuit in one ~13 MB file), dist/svg-png.mjs and
// dist/resvg.wasm. The server runs only these, under --permission with read access to dist/, so neither the 770 MB
// node_modules nor the repo is reachable from the worker, and the container ships dist alone.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { build } from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dist = path.join(root, 'dist');
const require = createRequire(path.join(root, 'package.json'));
// emptied rather than removed: on Windows a running worker (its cwd is dist) keeps the folder itself from going
fs.mkdirSync(dist, { recursive: true });
for (const f of fs.readdirSync(dist)) fs.rmSync(path.join(dist, f), { recursive: true, force: true });

// circuit-json-to-gltf renders the board texture with the native @resvg/resvg-js, which cannot load under
// --permission; preview.mjs provides the same class on the wasm build.
const resvgShim = {
  name: 'resvg-wasm-shim',
  setup(b) {
    b.onResolve({ filter: /^@resvg\/resvg-js$/ }, () => ({ path: path.join(root, 'src', 'preview.mjs') }));
    // its browser path imports the wasm as a URL (Vite style); Node never takes it
    b.onResolve({ filter: /\.wasm\?url$/ }, (a) => ({ path: a.path, namespace: 'unused-browser-asset' }));
    b.onLoad({ filter: /.*/, namespace: 'unused-browser-asset' }, () => ({ contents: 'export default "";', loader: 'js' }));
  },
};

const common = {
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node22',
  legalComments: 'none',
  minify: true,
  keepNames: true, // some components are looked up by class name
  logLevel: 'warning',
  define: { 'process.env.NODE_ENV': '"production"' },
  // CommonJS dependencies call require() for node builtins
  banner: { js: "import { createRequire as __fwCreateRequire } from 'node:module'; const require = __fwCreateRequire(import.meta.url);" },
  // STEP model import is only reached with includeModels, which the previews never ask for
  external: ['occt-import-js'],
  plugins: [resvgShim],
};

const t0 = Date.now();
await build({ ...common, entryPoints: [path.join(root, 'src', 'worker.mjs')], outfile: path.join(dist, 'pcb-worker.mjs') });
await build({
  ...common,
  stdin: { contents: "import { pngMain } from './src/preview.mjs';\nawait pngMain();\n", resolveDir: root, sourcefile: 'svg-png-entry.mjs', loader: 'js' },
  outfile: path.join(dist, 'svg-png.mjs'),
  // the converters are lazy imports in preview.mjs and never run here
  external: [...common.external, 'circuit-to-svg', 'circuit-json-to-gltf'],
});
fs.copyFileSync(require.resolve('@resvg/resvg-wasm/index_bg.wasm'), path.join(dist, 'resvg.wasm'));
// the copper pour solver loads manifold's wasm from next to the bundle: the one its own manifold-3d ships
const pourRequire = createRequire(require.resolve('@tscircuit/copper-pour-solver'));
fs.copyFileSync(pourRequire.resolve('manifold-3d/manifold.wasm'), path.join(dist, 'manifold.wasm'));
const size = (f) => `${(fs.statSync(path.join(dist, f)).size / 1e6).toFixed(1)} MB`;
console.log(`dist/pcb-worker.mjs ${size('pcb-worker.mjs')}, svg-png.mjs ${size('svg-png.mjs')}, resvg.wasm ${size('resvg.wasm')}, manifold.wasm ${size('manifold.wasm')} in ${Date.now() - t0} ms`);
