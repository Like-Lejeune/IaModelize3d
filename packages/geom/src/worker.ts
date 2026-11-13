// Server-side geometry worker: JSON lines on stdin -> JSON lines on stdout.
// Programs run inside a `vm` context with a per-call timeout. The process is started with the Node
// permission model (see server/iamodelize3d/geom.py), so even a program that escapes the vm realm
// cannot read the repo/.env/data, write files, spawn processes, start worker threads or load addons.
// The permission model does NOT cover network, so severNetwork() below cuts every outbound route
// reachable from this realm; in production the container also has no network (defense in depth).
import vm from 'node:vm';
import readline from 'node:readline';
import { Engine } from './engine.ts';
import { loadKernel } from './kernel.ts';
import { validateProgram, type Evaluator } from './program.ts';

const TIMEOUT_MS = Number(process.env.FW_PROGRAM_TIMEOUT_MS ?? 20000);

// Disable outbound network (and, for a clearer error, process spawning) in this realm, before any
// program runs. An escaped program reaches main-realm `process`, so blocking the user-facing module
// functions is not enough: we also block the raw tcp/udp/tls C++ bindings. We never touch stdio,
// which rides pipe_wrap/tty_wrap streams and Socket.prototype.write, so JSON lines keep flowing.
function severNetwork(): void {
  // a plain function, so `new dgram.Socket()` throws this too rather than "not a constructor"
  const die = (what: string) => function () {
    throw new Error(`network disabled in geometry worker: ${what}`);
  };
  const mod = (name: string): any => {
    try {
      return (process as any).getBuiltinModule(name);
    } catch {
      return null;
    }
  };
  const outbound: Record<string, string[]> = {
    net: ['connect', 'createConnection', 'createServer'],
    tls: ['connect', 'createServer'],
    http: ['request', 'get', 'createServer'],
    https: ['request', 'get', 'createServer'],
    http2: ['connect', 'createServer', 'createSecureServer'],
    dgram: ['createSocket'],
    dns: ['lookup', 'resolve', 'resolve4', 'resolve6', 'Resolver'],
    'dns/promises': ['lookup', 'resolve', 'Resolver'],
    inspector: ['open', 'url', 'console'],
    // already blocked by the permission model; fail fast with a clear message too
    child_process: ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork'],
    worker_threads: ['Worker'],
  };
  for (const [name, fns] of Object.entries(outbound)) {
    const m = mod(name);
    if (!m) continue;
    for (const fn of fns) if (fn in m) try { m[fn] = die(`${name}.${fn}`); } catch { /* frozen */ }
  }
  const methods: [string, string, string[]][] = [['net', 'Socket', ['connect']], ['tls', 'TLSSocket', ['connect']], ['net', 'Server', ['listen']],
    ['dgram', 'Socket', ['connect', 'bind', 'send']]];
  for (const [name, cls, fns] of methods) {
    const C = mod(name)?.[cls];
    for (const fn of fns) if (C?.prototype && fn in C.prototype) try { C.prototype[fn] = die(`${name}.${cls}.${fn}`); } catch { /* frozen */ }
  }
  // UDP and DNS carry no stdio, so every function they export goes: `new dgram.Socket()` with its own lookup never calls
  // createSocket, and resolveTxt/reverse/resolveMx query the network as well as lookup does
  for (const name of ['dgram', 'dns', 'dns/promises']) {
    const m = mod(name);
    if (m) for (const fn of Object.keys(m)) if (typeof m[fn] === 'function') try { m[fn] = die(`${name}.${fn}`); } catch { /* frozen */ }
  }
  try { mod('module')?.syncBuiltinESMExports(); } catch { /* older node */ }
  (globalThis as any).fetch = die('fetch');
  (globalThis as any).WebSocket = undefined;
  // Raw bindings for outbound sockets only; pipe_wrap/tty_wrap are left alone so stdio still works.
  try {
    const orig = (process as any).binding?.bind(process);
    if (orig) {
      (process as any).binding = (name: string) => {
        if (/^(tcp_wrap|udp_wrap|tls_wrap|http2)$/.test(String(name))) throw new Error('network binding disabled');
        return orig(name);
      };
    }
  } catch { /* process.binding not available */ }
}

severNetwork();

function vmEvaluator(): Evaluator {
  const context = vm.createContext(Object.create(null), { codeGeneration: { strings: false, wasm: false } });
  const runner = vm.runInContext('(fn) => fn()', context) as (fn: () => unknown) => unknown;
  // JSON lives in the context's own realm, so the clone and everything reachable from it is vm-realm.
  const cloneInRealm = vm.runInContext('(json) => JSON.parse(json)', context) as (json: string) => unknown;
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
    realmClone<T>(data: T): T {
      return cloneInRealm(JSON.stringify(data)) as T;
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
    const method = msg.method as 'build' | 'render' | 'export' | 'fit' | 'inspect' | 'parseMesh';
    if (!['build', 'render', 'export', 'fit', 'inspect', 'parseMesh'].includes(method)) throw new Error(`unknown method ${method}`);
    const result = (engine as any)[method](msg.params);
    write({ id: msg.id, result, ms: Date.now() - t0 });
  } catch (e: any) {
    write({ id: msg.id, error: { stage: e?.stage ?? 'runtime', message: String(e?.message ?? e).slice(0, 2000) }, ms: Date.now() - t0 });
  }
}
