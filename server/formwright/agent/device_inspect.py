"""Close looks for the device designer (pack 'device'): the designer chooses what to look at and gets an image with the
numbers measured on the build, instead of whole-board pictures.

inspect_board  a PCB version's own drawing (pcb_top.svg / pcb_bottom.svg) cropped to a part, a net or a region, the rest of
               the board's copper dimmed or filtered by layer, with a mm grid; the facts come from the build's circuit.json
               (routed length and vias per connection, how far a trace detours) and board.json (where each part sits, its
               neighbours, what a module above covers, which way a connector faces).
inspect_case   the printed case (the current program, made by make_enclosure) assembled, lid off, exploded or cut, from the
               chosen side, zoomed on a part that is highlighted; the facts are the case's own report (lid height, inner
               walls, every window and grille with its rectangle) and the enclosure check's findings for that part.
inspect_part   text only: one node's card, pins and nets, what drives it from the microcontroller, where it was placed, its
               case opening, the firmware lines that use its pins and the design-rule findings that name it.

The hub (tools.py) offers TOOLS in pack 'device' and hands NAMES to run(). Nothing here changes a version: the case wrapper
program is rendered, never saved. Images use only the renderers the other tools use (pcb.render_png_async for the SVG,
geom().render for the case).
"""
from __future__ import annotations

import json
import logging
import math
import re
import xml.etree.ElementTree as ET
from typing import Any

from .. import device, pcb, pcb_store, storage
from ..geom import GeomError

log = logging.getLogger(__name__)

NEAR_MM = 8.0          # neighbours: edge-to-edge gap of their boxes on the board
OPPOSITE_MM = 20.0     # a light sensor and the lights it must ignore, a microphone and a buzzer: said up to this far apart
CROP_MARGIN_MM = 9.0
IMG_W = 1000
IMG_H_MAX = 1200
DETOUR = 2.0           # a connection routed this many times its straight distance (and >= DETOUR_MIN_MM) is called out
DETOUR_MIN_MM = 10.0
SVG_NS = "http://www.w3.org/2000/svg"
ACCESS_COLOR = {"light": "#ffd60a", "sensor": "#30d158", "sound": "#bf5af2", "display": "#64d2ff", "press": "#ff9f0a", "port": "#ff453a"}
OPPOSITE = {"sensor": "light", "light": "sensor"}
VIEWS = {"iso": (45.0, 30.0), "top": (0.0, 90.0), "bottom": (0.0, -90.0), "front": (0.0, 0.0), "right": (90.0, 0.0),
         "back": (180.0, 0.0), "left": (270.0, 0.0)}
MODES = ("assembled", "lid_off", "exploded", "section")
BOARD_RGB = "#2e6b45"
FOCUS_RGB = "#e0218a"
DEFAULT_VIEWS = {"assembled": ["top", "iso"], "lid_off": ["top", "iso"], "exploded": ["iso", "front"]}
LAYERS = ("all", "copper_top", "copper_bottom", "silk", "parts")
FW_CONTEXT = re.compile(r"pin|gpio|#define|const\s|constexpr|ledc|digital|analog|attach|Wire|Serial\d|\bI2C\b|SPI|tone|Pin\(|machine", re.I)
FW_LINES_MAX = 14


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}


_S = {"type": "string"}
_N = {"type": "number"}
FOCUS = {"description": "what to look at: a node id ('U2', 'LED1', 'J1'), a net name ('V3V3', 'SDA') or a pin ('U2.SDA' = its net), or a "
                        "region {x, y, w, h} in board mm (origin at the board's bottom-left corner); leave it out for the whole board"}

INSPECT_BOARD = _fn(
    "inspect_board",
    "Look closely at the routed board: a sharp crop of the PCB drawing around a part (outlined, its user-facing neighbours "
    "marked), a net (its copper bright, the rest dimmed) or a region, with a mm grid. Returns measured facts: a part's "
    "position, rotation and size, its neighbours within 8 mm with gaps, what sits over it, its distance to the edges and "
    "which way a connector faces; a net's pads, each connection's routed length against the straight distance, vias and "
    "layers; with no focus, the longest connections and the detours. Use it after build_device on every user-facing part "
    "and every long trace.",
    {"focus": FOCUS,
     "side": {"type": "string", "enum": ["top", "bottom"], "description": "top (default) or bottom copper emphasised; both are drawn "
                                                                          "as seen from the top, not mirrored"},
     "layers": {"type": "string", "enum": list(LAYERS), "description": "all (default) | copper_top | copper_bottom | silk | parts "
                                                                      "(pads, silkscreen and every part's outline with its id)"},
     "version": {"type": "integer", "description": "PCB version (default: the latest)"}},
    [])
INSPECT_CASE = _fn(
    "inspect_case",
    "Look closely at the printed case made by make_enclosure, with the board in it (green, the focused part red): "
    "mode assembled (lid on: through its windows you see what is under them) | lid_off | exploded (lid and board lifted) | "
    "section (cut through the case; the cut goes through the focused part unless `cut` says where). focus a node id to zoom "
    "where that part sits. Returns the opening over the part (window or grille rectangle, how much of the part it uncovers, "
    "offset), the lid's underside above the part, the inner walls around it and the case check's findings for it.",
    {"mode": {"type": "string", "enum": list(MODES), "description": "default assembled"},
     "view": {"type": "string", "enum": list(VIEWS), "description": "one view; default top + iso (exploded: iso + front; section: "
                                                                    "straight at the cut and two oblique)"},
     "focus": {**_S, "description": "a node id (a part or an accessory module): zoom on it and report its opening"},
     "cut": {"type": "object", "description": "for mode section: {axis: 'x'|'y'|'z', at: mm in the board frame (z from the PCB "
                                              "bottom)}; default through the focus (or the board's middle) across y",
             "properties": {"axis": {"type": "string", "enum": ["x", "y", "z"]}, "at": _N}}},
    [])
INSPECT_PART = _fn(
    "inspect_part",
    "Everything about one node of the device, as text (no image, cheap): its card (part number, kind, current, ratings), every "
    "pin with its net and what else is on that net, which microcontroller pin drives or reads it (through series resistors "
    "and a transistor), where the latest board placed it, the case opening over it, every firmware line that uses its pins "
    "(by name, alias or GPIO number) and the design-rule findings that name it. Use it before claiming a part works.",
    {"id": {**_S, "description": "node id, e.g. 'U2', 'LED1', 'BZ1'"}},
    ["id"])

TOOLS = [INSPECT_BOARD, INSPECT_CASE, INSPECT_PART]
NAMES = {t["name"] for t in TOOLS}


