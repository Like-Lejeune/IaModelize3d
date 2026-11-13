"""Justified print profile: every change to the stock profile cites evidence.

1. `features()` turns printability checks, model stats and the project brief into
   evidence items with stable ids (tall_thin, overhang, long_bridge, ...).
2. Rules (printing/rules.py) fire only on present evidence and bound one setting each.
3. Optionally a model refines the diff, but everything it says is validated: only
   whitelisted keys, at least one existing evidence id, values inside machine limits.
   Anything else is dropped. No evidence -> no change.
"""
from __future__ import annotations

import json
import logging
import math
from collections import defaultdict
from typing import Any

from ..config import settings
from ..llm.client import CostMeter, meta
from .presets import first, num
from .rules import PART_RULES, PART_SETTINGS, RULES, SETTINGS

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ evidence
def _issues(checks: dict | None, code: str) -> list[dict]:
    return [i for i in (checks or {}).get("issues", []) if i.get("code") == code]


def _z0(items: list[dict]) -> float | None:
    zs = [i["z"][0] for i in items if i.get("z")]
    return min(zs) if zs else None


def features(checks: dict | None, stats: dict | None, brief: dict | None) -> list[dict]:
    checks = checks or {}
    stats = stats or checks.get("stats") or {}
    brief = brief or {}
    ev: list[dict] = []

    def add(kind: str, value: Any, detail: str, z0: float | None = None, z1: float | None = None) -> None:
        item: dict[str, Any] = {"id": kind, "kind": kind, "value": value, "detail": detail}
        if z0 is not None:
            item["z0"] = round(z0, 2)
        if z1 is not None:
            item["z1"] = round(z1, 2)
        ev.append(item)

    size = stats.get("size") or [0, 0, 0]
    first_area = float(stats.get("firstLayerArea") or 0)
    if size[2] > 25 and first_area > 0:
        ratio = size[2] / math.sqrt(first_area)
        if ratio >= 4:
            add("tall_thin", round(ratio, 2), f"height {size[2]:.0f} mm on a {math.sqrt(first_area):.0f} mm base")
    for code, kind in (("small_contact", "small_contact"),):
        items = _issues(checks, code)
        if items:
            add(kind, float(items[0].get("value") or first_area), items[0].get("message", ""))
    if max(size[0], size[1]) > 120 and first_area > 2000:
        add("large_footprint", round(max(size[0], size[1]), 1), f"{size[0]:.0f} x {size[1]:.0f} mm on the bed")

    islands = _issues(checks, "floating_island")
    if islands:
        add("floating_island", round(sum(float(i.get("value") or 0) for i in islands), 1), islands[0].get("message", ""), _z0(islands))
    overhangs = _issues(checks, "overhang")
    if overhangs:
        add("overhang", round(sum(float(i.get("value") or 0) for i in overhangs), 1), overhangs[0].get("message", ""), _z0(overhangs))
    bridges = _issues(checks, "long_bridge")
    if bridges:
        add("long_bridge", round(max(float(i.get("value") or 0) for i in bridges), 1), bridges[0].get("message", ""), _z0(bridges))
    short = _issues(checks, "short_layer_time")
    if short:
        add("short_layer_time", round(min(float(i.get("value") or 99) for i in short), 2), short[0].get("message", ""), _z0(short))
    thin = _issues(checks, "thin_wall") + _issues(checks, "too_thin") + _issues(checks, "small_text")
    if thin:
        add("thin_features", round(sum(float(i.get("value") or 0) for i in thin), 1), thin[0].get("message", ""), _z0(thin))

    load = brief.get("load")
    if load:
        desc = load if isinstance(load, str) else (load.get("description") or load.get("direction") or "yes") if isinstance(load, dict) else "yes"
        add("functional_load", desc, f"load: {desc}")
    if brief.get("fits") or brief.get("mating_faces") or brief.get("mating"):
        add("mating_faces", True, "parts must fit something else")
    screws = brief.get("screws")
    if screws:
        n = len(screws) if isinstance(screws, list) else int(screws) if str(screws).isdigit() else 1
        add("screw_boss", n, f"{n} screw hole(s) or boss(es)")
    if brief.get("vase_mode") and not _issues(checks, "vase_incompatible"):
        add("vase_eligible", True, "single outline per layer, no top")
    if brief.get("flat_top"):
        add("flat_top", True, "large flat top surface")
    parts = brief.get("parts") or stats.get("parts") or []
    colors = {p.get("color") for p in parts if p.get("role", "model") == "model" and p.get("color")}
    n_colors = max(len(colors), int(brief.get("colors") or 0))
    if n_colors > 1:
        add("multicolor", n_colors, f"{n_colors} colors")
    material = str(brief.get("material") or "").upper()
    if material:
        add(f"material:{material}", material, f"printed in {material}")
    return ev


