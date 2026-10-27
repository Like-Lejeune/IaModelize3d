"""Reference programs shown to the designer (few-shot). Each one is built and checked in
tests/test_examples.py, so the agent only ever sees examples that print cleanly."""

SHELF_HOOK = r"""
// Clamp-on bag hook for a shelf board. Printed on its side: layers follow the load.
const meta = { title: 'Shelf bag hook', pack: 'household' };
const params = {
  board: { value: 18, min: 8, max: 40, step: 0.1, unit: 'mm', label: 'Shelf thickness', source: 'caliper', group: 'Fit' },
  depth: { value: 35, min: 20, max: 80, unit: 'mm', label: 'Clamp depth', source: 'design', group: 'Fit' },
  reach: { value: 45, min: 25, max: 90, unit: 'mm', label: 'Hook reach', source: 'design', group: 'Shape' },
  width: { value: 22, min: 12, max: 60, unit: 'mm', label: 'Width', source: 'design', group: 'Shape' },
  wall: { value: 4.2, min: 2.52, max: 8.4, step: 0.42, unit: 'mm', label: 'Wall', source: 'design', group: 'Strength' },
};
function handles(p) {
  return [{ type: 'linear', param: 'reach', at: [p.wall + p.reach, -28, p.width / 2], axis: [1, 0, 0], label: 'Reach' }];
}
function build(p, lib) {
  const { std, CS } = lib;
  const gap = p.board + std.fit('snug');
  const H = gap + 2 * p.wall;
  // C-clamp around the board edge (XY profile; extruded along Z = width)
  const clamp = std.rect(p.depth + p.wall, H, { center: false }).subtract(std.rect(p.depth + 1, gap, { center: false }).translate([p.wall, p.wall]));
  // drop below the clamp, then the hook arm with an upturned lip so handles cannot slide off
  const drop = std.rect(p.wall, 30, { center: false }).translate([0, -30]);
  const arm = std.rect(p.reach + p.wall, p.wall, { center: false }).translate([0, -30]);
  const lip = std.rect(p.wall, 12, { center: false }).translate([p.reach, -30]); // leaves an 18 mm mouth for handles
  let profile = CS.union([clamp, drop, arm, lip]);
  profile = std.fillet2d(profile, 1.0, 3.0); // round outside edges, fillet the loaded inner corners
  return std.extrude(profile, p.width, { chamferBottom: 0.5, chamferTop: 0.5 });
}
return { meta, params, handles, build };
"""

COPY_FROM_PHOTO = r"""
// Copy of a flat part measured on a photo: outline and holes come from the scene, not from guesses.
const meta = { title: 'Bracket copy', pack: 'copy' };
const params = {
  thickness: { value: 4, min: 1.2, max: 12, step: 0.2, unit: 'mm', label: 'Thickness', source: 'caliper' },
  hole_d: { value: 5.5, min: 3, max: 8, step: 0.1, unit: 'mm', label: 'Hole (M5 clearance)', source: 'standard' },
  edge: { value: 0.6, min: 0, max: 1.5, step: 0.1, unit: 'mm', label: 'Edge chamfer', source: 'design' },
};
// measured centres from the scene (holes_mm), mm in the photo's reference frame
const HOLES = [[79.95, 145.0], [128.19, 118.88]];
function build(p, lib) {
  const { std } = lib;
  const outline = lib.inputs.outlines?.part;          // polygons in mm from the selected object
  lib.assert(outline, 'select the part on the photo first');
  let body = std.extrude(std.poly(outline), p.thickness, { chamferBottom: p.edge, chamferTop: p.edge });
  for (const [x, y] of HOLES) body = body.subtract(std.holeZ(p.hole_d, p.thickness, { at: [x, y, p.thickness], through: true }));
  return body;                                         // XY kept in the photo frame so the overlay lines up
}
return { meta, params, build };
"""

