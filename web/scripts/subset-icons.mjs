// Subsets the Tabler Icons webfont to the `ti-*` glyphs referenced in src/, so the app ships a few KB instead of ~800.
// Needs fontTools (`pip install fonttools brotli`). Run: npm run icons -w @formwright/web
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync, readdirSync, mkdirSync, statSync } from 'node:fs';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { dirname, join, extname } from 'node:path';

const web = join(dirname(fileURLToPath(import.meta.url)), '..');
const pkg = dirname(createRequire(import.meta.url).resolve('@tabler/icons-webfont/package.json'));
const { version } = JSON.parse(readFileSync(join(pkg, 'package.json'), 'utf8'));
const FULL_CSS = join(pkg, 'dist', 'tabler-icons.css');
const FULL_WOFF2 = join(pkg, 'dist', 'fonts', 'tabler-icons.woff2');
const TARGET = join(web, 'static', 'fonts', 'tabler-icons');
const SHELL = join(web, 'src', 'app.html');

function collect(dir, out) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) collect(full, out);
    else if (['.svelte', '.ts', '.js', '.html'].includes(extname(entry.name))) {
      for (const m of readFileSync(full, 'utf8').matchAll(/\bti-[a-z0-9]+(?:-[a-z0-9]+)*/g)) out.add(m[0].slice(3));
    }
  }
  return out;
}

const glyphs = new Map();
for (const m of readFileSync(FULL_CSS, 'utf8').matchAll(/\.ti-([a-z0-9-]+):+before\s*\{\s*content:\s*["']\\([0-9a-fA-F]+)["']/g)) glyphs.set(m[1], m[2].toLowerCase());

const found = [...collect(join(web, 'src'), new Set())];
const missing = found.filter((n) => !glyphs.has(n));
const used = found.filter((n) => glyphs.has(n)).sort();
if (!used.length) throw new Error('no ti-* icons found in src/');
if (missing.length) console.warn(`not in Tabler ${version}: ${missing.join(', ')}`);

const hash = createHash('sha256').update(used.join(',')).digest('hex').slice(0, 8);
const css =
  `/*! Tabler Icons ${version} (MIT, https://tabler.io/icons), subset of ${used.length} glyphs by scripts/subset-icons.mjs. Do not edit. */\n` +
  `@font-face{font-family:'tabler-icons';font-style:normal;font-weight:400;font-display:swap;src:url('./fonts/tabler-icons.woff2?v=${hash}') format('woff2')}\n` +
  `.ti{font-family:'tabler-icons'!important;speak:none;font-style:normal;font-weight:normal;font-variant:normal;text-transform:none;line-height:1;-webkit-font-smoothing:antialiased;-moz-osx-font-smoothing:grayscale}\n` +
  used.map((n) => `.ti-${n}::before{content:"\\${glyphs.get(n)}"}`).join('') +
  '\n';

mkdirSync(join(TARGET, 'fonts'), { recursive: true });
writeFileSync(join(TARGET, 'tabler-icons.min.css'), css);
const woff2 = join(TARGET, 'fonts', 'tabler-icons.woff2');
execFileSync(
  'python',
  ['-m', 'fontTools.subset', FULL_WOFF2, `--unicodes=${used.map((n) => glyphs.get(n)).join(',')}`, '--flavor=woff2', '--layout-features=', '--no-hinting', '--desubroutinize', `--output-file=${woff2}`],
  { stdio: ['ignore', 'ignore', 'inherit'] },
);

const shell = readFileSync(SHELL, 'utf8');
writeFileSync(SHELL, shell.replace(/(fonts\/tabler-icons\/(?:tabler-icons\.min\.css|fonts\/tabler-icons\.woff2))(\?v=[0-9a-f]+)?/g, `$1?v=${hash}`));

console.log(`${used.length} icons, woff2 ${(statSync(woff2).size / 1024).toFixed(1)} KB, v=${hash}`);
