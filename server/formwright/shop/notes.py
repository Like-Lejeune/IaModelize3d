"""The order journal's notes as codes with parameters, so the web says them in the UI's language (web/src/lib/shop/i18n.ts
maps `note.<code>`). The English line is still written to shop_log.note for the log and for clients that do not know
a code. Raw exception text stays with the farm: parameters named in PRIVATE reach operators only.

Rows written before the codes existed are read back through `legacy`, which knows the old English lines.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

PRIVATE = {"error", "detail"}  # exception text and server-side details: operators only


def _quoted(p: dict[str, Any]) -> str:
    by = "OrcaSlicer" if p.get("by") == "orca" else "the operator"
    usd = p.get("total_usd")
    return (f"{p.get('grams')} g, {p.get('minutes')} min each x{p.get('quantity')}: {float(p.get('total') or 0):,.0f} {p.get('currency') or 'KZT'}"
            + (f" (${float(usd):.2f})" if usd is not None else "") + f", by {by}")


def _with(base: str, key: str) -> Callable[[dict[str, Any]], str]:
    return lambda p: f"{base}: {p[key]}" if p.get(key) else base


EN: dict[str, Callable[[dict[str, Any]], str]] = {
    "created": lambda p: "created",
    "ordered_studio": lambda p: "ordered from the studio",
    "ordered_telegram": lambda p: "ordered from the Telegram chat",
    "ordered_catalog": _with("ordered from the catalog", "title"),
    "intake_read": lambda p: f"read by {p.get('model') or 'the intake model'}: {p.get('title') or ''}",
    "intake_unread": _with("not read", "error"),
    "held": _with("held for the farm operator", "why"),
    # with what the operator set for a request nobody could read
    "approved": lambda p: _with("approved by the operator", "note")(p) + "".join(
        f", {x}" for x in (f"{p['quantity']} pcs" if p.get("quantity") else "", p.get("material") or "") if x),
    "refused_safety": lambda p: p.get("reason") or "refused by the safety check",
    "refused_operator": lambda p: p.get("note") or "refused by the operator",
    "designing": lambda p: "the agent is measuring and designing",
    "asked": lambda p: "the agent asked the customer a question",
    "answered": lambda p: "answered; the agent goes on",
    "design_done": lambda p: "the design finished",
    "quoted": _quoted,
    "requoted": lambda p: f"quoted again: {_quoted(p)}",
    "problem": lambda p: f"{p.get('code')}: {p['detail']}" if p.get("detail") else str(p.get("code") or "stopped"),
    "expired": lambda p: "the quote expired; a fresh quote brings the order back",
    "paid_test": lambda p: "test payment",
    # G1: declared by the customer, checked by hand by the workshop (shop.routes.PayIn)
    "paid_mobile_money": lambda p: f"paid by Mobile Money ({p.get('operator') or '?'}), reference {p.get('reference') or '?'}, to verify",
    "paid_on_pickup": lambda p: "to be paid in cash on pickup",
    "payment_verified": _with("Mobile Money payment checked by the workshop", "reference"),
    "assigned": lambda p: f"on {p.get('printer')}" + (f", sliced again: {p.get('grams')} g (quoted {p.get('quoted')} g), the paid price holds"
                                                      if p.get("resliced") else ""),
    "printed": lambda p: "off the plate, waiting for the QC photo",
    "qc_unmeasured": _with("QC photo not measured", "error"),
    "qc_pass": lambda p: f"QC passed: max {p.get('max')} mm within ±{p.get('tol')} mm",
    "qc_fail": lambda p: f"QC failed: max {p.get('max')} mm over ±{p.get('tol')} mm",
    "reprint_qc": lambda p: "QC failed, back in the queue for a reprint",
    "reprint": lambda p: p.get("note") or "reprint",
    "shipped": lambda p: " ".join(str(p[k]) for k in ("carrier", "tracking") if p.get(k)),
}


def text(code: str, params: dict[str, Any] | None = None) -> str:
    """The English line of a note."""
    f = EN.get(code)
    return f(params or {}) if f else code


def public(params: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (params or {}).items() if k not in PRIVATE}


# the English lines written before the codes: (pattern, code, parameter names, only on a move to this status)
_LEGACY: list[tuple[re.Pattern[str], str, tuple[str, ...], str | None]] = [(re.compile(rx, re.S), code, keys, (on or [None])[0])
                                                                           for rx, code, keys, *on in (
    (r"^created$", "created", ()),
    (r"^ordered from the studio$", "ordered_studio", ()),
    (r"^ordered from the catalog: (.*)$", "ordered_catalog", ("title",)),
    (r"^read by (.*?): (.*)$", "intake_read", ("model", "title")),
    (r"^not read: (.*)$", "intake_unread", ("error",)),
    (r"^held for the farm operator: ?(.*)$", "held", ("why",)),
    (r"^approved by the operator$", "approved", ()),
    (r"^refused by the operator$", "refused_operator", ()),
    (r"^refused by the safety check$", "refused_safety", ()),
    (r"^the agent is measuring and designing$", "designing", ()),
    (r"^the agent asked the customer a question$", "asked", ()),
    (r"^answered; the agent goes on$", "answered", ()),
    (r"^the design finished$", "design_done", ()),
    (r"^quoted again: ([\d.]+) g, ([\d.]+) min each x(\d+): ([\d,]+) KZT \(\$([\d.]+)\), by (OrcaSlicer|the operator)$", "requoted",
     ("grams", "minutes", "quantity", "total", "total_usd", "by")),
    (r"^([\d.]+) g, ([\d.]+) min each x(\d+): ([\d,]+) KZT \(\$([\d.]+)\), by (OrcaSlicer|the operator)$", "quoted",
     ("grams", "minutes", "quantity", "total", "total_usd", "by")),
    (r"^test payment$", "paid_test", ()),
    (r"^on (.*?), sliced again: ([\d.]+) g \(quoted (.*?) g\), the paid price holds$", "assigned", ("printer", "grams", "quoted"), "printing"),
    (r"^on (.*)$", "assigned", ("printer",), "printing"),
    (r"^off the plate, waiting for the QC photo$", "printed", ()),
    (r"^QC photo not measured: (.*)$", "qc_unmeasured", ("error",)),
    (r"^QC passed: max (\S+) mm within ±(\S+) mm$", "qc_pass", ("max", "tol")),
    (r"^QC failed: max (\S+) mm over ±(\S+) mm$", "qc_fail", ("max", "tol")),
    (r"^QC failed, back in the queue for a reprint$", "reprint_qc", ()),
    (r"^([a-z_]+): (.*)$", "problem", ("code", "detail")),
)]
_NUMBERS = ("grams", "minutes", "total", "total_usd")


def legacy(note: str, status: str, frm: str | None, actor: str = "system") -> tuple[str, dict[str, Any]] | None:
    """(code, params) of an English line written before the codes, or None for free text (an operator's own note)."""
    note = (note or "").strip()
    if not note:
        return None
    for rx, code, keys, on in _LEGACY:
        m = rx.match(note)
        if not m or (on and on != status):
            continue
        p: dict[str, Any] = dict(zip(keys, m.groups()))
        for k in _NUMBERS:
            if k in p:
                p[k] = float(str(p[k]).replace(",", ""))
        if "quantity" in p:
            p["quantity"] = int(p["quantity"])
        if "by" in p:
            p["by"] = "orca" if p["by"] == "OrcaSlicer" else "operator"
        if code == "assigned" and "grams" in p:
            p["resliced"] = True
        return code, p
    # an operator's or the safety check's own words on a move that names its step
    if status == "refused":
        return ("refused_operator", {"note": note}) if actor == "operator" else ("refused_safety", {"reason": note})
    if status == "shipped":
        return "shipped", {"carrier": note}
    if status == "paid" and frm == "qc":
        return "reprint", {"note": note}
    if status == "requested" and frm == "requested" and actor == "operator":
        return "approved", {"note": note}
    return None


def entry(row: dict[str, Any], operator: bool) -> dict[str, Any]:
    """A shop_log row as the timeline shows it: the code and its parameters, private ones for the farm only."""
    data = row.get("data") or {}
    code, params = data.get("code"), data.get("params")
    if not code:
        found = legacy(row.get("note") or "", row.get("too") or "", row.get("frm"), row.get("actor") or "system")
        code, params = found if found else (None, None)
    out = {"status": row["too"], "from": row["frm"], "actor": row["actor"], "note": row.get("note") or "", "ts": row["ts"],
           "code": code, "params": params or {}}
    if code and not operator:
        out["params"] = public(params)
        if set(params or {}) & PRIVATE:
            out["note"] = text(code, out["params"])
    return out
