// check_enclosure over the whole lid range of the case program (1.0 to 3.0 mm in its 0.2 mm steps) for every board
// with a top button: a press tongue is as thick as the lid, so lib.elec sizes it from the strain limit and a thick
// lid gets a longer tongue (strain under the ~2 % button_reach allows), still inside the walls and off the posts,
// the snap hooks and the other tongues. Its own file, so node --test runs it beside the clear sweeps.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { Engine, loadKernel, functionEvaluator, makeLib, DEFAULT_PRINTER, withArena } from '../src/index.ts';
import type { BoardSpec } from '../src/lib/elec.ts';
import { BOARD_CASE } from './fixtures.ts';

const json = (rel: string) => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8'));
const dataset = json('../src/boards.json') as { boards: BoardSpec[] };
const carrier = json('./data/xiao_carrier.board.json') as BoardSpec;
const LIDS = Array.from({ length: 11 }, (_, i) => +(1.0 + 0.2 * i).toFixed(1));
// the case program with the lid as a param, as elec_tools.enclosure_program() writes it (lid 1.0..3, step 0.2)
const CASE_LID = BOARD_CASE.replace('const params = {', "const params = {\n  lid: { value: 1.6, min: 1.0, max: 3, step: 0.2, unit: 'mm', source: 'design' },")
  .replace('standoff: p.standoff,', 'standoff: p.standoff, lid: p.lid,');
assert.ok(CASE_LID.includes('lid: p.lid') && CASE_LID.includes('lid: { value: 1.6'));

const engine = new Engine(await loadKernel(), functionEvaluator());
const topButtons = (spec: BoardSpec) => spec.components.filter((c) => c.access === 'press' && c.side !== 'bottom' && (c.normal?.[2] ?? 1) > 0.5);
const DIR: Record<string, number[]> = { '+y': [0, 1], '-y': [0, -1], '+x': [1, 0], '-x': [-1, 0] };
const hit = (r: number[], q: number[]) => r[0] < q[2] && r[2] > q[0] && r[1] < q[3] && r[3] > q[1];

// the tongues and the snap hooks of the case in plan, from lib.elec's own report
function layout(spec: BoardSpec, lid: number) {
  return withArena(() => {
    const lib = makeLib(engine.wasm, { printer: DEFAULT_PRINTER, inputs: { boards: { board: spec } } });
    const enc = lib.elec.enclosure(lib.elec.board(spec), { lid });
    const hk = enc.report.features.find((f: any) => f.type === 'snap_hooks');
    const { x0, y0, x1, y1 } = enc.inner;
    const tabs = enc.report.features.filter((f: any) => f.type === 'flex_button').map((f: any) => {
      // the tongue with its slots: 1.6 + slot behind the plunger to the root, its width + a slot each side
      const v = DIR[f.dir], [cx, cy] = f.at, a0 = -1.6 - 0.8, a1 = f.len - 1.6, hw = f.width / 2 + 0.8;
      const rect = v[0] ? [cx + Math.min(v[0] * a0, v[0] * a1), cy - hw, cx + Math.max(v[0] * a0, v[0] * a1), cy + hw]
        : [cx - hw, cy + Math.min(v[1] * a0, v[1] * a1), cx + hw, cy + Math.max(v[1] * a0, v[1] * a1)];
      return { ...f, rect };
    });
    const hooks = enc.hooks.map((h: any) => {
      // the hook with the room it flexes in
      const onX = h.side[1] === 'x', ac = onX ? y0 + (y1 - y0) * h.along : x0 + (x1 - x0) * h.along, deep = hk.fit + hk.thickness + 2 * 0.4;
      return onX ? (h.side[0] === '+' ? [x1 - deep, ac - 3, x1, ac + 3] : [x0, ac - 3, x0 + deep, ac + 3])
        : (h.side[0] === '+' ? [ac - 3, y1 - deep, ac + 3, y1] : [ac - 3, y0, ac + 3, y0 + deep]);
    });
    return { tabs, hooks, inner: enc.inner };
  });
}

for (const spec of [...dataset.boards, carrier].filter((b) => topButtons(b).length)) {
  test(`${spec.id}: every top button is reachable at every lid from 1.0 to 3.0 mm`, () => {
    const bad: string[] = [];
    for (const lid of LIDS) {
      const r = engine.inspect({ source: CASE_LID, inputs: { boards: { board: spec } }, params: { lid }, ops: [{ op: 'enclosure' }] }).results[0] as any;
      for (const f of r.findings.filter((f: any) => f.severity === 'error')) bad.push(`lid ${lid}: ${f.code} ${f.msg}`);
      for (const c of topButtons(spec)) if (r.findings.find((f: any) => f.part === c.id && f.code.startsWith('button'))?.code !== 'button_reach') bad.push(`lid ${lid}: ${c.id} not reached`);
      const { tabs, hooks, inner } = layout(spec, lid);
      assert.equal(tabs.length, topButtons(spec).length, `${spec.id} lid ${lid}`);
      tabs.forEach((t: any, i: number) => {
        const at = `lid ${lid}: ${t.for} (${t.dir}, ${t.len} mm)`;
        // 10 mm up to a 2 mm lid, then just long enough for 1.8 %
        if (t.strain >= 0.0181 || t.len < 10 || (lid <= 2.0 && t.len !== 10)) bad.push(`${at}: strain ${t.strain}`);
        if (!t.clearOfPosts) bad.push(`${at}: no direction inside the walls and off the posts and hooks`);
        if (Math.min(t.rect[0] - inner.x0, t.rect[1] - inner.y0, inner.x1 - t.rect[2], inner.y1 - t.rect[3]) < 0.3) bad.push(`${at}: runs into the wall`);
        hooks.forEach((h: number[], j: number) => hit(t.rect, h) && bad.push(`${at}: over snap hook ${j}`));
        tabs.slice(i + 1).forEach((u: any) => hit(t.rect, u.rect) && bad.push(`${at}: over the tongue of ${u.for}`));
      });
    }
    assert.deepEqual(bad, [], spec.id);
  });
}
