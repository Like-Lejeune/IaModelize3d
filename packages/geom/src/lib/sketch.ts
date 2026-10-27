// Constraint sketches, like a real CAD sketcher: the program declares points with
// rough positions and relations (horizontal, distance, tangent...), and a damped
// Gauss-Newton solver finds exact coordinates. LLMs are good at relations and bad
// at arithmetic; this keeps the arithmetic out of the model.
import type { CrossSection, Wasm } from '../kernel.ts';

type Var = number; // index into x
interface Pt { kind: 'point'; i: Var; name?: string }
interface Ln { kind: 'line'; a: Pt; b: Pt }
interface Ci { kind: 'circle'; c: Pt; r: Var }
interface Constraint { name: string; residuals: (x: Float64Array) => number[] }

export function makeSketch(wasm: Wasm) {
  const { CrossSection: CS } = wasm;

  return function sketch() {
    const x: number[] = [];
    const fixed = new Set<number>();
    const cons: Constraint[] = [];
    const v = (val: number) => x.push(val) - 1;
    const P = (p: Pt, X: Float64Array): [number, number] => [X[p.i], X[p.i + 1]];
    const dir = (l: Ln, X: Float64Array) => {
      const [ax, ay] = P(l.a, X), [bx, by] = P(l.b, X);
      return [bx - ax, by - ay];
    };
    const add = (name: string, residuals: Constraint['residuals']) => cons.push({ name, residuals });

    const api = {
      point(px: number, py: number, o: { fixed?: boolean; name?: string } = {}): Pt {
        const i = v(px);
        v(py);
        if (o.fixed) {
          fixed.add(i);
          fixed.add(i + 1);
        }
        return { kind: 'point', i, name: o.name };
      },
      line(a: Pt, b: Pt): Ln {
        return { kind: 'line', a, b };
      },
      circle(c: Pt, r: number): Ci {
        return { kind: 'circle', c, r: v(r) };
      },
      fix(p: Pt) {
        fixed.add(p.i);
        fixed.add(p.i + 1);
      },
      coincident(p: Pt, q: Pt) {
        add('coincident', (X) => [X[p.i] - X[q.i], X[p.i + 1] - X[q.i + 1]]);
      },
      horizontal(l: Ln) {
        add('horizontal', (X) => [dir(l, X)[1]]);
      },
      vertical(l: Ln) {
        add('vertical', (X) => [dir(l, X)[0]]);
      },
      distance(p: Pt, q: Pt, d: number) {
        add(`distance ${d}`, (X) => [Math.hypot(X[q.i] - X[p.i], X[q.i + 1] - X[p.i + 1]) - d]);
      },
      dx(p: Pt, q: Pt, d: number) {
        add(`dx ${d}`, (X) => [X[q.i] - X[p.i] - d]);
      },
      dy(p: Pt, q: Pt, d: number) {
        add(`dy ${d}`, (X) => [X[q.i + 1] - X[p.i + 1] - d]);
      },
      length(l: Ln, d: number) {
        api.distance(l.a, l.b, d);
      },
      equal(l1: Ln, l2: Ln) {
        add('equal', (X) => [Math.hypot(...dir(l1, X)) - Math.hypot(...dir(l2, X))]);
      },
      parallel(l1: Ln, l2: Ln) {
        add('parallel', (X) => {
          const [a, b] = dir(l1, X), [c, d] = dir(l2, X);
          return [(a * d - b * c) / ((Math.hypot(a, b) * Math.hypot(c, d)) || 1)];
        });
      },
      perpendicular(l1: Ln, l2: Ln) {
        add('perpendicular', (X) => {
          const [a, b] = dir(l1, X), [c, d] = dir(l2, X);
          return [(a * c + b * d) / ((Math.hypot(a, b) * Math.hypot(c, d)) || 1)];
        });
      },
      angle(l1: Ln, l2: Ln, deg: number) {
        add(`angle ${deg}`, (X) => {
          const [a, b] = dir(l1, X), [c, d] = dir(l2, X);
          const ang = Math.atan2(a * d - b * c, a * c + b * d);
          let diff = ang - (deg * Math.PI) / 180;
          diff = Math.atan2(Math.sin(diff), Math.cos(diff));
          return [diff];
        });
      },
      pointOnLine(p: Pt, l: Ln) {
        add('pointOnLine', (X) => {
          const [ax, ay] = P(l.a, X);
          const [dx, dy] = dir(l, X);
          return [((X[p.i] - ax) * dy - (X[p.i + 1] - ay) * dx) / (Math.hypot(dx, dy) || 1)];
        });
      },
      midpoint(p: Pt, l: Ln) {
        add('midpoint', (X) => [X[p.i] - (X[l.a.i] + X[l.b.i]) / 2, X[p.i + 1] - (X[l.a.i + 1] + X[l.b.i + 1]) / 2]);
      },
      radius(c: Ci, r: number) {
        add(`radius ${r}`, (X) => [X[c.r] - r]);
      },
      pointOnCircle(p: Pt, c: Ci) {
        add('pointOnCircle', (X) => [Math.hypot(X[p.i] - X[c.c.i], X[p.i + 1] - X[c.c.i + 1]) - X[c.r]]);
      },
      tangent(l: Ln, c: Ci) {
        add('tangent', (X) => {
          const [ax, ay] = P(l.a, X);
          const [dx, dy] = dir(l, X);
          const dist = Math.abs((X[c.c.i] - ax) * dy - (X[c.c.i + 1] - ay) * dx) / (Math.hypot(dx, dy) || 1);
          return [dist - X[c.r]];
        });
      },
      symmetric(p: Pt, q: Pt, axis: Ln) {
        add('symmetric', (X) => {
          const [ax, ay] = P(axis.a, X);
          const [dx, dy] = dir(axis, X);
          const L = Math.hypot(dx, dy) || 1;
          const mx = (X[p.i] + X[q.i]) / 2 - ax, my = (X[p.i + 1] + X[q.i + 1]) / 2 - ay;
          const px = X[q.i] - X[p.i], py = X[q.i + 1] - X[p.i + 1];
          return [(mx * dy - my * dx) / L, (px * dx + py * dy) / L];
        });
      },

      solve(o: { maxIter?: number; tol?: number } = {}) {
        const free = x.map((_, i) => i).filter((i) => !fixed.has(i));
        const X = Float64Array.from(x);
        const resid = () => cons.flatMap((c) => c.residuals(X));
        let r = resid();
        let cost = r.reduce((s, e) => s + e * e, 0);
        let lambda = 1e-3;
        const n = free.length;
        let iter = 0;
        for (; iter < (o.maxIter ?? 200) && cost > (o.tol ?? 1e-14); iter++) {
          const m = r.length;
          const J = new Float64Array(m * n);
          for (let k = 0; k < n; k++) {
            const i = free[k];
            const h = 1e-7 * Math.max(1, Math.abs(X[i]));
            const old = X[i];
            X[i] = old + h;
            const r2 = resid();
            X[i] = old;
            for (let j = 0; j < m; j++) J[j * n + k] = (r2[j] - r[j]) / h;
          }
          // (JtJ + lambda*diag) dx = -Jt r
          const A = new Float64Array(n * n);
          const g = new Float64Array(n);
          for (let j = 0; j < m; j++)
            for (let a = 0; a < n; a++) {
              const ja = J[j * n + a];
              if (ja === 0) continue;
              g[a] -= ja * r[j];
              for (let b = 0; b < n; b++) A[a * n + b] += ja * J[j * n + b];
            }
          let improved = false;
          for (let tries = 0; tries < 8 && !improved; tries++) {
            const M = Float64Array.from(A);
            for (let a = 0; a < n; a++) M[a * n + a] += lambda * (A[a * n + a] + 1e-9);
            const dx = solveLinear(M, Float64Array.from(g), n);
            if (!dx) { lambda *= 10; continue; }
            const backup = free.map((i) => X[i]);
            free.forEach((i, k) => (X[i] += dx[k]));
            const r2 = resid();
            const c2 = r2.reduce((s, e) => s + e * e, 0);
            if (c2 < cost) {
              r = r2;
              cost = c2;
              lambda = Math.max(lambda / 3, 1e-12);
              improved = true;
            } else {
              free.forEach((i, k) => (X[i] = backup[k]));
              lambda *= 10;
            }
          }
          if (!improved) break;
        }
        for (let i = 0; i < x.length; i++) x[i] = X[i];
        const unsatisfied = cons.filter((c) => c.residuals(X).some((e) => Math.abs(e) > 1e-4)).map((c) => c.name);
        const dof = n - Math.min(n, r.length);
        return { ok: unsatisfied.length === 0, residual: Math.sqrt(cost), iterations: iter, unsatisfied, freeVariables: n, equations: r.length, dofEstimate: dof };
      },
      at(p: Pt): [number, number] {
        return [x[p.i], x[p.i + 1]];
      },
      r(c: Ci): number {
        return x[c.r];
      },
      // closed loop of points -> CrossSection
      polygon(points: Pt[]): CrossSection {
        return new CS([points.map((p) => api.at(p))], 'NonZero');
      },
      disc(c: Ci, segments?: number): CrossSection {
        return CS.circle(x[c.r], segments).translate(api.at(c.c));
      },
    };
    return api;
  };
}

function solveLinear(A: Float64Array, b: Float64Array, n: number): Float64Array | null {
  for (let c = 0; c < n; c++) {
    let p = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(A[r * n + c]) > Math.abs(A[p * n + c])) p = r;
    if (Math.abs(A[p * n + c]) < 1e-14) return null;
    if (p !== c) {
      for (let k = 0; k < n; k++) [A[c * n + k], A[p * n + k]] = [A[p * n + k], A[c * n + k]];
      [b[c], b[p]] = [b[p], b[c]];
    }
    for (let r = c + 1; r < n; r++) {
      const f = A[r * n + c] / A[c * n + c];
      if (f === 0) continue;
      for (let k = c; k < n; k++) A[r * n + k] -= f * A[c * n + k];
      b[r] -= f * b[c];
    }
  }
  const out = new Float64Array(n);
  for (let r = n - 1; r >= 0; r--) {
    let s = b[r];
    for (let k = r + 1; k < n; k++) s -= A[r * n + k] * out[k];
    out[r] = s / A[r * n + r];
  }
  return out;
}
