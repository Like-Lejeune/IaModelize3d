"""The device's concept (doc.concept, fw.device/1): how it is used and what it looks like, decided before the parts. Devices
came out as one generic box (the module at the top edge, the display under it, the buttons under that) because nobody chose
a form, a stance or a mounting; now the designer imagines the uses, brainstorms at least three genuinely different options
and picks one, and the rest of the design follows it:

  {uses: ['2-4 short scenarios'],
   options: [{name, look, form: soft|round|box, stance: desk|tilt|upright|wall|hand|auto,
              mounting: none|ears|strap|lanyard|stake|magnets|contacts, board: {shape: rect|rounded|round, w, h},
              module_edge: +y|-y|+x|-x, panel: 'what is where on the lid / front'}, ...],
   chosen: 'the name of one option', why: 'why it fits the uses best'}

The case values are make_enclosure's own (agent/elec_tools.CHOICES), the board shapes the compiler's (doc.board.shape).
clean() is what device.normalize keeps (lenient: a wrong value is dropped, never guessed); problems() is what write_device
reports as design errors; drift() says where the built board or case left the chosen option (warnings: either the concept or
the design changes). Nothing here imports the rest of the server.
"""
from __future__ import annotations

import math
from typing import Any

FORMS = ("soft", "round", "box")
STANCES = ("desk", "tilt", "upright", "wall", "hand", "auto")
MOUNTINGS = ("none", "ears", "strap", "lanyard", "stake", "magnets", "contacts")
SHAPES = ("rect", "rounded", "round")
EDGES = ("+y", "-y", "+x", "-x")
ENUMS = {"form": FORMS, "stance": STANCES, "mounting": MOUNTINGS, "module_edge": EDGES}
MIN_USES, MAX_USES = 2, 6
MIN_OPTIONS, MAX_OPTIONS = 3, 6
BOARD_MM = (10.0, 200.0)
# a built board this much off the chosen size (either side, mm or a share of it, whichever is larger) is another device
SIZE_SLACK_MM, SIZE_SLACK = 5.0, 0.2

HOW = ("doc.concept = {uses: ['2-4 short scenarios: where it lives, who uses it, how it is seen / heard / touched, how it is "
       "powered'], options: [at least 3 genuinely different {name, look, form: soft|round|box, stance: desk|tilt|upright|wall|hand|auto, "
       "mounting: none|ears|strap|lanyard|stake|magnets|contacts, board: {shape: rect|rounded|round, w, h}, module_edge: +y|-y|+x|-x, "
       "panel: 'what is where on the lid'}], chosen: 'one option's name', why: 'why it fits the uses best'}")


def _text(v: Any, n: int) -> str:
    return " ".join(str(v).split())[:n] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def _mm(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 1) if math.isfinite(f) and BOARD_MM[0] <= f <= BOARD_MM[1] else None


def _option(raw: Any, i: int) -> tuple[dict[str, Any] | None, list[str]]:
    """One option cleaned (only valid values kept) and what is wrong with it."""
    if not isinstance(raw, dict):
        return None, [f"option {i + 1} is not an object {{name, look, form, stance, mounting, board, module_edge, panel}}"]
    name = _text(raw.get("name"), 60)
    who = f"option {name!r}" if name else f"option {i + 1}"
    out: dict[str, Any] = {"name": name or f"Option {i + 1}"}
    bad: list[str] = [] if name else [f"{who} has no name"]
    for k in ("look", "panel"):
        t = _text(raw.get(k), 240)
        if t:
            out[k] = t
        else:
            bad.append(f"{who} has no {k} ({'one line: the overall look' if k == 'look' else 'what is where on the lid / front'})")
    for k, allowed in ENUMS.items():
        v = str(raw.get(k) or "").strip().lower()
        if v in allowed:
            out[k] = v
        else:
            bad.append(f"{who}: {k} {v or 'missing'!r} is not one of {', '.join(allowed)}")
    b = raw.get("board") if isinstance(raw.get("board"), dict) else {}
    shape = str(b.get("shape") or "").strip().lower()
    w, h = _mm(b.get("w")), _mm(b.get("h"))
    if shape == "round" and w and not h:
        h = w  # a round board's size is its diameter
    board: dict[str, Any] = {}
    if shape in SHAPES:
        board["shape"] = shape
    else:
        bad.append(f"{who}: board.shape {shape or 'missing'!r} is not one of {', '.join(SHAPES)}")
    if w and h:
        board.update({"w": w, "h": h})
    else:
        bad.append(f"{who}: board.w and board.h must be the board's size in mm ({BOARD_MM[0]:g}-{BOARD_MM[1]:g})")
    if board:
        out["board"] = board
    return out, bad


