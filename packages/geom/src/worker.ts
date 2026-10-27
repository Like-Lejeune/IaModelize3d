// Server-side geometry worker: JSON lines on stdin -> JSON lines on stdout.
// Programs run inside a `vm` context with a per-call timeout. Start it with the
// Node permission model so even an escaped program cannot read files or spawn
// processes; in production the container also has no network.
import vm from 'node:vm';
import readline from 'node:readline';
import { Engine } from './engine.ts';
import { loadKernel } from './kernel.ts';
import { validateProgram, type Evaluator } from './program.ts';

const TIMEOUT_MS = Number(process.env.FW_PROGRAM_TIMEOUT_MS ?? 20000);

function vmEvaluator(): Evaluator {
  const context = vm.createContext(Object.create(null), { codeGeneration: { strings: false, wasm: false } });
  const runner = vm.runInContext('(fn) => fn()', context) as (fn: () => unknown) => unknown;
  return {
    compile(source) {
      const raw = vm.runInContext(`"use strict";(function(){\n${source}\n})()`, context, { timeout: TIMEOUT_MS, filename: 'program.js' });
      return validateProgram(raw);
    },
    call<T>(fn: () => T): T {
      // Re-enter the context so the timeout applies to build() as well.
      const ctx = vm.createContext({ fn, runner });
      return vm.runInContext('runner(fn)', ctx, { timeout: TIMEOUT_MS }) as T;
    },
  };
}

const wasm = await loadKernel();
const engine = new Engine(wasm, vmEvaluator());

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
const write = (obj: unknown) => process.stdout.write(JSON.stringify(obj) + '\n');
write({ ready: true });

for await (const line of rl) {
  if (!line.trim()) continue;
  let msg: any;
  try {
    msg = JSON.parse(line);
  } catch {
    write({ id: null, error: { stage: 'protocol', message: 'bad json' } });
    continue;
  }
  const t0 = Date.now();
  try {
    const method = msg.method as 'build' | 'render' | 'export' | 'fit' | 'inspect';
    if (!['build', 'render', 'export', 'fit', 'inspect'].includes(method)) throw new Error(`unknown method ${method}`);
    const result = (engine as any)[method](msg.params);
    write({ id: msg.id, result, ms: Date.now() - t0 });
  } catch (e: any) {
    write({ id: msg.id, error: { stage: e?.stage ?? 'runtime', message: String(e?.message ?? e).slice(0, 2000) }, ms: Date.now() - t0 });
  }
}
