// The home page's PCB example (server/formwright/showcase.py XIAO_CARRIER, the same code): a carrier board for a Seeed
// XIAO ESP32-C3 with USB-C power input, status LED, push button and a 4-pin I2C header. 0 DRC errors, 0 warnings.
// Only offline footprinter strings are used (no jlcpcb:/kicad: footprints, no network).
// What the design promises, checked by the build next to DRC (src/intent.mjs).
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
