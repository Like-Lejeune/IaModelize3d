// One program must not change what the next one builds: the server worker keeps the kernel (and
// a few builds) between calls from different projects.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { Engine, loadKernel, validateProgram, type Evaluator } from '../src/index.ts';

// The evaluator of src/worker.ts (which starts its stdin loop on import, so it is rebuilt here),
// with a shorter timeout.
const TIMEOUT_MS = 1000;
function vmEvaluator(): Evaluator {
  const context = vm.createContext(Object.create(null), { codeGeneration: { strings: false, wasm: false } });
  const runner = vm.runInContext('(fn) => fn()', context) as (fn: () => unknown) => unknown;
  return {
    compile(source) {
      return validateProgram(vm.runInContext(`"use strict";(function(){\n${source}\n})()`, context, { timeout: TIMEOUT_MS, filename: 'program.js' }));
    },
    call<T>(fn: () => T): T {
      return vm.runInContext('runner(fn)', vm.createContext({ fn, runner }), { timeout: TIMEOUT_MS }) as T;
    },
  };
}

const engine = new Engine(await loadKernel(), vmEvaluator());
const VICTIM = `return { meta: {}, params: {}, build: (p, lib) => lib.std.box([10, 10, 10]) };`;
const volume = (source: string) => engine.build({ source, analyze: 'fast' }).checks.stats.volume;

test('a program cannot patch the solids of the next build', () => {
  const evil = `
function build(p, lib) {
  const box = lib.std.box([1, 1, 1]);
  const tryAll = (fn) => { try { fn(); } catch {} };
  const proto = Object.getPrototypeOf(box);
  tryAll(() => { proto.volume = () => 424242; });
  tryAll(() => { Object.defineProperty(proto, 'boundingBox', { value: () => ({ min: [0, 0, 0], max: [1, 1, 1] }) }); });
  tryAll(() => { Object.getPrototypeOf(proto).delete = () => {}; });
  tryAll(() => { Object.getPrototypeOf(lib.CS.square(1)).area = () => 0; });
  tryAll(() => { lib.M.cube = () => null; });
  tryAll(() => { Object.getPrototypeOf(lib.M).union = () => null; });
  return box;
}
return { meta: {}, params: {}, build };`;
  assert.ok(Math.abs(volume(VICTIM) - 1000) < 1e-6);
  engine.build({ source: evil, analyze: 'none' });
  engine.release();
  const r = engine.build({ source: VICTIM, analyze: 'full' });
  assert.ok(Math.abs(r.checks.stats.volume - 1000) < 1e-6, String(r.checks.stats.volume));
  assert.deepEqual(r.checks.stats.size, [10, 10, 10]);
  assert.ok(r.checks.stats.firstLayerArea > 99);
  assert.ok(Math.abs(volume(`return { meta: {}, params: {}, build: (p, lib) => lib.M.union([lib.M.cube([5, 5, 5]), lib.M.cube([5, 5, 5]).translate([5, 0, 0])]) };`) - 250) < 1e-6);
});

test('a program that throws midway leaves the next build correct', () => {
  const crash = `
function build(p, lib) {
  const parts = [];
  for (let i = 0; i < 50; i++) parts.push(lib.std.box([i + 1, 2, 3]));
  lib.M.union(parts).subtract(lib.std.box([4, 4, 4]));
  throw new Error('boom');
}
return { meta: {}, params: {}, build };`;
  assert.throws(() => engine.build({ source: crash, analyze: 'fast' }), /boom/);
  assert.throws(() => engine.build({ source: `return { build: () => { while (true) {} } };` }), /timed out/);
  assert.ok(Math.abs(volume(VICTIM) - 1000) < 1e-6);
});
