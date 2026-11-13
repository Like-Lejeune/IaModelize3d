"""Order lifecycle of a printed spare part. One table of allowed moves, who may make them, and what must be true.

requested -> designing -> quoted -> paid -> printing -> qc -> shipped -> delivered
A part that already has a model (a studio project, a catalog listing) goes requested -> quoted with no design step.
side exits: needs_info (agent asked), refused (safety gate), cancelled, expired; a failed QC goes back to paid (reprint).
A ready model is quoted while the intake reads it, so Pay also waits for the safety verdict (`safety`); an expired
quote comes back to quoted with a fresh slice.
"""
from __future__ import annotations

import time
from typing import Any

STATUSES = ("requested", "designing", "needs_info", "quoted", "paid", "printing", "qc", "shipped", "delivered",
            "refused", "cancelled", "expired")
OPEN = ("requested", "designing", "needs_info", "quoted")
ACTIVE = ("paid", "printing", "qc")  # the operator's queue
FINAL = ("delivered", "refused", "cancelled", "expired")


class FlowError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def safety(o: dict[str, Any]) -> str | None:
    """Where the intake's safety verdict stands, when it does not let the order be paid: 'pending' (Muse Spark 1.3 is
    still reading it, or could not run yet), 'held' (for the farm operator: the models disagreed, or nothing could be
    read), 'refused'. None: paid may follow."""
    data = o.get("intake") or {}
    if not isinstance(data.get("refuse"), bool):
        return "pending"
    if data["refuse"]:
        return "refused"
    if data.get("review") and not data.get("reviewed"):
        return "held"
    return None


SAFETY_WHY = {"pending": "the safety check is still running", "held": "the farm operator looks at this request first",
              "refused": "refused by the safety check"}


def material_due(o: dict[str, Any]) -> str | None:
    """A ready model ordered with "choose for me" is priced in the order's material while the intake reads it; once the
    intake has picked another one (PETG for a dishwasher part), that is the material to pay for. Returns it while the
    quote is still in another material (its own slice is running, or failed and is tried again), else None."""
    data = o.get("intake") or {}
    req = data.get("request") or {}
    if req.get("kind") != "project" or req.get("material") or data.get("error") or not isinstance(data.get("refuse"), bool):
        return None
    m, q = data.get("material"), (o.get("quote") or {}).get("material")
    return m if m and q and m != q else None


def _quote_ok(o: dict[str, Any]) -> str | None:
    if (s := safety(o)):
        return SAFETY_WHY[s]
    if (m := material_due(o)):
        return f"the price in {m}, the material picked for this part, is not ready yet"
    q = o.get("quote") or {}
    if not q.get("binding"):
        return "only a slicer quote can be paid"
    if q.get("version") is not None and o.get("version") is not None and q["version"] != o["version"]:
        return "the model changed after this quote; quote again"
    return None


def _assigned(o: dict[str, Any]) -> str | None:
    pay = o.get("payment") or {}
    if pay.get("mode") == "mobile_money" and not pay.get("verified"):
        return "check the Mobile Money payment first"
    if not o.get("printer_id"):
        return "assign a printer first"
    if not ((o.get("slice") or {}).get("files") or {}).get("gcode"):
        return "slice for the assigned printer first"
    return None


def _qc_passed(o: dict[str, Any]) -> str | None:
    qc = o.get("qc") or {}
    if not qc.get("pass"):
        return "QC has not passed"
    return None


def _tracking(o: dict[str, Any], data: dict[str, Any]) -> str | None:
    if (o.get("delivery") or {}).get("method") == "pickup":
        return None
    return None if data.get("tracking") or (o.get("shipping") or {}).get("tracking") else "add a tracking number"


def _past_valid(o: dict[str, Any]) -> str | None:
    until = (o.get("quote") or {}).get("valid_until")
    return None if until and until < time.time() else "the quote is still valid"


def _binding(o: dict[str, Any], d: dict[str, Any]) -> str | None:
    return None if (o.get("quote") or {}).get("binding") else "no slicer quote yet"


# (from, to): (actors, guard)
MOVES: dict[tuple[str, str], tuple[tuple[str, ...], Any]] = {
    ("requested", "designing"): (("system", "operator"), None),  # operator: a request held for review, approved
    ("requested", "quoted"): (("system", "operator"), _binding),  # the part already has a model
    ("requested", "refused"): (("system", "operator"), None),
    ("designing", "quoted"): (("system", "operator"), _binding),
    ("designing", "needs_info"): (("system",), None),
    ("designing", "refused"): (("system", "operator"), None),
    ("needs_info", "designing"): (("customer", "system"), None),
    ("quoted", "designing"): (("customer", "system"), None),  # asked for a change
    ("quoted", "paid"): (("customer",), lambda o, d: _quote_ok(o)),
    # on the order as it is now: a list read a moment ago may hold a quote that was renewed since
    ("quoted", "expired"): (("system",), lambda o, d: _past_valid(o)),
    ("expired", "quoted"): (("customer", "system", "operator"), _binding),  # a fresh quote revives it
    # the safety gate answered after the quote (a ready model is quoted while it reads), or the operator refuses a held one
    ("quoted", "refused"): (("system", "operator"), None),
    ("paid", "printing"): (("operator",), lambda o, d: _assigned(o)),
    ("printing", "qc"): (("operator",), None),
    ("qc", "paid"): (("operator", "system"), None),  # QC failed: back in the queue for a reprint
    ("qc", "shipped"): (("operator",), lambda o, d: _qc_passed(o) or _tracking(o, d)),
    ("shipped", "delivered"): (("customer", "operator", "system"), None),
}
for s in OPEN + ("paid",):
    MOVES[(s, "cancelled")] = (("customer", "operator"), None)

# moves whose endpoint writes what the guard checks (assign slices for the printer, quote makes the quote):
# the UI offers them although the guard would fail on the order as it is now
FILLED_BY_ENDPOINT = {("paid", "printing"), ("designing", "quoted"), ("requested", "quoted"), ("expired", "quoted")}


def check(order: dict[str, Any], to: str, actor: str, data: dict[str, Any] | None = None) -> None:
    frm = order["status"]
    if to not in STATUSES:
        raise FlowError("bad_status", f"unknown status {to}")
    move = MOVES.get((frm, to))
    if move is None:
        raise FlowError("bad_move", f"{frm} -> {to} is not allowed")
    actors, guard = move
    if actor not in actors:
        raise FlowError("forbidden", f"{actor} cannot move an order {frm} -> {to}")
    if guard and (why := guard(order, data or {})):
        raise FlowError("guard", why)


def next_moves(order: dict[str, Any], actor: str) -> list[str]:
    """What the UI may offer this actor right now (guards included)."""
    out = []
    for (frm, to), (actors, guard) in MOVES.items():
        if frm != order["status"] or actor not in actors:
            continue
        if guard and (frm, to) not in FILLED_BY_ENDPOINT and guard(order, {"tracking": "?"}):
            continue
        out.append(to)
    return out
