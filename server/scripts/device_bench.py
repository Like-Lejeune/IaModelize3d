"""The device board bench: real device documents through deviceapi.build_device's real attempt loop, offline. No LLM, no job,
nothing saved (the store and the events are stubbed, as tests/test_device_compile.py does); the tscircuit worker needs no
network and the catalogue is cached in data/catalog.

Each document (the latest version of a project) is built from its own board and, when it differs, from the chosen concept's
board size. One row per build: the size asked for, the size built, its area, the parts' footprint area, their ratio, the
attempts, the DRC errors left, the vias and the seconds.

    cd server; PYTHONPATH=. .venv/Scripts/python.exe scripts/device_bench.py [--ids p_a p_b] [--modes doc concept auto]
        [--jobs 3] [--json out.json] [--render DIR]

--render writes each board's pcb_top as a PNG. 'auto' starts from what the compiler itself asks for: no board.w/h at all.
"""
from __future__ import annotations

import argparse
import asyncio
import collections
import json
import logging
import sqlite3
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from formwright import device, device_concept, deviceapi, pcb
from formwright.config import REPO_DIR

BENCH = ("p_c37992a561a1490e p_676f80c60e764971 p_2ef9024d09344d35 p_1c771479691b4af7 p_5112fdf17cc74558 p_56ccba999cd84e2c p_fa119f02a7ac426c "
         "p_706cd44da00b4f13 p_08bf1a5e5f6a4d81 p_139d712e8d3e40fb p_75c8f7520c014bd8 p_7a4af5e28ada4f46 p_988e972430b84bc8 p_5196dae28c314a26 "
         "p_b7c373f74a174d38 p_ca81339b063a4319 p_3ad2345108ef46ea").split()


SAVED: dict[str, dict[str, Any]] = {}  # what build_device would have saved, by the key it was built under


def latest_doc(db: sqlite3.Connection, project_id: str) -> dict[str, Any] | None:
    row = db.execute("SELECT doc FROM device_docs WHERE project_id = ? ORDER BY version DESC LIMIT 1", (project_id,)).fetchone()
    if not row:
        return None
    doc = json.loads(row[0])
    doc.pop("firmware", None)
    return doc


def starts(doc: dict[str, Any], modes: list[str]) -> list[tuple[str, dict[str, Any]]]:
    """(mode, the document to build) for each start asked for; the concept's board is only a start of its own when it differs."""
    out: list[tuple[str, dict[str, Any]]] = []
    norm, _ = device.normalize(doc)
    board = {k: norm["board"].get(k) for k in ("shape", "w", "h")}
    for mode in modes:
        d = json.loads(json.dumps(doc))
        if mode == "concept":
            want = (device_concept.chosen(norm) or {}).get("board") or {}
            if not (want.get("w") and want.get("h")):
                continue
            d["board"] = {**(d.get("board") or {}), **{k: want[k] for k in ("shape", "w", "h", "r") if k in want}}
            if {k: device.normalize(d)[0]["board"].get(k) for k in ("shape", "w", "h")} == board and "doc" in modes:
                continue
        elif mode == "auto":
            d["board"] = {k: v for k, v in (d.get("board") or {}).items() if k not in ("w", "h")}
        out.append((mode, d))
    return out


async def build_one(project_id: str, mode: str, doc: dict[str, Any], render: Path | None) -> dict[str, Any]:
    """One document through the attempt loop: a row of the bench, every placement or routing error counted by type."""
    t0 = time.perf_counter()
    norm, _ = device.normalize(doc)
    parts, _ = await device.resolve(norm)
    asked = device.estimate(norm, parts)
    key = f"{project_id}:{mode}"
    res = await deviceapi.build_device(key, doc)
    secs = time.perf_counter() - t0
    row: dict[str, Any] = {"id": project_id, "mode": mode, "title": norm["title"], "shape": norm["board"].get("shape") or "rect", "board": [norm["board"].get("w"), norm["board"].get("h")],
                           "asked": list(asked), "seconds": round(secs, 1)}
    if not res.get("build"):
        return {**row, "error": str(res.get("error"))[:200], "attempts": len(res.get("attempts") or [])}
    size = tuple(res["size_mm"])
    area, need = device.board_area(norm, size), device.footprint_area(norm, parts)
    b = res["build"]
    kinds = collections.Counter(str(e.get("type")) for e in b.get("errors") or [])
    packing = sum(1 for a in res["attempts"] if "pack" in str(a.get("first") or "").lower())
    row.update({"built": list(size), "area": round(area), "need": round(need), "ratio": round(area / need, 2) if need else None,
                "attempts": len(res["attempts"]), "sizes": [a.get("size_mm") for a in res["attempts"]], "errors": len(b.get("errors") or []), "cascaded": int(b.get("suppressed") or 0),
                "kinds": dict(kinds), "first": [a.get("first") for a in res["attempts"] if a.get("first")][:5], "packing": packing,
                "vias": (b.get("counts") or {}).get("vias"), "traces": (b.get("counts") or {}).get("traces"), "intent_ok": res.get("intent_ok"),
                "warnings": collections.Counter(str(w.get("type")) for w in b.get("warnings") or [])})
    svg = ((SAVED.pop(key, {}).get("files") or {}).get("files") or {}).get("pcb_top.svg")
    if render and svg:
        png = await pcb.render_png_async(svg, 1000, "#ffffff")
        if png:
            (render / f"{project_id}_{mode}.png").write_bytes(png)
    return row


