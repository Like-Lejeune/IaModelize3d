// Compiled from the device graph (fw.device/1) by IaModelize3d: parts on an edge and the designer's are where they
// were put, the rest next to the pins it connects, then autorouted on 2 layers.
export const meta = {"title": "Датчик протечки воды", "intent": {"nets_max": 30, "edge": {"U1": "-y", "PR1": "-y"}, "gpio": {"LED1": "U1.D2", "SW1": "U1.D1"}}, "device": true}

export default () => (
  <board width="46mm" height="37mm" thickness="1.6mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.6mm">
    <chip name="U1" manufacturerPartNumber="113991054" pcbX={-4.16} pcbY={-8} pcbRotation={180} pinLabels={{ pin1: "D0", pin2: "D1", pin3: "D2", pin4: "D3", pin5: "SDA", pin6: "SCL", pin7: "TX", pin8: "RX", pin9: "SCK", pin10: "MISO", pin11: "MOSI", pin12: "V3V3", pin13: "GND", pin14: "V5" }} footprint={<footprint><platedhole portHints={["pin1"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={7.62} /><platedhole portHints={["pin2"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={5.08} /><platedhole portHints={["pin3"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={2.54} /><platedhole portHints={["pin4"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={0} /><platedhole portHints={["pin5"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-2.54} /><platedhole portHints={["pin6"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-5.08} /><platedhole portHints={["pin7"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-7.62} /><platedhole portHints={["pin8"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-7.62} /><platedhole portHints={["pin9"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-5.08} /><platedhole portHints={["pin10"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-2.54} /><platedhole portHints={["pin11"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={0} /><platedhole portHints={["pin12"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={2.54} /><platedhole portHints={["pin13"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={5.08} /><platedhole portHints={["pin14"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={7.62} /><courtyardrect pcbX={0} pcbY={0} width={16.94} height={16.94} /><silkscreenrect pcbX={0} pcbY={0} width={17.8} height={21} /><silkscreenrect pcbX={0} pcbY={7.85} width={8.94} height={7.3} /></footprint>} />
    <pinheader name="PR1" pinCount={2} pitch="2.54mm" pinLabels={["SENSE", "GND"]} supplierPartNumbers={{ jlcpcb: ["C2337"] }} pcbX={10.12} pcbY={-16} />
    <chip name="BZ1" footprint="lcsc:C781847" manufacturerPartNumber="YX-YT9042 3v" supplierPartNumbers={{ jlcpcb: ["C781847"] }} pcbX={-8} pcbY={9} pinLabels={{ pin1: "POS", pin2: "NEG" }} />
    <chip name="Q1" footprint="lcsc:C2146" manufacturerPartNumber="S8050 J3Y(RANGE:200-350)" supplierPartNumbers={{ jlcpcb: ["C2146"] }} pcbX={0.5} pcbY={9} pinLabels={{ pin1: "B", pin2: "E", pin3: "C" }} />
    <diode name="D1" footprint="sod123" manufacturerPartNumber="B5819W" supplierPartNumbers={{ jlcpcb: ["C8598"] }} pcbX={-0.5} pcbY={14.5} pcbRotation={90} />
    <resistor name="RB" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={0.5} pcbY={5} />
    <resistor name="R1" resistance="100k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C25803"] }} pcbX={10} pcbY={-11} pcbRotation={270} />
    <resistor name="R2" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={7} pcbY={-11} pcbRotation={270} />
    <led name="LED1" color="red" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C2286"] }} pcbX={18} pcbY={8} />
    <resistor name="RL" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={16} pcbY={5} />
    <pushbutton name="SW1" footprint="pushbutton" internallyConnectedPins={[["pin1","pin2"],["pin3","pin4"]]} supplierPartNumbers={{ jlcpcb: ["C110153"] }} pcbX={17} pcbY={-5} />
    <hole name="H1" diameter="3.2mm" pcbX={-19.5} pcbY={15} />
    <hole name="H2" diameter="3.2mm" pcbX={19.5} pcbY={15} />
    <hole name="H3" diameter="3.2mm" pcbX={-19.5} pcbY={-15} />
    <hole name="H4" diameter="3.2mm" pcbX={19.5} pcbY={-15} />
    <trace from=".U1 > .GND" to="net.GND" />
    <trace from=".PR1 > .GND" to="net.GND" />
    <trace from=".Q1 > .E" to="net.GND" />
    <trace from=".LED1 > .cathode" to="net.GND" />
    <trace from=".SW1 > .pin3" to="net.GND" />
    <trace from=".U1 > .V3V3" to="net.V3V3" />
    <trace from=".BZ1 > .POS" to="net.V3V3" />
    <trace from=".D1 > .cathode" to="net.V3V3" />
    <trace from=".R1 > .pin1" to="net.V3V3" />
    <trace from=".U1 > .D3" to=".R2 > .pin1" />
    <trace from=".R2 > .pin2" to="net.N1" />
    <trace from=".R1 > .pin2" to="net.N1" />
    <trace from=".PR1 > .SENSE" to="net.N1" />
    <trace from=".U1 > .MOSI" to=".RB > .pin1" />
    <trace from=".RB > .pin2" to=".Q1 > .B" />
    <trace from=".U1 > .D2" to=".RL > .pin1" />
    <trace from=".RL > .pin2" to=".LED1 > .anode" />
    <trace from=".U1 > .D1" to=".SW1 > .pin1" />
    <trace from=".Q1 > .C" to="net.N2" />
    <trace from=".BZ1 > .NEG" to="net.N2" />
    <trace from=".D1 > .anode" to="net.N2" />
  </board>
)
