"""Independent reviewer of a finished device (pack 'device'), in place of critic.review there.

The generic critic sees the case render and the measured print facts; it passed five broken devices with 8-9/10 (a sealed
night light, dice pips packed at random, a LiPo on 5 V, firmware that does not compile). A device is judged on what makes
it work: this reviewer reads the request, the designer's requirements, the graph (parts and nets), the routed board from
the top, the case render, the firmware, every check (design rules, firmware check, DRC and intent, case findings), what
the order contains, and the designer's own summary, and grades it against a device rubric. It never sees the case's JS.
The answer has critic.review's shape ({verdict, match_score, issues, model, reviewer, version}), so tools._finish, the
loop and narrate.review_of treat it alike; a major issue is a revise, and tools._finish blocks on it.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .. import device, storage
from ..config import settings
from ..db import get_db
from ..llm.client import BudgetExceeded, meta
from . import critic
from .runner import JobContext, model_text

log = logging.getLogger(__name__)

SCHEMA = critic.SCHEMA
MAX_OUTPUT = critic.MAX_OUTPUT
FIRMWARE_CHARS = 14_000  # the code the reviewer reads, all files together
BOM_LINES = 40
OPENING_CODES = ("light_window", "display_window", "sound_grille", "sensor_window", "cable_exit", "battery_space")

SYSTEM = """
You are an independent reviewer of an electronic device designed from a person's description: a carrier board with real
LCSC parts and a microcontroller module, a 3D-printed snap-fit case, firmware, and an order of finished devices. You see the
request, the designer's requirements, the device graph (parts and nets), the routed board from the top, renders of the case,
the firmware, the automatic checks, what the order contains and the designer's summary. You do NOT see the case's code.
Judge whether the device will do what the person asked when they unpack it:
1. Requirements: every function the person asked for (and the obvious ones a device of this kind needs) is implemented in
   hardware (the right parts, wired to the pins the firmware uses) AND in firmware (the code really does it: no stub, TODO,
   placeholder or a function that is never called). A missing or broken requested function is major.
2. Front panel: the board render shows user-facing parts where they make sense (dice pips in the dice pattern, an LED row in a
   row, buttons reachable, a display where the lid shows it); the case gives every light an opening, a display a window, a
   buzzer a grille, a sensor that must see or sense the air an opening, a cable an exit, a battery room. A sealed light, a
   hidden display or a sensor behind plastic is major.
3. The order: the order rows contain everything the device needs to work (display, sensor modules, probes, battery,
   driver transistors). A bare header "for your module" whose module is not in the order and not stated as the person's to
   buy is major. Every row is in the order and arrives fitted in the device.
