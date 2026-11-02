"""Ready examples on the home page: tested programs a visitor opens as their own project, free and instantly.

Covers are rendered once per program and kept under data/files/examples, keyed by a hash of the source and REVISION
(and of the example's inputs, for the ones that carry some: the board of a case; and of what a spare part's fit check
measures: the wheel's hole, neck and play on its axle, which its opening message quotes). The PCB example also routes its
circuit once (in the sandboxed PCB worker, keyed by the circuit and the worker bundle) and keeps the whole version
under data/files/examples/pcb; every project opened from it gets a copy of that version and a case made from its board.
Its circuit is its own (XIAO_CARRIER), not the designer's reference board: the agent learns from a different board
(agent/pcb_prompt.EXAMPLE), so a XIAO brief gets designed rather than copied."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
from typing import Any

from . import storage

log = logging.getLogger("formwright.showcase")
try:
    from .agent import elec_tools
except Exception:  # noqa: BLE001 - like the agent hub: a broken case module takes the board examples away, not the app
    log.exception("showcase: the electronics modules did not import, the board examples are off")
    elec_tools = None  # type: ignore[assignment]

# The home page versions of the designer's reference shade and soap dish (agent/examples.py), tuned to print
# without a single warning: the holder ring sits on a 45° chamfer that starts outside the ribbed wall, and
# the lettering has three-line strokes and a 0.6 mm relief.
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
  const mid = (z) => math.lerp(p.base_r, p.top_r, Math.pow(z / p.height, 0.8));
  const r = (z, th, t) => mid(z) + 2.4 * Math.sin(p.ribs * th + math.rad(p.twist) * t);
  // wide rim on the bed, holder ring on top
  const shell = forms.surface({ height: p.height, mode: 'open', wall: 1.68, segments: 192, radius: r });
  const envelope = forms.surface({ height: p.height, mode: 'solid', segments: 192, radius: r });
  // 45° chamfer under a 3 mm flat ring around the holder hole. The cone starts just outside the ribs
  // (radius r0 at height z0, found in a few steps), so nothing under the ring is flat: no support needed.
  let r0 = p.top_r + 4;
  for (let i = 0; i < 6; i++) r0 = mid(p.height - 3 - (r0 - p.fitter / 2)) + 3.4;
  const dr = r0 - p.fitter / 2;
  const z0 = p.height - 3 - dr;
  const funnel = M.cylinder(dr + 3, r0, r0).translate([0, 0, z0])
    .subtract(M.cylinder(dr, r0, p.fitter / 2).translate([0, 0, z0 - 0.01]))
    .subtract(std.cyl(p.fitter, p.height * 3, { center: true }))
    .intersect(envelope);
  return shell.add(funnel);
}
return { meta, params, handles, build };
"""

SOAP_DISH = r"""
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
  // a decorative line along the middle of the rim, and initials raised on the curved side wall:
  // strokes three lines wide, and a 0.6 mm relief so the letters' undersides print without support
  body = std.groove(body, plan.offset(-4.4, 'Round').subtract(plan.offset(-5.6, 'Round')), 0.6);
  return std.emboss(body, std.text2d('FW', { size: 8, stroke: 1.26 }).translate([0, H * 0.45]), 0.6, { dir: '-y' });
}
return { meta, params, build };
"""

# The spare part: the wheel of a live run (p_6e49f0581fb94775: 25 x 8 mm, a 4 mm wire axle, a 3.2 mm clip opening) as a
# spoked wheel. It lies flat with the axle on Z through the origin and the snap slot along +X, which is what
# _axle_fit measures.
RACK_WHEEL = r"""
// Replacement dishwasher rack wheel: it snaps sideways onto the rack's wire axle through a neck narrower than the wire,
// then turns freely on it. Prints flat (axle vertical) with no supports.
const meta = { title: 'Dishwasher rack wheel', pack: 'household' };
const params = {
  diameter: { value: 25, min: 18, max: 40, step: 0.5, unit: 'mm', label: 'Wheel diameter', source: 'user', group: 'Fit' },
  width: { value: 8, min: 5, max: 14, step: 0.5, unit: 'mm', label: 'Wheel width', source: 'user', group: 'Fit' },
  axle: { value: 4, min: 3, max: 5, step: 0.1, unit: 'mm', label: 'Wire axle diameter', source: 'user', group: 'Fit' },
  clip_open: { value: 3.2, min: 2.4, max: 4.4, step: 0.1, unit: 'mm', label: 'Clip opening', source: 'design', group: 'Fit' },
  spokes: { value: 5, min: 3, max: 8, kind: 'int', label: 'Spokes', source: 'design', group: 'Shape' },
  edge: { value: 0.6, min: 0, max: 1, step: 0.1, unit: 'mm', label: 'Edge chamfer', source: 'design', group: 'Shape' },
};
function build(p, lib) {
  const { std } = lib;
  const R = p.diameter / 2;
  // axle hole: the wire plus a sliding fit, compensated for holes printing small, so it turns freely
  const bore = std.comp(p.axle + std.fit('slide'));
  // spoke openings between the hub and a 2.4 mm tread (six lines of the 0.4 nozzle); the snap slot runs through one
  let open = std.circle(2 * (R - 2.4)).subtract(std.circle(bore + 6));
  for (let i = 0; i < p.spokes; i++) open = open.subtract(std.rect(R + 1, 2.4, { center: false }).translate([0, -1.2]).rotate((360 / p.spokes) * (i + 0.5)));
  open = std.fillet2d(open, 0.8, 0);
  // the snap: a slot wider than the wire through the tread, a lead-in, then the neck narrower than the wire into the hole
  const n = p.clip_open / 2, s = (p.axle + 0.6) / 2, xa = bore / 2 + 1.2, xb = xa + 1.4;
  const snap = std.circle(bore).add(std.poly([[0, -n], [xa, -n], [xb, -s], [R + 1, -s], [R + 1, s], [xb, s], [xa, n], [0, n]]));
  const profile = std.fillet2d(std.circle(p.diameter).subtract(open).subtract(snap), 0.3, 0.3);
  // both faces chamfered: the tread rolls off its edges, the hole and the neck get a lead-in, the first layer no elephant foot
  return std.extrude(profile, p.width, { chamferBottom: p.edge, chamferTop: p.edge });
}
return { meta, params, build };
"""

