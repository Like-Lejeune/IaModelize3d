// Compiled from the device graph (fw.device/1) by Formwright: parts on an edge and the designer's are where they
// were put, the rest next to the pins it connects, then autorouted on 2 layers.
export const meta = {"title": "Home Weather Station", "intent": {"nets_max": 30, "edge": {"U1": "-y"}, "gpio": {"LED1": "U1.MOSI", "SW1": "U1.D1"}}, "device": true}

export default () => (
  <board width="46mm" height="50mm" thickness="1.6mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.6mm">
    <chip name="U1" footprint="dip14_w15.24mm" manufacturerPartNumber="113991054" pcbX={0} pcbY={-14.5} pcbRotation={180} pinLabels={{ pin1: "D0", pin2: "D1", pin3: "D2", pin4: "D3", pin5: "SDA", pin6: "SCL", pin7: "TX", pin8: "RX", pin9: "SCK", pin10: "MISO", pin11: "MOSI", pin12: "V3V3", pin13: "GND", pin14: "V5" }} />
    <chip name="U2" footprint="lcsc:C92489" manufacturerPartNumber="BME280" supplierPartNumbers={{ jlcpcb: ["C92489"] }} pcbX={-12.5} pcbY={-17} pcbRotation={90} pinLabels={{ pin1: "GND", pin2: "CSB", pin3: "SDI", pin4: "SCK", pin5: "SDO", pin6: "VDDIO", pin7: "GND_7", pin8: "VDD" }} />
    <capacitor name="C1" capacitance="100nF" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C14663"] }} pcbX={-17} pcbY={-17} pcbRotation={90} maxDecouplingTraceLength={25} />
    <resistor name="R1" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={-12.5} pcbY={-22} />
    <resistor name="R2" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={-19} pcbY={-12.5} />
    <resistor name="R3" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={-14} pcbY={-8.5} pcbRotation={180} />
    <led name="LED1" color="green" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C12624"] }} pcbX={-14} pcbY={-12} />
    <pushbutton name="SW1" footprint="pushbutton" internallyConnectedPins={[["pin1","pin2"],["pin3","pin4"]]} supplierPartNumbers={{ jlcpcb: ["C110153"] }} pcbX={14} pcbY={-12} />
    <chip name="DS1" manufacturerPartNumber="0.96in OLED 128x64 I2C (SSD1306)" supplierPartNumbers={{ jlcpcb: ["C2337"] }} pcbX={0} pcbY={22.4} pinLabels={{ pin1: "GND", pin2: "VCC", pin3: "SCL", pin4: "SDA" }} footprint={<footprint><platedhole portHints={["pin1"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={-3.81} pcbY={0} /><platedhole portHints={["pin2"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={-1.27} pcbY={0} /><platedhole portHints={["pin3"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={1.27} pcbY={0} /><platedhole portHints={["pin4"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={3.81} pcbY={0} /><courtyardrect pcbX={0} pcbY={-12.4} width={27.3} height={27.8} /><silkscreenrect pcbX={0} pcbY={-12.4} width={27.3} height={27.8} /></footprint>} />
    <hole name="H1" diameter="3.2mm" pcbX={-19.5} pcbY={21.5} />
    <hole name="H2" diameter="3.2mm" pcbX={19.5} pcbY={21.5} />
    <hole name="H3" diameter="3.2mm" pcbX={-19.5} pcbY={-21.5} />
    <hole name="H4" diameter="3.2mm" pcbX={19.5} pcbY={-21.5} />
    <trace from=".U1 > .GND" to="net.N1" />
    <trace from=".U2 > .GND" to="net.N1" />
    <trace from=".U2 > .GND_7" to="net.N1" />
    <trace from=".U2 > .SDO" to="net.N1" />
    <trace from=".C1 > .pin2" to="net.N1" />
    <trace from=".LED1 > .cathode" to="net.N1" />
    <trace from=".SW1 > .pin3" to="net.N1" />
    <trace from=".DS1 > .GND" to="net.N1" />
    <trace from=".U1 > .V3V3" to="net.V3V3" />
    <trace from=".U2 > .VDD" to="net.V3V3" />
    <trace from=".U2 > .VDDIO" to="net.V3V3" />
    <trace from=".U2 > .CSB" to="net.V3V3" />
    <trace from=".C1 > .pin1" to="net.V3V3" />
    <trace from=".R1 > .pin1" to="net.V3V3" />
    <trace from=".R2 > .pin1" to="net.V3V3" />
    <trace from=".DS1 > .VCC" to="net.V3V3" />
    <trace from=".U1 > .SDA" to="net.SDA" />
    <trace from=".U2 > .SDI" to="net.SDA" />
    <trace from=".R1 > .pin2" to="net.SDA" />
    <trace from=".DS1 > .SDA" to="net.SDA" />
    <trace from=".U1 > .SCL" to="net.SCL" />
    <trace from=".U2 > .SCK" to="net.SCL" />
    <trace from=".R2 > .pin2" to="net.SCL" />
    <trace from=".DS1 > .SCL" to="net.SCL" />
    <trace from=".U1 > .MOSI" to=".R3 > .pin1" />
    <trace from=".R3 > .pin2" to=".LED1 > .anode" />
    <trace from=".U1 > .D1" to=".SW1 > .pin1" />
  </board>
)