# ------------------------------------------------------------------ values
def _spec_value(key: str, raw: Any) -> Any:
    """Normalized comparable value of a setting (number, bool or string)."""
    spec = SETTINGS[key]
    v = first(raw)
    if v is None:
        return None
    t = spec["type"]
    if t == "bool":
        return str(v).strip().lower() in ("1", "true")
    if t == "percent":  # "15%" means 15 here, not 0.15
        try:
            return float(str(v).strip().rstrip("%"))
        except ValueError:
            return float("nan")
    if t in ("int", "num"):
        return num(v, float("nan"))
    return str(v)


def _encode(key: str, value: Any, current: Any) -> Any:
    spec = SETTINGS[key]
    t = spec["type"]
    if t == "bool":
        s = "1" if value else "0"
    elif t == "percent":
        s = f"{int(round(float(value)))}%"
    elif t == "int":
        s = str(int(round(float(value))))
    elif t == "num":
        s = f"{float(value):.3f}".rstrip("0").rstrip(".")
    else:
        s = str(value)
    if isinstance(current, list):
        return [s] * max(1, len(current))
    if current is None and spec["file"] == "filament":
        return [s]
    return s


def _display(raw: Any) -> str | None:
    v = first(raw)
    return None if v is None else str(v)


def _bounds(key: str, limits: dict) -> tuple[float, float]:
    spec = SETTINGS[key]
    lo = float(spec.get("min", -math.inf))
    hi = float(spec.get("max", math.inf))
    if spec.get("limit") == "accel":
        hi = min(hi, float(limits.get("max_acceleration") or math.inf))
    if spec.get("limit") == "speed":
        hi = min(hi, float(limits.get("max_speed") or math.inf))
    return lo, hi


def validate(key: str, value: Any, *, base: dict, limits: dict) -> tuple[bool, Any, str]:
    """(ok, normalized value, why not). Used for rule output and model suggestions alike."""
    spec = SETTINGS.get(key)
    if spec is None:
        return False, None, f"{key} is not an allowed setting"
    t = spec["type"]
    if t == "bool":
        if isinstance(value, str):
            value = value.strip().lower() in ("1", "true", "yes", "on")
        return True, bool(value), ""
    if t == "enum":
        if str(value) not in spec["options"]:
            return False, None, f"{value!r} is not one of {spec['options']}"
        return True, str(value), ""
    try:
        v = float(str(value).rstrip("%"))
    except ValueError:
        return False, None, f"{value!r} is not a number"
    lo, hi = _bounds(key, limits)
    if not (lo <= v <= hi):
        return False, None, f"{key}={v:g} outside {lo:g}..{hi:g} for this printer"
    return True, v, ""


def _fmt(template: str, ev: dict, material: str) -> str:
    fields = defaultdict(lambda: "?", {**ev, "material": material})
    try:
        return template.format_map(fields)
    except (ValueError, TypeError, KeyError):
        return template.split("{")[0].strip() or template


