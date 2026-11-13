"""How well a model writes circuits for the PCB pack: six board briefs, each written once from the pack's rules and
reference board, built offline in the sandboxed PCB worker; failures go back with the build's hints for up to
--repairs rounds. Measures the share with 0 DRC errors at the first try and after repairs, whether the intent was
stated and met, tokens and seconds per call.

Paid calls are capped (--calls, at most 8): nothing is sent without it. Keys come from the server settings (.env),
never printed. Muse Spark Open answers through its own Chat Completions endpoint, once, with the same 24k budget.

    python scripts/eval_pcb.py --list
    python scripts/eval_pcb.py --calls 8 --repairs 3 --open 1 --out ../../eval_pcb
    python scripts/eval_pcb.py --calls 2 --briefs xiao,keypad
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamodelize3d import pcb  # noqa: E402
from iamodelize3d.agent.loop import PACK_LLM  # noqa: E402
from iamodelize3d.agent.pcb_prompt import EXAMPLE, PACK_TEXT  # noqa: E402
from iamodelize3d.config import settings  # noqa: E402
from iamodelize3d.llm import pricing  # noqa: E402
from iamodelize3d.llm.client import CostMeter, _usage, meta  # noqa: E402
from iamodelize3d.pcb import PcbError  # noqa: E402

MAX_CALLS = 8
BRIEFS = {
    "xiao": "Carrier board for a Seeed XIAO ESP32-C3: USB-C power input, a push button, a status LED on a GPIO, "
            "a 4-pin I2C header on the right edge.",
    "pico": "Carrier board for a Raspberry Pi Pico on two 20-pin headers (footprint dip40_w17.78mm): USB-C 5 V input on the "
            "bottom edge into VSYS through a Schottky diode, a reset button from RUN to GND, a 4-pin I2C header on the left edge.",
    "keypad": "A 4-key macro keypad: a Seeed XIAO ESP32-C3 with its own USB-C at the top edge, four 6x6 push buttons in a row, "
              "each from its own GPIO (D0, D1, D2, D3) to GND, four M3 mounting holes.",
    "sensor": "A small I2C sensor breakout: an SOIC-8 sensor chip (pins VDD, GND, SDA, SCL, ADDR, ALERT, NC1, NC2) with a 100nF "
              "decoupling capacitor, ADDR to GND, 4.7k pull-ups on SDA and SCL, a 4-pin header (VCC, GND, SDA, SCL) on the left edge.",
    "led": "An LED strip driver: USB-C 5 V input on the bottom edge, an SOT-23 N-MOSFET (pins G, S, D) switching a 2-pin JST output "
           "on the right edge, its gate from a 3-pin header (5V, GND, PWM) on the left edge through 100 ohm with a 10k pull-down, "
           "a green power LED with its resistor.",
    "splitter": "A USB-C power splitter: one USB-C input on the left edge, two 2-pin JST outputs on the right edge, each through "
                "its own Schottky diode, a green power LED with its resistor, four M3 mounting holes.",
}
ANSWER = "Answer with the whole TSX file in one ```tsx block and nothing else."


def instructions() -> str:
    return PACK_TEXT + "\n\n# Reference board (built: 0 DRC errors, 23 traces, intent met)\n```tsx\n" + EXAMPLE + "```\n\n" + ANSWER


def code_of(text: str) -> str:
    m = re.findall(r"```(?:tsx|jsx|typescript|ts)?\s*\n(.*?)```", text or "", re.S)
    return max(m, key=len) if m else (text or "")


def problems(build: dict[str, Any]) -> str:
    """What the agent's tool would hand back: errors with hints, then intent issues."""
    lines = [f"- {e['type']}{' (' + e['ref'] + ')' if e.get('ref') else ''}: {e['message'][:300]}" + (f"\n  hint: {e['hint']}" if e.get("hint") else "")
             for e in build.get("errors") or []]
    intent = build.get("intent") or {}
    if not intent.get("checked"):
        lines.append("- no intent stated: add meta.intent (edge for every connector, gpio for LEDs and buttons)")
    lines += [f"- {i['code']} ({i.get('ref')}): {i['msg']}" + (f"\n  hint: {i['hint']}" if i.get("hint") else "") for i in intent.get("issues") or []]
    return "\n".join(lines)


async def ask(model: str, brief: str, previous: str | None, issues: str | None, *, use_open: bool) -> dict[str, Any]:
    meter = CostMeter(budget_usd=5)
    user = f"Design this board:\n{brief}"
    if previous is not None:
        user += f"\n\nYour previous file:\n```tsx\n{previous}\n```\nThe build reported these problems; fix them and return the whole corrected file:\n{issues}"
    t0 = time.monotonic()
    budget = PACK_LLM["pcb"]["max_output_tokens"]
    client = meta()
    if use_open:
        raw = await client._retry(model, lambda: client.open.chat.completions.with_raw_response.create(  # type: ignore[union-attr]
            model=model, max_tokens=budget, messages=[{"role": "system", "content": instructions()}, {"role": "user", "content": user}]), attempts=2)
        tin, tout, cached = _usage(raw)
        meter.add(model, pricing.token_cost(model, tin, cached, tout), tin, tout, cached, purpose="eval_pcb")
        text = raw.choices[0].message.content or ""
    else:
        resp = await client.respond(meter, model=model, instructions=instructions(), input=[{"role": "user", "content": user}],
                                    effort=PACK_LLM["pcb"]["effort"], max_output_tokens=budget, purpose="eval_pcb")
        text = resp.output_text or ""
    return {"text": text, "seconds": round(time.monotonic() - t0, 1), "tokens_in": meter.tokens_in, "tokens_out": meter.tokens_out,
            "usd": round(meter.usd, 5)}


