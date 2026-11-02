import { test } from 'node:test';
import assert from 'node:assert/strict';
import { strFromU8, unzipSync, unzlibSync } from 'fflate';
import { Engine, loadKernel, functionEvaluator, fromBase64 } from '../src/index.ts';
import { BAG_HOOK, VASE, BAD_SHELF } from './fixtures.ts';

const engine = new Engine(await loadKernel(), functionEvaluator());

test('bag hook builds and passes full checks', () => {
  const r = engine.build({ source: BAG_HOOK, analyze: 'full', mesh: true });
  assert.equal(r.ok, true);
  assert.ok(r.checks.stats.volume > 1000);
  const errors = r.checks.issues.filter((i: any) => i.severity === 'error');
  assert.deepEqual(errors, []);
  assert.equal(r.handles.length, 1);
});

test('params are clamped to their range', () => {
  const r = engine.build({ source: BAG_HOOK, params: { shelf_t: 999 }, analyze: 'none' });
  assert.equal(r.params.shelf_t, 40);
});

test('vase surface is a closed solid', () => {
  const r = engine.build({ source: VASE, analyze: 'fast' });
  assert.equal(r.checks.issues.filter((i: any) => i.code === 'invalid_mesh').length, 0);
  assert.ok(r.checks.stats.size[2] > 119);
});

test('bad shelf reports islands and thin features with heights', () => {
  const r = engine.build({ source: BAD_SHELF, analyze: 'full' });
  const codes = r.checks.issues.map((i: any) => i.code);
  assert.ok(codes.includes('floating_island'), codes.join(','));
  assert.ok(codes.includes('too_thin'), codes.join(','));
  const island = r.checks.issues.find((i: any) => i.code === 'floating_island');
  assert.ok(island.z[0] >= 19 && island.z[0] <= 21, JSON.stringify(island.z));
});

test('compile errors are reported with a stage', () => {
  assert.throws(() => engine.build({ source: 'return { build: 1 }' }), /build/);
});

test('render sheet and 3mf export produce bytes', () => {
  const png = engine.render({ source: BAG_HOOK, view: 'sheet', tile: 200 });
  assert.ok(png.png.length > 1000);
  const tmf = engine.export({ source: BAG_HOOK, format: '3mf', title: 'hook' });
  assert.ok(tmf.data.length > 1000);
});

// A table from two parts: the top's underside overhangs the leg, so a heat render shows red there.
const TWO_PARTS = `
function build(p, lib) {
  const { std, part } = lib;
  const leg = std.box([10, 10, 30]);
  const top = std.box([50, 50, 4]).translate([0, 0, 30]);
  const grey = '#d6d8de';
  return [part(leg, { name: 'leg', color: grey }), part(top, { name: 'top', color: grey }),
          part(std.box([8, 8, 8]).translate([0, 0, 10]), { name: 'dense', role: 'modifier', settings: { sparse_infill_density: '40%' } })];
}
return { meta: { title: 'Table' }, params: {}, build };
`;

// RGBA pixels of a PNG from encodePng (one IDAT, filter 0 on every row).
function pixels(b64: string) {
  const png = fromBase64(b64);
  const dv = new DataView(png.buffer, png.byteOffset);
  const width = dv.getUint32(16);
  let o = 8;
  const idat: Uint8Array[] = [];
  while (o < png.length) {
    const len = dv.getUint32(o);
    const type = String.fromCharCode(...png.subarray(o + 4, o + 8));
    if (type === 'IDAT') idat.push(png.subarray(o + 8, o + 8 + len));
    o += 12 + len;
  }
  const raw = unzlibSync(Uint8Array.from(idat.flatMap((c) => [...c])));
  const rows = raw.length / (width * 4 + 1);
  const out = new Uint8Array(width * rows * 4);
  for (let y = 0; y < rows; y++) out.set(raw.subarray(y * (width * 4 + 1) + 1, (y + 1) * (width * 4 + 1)), y * width * 4);
  return out;
}
const reddish = (rgba: Uint8Array) => {
  let n = 0;
  for (let i = 0; i < rgba.length; i += 4) if (rgba[i] > 150 && rgba[i] - rgba[i + 1] > 70 && rgba[i] - rgba[i + 2] > 70) n++;
  return n;
};

test('a multi-part render shows overhang heat under the overhanging part', () => {
  const r = engine.build({ source: TWO_PARTS, analyze: 'none' });
  assert.deepEqual(r.parts.map((p: any) => p.role), ['model', 'model', 'modifier']);
  // the sheet's red 10 mm scale bars are in both renders
  const hot = reddish(pixels(engine.render({ source: TWO_PARTS, view: 'sheet', tile: 160, heat: true }).png));
  const plain = reddish(pixels(engine.render({ source: TWO_PARTS, view: 'sheet', tile: 160 }).png));
  assert.ok(hot - plain > 200, `only ${hot - plain} heat pixels`);
});

