export type ThemeMode = 'dark' | 'light';

export type ThemeTokens = Record<string, string>;

// The pre-paint script in `app.html` reads this shape: change it only together with that script and `TOKENS_VERSION`.
export interface StoredTheme {
  v: number;
  seed: string;
  mode: ThemeMode;
  css: string;
}

export const THEME_STORAGE_KEY = 'fw-theme';

export const COLOR_TOKENS: readonly string[] = [
  '--surface',
  '--surface-container-lowest',
  '--surface-container-low',
  '--surface-container',
  '--surface-high',
  '--surface-container-highest',
  '--surface-bright',
  '--divider',
  '--on-surface',
  '--on-surface-var',
  '--outline',
  '--outline-variant',
  '--tag-bg',
  '--tag-text',
  '--primary',
  '--on-primary',
  '--primary-container',
  '--on-primary-container',
  '--error',
  '--swatch-inner-ring',
  '--swatch-selected-ring',
];

// Bump when token NAMES change, not values: an old cache is then rebuilt from the seed.
export const TOKENS_VERSION = 1;

export const DEFAULT_SEED = '#a6c84b';

export const DEFAULT_MODE: ThemeMode = 'dark';

export function normalizeSeed(raw: string): string | null {
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(raw.trim());
  if (!m) return null;
  const body = m[1].toLowerCase();
  const full = body.length === 3 ? body[0] + body[0] + body[1] + body[1] + body[2] + body[2] : body;
  return `#${full}`;
}

export function isThemeMode(v: unknown): v is ThemeMode {
  return v === 'dark' || v === 'light';
}

export function tokensToCss(tokens: ThemeTokens): string {
  let out = '';
  for (const [token, value] of Object.entries(tokens)) out += `${token}:${value};`;
  return out;
}
