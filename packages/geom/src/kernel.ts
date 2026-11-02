// Loads the manifold WASM module once and tracks every object created during a
// build so it can be freed afterwards. Without this, slider drags leak WASM memory.
import Module from 'manifold-3d';
import type { ManifoldToplevel, Manifold, CrossSection } from 'manifold-3d';

export type Wasm = ManifoldToplevel;
export type { Manifold, CrossSection };

let wasmPromise: Promise<Wasm> | null = null;

export function loadKernel(locateFile?: () => string): Promise<Wasm> {
  if (!wasmPromise) {
    wasmPromise = (async () => {
      const wasm = await (Module as any)(locateFile ? { locateFile } : undefined);
      wasm.setup();
      wasm.setMinCircularEdgeLength(0.5);
      wasm.setMinCircularAngle(6);
      patchForCollection(wasm);
      return wasm as Wasm;
    })();
  }
  return wasmPromise;
}

// Every Manifold/CrossSection returned by a static or instance method is pushed
// onto the active arena; `withArena` deletes everything not explicitly kept.
let arena: Set<{ delete(): void }> | null = null;

function track<T>(value: T): T {
  if (arena && value && typeof value === 'object') {
    if (Array.isArray(value)) value.forEach((v) => track(v));
    else if (typeof (value as any).delete === 'function') arena.add(value as any);
  }
  return value;
}

// Programs run in a separate `vm` realm on the server. manifold's glue tests
// `x instanceof Array`, which is false for arrays from another realm, so every
// argument crossing into the kernel is rebuilt with this realm's constructors.
function normalizeArg(v: any): any {
  if (Array.isArray(v)) return Array.from(v, normalizeArg);
  if (v !== null && typeof v === 'object' && !(v instanceof Object)) {
    if (ArrayBuffer.isView(v)) {
      const Ctor = (globalThis as any)[(v as any).constructor?.name];
      return Ctor ? new Ctor(v) : v;
    }
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(v)) out[k] = normalizeArg(v[k]);
    return out;
  }
  return v;
}

// Instances carry the embind prototype, which is not `cls.prototype` after setup().
function patchClass(cls: any, proto: any) {
  for (const key of Object.getOwnPropertyNames(cls)) {
    const fn = cls[key];
    if (typeof fn !== 'function' || key === 'prototype' || key === 'length' || key === 'name') continue;
    cls[key] = function (...args: unknown[]) {
      return track(fn.apply(this, args.map(normalizeArg)));
    };
  }
  for (const key of Object.getOwnPropertyNames(proto)) {
    if (key === 'constructor' || key === 'delete') continue;
    const desc = Object.getOwnPropertyDescriptor(proto, key);
    if (!desc || typeof desc.value !== 'function') continue;
    const fn = desc.value;
    proto[key] = function (...args: unknown[]) {
      return track(fn.apply(this, args.map(normalizeArg)));
    };
  }
}

function patchForCollection(wasm: any) {
  // The bindings mis-convert a scalar scaleTop (Y becomes 0), which silently turns
  // boxes into wedges. Programs written by the agent pass scalars, so normalize here.
  const pair = (s: unknown) => (typeof s === 'number' ? [s, s] : s);
  const sampleCs = wasm.CrossSection.square(1);
  const sampleM = wasm.Manifold.cube(1);
  const protos: Record<string, any> = {
    CrossSection: Object.getPrototypeOf(sampleCs),
    Manifold: Object.getPrototypeOf(sampleM),
  };
  sampleCs.delete();
  sampleM.delete();
  const csExtrude = protos.CrossSection.extrude;
  protos.CrossSection.extrude = function (h: number, n?: number, tw?: number, st?: unknown, c?: boolean) {
    return csExtrude.call(this, h, n ?? 0, tw ?? 0, pair(st ?? 1), c ?? false);
  };
  const mExtrude = wasm.Manifold.extrude;
  wasm.Manifold.extrude = function (p: unknown, h: number, n?: number, tw?: number, st?: unknown, c?: boolean) {
    return mExtrude.call(this, p, h, n ?? 0, tw ?? 0, pair(st ?? 1), c ?? false);
  };
  for (const name of ['Manifold', 'CrossSection']) {
    const Orig = wasm[name];
    patchClass(Orig, protos[name]);
    // `new Manifold(mesh)` / `new CrossSection(polys)` must be tracked too.
    const Wrapped = function (this: unknown, ...args: unknown[]) {
      return track(new Orig(...args.map(normalizeArg)));
    } as any;
    Object.setPrototypeOf(Wrapped, Orig);
    Wrapped.prototype = Orig.prototype;
    wasm[name] = Wrapped;
    Object.freeze(Wrapped);
    Object.freeze(Orig);
  }
  // Workers keep the kernel across builds, and programs reach these objects through any
  // solid (Object.getPrototypeOf(box)). Frozen, one program cannot swap volume() or
  // delete() under the next build; a write throws in strict code and is ignored otherwise.
  Object.freeze(protos.Manifold);
  Object.freeze(protos.CrossSection);
  Object.freeze(Object.getPrototypeOf(protos.Manifold));
}

// Preview builds (while a slider or handle is being dragged) trade detail for speed:
// meshing grids, ray grids, refinement and circle segments get coarser by `factor`.
// Libraries read it at call time; final builds, checks and exports use 1.
export const detail = { factor: 1 };

export function withDetail<T>(wasm: Wasm, factor: number, fn: () => T): T {
  const prev = detail.factor;
  if (factor === prev) return fn();
  detail.factor = factor;
  wasm.setMinCircularEdgeLength(0.5 * factor);
  wasm.setMinCircularAngle(6 * factor);
  try {
    return fn();
  } finally {
    detail.factor = prev;
    wasm.setMinCircularEdgeLength(0.5 * prev);
    wasm.setMinCircularAngle(6 * prev);
  }
}

// Synchronous on purpose: an `await` inside would let another build swap the arena.
export function withArena<T>(fn: (keep: <U>(v: U) => U) => T): T {
  const prev = arena;
  const mine = new Set<{ delete(): void }>();
  arena = mine;
  const kept = new Set<unknown>();
  try {
    return fn((v) => {
      kept.add(v);
      return v;
    });
  } finally {
    arena = prev;
    for (const obj of mine) {
      if (kept.has(obj)) continue;
      try {
        obj.delete();
      } catch {
        /* already freed */
      }
    }
  }
}
