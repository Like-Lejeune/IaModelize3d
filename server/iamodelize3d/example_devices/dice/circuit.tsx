// Compiled from the device graph (fw.device/1) by IaModelize3d: parts on an edge and the designer's are where they
// were put, the rest next to the pins it connects, then autorouted on 2 layers.
export const meta = {"title": "Электронный игральный кубик", "intent": {"nets_max": 30, "edge": {"U1": "+x"}, "gpio": {"LED1": "U1.D2", "LED2": "U1.D3", "LED3": "U1.MOSI", "LED4": "U1.RX", "LED5": "U1.RX", "LED6": "U1.MOSI", "LED7": "U1.D3", "SW1": "U1.D1"}}, "device": true}

export default () => (
  <board width="31mm" height="54mm" thickness="1.6mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.6mm">
    <chip name="U1" manufacturerPartNumber="113991054" pcbX={5} pcbY={0} pcbRotation={270} pinLabels={{ pin1: "D0", pin2: "D1", pin3: "D2", pin4: "D3", pin5: "SDA", pin6: "SCL", pin7: "TX", pin8: "RX", pin9: "SCK", pin10: "MISO", pin11: "MOSI", pin12: "V3V3", pin13: "GND", pin14: "V5" }} footprint={<footprint><platedhole portHints={["pin1"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={7.62} /><platedhole portHints={["pin2"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={5.08} /><platedhole portHints={["pin3"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={2.54} /><platedhole portHints={["pin4"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={0} /><platedhole portHints={["pin5"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-2.54} /><platedhole portHints={["pin6"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-5.08} /><platedhole portHints={["pin7"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-7.62} /><platedhole portHints={["pin8"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-7.62} /><platedhole portHints={["pin9"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-5.08} /><platedhole portHints={["pin10"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-2.54} /><platedhole portHints={["pin11"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={0} /><platedhole portHints={["pin12"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={2.54} /><platedhole portHints={["pin13"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={5.08} /><platedhole portHints={["pin14"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={7.62} /><courtyardrect pcbX={0} pcbY={0} width={16.94} height={16.94} /><silkscreenrect pcbX={0} pcbY={0} width={17.8} height={21} /><silkscreenrect pcbX={0} pcbY={7.85} width={8.94} height={7.3} /></footprint>} />
    <led name="LED1" color="red" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C2286"] }} pcbX={0} pcbY={17.93} />
    <led name="LED2" color="red" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C2286"] }} pcbX={-8} pcbY={25.93} />
    <led name="LED3" color="red" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C2286"] }} pcbX={8} pcbY={25.93} />
    <led name="LED4" color="red" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C2286"] }} pcbX={-8} pcbY={17.93} />
    <led name="LED5" color="red" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C2286"] }} pcbX={8} pcbY={17.93} />
    <led name="LED6" color="red" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C2286"] }} pcbX={-8} pcbY={9.93} />
    <led name="LED7" color="red" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C2286"] }} pcbX={8} pcbY={9.93} />
    <resistor name="R1" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={0} pcbY={15} pcbRotation={180} />
    <resistor name="R2" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={-7.5} pcbY={23} pcbRotation={180} />
    <resistor name="R3" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={7} pcbY={22} pcbRotation={90} />
    <resistor name="R4" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={-8.5} pcbY={14} pcbRotation={90} />
    <resistor name="R5" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={4} pcbY={16.5} pcbRotation={90} />
    <resistor name="R6" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={-4.5} pcbY={13} pcbRotation={180} />
    <resistor name="R7" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={3.5} pcbY={11.5} />
    <pushbutton name="SW1" footprint="pushbutton" internallyConnectedPins={[["pin1","pin2"],["pin3","pin4"]]} supplierPartNumbers={{ jlcpcb: ["C110153"] }} pcbX={-9.3} pcbY={-12} />
    <hole name="H1" diameter="3.2mm" pcbX={-12} pcbY={23.5} />
    <hole name="H2" diameter="3.2mm" pcbX={12} pcbY={23.5} />
    <hole name="H3" diameter="3.2mm" pcbX={-12} pcbY={-23.5} />
    <hole name="H4" diameter="3.2mm" pcbX={12} pcbY={-23.5} />
    <trace from=".U1 > .GND" to="net.GND" />
    <trace from=".LED1 > .cathode" to="net.GND" />
    <trace from=".LED2 > .cathode" to="net.GND" />
    <trace from=".LED3 > .cathode" to="net.GND" />
    <trace from=".LED4 > .cathode" to="net.GND" />
    <trace from=".LED5 > .cathode" to="net.GND" />
    <trace from=".LED6 > .cathode" to="net.GND" />
    <trace from=".LED7 > .cathode" to="net.GND" />
    <trace from=".SW1 > .pin3" to="net.GND" />
    <trace from=".U1 > .D2" to=".R1 > .pin1" />
    <trace from=".U1 > .D3" to="net.N1" />
    <trace from=".R2 > .pin1" to="net.N1" />
    <trace from=".R7 > .pin1" to="net.N1" />
    <trace from=".U1 > .MOSI" to="net.N2" />
    <trace from=".R3 > .pin1" to="net.N2" />
    <trace from=".R6 > .pin1" to="net.N2" />
    <trace from=".U1 > .RX" to="net.N3" />
    <trace from=".R4 > .pin1" to="net.N3" />
    <trace from=".R5 > .pin1" to="net.N3" />
    <trace from=".R1 > .pin2" to=".LED1 > .anode" />
    <trace from=".R2 > .pin2" to=".LED2 > .anode" />
    <trace from=".R3 > .pin2" to=".LED3 > .anode" />
    <trace from=".R4 > .pin2" to=".LED4 > .anode" />
    <trace from=".R5 > .pin2" to=".LED5 > .anode" />
    <trace from=".R6 > .pin2" to=".LED6 > .anode" />
    <trace from=".R7 > .pin2" to=".LED7 > .anode" />
    <trace from=".U1 > .D1" to=".SW1 > .pin1" />
  </board>
)