PHONE_STAND = r"""
// Desk phone stand: the phone leans on a back rest, a front lip keeps it from sliding. Prints upright without supports.
const meta = { title: 'Phone stand', pack: 'household' };
const params = {
  angle: { value: 68, min: 55, max: 80, unit: 'deg', label: 'Lean angle', source: 'design', group: 'Fit' },
  phone: { value: 12, min: 7, max: 18, step: 0.5, unit: 'mm', label: 'Phone with case', source: 'design', group: 'Fit' },
  rest: { value: 95, min: 60, max: 130, unit: 'mm', label: 'Back rest', source: 'design', group: 'Shape' },
  lip: { value: 14, min: 8, max: 25, unit: 'mm', label: 'Front lip', source: 'design', group: 'Shape' },
  width: { value: 70, min: 40, max: 110, unit: 'mm', label: 'Width', source: 'design', group: 'Shape' },
  wall: { value: 5.04, min: 3.36, max: 8.4, step: 0.42, unit: 'mm', label: 'Wall', source: 'design', group: 'Strength' },
};
function geo(p) {
  const a = (p.angle * Math.PI) / 180;
  const foot = p.wall + p.phone + 1; // phone slot plus clearance
  const tip = [foot + p.rest * Math.cos(a), p.wall + p.rest * Math.sin(a)];
  return { a, foot, tip, depth: Math.max(tip[0] + 18, foot + 45) };
}
function handles(p) {
  const g = geo(p);
  return [
    { type: 'angle', param: 'angle', center: [g.foot, 0, p.wall], axis: [0, 1, 0], at: [g.tip[0], 0, g.tip[1]], label: 'Angle' },
    { type: 'linear', param: 'width', at: [g.depth / 2, p.width / 2, 0], axis: [0, 1, 0], scale: 2, label: 'Width' },
  ];
}
function build(p, lib) {
  const { std, CS } = lib;
  const g = geo(p);
  // side profile in XY (X: front to back, Y: up), extruded across the width
  const base = std.rect(g.depth, p.wall, { center: false });
  const lip = std.rect(p.wall, p.lip + p.wall, { center: false });
  const rest = std.rect(p.rest + p.wall, p.wall, { center: false }).rotate(p.angle).translate([g.foot + p.wall * Math.sin(g.a), 0]);
  // round the corners, then square the bottom again so the first layer has no overhang
  const profile = CS.union([std.fillet2d(CS.union([base, lip, rest]), 1.5, 4), std.rect(g.depth, p.wall / 2, { center: false })]);
  // stand it up: the profile's Y becomes Z, the width runs along Y
  return std.extrude(profile, p.width).rotate([90, 0, 0]).translate([0, p.width / 2, 0]);
}
return { meta, params, handles, build };
"""