test('STL export round-trips to a closed solid of the same volume', () => {
  for (const source of [BAG_HOOK, TWO_PARTS]) {
    const volume = engine.build({ source, analyze: 'fast' }).checks.stats.volume;
    const stl = engine.export({ source, format: 'stl' });
    assert.equal(stl.mime, 'model/stl');
    const back = engine.parseMesh({ data: stl.data, format: 'stl' });
    assert.equal(back.stats.closed, true, back.stats.reason);
    assert.ok(Math.abs(back.stats.volume - volume) / volume < 0.001, `${back.stats.volume} vs ${volume}`);
  }
});

test('3MF export: millimetres, one part per part with its subtype, extruder slots, production ids', () => {
  const tmf = engine.export({ source: TWO_PARTS, format: '3mf', title: 'Table' });
  const files = unzipSync(fromBase64(tmf.data));
  const text = (name: string) => strFromU8(files[name]);
  assert.ok(files['[Content_Types].xml'] && files['_rels/.rels'] && files['3D/_rels/3dmodel.model.rels']);
  const root = text('3D/3dmodel.model');
  const objects = text('3D/Objects/object_1.model');
  for (const xml of [root, objects]) {
    assert.match(xml, /<model unit="millimeter"/);
    assert.match(xml, /requiredextensions="p"/);
  }
  assert.equal((objects.match(/<object /g) ?? []).length, 3);
  assert.equal((root.match(/<component p:path="\/3D\/Objects\/object_1.model"/g) ?? []).length, 3);
  // the production extension needs an id on every object, component, the build and its items
  const tags = [...root.matchAll(/<(object|component|build|item) [^>]*>/g), ...objects.matchAll(/<object [^>]*>/g)].map((m) => m[0]);
  assert.equal(tags.length, 1 + 3 + 1 + 1 + 3);
  for (const tag of tags) assert.match(tag, /p:UUID="[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"/, tag);
  const ids = tags.map((t) => /p:UUID="([^"]+)"/.exec(t)![1]);
  assert.equal(new Set(ids).size, ids.length);
  const cfg = text('Metadata/model_settings.config');
  const parts = [...cfg.matchAll(/<part id="(\d+)" subtype="([a-z_]+)">(.*?)<\/part>/g)].map((m) => ({ id: m[1], subtype: m[2], body: m[3] }));
  assert.deepEqual(parts.map((p) => p.subtype), ['normal_part', 'normal_part', 'modifier_part']);
  assert.deepEqual(parts.map((p) => /key="name" value="([^"]+)"/.exec(p.body)?.[1]), ['leg', 'top', 'dense']);
  // same colour, same filament slot; modifiers take no slot but carry their settings
  assert.deepEqual(parts.map((p) => /key="extruder" value="(\d+)"/.exec(p.body)?.[1] ?? null), ['1', '1', null]);
  assert.match(parts[2].body, /key="sparse_infill_density" value="40%"/);
});

test('extrude keeps its cross-section (scalar scaleTop binding bug)', async () => {
  const { makeLib, DEFAULT_PRINTER } = await import('../src/index.ts');
  const lib = makeLib(engine.wasm, { printer: DEFAULT_PRINTER });
  const box = lib.CS.square([10, 10], true).extrude(40, 0, 0, 1);
  assert.ok(Math.abs(box.volume() - 4000) < 1, String(box.volume()));
  assert.ok(Math.abs(lib.std.box([10, 10, 40]).volume() - 4000) < 1);
});

test('constraint sketch solves a dimensioned bracket with a tangent', async () => {
  const { makeLib, DEFAULT_PRINTER } = await import('../src/index.ts');
  const lib = makeLib(engine.wasm, { printer: DEFAULT_PRINTER });
  const s = lib.std.sketch();
  // rough guesses on purpose; relations fix the exact shape
  const a = s.point(0, 0, { fixed: true }), b = s.point(37, 3), c = s.point(41, 22), d = s.point(2, 18);
  const ab = s.line(a, b), bc = s.line(b, c), cd = s.line(c, d), da = s.line(d, a);
  s.horizontal(ab); s.vertical(bc); s.horizontal(cd); s.vertical(da);
  s.length(ab, 40); s.length(bc, 20);
  const hole = s.circle(s.point(30, 8), 3);
  s.radius(hole, 4); s.tangent(bc, hole); s.dy(a, hole.c, 10);
  const r = s.solve();
  assert.equal(r.ok, true, JSON.stringify(r));
  const [cx, cy] = s.at(c);
  assert.ok(Math.abs(cx - 40) < 1e-6 && Math.abs(cy - 20) < 1e-6, `${cx},${cy}`);
  const [hx, hy] = s.at(hole.c);
  assert.ok(Math.abs(hx - 36) < 1e-5 && Math.abs(hy - 10) < 1e-5, `${hx},${hy}`);
  const plate = s.polygon([a, b, c, d]).subtract(s.disc(hole));
  assert.ok(Math.abs(plate.area() - (800 - Math.PI * 16)) < 0.6);
});

