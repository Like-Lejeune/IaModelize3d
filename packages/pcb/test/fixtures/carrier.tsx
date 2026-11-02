// The designer's reference board (server/formwright/agent/pcb_prompt.py EXAMPLE, the same code with comments for the
// model): a carrier for a Raspberry Pi Pico with USB-C power input, user button, status LED and a 4-pin I2C header.
// A different board from the home page's XIAO example, so a XIAO brief is designed, not copied. 0 DRC errors, 0 warnings.
// Only offline footprinter strings are used (no jlcpcb:/kicad: footprints, no network).
// What the design promises, checked by the build next to DRC (src/intent.mjs).
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