# The PCB example: a XIAO ESP32-C3 carrier, the same code as packages/pcb/test/fixtures/xiao_carrier.tsx, which the engine's
# tests build with 0 DRC errors and 0 warnings. The card shows the build's warnings as engine notes next to DRC 0, so it
# has none: the 6x6 button's legs 1-2 and 3-4 are one contact each (GPIO on pin1, GND on pin3, the pairs declared), and the
# 5 V path runs pin to pin, where the router keeps its 0.4 mm (a width on a trace to a net is dropped).
XIAO_CARRIER = r"""
// Carrier board for a Seeed XIAO ESP32-C3: USB-C power input, status LED, push button, 4-pin I2C header.
// Only offline footprint strings are used (no jlcpcb:/kicad: footprints, no network).
// What the design promises: checked on every build next to DRC.
export const meta = {
  title: "XIAO ESP32-C3 carrier",
  intent: { edge: { J1: "-y", J2: "+x", U1: "+y" }, gpio: { LED1: "D10", SW1: "D1" }, nets_max: 30 },
}

export default () => (
  <board width="44mm" height="36mm" thickness="1.6mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.6mm">
    {/* XIAO ESP32-C3 on two 7-pin 2.54 mm rows, 15.24 mm apart; its own USB-C faces the top edge */}
    <chip
      name="U1"
      footprint="dip14_w15.24mm"
      manufacturerPartNumber="113991054"
      pcbX={0}
      pcbY={7.5}
      pinLabels={{
        pin1: "D0", pin2: "D1", pin3: "D2", pin4: "D3", pin5: "SDA", pin6: "SCL", pin7: "TX",
        pin8: "RX", pin9: "SCK", pin10: "MISO", pin11: "MOSI", pin12: "V3V3", pin13: "GND", pin14: "V5",
      }}
    />
    {/* USB-C power input on the bottom edge (power only: CC pull-downs make it a 5 V sink) */}
    <chip
      name="J1"
      footprint="usbcmidmount"
      manufacturerPartNumber="TYPE-C-31-M-12"
      supplierPartNumbers={{ jlcpcb: ["C165948"] }}
      pcbX={0}
      pcbY={-12.5}
      pinLabels={{
        pin1: "SH1", pin2: "SH2", pin3: "SH3", pin4: "SH4",
        pin5: "GND_A", pin6: "VBUS_A", pin7: "SBU2", pin8: "CC1", pin9: "DN2", pin10: "DP1",
        pin11: "DN1", pin12: "DP2", pin13: "SBU1", pin14: "CC2", pin15: "VBUS_B", pin16: "GND_B",
      }}
    />
    <resistor name="R1" resistance="5.1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23186"] }} pcbX={-6} pcbY={-7.5} />
    <resistor name="R2" resistance="5.1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23186"] }} pcbX={6} pcbY={-7.5} />
    {/* Schottky from USB VBUS to the XIAO 5V pin, so a cable in the XIAO's own port cannot back-feed */}
    <diode name="D1" footprint="sod123" manufacturerPartNumber="B5819W" supplierPartNumbers={{ jlcpcb: ["C8598"] }} pcbX={11} pcbY={-13} pcbRotation={90} />
    {/* status LED on D10 (GPIO10) */}
    <resistor name="R3" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={15} pcbY={-6} pcbRotation={90} />
    <led name="LED1" color="green" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C72043"] }} pcbX={15} pcbY={-11} pcbRotation={90} />
    {/* push button on D1 (GPIO3) to GND, internal pull-up; legs 1-2 and 3-4 are one contact each, so D1 goes to pin1 and GND to pin3 */}
    <pushbutton name="SW1" footprint="pushbutton" internallyConnectedPins={[["pin1", "pin2"], ["pin3", "pin4"]]} pcbX={-12} pcbY={-7} />
    {/* 4-pin I2C header on the right edge: 3V3, GND, SDA, SCL; with 4.7k pull-ups */}
    <pinheader name="J2" pinCount={4} pitch="2.54mm" pcbX={19.5} pcbY={4} pcbRotation={90}
      pinLabels={["V3V3", "GND", "SDA", "SCL"]} />
    <resistor name="R4" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={14.5} pcbY={5} pcbRotation={90} />
    <resistor name="R5" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={14.5} pcbY={0} pcbRotation={90} />
    {/* M3 mounting holes */}
    <hole name="H1" diameter="3.2mm" pcbX={-18.5} pcbY={14.5} />
    <hole name="H2" diameter="3.2mm" pcbX={18.5} pcbY={14.5} />
    <hole name="H3" diameter="3.2mm" pcbX={-18.5} pcbY={-14.5} />
    <hole name="H4" diameter="3.2mm" pcbX={18.5} pcbY={-14.5} />

    {/* the 5 V path pin to pin, so its 0.4 mm width is kept (a width on a trace to a net is not) */}
    <trace from=".J1 > .VBUS_A" to=".D1 > .anode" thickness="0.4mm" />
    <trace from=".D1 > .cathode" to=".U1 > .V5" thickness="0.4mm" />
    <trace from=".J1 > .VBUS_B" to=".J1 > .VBUS_A" />
    <trace from=".J1 > .GND_A" to="net.GND" />
    <trace from=".J1 > .GND_B" to="net.GND" />
    <trace from=".J1 > .SH1" to="net.GND" />
    <trace from=".J1 > .CC1" to=".R1 > .pin1" />
    <trace from=".R1 > .pin2" to="net.GND" />
    <trace from=".J1 > .CC2" to=".R2 > .pin1" />
    <trace from=".R2 > .pin2" to="net.GND" />
    <trace from=".U1 > .GND" to="net.GND" />
    <trace from=".U1 > .MOSI" to=".R3 > .pin1" />
    <trace from=".R3 > .pin2" to=".LED1 > .anode" />
    <trace from=".LED1 > .cathode" to="net.GND" />
    <trace from=".U1 > .D1" to=".SW1 > .pin1" />
    <trace from=".SW1 > .pin3" to="net.GND" />
    <trace from=".J2 > .V3V3" to=".U1 > .V3V3" />
    <trace from=".J2 > .GND" to="net.GND" />
    <trace from=".J2 > .SDA" to=".U1 > .SDA" />
    <trace from=".J2 > .SCL" to=".U1 > .SCL" />
    <trace from=".R4 > .pin1" to=".U1 > .V3V3" />
    <trace from=".R4 > .pin2" to=".U1 > .SDA" />
    <trace from=".R5 > .pin1" to=".U1 > .V3V3" />
    <trace from=".R5 > .pin2" to=".U1 > .SCL" />
  </board>
)
""".lstrip("\n")

