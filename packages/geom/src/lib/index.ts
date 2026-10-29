// The `lib` object handed to build(p, lib). Everything a program may touch lives here.
import type { Manifold, Wasm } from '../kernel.ts';
import { makeForms, makeNoise } from './forms.ts';
import { makeMech } from './mech.ts';
import { makeMeshOps, type RawMesh } from './meshops.ts';
import { makeSdf } from './sdf.ts';
import { makeShape } from './shape.ts';
import { makeStd } from './std.ts';
import { makeSketch } from './sketch.ts';
import { makeThreads } from './threads.ts';

export interface PrinterProfile {
  name?: string;
  bed: [number, number, number];
  nozzle: number;
  layer: number;
  lineWidth: number;
  maxOverhang: number; // degrees from vertical that print without support
  maxBridge: number; // mm
  minLayerTime: number; // s
  // Fingerprint: how this printer deviates. Positive holeDelta enlarges holes.
  holeDelta?: number;
  outerDelta?: number;
  fitDelta?: number;
  elephantFoot?: number;
  material?: string;
  speed?: number; // mm/s typical outer wall
}

export const DEFAULT_PRINTER: PrinterProfile = {
  name: 'generic 0.4',
  bed: [256, 256, 256],
  nozzle: 0.4,
  layer: 0.2,
  lineWidth: 0.42,
  maxOverhang: 50,
  maxBridge: 12,
  minLayerTime: 6,
  holeDelta: 0.15,
  outerDelta: 0,
  fitDelta: 0,
  elephantFoot: 0.2,
  material: 'PLA',
  speed: 120,
};

// Data the agent attaches from the real world: measured outlines (mm, from photos),
// heightmaps (terrain), point sets and named values.
export interface Inputs {
  outlines?: Record<string, [number, number][][]>;
  heightmaps?: Record<string, { w: number; h: number; data: number[]; sizeX?: number; sizeY?: number }>;
  points?: Record<string, [number, number, number][]>;
  values?: Record<string, number | string>;
  // imported meshes (STL/OBJ uploads, scans): vertex xyz and triangle indices
  meshes?: Record<string, RawMesh>;
}

export interface LibContext {
  printer: PrinterProfile;
  inputs?: Inputs;
  skills?: Record<string, (lib: any, ...args: any[]) => unknown>;
  // 'preview' while a slider is dragged: coarser meshing for speed (see kernel.detail)
  quality?: 'preview' | 'final';
}

export function makeLib(wasm: Wasm, ctx: LibContext) {
  const std = makeStd(wasm, ctx);
  const threads = makeThreads(wasm);
  const forms = makeForms(wasm);
  const mech = makeMech(wasm, std.fit);
  const shape = makeShape(wasm);
  const lib: any = {
    Manifold: wasm.Manifold,
    CrossSection: wasm.CrossSection,
    M: wasm.Manifold,
    CS: wasm.CrossSection,
    std: { ...std, ...threads, ...mech, ...shape, sketch: makeSketch(wasm) },
    forms,
    sdf: makeSdf(wasm),
    mesh: makeMeshOps(wasm, ctx.inputs ?? {}),
    printer: ctx.printer,
    inputs: ctx.inputs ?? {},
    quality: ctx.quality ?? 'final',
    noise: makeNoise,
    part: (solid: Manifold, o: { name?: string; color?: string; role?: string; settings?: Record<string, unknown>; material?: string } = {}) => ({
      solid,
      name: o.name ?? 'body',
      role: o.role ?? 'model',
      color: o.color,
      settings: o.settings,
      material: o.material,
    }),
    rng: (seed = 1) => makeNoise(seed).rand,
    math: {
      deg: (r: number) => (r * 180) / Math.PI,
      rad: (d: number) => (d * Math.PI) / 180,
      clamp: (v: number, a: number, b: number) => Math.min(b, Math.max(a, v)),
      lerp: (a: number, b: number, t: number) => a + (b - a) * t,
      smoothstep: (a: number, b: number, x: number) => {
        const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
        return t * t * (3 - 2 * t);
      },
    },
    assert: (cond: unknown, message: string) => {
      if (!cond) throw new Error(`assertion failed: ${message}`);
    },
  };
  // Skills are saved, tested functions from the memory library: lib.skills.name(...args)
  lib.skills = Object.fromEntries(
    Object.entries(ctx.skills ?? {}).map(([name, fn]) => [name, (...args: unknown[]) => fn(lib, ...args)]),
  );
  return lib;
}
