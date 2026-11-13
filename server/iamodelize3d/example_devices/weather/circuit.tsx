// Compiled from the device graph (fw.device/1) by IaModelize3d: parts on an edge and the designer's are where they
// were put, the rest next to the pins it connects, then autorouted on 2 layers.
export const meta = {"title": "Настольная метеостанция OLED", "intent": {"nets_max": 30, "edge": {"U1": "+y"}, "gpio": {"SW1": "U1.D1"}}, "device": true}

export default () => (
  <board width="46mm" height="55mm" thickness="1.6mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.6mm">
    <chip name="U1" manufacturerPartNumber="113991054" pcbX={0} pcbY={17} pinLabels={{ pin1: "D0", pin2: "D1", pin3: "D2", pin4: "D3", pin5: "SDA", pin6: "SCL", pin7: "TX", pin8: "RX", pin9: "SCK", pin10: "MISO", pin11: "MOSI", pin12: "V3V3", pin13: "GND", pin14: "V5" }} footprint={<footprint><platedhole portHints={["pin1"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={7.62} /><platedhole portHints={["pin2"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={5.08} /><platedhole portHints={["pin3"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={2.54} /><platedhole portHints={["pin4"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={0} /><platedhole portHints={["pin5"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-2.54} /><platedhole portHints={["pin6"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-5.08} /><platedhole portHints={["pin7"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-7.62} /><platedhole portHints={["pin8"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-7.62} /><platedhole portHints={["pin9"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-5.08} /><platedhole portHints={["pin10"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-2.54} /><platedhole portHints={["pin11"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={0} /><platedhole portHints={["pin12"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={2.54} /><platedhole portHints={["pin13"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={5.08} /><platedhole portHints={["pin14"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={7.62} /><courtyardrect pcbX={0} pcbY={0} width={16.94} height={16.94} /><silkscreenrect pcbX={0} pcbY={0} width={17.8} height={21} /><silkscreenrect pcbX={0} pcbY={7.85} width={8.94} height={7.3} /></footprint>} />
    <chip name="U2" footprint="lcsc:C92489" manufacturerPartNumber="BME280" supplierPartNumbers={{ jlcpcb: ["C92489"] }} pcbX={-12} pcbY={9.5} pcbRotation={90} pinLabels={{ pin1: "GND", pin2: "CSB", pin3: "SDI", pin4: "SCK", pin5: "SDO", pin6: "VDDIO", pin7: "GND_7", pin8: "VDD" }} />
    <capacitor name="C1" capacitance="100nF" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C14663"] }} pcbX={-14.52} pcbY={9.04} pcbRotation={90} maxDecouplingTraceLength={10} />
    <resistor name="R1" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={-12} pcbY={14} />
    <resistor name="R2" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={-16} pcbY={13.5} pcbRotation={270} />
    <chip name="DS1" manufacturerPartNumber="0.96in OLED 128x64 I2C (SSD1306)" supplierPartNumbers={{ jlcpcb: ["C2337"] }} pcbX={-3} pcbY={4.4} pinLabels={{ pin1: "GND", pin2: "VCC", pin3: "SCL", pin4: "SDA" }} footprint={<footprint><platedhole portHints={["pin1"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={-3.81} pcbY={0} /><platedhole portHints={["pin2"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={-1.27} pcbY={0} /><platedhole portHints={["pin3"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={1.27} pcbY={0} /><platedhole portHints={["pin4"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={3.81} pcbY={0} /><courtyardrect pcbX={0} pcbY={-12.4} width={27.3} height={27.8} /><silkscreenrect pcbX={0} pcbY={-12.4} width={27.3} height={27.8} /></footprint>} />
    <pushbutton name="SW1" footprint="pushbutton" internallyConnectedPins={[["pin1","pin2"],["pin3","pin4"]]} supplierPartNumbers={{ jlcpcb: ["C110153"] }} pcbX={15} pcbY={-14} />
    <hole name="H1" diameter="3.2mm" pcbX={-19.5} pcbY={24} />
    <hole name="H2" diameter="3.2mm" pcbX={19.5} pcbY={24} />
    <hole name="H3" diameter="3.2mm" pcbX={-19.5} pcbY={-24} />
    <hole name="H4" diameter="3.2mm" pcbX={19.5} pcbY={-24} />
    <trace from=".U1 > .GND" to="net.GND" />
    <trace from=".U2 > .GND" to="net.GND" />
    <trace from=".U2 > .GND_7" to="net.GND" />
    <trace from=".U2 > .SDO" to="net.GND" />
    <trace from=".C1 > .pin2" to=".U2 > .GND_7" />
    <trace from=".SW1 > .pin3" to="net.GND" />
    <trace from=".DS1 > .GND" to="net.GND" />
    <trace from=".U1 > .V3V3" to="net.V3V3" />
    <trace from=".U2 > .VDD" to="net.V3V3" />
    <trace from=".U2 > .VDDIO" to="net.V3V3" />
    <trace from=".U2 > .CSB" to="net.V3V3" />
    <trace from=".C1 > .pin1" to=".U2 > .VDD" />
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
    <trace from=".U1 > .D1" to=".SW1 > .pin1" />
  </board>
)