# The PCB example's cover: the routed board (its fw.board/1 description, the parts in their colours) just above the open
# case it drops into, built with the case program's defaults, and the lid beside it as it is printed, inside up. Seated,
# the walls hide most of the board at tile size. Rendered only.
COVER_PCB = r"""
// Cover: the board over its open case, the lid beside it.
const meta = { title: 'Carrier board in its case', pack: 'enclosure' };
const D = %(defaults)s;
const COLORS = { xiao_esp32c3: '#1f2c4d', shield: '#c4c8ce', usb_c: '#b3b8c0', pin_header_2_54: '#26282c', tact_6x6: '#34373c',
  tact_3x4_smd: '#e1e1e1', led_0603: '#36d06a', ufl: '#d8ad4f', diode_sod123: '#2b2b2b' };
function build(p, lib) {
  const E = lib.elec, M = lib.M;
  const b = E.board(lib.inputs.boards.board);
  const enc = E.enclosure(b, { wall: D.wall, floor: D.floor, lid: D.lid, clear: D.clear, standoff: D.standoff, portFit: D.port_fit,
    lights: D.lights, mount: D.mount });
  let pcb = b.outline.extrude(b.T);
  if (b.mounts.length) pcb = pcb.subtract(M.union(b.mounts.map((h) => M.cylinder(b.T + 2, h.d / 2, h.d / 2, 32).translate([h.x, h.y, -1]))));
  const z = enc.zTop + 3; // the board's bottom face, 3 mm over the rim
  const out = [lib.part(enc.base, { name: 'base' }), lib.part(pcb.translate([0, 0, z]), { name: 'pcb', color: '#2f7f4f' })];
  for (const c of b.comps) {
    const s = c.box, size = [s.max[0] - s.min[0], s.max[1] - s.min[1], s.max[2] - s.min[2]];
    if (size[2] < 0.05) continue;
    out.push(lib.part(M.cube(size).translate([s.min[0], s.min[1], s.min[2] + z]), { name: c.id, color: COLORS[c.type] || '#c9a26b' }));
  }
  out.push(lib.part(E.printLayout(enc).lid, { name: 'lid', color: '#e8965a' }));
  return out;
}
return { meta, build };
"""

# A case around a board from the dataset (boards.json), checked against it: plug paths through the USB window,
# the press tab over BOOTSEL, the LED window, snap strain and the antenna keep-out. The board travels as the
# example's inputs.boards.board; the program is the designer's case example with its own title, and carries the
# board's geometry as well, so the case also builds in a project opened without those inputs.
# The PCB example (XIAO_CARRIER, DRC-clean, warning-free and intent-checked in the tests): routed here, its board.json
# becomes inputs.boards.board of the same case program the agent's make_enclosure writes, with the printed stand-in
# plate of the PCB.
PICO_W = PICO_W_CASE = XIAO_CASE = XIAO_COVER = None
if elec_tools:
    try:
        PICO_W = elec_tools.dataset_board("rpi-pico-w")
        PICO_W_CASE = elec_tools.enclosure_program(title="Pico W snap case", fallback=PICO_W)
        XIAO_CASE = elec_tools.enclosure_program(title="XIAO ESP32-C3 carrier case", mockup=True)
        XIAO_COVER = COVER_PCB % {"defaults": json.dumps(elec_tools.DEFAULTS)}
    except Exception:  # noqa: BLE001 - the board examples are off, the others stay
        log.exception("showcase: the board examples could not be made")
        PICO_W = PICO_W_CASE = XIAO_CASE = XIAO_COVER = None

