// node --test web/test/replaylog.test.ts: a recorded run as the replay player's timeline.
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { MAX_GAP_S, clockOf, indexAfter, marksOf, withMessages } = await import('../src/lib/replaylog.ts');

const ev = (seq: number, ts: number, type = 'agent.status', data: Record<string, any> = {}) => ({ seq, ts, type, data });

test('long silences are squeezed, out-of-order times do not run the clock back', () => {
  const at = clockOf([ev(1, 100), ev(2, 103), ev(3, 5000), ev(4, 4999), ev(5, 5001)]);
  assert.deepEqual(at, [0, 3, 3 + MAX_GAP_S, 3 + MAX_GAP_S, 3 + MAX_GAP_S + 2]);
});

test('indexAfter counts every event played by that moment', () => {
  const at = [0, 0, 3, 7];
  assert.equal(indexAfter(at, -1), 0);
  assert.equal(indexAfter(at, 0), 2);
  assert.equal(indexAfter(at, 2.9), 2);
  assert.equal(indexAfter(at, 3), 3);
  assert.equal(indexAfter(at, 99), 4);
  assert.equal(indexAfter([], 5), 0);
});

test('a message without an event of its own goes in by its time; one with an event stays single', () => {
  const log = [ev(1, 100, 'user.message', { text: 'a hook' }), ev(2, 200, 'job.started')];
  const messages = [
    { id: 'm1', role: 'user', text: 'a hook', created_at: 99 },
    { id: 'm2', role: 'user', text: 'make it bigger', data: { asset_ids: ['a1'] }, created_at: 150 },
    { id: 'm3', role: 'agent', text: 'done', created_at: 160 },
  ];
  const out = withMessages(log, messages);
  assert.deepEqual(out.map((e) => e.seq), [1, -1, 2]);
  assert.deepEqual(out[1].data, { text: 'make it bigger', asset_ids: ['a1'] });
});

test('the log comes back as it was when nothing is missing', () => {
  const log = [ev(1, 100, 'user.message', { text: 'x' })];
  assert.equal(withMessages(log, [{ id: 'm', role: 'user', text: 'x', created_at: 100 }]), log);
});

test('the scrubber marks what a viewer would jump to', () => {
  const log = [
    ev(1, 0, 'user.message', { text: 'x' }),
    ev(2, 1, 'agent.status'),
    ev(3, 2, 'device.version', { version: 1, author: 'agent' }),
    ev(4, 3, 'device.version', { version: 2, author: 'user' }),
    ev(5, 4, 'pcb.version', { version: 1 }),
    ev(6, 5, 'program.updated', { version: 3 }),
    ev(7, 6, 'job.finished', { status: 'done' }),
    ev(8, 7, 'job.finished', { status: 'failed' }),
  ];
  const marks = marksOf(log, clockOf(log));
  assert.deepEqual(marks.map((m) => [m.kind, m.n, m.t]), [
    ['ask', undefined, 0], ['graph', 1, 2], ['board', 1, 4], ['version', 3, 5], ['done', undefined, 6], ['error', undefined, 7],
  ]);
});
