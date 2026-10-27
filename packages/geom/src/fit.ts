// "LLM sets the structure, the optimizer sets the numbers": Nelder-Mead over the
// chosen parameters, scored by silhouette IoU against photo masks.

export interface FitResult {
  x: number[];
  score: number;
  evaluations: number;
  history: number[];
}

// Minimizes f over the unit cube [0,1]^n (callers map to real ranges).
export function nelderMead(f: (x: number[]) => number, x0: number[], o: { maxEval?: number; step?: number; tol?: number } = {}): FitResult {
  const n = x0.length;
  const maxEval = o.maxEval ?? 120;
  const clamp = (x: number[]) => x.map((v) => Math.min(1, Math.max(0, v)));
  let evals = 0;
  const history: number[] = [];
  const evalAt = (x: number[]) => {
    evals++;
    const v = f(clamp(x));
    history.push(v);
    return v;
  };
  let simplex = [clamp(x0)];
  for (let i = 0; i < n; i++) {
    const x = [...x0];
    x[i] = x[i] + (x[i] > 0.5 ? -1 : 1) * (o.step ?? 0.15);
    simplex.push(clamp(x));
  }
  let values = simplex.map(evalAt);
  while (evals < maxEval) {
    const order = values.map((v, i) => [v, i] as const).sort((a, b) => a[0] - b[0]).map(([, i]) => i);
    simplex = order.map((i) => simplex[i]);
    values = order.map((i) => values[i]);
    if (Math.abs(values[n] - values[0]) < (o.tol ?? 1e-4)) break;
    const centroid = Array.from({ length: n }, (_, j) => simplex.slice(0, n).reduce((s, p) => s + p[j], 0) / n);
    const at = (t: number) => clamp(centroid.map((c, j) => c + t * (simplex[n][j] - c)));
    const xr = at(-1);
    const fr = evalAt(xr);
    if (fr < values[0]) {
      const xe = at(-2);
      const fe = evalAt(xe);
      if (fe < fr) { simplex[n] = xe; values[n] = fe; } else { simplex[n] = xr; values[n] = fr; }
    } else if (fr < values[n - 1]) {
      simplex[n] = xr; values[n] = fr;
    } else {
      const xc = at(fr < values[n] ? -0.5 : 0.5);
      const fc = evalAt(xc);
      if (fc < Math.min(fr, values[n])) {
        simplex[n] = xc; values[n] = fc;
      } else {
        for (let i = 1; i <= n; i++) {
          simplex[i] = clamp(simplex[i].map((v, j) => simplex[0][j] + 0.5 * (v - simplex[0][j])));
          values[i] = evalAt(simplex[i]);
        }
      }
    }
  }
  const best = values.indexOf(Math.min(...values));
  return { x: simplex[best], score: values[best], evaluations: evals, history };
}

export function unpackMask(b64bits: Uint8Array, width: number, height: number): Uint8Array {
  const out = new Uint8Array(width * height);
  for (let i = 0; i < out.length; i++) out[i] = (b64bits[i >> 3] >> (7 - (i & 7))) & 1;
  return out;
}