# Order is the order on the home page (two rows of three): the spare part first, since that is what the Axo farm prints
# for people, then the striking forms, the boards and an everyday fit.
EXAMPLES: list[dict[str, Any]] = [e for e in [
    {
        "key": "rack-wheel", "source": RACK_WHEEL, "pack": "household", "fit": {"axle": "axle", "diameter": "diameter", "width": "width"},
        "material": "PETG",  # hot and wet: its first message says so, and 'Order a print' prices it in PETG
        "title": {"en": "Dishwasher rack wheel", "ru": "Колёсико корзины посудомойки"},
        # two lines on a phone; the opening message gives the measured fit
        "caption": {"en": "Replacement part: 25 mm, axle 4 mm, snaps on", "ru": "Запчасть на замену: 25 мм, ось 4 мм, на защёлке"},
        "prompt": {"en": "A replacement wheel for my dishwasher's lower rack: 25 mm across, 8 mm wide, it snaps onto a 4 mm wire axle",
                   "ru": "Колёсико на замену для нижней корзины посудомойки: 25 мм в диаметре, 8 мм шириной, защёлкивается на "
                         "проволочную ось 4 мм"},
    },
    {
        "key": "lamp-shade", "source": LAMP_SHADE, "pack": "forms",
        "title": {"en": "Twisted lamp shade", "ru": "Абажур с закруткой"},
        "caption": {"en": "Free-form body, exact E27 holder ring", "ru": "Свободная форма и точное кольцо под патрон E27"},
        "prompt": {"en": "A twisted lamp shade for an E27 holder, about 15 cm tall", "ru": "Абажур с закруткой под патрон E27, высотой около 15 см"},
    },
    {
        "key": "soap-dish", "source": SOAP_DISH, "pack": "household",
        "title": {"en": "Pebble soap dish", "ru": "Мыльница-галька"},
        "caption": {"en": "Soft body, drain ribs, lettering on a curve", "ru": "Мягкая форма, рёбра для стока, надпись по изгибу"},
        "prompt": {"en": "A pebble-shaped soap dish with ribs so the soap dries", "ru": "Мыльница в форме гальки с рёбрами, чтобы мыло высыхало"},
    },
    {
        "key": "xiao-carrier", "source": XIAO_CASE, "pack": "pcb", "circuit": XIAO_CARRIER, "cover": XIAO_COVER,
        "title": {"en": "XIAO ESP32-C3 carrier board + case", "ru": "Плата для XIAO ESP32-C3 + корпус"},
        "caption": {"en": "Routed on 2 layers, DRC 0, Gerber files; the case is checked through its ports",
                    "ru": "Разведена в 2 слоя, DRC 0, файлы Gerber; корпус проверен через разъёмы"},
        "prompt": {"en": "A carrier board for my Seeed XIAO ESP32-C3: USB-C power in, a button, a status LED on a GPIO and an I2C header on the "
                         "right edge, and a case for it",
                   "ru": "Плата для Seeed XIAO ESP32-C3: питание по USB-C, кнопка, светодиод статуса на GPIO и разъём I2C на правом краю, "
                         "и корпус к ней"},
    },
    {
        "key": "pico-w-case", "source": PICO_W_CASE, "pack": "enclosure", "inputs": {"boards": {"board": PICO_W}},
        "title": {"en": "Pico W case", "ru": "Корпус для Pico W"},
        "caption": {"en": "Checked against the board: USB plug, BOOTSEL tab, LED window", "ru": "Проверен против платы: штекер USB, язычок BOOTSEL, окно светодиода"},
        "prompt": {"en": "A snap-fit case for my Raspberry Pi Pico W: USB open, a press tab over BOOTSEL and a window for the LED",
                   "ru": "Корпус на защёлках для Raspberry Pi Pico W: открытый USB, язычок над BOOTSEL и окно для светодиода"},
    },
    {
        "key": "phone-stand", "source": PHONE_STAND, "pack": "household",
        "title": {"en": "Phone stand", "ru": "Подставка для телефона"},
        "caption": {"en": "Lean angle and slot for your phone and case", "ru": "Наклон и паз под ваш телефон в чехле"},
        "prompt": {"en": "A desk stand for my phone in a case, leaning at about 68°", "ru": "Подставка на стол для телефона в чехле, наклон около 68°"},
    },
] if e["source"]]
BY_KEY = {e["key"]: e for e in EXAMPLES}

INTRO = {
    "en": "This is a ready example: the model is built and checked for printing. Change the sizes with the sliders or the "
          "handles on the model, or tell me what to change and I will rework it.",
    "ru": "Это готовый пример: модель собрана и проверена на печатность. Меняйте размеры ползунками или ручками на модели, "
          "а если нужно другое — напишите, и я доработаю.",
}
INTRO_PCB = {
    "en": "This is a ready example: a carrier board for the Seeed XIAO ESP32-C3, placed and routed on 2 layers ({traces} traces, "
          "{vias} vias) and checked: 0 DRC errors, and the design intent holds ({checked} checks: the connectors on their edges, the "
          "LED and the button on their GPIOs). Gerber, BOM and pick-and-place files are ready for the fab. The case is built from the "
          "same board description and checked with rays through its ports. Open the PCB tab to watch the routing, or tell me what "
          "to change on the board or the case.",
    "ru": "Это готовый пример: плата для Seeed XIAO ESP32-C3. Детали расставлены, дорожки разведены в 2 слоя (трасс: {traces}, "
          "переходных отверстий: {vias}) и проверены: ошибок DRC нет, замысел выполнен (проверок: {checked} — разъёмы на своих краях, "
          "светодиод и кнопка на своих GPIO). Файлы Gerber, BOM и расстановки готовы для завода. Корпус построен по описанию той же "
          "платы и проверен лучами через её разъёмы. Откройте вкладку «Плата», чтобы посмотреть разводку, или напишите, что поменять "
          "в плате или в корпусе.",
}