def _check(raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
    none = f"no concept: before the parts, write {HOW}; then design to the chosen one"
    if not isinstance(raw, dict):
        return None, [none if raw is None else f"no concept: it is not an object; before the parts, write {HOW}"]
    bad: list[str] = []
    uses = [t for t in (_text(u, 200) for u in (raw.get("uses") if isinstance(raw.get("uses"), list) else [])) if t][:MAX_USES]
    if len(uses) < MIN_USES:
        bad.append(f"concept.uses has {len(uses)} scenario(s): imagine {MIN_USES}-4 (where it lives, who uses it, how it is seen, heard "
                   "or touched, how it is powered and charged)")
    options: list[dict[str, Any]] = []
    raws = raw.get("options") if isinstance(raw.get("options"), list) else []
    for i, o in enumerate(raws[:MAX_OPTIONS]):
        opt, why = _option(o, i)
        bad += why
        if opt is None:
            continue
        if any(x["name"].lower() == opt["name"].lower() for x in options):
            bad.append(f"two options are called {opt['name']!r}: name each one")
            continue
        options.append(opt)
    if len(options) < MIN_OPTIONS:
        bad.append(f"concept.options has {len(options)}: brainstorm at least {MIN_OPTIONS} genuinely different ones (form, stance, "
                   "mounting, board shape, panel)")
    else:
        # the same form, stance, mounting, board shape and module edge is the same device in other words
        looks = {(o.get("form"), o.get("stance"), o.get("mounting"), (o.get("board") or {}).get("shape"), o.get("module_edge")) for o in options}
        if len(looks) < MIN_OPTIONS:
            bad.append("the options are not genuinely different: at least three must differ in form, stance, mounting, board shape or "
                       "module edge, not only in words")
    out: dict[str, Any] = {"uses": uses, "options": options}
    want = _text(raw.get("chosen"), 60)
    pick = next((o for o in options if o["name"].lower() == want.lower()), None) if want else None
    if pick:
        out["chosen"] = pick["name"]
    else:
        bad.append(f"concept.chosen {want or 'missing'!r} names none of the options ({', '.join(o['name'] for o in options) or 'none yet'}): "
                   "pick the one that fits the uses best and is compact")
    why = _text(raw.get("why"), 300)
    if why:
        out["why"] = why
    else:
        bad.append("concept.why is missing: one or two sentences, why the chosen option fits the uses best")
    if not uses and not options:
        return None, [none]
    return out, bad


def clean(raw: Any) -> dict[str, Any] | None:
    """The concept as device.normalize keeps it: valid values only, None when nothing of it is usable."""
    return _check(raw)[0]


def problems(raw: Any) -> list[str]:
    """What write_device reports as design errors: no concept, or one that is not complete (fewer than three options, no
    chosen one, unknown values)."""
    return _check(raw)[1]


def chosen(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """The chosen option of a document's concept (as stored), or None."""
    c = (doc or {}).get("concept")
    if not isinstance(c, dict) or not c.get("chosen"):
        return None
    return next((o for o in c.get("options") or [] if isinstance(o, dict) and o.get("name") == c["chosen"]), None)


def line(doc: dict[str, Any] | None) -> str | None:
    """The chosen option in one line, for the designer to keep in view."""
    o = chosen(doc)
    if not o:
        return None
    b = o.get("board") or {}
    size = f" {b['w']:g} x {b['h']:g} mm" if b.get("w") and b.get("h") else ""
    return (f"{o['name']}: {o.get('look') or ''} (form {o.get('form')}, stance {o.get('stance')}, mounting {o.get('mounting')}; "
            f"{b.get('shape') or '?'} board{size}, module on {o.get('module_edge')}; panel: {o.get('panel') or '?'}). Design to it: "
            "board.shape and w/h, the module's edge, place and layouts as the panel says, make_enclosure with its form, stance and mounting")


def _say(o: dict[str, Any], what: str, fix: str) -> str:
    return f"concept {o['name']!r}: {what}: {fix}, or change the concept (write_device with a new concept.chosen) so the two agree"


def board_drift(doc: dict[str, Any], board: dict[str, Any] | None) -> list[str]:
    """Where the built board (board.json) left the chosen option: its shape, its size, the module's edge."""
    o = chosen(doc)
    if not o:
        return []
    out: list[str] = []
    want = o.get("board") or {}
    outline = ((board or {}).get("pcb") or {}).get("outline") or {}
    db = (doc or {}).get("board") or {}
    shape = next((s for s in (outline.get("shape"), db.get("shape"), outline.get("kind")) if s in SHAPES), "rect")
    if want.get("shape") and shape != want["shape"]:
        out.append(_say(o, f"the board is {shape}, the concept's is {want['shape']}", f"set board.shape '{want['shape']}'"))
    try:
        w, h = float(outline.get("w") or db.get("w") or 0), float(outline.get("h") or db.get("h") or 0)
    except (TypeError, ValueError):
        w = h = 0.0
    if w and h and want.get("w") and want.get("h"):
        far = any(abs(got - aim) > max(SIZE_SLACK_MM, SIZE_SLACK * aim) for got, aim in ((w, want["w"]), (h, want["h"])))
        if far:
            out.append(_say(o, f"the board is {w:g} x {h:g} mm, the concept's {want['w']:g} x {want['h']:g} mm",
                            "fit the parts to that size (board.w/h, place, a smaller package) or rotate the layout"))
    edge = o.get("module_edge")
    mod = next((n for n in (doc or {}).get("nodes") or [] if isinstance(n, dict) and n.get("kind") == "module"), None)
    if mod and edge:
        built = next((c.get("edge") for c in (board or {}).get("components") or []
                      if isinstance(c, dict) and str(c.get("id")) == str(mod.get("id")) and c.get("edge") in EDGES), None)
        got = built or mod.get("edge") or "+y"
        if got != edge:
            out.append(_say(o, f"the module {mod.get('id')} sits on {got}, the concept puts it on {edge}", f"set its edge '{edge}'"))
    return out


def case_drift(doc: dict[str, Any], options: dict[str, Any] | None) -> list[str]:
    """Where the case's options (elec_tools.case_options of the case program) left the chosen option's form, stance and
    mounting; a stance of 'auto' on either side follows the mounting and is not compared."""
    o = chosen(doc)
    if not o or not isinstance(options, dict):
        return []
    diff = {k: (options.get(k), o.get(k)) for k in ("form", "stance", "mounting")
            if options.get(k) and o.get(k) and options.get(k) != o.get(k) and not (k == "stance" and "auto" in (options.get(k), o.get(k)))}
    if not diff:
        return []
    got = ", ".join(f"{k} {a}" for k, (a, _) in diff.items())
    aim = ", ".join(f"{k} {b}" for k, (_, b) in diff.items())
    fix = "make_enclosure with options {" + ", ".join(f"{k}: '{b}'" for k, (_, b) in diff.items()) + "}"
    return [_say(o, f"the case has {got}, the concept {aim}", fix)]
