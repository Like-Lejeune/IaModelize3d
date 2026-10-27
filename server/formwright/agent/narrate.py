"""Human-readable narration of agent steps for the timeline and Telegram.

Raw tool JSON stays available as `summary` for the details expander; these titles are
what people read: "Measured the bracket: 70.5 × 45.4 mm ±0.6".
"""
from __future__ import annotations

from typing import Any

KIND = {
    "write_program": "build", "edit_program": "edit", "set_params": "params", "inspect_model": "inspect",
    "render_view": "render", "look_at": "look", "scene": "scene", "measure_photo": "measure", "read_caliper": "caliper",
    "lookup_standard": "standard", "search_dimensions": "search", "recall": "memory", "remember_interface": "memory",
    "ask_user": "ask", "fit_to_photo": "fit", "propose_probe": "probe", "concept_images": "concepts",
    "load_terrain": "terrain", "save_skill": "skill", "compare_print": "compare", "finish": "finish",
}

# which stage of the job a tool belongs to
STAGE = {
    "build": "design", "edit": "design", "params": "design", "skill": "design", "terrain": "measure", "concepts": "design",
    "measure": "measure", "caliper": "measure", "scene": "measure", "look": "measure", "standard": "measure", "search": "measure",
    "memory": "understand", "ask": "understand", "inspect": "check", "render": "check", "fit": "check", "probe": "check",
    "compare": "check", "finish": "review",
}

STAGE_LABEL = {
    "understand": "Understanding the request",
    "measure": "Measuring and looking things up",
    "design": "Designing",
    "check": "Checking against reality",
    "review": "Independent review",
    "done": "Ready",
}


def _mm(v: Any) -> str:
    try:
        return f"{float(v):.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(v)


def _size(size: list | None) -> str:
    return " × ".join(_mm(v) for v in (size or [])) + " mm" if size else ""


def call_title(name: str, args: dict[str, Any]) -> str:
    a = args or {}
    return {
        "write_program": f"Writing the model: {a.get('summary') or 'first version'}",
        "edit_program": f"Changing: {a.get('summary') or 'details'}",
        "set_params": f"Adjusting {', '.join((a.get('values') or {}).keys()) or 'parameters'}",
        "inspect_model": "Measuring my own model",
        "render_view": "Comparing with the photo" if a.get("view") == "photo" else "Rendering views",
        "look_at": "Taking a closer look at the photo",
        "scene": "Reading measurements from the photos",
        "measure_photo": f"Measuring “{a.get('target', 'the object')}” on the photo",
        "read_caliper": "Reading the caliper",
        "lookup_standard": f"Checking standards: {a.get('query', '')}",
        "search_dimensions": f"Searching official dimensions: {a.get('query', '')}",
        "recall": "Checking what I remember about your setup",
        "remember_interface": f"Remembering “{a.get('name', '')}” for next time",
        "ask_user": "Asking you a question",
        "fit_to_photo": f"Fitting {', '.join(a.get('params') or []) or 'the outline'} to the photo silhouette",
        "propose_probe": f"Preparing a test print for {a.get('dimension', 'a critical size')}",
        "concept_images": "Sketching concepts",
        "load_terrain": f"Loading real elevation data{(': ' + a['place']) if a.get('place') else ''}",
        "save_skill": f"Saving a reusable module “{a.get('name', '')}”",
        "compare_print": "Comparing your print with the target",
        "finish": "Final check before handing over",
    }.get(name, name.replace("_", " "))


def result_title(name: str, args: dict[str, Any], r: dict[str, Any]) -> str:
    if r.get("ok") is False:
        err = str(r.get("error") or r.get("reason") or "failed")
        return f"Problem: {err[:140]}"
    if name in ("write_program", "edit_program", "set_params", "fit_to_photo"):
        issues = r.get("issues") or []
        errors = sum(1 for i in issues if i.get("severity") == "error")
        warns = sum(1 for i in issues if i.get("severity") == "warn")
        state = "printable" if r.get("printable", True) and not errors else f"{errors} problem{'s' if errors != 1 else ''} to fix"
        extra = f", {warns} note{'s' if warns != 1 else ''}" if warns else ""
        fit = r.get("fit")
        fitted = f" — silhouette match {fit['iou_before']:.0%} → {fit['iou_after']:.0%}" if fit else ""
        return f"Version {r.get('version')} — {_size(r.get('size_mm'))}, {state}{extra}{fitted}"
    if name == "measure_photo":
        unc = r.get("uncertainty_mm")
        holes = r.get("holes_mm") or []
        hole_txt = f", {len(holes)} hole{'s' if len(holes) != 1 else ''} Ø{_mm(holes[0]['d'])}" if holes else ""
        if r.get("calibrated") and r.get("size_mm"):
            return f"Measured {r.get('name', 'object')}: {_size(r['size_mm'])}{f' ±{_mm(unc)}' if unc else ''}{hole_txt}"
        return f"Found {r.get('name', 'the object')} (no reference in the photo, sizes in pixels only)"
    if name == "read_caliper":
        return f"Caliper reads {_mm(r.get('value_mm'))} mm" if r.get("value_mm") else "Couldn't read the caliper"
    if name == "search_dimensions":
        facts = r.get("facts") or []
        return f"Found {len(facts)} dimension{'s' if len(facts) != 1 else ''}{' (from memory)' if r.get('from_cache') else ''}"
    if name == "lookup_standard":
        n = len(r.get("results") or [])
        return f"{n} standard value{'s' if n != 1 else ''} found" if n else "Not in the standards tables"
    if name == "inspect_model":
        return "Measured the model"
    if name == "scene":
        n = len(r.get("measurements") or [])
        return f"{n} measurement{'s' if n != 1 else ''} available"
    if name == "ask_user":
        return f"You answered: {r.get('answer')}" if r.get("answer") else "No answer — continuing with a stated assumption"
    if name == "propose_probe":
        v = r.get("variants") or []
        return f"Test print ready: {len(v)} variants, ~{_mm(r.get('est_minutes'))} min"
    if name == "concept_images":
        return f"{r.get('count', 0)} concepts ready"
    if name == "load_terrain":
        return f"Elevation loaded: {_mm(r.get('relief_m'))} m relief over {_mm(r.get('size_km'))} km"
    if name == "compare_print":
        return f"Print deviates {_mm(r.get('mean_mm'))} mm on average (max {_mm(r.get('max_mm'))})"
    if name == "finish":
        if r.get("accepted"):
            return "Approved"
        return f"Not yet: {r.get('reason', 'needs fixes')}"
    if name == "render_view":
        return "Overlay ready" if args.get("view") == "photo" else "Views rendered"
    if name == "recall":
        return "Memory checked"
    if name == "remember_interface":
        return "Saved to your setup"
    return "Done"