test('thread crests are fine detail, not errors', () => {
  const src = `return { meta: {}, params: {}, build: (p, lib) => lib.std.thread({ d: 6, pitch: 1, length: 12 }) };`;
  const r = engine.build({ source: src, analyze: 'full' });
  const errors = r.checks.issues.filter((i: any) => i.severity === 'error').map((i: any) => i.message);
  assert.deepEqual(errors, []);
});

test('issues are grouped by kind and the score counts kinds, not regions', () => {
  const r = engine.build({ source: BAD_SHELF, analyze: 'full' });
  const codes = r.checks.groups.map((g: any) => g.code);
  assert.equal(new Set(codes).size, codes.length);
  assert.equal(r.checks.groups[0].severity, 'error');
  const total = r.checks.groups.reduce((s: number, g: any) => s + g.count, 0);
  assert.equal(total, r.checks.issues.length);
  assert.ok(r.checks.score >= 0 && r.checks.score <= 100);
});

test('cube-corner relief planter prints without support errors', async () => {
  const { CUBE_PLANTER } = await import('./fixtures.ts');
  const r = engine.build({ source: CUBE_PLANTER, analyze: 'full' });
  const bad = r.checks.issues.filter((i: any) => i.severity === 'error' || i.code === 'overhang').map((i: any) => i.message);
  assert.deepEqual(bad, []);
});

// ---- free-form toolkit: sdf, loft/sweep, smoothing, surface features, mesh edits ----
const lib = async () => {
  const { makeLib, DEFAULT_PRINTER } = await import('../src/index.ts');
  return makeLib(engine.wasm, { printer: DEFAULT_PRINTER });
};

test('sdf: blended ellipsoids with a flat base mesh into one closed body', async () => {
  const { sdf } = await lib();
  const body = sdf.blend([sdf.ellipsoid([50, 70, 36]).translate([0, -15, 0]), sdf.ellipsoid([44, 60, 26]).translate([0, 25, -3])], 20)
    .intersect(sdf.halfspace([0, 0, -1], 0)).mesh();
  assert.equal(body.status(), 'NoError');
  assert.equal(body.genus(), 0);
  assert.ok(body.boundingBox().min[2] > -0.5 && body.numTri() < 40000, `${body.boundingBox().min[2]} ${body.numTri()}`);
});

test('sdf: rounded extrusion keeps its outline size and rounds the edges', async () => {
  const { sdf, std } = await lib();
  const s = sdf.extrude(std.rect(40, 20), 10, { r: 3 }).mesh();
  const b = s.boundingBox();
  assert.ok(Math.abs(b.max[0] - b.min[0] - 40) < 0.3 && Math.abs(b.max[2] - b.min[2] - 10) < 0.3);
  assert.ok(s.volume() < 8000 && s.volume() > 7300, String(s.volume())); // 40*20*10 minus rounded edges
});

test('loft along Y through spline sections is a closed solid with the right length', async () => {
  const { std } = await lib();
  const sec = (w: number, h: number) => std.poly(std.spline2d([[-w, 0], [w, 0], [w * 0.9, h * 0.7], [0, h], [-w * 0.9, h * 0.7]]));
  const s = std.loft([{ shape: sec(20, 18), at: -55 }, { shape: sec(31, 36), at: -15 }, { shape: sec(28, 25), at: 30 }, { shape: sec(18, 9), at: 58 }], { axis: 'y' });
  assert.equal(s.status(), 'NoError');
  const b = s.boundingBox();
  assert.ok(Math.abs(b.max[1] - b.min[1] - 113) < 0.01 && s.volume() > 100000);
});

test('sweep and closed pipe follow their paths', async () => {
  const { std } = await lib();
  const ring = std.pipe(std.spline3d([[30, 0, 5], [0, 30, 5], [-30, 0, 5], [0, -30, 5]], { closed: true }), 6, { closed: true });
  assert.equal(ring.status(), 'NoError');
  assert.equal(ring.genus(), 1);
  const bar = std.sweep(std.rect(6, 3), [[0, 0, 0], [50, 0, 0]]);
  assert.ok(Math.abs(bar.volume() - 900) < 1, String(bar.volume()));
});

test('smooth turns a low-poly ball into a round one', async () => {
  const { std, M } = await lib();
  const coarse = M.sphere(20, 8);
  const s = std.smooth(coarse, { angle: 90 });
  const ideal = (4 / 3) * Math.PI * 20 ** 3;
  assert.ok(s.numTri() > coarse.numTri() * 4);
  assert.ok(Math.abs(s.volume() - ideal) < Math.abs(coarse.volume() - ideal), `${s.volume()} vs ${coarse.volume()}`);
});