LAMP_SHADE = r"""
// Lamp shade: exact interface (E27 holder ring) + free generative body.
const meta = { title: 'Twisted shade', pack: 'forms' };
const params = {
  height: { value: 150, min: 80, max: 240, unit: 'mm', label: 'Height', source: 'user', group: 'Form' },
  base_r: { value: 60, min: 35, max: 110, unit: 'mm', label: 'Bottom radius', source: 'design', group: 'Form' },
  top_r: { value: 32, min: 26, max: 80, unit: 'mm', label: 'Top radius', source: 'design', group: 'Form' },
  ribs: { value: 16, min: 0, max: 40, kind: 'int', label: 'Ribs', source: 'design', group: 'Form' },
  twist: { value: 120, min: 0, max: 360, unit: 'deg', label: 'Twist', source: 'design', group: 'Form' },
  fitter: { value: 42, min: 28, max: 60, step: 0.5, unit: 'mm', label: 'Holder hole', source: 'search', group: 'Fit' },
};
function handles(p) {
  return [
    { type: 'radial', param: 'base_r', center: [0, 0, 0], axis: [0, 0, 1], at: [p.base_r, 0, 2], label: 'Bottom' },
    { type: 'linear', param: 'height', at: [0, 0, p.height], axis: [0, 0, 1], label: 'Height' },
  ];
}
function build(p, lib) {
  const { std, forms, math, M } = lib;
  const r = (z, th, t) => math.lerp(p.base_r, p.top_r, Math.pow(t, 0.8)) + 2.4 * Math.sin(p.ribs * th + math.rad(p.twist) * t);
  // wide rim on the bed, holder ring on top
  const shell = forms.surface({ height: p.height, mode: 'open', wall: 1.68, segments: 192, radius: r });
  const envelope = forms.surface({ height: p.height, mode: 'solid', segments: 192, radius: r });
  // 45° funnel from the wall up to a 3 mm flat ring around the holder hole: prints without support
  const dr = p.top_r + 1 - p.fitter / 2;
  const z0 = p.height - 3 - dr;
  const funnel = M.cylinder(dr + 3, p.top_r + 4, p.top_r + 4).translate([0, 0, z0])
    .subtract(M.cylinder(dr, p.top_r + 1, p.fitter / 2).translate([0, 0, z0 - 0.01]))
    .subtract(std.cyl(p.fitter, p.height * 3, { center: true }))
    .intersect(envelope);
  return shell.add(funnel);
}
return { meta, params, handles, build };
"""

SMOOTH_BODY = r"""
// Smooth product body: one soft shape from a plan outline and a top surface, details follow the surface.
const meta = { title: 'Pebble soap dish', pack: 'household' };
const params = {
  length: { value: 110, min: 80, max: 140, unit: 'mm', label: 'Length', source: 'design' },
  width: { value: 75, min: 55, max: 100, unit: 'mm', label: 'Width', source: 'design' },
  height: { value: 22, min: 14, max: 35, unit: 'mm', label: 'Height', source: 'design' },
};
function build(p, lib) {
  const { std, sdf } = lib;
  const L = p.length, W = p.width, H = p.height;
  // plan: a slightly egg-shaped pebble (spline through a few points, wider at -Y)
  const plan = std.poly(std.spline2d([[0, L / 2], [W * 0.42, L * 0.3], [W / 2, -L * 0.1], [W * 0.38, -L * 0.42],
                                      [0, -L / 2], [-W * 0.38, -L * 0.42], [-W / 2, -L * 0.1], [-W * 0.42, L * 0.3]]));
  // flat top at H (a level rim prints clean); r rounds where it meets the walls
  const top = () => H;
  let body = sdf.heightfield(plan, top, { r: 3 }).mesh({ edge: 0.8 });
  // drained dish: a smooth-edged pocket, then ribs so the soap dries
  const floor = 0.25 * H + 3;
  const pocket = sdf.extrude(plan.offset(-10, 'Round'), 2 * H, { r: 3 }).translate([0, 0, floor + H]);
  body = body.subtract(pocket.mesh({ edge: 0.8 }));
  for (const x of [-16, 0, 16]) body = body.add(sdf.box([2.52, L * 0.55, 6], { r: 1.2 }).translate([x, 0, floor - 1]).mesh({ edge: 0.6 }));
  // a decorative line along the middle of the rim, and initials raised on the curved side wall
  body = std.groove(body, plan.offset(-4.4, 'Round').subtract(plan.offset(-5.6, 'Round')), 0.6);
  return std.emboss(body, std.text2d('FW', { size: 8 }).translate([0, H * 0.45]), 0.8, { dir: '-y' });
}
return { meta, params, build };
"""

EXAMPLES_TEXT = f"""
# Reference programs (patterns to reuse; adapt, do not copy blindly)
## Clamp-on hook with a retaining lip (household)
```js{SHELF_HOOK}```
## Copy of a measured flat part (copy)
```js{COPY_FROM_PHOTO}```
## Exact interface + generative body (forms)
```js{LAMP_SHADE}```
## One smooth body with details on its curved surface (products, shells: sdf + groove/emboss)
```js{SMOOTH_BODY}```
"""