# a case example: what its check against the board measured (checks.enclosure of the cached build)
INTRO_CASE = {
    "en": "This is a ready example: a snap-fit case checked against the {board} itself, with rays from the board's own parts: "
          "{checks}. Switch to Print layout to see the parts as they print, change the fit with the sliders, or tell me what "
          "to change.",
    "ru": "Это готовый пример: корпус на защёлках, проверенный по самой плате {board} лучами от её деталей: {checks}. "
          "Переключитесь на раскладку для печати, чтобы увидеть детали так, как они печатаются, меняйте посадку ползунками "
          "или напишите, что поменять.",
}
CASE_CHECKS = {
    "usb": ("USB plug {v} mm clear", "зазор у разъёма USB {v} мм"),
    "button": ("{p} tab {v} mm over the button", "толкатель {p} в {v} мм над кнопкой"),
    "light": ("{p} window open", "окно {p} открыто"),
    "snaps": ("snaps bend {v} %", "защёлки гнутся на {v} %"),
}

# the spare part: what the fit check measured on its wire axle (_axle_fit of the cached build)
INTRO_PART = {
    "en": "This is a ready example: a replacement wheel for a dishwasher's lower rack, {d} mm across and {w} mm wide. Its fit "
          "on the {a} mm wire axle was checked with rays through the model: the axle hole is {hole} mm, and holes print about "
          "{shrink} mm small, so it turns with {play} mm of play; the snap neck is {neck} mm, {grip} mm narrower than the wire "
          "on each side, so it clicks on and stays on. Print it in PETG rather than PLA: a dishwasher is hot and wet. Match "
          "the sizes to your old wheel with the sliders, tell me what to change, or press Order a print to have it printed by "
          "the Axo farm.",
    "ru": "Это готовый пример: колёсико на замену для нижней корзины посудомойки, {d} мм в диаметре и {w} мм шириной. Посадку "
          "на проволочной оси {a} мм проверили лучами через модель: отверстие под ось {hole} мм, а отверстия печатаются "
          "примерно на {shrink} мм меньше, так что колесо вращается с зазором {play} мм; горловина защёлки {neck} мм — на "
          "{grip} мм уже проволоки с каждой стороны, поэтому колесо защёлкивается и не слетает. Печатайте из PETG, а не PLA: "
          "в посудомойке горячо и влажно. Подгоните размеры под старое колёсико ползунками, напишите, что поменять, или "
          "нажмите «Заказать печать», чтобы его напечатала ферма Axo.",
}
# mm: how much smaller holes print on the default printer (geom DEFAULT_PRINTER.holeDelta), which std.comp adds back
HOLE_SHRINK = 0.15

_lock = asyncio.Lock()
# Bump when the checks or the cover renderer change, so every cached cover and report is rebuilt.
REVISION = 5  # 3: lib.elec edge clips and the finer port cutter (USB 0.29 mm); 4: the XIAO carrier without engine warnings;
#               5: the spare-part wheel and its fit check
# A PCB example that did not route (no bundle, a failed build) is tried again after this long, not on every home page visit.
RETRY_S = 600.0
_failed: dict[str, float] = {}
_bundle: tuple[tuple[str, int, int], str] | None = None


def _stem(ex: dict[str, Any]) -> str:
    inputs = f":{json.dumps(ex['inputs'], sort_keys=True)}" if ex.get("inputs") else ""
    # a part with a fit check: what it measures is part of the key too
    fit = f":fit:{json.dumps(ex['fit'], sort_keys=True)}" if ex.get("fit") else ""
    digest = hashlib.sha1(f"{REVISION}:{ex['source']}{inputs}{fit}".encode()).hexdigest()[:10]
    return f"{ex['key']}-{digest}"


def _bundle_id() -> str | None:
    """A hash of the PCB worker bundle (None when it is not built): a rebuilt worker routes the example again."""
    global _bundle
    from .pcb import WORKER, dist_dir

    path = dist_dir() / WORKER
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_size, st.st_mtime_ns)
    if _bundle is None or _bundle[0] != key:
        _bundle = (key, hashlib.sha1(path.read_bytes()).hexdigest()[:10])
    return _bundle[1]


def _pcb_stem(ex: dict[str, Any]) -> str | None:
    bundle = _bundle_id()
    if bundle is None:
        return None
    digest = hashlib.sha1(f"{REVISION}:{bundle}:{ex['circuit']}:{ex['source']}:{ex['cover']}".encode()).hexdigest()[:10]
    return f"{ex['key']}-{digest}"


