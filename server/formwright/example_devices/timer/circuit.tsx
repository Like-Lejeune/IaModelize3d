// Compiled from the device graph (fw.device/1) by Formwright: parts on an edge and the designer's are where they
// were put, the rest next to the pins it connects, then autorouted on 2 layers.
export const meta = {"title": "Кухонный таймер", "intent": {"nets_max": 30, "edge": {"U1": "+x"}, "gpio": {"SW1": "U1.D1", "SW2": "U1.D2", "SW3": "U1.D3"}}, "device": true}

export default () => (
  <board width="70mm" height="50mm" thickness="1.6mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.6mm">
    <chip name="U1" manufacturerPartNumber="113991054" pcbX={24.5} pcbY={0} pcbRotation={270} pinLabels={{ pin1: "D0", pin2: "D1", pin3: "D2", pin4: "D3", pin5: "SDA", pin6: "SCL", pin7: "TX", pin8: "RX", pin9: "SCK", pin10: "MISO", pin11: "MOSI", pin12: "V3V3", pin13: "GND", pin14: "V5" }} footprint={<footprint><platedhole portHints={["pin1"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={7.62} /><platedhole portHints={["pin2"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={5.08} /><platedhole portHints={["pin3"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={2.54} /><platedhole portHints={["pin4"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={0} /><platedhole portHints={["pin5"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-2.54} /><platedhole portHints={["pin6"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-5.08} /><platedhole portHints={["pin7"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-7.62} /><platedhole portHints={["pin8"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-7.62} /><platedhole portHints={["pin9"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-5.08} /><platedhole portHints={["pin10"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-2.54} /><platedhole portHints={["pin11"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={0} /><platedhole portHints={["pin12"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={2.54} /><platedhole portHints={["pin13"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={5.08} /><platedhole portHints={["pin14"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={7.62} /><courtyardrect pcbX={0} pcbY={0} width={16.94} height={16.94} /><silkscreenrect pcbX={0} pcbY={0} width={17.8} height={21} /><silkscreenrect pcbX={0} pcbY={7.85} width={8.94} height={7.3} /></footprint>} />
    <chip name="DS1" manufacturerPartNumber="0.96in OLED 128x64 I2C (SSD1306)" supplierPartNumbers={{ jlcpcb: ["C2337"] }} pcbX={-10} pcbY={22.4} pinLabels={{ pin1: "GND", pin2: "VCC", pin3: "SCL", pin4: "SDA" }} footprint={<footprint><platedhole portHints={["pin1"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={-3.81} pcbY={0} /><platedhole portHints={["pin2"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={-1.27} pcbY={0} /><platedhole portHints={["pin3"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={1.27} pcbY={0} /><platedhole portHints={["pin4"]} shape="circle" holeDiameter="1mm" outerDiameter="1.7mm" pcbX={3.81} pcbY={0} /><courtyardrect pcbX={0} pcbY={-12.4} width={27.3} height={27.8} /><silkscreenrect pcbX={0} pcbY={-12.4} width={27.3} height={27.8} /></footprint>} />
    <chip name="BZ1" footprint="lcsc:C781847" manufacturerPartNumber="YX-YT9042 3v" supplierPartNumbers={{ jlcpcb: ["C781847"] }} pcbX={-23} pcbY={-10} pinLabels={{ pin1: "POS", pin2: "NEG" }} />
    <chip name="D1" footprint="lcsc:C64885" manufacturerPartNumber="B5819W" supplierPartNumbers={{ jlcpcb: ["C64885"] }} pcbX={-15.5} pcbY={-11} pcbRotation={90} pinLabels={{ pin1: "K", pin2: "A" }} />
    <chip name="Q1" footprint="lcsc:C2146" manufacturerPartNumber="S8050 J3Y(RANGE:200-350)" supplierPartNumbers={{ jlcpcb: ["C2146"] }} pcbX={-11} pcbY={-9.5} pinLabels={{ pin1: "B", pin2: "E", pin3: "C" }} />
    <resistor name="R1" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={6} pcbY={22} pcbRotation={90} />
    <resistor name="R2" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={10} pcbY={18.5} />
    <resistor name="RB" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={-6} pcbY={-10.5} pcbRotation={180} />
    <pushbutton name="SW1" footprint="pushbutton" internallyConnectedPins={[["pin1","pin2"],["pin3","pin4"]]} supplierPartNumbers={{ jlcpcb: ["C110153"] }} pcbX={-20} pcbY={-20} />
    <pushbutton name="SW2" footprint="pushbutton" internallyConnectedPins={[["pin1","pin2"],["pin3","pin4"]]} supplierPartNumbers={{ jlcpcb: ["C110153"] }} pcbX={-6} pcbY={-20} />
    <pushbutton name="SW3" footprint="pushbutton" internallyConnectedPins={[["pin1","pin2"],["pin3","pin4"]]} supplierPartNumbers={{ jlcpcb: ["C110153"] }} pcbX={10} pcbY={-20} />
    <hole name="H1" diameter="3.2mm" pcbX={-31.5} pcbY={21.5} />
    <hole name="H2" diameter="3.2mm" pcbX={31.5} pcbY={21.5} />
    <hole name="H3" diameter="3.2mm" pcbX={-31.5} pcbY={-21.5} />
    <hole name="H4" diameter="3.2mm" pcbX={31.5} pcbY={-21.5} />
    <trace from=".U1 > .GND" to="net.GND" />
    <trace from=".DS1 > .GND" to="net.GND" />
    <trace from=".SW1 > .pin3" to="net.GND" />
    <trace from=".SW2 > .pin3" to="net.GND" />
    <trace from=".SW3 > .pin3" to="net.GND" />
    <trace from=".Q1 > .E" to="net.GND" />
    <trace from=".U1 > .V3V3" to="net.V3V3" />
    <trace from=".DS1 > .VCC" to="net.V3V3" />
    <trace from=".R1 > .pin1" to="net.V3V3" />
    <trace from=".R2 > .pin1" to="net.V3V3" />
    <trace from=".BZ1 > .POS" to="net.V3V3" />
    <trace from=".D1 > .K" to="net.V3V3" />
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
    <trace from=".D1 > .A" to="net.N1" />
  </board>
)