test('groove follows the curved top and emboss raises a shape on it', async () => {
  const { std, sdf } = await lib();
  const dome = sdf.ellipsoid([60, 100, 60]).intersect(sdf.halfspace([0, 0, -1], 0)).mesh();
  const cut = std.groove(dome, std.stroke2d([[0, -30], [0, 30]], 1.5), 1);
  const removed = dome.volume() - cut.volume();
  assert.ok(removed > 60 && removed < 120, String(removed)); // ~60 mm long x 1.5 wide x 1 deep along the curve
  const side = std.groove(std.box([30, 30, 30]), std.stroke2d([[-10, 5], [10, 5]], 2), 1, { dir: 'x' });
  assert.ok(Math.abs(27000 - side.volume() - 43) < 3, String(side.volume()));
  const up = std.emboss(std.box([40, 40, 10]), std.rect(10, 10), 1);
  assert.ok(Math.abs(up.volume() - 16100) < 1 && Math.abs(up.boundingBox().max[2] - 11) < 1e-6);
});

test('mesh edits keep a closed manifold; imported meshes become solids', async () => {
  const { sdf, mesh, std } = await lib();
  const ball = sdf.sphere(40).mesh();
  const s = mesh.sculpt(ball, [
    { brush: 'grab', at: [0, 0, 20], radius: 12, strength: 8, dir: [0, 0, 1] },
    { brush: 'crease', path: [[-20, -5, 10], [20, -5, 10]], radius: 4, strength: 1.5 },
  ]);
  assert.equal(s.status(), 'NoError');
  assert.ok(s.boundingBox().max[2] > 25);
  assert.equal(mesh.relax(std.box([20, 20, 20]), { edge: 1 }).status(), 'NoError');
  const stl = 'solid t\n' + [[0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 0, 0, 0, 0, 1, 1, 0, 0], [0, 0, 0, 0, 1, 0, 0, 0, 1], [1, 0, 0, 0, 0, 1, 0, 1, 0]]
    .map((t) => `facet normal 0 0 0\nouter loop\n${[0, 1, 2].map((v) => `vertex ${t[v * 3] * 10} ${t[v * 3 + 1] * 10} ${t[v * 3 + 2] * 10}`).join('\n')}\nendloop\nendfacet`).join('\n') + '\nendsolid';
  const parsed = engine.parseMesh({ data: Buffer.from(stl).toString('base64'), format: 'stl' });
  assert.equal(parsed.stats.closed, true);
  assert.ok(Math.abs(parsed.stats.volume - 1000 / 6) < 0.01);
  const src = `return { meta: {}, params: {}, build: (p, lib) => lib.mesh.input('scan').scale(2) };`;
  const r = engine.build({ source: src, analyze: 'none', inputs: { meshes: { scan: parsed } } });
  assert.ok(Math.abs(r.parts[0].volume - 8000 / 6) < 0.1);
});

test('close-up renders: any angle, a part, a section cut', () => {
  const views = engine.render({ source: BAG_HOOK, views: [{ azimuth: 30, elevation: 20 }, { azimuth: 200, elevation: -10 }] });
  assert.ok(views.png.length > 1000 && views.width === 840);
  const cut = engine.render({ source: BAG_HOOK, cut: { axis: 'z', at: 10 } });
  assert.ok(cut.png.length > 1000 && cut.width === 1260);
  const zoom = engine.render({ source: BAG_HOOK, focus: { center: [0, 0, 10], size: 20 } });
  assert.ok(zoom.png.length > 1000);
  assert.throws(() => engine.render({ source: BAG_HOOK, focus: { part: 'nope' } }), /no part/);
});

test('pillow body has no creases to its outline and onSurface pads fuse without slivers', async () => {
  const { sdf, std } = await lib();
  const plan = std.poly(std.spline2d([[0, 60], [28, 40], [31, 0], [30, -40], [0, -60], [-30, -40], [-31, 0], [-28, 40]]));
  const t0 = Date.now();
  const body = sdf.pillow(plan, (x: number, y: number) => 36 - Math.abs(y) * 0.15, { edge: 20, r: 3 }).mesh({ edge: 0.7 });
  assert.ok(Date.now() - t0 < 5000, `pillow took ${Date.now() - t0} ms`);
  assert.equal(body.genus(), 0);
  assert.ok(Math.abs(body.boundingBox().max[2] - 36) < 0.6);
  const pad = std.onSurface(body, std.rect(16, 6, { r: 2 }).translate([0, 12]), 1.2, { dir: '-x' });
  assert.equal(body.add(pad).decompose().length, 1);
});
