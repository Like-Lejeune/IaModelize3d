import type { ThemeMode } from './spec';

export interface ThemePreset {
  id: string;
  seed: string;
  primary: Record<ThemeMode, string>;
}

export const THEME_PRESETS: readonly ThemePreset[] = [
  { id: 'lime', seed: '#a6c84b', primary: { dark: '#b1d355', light: '#4f6700' } },
  { id: 'ocean', seed: '#4b90c8', primary: { dark: '#95ccff', light: '#00639a' } },
  { id: 'teal', seed: '#3fbfa8', primary: { dark: '#58dbc2', light: '#006b5c' } },
  { id: 'violet', seed: '#9b6bd8', primary: { dark: '#d9b9ff', light: '#7546b0' } },
  { id: 'rose', seed: '#db5c86', primary: { dark: '#ffb1c5', light: '#a6335d' } },
  { id: 'coral', seed: '#e0714b', primary: { dark: '#ffb59d', light: '#9f411f' } },
];

export function presetForSeed(seed: string): ThemePreset | undefined {
  const needle = seed.toLowerCase();
  return THEME_PRESETS.find((p) => p.seed === needle);
}