# ------------------------------------------------------------------ rules
def rule_diff(base: dict, evidence: list[dict], limits: dict) -> list[dict]:
    by_kind = {e["kind"]: e for e in evidence}
    material = str(base.get("material") or next((e["value"] for e in evidence if e["kind"].startswith("material:")), "PLA")).upper()
    acc: dict[str, dict[str, Any]] = {}
    parts: list[dict] = []

    def fires(rule: dict) -> dict | None:
        ev = by_kind.get(rule["evidence"])
        if ev is None:
            return None
        if "min" in rule:
            try:
                if float(ev.get("value")) < rule["min"]:
                    return None
            except (TypeError, ValueError):
                return None
        if "materials" in rule and material not in rule["materials"]:
            return None
        if any(k in by_kind for k in rule.get("unless", [])):
            return None
        if not all(k in by_kind for k in rule.get("requires", [])):
            return None
        return ev

    for rule in RULES:
        ev = fires(rule)
        if ev is None:
            continue
        reason = _fmt(rule["reason"], ev, material)
        cited = [ev["id"]] + [k for k in rule.get("requires", []) if k in by_kind]
        for ch in rule["changes"]:
            slot = acc.setdefault(ch["key"], {"to": None, "at_least": None, "at_most": None, "reasons": [], "evidence": [], "rules": [], "required": False})
            if "to" in ch and slot["to"] is None:
                slot["to"] = ch["to"]
            if "at_least" in ch:
                slot["at_least"] = ch["at_least"] if slot["at_least"] is None else max(slot["at_least"], ch["at_least"])
            if "at_most" in ch:
                slot["at_most"] = ch["at_most"] if slot["at_most"] is None else min(slot["at_most"], ch["at_most"])
            if reason not in slot["reasons"]:
                slot["reasons"].append(reason)
            slot["evidence"] += [c for c in cited if c not in slot["evidence"]]
            slot["rules"].append(rule["id"])
            slot["required"] = slot["required"] or bool(rule.get("required"))

    for rule in PART_RULES:
        ev = fires(rule)
        if ev is None:
            continue
        reason = _fmt(rule["reason"], ev, material)
        for ch in rule["changes"]:
            if ch["key"] in PART_SETTINGS:
                parts.append({"key": ch["key"], "from": None, "to": str(ch["to"]), "value": ch["to"], "reason": reason, "evidence": [ev["id"]],
                              "file": "part", "part": rule["part"], "source": f"rules:{rule['id']}"})

    diff: list[dict] = []
    for key, slot in acc.items():
        spec = SETTINGS[key]
        current_raw = base.get(spec["file"], {}).get(key)
        current = _spec_value(key, current_raw)
        if slot["to"] is not None:
            target: Any = slot["to"]
        else:
            target = current if isinstance(current, (int, float)) and not (isinstance(current, float) and math.isnan(current)) else None
            if target is None:
                target = slot["at_least"] if slot["at_least"] is not None else slot["at_most"]
            if slot["at_least"] is not None and target < slot["at_least"]:
                target = slot["at_least"]
            # strength/safety wins over speed when bounds conflict
            if slot["at_most"] is not None and target > slot["at_most"] and not (slot["at_least"] is not None and slot["at_least"] > slot["at_most"]):
                target = slot["at_most"]
        if spec["type"] in ("int", "num", "percent"):
            lo, hi = _bounds(key, limits)
            target = min(max(float(target), lo), hi)
        ok, norm, why = validate(key, target, base=base, limits=limits)
        if not ok:
            log.info("rule change dropped: %s", why)
            continue
        if _same(key, norm, current):
            continue
        diff.append({
            "key": key, "from": _display(current_raw), "to": _display(_encode(key, norm, current_raw)), "value": _encode(key, norm, current_raw),
            "reason": " ".join(slot["reasons"]), "evidence": slot["evidence"], "file": spec["file"],
            "source": "rules:" + ",".join(dict.fromkeys(slot["rules"])), "required": slot["required"],
        })
    return diff + parts


def _same(key: str, new: Any, current: Any) -> bool:
    if current is None:
        return False
    t = SETTINGS[key]["type"]
    if t in ("int", "num", "percent"):
        try:
            return abs(float(new) - float(current)) < 1e-6
        except (TypeError, ValueError):
            return False
    return new == current


# ------------------------------------------------------------------ model refinement
REFINE_SCHEMA = {
    "type": "object",
    "properties": {
        "add": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string"}, "to": {"type": "string"}, "reason": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}}}, "required": ["key", "to", "reason", "evidence"]}},
        "drop": {"type": "array", "items": {"type": "object", "properties": {
            "key": {"type": "string"}, "reason": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}}}, "required": ["key", "reason", "evidence"]}},
    },
    "required": ["add", "drop"],
}

REFINE_SYSTEM = """You review a 3D-print slicer profile for one specific model.
The default is NO CHANGE: the stock profile is tuned by the printer maker.
You may (a) add a change to an allowed setting, or (b) drop a proposed non-required change.
Every add/drop MUST cite at least one evidence id from the list; never cite an id that is not listed.
Only change something when the evidence makes the stock value clearly wrong for this model.
Never exceed the machine limits. Prefer fewer changes. Empty lists are a good answer."""


