// Snap-fit case for the board in inputs.boards.board (fw.board/1): lib.elec builds it, check_enclosure verifies it.
const meta = {"title": "\u041d\u043e\u0447\u043d\u0438\u043a \u0441 \u0434\u0430\u0442\u0447\u0438\u043a\u043e\u043c \u0434\u0432\u0438\u0436\u0435\u043d\u0438\u044f case", "pack": "enclosure", "printNotes": "Base floor-down, lid top-down; PETG for the snap hooks (PLA works), 0.2 mm layers, no supports."};
const params = {
  wall: { value: 2, min: 1.2, max: 4, step: 0.1, unit: 'mm', label: 'Wall', source: 'design', group: 'Shell' },
  floor: { value: 1.6, min: 1.0, max: 4, step: 0.2, unit: 'mm', label: 'Floor', source: 'design', group: 'Shell' },
  lid: { value: 1.6, min: 1.0, max: 3, step: 0.2, unit: 'mm', label: 'Lid', source: 'design', group: 'Shell' },
  clear: { value: 0.5, min: 0.2, max: 2, step: 0.1, unit: 'mm', label: 'Gap around the board', source: 'design', group: 'Fit' },
  standoff: { value: 2.5, min: 1.5, max: 12, step: 0.1, unit: 'mm', label: 'Space under the board', source: 'design', group: 'Fit' },
  port_fit: { value: 0.3, min: 0.1, max: 1.0, step: 0.05, unit: 'mm', label: 'Gap around plugs', source: 'design', group: 'Fit' },
  lights: { value: 'hole', options: ['hole', 'skin'], label: 'LED window', source: 'design', group: 'Access' },
  mount: { value: 'peg', options: ['peg', 'auto', 'screw'], label: 'Board mount', source: 'design', group: 'Fit' },
  form: { value: 'soft', options: ['soft', 'round', 'box'], label: 'Shape', source: 'design', group: 'Shell' },
  mockup: { value: true, label: 'Printed stand-in for the PCB', source: 'design' },
  layout: { value: 'print', options: ['print', 'assembled'], label: 'Layout', source: 'design' },
  show_board: { value: false, label: 'Show the board', source: 'design' },
};
function build(p, lib) {
  const E = lib.elec;
  const spec = (lib.inputs.boards && lib.inputs.boards.board);
  lib.assert(spec, 'attach the board JSON as inputs.boards.board');
  const b = E.board(spec);
  const enc = E.enclosure(b, { wall: p.wall, floor: p.floor, lid: p.lid, clear: p.clear, standoff: p.standoff,
    portFit: p.port_fit, lights: p.lights, mount: p.mount, form: p.form });
  const parts = E.parts(enc, { layout: p.layout, ghost: p.show_board });
  if (p.mockup && p.layout !== 'assembled') {
    // the PCB's stand-in in front of the case: try the real module and the case before the board is made
    const plate = E.pcbPlate(b), pb = plate.boundingBox(), cb = enc.base.boundingBox();
    parts.push(lib.part(plate.translate([cb.min[0] - pb.min[0], cb.min[1] - 6 - pb.max[1], -pb.min[2]]), { name: 'pcb_mockup', color: '#3a7d44' }));
  }
  return parts;
}
return { meta, params, build };
