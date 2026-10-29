import { DEFAULT_MODE, DEFAULT_SEED, THEME_STORAGE_KEY, TOKENS_VERSION, isThemeMode, normalizeSeed, tokensToCss, type StoredTheme, type ThemeMode } from './spec';
import { applyTheme, paintImmediate } from './paint';

let generator: Promise<typeof import('./palette')> | null = null;
let generatorSync: typeof import('./palette') | null = null;

function loadGenerator(): Promise<typeof import('./palette')> {
  generator ??= import('./palette').then((m) => (generatorSync = m));
  return generator;
}

function readStored(): StoredTheme | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    const candidate = parsed as Partial<StoredTheme>;
    const seed = typeof candidate.seed === 'string' ? normalizeSeed(candidate.seed) : null;
    if (!seed || !isThemeMode(candidate.mode)) return null;
    return {
      v: typeof candidate.v === 'number' ? candidate.v : 0,
      seed,
      mode: candidate.mode,
      css: typeof candidate.css === 'string' ? candidate.css : '',
    };
  } catch {
    return null;
  }
}

function persist(next: StoredTheme): void {
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(THEME_STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable: the theme lasts until reload */
  }
}

function systemMode(): ThemeMode {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return DEFAULT_MODE;
  }
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : DEFAULT_MODE;
}

const initial = readStored();

let seed = $state<string>(initial?.seed ?? DEFAULT_SEED);
let mode = $state<ThemeMode>(initial?.mode ?? systemMode());

let previewing = false;

async function apply(nextSeed: string, nextMode: ThemeMode): Promise<void> {
  const normalized = normalizeSeed(nextSeed) ?? DEFAULT_SEED;
  const { buildTokens } = await loadGenerator();
  const tokens = buildTokens(normalized, nextMode);
  previewing = false;

  seed = normalized;
  mode = nextMode;
  persist({ v: TOKENS_VERSION, seed: normalized, mode: nextMode, css: tokensToCss(tokens) });

  applyTheme(tokens, nextMode);
}

export const theme = {
  preload(): void {
    void loadGenerator().catch(() => {});
  },

  get seed(): string {
    return seed;
  },

  get mode(): ThemeMode {
    return mode;
  },

  setSeed(next: string): Promise<void> {
    const normalized = normalizeSeed(next);
    if (!normalized) return Promise.resolve();
    if (normalized === seed && !previewing) return Promise.resolve();
    return apply(normalized, mode);
  },

  previewSeed(next: string): void {
    const normalized = normalizeSeed(next);
    if (!normalized || normalized === seed) return;
    if (!generatorSync) {
      void loadGenerator();
      return;
    }
    seed = normalized;
    previewing = true;
    applyTheme(generatorSync.buildTokens(normalized, mode), mode, { animate: false });
  },

  setMode(next: ThemeMode): Promise<void> {
    if (!isThemeMode(next) || next === mode) return Promise.resolve();
    return apply(seed, next);
  },

  toggleMode(): Promise<void> {
    return apply(seed, mode === 'dark' ? 'light' : 'dark');
  },

  async init(): Promise<void> {
    const stored = readStored();
    if (!stored) return;
    const root = document.documentElement;
    const painted = root.dataset.theme === stored.mode && stored.v === TOKENS_VERSION;
    if (painted) return;

    try {
      const { buildTokens } = await loadGenerator();
      const tokens = buildTokens(stored.seed, stored.mode);
      seed = stored.seed;
      mode = stored.mode;
      persist({ v: TOKENS_VERSION, seed: stored.seed, mode: stored.mode, css: tokensToCss(tokens) });
      paintImmediate(tokens, stored.mode);
    } catch {
      /* the generator did not load: the default theme stays */
    }
  },
};
