"""Probe prints: when a dimension is less certain than the fit needs, print a tiny
gauge with a few labelled variants (a 5-15 minute print), let the person try them
on the real object and feed the winner back into the design.

Variants are *design* values: the probe is built with the same stdlib and printer
compensation as the final part, so "variant 32.4 fits" means "design it at 32.4".
"""
from __future__ import annotations

import json
import math
from typing import Any, Literal

from ..knowledge.facts import standards

Kind = Literal["hole", "peg", "gap", "thread", "clip"]

# label size/stroke chosen to pass the printability checks on a 0.4 mm nozzle
LABEL = "{ size: 5, stroke: 0.9, depth: 0.6 }"


def _label(v: float, prefix: str = "") -> str:
    return prefix + (f"{v:.2f}".rstrip("0").rstrip("."))


def _step(kind: str, nominal: float) -> float:
    if kind in ("gap", "clip"):
        return 0.2
    if nominal <= 10:
        return 0.1
    if nominal <= 30:
        return 0.15
    return 0.2


def default_variants(kind: Kind, nominal: float) -> list[float]:
    if kind == "thread":
        return [0.2, 0.3, 0.4, 0.5]
    s = _step(kind, nominal)
    return [round(nominal + k * s, 3) for k in (-2, -1, 0, 1, 2)]


def _common(title: str, values: list[float], labels: list[str], params: dict[str, Any]) -> str:
    return (
        f"const meta = {{ title: {json.dumps(title)}, pack: 'probe' }};\n"
        f"const VALUES = {json.dumps(values)};\n"
        f"const LABELS = {json.dumps(labels)};\n"
        f"const params = {json.dumps(params)};\n"
        f"const LABEL = {LABEL};\n"
    )


def _hole(values: list[float], labels: list[str], extra: dict) -> tuple[str, float]:
    t = float(extra.get("thickness", 4))
    src = _common("Hole fit probe", values, labels, {"thickness": {"value": t, "min": 2, "max": 12, "unit": "mm", "source": "design"}}) + """
function build(p, lib) {
  const { std, M } = lib;
  const dmax = Math.max(...VALUES);
  const cellW = Math.max(dmax + 8, 22), cellH = dmax + 16;
  const cols = dmax > 20 ? 3 : VALUES.length, rows = Math.ceil(VALUES.length / cols);
  let plate = std.box([cols * cellW, rows * cellH, p.thickness], { r: 2, chamferBottom: 0.4 });
  const labels = [];
  VALUES.forEach((d, i) => {
    const cx = ((i % cols) - (cols - 1) / 2) * cellW;
    const cy = ((rows - 1) / 2 - Math.floor(i / cols)) * cellH + 3.5;
    plate = plate.subtract(std.holeZ(d, p.thickness, { at: [cx, cy, p.thickness], through: true }));
    labels.push(std.text(LABELS[i], LABEL).translate([cx, cy - d / 2 - 5, p.thickness]));
  });
  return M.union([plate, ...labels]);
}
return { meta, params, build };
"""
    dmax = max(values)
    area = (max(dmax + 8, 22) * (dmax + 16)) * len(values) - sum(math.pi * d * d / 4 for d in values)
    return src, area * t


def _peg(values: list[float], labels: list[str], extra: dict) -> tuple[str, float]:
    h = float(extra.get("height", 8))
    src = _common("Peg fit probe", values, labels, {"height": {"value": h, "min": 3, "max": 25, "unit": "mm", "source": "design"}}) + """
function build(p, lib) {
  const { std, M } = lib;
  const dmax = Math.max(...VALUES);
  const cellW = Math.max(dmax + 8, 22), cellH = dmax + 16;
  const cols = dmax > 20 ? 3 : VALUES.length, rows = Math.ceil(VALUES.length / cols);
  const base = 2;
  const parts = [std.box([cols * cellW, rows * cellH, base], { r: 2, chamferBottom: 0.4 })];
  VALUES.forEach((d, i) => {
    const cx = ((i % cols) - (cols - 1) / 2) * cellW;
    const cy = ((rows - 1) / 2 - Math.floor(i / cols)) * cellH + 3.5;
    parts.push(std.extrude(std.circle(d), p.height, { chamferTop: 0.4 }).translate([cx, cy, base - 0.01]));
    parts.push(std.text(LABELS[i], LABEL).translate([cx, cy - d / 2 - 5, base]));
  });
  return M.union(parts);
}
return { meta, params, build };
"""
    dmax = max(values)
    vol = max(dmax + 8, 22) * (dmax + 16) * len(values) * 2 + sum(math.pi * d * d / 4 * h for d in values)
    return src, vol


