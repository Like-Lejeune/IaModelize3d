import { COLOR_TOKENS, type ThemeMode, type ThemeTokens } from './spec';

const SHIFT_ATTR = 'data-theme-shift';

let shiftTimer: ReturnType<typeof setTimeout> | undefined;

function holdShift(durationMs: number): void {
  const root = document.documentElement;
  root.setAttribute(SHIFT_ATTR, '');
  clearTimeout(shiftTimer);
  shiftTimer = setTimeout(() => root.removeAttribute(SHIFT_ATTR), durationMs + 40);
}

let transitionValue: string | null = null;
function colorTransition(): string {
  transitionValue ??= COLOR_TOKENS.map((token) => `${token} var(--t-theme-shift) var(--ease-standard)`).join(', ');
  return transitionValue;
}

function cssTimeMs(token: string): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  const n = parseFloat(raw);
  if (!Number.isFinite(n)) return 0;
  return raw.endsWith('ms') ? n : raw.endsWith('s') ? n * 1000 : n;
}

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function writeTokens(tokens: ThemeTokens, mode: ThemeMode): void {
  const root = document.documentElement;
  for (const [token, value] of Object.entries(tokens)) root.style.setProperty(token, value);
  root.setAttribute('data-theme', mode);
  syncMetaThemeColor(tokens['--surface']);
}

function syncMetaThemeColor(surface: string | undefined): void {
  if (!surface) return;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', surface);
}

export interface ApplyOptions {
  animate?: boolean;
}

export function applyTheme(tokens: ThemeTokens, mode: ThemeMode, options: ApplyOptions = {}): void {
  const animate = options.animate ?? !prefersReducedMotion();
  const root = document.documentElement;
  root.style.transition = animate ? colorTransition() : '';
  holdShift(animate ? cssTimeMs('--t-theme-shift') || 380 : 0);
  writeTokens(tokens, mode);
}

export function paintImmediate(tokens: ThemeTokens, mode: ThemeMode): void {
  applyTheme(tokens, mode, { animate: false });
}
