// Programs used by tests and as few-shot examples for the agent.
export const BAG_HOOK = `
const meta = { title: 'Shelf bag hook', pack: 'household' };
const params = {
  shelf_t: { value: 18.2, min: 8, max: 40, step: 0.1, unit: 'mm', label: 'Shelf thickness', source: 'caliper' },
  depth:   { value: 30, min: 15, max: 60, unit: 'mm', label: 'Clamp depth', source: 'design' },
  width:   { value: 24, min: 10, max: 60, unit: 'mm', label: 'Width', source: 'design' },
  wall:    { value: 4, min: 2.4, max: 8, step: 0.42, unit: 'mm', label: 'Wall', source: 'design' },
  hook:    { value: 35, min: 15, max: 80, unit: 'mm', label: 'Hook reach', source: 'design' },
};
function handles(p) {
  return [{ type: 'linear', param: 'hook', at: [p.wall + p.hook, 0, 0], axis: [1, 0, 0], label: 'Hook reach' }];
}
function build(p, lib) {
  const { std } = lib;
  const t = p.shelf_t + std.fit('snug');
  // C-clamp profile in XZ, extruded along Y (prints on its side, layers follow the load)
  const outer = std.rect(p.depth + p.wall, t + 2 * p.wall, { center: false });
  const gap = std.rect(p.depth + 1, t, { center: false }).translate([p.wall, p.wall]);
  const arm = std.rect(p.hook, p.wall, { center: false }).translate([p.wall, -p.hook * 0]).translate([-p.hook + p.wall*0, 0]);
  let profile = outer.subtract(gap);
  const drop = std.rect(p.wall, p.hook, { center: false }).translate([0, -p.hook]);
  const lip = std.rect(p.hook * 0.35, p.wall, { center: false }).translate([0, -p.hook]);
  const tip = std.rect(p.wall, 8, { center: false }).translate([p.hook * 0.35 - p.wall, -p.hook]);
  profile = std.fillet2d(lib.CS.union([profile, drop, lip, tip]), 0.8, 2);
  return std.extrude(profile, p.width, { chamferBottom: 0.5 });
}
return { meta, params, handles, build };
`;

export const VASE = `
const meta = { title: 'Twisted ripple vase', pack: 'forms' };
const params = {
  height: { value: 120, min: 40, max: 250, unit: 'mm' },
  radius: { value: 40, min: 15, max: 90, unit: 'mm' },
  ripples: { value: 9, min: 0, max: 24, kind: 'int' },
  amp: { value: 4, min: 0, max: 12, unit: 'mm' },
  twist: { value: 90, min: 0, max: 360, unit: 'deg' },
};
function build(p, lib) {
  return lib.forms.surface({
    height: p.height, mode: 'shell', wall: 1.6, bottom: 2, segments: 160,
    radius: (z, th, t) => p.radius * (0.75 + 0.35 * Math.sin(t * Math.PI * 0.9 + 0.3)) + p.amp * Math.sin(p.ripples * th + lib.math.rad(p.twist) * t),
  });
}
return { meta, params, build };
`;

export const BAD_SHELF = `
const meta = { title: 'Floating shelf (bad on purpose)' };
const params = { };
function build(p, lib) {
  const { std } = lib;
  const post = std.box([10, 10, 40]);
  const plate = std.box([60, 30, 2]).translate([0, 0, 40]);
  const blob = std.box([8, 8, 4]).translate([40, 40, 20]);
  const fin = std.box([0.3, 20, 10]).translate([-20, 0, 0]);
  return lib.M.union([post, plate, blob, fin]);
}
return { meta, params, build };
`;

export const CUBE_PLANTER = `
const meta = { title: 'Cube-corner planter', pack: 'forms' };
const params = {
  height: { value: 110, min: 60, max: 200, unit: 'mm' },
  radius: { value: 48, min: 30, max: 90, unit: 'mm' },
  edge: { value: 9, min: 5, max: 16, unit: 'mm', label: 'Tile size' },
};
function build(p, lib) {
  const { forms } = lib;
  const shell = forms.surface({ height: p.height, mode: 'shell', wall: 2.1, bottom: 2.4, segments: 128, radius: () => p.radius });
  const R = p.edge * Math.sqrt(2 / 3);
  const perRow = Math.round((2 * Math.PI * p.radius) / (2 * R * Math.cos(Math.PI / 6)));
  const rows = Math.floor((p.height - 2 * R - 6) / (1.5 * R)) + 1;
  const relief = forms.tile({ radius: () => p.radius, element: forms.cubeCorner(p.edge), rows, perRow, z0: R + 4, z1: R + 4 + (rows - 1) * 1.5 * R, stagger: true });
  return shell.add(relief);
}
return { meta, params, build };
`;

// The case program an agent writes for a board: about 30 lines over lib.elec (elec*.test.ts).
export const BOARD_CASE = `
const meta = { title: 'Board snap case', pack: 'enclosure', printNotes: 'Base floor-down, lid top-down; PETG for the snap hooks, no supports.' };
const params = {
  wall: { value: 2.0, min: 1.2, max: 4, step: 0.1, unit: 'mm', source: 'design' },
  clear: { value: 0.5, min: 0.2, max: 2, step: 0.1, unit: 'mm', source: 'design' },
  standoff: { value: 2.5, min: 1.5, max: 12, step: 0.1, unit: 'mm', source: 'design' },
  port_fit: { value: 0.3, min: 0.1, max: 1.0, step: 0.05, unit: 'mm', source: 'design' },
  lights: { value: 'hole', options: ['hole', 'skin'], source: 'design' },
  mount: { value: 'peg', options: ['peg', 'auto', 'screw'], source: 'design' },
  buttons: { value: 'flex', options: ['flex', 'none'], source: 'design' },
  layout: { value: 'print', options: ['print', 'assembled'], source: 'design' },
  show_board: { value: false, source: 'design' },
};
function build(p, lib) {
  const E = lib.elec;
  const spec = lib.inputs.boards && lib.inputs.boards.board;
  lib.assert(spec, 'attach the board JSON as inputs.boards.board');
  const enc = E.enclosure(E.board(spec), { wall: p.wall, clear: p.clear, standoff: p.standoff, portFit: p.port_fit,
    lights: p.lights, mount: p.mount, buttons: p.buttons });
  return E.parts(enc, { layout: p.layout, ghost: p.show_board });
}
return { meta, params, build };
`;
