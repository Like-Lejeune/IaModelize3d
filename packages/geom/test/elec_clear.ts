// check_enclosure over the whole clear range of the case program (0.2 to 2.0 mm in its 0.1 mm steps) at the
// default wall, for every dataset board and the XIAO carrier: no errors, and every plug clears its window by the
// port fit (less the corner arcs' chord). elec_clear_even/_odd.test.ts take every other board, so node --test
// runs the two halves side by side.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Engine, loadKernel, functionEvaluator } from '../src/index.ts';
import type { BoardSpec } from '../src/lib/elec.ts';
import { BOARD_CASE } from './fixtures.ts';

const json = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8'));
const dataset = json('../src/boards.json') as { boards: BoardSpec[] };
const carrier = json('./data/xiao_carrier.board.json') as BoardSpec;
const CLEARS = Array.from({ length: 19 }, (_, i) => +(0.2 + 0.1 * i).toFixed(1));

export async function sweepClear(half: 0 | 1) {
  const engine = new Engine(await loadKernel(), functionEvaluator());
  for (const spec of [...dataset.boards, carrier].filter((_, i) => i % 2 === half)) {
    test(`${spec.id}: the case passes check_enclosure at every clear from 0.2 to 2.0 mm`, () => {
      const ports = spec.components.filter((p) => p.access === 'port');
      const bad: string[] = [];
      for (const clear of CLEARS) {
        const r = engine.inspect({ source: BOARD_CASE, inputs: { boards: { board: spec } }, params: { clear }, ops: [{ op: 'enclosure' }] }).results[0] as any;
        const errs = r.findings.filter((f: any) => f.severity === 'error');
        for (const f of errs) bad.push(`clear ${clear}: ${f.code} ${f.msg}`);
        for (const p of ports)
          if (!(r.clearance[p.id] >= 0.285) && !errs.some((f: any) => f.part === p.id)) bad.push(`clear ${clear}: ${p.id} clears its window by ${r.clearance[p.id]} mm`);
      }
      assert.deepEqual(bad, [], spec.id);
    });
  }
}