async def build(source: str) -> dict[str, Any]:
    try:
        r = await pcb.pool().build(source)
    except PcbError as e:
        return {"ok": False, "stage": e.stage, "errors": [{"type": e.stage, "message": e.message, "hint": e.hint}], "intent": {}}
    return r


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--list", action="store_true", help="print the briefs and exit (no calls)")
    ap.add_argument("--calls", type=int, default=0, help=f"paid calls allowed in this run (at most {MAX_CALLS})")
    ap.add_argument("--repairs", type=int, default=3, help="repair rounds per brief while calls remain")
    ap.add_argument("--open", type=int, default=0, help="first tries on Muse Spark Open (the first briefs)")
    ap.add_argument("--briefs", default=",".join(BRIEFS), help="comma-separated brief names")
    ap.add_argument("--model", default=None, help="designer model (default: settings model_designer)")
    ap.add_argument("--out", default=None, help="folder for the written files and results.json")
    a = ap.parse_args()
    if a.list:
        for k, v in BRIEFS.items():
            print(f"{k}: {v}")
        return 0
    calls = min(max(0, a.calls), MAX_CALLS)
    if not calls:
        print("no paid calls allowed: pass --calls N (at most 8)")
        return 1
    s = settings()
    model = a.model or s.model_designer
    out = Path(a.out) if a.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    names = [n.strip() for n in a.briefs.split(",") if n.strip() in BRIEFS]
    runs: list[dict[str, Any]] = []
    left = calls

    async def attempt(name: str, who: str, use_open: bool, previous: str | None = None, issues: str | None = None, round_: int = 0) -> dict[str, Any]:
        nonlocal left
        left -= 1
        try:
            answer = await ask(who, BRIEFS[name], previous, issues, use_open=use_open)
        except Exception as e:  # noqa: BLE001 - a failed call is a result too
            return {"brief": name, "model": who, "round": round_, "error": f"{type(e).__name__}: {str(e)[:300]}"}
        source = code_of(answer["text"])
        r = await build(source) if source.strip() else {"ok": False, "errors": [{"type": "empty", "message": "empty answer"}], "intent": {}}
        intent = r.get("intent") or {}
        rec = {"brief": name, "model": who, "round": round_, **{k: answer[k] for k in ("seconds", "tokens_in", "tokens_out", "usd")},
               "chars": len(source), "ok": bool(r.get("ok")), "errors": [e["type"] for e in r.get("errors") or []],
               "intent_checked": intent.get("checked", 0), "intent_ok": bool(intent.get("ok")) and bool(intent.get("checked")),
               "counts": r.get("counts"), "source": source, "problems": problems(r)}
        if out:
            (out / f"{name}_{'open' if use_open else 'spark'}_{round_}.tsx").write_text(source, encoding="utf-8")
        print(json.dumps({k: v for k, v in rec.items() if k not in ("source", "problems")}, ensure_ascii=False), flush=True)
        return rec

    try:
        # first tries for every brief, then repairs in brief order while calls remain, then the open model
        opens = min(max(0, a.open), left)
        firsts = []
        for name in names:
            if left - opens <= 0:
                break
            firsts.append(await attempt(name, model, False))
        runs += firsts
        for rec in firsts:
            last = rec
            while last.get("source") is not None and not (last["ok"] and last["intent_ok"]) and last["round"] < a.repairs and left - opens > 0:
                last = await attempt(rec["brief"], model, False, last["source"], last["problems"], last["round"] + 1)
                runs.append(last)
        for name in names[:opens]:
            if s.open_model and meta().open is not None:
                runs.append(await attempt(name, s.open_model, True))
    finally:
        await pcb.close()

    def share(rows: list[dict[str, Any]]) -> str:
        return f"{sum(1 for r in rows if r.get('ok') and r.get('intent_ok'))}/{len(rows)}"

    spark_first = [r for r in runs if r["model"] == model and r["round"] == 0]
    final = {}
    for r in runs:
        if r["model"] == model:
            final[r["brief"]] = r
    summary = {"calls": calls - left, "model": model, "clean_first_try": share(spark_first), "clean_after_repairs": share(list(final.values())),
               "open": [{k: r.get(k) for k in ("brief", "ok", "intent_ok", "errors", "seconds", "tokens_out", "error")} for r in runs if r["model"] != model],
               "seconds_median": sorted(r["seconds"] for r in runs if "seconds" in r)[len(runs) // 2] if runs else None,
               "usd": round(sum(r.get("usd", 0) for r in runs), 4)}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    if out:
        (out / "results.json").write_text(json.dumps({"summary": summary, "runs": runs}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