def _gap(values: list[float], labels: list[str], extra: dict) -> tuple[str, float]:
    depth = float(extra.get("depth", 14))
    src = _common("Gap fit probe (comb)", values, labels, {
        "depth": {"value": depth, "min": 6, "max": 40, "unit": "mm", "source": "design"},
        "tooth": {"value": 4, "min": 2.5, "max": 10, "unit": "mm", "source": "design"},
        "height": {"value": 6, "min": 3, "max": 20, "unit": "mm", "source": "design"},
    }) + """
function build(p, lib) {
  const { std, M } = lib;
  const labelW = 20;
  const pitch = (g) => Math.max(g + p.tooth, labelW);
  const total = VALUES.reduce((s, g) => s + pitch(g), 0) + p.tooth;
  const bar = 10;
  const solids = [std.box([total, bar, p.height], { center: false, chamferBottom: 0.4 })];
  let x = 0;
  VALUES.forEach((g, i) => {
    const w = pitch(g);
    // tooth on the left of every slot, slot of width g, then the next tooth
    solids.push(std.box([w - g, p.depth, p.height], { center: false, chamferBottom: 0.4 }).translate([x, bar - 0.01, 0]));
    solids.push(std.text(LABELS[i], LABEL).translate([x + (w - g) + g / 2, bar / 2, p.height]));
    x += w;
  });
  solids.push(std.box([p.tooth, p.depth, p.height], { center: false, chamferBottom: 0.4 }).translate([x, bar - 0.01, 0]));
  return M.union(solids);
}
return { meta, params, build };
"""
    vol = sum(max(g + 4, 20) for g in values) * (10 * 6) + len(values) * 4 * depth * 6
    return src, vol


def _clip(values: list[float], labels: list[str], extra: dict) -> tuple[str, float]:
    wall = float(extra.get("wall", 3))
    depth = float(extra.get("depth", 12))
    src = _common("Clip fit probe", values, labels, {
        "wall": {"value": wall, "min": 1.6, "max": 8, "unit": "mm", "source": "design"},
        "depth": {"value": depth, "min": 6, "max": 40, "unit": "mm", "source": "design"},
        "height": {"value": 8, "min": 4, "max": 20, "unit": "mm", "source": "design"},
    }) + """
function build(p, lib) {
  const { std, M } = lib;
  const parts = [];
  let x = 0;
  const backH = 9;
  const pitchOf = (g) => Math.max(g + 2 * p.wall + 3, 22);
  const total = VALUES.reduce((s, g) => s + pitchOf(g), 0);
  // shared back bar carries the labels and keeps the clips in one piece
  parts.push(std.box([total, backH, p.height], { center: false, chamferBottom: 0.4 }).translate([0, -backH + 0.01, 0]));
  VALUES.forEach((g, i) => {
    const w = g + 2 * p.wall;
    const pitch = pitchOf(g);
    const x0 = x + (pitch - w) / 2;
    const outer = std.rect(w, p.depth + p.wall, { center: false });
    const inner = std.rect(g, p.depth + 1, { center: false }).translate([p.wall, p.wall]);
    // small lip at the arm tips to feel the snap
    const lip = std.rect(0.6, 1.2, { center: false });
    let cs = outer.subtract(inner).add(lip.translate([p.wall - 0.01, p.depth + p.wall - 1.2])).add(lip.translate([p.wall + g - 0.59, p.depth + p.wall - 1.2]));
    parts.push(std.extrude(cs, p.height, { chamferBottom: 0.4 }).translate([x0, 0, 0]));
    parts.push(std.text(LABELS[i], LABEL).translate([x + pitch / 2, -backH / 2, p.height]));
    x += pitch;
  });
  return M.union(parts);
}
return { meta, params, build };
"""
    vol = sum((g + 2 * wall) * (depth + wall) - g * depth for g in values) * 8 + sum(max(g + 2 * wall + 3, 22) for g in values) * 9 * 8
    return src, vol


