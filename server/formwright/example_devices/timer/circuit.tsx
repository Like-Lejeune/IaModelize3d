// Compiled from the device graph (fw.device/1) by Formwright: parts on an edge and the designer's are where they
// were put, the rest next to the pins it connects, then autorouted on 2 layers.
export const meta = {"title": "Kitchen Timer", "intent": {"nets_max": 30, "edge": {"U1": "-y"}, "gpio": {"SW1": "U1.D1", "SW2": "U1.D2", "SW3": "U1.D3", "LED1": "U1.RX"}}, "device": true}

export default () => (
  <board width="76mm" height="72mm" thickness="1.6mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.6mm">
    <chip name="U1" footprint="dip14_w15.24mm" manufacturerPartNumber="113991054" pcbX={0} pcbY={-25.5} pcbRotation={180} pinLabels={{ pin1: "D0", pin2: "D1", pin3: "D2", pin4: "D3", pin5: "SDA", pin6: "SCL", pin7: "TX", pin8: "RX", pin9: "SCK", pin10: "MISO", pin11: "MOSI", pin12: "V3V3", pin13: "GND", pin14: "V5" }} />
    <chip name="DS1" manufacturerPartNumber="0.96in OLED 128x64 I2C (SSD1306)" supplierPartNumbers={{ jlcpcb: ["C2337"] }} pcbX={-12} pcbY={26.4} pinLabels={{ pin1: "GND", pin2: "VCC", pin3: "SCL", pin4: "SDA" }} footprint={<footprint><platedhole portHints={["pin1"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={-3.81} pcbY={0} /><platedhole portHints={["pin2"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={-1.27} pcbY={0} /><platedhole portHints={["pin3"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={1.27} pcbY={0} /><platedhole portHints={["pin4"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={3.81} pcbY={0} /><courtyardrect pcbX={0} pcbY={-12.4} width={27.3} height={27.8} /><silkscreenrect pcbX={0} pcbY={-12.4} width={27.3} height={27.8} /></footprint>} />
    <pushbutton name="SW1" footprint="pushbutton" internallyConnectedPins={[["pin1","pin2"],["pin3","pin4"]]} supplierPartNumbers={{ jlcpcb: ["C110153"] }} pcbX={-16} pcbY={-10} />
    <pushbutton name="SW2" footprint="pushbutton" internallyConnectedPins={[["pin1","pin2"],["pin3","pin4"]]} supplierPartNumbers={{ jlcpcb: ["C110153"] }} pcbX={0} pcbY={-10} />
    <pushbutton name="SW3" footprint="pushbutton" internallyConnectedPins={[["pin1","pin2"],["pin3","pin4"]]} supplierPartNumbers={{ jlcpcb: ["C110153"] }} pcbX={16} pcbY={-10} />
    <chip name="BZ1" footprint="lcsc:C781847" manufacturerPartNumber="YX-YT9042 3v" supplierPartNumbers={{ jlcpcb: ["C781847"] }} pcbX={-31} pcbY={-2} pinLabels={{ pin1: "POS", pin2: "NEG" }} />
    <chip name="Q1" footprint="lcsc:C2146" manufacturerPartNumber="S8050 J3Y(RANGE:200-350)" supplierPartNumbers={{ jlcpcb: ["C2146"] }} pcbX={-23} pcbY={-3.5} pcbRotation={270} pinLabels={{ pin1: "B", pin2: "E", pin3: "C" }} />
    <resistor name="RB" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={-23.5} pcbY={-8.5} pcbRotation={90} />
    <diode name="D1" footprint="sod123" manufacturerPartNumber="B5819W" supplierPartNumbers={{ jlcpcb: ["C8598"] }} pcbX={-17.5} pcbY={-2.5} />
    <led name="LED1" color="green" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C12624"] }} pcbX={30} pcbY={2} />
    <resistor name="R4" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={25.5} pcbY={1} />
    <resistor name="R1" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={-9} pcbY={30.5} />
    <resistor name="R2" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={-13} pcbY={31} pcbRotation={270} />
    <hole name="H1" diameter="3.2mm" pcbX={-34.5} pcbY={32.5} />
    <hole name="H2" diameter="3.2mm" pcbX={34.5} pcbY={32.5} />
    <hole name="H3" diameter="3.2mm" pcbX={-34.5} pcbY={-32.5} />
    <hole name="H4" diameter="3.2mm" pcbX={34.5} pcbY={-32.5} />
    <trace from=".U1 > .GND" to="net.GND" />
    <trace from=".DS1 > .GND" to="net.GND" />
    <trace from=".SW1 > .pin3" to="net.GND" />
    <trace from=".SW2 > .pin3" to="net.GND" />
    <trace from=".SW3 > .pin3" to="net.GND" />
    <trace from=".Q1 > .E" to="net.GND" />
    <trace from=".LED1 > .cathode" to="net.GND" />
    <trace from=".U1 > .V3V3" to="net.V3V3" />
    <trace from=".DS1 > .VCC" to="net.V3V3" />
    <trace from=".R1 > .pin1" to="net.V3V3" />
    <trace from=".R2 > .pin1" to="net.V3V3" />
    <trace from=".BZ1 > .POS" to="net.V3V3" />
    <trace from=".D1 > .cathode" to="net.V3V3" />
    <trace from=".U1 > .SDA" to="net.SDA" />
    <trace from=".DS1 > .SDA" to="net.SDA" />
    <trace from=".R1 > .pin2" to="net.SDA" />
    <trace from=".U1 > .SCL" to="net.SCL" />
    <trace from=".DS1 > .SCL" to="net.SCL" />
    <trace from=".R2 > .pin2" to="net.SCL" />
    <trace from=".U1 > .D1" to=".SW1 > .pin1" />
    <trace from=".U1 > .D2" to=".SW2 > .pin1" />
    <trace from=".U1 > .D3" to=".SW3 > .pin1" />
    <trace from=".U1 > .MOSI" to=".RB > .pin1" />
    <trace from=".RB > .pin2" to=".Q1 > .B" />
    <trace from=".Q1 > .C" to="net.N1" />
    <trace from=".BZ1 > .NEG" to="net.N1" />
    <trace from=".D1 > .anode" to="net.N1" />
    <trace from=".U1 > .RX" to=".R4 > .pin1" />
    <trace from=".R4 > .pin2" to=".LED1 > .anode" />
  </board>
)
