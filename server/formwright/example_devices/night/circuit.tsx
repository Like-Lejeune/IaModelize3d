// Compiled from the device graph (fw.device/1) by Formwright: parts on an edge and the designer's are where they
// were put, the rest next to the pins it connects, then autorouted on 2 layers.
export const meta = {"title": "Ночник с датчиком движения", "intent": {"nets_max": 30, "edge": {"U1": "-y"}, "gpio": {"SW1": "U1.D2"}}, "device": true}

export default () => (
  <board outline={[{ x: 21, y: 18 }, { x: 20.914, y: 19.095 }, { x: 20.657, y: 20.163 }, { x: 20.237, y: 21.178 }, { x: 19.663, y: 22.114 }, { x: 18.95, y: 22.95 }, { x: 18.114, y: 23.663 }, { x: 17.178, y: 24.237 }, { x: 16.163, y: 24.657 }, { x: 15.095, y: 24.914 }, { x: 14, y: 25 }, { x: -14, y: 25 }, { x: -15.095, y: 24.914 }, { x: -16.163, y: 24.657 }, { x: -17.178, y: 24.237 }, { x: -18.114, y: 23.663 }, { x: -18.95, y: 22.95 }, { x: -19.663, y: 22.114 }, { x: -20.237, y: 21.178 }, { x: -20.657, y: 20.163 }, { x: -20.914, y: 19.095 }, { x: -21, y: 18 }, { x: -21, y: -18 }, { x: -20.914, y: -19.095 }, { x: -20.657, y: -20.163 }, { x: -20.237, y: -21.178 }, { x: -19.663, y: -22.114 }, { x: -18.95, y: -22.95 }, { x: -18.114, y: -23.663 }, { x: -17.178, y: -24.237 }, { x: -16.163, y: -24.657 }, { x: -15.095, y: -24.914 }, { x: -14, y: -25 }, { x: 14, y: -25 }, { x: 15.095, y: -24.914 }, { x: 16.163, y: -24.657 }, { x: 17.178, y: -24.237 }, { x: 18.114, y: -23.663 }, { x: 18.95, y: -22.95 }, { x: 19.663, y: -22.114 }, { x: 20.237, y: -21.178 }, { x: 20.657, y: -20.163 }, { x: 20.914, y: -19.095 }, { x: 21, y: -18 }]} thickness="1.6mm" minTraceWidth="0.2mm" minViaHoleDiameter="0.3mm" minViaPadDiameter="0.6mm">
    <chip name="U1" manufacturerPartNumber="113991054" pcbX={0} pcbY={-14.5} pcbRotation={180} pinLabels={{ pin1: "D0", pin2: "D1", pin3: "D2", pin4: "D3", pin5: "SDA", pin6: "SCL", pin7: "TX", pin8: "RX", pin9: "SCK", pin10: "MISO", pin11: "MOSI", pin12: "V3V3", pin13: "GND", pin14: "V5" }} footprint={<footprint><platedhole portHints={["pin1"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={7.62} /><platedhole portHints={["pin2"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={5.08} /><platedhole portHints={["pin3"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={2.54} /><platedhole portHints={["pin4"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={0} /><platedhole portHints={["pin5"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-2.54} /><platedhole portHints={["pin6"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-5.08} /><platedhole portHints={["pin7"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={-7.62} pcbY={-7.62} /><platedhole portHints={["pin8"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-7.62} /><platedhole portHints={["pin9"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-5.08} /><platedhole portHints={["pin10"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={-2.54} /><platedhole portHints={["pin11"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={0} /><platedhole portHints={["pin12"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={2.54} /><platedhole portHints={["pin13"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={5.08} /><platedhole portHints={["pin14"]} shape="circle" holeDiameter="1mm" outerDiameter="1.6mm" pcbX={7.62} pcbY={7.62} /><courtyardrect pcbX={0} pcbY={0} width={16.94} height={16.94} /><silkscreenrect pcbX={0} pcbY={0} width={17.8} height={21} /><silkscreenrect pcbX={0} pcbY={7.85} width={8.94} height={7.3} /></footprint>} />
    <chip name="U2" footprint="lcsc:C2887901" manufacturerPartNumber="PIR223D-S0" supplierPartNumbers={{ jlcpcb: ["C2887901"] }} pcbX={0} pcbY={18} pinLabels={{ pin1: "VDD", pin2: "REL", pin3: "VSS" }} />
    <chip name="U3" footprint="lcsc:C78960" manufacturerPartNumber="BH1750FVI-TR" supplierPartNumbers={{ jlcpcb: ["C78960"] }} pcbX={12} pcbY={17} pinLabels={{ pin1: "VCC", pin2: "ADDR", pin3: "GND", pin4: "SDA", pin5: "DVI", pin6: "SCL", pin7: "EP" }} />
    <capacitor name="C1" capacitance="100nF" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C14663"] }} pcbX={-5.87} pcbY={20.07} pcbRotation={90} maxDecouplingTraceLength={10} />
    <capacitor name="C2" capacitance="100nF" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C14663"] }} pcbX={11.37} pcbY={18.84} maxDecouplingTraceLength={10} />
    <chip name="LED1" footprint="lcsc:C210315" manufacturerPartNumber="HL-AM-2835H421W-S1-08-HR3(Color Temperature2800-3100K)" supplierPartNumbers={{ jlcpcb: ["C210315"] }} pcbX={-13.5} pcbY={8} pinLabels={{ pin1: "K", pin2: "A" }} />
    <chip name="LED2" footprint="lcsc:C210315" manufacturerPartNumber="HL-AM-2835H421W-S1-08-HR3(Color Temperature2800-3100K)" supplierPartNumbers={{ jlcpcb: ["C210315"] }} pcbX={-4.5} pcbY={8} pinLabels={{ pin1: "K", pin2: "A" }} />
    <chip name="LED3" footprint="lcsc:C210315" manufacturerPartNumber="HL-AM-2835H421W-S1-08-HR3(Color Temperature2800-3100K)" supplierPartNumbers={{ jlcpcb: ["C210315"] }} pcbX={4.5} pcbY={8} pinLabels={{ pin1: "K", pin2: "A" }} />
    <chip name="LED4" footprint="lcsc:C210315" manufacturerPartNumber="HL-AM-2835H421W-S1-08-HR3(Color Temperature2800-3100K)" supplierPartNumbers={{ jlcpcb: ["C210315"] }} pcbX={13.5} pcbY={8} pinLabels={{ pin1: "K", pin2: "A" }} />
    <chip name="Q1" footprint="lcsc:C2146" manufacturerPartNumber="S8050 J3Y(RANGE:200-350)" supplierPartNumbers={{ jlcpcb: ["C2146"] }} pcbX={-8} pcbY={13} pcbRotation={90} pinLabels={{ pin1: "B", pin2: "E", pin3: "C" }} />
    <resistor name="R1" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={14} pcbY={13.5} pcbRotation={180} />
    <resistor name="R2" resistance="4.7k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C23162"] }} pcbX={17} pcbY={17} pcbRotation={180} />
    <resistor name="R3" resistance="1k" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C21190"] }} pcbX={-3} pcbY={12} pcbRotation={180} />
    <resistor name="R4" resistance="100R" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C22775"] }} pcbX={-8} pcbY={3} pcbRotation={90} />
    <resistor name="R5" resistance="100R" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C22775"] }} pcbX={-4} pcbY={4} />
    <resistor name="R6" resistance="100R" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C22775"] }} pcbX={5} pcbY={4} />
    <resistor name="R7" resistance="100R" footprint="0603" supplierPartNumbers={{ jlcpcb: ["C22775"] }} pcbX={14} pcbY={4} />
    <pushbutton name="SW1" footprint="pushbutton" internallyConnectedPins={[["pin1","pin2"],["pin3","pin4"]]} supplierPartNumbers={{ jlcpcb: ["C110153"] }} pcbX={-14} pcbY={-2} />
    <hole name="H1" diameter="3.2mm" pcbX={-16.47} pcbY={20.47} />
    <hole name="H2" diameter="3.2mm" pcbX={16.47} pcbY={20.47} />
    <hole name="H3" diameter="3.2mm" pcbX={-16.47} pcbY={-20.47} />
    <hole name="H4" diameter="3.2mm" pcbX={16.47} pcbY={-20.47} />
    <trace from=".U1 > .GND" to="net.GND" />
    <trace from=".U2 > .VSS" to="net.GND" />
    <trace from=".U3 > .GND" to="net.GND" />
    <trace from=".U3 > .ADDR" to="net.GND" />
    <trace from=".C1 > .pin2" to=".U2 > .VSS" />
    <trace from=".C2 > .pin2" to=".U3 > .GND" />
    <trace from=".Q1 > .E" to="net.GND" />
    <trace from=".SW1 > .pin3" to="net.GND" />
    <trace from=".U1 > .V3V3" to="net.V3V3" />
    <trace from=".U2 > .VDD" to="net.V3V3" />
    <trace from=".U3 > .VCC" to="net.V3V3" />
    <trace from=".U3 > .DVI" to="net.V3V3" />
    <trace from=".C1 > .pin1" to=".U2 > .VDD" />
    <trace from=".C2 > .pin1" to=".U3 > .VCC" />
    <trace from=".R1 > .pin1" to="net.V3V3" />
    <trace from=".R2 > .pin1" to="net.V3V3" />
    <trace from=".U1 > .V5" to=".R4 > .pin1" thickness="0.4mm" />
    <trace from=".R4 > .pin1" to=".R5 > .pin1" thickness="0.4mm" />
    <trace from=".R5 > .pin1" to=".R6 > .pin1" thickness="0.4mm" />
    <trace from=".R6 > .pin1" to=".R7 > .pin1" thickness="0.4mm" />
    <trace from=".U1 > .SDA" to="net.SDA" />
    <trace from=".U3 > .SDA" to="net.SDA" />
    <trace from=".R1 > .pin2" to="net.SDA" />
    <trace from=".U1 > .SCL" to="net.SCL" />
    <trace from=".U3 > .SCL" to="net.SCL" />
    <trace from=".R2 > .pin2" to="net.SCL" />
    <trace from=".U1 > .D1" to=".U2 > .REL" />
    <trace from=".U1 > .MOSI" to=".R3 > .pin1" />
    <trace from=".Q1 > .B" to=".R3 > .pin2" />
    <trace from=".Q1 > .C" to="net.N1" />
    <trace from=".LED1 > .K" to="net.N1" />
    <trace from=".LED2 > .K" to="net.N1" />
    <trace from=".LED3 > .K" to="net.N1" />
    <trace from=".LED4 > .K" to="net.N1" />
    <trace from=".LED1 > .A" to=".R4 > .pin2" />
    <trace from=".LED2 > .A" to=".R5 > .pin2" />
    <trace from=".LED3 > .A" to=".R6 > .pin2" />
    <trace from=".LED4 > .A" to=".R7 > .pin2" />
    <trace from=".U1 > .D2" to=".SW1 > .pin1" />
  </board>
)