async def _case_check(ex: dict[str, Any], params: dict[str, Any]) -> dict[str, Any] | None:
    """checks.enclosure of a case example (C5), so the studio shows the plug rays and findings at once."""
    from .geom import geom

    boards = (ex.get("inputs") or {}).get("boards") or {}
    if not boards:
        return None
    name = "board" if "board" in boards else next(iter(boards))
    out = await geom().inspect(ex["source"], params, [{"op": "enclosure", "board": name}], inputs=ex["inputs"])
    return elec_tools.enclosure_checks(out["results"][0], name, boards[name], 1)


async def _axle_fit(ex: dict[str, Any], params: dict[str, Any]) -> dict[str, Any] | None:
    """The fit of a part that snaps onto a wire axle (ex['fit'] names its params): rays through the built model at half its
    width. Across the hole from the axle's centre, then from points along the snap slot (+X) to both of its walls: the
    narrowest of those is the neck the wire squeezes through on its way in."""
    from .geom import geom

    spec = ex["fit"]
    axle, r, z = float(params[spec["axle"]]), float(params[spec["diameter"]]) / 2, float(params[spec["width"]]) / 2

    def across(x: float) -> list[dict[str, Any]]:
        return [{"op": "ray", "from": [x, 0, z], "to": [x, sign * r, z]} for sign in (-1, 1)]

    async def widths(xs: list[float]) -> list[float | None]:
        out: list[float | None] = []
        for i in range(0, len(xs), 10):  # inspect takes 20 ops a call
            res = (await geom().inspect(ex["source"], params, [o for x in xs[i:i + 10] for o in across(x)]))["results"]
            for a, b in zip(res[::2], res[1::2]):
                out.append(a["hits"][0]["distance"] + b["hits"][0]["distance"] if a["hits"] and b["hits"] else None)
        return out

    [hole] = await widths([0.0])
    if hole is None:
        return None
    slot = [w for w in await widths([hole / 2 + 0.2 * i for i in range(1, int((r - hole / 2) / 0.2))]) if w is not None]
    if not slot:
        return None
    neck = min(slot)
    play, grip = hole - HOLE_SHRINK - axle, (axle - neck) / 2
    return {"axle": axle, "hole": round(hole, 3), "shrink": HOLE_SHRINK, "play": round(play, 3), "neck": round(neck, 3),
            "grip": round(grip, 3), "ok": play > 0 and grip > 0}


async def prepared(ex: dict[str, Any]) -> dict[str, Any] | None:
    """Cover (the same iso view as project covers), default params and checks: built once per program, kept on disk.
    An example's inputs (the board of a case) go into the build, the cover and the case check; the project opened
    from it gets them as its program's inputs."""
    from .geom import GeomError, geom

    if ex.get("circuit"):
        return await _prepared_pcb(ex)
    meta = storage.abs_path(f"examples/covers/{_stem(ex)}.json")
    if meta.exists():
        return json.loads(meta.read_text(encoding="utf-8"))
    async with _lock:
        if meta.exists():
            return json.loads(meta.read_text(encoding="utf-8"))
        extra = {"inputs": ex["inputs"]} if ex.get("inputs") else {}
        try:
            built = await geom().build(ex["source"], {}, analyze="full", **extra)
            png = await geom().render(ex["source"], built["params"], view="iso", tile=512, **extra)
            case = await _case_check(ex, built["params"])
            fit = await _axle_fit(ex, built["params"]) if ex.get("fit") else None
        except GeomError as e:
            log.warning("example %s does not build: %s", ex["key"], e)
            return None
        cover = storage.save_bytes("examples", "covers", f"{_stem(ex)}.png", base64.b64decode(png["png"]))
        checks = {**(built.get("checks") or {}), "enclosure": case} if case else built.get("checks")
        out = {"cover": cover, "params": built["params"], "checks": checks} | ({"fit": fit} if fit else {})
        storage.save_bytes("examples", "covers", meta.name, json.dumps(out).encode())
        return out


