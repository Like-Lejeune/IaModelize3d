"""Model-facing text of the 'pcb' pack: the rules of the circuit file (a tscircuit TSX subset that builds offline in the
PCB worker), the verified reference board and the classifier line. Everything here is English: models read it.

EXAMPLE is the reference board the engine is tested with (packages/pcb/test/fixtures/carrier.tsx, comments for the model):
a Raspberry Pi Pico carrier, on purpose not the home page's XIAO board (showcase.XIAO_CARRIER), so a XIAO brief gets
designed rather than copied. The tests build it and expect 0 DRC errors, 0 warnings and a met intent, so the designer only
ever learns from a clean one.
"""
from __future__ import annotations

PACK_TEXT = """
# Pack: printed circuit boards (a carrier or small custom board, then its 3D-printed case)
Here the board is a tscircuit TSX file built with write_circuit, not a JavaScript program; the JS program format above is
only for the case, which make_enclosure writes for you. Flow: write_circuit -> fix every error with its hint (write_circuit
with `edits`) -> export_fab -> make_enclosure -> finish. A build places nothing itself: it checks your placement,
autoroutes 2 layers, runs DRC and your intent checks, and describes the board for the case; a clean build gets fab files.
Choose pins, values and the layout yourself and say which in the summary; ask only what changes the board's purpose.

## The file
export const meta = { title: 'XIAO ESP32-C3 carrier', intent: { edge: { J1: '-y', J2: '+x', U1: '+y' }, gpio: { LED1: 'D10', SW1: 'D1' }, nets_max: 30 } };
export default () => (<board width="44mm" height="36mm" thickness="1.6mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.6mm"> ... </board>);
TSX only: no imports, hooks or helper code. Units mm. pcbX/pcbY are part centres relative to the board centre (0,0), +x right,
+y up (towards the top edge). Board as small as the parts allow, at most 100 x 100 mm, 30 nets, 40 parts; copper 1 mm from the edge.

## Intent (checked on every build; finish needs it stated and met)
edge: the part on each edge, its opening facing out ('-x'|'+x'|'-y'|'+y' or left/right/bottom/top): every connector and a
module whose own USB must face out. gpio: the pin that drives each LED and button ('D10', or 'U1.D10'; aliases such as GPIO10
work). nets_max. DRC cannot see these: a "status" LED on 3V3 or a header in the middle of the board passes DRC, not the intent.

## Parts (only these footprint strings, generated offline; never jlcpcb:, kicad: or standard=)
- <resistor name="R1" resistance="1k" footprint="0603" />, <capacitor name="C1" capacitance="100nF" footprint="0603" />: pin1,
  pin2 (0402, 0805, 1206 too). <led name="LED1" color="green" footprint="0603" />: anode, cathode; always with a series resistor.
- <diode name="D1" footprint="sod123" manufacturerPartNumber="B5819W" />: anode, cathode (Schottky).
- <pushbutton name="SW1" footprint="pushbutton" internallyConnectedPins={[["pin1","pin2"],["pin3","pin4"]]} />: 6x6 mm THT, 4 legs
  but 2 contacts: pins 1-2 are one, 3-4 the other. GPIO to pin1, GND to pin3 (pull-up); pin1 + pin2 would short them.
- <pinheader name="J2" pinCount={4} pitch="2.54mm" pinLabels={["V3V3","GND","SDA","SCL"]} />: pins by label; pcbRotation={90}
  runs it along y. Chips: <chip name="U2" footprint="soic8" pinLabels={{ pin1: "...", ... }} /> (also sot23, jst2).
- USB-C receptacle, 16 pins, power only, exact labels: <chip name="J1" footprint="usbcmidmount" manufacturerPartNumber="TYPE-C-31-M-12"
  pinLabels={{ pin1:"SH1", pin2:"SH2", pin3:"SH3", pin4:"SH4", pin5:"GND_A", pin6:"VBUS_A", pin7:"SBU2", pin8:"CC1", pin9:"DN2",
  pin10:"DP1", pin11:"DN1", pin12:"DP2", pin13:"SBU1", pin14:"CC2", pin15:"VBUS_B", pin16:"GND_B" }} />. 5 V sink: CC1 and CC2 each
  through 5.1k to GND; wire VBUS_A, VBUS_B, GND_A, GND_B, SH1. Its body spans y -5.5..+2.9 around its origin and the plug enters
  from -y: on the bottom edge pcbY = -(height/2) + 5.5; pcbRotation={90} turns it to +x (pcbX = width/2 - 5.5), {270} to -x.
- Seeed XIAO ESP32-C3 on two 7-pin headers, exact (the manufacturerPartNumber makes it a module, its own USB-C included):
  <chip name="U1" footprint="dip14_w15.24mm" manufacturerPartNumber="113991054" pinLabels={{ pin1:"D0", pin2:"D1", pin3:"D2",
  pin4:"D3", pin5:"SDA", pin6:"SCL", pin7:"TX", pin8:"RX", pin9:"SCK", pin10:"MISO", pin11:"MOSI", pin12:"V3V3", pin13:"GND",
  pin14:"V5" }} />. 17.8 x 21 mm, its USB-C at the +y end: on the top edge pcbY = height/2 - 10.5. It decouples its own supply.
  Aliases: D10 = MOSI = GPIO10, D1 = GPIO3, SDA = D4, SCL = D5. 5 V from another USB-C goes into V5 through the Schottky
  (anode on VBUS), so a cable in the XIAO's own port cannot back-feed.
- Raspberry Pi Pico on two 20-pin headers: footprint="dip40_w17.78mm" manufacturerPartNumber="SC0915" (Pico W "SC0918"), pinLabels
  exactly as in the reference board (GP0..GP28, GND, V3V3, VSYS, VBUS, RUN; aliases GPIO15 = GP15). 21 x 51 mm, micro-USB at
  the +y end: on the top edge pcbY = height/2 - 25.75. Another 5 V source goes into VSYS through the Schottky.
- <hole name="H1" diameter="3.2mm" pcbX={...} pcbY={...} />: M3 mounting holes about 3.5 mm in from two edges, 2 mm clear of parts.
An edge part's body ends within 1 mm of the edge: a header turned along y sits at pcbX = +-(width/2 - 2.5), along x at
pcbY = +-(height/2 - 2.5). Every part has explicit pcbX, pcbY and optional pcbRotation={90|180|270}. Courtyards (w x h at rotation 0): 0603 2.2x1.2,
sod123 4.5x2, pushbutton 7x9, 4-pin header 11.2x3.5, usbcmidmount 10.4x8.4, XIAO 17.4x18.3, Pico 19.9x51.3; no overlaps with
parts, holes or the edge. Optional BOM numbers: supplierPartNumbers={{ jlcpcb: ["C23186"] }} (kept as written, not verified).

## Connections
<trace from=".J1 > .CC1" to=".R1 > .pin1" />: selectors .<name> > .<pin label or pinN>. Nets: to="net.GND", to="net.VBUS"; a net
name starts with a letter or underscore (net.V3V3, never net.3V3). Run the 5 V path pin to pin with thickness="0.4mm"
(.J1 > .VBUS_A to .D1 > .anode, .D1 > .cathode to .U1 > .V5): a width on a trace to a net is dropped (0.2 mm). Never give
trace coordinates: the autorouter routes.

## Rules DRC enforces without saying so
- A 100nF capacitor between a supply and GND counts as decoupling: both its traces must be <= 1 mm, so its pads sit at the pins
  it decouples; or leave it out where a module decouples itself.
- Copper keeps 0.2 mm from non-plated pegs (the USB-C shell): join twin pins (.J1 > .VBUS_B to .J1 > .VBUS_A) instead of
  routing both past the pegs to a net.
- Errors come root cause first, each with a hint ("move SW1 by +2.22 mm in y (pcbY -7 -> -4.78)"). Routing is skipped while
  placement errors remain, so fix those first; routing is deterministic, so a failing layout has to change.
- Warnings are shown to the person next to DRC. Two are design faults: "pin3 on SW1 is missing a trace" (the switch legs are wired
  wrong) and "routed thinner than requested" (a via squeezed the 5 V path: move the parts beside it 1-2 mm). Style notes on
  segment angles are the router's own: leave them.

## Fixing and finishing
- After a build apply the hints (edits on the current file), rewire or move parts for intent issues, and build again until
  0 errors and intent ok (usually 1-3 rounds). look(what='pcb') shows the routed board.
- export_fab gives the links (Gerber zip, BOM, CPL). LCSC numbers and CPL rotations are not checked yet: say so.
- make_enclosure builds the snap-fit case from the same board.json and checks plug paths, buttons and LEDs; with_mockup adds a
  printed 1.6 mm stand-in plate of the PCB, to try the real module in the case before the board is made. Case errors:
  its options (port_fit, clear, standoff) or move the part on the board. Its size is case_fit.case_mm (not size_mm).
- finish needs the latest version with 0 DRC errors, intent stated and ok, fab files, and a case of that version without errors.
- Summary: what the board does and which pin drives what, size, DRC 0, fab files (2 layers; a fab house makes and assembles it,
  which takes weeks), the case (print time, the mock-up plate) and what is unverified (LCSC numbers, rotations, part heights).
""".strip()