def _thread(values: list[float], labels: list[str], nominal: float, extra: dict) -> tuple[str, float]:
    pitch = extra.get("pitch")
    if pitch is None:
        table = standards().get("metric_coarse_pitch", {})
        pitch = table.get(f"M{int(round(nominal))}") if abs(nominal - round(nominal)) < 0.05 else None
        pitch = float(pitch or (1.5 if nominal < 16 else 2.5))
    pitch = float(pitch)
    starts = int(extra.get("starts", 1))
    height = max(pitch * 3 * max(1, starts) * 0 + pitch * 3, 6.0)
    src = _common("Thread fit probe", values, labels, {
        "d": {"value": nominal, "min": 3, "max": 120, "unit": "mm", "source": "photo"},
        "pitch": {"value": pitch, "min": 0.3, "max": 8, "unit": "mm", "source": "design"},
        "height": {"value": round(height, 2), "min": 4, "max": 30, "unit": "mm", "source": "design"},
    }) + f"""
const STARTS = {starts};
function build(p, lib) {{
  const {{ std, M }} = lib;
  const od = p.d + 9;
  const cell = Math.max(od + 4, 24);
  const base = 1.6;
  const parts = [];
  let plate = std.box([cell * VALUES.length, cell + 10, base], {{ r: 2, chamferBottom: 0.4 }});
  VALUES.forEach((c, i) => {{
    const cx = (i - (VALUES.length - 1) / 2) * cell, cy = 5;
    const cutter = std.thread({{ d: p.d, pitch: p.pitch, length: p.height + base, internal: true, clearance: c, starts: STARTS }});
    const ring = std.cyl(od, p.height).translate([cx, cy, base - 0.01]);
    plate = plate.subtract(std.cyl(p.d + c + 0.6, base + 2).translate([cx, cy, -1]));
    parts.push(ring.subtract(cutter.translate([cx, cy, 0])));
    parts.push(std.text(LABELS[i], LABEL).translate([cx, -cell / 2 + 2.5, base]));
  }});
  return M.union([plate, ...parts]);
}}
return {{ meta, params, build }};
"""
    od = nominal + 9
    vol = len(values) * (math.pi / 4 * (od * od - nominal * nominal) * height) + len(values) * max(od + 4, 24) * (max(od + 4, 24) + 10) * 1.6
    return src, vol


def make_probe(kind: Kind, nominal: float, *, variants: list[float] | None = None, extra: dict | None = None) -> dict[str, Any]:
    extra = extra or {}
    values = [round(float(v), 3) for v in (variants or default_variants(kind, nominal))]
    if not values:
        raise ValueError("a probe needs at least one variant")
    if kind == "thread":
        labels = [_label(v, "C") for v in values]
        src, vol = _thread(values, labels, nominal, extra)
    else:
        labels = [_label(v) for v in values]
        builders = {"hole": _hole, "peg": _peg, "gap": _gap, "clip": _clip}
        if kind not in builders:
            raise ValueError(f"unknown probe kind {kind!r}")
        src, vol = builders[kind](values, labels, extra)
    # ~10 mm³/s average for small parts at 15-20% infill, plus heat-up and first layer
    est_minutes = round(3 + vol * 0.45 / 10 / 60, 1)
    return {
        "kind": kind,
        "nominal": nominal,
        "source": src,
        "variants": [{"label": l, "value": v} for l, v in zip(labels, values)],
        "est_minutes": est_minutes,
        "meaning": "clearance (mm, diametral) of the internal thread" if kind == "thread" else "design value in mm",
    }


def apply_choice(variants: list[dict[str, Any]], chosen_label: str) -> float:
    """Value of the variant the person picked: by label ('32.4', 'C0.3') or 1-based index ('2')."""
    key = str(chosen_label).strip().lower().replace(",", ".")
    for v in variants:
        if str(v["label"]).lower() == key:
            return float(v["value"])
    if key.isdigit() and 1 <= int(key) <= len(variants):
        return float(variants[int(key) - 1]["value"])
    for v in variants:
        try:
            if abs(float(key.lstrip("c")) - float(v["value"])) < 1e-6:
                return float(v["value"])
        except ValueError:
            break
    raise ValueError(f"no variant {chosen_label!r}; options: {', '.join(v['label'] for v in variants)}")