async def refine(meter: CostMeter, *, base: dict, evidence: list[dict], goals: list[str], limits: dict, diff: list[dict], model: str) -> tuple[list[dict], list[dict]]:
    ev_ids = {e["id"] for e in evidence}
    table = []
    for key, spec in SETTINGS.items():
        cur = base.get(spec["file"], {}).get(key)
        lo, hi = _bounds(key, limits) if spec["type"] in ("int", "num", "percent") else (None, None)
        table.append({"key": key, "current": _display(cur), "type": spec["type"], "options": spec.get("options"),
                      "min": None if lo in (None, -math.inf) else lo, "max": None if hi in (None, math.inf) else hi})
    payload = {
        "material": base.get("material"),
        "goals": goals,
        "evidence": evidence,
        "proposed": [{k: d[k] for k in ("key", "from", "to", "reason", "evidence", "required") if k in d} for d in diff if not d.get("part")],
        "allowed_settings": table,
        "machine_limits": {k: v for k, v in limits.items() if k != "bed"},
    }
    out = await meta().json(
        meter, model=model, system=REFINE_SYSTEM, name="profile_review",
        content=[{"type": "input_text", "text": json.dumps(payload, ensure_ascii=False)}],
        schema=REFINE_SCHEMA, effort="low", max_output_tokens=8000,
    )
    rejected: list[dict] = []
    result = list(diff)
    for d in out.get("drop", []) or []:
        cites = [c for c in d.get("evidence", []) if c in ev_ids]
        target = next((x for x in result if x["key"] == d.get("key") and not x.get("part")), None)
        if target is None:
            continue
        if target.get("required") or not cites:
            rejected.append({"action": "drop", **d, "why": "required for printability" if target.get("required") else "no valid evidence cited"})
            continue
        result.remove(target)
    for a in out.get("add", []) or []:
        key = a.get("key", "")
        cites = [c for c in a.get("evidence", []) if c in ev_ids]
        if not cites:
            rejected.append({"action": "add", **a, "why": "no valid evidence cited"})
            continue
        if any(x["key"] == key and not x.get("part") for x in result):
            rejected.append({"action": "add", **a, "why": "already decided by rules"})
            continue
        ok, norm, why = validate(key, a.get("to"), base=base, limits=limits)
        if not ok:
            rejected.append({"action": "add", **a, "why": why})
            continue
        spec = SETTINGS[key]
        current_raw = base.get(spec["file"], {}).get(key)
        if _same(key, norm, _spec_value(key, current_raw)):
            continue
        encoded = _encode(key, norm, current_raw)
        result.append({"key": key, "from": _display(current_raw), "to": _display(encoded), "value": encoded, "reason": a.get("reason", ""),
                       "evidence": cites, "file": spec["file"], "source": "model", "required": False})
    return result, rejected


async def propose_with_report(meter: CostMeter | None, *, base: dict, evidence: list, goals: list, limits: dict,
                              model: str | None, use_llm: bool = True) -> dict[str, Any]:
    ev = list(evidence) + [{"id": f"goal:{g}", "kind": f"goal:{g}", "value": g, "detail": "your preference"} for g in goals]
    diff = rule_diff(base, ev, limits)
    rejected: list[dict] = []
    if use_llm and meter is not None:
        try:
            diff, rejected = await refine(meter, base=base, evidence=ev, goals=goals, limits=limits, diff=diff,
                                          model=model or settings().model_fast)
        except Exception as e:  # the rule diff alone is always a valid answer
            log.warning("profile refinement skipped: %s", e)
    return {"diff": diff, "rejected": rejected, "evidence": ev}


async def propose(meter: CostMeter | None, *, base: dict, evidence: list, goals: list, limits: dict, model: str | None,
                  use_llm: bool = True) -> list[dict]:
    return (await propose_with_report(meter, base=base, evidence=evidence, goals=goals, limits=limits, model=model, use_llm=use_llm))["diff"]


def apply_diff(process: dict, filament: dict, diff: list[dict]) -> tuple[dict, dict]:
    proc, fil = dict(process), dict(filament)
    for d in diff:
        if d.get("part"):
            continue
        (proc if d["file"] == "process" else fil)[d["key"]] = d["value"]
    return proc, fil
