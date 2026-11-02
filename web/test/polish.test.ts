// node --test web/test/polish.test.ts: small text glitches that compile fine and only show on the page.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parse } from 'svelte/compiler';

const SRC = fileURLToPath(new URL('../src', import.meta.url));

function svelteFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? svelteFiles(join(dir, e.name)) : e.name.endsWith('.svelte') ? [join(dir, e.name)] : [],
  );
}

/**
 * Svelte 5 drops the whitespace at the start and the end of an element's or a block's content: `<span> · {x}</span>`
 * after a word renders 'word· x'. A space that must show goes in as {' · '}. Line breaks there are layout, not text.
 */
function trimmedSpaces(src: string, name: string): string[] {
  const line = (i: number) => src.slice(0, i).split('\n').length;
  const out: string[] = [];
  const fragment = (nodes: any[]) => {
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (first?.type === 'Text' && /^[ \t]+\S/.test(first.data)) out.push(`${line(first.start)}: ${JSON.stringify(first.data.slice(0, 24))}`);
    if (last?.type === 'Text' && /\S[ \t]+$/.test(last.data)) out.push(`${line(last.end)}: ${JSON.stringify(last.data.slice(-24))}`);
  };
  const visit = (n: any): void => {
    if (!n || typeof n !== 'object') return;
    if (Array.isArray(n)) return n.forEach(visit);
    if (n.type === 'RegularElement' && ['script', 'style', 'pre', 'textarea'].includes(n.name)) return;
    if (n.type === 'Fragment' && Array.isArray(n.nodes)) fragment(n.nodes);
    for (const [k, v] of Object.entries(n)) if (k !== 'metadata' && k !== 'parent' && v && typeof v === 'object') visit(v);
  };
  visit(parse(src, { modern: true }).fragment);
  return out.map((h) => `${name}:${h}`);
}

test('no space at the start or end of an element or a block is lost', () => {
  assert.deepEqual(svelteFiles(SRC).flatMap((f) => trimmedSpaces(readFileSync(f, 'utf8'), relative(SRC, f))), []);
});

test('the check catches the pattern it is for, and leaves the fixed form and layout alone', () => {
  const bad = '<p>{a}<span> · {b}</span>{#if c} — {d}{/if}<b>{e} / </b></p>';
  assert.deepEqual(trimmedSpaces(bad, 'x'), ['x:1: " · "', 'x:1: " — "', 'x:1: " / "']);
  const good = "<p>{a}<span>{' · '}{b}</span>{#if c}{' — '}{d}{/if} · {e}\n  <b>\n    {f}\n  </b></p>";
  assert.deepEqual(trimmedSpaces(good, 'x'), []);
});

test('a private project says so in either language, even after a language switch', async () => {
  (globalThis as any).$state = (v: unknown) => v;
  const { i18n, isText, t } = await import('../src/lib/i18n.svelte.ts');
  i18n.lang = 'en';
  const en = t('forbidden');
  i18n.lang = 'ru';
  // the store keeps the text of the language it loaded in
  assert.ok(isText(en, 'forbidden') && isText(t('forbidden'), 'forbidden'));
  assert.ok(!isText('Project not found', 'forbidden') && !isText(null, 'forbidden'));
  assert.match(t('private_project'), /закрытый проект/);
  assert.doesNotMatch(t('private_project'), /ремикс/i);
  i18n.lang = 'en';
  assert.doesNotMatch(t('private_project'), /remix/i);
});