def table(rows: list[dict[str, Any]]) -> str:
    head = f"{'project':<20} {'from':<8} {'shape':<8} {'asked':>8} {'built':>8} {'area':>6} {'parts':>6} {'ratio':>6} {'att':>4} {'drc':>4} {'vias':>5} {'sec':>6}  errors"
    lines = [head, "-" * len(head)]
    size = lambda s: f"{s[0]:g}x{s[1]:g}" if s else "-"  # noqa: E731
    for r in rows:
        if r.get("error"):
            lines.append(f"{r['id']:<20} {r['mode']:<8} {r['shape']:<8} {size(r['asked']):>8} ERROR after {r['attempts']} attempts: {r['error']}")
            continue
        lines.append(f"{r['id']:<20} {r['mode']:<8} {r['shape']:<8} {size(r['asked']):>8} {size(r['built']):>8} {r['area']:>6} {r['need']:>6} {r['ratio']:>6} {r['attempts']:>4} "
                     f"{r['errors']:>4} {str(r['vias']):>5} {r['seconds']:>6}  {', '.join(f'{k} x{v}' for k, v in r['kinds'].items())}")
    done = [r for r in rows if not r.get("error")]
    if done:
        lines.append("-" * len(head))
        lines.append(f"{len(done)} built, {sum(1 for r in done if not r['errors'])} DRC clean, median ratio {statistics.median(r['ratio'] for r in done):.2f}, ratio > 2.5: {sum(1 for r in done if r['ratio'] > 2.5)}, "
                     f"first or second attempt: {sum(1 for r in done if r['attempts'] <= 2)}, packing errors on the way: {sum(r['packing'] for r in done)}, "
                     f"mean vias {statistics.mean(r['vias'] or 0 for r in done):.1f}, total {sum(r['seconds'] for r in done):.0f} s")
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ids", nargs="*", default=BENCH)
    ap.add_argument("--modes", nargs="*", default=["doc", "concept"], choices=["doc", "concept", "auto"])
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--db", default=str(REPO_DIR / "data" / "formwright.db"))
    ap.add_argument("--gap", type=float, help="the placer's gap between free parts, mm (else device.ARRANGE_GAPS_MM)")
    ap.add_argument("--json")
    ap.add_argument("--render")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    render = Path(a.render) if a.render else None
    if a.gap is not None:
        device.ARRANGE_GAPS_MM = (a.gap,)
    if render:
        render.mkdir(parents=True, exist_ok=True)

    async def nothing(*_a: Any, **_k: Any) -> None:
        return None

    async def save(key: str, **k: Any) -> int:
        SAVED[key] = k
        return 1

    deviceapi.pcb_store.save = save  # type: ignore[assignment]
    deviceapi.events.emit = nothing  # type: ignore[assignment]
    deviceapi.pcbapi.emit_route = nothing  # type: ignore[assignment]
    deviceapi.pcbapi.emit_version = nothing  # type: ignore[assignment]
    pcb._pool = pcb.PcbPool(a.jobs)
    gate = asyncio.Semaphore(a.jobs)
    db = sqlite3.connect(a.db)
    todo = [(pid, mode, d) for pid in a.ids if (doc := latest_doc(db, pid)) for mode, d in starts(doc, a.modes)]

    async def run(pid: str, mode: str, d: dict[str, Any]) -> dict[str, Any]:
        async with gate:
            try:
                r = await build_one(pid, mode, d, render)
            except Exception as e:  # noqa: BLE001 - one document never stops the bench
                r = {"id": pid, "mode": mode, "shape": "?", "asked": None, "attempts": 0, "error": f"{type(e).__name__}: {e}"[:200]}
            print(f"  {pid} {mode}: {r.get('built')} in {r.get('attempts')} attempts, {r.get('errors')} errors {r.get('error') or ''}", file=sys.stderr, flush=True)
            return r

    rows = await asyncio.gather(*(run(*t) for t in todo))
    await pcb.close()
    print(table(rows))
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
