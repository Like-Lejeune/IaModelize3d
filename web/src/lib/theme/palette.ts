import { Hct, TonalPalette, argbFromHex, hexFromArgb } from '@material/material-color-utilities';
import { normalizeSeed, type ThemeMode, type ThemeTokens } from './spec';

type Tones = readonly [dark: number, light: number];

const NEUTRAL_ROLES: Record<string, Tones> = {
  '--surface': [6, 98],
  '--surface-container-lowest': [4, 100],
  '--surface-container-low': [10, 96],
  '--surface-container': [12, 94],
  '--surface-high': [17, 92],
  '--surface-container-highest': [22, 90],
  '--surface-bright': [24, 98],
  '--divider': [14, 91],
  '--on-surface': [90, 10],
};

const NEUTRAL_VARIANT_ROLES: Record<string, Tones> = {
  '--on-surface-var': [80, 30],
  '--outline': [60, 50],
  '--outline-variant': [30, 80],
  '--tag-bg': [20, 90],
  '--tag-text': [90, 30],
};

const PRIMARY_ROLES: Record<string, Tones> = {
  '--primary': [80, 40],
  '--on-primary': [20, 100],
  '--primary-container': [30, 90],
  '--on-primary-container': [90, 10],
};

const NEUTRAL_CHROMA = 4;
const NEUTRAL_VARIANT_CHROMA = 8;

const MIN_PRIMARY_CHROMA = 48;

const SEMANTIC_ROLES: { token: string; hue: number; chroma: number; tones: Tones }[] = [{ token: '--error', hue: 28, chroma: 34, tones: [65, 45] }];

const SWATCH_INNER_RING: Record<ThemeMode, string> = {
  dark: 'rgba(255, 255, 255, 0.22)',
  light: 'rgba(0, 0, 0, 0.18)',
};

export function buildTokens(seedHex: string, mode: ThemeMode): ThemeTokens {
  const seed = normalizeSeed(seedHex);
  if (!seed) throw new Error(`buildTokens: invalid seed ${JSON.stringify(seedHex)}`);

  const src = Hct.fromInt(argbFromHex(seed));
  const i = mode === 'dark' ? 0 : 1;
  const hex = (palette: TonalPalette, tones: Tones) => hexFromArgb(palette.tone(tones[i]));

  const neutral = TonalPalette.fromHueAndChroma(src.hue, NEUTRAL_CHROMA);
  const neutralVariant = TonalPalette.fromHueAndChroma(src.hue, NEUTRAL_VARIANT_CHROMA);
  const primary = TonalPalette.fromHueAndChroma(src.hue, Math.max(MIN_PRIMARY_CHROMA, src.chroma));

  const tokens: ThemeTokens = {};

  for (const [token, tones] of Object.entries(NEUTRAL_ROLES)) {
    tokens[token] = hex(neutral, tones);
  }
  for (const [token, tones] of Object.entries(NEUTRAL_VARIANT_ROLES)) {
    tokens[token] = hex(neutralVariant, tones);
  }
  for (const [token, tones] of Object.entries(PRIMARY_ROLES)) {
    tokens[token] = hex(primary, tones);
  }
  for (const { token, hue, chroma, tones } of SEMANTIC_ROLES) {
    tokens[token] = hex(TonalPalette.fromHueAndChroma(hue, chroma), tones);
  }

  tokens['--swatch-inner-ring'] = SWATCH_INNER_RING[mode];
  tokens['--swatch-selected-ring'] = tokens['--primary'];
  tokens['--scheme'] = mode;

  return tokens;
}