EXAMPLE = r"""
// Reference board: a carrier for a Raspberry Pi Pico with USB-C power input, a user button, a status LED and a 4-pin I2C
// header. Built: 0 DRC errors, 0 warnings, intent met. Learn its patterns; your board places its own parts.
// Only offline footprint strings are used (no jlcpcb:/kicad: footprints, no network).
// What the design promises: checked on every build next to DRC.
export const meta = {
  title: "Pico carrier",
  intent: { edge: { U1: "+y", J1: "+x", J2: "-y" }, gpio: { LED1: "GP15", SW1: "GP14" }, nets_max: 30 },
}

export default () => (
  <board width="46mm" height="62mm" thickness="1.6mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.6mm">
    {/* Raspberry Pi Pico on two 20-pin 2.54 mm rows, 17.78 mm apart; a module by its part number: its own micro-USB faces the top edge */}
    <chip
      name="U1"
      footprint="dip40_w17.78mm"
      manufacturerPartNumber="SC0915"
      pcbX={-5.5}
      pcbY={5.25}
      pinLabels={{
        pin1: "GP0", pin2: "GP1", pin3: "GND3", pin4: "GP2", pin5: "GP3", pin6: "GP4", pin7: "GP5", pin8: "GND8", pin9: "GP6",
        pin10: "GP7", pin11: "GP8", pin12: "GP9", pin13: "GND13", pin14: "GP10", pin15: "GP11", pin16: "GP12", pin17: "GP13",
        pin18: "GND18", pin19: "GP14", pin20: "GP15", pin21: "GP16", pin22: "GP17", pin23: "GND23", pin24: "GP18", pin25: "GP19",
        pin26: "GP20", pin27: "GP21", pin28: "GND28", pin29: "GP22", pin30: "RUN", pin31: "GP26", pin32: "GP27", pin33: "AGND",
        pin34: "GP28", pin35: "ADC_VREF", pin36: "V3V3", pin37: "V3V3_EN", pin38: "GND", pin39: "VSYS", pin40: "VBUS",
      }}
    />
    {/* USB-C power input turned to the right edge (pcbRotation 90: the plug enters from +x); CC pull-downs make it a 5 V sink */}
    <chip
      name="J1"
      footprint="usbcmidmount"
      manufacturerPartNumber="TYPE-C-31-M-12"
      supplierPartNumbers={{ jlcpcb: ["C165948"] }}
      pcbX={17.5}
      pcbY={18}
      pcbRotation={90}
      pinLabels={{
        pin1: "SH1", pin2: "SH2", pin3: "SH3", pin4: "SH4",
        pin5: "GND_A", pin6: "VBUS_A", pin7: "SBU2", pin8: "CC1", pin9: "DN2", pin10: "DP1",
        pin11: "DN1", pin12: "DP2", pin13: "SBU1", pin14: "CC2", pin15: "VBUS_B", pin16: "GND_B",
      }}
    />
    <resistor name="R1" resistance="5.1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23186"] }} pcbX={10} pcbY={12} pcbRotation={90} />
    <resistor name="R2" resistance="5.1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23186"] }} pcbX={10} pcbY={21} pcbRotation={90} />
    {/* Schottky from the USB-C VBUS into VSYS, the Pico datasheet's way to add a supply: neither USB port back-feeds the other */}
    <diode name="D1" footprint="sod123" manufacturerPartNumber="B5819W" supplierPartNumbers={{ jlcpcb: ["C8598"] }} pcbX={9} pcbY={28} pcbRotation={180} />
    {/* status LED on GP15 through its series resistor, in the strip left of the Pico */}
    <resistor name="R3" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={-20} pcbY={-9} pcbRotation={90} />
    <led name="LED1" color="green" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C72043"] }} pcbX={-20} pcbY={-14} pcbRotation={90} />
    {/* user button on GP14 to GND, internal pull-up; legs 1-2 and 3-4 are one contact each, so GP14 goes to pin1 and GND to pin3 */}
    <pushbutton name="SW1" footprint="pushbutton" internallyConnectedPins={[["pin1", "pin2"], ["pin3", "pin4"]]} pcbX={-10} pcbY={-25.5} />
    {/* 4-pin I2C header along the bottom edge: 3V3, GND, SDA (GP18), SCL (GP19); 4.7k pull-ups next to the Pico */}
    <pinheader name="J2" pinCount={4} pitch="2.54mm" pcbX={6} pcbY={-28.5} pinLabels={["V3V3", "GND", "SDA", "SCL"]} />
    <resistor name="R4" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={8} pcbY={-20} pcbRotation={90} />
    <resistor name="R5" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={11} pcbY={-20} pcbRotation={90} />
    {/* M3 mounting holes */}
    <hole name="H1" diameter="3.2mm" pcbX={-19.5} pcbY={27.5} />
    <hole name="H2" diameter="3.2mm" pcbX={19.5} pcbY={27.5} />
    <hole name="H3" diameter="3.2mm" pcbX={-19.5} pcbY={-27.5} />
    <hole name="H4" diameter="3.2mm" pcbX={19.5} pcbY={-27.5} />

    {/* the 5 V path pin to pin, so its 0.4 mm width is kept (a width on a trace to a net is not) */}
    <trace from=".J1 > .VBUS_A" to=".D1 > .anode" thickness="0.4mm" />
    <trace from=".D1 > .cathode" to=".U1 > .VSYS" thickness="0.4mm" />
    <trace from=".J1 > .VBUS_B" to=".J1 > .VBUS_A" />
    <trace from=".J1 > .GND_A" to="net.GND" />
    <trace from=".J1 > .GND_B" to="net.GND" />
    <trace from=".J1 > .SH1" to="net.GND" />
    <trace from=".J1 > .CC1" to=".R1 > .pin1" />
    <trace from=".R1 > .pin2" to="net.GND" />
    <trace from=".J1 > .CC2" to=".R2 > .pin1" />
    <trace from=".R2 > .pin2" to="net.GND" />
    <trace from=".U1 > .GND" to="net.GND" />
    <trace from=".U1 > .GP15" to=".R3 > .pin1" />
    <trace from=".R3 > .pin2" to=".LED1 > .anode" />
    <trace from=".LED1 > .cathode" to="net.GND" />
    <trace from=".U1 > .GP14" to=".SW1 > .pin1" />
    <trace from=".SW1 > .pin3" to="net.GND" />
    <trace from=".J2 > .V3V3" to=".U1 > .V3V3" />
    <trace from=".J2 > .GND" to="net.GND" />
    <trace from=".J2 > .SDA" to=".U1 > .GP18" />
    <trace from=".J2 > .SCL" to=".U1 > .GP19" />
    <trace from=".R4 > .pin1" to=".U1 > .V3V3" />
    <trace from=".R4 > .pin2" to=".U1 > .GP18" />
    <trace from=".R5 > .pin1" to=".U1 > .V3V3" />
    <trace from=".R5 > .pin2" to=".U1 > .GP19" />
  </board>
)
""".lstrip("\n")

CLASSIFY_HINT = ("pcb (design a printed circuit board itself: a carrier or breakout board for a module such as a XIAO ESP32-C3, a small "
                 "board with USB-C, buttons, LEDs, headers; schematic, routing, Gerbers, then its case)")