async def _prepared_pcb(ex: dict[str, Any]) -> dict[str, Any] | None:
    """The PCB example: its circuit routed and exported once into a whole PCB version (pcb_store.pack) kept under
    examples/pcb/<stem>, then the case from that version's board.json, built, checked and rendered like the other cases,
    with the board-in-its-case cover. None (the card stays off the home page) without the PCB bundle, or when the
    circuit does not route clean with its intent met."""
    from . import pcb, pcb_store
    from .geom import GeomError, geom

    stem = _pcb_stem(ex)
    if stem is None:
        return None
    meta = storage.abs_path(f"examples/covers/{stem}.json")
    folder = f"pcb/{stem}"
    have = lambda: meta.exists() and storage.abs_path(f"examples/{folder}/board.json").exists()  # noqa: E731
    if have():
        return json.loads(meta.read_text(encoding="utf-8"))
    if time.monotonic() - _failed.get(stem, -RETRY_S) < RETRY_S:
        return None
    async with _lock:
        if have():
            return json.loads(meta.read_text(encoding="utf-8"))
        try:
            build = await pcb.pool().build(ex["circuit"])
            if not build["ok"] or not build["intent"].get("ok"):
                raise pcb.PcbError("runtime", f"{len(build['errors'])} DRC errors, intent issues {build['intent'].get('issues')}")
            exported = await pcb.pool().export(build["circuit_json"])
        except pcb.PcbError as e:
            log.warning("example %s does not route: %s", ex["key"], e)
            _failed[stem] = time.monotonic()
            return None
        packed = pcb_store.pack(source=ex["circuit"], intent=None, build=build, files=exported, version=1)
        for name, data in packed["files"].items():
            storage.save_bytes("examples", folder, name, data.encode() if isinstance(data, str) else bytes(data))
        inputs = {"boards": {"board": json.loads(packed["files"]["board.json"])}}
        try:
            built = await geom().build(ex["source"], {}, analyze="full", inputs=inputs)
            png = await geom().render(ex["cover"], {}, view="iso", tile=512, inputs=inputs)
            case = await _case_check({**ex, "inputs": inputs}, built["params"])
        except GeomError as e:
            log.warning("example %s does not build: %s", ex["key"], e)
            _failed[stem] = time.monotonic()
            return None
        cover = storage.save_bytes("examples", "covers", f"{stem}.png", base64.b64decode(png["png"]))
        out = {"cover": cover, "params": built["params"], "checks": {**(built.get("checks") or {}), "enclosure": case}, "inputs": inputs,
               "pcb": {"files": f"examples/{folder}", "intent": packed["intent"], "checks": packed["checks"]}}
        storage.save_bytes("examples", "covers", meta.name, json.dumps(out).encode())
        return out


async def add_pcb(project_id: str, ready: dict[str, Any]) -> int:
    """The PCB example's routed board as the next PCB version of a project opened from it: the cached files are copied,
    nothing is routed again. Returns the version (1 in a new project, which is what the case's board.json names)."""
    from . import pcb_store

    p = ready["pcb"]
    folder = storage.abs_path(p["files"])
    files: dict[str, bytes | str] = {f.name: f.read_bytes() for f in folder.iterdir() if f.name in pcb_store.ARTIFACTS}
    return await pcb_store.add(project_id, {"source": files["circuit.tsx"].decode(), "intent": p["intent"], "checks": p["checks"], "files": files})


def intro(ex: dict[str, Any], ready: dict[str, Any], lang: str) -> str:
    """The studio's first agent message in a project opened from an example."""
    p = ready.get("pcb")
    if ready.get("fit"):
        return _intro_part(ready["fit"], ready["params"], ex, lang) or INTRO[lang]
    if not p:
        return _intro_case(((ready.get("checks") or {}).get("enclosure")) or {}, lang) or INTRO[lang]
    counts, checks = p["checks"].get("counts") or {}, p["checks"]
    return INTRO_PCB[lang].format(traces=counts.get("traces", 0), vias=counts.get("vias", 0), checked=(checks.get("intent") or {}).get("checked", 0))


def _intro_case(enc: dict[str, Any], lang: str) -> str | None:
    """INTRO_CASE from a passing case check, None without one (the plain INTRO then)."""
    if not enc.get("ok") or not enc.get("board_name"):
        return None
    ru = lang == "ru"
    s, fs = enc.get("summary") or {}, enc.get("findings") or []

    def num(v: Any) -> str:
        return f"{v:.2f}" if isinstance(v, (int, float)) else str(v)

    def part(code: str) -> str | None:
        f = next((f for f in fs if f.get("code") == code and f.get("severity") == "info"), None)
        return str(f.get("part") or "").upper().replace("_", " ") or None if f else None

    said = []
    if isinstance(s.get("usb_clearance_mm"), (int, float)):
        said.append(CASE_CHECKS["usb"][ru].format(v=num(s["usb_clearance_mm"])))
    if isinstance(s.get("button_gap_mm"), (int, float)) and (b := part("button_reach")):
        said.append(CASE_CHECKS["button"][ru].format(p=b, v=num(s["button_gap_mm"])))
    if (w := part("light_window")):
        said.append(CASE_CHECKS["light"][ru].format(p="светодиода" if ru and w == "LED" else w))
    if isinstance(s.get("snap_strain_pct"), (int, float)):
        said.append(CASE_CHECKS["snaps"][ru].format(v=f"{s['snap_strain_pct']:.1f}"))
    return INTRO_CASE[lang].format(board=enc["board_name"], checks=", ".join(said)) if said else None


def _intro_part(fit: dict[str, Any], params: dict[str, Any], ex: dict[str, Any], lang: str) -> str | None:
    """INTRO_PART from a passing fit check, None without one (the plain INTRO then)."""
    if not fit.get("ok"):
        return None
    spec = ex["fit"]
    return INTRO_PART[lang].format(d=f"{params[spec['diameter']]:g}", w=f"{params[spec['width']]:g}", a=f"{fit['axle']:g}",
                                   **{k: f"{fit[k]:.2f}" for k in ("hole", "shrink", "play", "neck", "grip")})


async def warm() -> None:
    try:
        for ex in EXAMPLES:
            await prepared(ex)
    except Exception:  # noqa: BLE001 - the home page retries on its own request
        log.exception("example warm-up failed")