async def run(ctx: Any, state: Any, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    try:
        if name == "inspect_board":
            return await inspect_board(ctx, state, args)
        if name == "inspect_case":
            return await inspect_case(ctx, state, args)
        if name == "inspect_part":
            return await inspect_part(ctx, state, args), []
    except GeomError as e:
        return {"ok": False, "stage": e.stage, "error": e.message[:500]}, []
    except device.DeviceError as e:
        return {"ok": False, "error": str(e)}, []
    return {"ok": False, "error": f"unknown tool {name}"}, []


# ------------------------------------------------------------------ small helpers
def _r(v: float, n: int = 1) -> float:
    return round(float(v), n)


def _as_obj(v: Any) -> Any:
    if isinstance(v, str) and v.strip().startswith("{"):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    return v


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _box(c: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """A board.json component or accessory as (x0, y0, x1, y1) in board mm."""
    x, y, w, d = (_num(c.get(k)) for k in ("x", "y", "w", "d"))
    if x is None or y is None or not w or not d:
        return None
    return (x - w / 2, y - d / 2, x + w / 2, y + d / 2)


def _gap(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Edge-to-edge distance of two boxes; 0 when they touch or overlap."""
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return math.hypot(dx, dy)


def _overlap_area(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def _centre(b: tuple[float, ...]) -> tuple[float, float]:
    return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)


def _dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _label(s: str) -> str:
    """Text on a picture: the board font draws '.' at mid height, so 'U2.SDA' would read 'U2-SDA'."""
    return _esc(s.replace(".", " "))


def _pin_name(name: str) -> str:
    m = re.fullmatch(r"pin(\d+)", name)
    return m.group(1) if m else name


# ------------------------------------------------------------------ circuit.json: pads, nets, routed copper
class Circuit:
    """The routed circuit of one PCB version in the board frame (mm, origin at the board's bottom-left corner)."""

    def __init__(self, cj: list[dict[str, Any]], W: float, H: float, doc: dict[str, Any] | None = None):
        board = next((e for e in cj if e.get("type") == "pcb_board"), {})
        c = board.get("center") or {"x": 0, "y": 0}
        bw, bh = _num(board.get("width")) or W, _num(board.get("height")) or H
        self.dx, self.dy = bw / 2 - float(c.get("x") or 0), bh / 2 - float(c.get("y") or 0)
        comp_name = {e["source_component_id"]: e.get("name") for e in cj if e.get("type") == "source_component"}
        self.rotation: dict[str, float] = {}
        for e in cj:
            if e.get("type") == "pcb_component" and comp_name.get(e.get("source_component_id")):
                self.rotation[comp_name[e["source_component_id"]]] = float(e.get("rotation") or 0) % 360
        sports = {e["source_port_id"]: e for e in cj if e.get("type") == "source_port"}
        self.net_name: dict[str, str] = {}
        net_key: dict[str, str] = {}
        for e in cj:
            if e.get("type") == "source_net" and e.get("subcircuit_connectivity_map_key"):
                net_key[e["source_net_id"]] = e["subcircuit_connectivity_map_key"]
                if e.get("name"):
                    self.net_name.setdefault(e["subcircuit_connectivity_map_key"], str(e["name"]))
        port_key: dict[str, str] = {}
        trace_key: dict[str, str] = {}
        for e in cj:
            if e.get("type") == "source_trace" and e.get("subcircuit_connectivity_map_key"):
                k = e["subcircuit_connectivity_map_key"]
                trace_key[e["source_trace_id"]] = k
                for p in e.get("connected_source_port_ids") or []:
                    port_key[p] = k
        # pads: pcb_port id -> {ref, x, y, key}
        self.ports: dict[str, dict[str, Any]] = {}
        self.port_hints: dict[str, set[str]] = {}
        for e in cj:
            if e.get("type") != "pcb_port":
                continue
            sp = sports.get(e.get("source_port_id")) or {}
            comp = comp_name.get(sp.get("source_component_id")) or "?"
            ref = f"{comp}.{_pin_name(str(sp.get('name') or '?'))}"
            self.ports[e["pcb_port_id"]] = {"ref": ref, "comp": comp, "x": float(e["x"]) + self.dx, "y": float(e["y"]) + self.dy,
                                            "key": port_key.get(e.get("source_port_id")), "layers": e.get("layers") or []}
            self.port_hints[e["pcb_port_id"]] = {str(h).lower() for h in [sp.get("name"), *(sp.get("port_hints") or [])] if h}
        self.pads: list[dict[str, Any]] = []
        for e in cj:
            t = e.get("type")
            if t not in ("pcb_smtpad", "pcb_plated_hole") or e.get("pcb_port_id") not in self.ports:
                continue
            w = _num(e.get("width")) or _num(e.get("rect_pad_width")) or _num(e.get("outer_diameter")) or _num(e.get("radius") and 2 * e["radius"]) or 1.0
            h = _num(e.get("height")) or _num(e.get("rect_pad_height")) or _num(e.get("outer_diameter")) or w
            self.pads.append({"port": e["pcb_port_id"], "x": float(e["x"]) + self.dx, "y": float(e["y"]) + self.dy, "w": w, "h": h,
                              "layer": e.get("layer") or "through", "round": t == "pcb_plated_hole" and not e.get("rect_pad_width")})
        # routed connections
        self.traces: list[dict[str, Any]] = []
        tid_key: dict[str, str] = {}
        for e in cj:
            if e.get("type") != "pcb_trace":
                continue
            pts = [p for p in e.get("route") or [] if _num(p.get("x")) is not None and _num(p.get("y")) is not None]
            if len(pts) < 2:
                continue
            ends = [p.get("start_pcb_port_id") for p in pts if p.get("start_pcb_port_id")] + \
                   [p.get("end_pcb_port_id") for p in pts if p.get("end_pcb_port_id")]
            ends = ends or list(e.get("connectsTo") or [])
            key = self._key_of(e, net_key, trace_key, ends)
            tid_key[e.get("pcb_trace_id")] = key
            layers: dict[str, float] = {}
            segs = []
            for a, b in zip(pts, pts[1:]):
                ax, ay, bx, by = float(a["x"]) + self.dx, float(a["y"]) + self.dy, float(b["x"]) + self.dx, float(b["y"]) + self.dy
                layer = str(b.get("layer") or a.get("layer") or b.get("to_layer") or "top")
                if b.get("route_type") == "via":
                    layer = str(a.get("layer") or b.get("from_layer") or "top")
                L = math.hypot(bx - ax, by - ay)
                layers[layer] = layers.get(layer, 0.0) + L
                segs.append((ax, ay, bx, by, layer, float(b.get("width") or a.get("width") or 0.2)))
            vias = sum(1 for p in pts if p.get("route_type") == "via")
            first, last = pts[0], pts[-1]
            fa = (float(first["x"]) + self.dx, float(first["y"]) + self.dy)
            la = (float(last["x"]) + self.dx, float(last["y"]) + self.dy)
            refs = [self.ports[p]["ref"] for p in dict.fromkeys(ends) if p in self.ports]
            self.traces.append({"key": key, "segs": segs, "length": sum(layers.values()), "straight": _dist(fa, la),
                                "layers": layers, "vias": vias, "ends": refs[:2], "a": fa, "b": la})
        self.vias: list[dict[str, Any]] = []
        for e in cj:
            if e.get("type") == "pcb_via" and _num(e.get("x")) is not None:
                self.vias.append({"x": float(e["x"]) + self.dx, "y": float(e["y"]) + self.dy,
                                  "key": tid_key.get(e.get("pcb_trace_id")) or e.get("subcircuit_connectivity_map_key")})
        if doc:
            self.adopt_names(doc)

    def adopt_names(self, doc: dict[str, Any]) -> None:
        """The device's own net names for nets the compiler wired pin to pin (V5, LED_A): circuit.json has no name for them."""
        nodes = _doc_nodes(doc)
        for net in doc.get("nets") or []:
            if not net.get("name"):
                continue
            for ref in net.get("pins") or []:
                if "." not in ref:
                    continue
                comp, pin = ref.split(".", 1)
                key = self.key_of_pin(comp, _pad_names(nodes.get(comp), pin))
                if key:
                    self.net_name.setdefault(key, str(net["name"]))
                    break

    def _key_of(self, e: dict[str, Any], net_key: dict[str, str], trace_key: dict[str, str], ends: list[str]) -> str | None:
        name = str(e.get("connection_name") or "")
        if name in net_key:
            return net_key[name]
        for part in re.split(r"__", re.sub(r"_mst\d+.*$", "", name)):
            if part in trace_key:
                return trace_key[part]
            if part in net_key:
                return net_key[part]
        for p in ends:
            if self.ports.get(p, {}).get("key"):
                return self.ports[p]["key"]
        return None

    # -------------------------------------------------- lookups
    def keys(self) -> set[str]:
        return {p["key"] for p in self.ports.values() if p["key"]}

    def name_of(self, key: str | None) -> str:
        if not key:
            return "unconnected"
        if key in self.net_name:
            return self.net_name[key]
        refs = sorted(p["ref"] for p in self.ports.values() if p["key"] == key)
        return "-".join(refs[:3]) + ("..." if len(refs) > 3 else "")

    def key_by_name(self, name: str) -> str | None:
        low = name.lower()
        return next((k for k, n in self.net_name.items() if n.lower() == low), None)

    def key_of_pin(self, comp: str, pins: list[str]) -> str | None:
        want = {p.lower() for p in pins if p}
        for pid, p in self.ports.items():
            if p["comp"].lower() == comp.lower() and self.port_hints.get(pid, set()) & want and p["key"]:
                return p["key"]
        return None

    def comp_ports(self, comp: str) -> list[dict[str, Any]]:
        return [p for p in self.ports.values() if p["comp"] == comp]

    def connections(self, key: str) -> list[dict[str, Any]]:
        return [t for t in self.traces if t["key"] == key]


def _pad_names(node: dict[str, Any] | None, pin: str) -> list[str]:
    """The pad names a device pin may have on the board ('A' -> 'anode', 'VBUS' -> 'VBUS_A')."""
    out = [pin]
    if node:
        try:
            out += device.ports_of(node, {}, pin)
        except (KeyError, TypeError, AttributeError):
            pass
    return out


def connection_fact(t: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    ends = t["ends"] if len(t["ends"]) == 2 else t["ends"] + ["(trace)"] * (2 - len(t["ends"]))
    out: dict[str, Any] = {"from": ends[0], "to": ends[1], "routed_mm": _r(t["length"]), "straight_mm": _r(t["straight"])}
    if name:
        out = {"net": name, **out}
    if t["straight"] > 0.5:
        out["detour"] = _r(t["length"] / t["straight"])
    out["layers"] = {k: _r(v) for k, v in sorted(t["layers"].items()) if v >= 0.05}
    if t["vias"]:
        out["vias"] = t["vias"]
    return out


# ------------------------------------------------------------------ loading a built board
async def _version_row(ctx: Any, version: Any) -> tuple[dict[str, Any] | None, str | None]:
    from . import pcb_tools

    return await pcb_tools._row(ctx, version)


def _read_json(project_id: str, version: int, name: str) -> Any:
    path = pcb_store.artifact_path(project_id, version, name)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("%s of %s v%s: %s", name, project_id, version, e)
        return None


def _things(board: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Components and accessories of a board.json by id (accessories win: their box is the module's body)."""
    out: dict[str, dict[str, Any]] = {}
    for c in board.get("components") or []:
        if isinstance(c, dict) and c.get("id"):
            out[str(c["id"])] = {**c, "_acc": False}
    for a in board.get("accessories") or []:
        if isinstance(a, dict) and a.get("id"):
            out[str(a["id"])] = {**out.get(str(a["id"]), {}), **a, "_acc": True, "access": a.get("kind") if a.get("kind") in ACCESS_COLOR
                                 else out.get(str(a["id"]), {}).get("access")}
    return out


def _find_id(ids: Any, want: str) -> str | None:
    if want in ids:
        return want
    low = want.lower()
    return next((i for i in ids if str(i).lower() == low), None)


def _doc_nodes(doc: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {str(n.get("id")): n for n in (doc or {}).get("nodes") or [] if isinstance(n, dict) and n.get("id")}


def _family(things: dict[str, dict[str, Any]], pid: str) -> set[str]:
    """A module and the parts it brings (U1, U1_usb, U1_btn_boot): one thing, never its own neighbour."""
    return {i for i in things if i == pid or i.startswith(pid + "_")}


def _edge_gaps(b: tuple[float, ...], W: float, H: float) -> dict[str, float]:
    return {"-x": _r(b[0]), "+x": _r(W - b[2]), "-y": _r(b[1]), "+y": _r(H - b[3])}


def part_facts(pid: str, board: dict[str, Any], circ: Circuit | None, doc: dict[str, Any] | None) -> dict[str, Any]:
    """Where one part sits on the board and what is around it."""
    things = _things(board)
    t = things[pid]
    o = ((board.get("pcb") or {}).get("outline") or {})
    W, H = float(o.get("w") or 0), float(o.get("h") or 0)
    node = _doc_nodes(doc).get(pid) or {}
    out: dict[str, Any] = {"id": pid}
    if node.get("label"):
        out["label"] = node["label"]
    out["kind"] = node.get("kind") or t.get("type")
    b = _box(t)
    if t.get("edge") and b is None:
        out["edge"] = t["edge"]
        out["note"] = "an edge part of its module: it sits at the module's own edge"
        return out
    if b is None:
        return {**out, "error": "the board has no position for it"}
    out["at_mm"] = [_r(t["x"]), _r(t["y"])]
    out["size_mm"] = [_r(t["w"]), _r(t["d"])] + ([_r(t["h"])] if _num(t.get("h")) else [])
    if circ and pid in circ.rotation:
        out["rotation"] = _r(circ.rotation[pid], 0)
    out["side"] = t.get("side") or "top"
    if t.get("access") and t.get("access") != "none":
        out["access"] = t["access"]
    if t.get("_acc"):
        out["accessory"] = f"{t.get('name') or t.get('key')}: a module {t.get('mount') or 'board'}-mounted, its body {_r(t.get('z0') or 0)} mm above the board"
    gaps = _edge_gaps(b, W, H)
    near = min(gaps, key=gaps.get)
    out["edges_mm"] = gaps
    out["nearest_edge"] = f"{near} {gaps[near]} mm"
    facing = _facing(node, near, out.get("rotation"))
    if facing:
        out["faces"] = facing
    fam = _family(things, pid)
    neigh = []
    for oid, o2 in things.items():
        if oid in fam or (oid.split("_")[0] in fam and "_" in oid):
            continue
        ob = _box(o2)
        if ob is None:
            continue
        g = _gap(b, ob)
        if g <= NEAR_MM:
            neigh.append((g, oid, o2, ob))
    neigh.sort(key=lambda n: n[0])
    out["neighbours"] = [f"{oid}{' (' + str(o2['access']) + ')' if o2.get('access') not in (None, 'none') else ''}: gap {_r(g)} mm, "
                         f"centres {_r(_dist(_centre(b), _centre(ob)))} mm" + (" (module above the board)" if o2.get("_acc") else "")
                         for g, oid, o2, ob in neigh[:10]]
    if len(neigh) > 10:
        out["neighbours"].append(f"and {len(neigh) - 10} more within {NEAR_MM:.0f} mm")
    # a sensor and the lights it must not see, said even past the neighbour radius
    want = OPPOSITE.get(str(t.get("access")))
    if want:
        opp = sorted((_dist(_centre(b), _centre(ob)), oid) for oid, o2 in things.items() if o2.get("access") == want and oid not in fam
                     and (ob := _box(o2)) is not None)
        close = [f"{oid} {_r(d)} mm" for d, oid in opp if d <= OPPOSITE_MM]
        if close:
            out[f"{want}s_within_{OPPOSITE_MM:.0f}mm"] = close
    # a module body over it (a display over a buzzer)
    if not t.get("_acc"):
        over = [f"{oid} ({o2.get('kind') or o2.get('access')}, body {_r(o2.get('z0') or 0)}-{_r((o2.get('z0') or 0) + (o2.get('h') or 0))} mm "
                f"above the board) covers {_r(100 * _overlap_area(b, ob) / max(1e-6, (b[2] - b[0]) * (b[3] - b[1])), 0):.0f}% of it"
                for oid, o2 in things.items() if o2.get("_acc") and oid not in fam and (ob := _box(o2)) is not None and _overlap_area(b, ob) > 0]
        if over:
            out["under"] = over
    if circ:
        conns = [connection_fact(tr, circ.name_of(tr["key"])) for tr in circ.traces
                 if any(e.split(".")[0] in fam for e in tr["ends"])]
        if conns:
            conns.sort(key=lambda c: -c["routed_mm"])
            out["connections"] = conns[:10]
    return out


def _facing(node: dict[str, Any], near: str, rot: float | None) -> str | None:
    """Which way a USB-C or JST connector opens, against the edge it is nearest to."""
    k = node.get("kind")
    if k not in device.FACING_ROT or rot is None:
        return None
    by_rot = {int(v) % 360: e for e, v in device.FACING_ROT[k].items()}
    opens = by_rot.get(int(round(rot)) % 360)
    if opens is None:
        return f"rotation {rot:.0f} is not a multiple of 90: the plug goes in at an angle"
    if opens == near:
        return f"its opening faces {opens}, out over the nearest edge"
    return (f"its opening faces {opens}, but the nearest edge is {near}: the plug would go in across the board. Give the node "
            f"edge '{near}' (or rotation {device.FACING_ROT[k][near]})")


def net_facts(key: str, circ: Circuit, board: dict[str, Any]) -> dict[str, Any]:
    things = _things(board)
    pads = [p for p in circ.ports.values() if p["key"] == key]
    conns = circ.connections(key)
    total = sum(t["length"] for t in conns)
    layers: dict[str, float] = {}
    for t in conns:
        for k, v in t["layers"].items():
            layers[k] = layers.get(k, 0.0) + v
    vias = [v for v in circ.vias if v["key"] == key]
    out: dict[str, Any] = {"net": circ.name_of(key), "pads": [f"{p['ref']} at ({_r(p['x'])}, {_r(p['y'])})" for p in pads][:24],
                           "routed_total_mm": _r(total), "layers_mm": {k: _r(v) for k, v in sorted(layers.items()) if v >= 0.05},
                           "vias": len(vias)}
    if vias:
        out["via_at"] = [[_r(v["x"]), _r(v["y"])] for v in vias[:12]]
    out["connections"] = sorted((connection_fact(t) for t in conns), key=lambda c: -c["routed_mm"])[:16]
    comps = sorted({p["comp"] for p in pads})
    users = [f"{c} ({things[c]['access']})" for c in comps if things.get(c, {}).get("access") not in (None, "none")]
    if users:
        out["user_facing_parts"] = users
    if len(pads) > 1 and not conns:
        out["note"] = "no copper routed for this net"
    return out


def board_facts(circ: Circuit | None, board: dict[str, Any]) -> dict[str, Any]:
    """The whole board: size, the user-facing parts, the longest connections and the detours."""
    o = ((board.get("pcb") or {}).get("outline") or {})
    things = _things(board)
    out: dict[str, Any] = {"board_mm": [o.get("w"), o.get("h")]}
    facing = [f"{i} ({t['access']}) at ({_r(t['x'])}, {_r(t['y'])})" for i, t in things.items()
              if t.get("access") not in (None, "none") and _num(t.get("x")) is not None]
    if facing:
        out["user_facing"] = facing[:20]
    if circ:
        conns = [connection_fact(t, circ.name_of(t["key"])) for t in circ.traces]
        conns.sort(key=lambda c: -c["routed_mm"])
        out["longest"] = conns[:6]
        det = [c for c in conns if c.get("detour", 0) >= DETOUR and c["routed_mm"] >= DETOUR_MIN_MM]
        if det:
            out["detours"] = det[:8]
        out["vias"] = len(circ.vias)
    return out


def region_facts(reg: tuple[float, float, float, float], circ: Circuit | None, board: dict[str, Any]) -> dict[str, Any]:
    things = _things(board)
    inside = [f"{i}{' (' + str(t['access']) + ')' if t.get('access') not in (None, 'none') else ''} at ({_r(t['x'])}, {_r(t['y'])})"
              for i, t in things.items() if (b := _box(t)) is not None and _overlap_area(b, reg) > 0]
    out: dict[str, Any] = {"region_mm": [_r(reg[0]), _r(reg[1]), _r(reg[2] - reg[0]), _r(reg[3] - reg[1])], "parts": inside[:30]}
    if circ:
        nets: dict[str, float] = {}
        for t in circ.traces:
            for ax, ay, bx, by, _, _ in t["segs"]:
                if _seg_in(ax, ay, bx, by, reg):
                    n = circ.name_of(t["key"])
                    nets[n] = nets.get(n, 0.0) + math.hypot(bx - ax, by - ay)
        out["nets_crossing"] = {k: _r(v) for k, v in sorted(nets.items(), key=lambda kv: -kv[1])[:16]}
        out["vias"] = sum(1 for v in circ.vias if reg[0] <= v["x"] <= reg[2] and reg[1] <= v["y"] <= reg[3])
    return out


def _seg_in(ax: float, ay: float, bx: float, by: float, reg: tuple[float, ...]) -> bool:
    for k in range(5):
        x, y = ax + (bx - ax) * k / 4, ay + (by - ay) * k / 4
        if reg[0] <= x <= reg[2] and reg[1] <= y <= reg[3]:
            return True
    return False


# ------------------------------------------------------------------ the board picture
def _svg_map(svg: str, W: float, H: float) -> tuple[float, float, float, float] | None:
    """board mm -> SVG px from the board outline the drawing has: px = a*x + e, py = d*y + f."""
    m = re.search(r'<path[^>]*class="pcb-board"[^>]*>', svg)
    d = re.search(r'\sd="([^"]+)"', m.group(0)) if m else None
    if not d or not W or not H:
        return None
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?(?:e-?\d+)?", d.group(1), re.I)]
    xs, ys = nums[0::2], nums[1::2]
    if not xs or not ys:
        return None
    a = (max(xs) - min(xs)) / W
    dd = -(max(ys) - min(ys)) / H
    return a, min(xs), dd, max(ys)


def _keep(el: ET.Element, layers: str) -> bool:
    t, ly = el.get("data-type") or "", el.get("data-pcb-layer") or ""
    if layers == "all" or t in ("pcb_background", "pcb_boundary", "pcb_board", "pcb_hole", "pcb_plated_hole_drill") or ly == "drill":
        return True
    silk = t.startswith("pcb_silkscreen") or t.startswith("pcb_fabrication") or t.startswith("pcb_courtyard")
    if layers == "silk":
        return silk
    if layers == "parts":
        return silk or t in ("pcb_smtpad", "pcb_plated_hole")
    side = "top" if layers == "copper_top" else "bottom"
    if t in ("pcb_trace", "pcb_smtpad"):
        return ly == side
    return t in ("pcb_via", "pcb_plated_hole")


class Picture:
    """A crop of the PCB drawing with overlays in board mm."""

    def __init__(self, svg: str, W: float, H: float, crop: tuple[float, float, float, float], layers: str):
        m = _svg_map(svg, W, H)
        if m is None:
            raise ValueError("the drawing has no board outline")
        self.a, self.e, self.d, self.f = m
        ET.register_namespace("", SVG_NS)
        root = ET.fromstring(svg)
        if layers != "all":
            for el in list(root):
                if not _keep(el, layers):
                    root.remove(el)
        self.crop = crop
        x0, y0 = self.px(crop[0], crop[3])
        x1, y1 = self.px(crop[2], crop[1])
        self.vb = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        out_w = min(IMG_W, IMG_H_MAX * self.vb[2] / max(1e-6, self.vb[3]))
        self.out_w = int(max(400, out_w))
        self.k = self.out_w / self.vb[2]  # output px per SVG px
        for a in ("width", "height", "viewBox"):
            root.attrib.pop(a, None)
        root.set("width", f"{self.vb[2]:.2f}")
        root.set("height", f"{self.vb[3]:.2f}")
        root.set("viewBox", " ".join(f"{v:.2f}" for v in self.vb))
        self.body = ET.tostring(root, encoding="unicode")
        self.over: list[str] = []

    def px(self, x: float, y: float) -> tuple[float, float]:
        return self.a * x + self.e, self.d * y + self.f

    def s(self, out_px: float) -> float:
        """An overlay size given in output pixels, in SVG px."""
        return out_px / self.k

    def rect(self, b: tuple[float, ...], color: str, width: float = 2.0, dash: bool = False, fill: str = "none", opacity: float = 1.0) -> None:
        x0, y0 = self.px(b[0], b[3])
        x1, y1 = self.px(b[2], b[1])
        d = f' stroke-dasharray="{self.s(7):.2f} {self.s(5):.2f}"' if dash else ""
        self.over.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{x1 - x0:.2f}" height="{y1 - y0:.2f}" fill="{fill}" stroke="{color}" '
                         f'stroke-width="{self.s(width):.2f}" opacity="{opacity}"{d}/>')

    def text(self, x: float, y: float, s: str, color: str = "#ffffff", size: float = 15, anchor: str = "start") -> None:
        px, py = self.px(x, y)
        self.over.append(f'<text x="{px:.2f}" y="{py:.2f}" font-size="{self.s(size):.2f}" fill="{color}" text-anchor="{anchor}" '
                         f'stroke="#000000" stroke-width="{self.s(3):.2f}" paint-order="stroke">{_label(s)}</text>')

    def line(self, ax: float, ay: float, bx: float, by: float, color: str, width_px: float, dash: bool = False, opacity: float = 1.0) -> None:
        x0, y0 = self.px(ax, ay)
        x1, y1 = self.px(bx, by)
        d = f' stroke-dasharray="{self.s(6):.2f} {self.s(4):.2f}"' if dash else ""
        self.over.append(f'<line x1="{x0:.2f}" y1="{y0:.2f}" x2="{x1:.2f}" y2="{y1:.2f}" stroke="{color}" stroke-width="{width_px:.2f}" '
                         f'stroke-linecap="round" opacity="{opacity}"{d}/>')

    def circle(self, x: float, y: float, r_px: float, color: str, fill: str = "none") -> None:
        px, py = self.px(x, y)
        self.over.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="{r_px:.2f}" fill="{fill}" stroke="{color}" stroke-width="{self.s(2):.2f}"/>')

    def dim(self, opacity: float = 0.55) -> None:
        x, y, w, h = self.vb
        self.over.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="#000000" opacity="{opacity}"/>')

    def grid(self) -> int:
        c = self.crop
        span = max(c[2] - c[0], c[3] - c[1])
        step = next((s for s in (1, 2, 5, 10, 20) if span / s <= 14), 20)
        lw = self.s(1)
        for i in range(math.ceil(c[0] / step), math.floor(c[2] / step) + 1):
            x = i * step
            self.line(x, c[1], x, c[3], "#ffffff", lw, opacity=0.22)
            self.text(x, c[1] + self.s(8) / abs(self.d), str(int(x)), "#e6e6e6", 13, "middle")
        for j in range(math.ceil(c[1] / step), math.floor(c[3] / step) + 1):
            y = j * step
            self.line(c[0], y, c[2], y, "#ffffff", lw, opacity=0.22)
            self.text(c[0] + self.s(5) / self.a, y - self.s(5) / abs(self.d), str(int(y)), "#e6e6e6", 13)
        return step

    def svg(self) -> str:
        i = self.body.rfind("</svg>")
        if i < 0:
            i = self.body.rfind("</ns0:svg>")
        return self.body[:i] + "".join(self.over) + self.body[i:]


def _crop(box: tuple[float, float, float, float], W: float, H: float, margin: float) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin
    # never more than 2:1, so a long net or a thin region still gives a readable picture
    w, h = x1 - x0, y1 - y0
    if w > 2 * h:
        cy, h = (y0 + y1) / 2, w / 2
        y0, y1 = cy - h / 2, cy + h / 2
    elif h > 2 * w:
        cx, w = (x0 + x1) / 2, h / 2
        x0, x1 = cx - w / 2, cx + w / 2
    # inside the board plus a little, so the edge shows
    x0, y0 = max(x0, -2.0), max(y0, -2.0)
    x1, y1 = min(x1, W + 2.0), min(y1, H + 2.0)
    return (x0, y0, x1, y1)


def _mark_user_parts(pic: Picture, things: dict[str, dict[str, Any]], skip: set[str], all_parts: bool) -> None:
    c = pic.crop
    # a label stays inside the picture even when its part is cut by the crop
    lx = lambda b: min(max(b[0], c[0] + pic.s(30) / pic.a), c[2] - pic.s(120) / pic.a)  # noqa: E731
    ly = lambda b: min(b[3] + pic.s(4) / abs(pic.d), c[3] - pic.s(16) / abs(pic.d))  # noqa: E731
    for i, t in things.items():
        b = _box(t)
        if b is None or i in skip or _overlap_area(b, c) <= 0:
            continue
        col = ACCESS_COLOR.get(str(t.get("access")))
        if t.get("_acc"):
            pic.rect(b, col or "#c7c7cc", 1.5, dash=True)
            pic.text(lx(b), ly(b), f"{i} module above", col or "#c7c7cc", 13)
        elif col:
            pic.rect(b, col, 2.0, dash=True)
            pic.text(lx(b), ly(b), i, col, 14)
        elif all_parts:
            pic.rect(b, "#d1d1d6", 1.0)
            pic.text(_centre(b)[0], _centre(b)[1], i, "#ffffff", 12, "middle")


async def inspect_board(ctx: Any, state: Any, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    row, error = await _version_row(ctx, args.get("version"))
    if row is None:
        return {"ok": False, "error": error}, []
    v = int(row["version"])
    board = _read_json(ctx.project_id, v, "board.json")
    if not board:
        return {"ok": False, "error": f"PCB v{v} has no board description (board.json): build_device again"}, []
    o = (board.get("pcb") or {}).get("outline") or {}
    W, H = float(o.get("w") or 0), float(o.get("h") or 0)
    cj = _read_json(ctx.project_id, v, "circuit.json")
    doc = _read_json(ctx.project_id, v, "device.json")
    circ = Circuit(cj, W, H, doc) if isinstance(cj, list) else None
    side = "bottom" if str(args.get("side") or "top").lower() == "bottom" else "top"
    layers = str(args.get("layers") or "all")
    if layers not in LAYERS:
        return {"ok": False, "error": f"layers must be one of {', '.join(LAYERS)}"}, []
    things = _things(board)
    focus = _as_obj(args.get("focus"))
    kind, target, facts = "board", None, {}
    if isinstance(focus, dict):
        x, y, w, h = (_num(focus.get(k)) for k in ("x", "y", "w", "h"))
        if None in (x, y, w, h) or w <= 0 or h <= 0:
            return {"ok": False, "error": "a region focus is {x, y, w, h} in board mm (x, y its bottom-left corner)"}, []
        kind, target = "region", (x, y, x + w, y + h)
        facts = region_facts(target, circ, board)
    elif isinstance(focus, str) and focus.strip():
        f = focus.strip()
        pid = None if "." in f else _find_id(things, f)
        if pid:
            kind, target = "part", pid
            facts = part_facts(pid, board, circ, doc)
        elif circ is not None:
            key = None
            if "." in f:
                comp, pin = f.split(".", 1)
                node = _doc_nodes(doc).get(comp) or next((n for i, n in _doc_nodes(doc).items() if i.lower() == comp.lower()), None)
                key = circ.key_of_pin(comp, _pad_names(node, pin))
                if key is None:
                    return {"ok": False, "error": f"{f}: no such pad on PCB v{v}"}, []
            else:
                key = circ.key_by_name(f)
            if key:
                kind, target = "net", key
                facts = net_facts(key, circ, board)
        if kind == "board":
            nets = sorted(set(circ.net_name.values())) if circ else []
            return {"ok": False, "error": f"{f!r} is neither a part nor a net of PCB v{v}",
                    "parts": sorted(things)[:40], "nets": nets[:30]}, []
    else:
        facts = board_facts(circ, board)
    # the picture
    name = "pcb_bottom.svg" if side == "bottom" else "pcb_top.svg"
    path = pcb_store.artifact_path(ctx.project_id, v, name)
    images: list[str] = []
    if path is not None:
        if kind == "part":
            b = _box(things[target]) or (0.0, 0.0, W, H)
            crop = _crop(b, W, H, CROP_MARGIN_MM)
        elif kind == "net":
            pts = [(p["x"], p["y"]) for p in circ.ports.values() if p["key"] == target] + \
                  [pt for t in circ.connections(target) for s in t["segs"] for pt in ((s[0], s[1]), (s[2], s[3]))]
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            crop = _crop((min(xs), min(ys), max(xs), max(ys)), W, H, 4.0) if pts else (-1.0, -1.0, W + 1, H + 1)
        elif kind == "region":
            crop = _crop(target, W, H, 1.0)
        else:
            crop = (-1.5, -1.5, W + 1.5, H + 1.5)
        try:
            pic = Picture(path.read_text(encoding="utf-8"), W, H, crop, layers)
        except (ValueError, ET.ParseError) as e:
            log.warning("inspect_board: %s v%s %s: %s", ctx.project_id, v, name, e)
            pic = None
        if pic is not None:
            skip: set[str] = set()
            if kind == "net":
                pic.dim()
                for t in circ.connections(target):
                    for ax, ay, bx, by, layer, wd in t["segs"]:
                        pic.line(ax, ay, bx, by, "#ffd60a" if layer == "top" else "#5ac8fa", max(pic.s(4), abs(pic.a) * wd * 1.6),
                                 dash=layer != "top")
                for vv in circ.vias:
                    if vv["key"] == target:
                        pic.circle(vv["x"], vv["y"], pic.s(6), "#ffffff", "#ffffff")
                for p in circ.ports.values():
                    if p["key"] == target:
                        pic.circle(p["x"], p["y"], pic.s(9), "#ff2d55")
                        pic.text(p["x"], p["y"] + pic.s(14) / abs(pic.d), p["ref"], "#ffffff", 14, "middle")
            else:
                if kind == "part":
                    skip = _family(things, target)
                _mark_user_parts(pic, things, skip, layers == "parts")
                if kind == "part":
                    b = _box(things[target])
                    if b:
                        pic.rect(b, "#00e5ff", 3.5)
                        pic.text(b[0], b[3] + pic.s(6) / abs(pic.d), target, "#00e5ff", 18)
                elif kind == "region":
                    pic.rect(target, "#00e5ff", 2.0, dash=True)
            step = pic.grid()
            png = await pcb.render_png_async(pic.svg(), pic.out_w)
            if png:
                tag = re.sub(r"[^A-Za-z0-9_-]", "_", str(target if kind in ("part",) else (facts.get("net") if kind == "net" else kind)))[:24]
                images.append(storage.save_bytes(ctx.project_id, "renders", f"pcb_v{v}_inspect_{side}_{layers}_{tag}.png", png))
                facts["picture"] = (f"{side} side, layers {layers}, grid {step} mm (labels in board mm, origin bottom-left)"
                                    + {"net": "; the net's copper bright (top yellow, bottom blue dashed), its pads circled, the rest dimmed",
                                       "part": "; the part outlined cyan; user-facing parts dashed (light yellow, sensor green, sound "
                                               "violet, display blue, button orange, port red), modules above the board grey"}.get(kind, ""))
    if not images:
        facts["picture"] = "the drawing could not be rendered; the facts are measured all the same"
    return {"ok": True, "version": v, "focus": kind, **facts}, images


# ------------------------------------------------------------------ the case
WRAP_JS = r"""
function build(p, lib) {
  const parts = __case.build(p, lib);
  const ghost = parts.find((q) => q && q.name === 'board' && q.role === 'reference');
  const rep = ghost && ghost.meta ? ghost.meta.enclosure : null;
  const up = __fw.mode === 'exploded' ? __fw.lift : 0;
  const out = [];
  for (const q of parts) {
    if (!q || !q.solid || q.name === 'stand') continue;  // a stand (stance tilt, upright) lies apart from the board and its frame
    if (q.name === 'lid') {
      if (__fw.mode === 'lid_off') continue;
      out.push(up ? { ...q, solid: q.solid.translate([0, 0, 2 * up]) } : q);
    } else if (q.role === 'reference') {
      out.push({ ...q, role: 'model', color: q === ghost ? __fw.board : q.color, solid: up ? q.solid.translate([0, 0, up]) : q.solid,
        settings: q === ghost ? { fw_report: rep } : q.settings });
    } else out.push(q);
  }
  // the user-facing parts in their colours over the board's one green, the focused part a little larger still
  const boxOf = (m, grow) => {
    const z = m.side === 'bottom' ? rep.zBoard - m.z0 - m.h : rep.zBoard + m.t + m.z0;
    return lib.M.cube([m.w + 2 * grow, m.d + 2 * grow, Math.max(0.3, m.h) + 2 * grow]).translate([m.x - m.w / 2 - grow, m.y - m.d / 2 - grow, z - grow + up]);
  };
  if (rep) for (const m of __fw.marks) out.push(lib.part(boxOf(m, 0.06), { name: 'mark_' + m.id, color: m.color }));
  if (rep && __fw.focus) out.push(lib.part(boxOf(__fw.focus, 0.2), { name: 'focus', color: __fw.focusColor }));
  return out;
}
return { meta: __case.meta, params: __case.params, build };
"""


def _box_cfg(t: dict[str, Any], T: float, color: str | None = None) -> dict[str, Any]:
    """A board.json part as the wrapper draws it (board frame, z0 above the face it sits on)."""
    out = {"id": str(t.get("id")), "x": float(t["x"]), "y": float(t["y"]), "w": float(t["w"]), "d": float(t["d"]), "h": float(t.get("h") or 0.5),
           "z0": float(t.get("z0") or 0), "t": T, "side": t.get("side") or "top"}
    return {**out, "color": color} if color else out


def case_program(source: str, mode: str, focus: dict[str, Any] | None = None, lift: float = 0.0,
                 marks: list[dict[str, Any]] | None = None) -> str:
    """The case program wrapped for a look: assembled with the board in it (a solid, dark green), the lid kept, removed or
    lifted, the user-facing parts in their colours, the focused part magenta; the board ghost carries the case's own report
    in its settings. Rendered, never saved."""
    cfg = json.dumps({"mode": mode, "focus": focus, "lift": lift, "marks": marks or [], "board": BOARD_RGB, "focusColor": FOCUS_RGB},
                     ensure_ascii=True)
    return ("// inspect_case: the case program, assembled for a close look (never saved)\n"
            "const __case = (function () {\n" + source + "\n})();\n" f"const __fw = {cfg};\n" + WRAP_JS)


async def _enclosure_findings(ctx: Any, state: Any) -> list[dict[str, Any]]:
    """The case check of the current case: the job's own, else the one stored with the program version."""
    enc = ((state.last_build or {}).get("checks") or {}).get("enclosure")
    if not isinstance(enc, dict) and state.version:
        try:
            from ..db import get_db

            r = await (await get_db()).one("SELECT checks FROM programs WHERE project_id = ? AND version = ?", ctx.project_id, int(state.version))
            enc = (json.loads(r["checks"]) if r and r.get("checks") else {}).get("enclosure")
        except Exception as e:  # noqa: BLE001 - the picture still helps without the findings
            log.info("inspect_case: no stored enclosure check: %s", e)
            enc = None
    return [f for f in (enc or {}).get("findings") or [] if isinstance(f, dict)] if isinstance(enc, dict) else []


OPENING_TYPES = {"light", "light_window", "sensor_window", "display_window", "sound_grille", "port_window", "flex_button", "cable_exit"}


def _feature_rect(f: dict[str, Any]) -> tuple[float, float, float, float] | None:
    at = f.get("at")
    if isinstance(at, list) and len(at) == 2 and _num(f.get("w")) and _num(f.get("d")):
        return (at[0] - f["w"] / 2, at[1] - f["d"] / 2, at[0] + f["w"] / 2, at[1] + f["d"] / 2)
    holes = f.get("holes")
    if isinstance(holes, list) and holes:
        r = (_num(f.get("d")) or 1.0) / 2
        xs, ys = [h[0] for h in holes], [h[1] for h in holes]
        return (min(xs) - r, min(ys) - r, max(xs) + r, max(ys) + r)
    return None


def _describe(f: dict[str, Any]) -> str:
    t = str(f.get("type"))
    if t == "sound_grille":
        s = f"sound grille of {f.get('count')} holes d {f.get('d')} mm"
    elif t == "flex_button":
        s = f"press tab {f.get('len')} mm long, plunger {f.get('plunger')} mm"
    elif t == "port_window":
        s = f"port window {f.get('w')} x {f.get('h')} mm in the {f.get('edge')} wall"
    elif t == "cable_exit":
        s = f"cable exit in the {f.get('edge')} wall"
    else:
        shape = "round " if f.get("shape") == "round" else ""
        mode = f" ({f['mode']})" if f.get("mode") else ""
        size = f"{f.get('w')} x {f.get('d')} mm" if f.get("w") else ""
        s = f"{shape}{t.replace('_', ' ')}{mode} {size}".strip()
    if isinstance(f.get("at"), list):
        s += f" at ({f['at'][0]}, {f['at'][1]})"
    for k in ("blocked", "shrunk", "covered"):
        if f.get(k):
            s += f"; {k} by {f[k]}"
    return s


def case_facts(pid: str | None, board: dict[str, Any], rep: dict[str, Any] | None, findings: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    rep = rep or {}
    if rep.get("outerSize"):
        out["case_mm"] = [_r(v) for v in rep["outerSize"]]
    feats = [f for f in rep.get("features") or [] if isinstance(f, dict)]
    T = float((board.get("pcb") or {}).get("thickness") or 1.6)
    if pid is None:
        out["openings"] = [f"{f.get('for')}: {_describe(f)}" for f in feats if f.get("type") in OPENING_TYPES and f.get("for")][:20]
        warn = [f.get("text") for f in feats if f.get("type") == "warning"]
        if warn:
            out["case_warnings"] = warn[:4]
        bad = [f"{f.get('part')}: {f.get('msg')}" for f in findings if f.get("severity") in ("error", "warn")]
        if bad:
            out["check_problems"] = bad[:10]
        return out
    t = _things(board)[pid]
    b = _box(t)
    z0 = float(t.get("z0") or 0)
    h = float(t.get("h") or 0)
    part: dict[str, Any] = {"id": pid, "access": t.get("access") or "none"}
    if b:
        part["at_mm"] = [_r(t["x"]), _r(t["y"])]
        part["size_mm"] = [_r(t["w"]), _r(t["d"]), _r(h)]
    out["part"] = part
    zb = _num(rep.get("zBoard"))
    zt = _num(rep.get("zTop"))
    if zb is not None and zt is not None and t.get("side") != "bottom":
        top = zb + T + z0 + h
        out["part_top_z_mm"] = _r(top)
        out["lid_underside_above_part_mm"] = _r(zt - top)
        if rep.get("lidT"):
            out["lid_mm"] = _r(rep["lidT"])
    inner = rep.get("inner") or {}
    if b and all(_num(inner.get(k)) is not None for k in ("x0", "y0", "x1", "y1")):
        walls = {"-x": _r(b[0] - inner["x0"]), "+x": _r(inner["x1"] - b[2]), "-y": _r(b[1] - inner["y0"]), "+y": _r(inner["y1"] - b[3])}
        near = min(walls, key=walls.get)
        out["inner_walls_mm"] = walls
        out["nearest_wall"] = f"{near} {walls[near]} mm"
    own = [f for f in feats if str(f.get("for")) == pid or (isinstance(f.get("for"), list) and pid in f["for"])]
    over = []
    if b:
        area = max(1e-6, (b[2] - b[0]) * (b[3] - b[1]))
        for f in feats:
            if f.get("type") not in OPENING_TYPES - {"port_window", "cable_exit", "flex_button"}:
                continue
            r = _feature_rect(f)
            if r is None:
                continue
            ov = _overlap_area(b, r)
            if ov <= 0 and f not in own:
                continue
            c1, c2 = _centre(b), _centre(r)
            over.append(f"{_describe(f)} (for {f.get('for')}): uncovers {100 * ov / area:.0f}% of {pid}, window centre "
                        f"{_r(c2[0] - c1[0])}, {_r(c2[1] - c1[1])} mm from the part's centre")
    out["opening"] = over or [_describe(f) for f in own] or ["none: the lid is closed over it" if t.get("side") != "bottom" else "none"]
    if own and not over:
        out["opening"] = [_describe(f) for f in own]
    mine = [f"{f.get('severity')}: {f.get('msg')}" for f in findings if str(f.get("part")) == pid]
    if mine:
        out["case_check"] = mine[:8]
    return out


async def inspect_case(ctx: Any, state: Any, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    from . import pcb_tools
    from .tools import _geom_retry, _render_args, geom

    made_from = pcb_tools.case_for(state)
    if made_from is None or not state.source:
        return {"ok": False, "error": "no case yet: make_enclosure first"}, []
    board = (((state.inputs or {}).get("boards") or {}).get(pcb_tools.BOARD)) or {}
    mode = str(args.get("mode") or "assembled")
    if mode not in MODES:
        return {"ok": False, "error": f"mode must be one of {', '.join(MODES)}"}, []
    things = _things(board)
    pid = None
    if args.get("focus"):
        pid = _find_id(things, str(args["focus"]).strip())
        if pid is None:
            return {"ok": False, "error": f"{args['focus']!r} is not a part of the board in this case",
                    "parts": sorted(i for i, t in things.items() if _box(t))[:40]}, []
        if _box(things[pid]) is None:
            return {"ok": False, "error": f"{pid} has no position of its own on the board (an edge part of its module): focus the module"}, []
    T = float((board.get("pcb") or {}).get("thickness") or 1.6)
    focus_cfg = _box_cfg({**things[pid], "id": pid}, T) if pid else None
    marks = [_box_cfg({**t, "id": i}, T, ACCESS_COLOR[str(t.get("access"))]) for i, t in things.items()
             if i != pid and str(t.get("access")) in ACCESS_COLOR and _box(t) is not None]
    ra = _render_args(state)
    params = {**ra.pop("params"), "layout": "assembled", "show_board": True}
    # first the report (window rectangles, lid height, inner walls), then the picture from the same kept build
    probe = case_program(state.source, mode if mode in ("assembled", "lid_off") else "assembled", focus_cfg, 0.0, marks)
    built = await _geom_retry(lambda: geom().build(probe, params, analyze="none", **ra))
    rep = next((p.get("settings", {}).get("fw_report") for p in built.get("parts") or []
                if isinstance(p, dict) and isinstance(p.get("settings"), dict) and p["settings"].get("fw_report")), None) or {}
    case_h = float((rep.get("outerSize") or [0, 0, 30])[2])
    lift = max(12.0, round(case_h * 0.9, 1))
    source = probe if mode in ("assembled", "lid_off", "section") else case_program(state.source, mode, focus_cfg, lift, marks)
    zb = float(rep.get("zBoard") or 0)
    extra: dict[str, Any] = {}
    view = str(args.get("view") or "").lower()
    if view and view not in VIEWS:
        return {"ok": False, "error": f"view must be one of {', '.join(VIEWS)}"}, []
    names = [view] if view else DEFAULT_VIEWS.get(mode, [])
    if names:
        extra["views"] = [{"name": n.upper(), "azimuth": VIEWS[n][0], "elevation": VIEWS[n][1]} for n in names]
    up = lift if mode == "exploded" else 0.0
    if pid:
        t = things[pid]
        zc = zb + T + float(t.get("z0") or 0) + float(t.get("h") or 0) / 2
        span = max(float(t["w"]), float(t["d"])) + 18.0
        if mode == "exploded":
            # the lifted part in the middle, the lid above it in the frame
            span, zc = max(span, 2 * lift + 12), zc + lift
        extra["focus"] = {"center": [float(t["x"]), float(t["y"]), zc], "size": span}
        extra["markers"] = [{"at": [float(t["x"]), float(t["y"]), zb + T + float(t.get("z0") or 0) + float(t.get("h") or 0) + up], "label": pid}]
    if mode == "section":
        cut = _as_obj(args.get("cut")) or {}
        axis = str(cut.get("axis") or "y") if isinstance(cut, dict) else "y"
        if axis not in ("x", "y", "z"):
            return {"ok": False, "error": "cut.axis must be x, y or z"}, []
        at = _num(cut.get("at")) if isinstance(cut, dict) else None
        o = (board.get("pcb") or {}).get("outline") or {}
        if at is None:
            if pid:
                at = float(things[pid]["x" if axis == "x" else "y"]) if axis != "z" else T + float(things[pid].get("z0") or 0) + float(things[pid].get("h") or 0) / 2
            else:
                at = {"x": float(o.get("w") or 0) / 2, "y": float(o.get("h") or 0) / 2, "z": T + 1.0}[axis]
        # the cut is given in the board frame; the case frame has the board's x and y, z from the case's floor
        extra["cut"] = {"axis": axis, "at": at + (zb if axis == "z" else 0.0), "keep": "below"}
        if axis == "z":
            extra.setdefault("views", [{"name": "TOP", "azimuth": 0.0, "elevation": 90.0}])
    n_views = len(extra.get("views") or []) or 3
    extra["tile"] = 640 if n_views == 1 else 460
    extra["title"] = f"{mode.replace('_', ' ')}{' ' + pid if pid else ''}"
    await ctx.status("Looking at the case" + (f" around {pid}" if pid else ""))
    r = await _geom_retry(lambda: geom().render(source, params, view="sheet", **ra, **extra))
    import base64

    name = f"v{state.version}_case_{mode}{'_' + view if view else ''}{'_' + re.sub(r'[^A-Za-z0-9_-]', '_', pid) if pid else ''}.png"
    image = storage.save_bytes(ctx.project_id, "renders", name, base64.b64decode(r["png"]))
    facts = case_facts(pid, board, rep, await _enclosure_findings(ctx, state))
    legend = ("case base grey, lid orange, board dark green; lights yellow, sensors green, sound violet, displays blue, buttons "
              "orange, ports red" + (f"; {pid} magenta with a dot (hollow where the case hides it)" if pid else ""))
    if mode == "exploded":
        legend += f"; lid lifted {_r(2 * lift)} mm, board {_r(lift)} mm"
    if mode == "section":
        legend += f"; cut at {extra['cut']['axis']}={_r(extra['cut']['at'] - (zb if extra['cut']['axis'] == 'z' else 0))} mm (board frame)"
    return {"ok": True, "case_version": state.version, "pcb_version": made_from, "mode": mode, "picture": legend, **facts}, [image]


# ------------------------------------------------------------------ one part, as text
def _pin_net(doc: dict[str, Any], ref: str) -> dict[str, Any] | None:
    return next((n for n in doc.get("nets") or [] if ref in (n.get("pins") or [])), None)


def _net_label(net: dict[str, Any] | None) -> str:
    if not net:
        return "not connected"
    return str(net.get("name") or "unnamed")


def _transistor_pins(node_pins: set[str]) -> tuple[set[str], set[str]] | None:
    """(switched, control) pins of a transistor node, by its pin names."""
    up = {p.upper() for p in node_pins}
    if {"G", "D"} <= up:
        return {"D", "S"}, {"G"}
    if {"B", "C"} <= up:
        return {"C", "E"}, {"B"}
    return None


def mcu_paths(doc: dict[str, Any], nid: str) -> list[str]:
    """Which microcontroller pins reach this node: straight on a net, through series resistors, or through a transistor's
    switched side to its gate or base (at most 4 hops)."""
    nodes = _doc_nodes(doc)
    mcus = {i for i, n in nodes.items() if n.get("kind") == "module" and n.get("module") in device.MODULES}
    if not mcus or nid in mcus:
        return []
    pins_by_node: dict[str, set[str]] = {}
    for net in doc.get("nets") or []:
        for ref in net.get("pins") or []:
            if "." in ref:
                a, p = ref.split(".", 1)
                pins_by_node.setdefault(a, set()).add(p)
    out: list[str] = []
    start = [f"{nid}.{p}" for p in sorted(pins_by_node.get(nid, set()))]
    seen = set(start)
    queue = [(r, [nid]) for r in start]
    while queue:
        ref, path = queue.pop(0)
        net = _pin_net(doc, ref)
        if not net or device.POWER_NET.match(str(net.get("name") or "")):
            continue
        for other in net.get("pins") or []:
            if other in seen:
                continue
            seen.add(other)
            oid, opin = other.split(".", 1)
            if oid in mcus:
                gp = device.MODULES[nodes[oid]["module"]].get("gpio", {}).get(opin)
                via = f" via {', '.join(path[1:])}" if len(path) > 1 else ""
                out.append(f"{other}{f' (GPIO{gp})' if gp is not None else ''}{via}")
                continue
            if len(path) >= 4:
                continue
            on = nodes.get(oid) or {}
            nxt: list[str] = []
            if on.get("kind") == "resistor":
                nxt = [f"{oid}.{p}" for p in ("1", "2") if p != opin]
            else:
                tr = _transistor_pins(pins_by_node.get(oid, set()))
                if tr and opin.upper() in tr[0]:
                    nxt = [f"{oid}.{p}" for p in pins_by_node.get(oid, set()) if p.upper() in tr[1]]
            for n2 in nxt:
                if n2 not in seen:
                    seen.add(n2)
                    queue.append((n2, path + [oid]))
    return out


def _fw_tokens(doc: dict[str, Any], mcu_refs: list[str]) -> tuple[set[str], set[int]]:
    """Names (D1, MOSI, D10, GPIO3) and GPIO numbers the firmware may use for these microcontroller pins."""
    nodes = _doc_nodes(doc)
    names: set[str] = set()
    nums: set[int] = set()
    for r in mcu_refs:
        ref = r.split(" ", 1)[0]
        mid, pin = ref.split(".", 1)
        m = device.MODULES.get((nodes.get(mid) or {}).get("module") or "") or {}
        names.add(pin)
        names.update(a for a, t in (m.get("aliases") or {}).items() if t == pin and re.match(r"^[A-Za-z]\w*$", a))
        g = (m.get("gpio") or {}).get(pin)
        if g is None and re.match(r"^GP\d+$", pin):
            g = int(pin[2:])
        if g is not None:
            nums.add(int(g))
            names.update({f"GPIO{g}", f"GPIO_NUM_{g}"})
    return names, nums


def firmware_lines(doc: dict[str, Any], part: dict[str, Any], mcu_refs: list[str]) -> list[str]:
    """Every firmware line that uses this node's microcontroller pins: by name, alias, GPIO number, or a constant defined
    from one; plus lines naming the part (its MPN or I2C bus for an I2C part)."""
    files = ((doc.get("firmware") or {}).get("files")) or {}
    if not files:
        return []
    names, nums = _fw_tokens(doc, mcu_refs)
    mpn = re.match(r"[A-Za-z]+\d+", str(part.get("mpn") or part.get("name") or ""))
    words = {w for w in [mpn.group(0) if mpn and len(mpn.group(0)) >= 4 else None] if w}
    pats = [re.compile(rf"(?<![\w.]){re.escape(n)}(?!\w)") for n in sorted(names)]
    num_pat = re.compile(r"(?<![\w.])(" + "|".join(str(n) for n in sorted(nums)) + r")(?![\w.])") if nums else None
    consts: set[str] = set()
    hits: list[tuple[str, int, str]] = []
    for fname, text in files.items():
        lines = str(text).splitlines()
        for i, ln in enumerate(lines, 1):
            code = ln.split("//", 1)[0] if not ln.lstrip().startswith("#") else ln
            hit = any(p.search(ln) for p in pats)
            if not hit and num_pat and FW_CONTEXT.search(code) and num_pat.search(code):
                hit = True
            if not hit and words and any(w.lower() in ln.lower() for w in words):
                hit = True
            if hit:
                hits.append((fname, i, ln.strip()))
                m = re.match(r"\s*#define\s+(\w+)\s+", ln) or re.match(r"\s*(?:static\s+)?(?:const(?:expr)?\s+)?\w+\s+(?:const\s+)?(\w+)\s*=\s*\w+\s*;", code)
                if m and m.group(1) not in names:
                    consts.add(m.group(1))
        if consts:
            cpat = re.compile(r"(?<!\w)(" + "|".join(re.escape(c) for c in sorted(consts)) + r")(?!\w)")
            for i, ln in enumerate(lines, 1):
                if cpat.search(ln) and not any(h[0] == fname and h[1] == i for h in hits):
                    hits.append((fname, i, ln.strip()))
    hits.sort(key=lambda h: (h[0], h[1]))
    out = [f"{f}:{i}: {s[:140]}" for f, i, s in hits[:FW_LINES_MAX]]
    if len(hits) > FW_LINES_MAX:
        out.append(f"and {len(hits) - FW_LINES_MAX} more lines")
    return out


async def _card(node: dict[str, Any]) -> dict[str, Any]:
    from .. import accessories, catalog

    k = node.get("kind")
    try:
        if k == "chip" and node.get("lcsc"):
            c = await catalog.info(str(node["lcsc"]))
            return {k2: c[k2] for k2 in ("lcsc", "mpn", "brand", "package", "category", "kind_hint", "current_ma", "stock", "basic",
                                         "datasheet") if c.get(k2) is not None} | {"description": str(c.get("description") or "")[:240],
                                                                                   "pins": c.get("pins") or []}
        if k == "module":
            m = device.MODULES.get(str(node.get("module"))) or {}
            return {"mpn": m.get("name"), "mcu": m.get("mcu"), "wireless": m.get("wireless"), "firmware": m.get("fw"),
                    "strapping_gpio": m.get("strapping"), "adc_pins": m.get("adc"), "battery": m.get("battery")}
        if k == "accessory":
            a = accessories.ACCESSORIES.get(str(node.get("accessory"))) or {}
            return {k2: a[k2] for k2 in ("name", "kind", "supply", "current_ma", "i2c_addr", "connect", "mount", "body", "window", "note")
                    if a.get(k2) is not None}
    except catalog.CatalogError as e:
        return {"error": str(e)}
    return {k2: node[k2] for k2 in ("value", "package", "color") if node.get(k2)}


async def inspect_part(ctx: Any, state: Any, args: dict[str, Any]) -> dict[str, Any]:
    from . import device_tools, pcb_tools

    want = str(args.get("id") or "").strip()
    if not want:
        return {"ok": False, "error": "id is empty: give a node id such as 'U2'"}
    raw, dv = await device_tools.current(ctx.project_id)
    if not raw:
        return {"ok": False, "error": "no device yet: write_device first"}
    doc, _ = device.normalize(raw)
    doc["firmware"] = raw.get("firmware")
    nodes = _doc_nodes(doc)
    nid = _find_id(nodes, want)
    if nid is None:
        return {"ok": False, "error": f"there is no node {want!r}", "nodes": sorted(nodes)[:40]}
    node = nodes[nid]
    card = await _card(node)
    out: dict[str, Any] = {"ok": True, "id": nid, "device_version": dv, "kind": node.get("kind")}
    if node.get("label"):
        out["label"] = node["label"]
    pins_meta = {p.get("label"): p for p in card.pop("pins", []) if isinstance(p, dict)}
    out["card"] = card
    if node.get("face") or node.get("edge") or node.get("place"):
        out["design"] = {k: node[k] for k in ("face", "edge", "place") if node.get(k)}
    # pins and nets
    pins = []
    labels = {str(n.get("id")): n.get("label") for n in doc.get("nodes") or []}
    try:
        names = device.pins_of(node, {"pins": list(pins_meta.values())} if pins_meta else None)
    except KeyError:
        names = []
    wired = {r.split(".", 1)[1] for net in doc.get("nets") or [] for r in net.get("pins") or [] if r.split(".", 1)[0] == nid}
    for p in list(dict.fromkeys([*names, *sorted(wired)])):
        net = _pin_net(doc, f"{nid}.{p}")
        if net is None and p not in wired:
            if p.upper().startswith("NC"):
                continue
            pins.append(f"{p}: not connected")
            continue
        others = [r + (f" ({labels.get(r.split('.', 1)[0])})" if labels.get(r.split(".", 1)[0]) else "") for r in net.get("pins") or []
                  if r != f"{nid}.{p}"]
        pins.append(f"{p} -> {_net_label(net)}: " + (", ".join(others[:8]) + (f" and {len(others) - 8} more" if len(others) > 8 else "")
                                                     if others else "nothing else"))
    out["pins"] = pins[:40]
    mcu = mcu_paths(doc, nid)
    if mcu:
        out["driven_by"] = mcu
    # where the latest board put it
    row = await pcb_store.get(ctx.project_id)
    board = None
    if row:
        v = int(row["version"])
        board = pcb_tools._board(ctx.project_id, v)
        built = _read_json(ctx.project_id, v, "device.json") or {}
        o = ((board or {}).get("pcb") or {}).get("outline") or {}
        things = _things(board or {})
        if nid in things:
            cj = _read_json(ctx.project_id, v, "circuit.json")
            circ = Circuit(cj, float(o.get("w") or 0), float(o.get("h") or 0), built) if isinstance(cj, list) else None
            pf = part_facts(nid, board, circ, built)
            out["board"] = {"pcb_version": v, **{k: pf[k] for k in ("at_mm", "rotation", "size_mm", "side", "access", "nearest_edge", "faces",
                                                                    "under", "lights_within_20mm", "sensors_within_20mm", "accessory")
                                                if k in pf}}
            if pf.get("neighbours"):
                out["board"]["neighbours"] = pf["neighbours"][:6]
            if pf.get("connections"):
                out["board"]["longest_connection"] = pf["connections"][0]
        else:
            out["board"] = {"pcb_version": v, "note": f"{nid} is not on PCB v{v}" + ("" if built.get("_version") == dv else
                                                                                       ": the board was built from an older device version")}
        if built.get("_version") is not None and built.get("_version") != dv:
            out["board"]["built_from_device_version"] = built.get("_version")
    else:
        out["board"] = "not built yet: build_device"
    # the case opening over it
    made_from = pcb_tools.case_for(state)
    if made_from is not None and board is not None:
        findings = [f for f in await _enclosure_findings(ctx, state) if str(f.get("part")) == nid]
        out["case"] = ([f"{f.get('severity')}: {f.get('msg')}" for f in findings][:6] or
                       [f"no finding names {nid}: " + ("its access is none, so the case cuts nothing over it"
                                                      if (_things(board).get(nid) or {}).get("access") in (None, "none")
                                                      else "make_enclosure again")])
        if made_from != (row or {}).get("version"):
            out["case"].append(f"the case was made from PCB v{made_from}, not the latest board")
    elif row is not None:
        out["case"] = "no case for this board yet: make_enclosure"
    # firmware
    fw = doc.get("firmware") or {}
    if fw.get("files"):
        lines = firmware_lines(doc, card, mcu if nid not in {i for i, n in nodes.items() if n.get("kind") == "module"} else
                               [f"{nid}.{p}" for p in wired])
        out["firmware"] = lines or [f"no line of {', '.join(fw['files'])} uses {nid}'s pins"
                                    + (f" ({', '.join(m.split(' ', 1)[0] for m in mcu)})" if mcu else "")]
    else:
        out["firmware"] = "none yet: write_firmware"
    # the design rules that name it
    items = await device_tools.design_checks(doc)
    word = re.compile(rf"(?<![\w]){re.escape(nid)}(?![\w])")
    named = [f"{i.get('severity', 'warn')} {i.get('code')}: {i.get('msg')}" + (f" -> {i['hint']}" if i.get("hint") else "")
             for i in items if str(i.get("ref") or "").split(".")[0] == nid or word.search(str(i.get("msg") or ""))]
    out["design_rules"] = named[:8] or ["none name it"]
    return out
