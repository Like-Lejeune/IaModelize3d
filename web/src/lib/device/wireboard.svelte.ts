// All the schematic's wires in one place: each wire edge says where its pins are, the sheet says where its parts stand, and
// the whole lot is routed together once a frame, so each wire can keep out of the others' way (wires.ts).
import { routeAll, wirePath, type Box, type Pt, type Wire } from './wires';

export class WireBoard {
  paths = $state.raw<Record<string, string>>({});
  joints = $state.raw<Record<string, Pt[]>>({});
  private wires = new Map<string, Wire>();
  private boxes: Box[] = [];
  private queued = false;

  setBoxes(boxes: Box[]) {
    this.boxes = boxes;
    this.queue();
  }

  want(w: Wire) {
    const o = this.wires.get(w.id);
    if (o && o.net === w.net && o.aDir === w.aDir && o.bDir === w.bDir && o.a[0] === w.a[0] && o.a[1] === w.a[1] && o.b[0] === w.b[0] && o.b[1] === w.b[1]) return;
    this.wires.set(w.id, w);
    this.queue();
  }

  drop(id: string) {
    if (this.wires.delete(id)) this.queue();
  }

  private queue() {
    if (this.queued) return;
    this.queued = true;
    requestAnimationFrame(() => {
      this.queued = false;
      const { ways, joints } = routeAll([...this.wires.values()], this.boxes);
      this.paths = Object.fromEntries(Object.entries(ways).map(([id, way]) => [id, wirePath(way)]));
      this.joints = joints;
    });
  }
}
