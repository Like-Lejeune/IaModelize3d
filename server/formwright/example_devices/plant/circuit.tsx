// Compiled from the device graph (fw.device/1) by Formwright: parts on an edge and the designer's are where they
// were put, the rest next to the pins it connects, then autorouted on 2 layers.
export const meta = {"title": "Houseplant Soil Moisture Sensor", "intent": {"nets_max": 30, "edge": {"U1": "+y", "PR1": "-y"}, "gpio": {"SW1": "U1.D1"}}, "device": true}

export default () => (
  <board width="46mm" height="58mm" thickness="1.6mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.6mm">
    <chip name="U1" footprint="dip14_w15.24mm" manufacturerPartNumber="113991054" pcbX={0} pcbY={18.5} pinLabels={{ pin1: "D0", pin2: "D1", pin3: "D2", pin4: "D3", pin5: "SDA", pin6: "SCL", pin7: "TX", pin8: "RX", pin9: "SCK", pin10: "MISO", pin11: "MOSI", pin12: "V3V3", pin13: "GND", pin14: "V5" }} />
    <chip name="DS1" manufacturerPartNumber="0.96in OLED 128x64 I2C (SSD1306)" supplierPartNumbers={{ jlcpcb: ["C2337"] }} pcbX={0} pcbY={4.4} pinLabels={{ pin1: "GND", pin2: "VCC", pin3: "SCL", pin4: "SDA" }} footprint={<footprint><platedhole portHints={["pin1"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={-3.81} pcbY={0} /><platedhole portHints={["pin2"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={-1.27} pcbY={0} /><platedhole portHints={["pin3"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={1.27} pcbY={0} /><platedhole portHints={["pin4"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={3.81} pcbY={0} /><courtyardrect pcbX={0} pcbY={-12.4} width={27.3} height={27.8} /><silkscreenrect pcbX={0} pcbY={-12.4} width={27.3} height={27.8} /></footprint>} />
    <pinheader name="PR1" pinCount={3} pitch="2.54mm" pinLabels={["GND", "VCC", "AOUT"]} supplierPartNumbers={{ jlcpcb: ["C2337"] }} pcbX={0} pcbY={-26.5} />
    <pushbutton name="SW1" footprint="pushbutton" internallyConnectedPins={[["pin1","pin2"],["pin3","pin4"]]} supplierPartNumbers={{ jlcpcb: ["C110153"] }} pcbX={14} pcbY={12} />
    <resistor name="R1" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={-11.5} pcbY={14} pcbRotation={270} />
    <resistor name="R2" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={-12} pcbY={10} pcbRotation={180} />
    <hole name="H1" diameter="3.2mm" pcbX={-19.5} pcbY={25.5} />
    <hole name="H2" diameter="3.2mm" pcbX={19.5} pcbY={25.5} />
    <hole name="H3" diameter="3.2mm" pcbX={-19.5} pcbY={-25.5} />
    <hole name="H4" diameter="3.2mm" pcbX={19.5} pcbY={-25.5} />
    <trace from=".U1 > .GND" to="net.GND" />
    <trace from=".DS1 > .GND" to="net.GND" />
    <trace from=".PR1 > .GND" to="net.GND" />
    <trace from=".SW1 > .pin3" to="net.GND" />
    <trace from=".U1 > .V3V3" to="net.V3V3" />
    <trace from=".DS1 > .VCC" to="net.V3V3" />
    <trace from=".R1 > .pin2" to="net.V3V3" />
    <trace from=".R2 > .pin2" to="net.V3V3" />
    <trace from=".U1 > .SDA" to="net.SDA" />
    <trace from=".DS1 > .SDA" to="net.SDA" />
    <trace from=".R1 > .pin1" to="net.SDA" />
    <trace from=".U1 > .SCL" to="net.SCL" />
    <trace from=".DS1 > .SCL" to="net.SCL" />
    <trace from=".R2 > .pin1" to="net.SCL" />
    <trace from=".U1 > .D2" to=".PR1 > .AOUT" />
    <trace from=".U1 > .D1" to=".SW1 > .pin1" />
    <trace from=".U1 > .MOSI" to=".PR1 > .VCC" />
  </board>
)