4. Electrical sanity and safety: a LiPo on a 5 V pin (USB would push 5 V into it), a load of 20 mA or more (buzzer, relay,
   motor, LED chain) driven straight from a GPIO, a transistor wired wrong (a low-side NPN has E to GND), 5 V logic fed 3.3 V
   data, strapping pins pulled low at boot, missing pull-ups or decoupling, a firmware pin that is not the pin the graph
   wires. A pin a part needs that sits on no net (a flyback diode's K, a transistor's base, a sensor's output) is a defect,
   major, never minor. Anything that can damage a part, the battery or the person is major.
   An accessory with connect module_bat (a LiPo) has no nets on the carrier by design: its leads are soldered to the
   module's BAT+/BAT- pads and the module charges it from USB-C. That is correct, not an unconnected part.
5. Sensor readings: for every analog sensor, work out from the divider as wired which way the reading moves (a light sensor
   from V3V3 to the pin with a resistor to GND reads higher in light and lower in the dark; the other way round when it sits
   between the pin and GND) and check that the firmware's thresholds and comparisons go the same way. A sensor_divider
   finding states it ("the reading rises with more light"): then "dark" is a reading below the threshold. Inverted logic is
   major. A light sensor in the case with the device's own lights sees them: firmware that turns the light off when the
   sensor reads bright while that light is on switches itself off and flickers (major); dark must be judged with the lights
   off. The firmware may name a module pin by its board name or its alias (a XIAO's D6 is TX): map both through the module
   line before calling a pin wrong.
6. The summary: every claim is backed by the graph, the board and the code; a feature it claims that the code lacks, or a
   check it says passed that did not, is major. In particular:
   - battery life: estimate it from the firmware's duty cycle (an ESP32 awake with Wi-Fi draws about 90 mA, awake without it
     about 25 mA, a XIAO in deep sleep about 0.1 mA; add LEDs, displays and buzzers while they are on; hours = mAh / average
     mA). A claim more than twice your estimate is major; say your numbers.
   - what is included: what the summary says is or is not in the box, and what the person must buy, plug or solder, must match
     the order rows and the graph (a LiPo row with connect module_bat is included and soldered to the module's BAT pads, which
     are pads, not a connector). A wrong claim is major.
The automatic checks are measured facts: an error any of them still reports is major unless it is clearly harmless; weigh
their warnings too (a sensor_divider or floating_pin warning names a real defect when the design shows it).
The requirements are the person's: never propose dropping, weakening or rewording a requirement to match the code; the fix
is in the hardware or the firmware. A requirement that no longer says what the request asked is itself major.
Be concrete: name the node, net, pin, file and line. Major = the device would not work as asked, is unsafe, cannot be built
from the order, or the summary says something false. Minor = cosmetic, optional or a nicer way. verdict = pass only when
there is no major issue. match_score: 10 = does everything asked, well; 7 = works with small gaps; 4 = a main function is
missing or broken; 1 = not the device asked for.
Write text and fix_hint in English whatever the request's language: the designer model reads them; fix_hint is the change in
device terms (which node, net, pin, place, case option or line of code). text_user is the same issue for the person, in a
few plain words and in the request's language, without engineering terms.
""".strip()


def _j(v: Any, n: int = 4000) -> str:
    s = json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    return s if len(s) <= n else s[:n] + "…"


def _accessory(key: Any) -> dict[str, Any]:
    try:
        from .. import accessories

        return accessories.get(str(key or "")) or {}
    except Exception:  # noqa: BLE001 - the library is optional here
        return {}


def module_text(mpn: Any) -> str:
    """A module as the reviewer needs it: name, the GPIO behind each pin label, strapping and ADC pins, where a cell goes."""
    m = device.MODULES.get(str(mpn)) or {}
    if not m:
        return str(mpn)
    gpio = m.get("gpio") or {}
    bits = [m["name"]]
    if gpio and any(f"GP{v}" != k for k, v in gpio.items()):  # a Pico's GPn = n says nothing
        # the firmware may use either name: a XIAO's D6 is its TX, GPIO21 (a reviewer once read D6 as GPIO6)
        alias = {}
        for a, label in (m.get("aliases") or {}).items():
            alias.setdefault(label, []).append(a)
        bits.append("GPIO " + ", ".join(f"{'/'.join([*alias.get(k, []), k])}={v}" for k, v in gpio.items()))
    if m.get("strapping"):
        bits.append("strapping GPIO " + ", ".join(map(str, m["strapping"])))
    if m.get("adc"):
        bits.append("ADC on " + ", ".join(m["adc"]))
    if m.get("battery"):
        bits.append(f"battery: {m['battery']}")
    return "; ".join(bits)


def accessory_text(key: Any) -> str:
    """An accessory with what decides whether it is wired right: its connection, mount, supply and current."""
    a = _accessory(key)
    if not a:
        return f"accessory {key}"
    out = (f"accessory {key} = {a.get('name')} ({a.get('kind')}; connect {a.get('connect')}, mount {a.get('mount')}"
           + (f", supply {a['supply']}" if a.get("supply") else "") + (f", {a['current_ma']} mA" if a.get("current_ma") else "") + ")")
    if a.get("connect") == "module_bat":
        out += "; its leads are soldered to the module's BAT+/BAT- pads, so it has no carrier nets by design (correct)"
    return out


def graph_text(doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> str:
    """The graph compactly: one line per part (kind, what it is, label, edge, place, face) and one per net."""
    rows = []
    for n in doc.get("nodes") or []:
        k, p = n.get("kind"), parts.get(n.get("id"), {})
        if k == "module":
            what = module_text(n.get("module"))
        elif k == "chip":
            what = " ".join(str(x) for x in (n.get("lcsc"), p.get("mpn"), f"({p['category']})" if p.get("category") else None,
                                            f"kind {p['kind_hint']}" if p.get("kind_hint") else None,
                                            f"{p['current_ma']} mA" if p.get("current_ma") is not None else None) if x)
        elif k == "accessory":
            what = accessory_text(n.get("accessory"))
        elif k == "header":
            what = "pins " + " ".join(n.get("pins") or [])
        else:
            what = n.get("value") or n.get("color") or ""
        bits = [f"{n.get('id')} {k}", str(what), f"'{n['label']}'" if n.get("label") else "", f"edge {n['edge']}" if n.get("edge") else "",
                f"place ({n['place'].get('x')}, {n['place'].get('y')})" if isinstance(n.get("place"), dict) else "",
                f"face {n['face']}" if n.get("face") else "",
                f"placed by the person at ({n['pcb'].get('x')}, {n['pcb'].get('y')})" if isinstance(n.get("pcb"), dict) else ""]
        rows.append("- " + " ".join(b for b in bits if b))
    for i, net in enumerate(doc.get("nets") or []):
        rows.append(f"- net {net.get('name') or f'n{i}'}: {', '.join(net.get('pins') or [])}")
    if doc.get("layouts"):
        rows.append("- layouts: " + _j(doc["layouts"], 800))
    return "\n".join(rows)


def _firmware_text(fw: dict[str, Any] | None) -> str:
    files = (fw or {}).get("files") or {}
    if not files:
        return "No firmware was written."
    out, left = [f"Firmware ({(fw or {}).get('lang') or 'arduino'}):"], FIRMWARE_CHARS
    for name, text in files.items():
        body = str(text)
        cut = body[:left] + ("\n… (cut)" if len(body) > left else "")
        out.append(f"## {name}\n```\n{cut}\n```")
        left -= len(cut)
        if left <= 0:
            out.append("(more files left out)")
            break
    if (fw or {}).get("notes"):
        out.append("Notes: " + str(fw["notes"])[:600])
    return "\n".join(out)


def _board_text(board: dict[str, Any] | None) -> str:
    """Where the parts people see or touch sit on the built board (board.json, origin bottom-left, mm)."""
    if not board:
        return ""
    o = (board.get("pcb") or {}).get("outline") or {}
    rows = [f"Built board: {o.get('w')} x {o.get('h')} mm (origin bottom-left, x right, y up). Parts that face the person:"]
    for c in board.get("components") or []:
        if c.get("access") not in (None, "none"):
            where = f"on edge {c['edge']}" if c.get("access") == "port" else f"at ({c.get('x')}, {c.get('y')})"
            rows.append(f"- {c.get('id')} ({c.get('type')}) access {c.get('access')} {where}")
    for a in board.get("accessories") or []:
        rows.append(f"- accessory {a.get('id')} {a.get('key')} ({a.get('kind')}, mount {a.get('mount')}) at ({a.get('x')}, {a.get('y')})")
    return "\n".join(rows)


def _enclosure_text(enc: dict[str, Any] | None) -> str:
    if not isinstance(enc, dict) or "findings" not in enc:
        return "Case check: none for the current case."
    fs = [f for f in enc.get("findings") or [] if isinstance(f, dict)]
    keep = [f for f in fs if f.get("severity") in ("error", "warn") or f.get("code") in OPENING_CODES]
    return "Case check (findings): " + ("; ".join(f"[{f.get('severity')}] {f.get('code')} {f.get('part')}: {f.get('msg')}" for f in keep[:24])
                                        or "no errors or warnings")


async def _bom_text(project_id: str) -> str:
    from fastapi import HTTPException

    from .. import deviceapi

    try:
        q = await deviceapi.quote_for(project_id, 5)
    except HTTPException as e:
        return f"Order: no quote ({e.detail})."
    except Exception as e:  # noqa: BLE001 - a quote that fails says nothing about the design
        log.warning("device review: quote of %s failed: %s", project_id, e)
        return "Order: the quote could not be made."
    bom = q.get("bom") or []
    rows = [f"Order of {q.get('qty')} devices: ${q.get('total_usd')}, ready by {q.get('eta')}; groups "
            + ", ".join(f"{g.get('key')} ${g.get('usd')}" for g in q.get("groups") or []) + ". Order rows (every row is in the order and "
            "arrives fitted in the device; check the summary's what-is-included claims against them):"]
    for b in bom[:BOM_LINES]:
        out = b.get("in_order") is False
        what = f"ready-made {b.get('name') or b.get('mpn')} ({b.get('accessory')}), fitted by hand" if b.get("kind") == "accessory" else \
            f"{b.get('kind')} {b.get('mpn') or ''} {b.get('lcsc') or ''}"
        rows.append(f"- {','.join(b.get('refs') or [])}: {what} '{b.get('label') or ''}' x{b.get('qty_each')} ({b.get('assembly')}"
                    f"{', out of stock' if b.get('in_stock') is False else ''}{', NOT in the order' if out else ''})".replace("  ", " "))
    if len(bom) > BOM_LINES:
        rows.append(f"- and {len(bom) - BOM_LINES} more lines")
    listed = q.get("in_order")
    if isinstance(listed, list) and listed:
        # the quote's own list of what ships, when it gives one
        rows.append("In the order (the quote's list): " + "; ".join(
            str(x.get("name") or x.get("key") or x.get("refs") or x) if isinstance(x, dict) else str(x) for x in listed[:30]))
    acc = [b for b in bom if b.get("kind") == "accessory" and b.get("in_order") is not False]
    rows.append("Ready-made modules in the order: " + ("; ".join(f"{','.join(b.get('refs') or [])} {b.get('name') or b.get('mpn')}" for b in acc)
                                                       if acc else "none"))
    return "\n".join(rows)


async def _pcb_image(ctx: JobContext, version: int) -> str | None:
    """The routed board from the top as the designer saw it (renders/pcb_vN_top.png), drawn now when it is not there."""
    from .. import pcb_store
    from . import pcb_tools

    rel = f"{ctx.project_id}/renders/pcb_v{version}_top.png"
    if storage.abs_path(rel).exists():
        return rel
    path = pcb_store.artifact_path(ctx.project_id, version, "pcb_top.svg")
    try:
        made = await pcb_tools._top_view(ctx, version, path.read_text(encoding="utf-8") if path else None)
    except Exception as e:  # noqa: BLE001 - no picture is no reason to skip the review
        log.warning("device review: no board picture for %s v%s: %s", ctx.project_id, version, e)
        return None
    return made[0] if made else None


async def compose(ctx: JobContext, state: Any, summary: str = "") -> list[dict[str, Any]]:
    """What the reviewer reads: text first (request, requirements, graph, checks, order, summary, firmware), then the board
    and the case pictures."""
    from .. import pcb_store
    from . import device_tools, pcb_tools

    db = await get_db()
    msgs = list(reversed(await db.all("SELECT text, data FROM messages WHERE project_id = ? AND role = 'user' ORDER BY created_at DESC LIMIT 3",
                                      ctx.project_id)))
    language = (ctx.project.get("brief") or {}).get("language")
    own = [m["text"].strip() for m in msgs if model_text(m) != m["text"] and m["text"].strip() and m["text"].strip() not in model_text(m)]
    asked = await critic.answered(ctx.project_id, ctx.job_id)
    lines = ["Request: " + " / ".join(t for t in map(model_text, msgs) if t),
             *(["The person's own words: " + " / ".join(map(critic._quote, own))] if own else []),
             *(["Questions the designer asked the person, with the answers (settled):", *asked] if asked else []),
             *([f"Request language: {language} (write text_user in it)"] if language else [])]
    doc, version = await device_tools.current(ctx.project_id)
    norm: dict[str, Any] = {}
    if not doc:
        lines.append("There is no device document: nothing was designed.")
    else:
        norm, _ = device.normalize(doc)
        device_tools.keep_requirements(norm, doc)
        resolved = device.clone(norm)
        try:
            parts, _ = await device.resolve(resolved)
        except BudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001 - the catalogue being down leaves the graph without part details
            log.warning("device review: parts of %s: %s", ctx.project_id, e)
            parts = {}
        reqs = norm.get("requirements") or []
        lines.append(f"Device version {version}: {norm.get('title')}. {norm.get('summary') or ''}".strip())
        lines.append("Requirements (written by the designer): " + ("; ".join(
            f"{r['id']} {r['text']} [parts {', '.join(r.get('parts') or []) or '-'}{', firmware' if r.get('firmware') else ''}]" for r in reqs)
            or "none written"))
        lines.append("Device graph:\n" + graph_text(resolved, parts))
        rules = await device_tools.design_checks(resolved, parts)
        problems = device_tools.requirement_problems(norm)
        lines.append("Design rule check: " + ("; ".join(f"[{r.get('severity')}] {device_tools._line(r)}" for r in rules[:20]) or "no findings")
                     + ("" if not problems else " Requirement problems: " + "; ".join(problems)))
        fw = doc.get("firmware") or {}
        chk = await device_tools.check_now(state, norm, fw) if fw.get("files") else None
        lines.append("Firmware check: " + ("not run" if chk is None else f"{'passed' if chk.get('ok') else 'FAILED'} ({chk.get('tool')})"
                                           + "".join(f"; [error] {device_tools._fw_line(e)}" for e in (chk.get("errors") or [])[:10])
                                           + "".join(f"; [warning] {device_tools._fw_line(w)}" for w in (chk.get("warnings") or [])[:6])))
    row = await pcb_store.get(ctx.project_id)
    board = None
    pcb_png = None
    if row:
        v, checks = int(row["version"]), row.get("checks") or {}
        board = pcb_tools._board(ctx.project_id, v)
        errors = checks.get("errors") or []
        intent = checks.get("intent") or {}
        lines.append(f"Board PCB v{v}: {len(errors)} DRC errors" + "".join(f"; {e.get('type')} {e.get('ref') or ''}: {str(e.get('message'))[:160]}"
                                                                          for e in errors[:6])
                     + f"; intent {'met' if intent.get('ok', True) else 'NOT met: ' + _j(intent.get('issues'), 600)}; counts {_j(checks.get('counts') or {}, 300)}")
        if board:
            lines.append(_board_text(board))
        pcb_png = await _pcb_image(ctx, v)
    else:
        lines.append("No board was built.")
    enc = ((state.last_build or {}).get("checks") or {}).get("enclosure")
    lines.append(_enclosure_text(enc))
    if norm and board:
        missing = device_tools.opening_problems(norm, board, enc)
        if missing:
            lines.append("Openings missing: " + "; ".join(missing))
    case = (state.pcb or {}).get("enclosure") or {}
    if case:
        size = ((enc or {}).get("summary") or {}).get("case_mm") if isinstance(enc, dict) else None
        lines.append(f"Case: program version {case.get('version')} made from PCB v{case.get('pcb_version')}"
                     + (f", assembled {' x '.join(f'{float(x):g}' for x in size)} mm" if isinstance(size, list) else ""))
    lines.append(await _bom_text(ctx.project_id) if row else "Order: nothing to order yet.")
    lines.append("The designer's summary (check every claim): " + (critic._quote(summary) if str(summary or "").strip() else "(none)"))
    if doc:
        lines.append(_firmware_text(doc.get("firmware")))
    earlier = state.critic or {}
    # the case's version often stays while the graph or the firmware changes: every earlier review counts here
    if earlier.get("issues"):
        found = "; ".join(f"{n}. [{i.get('severity')}] {i.get('text', '')}" for n, i in enumerate(earlier["issues"][:6], 1))
        lines.append(f"An earlier review found: {found}. Say in your issues which of them are still not fixed.")
    content: list[dict[str, Any]] = [{"type": "input_text", "text": "\n".join(lines)}]
    if pcb_png:
        content.append({"type": "input_text", "text": "The routed board from the top (both copper layers, pads, silkscreen):"})
        content.append({"type": "input_image", "image_url": storage.data_url(pcb_png, 1280)})
    if state.last_render:
        parts_legend = critic.legend(state)
        content.append({"type": "input_text", "text": "Renders of the case (6 views):" + (f"\n{parts_legend}" if parts_legend else "")})
        content.append({"type": "input_image", "image_url": storage.data_url(state.last_render, None)})
    return content


async def review(ctx: JobContext, state: Any, *, bar: float | None = None, summary: str = "") -> dict[str, Any]:
    """The verdict on the device that would ship, tagged like critic.review: the configured reviewer ('primary'), the fast model
    standing in ('fallback') or nobody ('unavailable', no verdict). A major issue always makes it a revise."""
    try:
        content = await compose(ctx, state, summary)
    except BudgetExceeded:
        raise
    except Exception:  # noqa: BLE001 - a broken composition still gets the request and the summary reviewed
        log.exception("device review: composing the review of %s failed", ctx.project_id)
        content = [{"type": "input_text", "text": "The device's details could not be gathered. The designer's summary: " + critic._quote(summary)}]
    model = meta().model_for("critic", settings().model_critic or ctx.models.fast)
    try:
        verdict = critic.usable(await meta().json(ctx.meter, model=model, system=SYSTEM, content=content, schema=SCHEMA, name="device_review",
                                                  effort="low", max_output_tokens=MAX_OUTPUT, fallback=False))
        reviewer = "primary"
    except BudgetExceeded:
        raise
    except Exception as e:  # noqa: BLE001 - a reviewer that is down is replaced, not fatal
        log.warning("device reviewer %s failed: %s: %s", model, type(e).__name__, e)
        verdict = {}
    if "verdict" not in verdict:
        model, reviewer = ctx.models.fast, "fallback"
        try:
            verdict = critic.usable(await meta().json(ctx.meter, model=model, system=SYSTEM, content=content, schema=SCHEMA, name="device_review",
                                                      effort="low", max_output_tokens=MAX_OUTPUT))
        except BudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("fallback device reviewer %s failed: %s: %s", model, type(e).__name__, e)
            verdict = {}
    if "verdict" not in verdict:
        return {"reviewer": "unavailable"}
    if any(i["severity"] == "major" for i in verdict["issues"]):
        verdict["verdict"] = "revise"
    return {**verdict, "model": model, "reviewer": reviewer, "version": state.version}
