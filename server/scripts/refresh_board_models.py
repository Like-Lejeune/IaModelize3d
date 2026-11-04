"""Redraw board.glb of boards built before the part models: modules as themselves, catalogue parts with their real 3D models.
Only the picture changes: the routed circuit, the fab files and the case stay as they were.

    python scripts/refresh_board_models.py             # the home page's examples and every device project's latest board
    python scripts/refresh_board_models.py p_0123 ...  # these projects
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from formwright import catalog, device, deviceapi, pcb  # noqa: E402
from formwright.config import settings  # noqa: E402
from formwright.showcase import DEVICES_DIR  # noqa: E402


async def redraw(folder: Path) -> str:
    """One board's folder (circuit.json, device.json, board.glb): written in place when the export gives a new picture."""
    cj = json.loads((folder / "circuit.json").read_text(encoding="utf-8"))
    doc, _ = device.normalize(json.loads((folder / "device.json").read_text(encoding="utf-8")))
    parts: dict[str, dict] = {}
    for n in doc["nodes"]:
        if n["kind"] == "chip":
            raw = await catalog.easyeda(n["lcsc"])
            parts[n["id"]] = {"raw": raw, "height_mm": catalog.height_of(raw) if raw else None}
    models = await deviceapi.part_models(doc, parts)
    out = await pcb.pool().export(cj, models=models)
    glb = out["files"].get("board.glb")
    if not glb:
        return f"no picture: {out.get('glb_error')}"
    (folder / "board.glb").write_bytes(glb)
    return f"{len(glb) / 1e6:.1f} MB, {len(models['objs'])} catalogue models" + (f", {out['glb_error']}" if out.get("glb_error") else "")


def folders(asked: list[str]) -> list[Path]:
    data = settings().data_dir
    con = sqlite3.connect(f"file:{(data / 'formwright.db').as_posix()}?mode=ro", uri=True)
    rows = con.execute("SELECT project_id, MAX(version) FROM pcb_boards GROUP BY project_id").fetchall()
    con.close()
    out = [] if asked else sorted(p for p in DEVICES_DIR.iterdir() if (p / "device.json").is_file())
    for pid, v in rows:
        if not asked or pid in asked:
            out.append(data / "files" / pid / "pcb" / f"v{v}")
    return [f for f in out if (f / "device.json").is_file() and (f / "circuit.json").is_file()]


async def main() -> None:
    for f in folders(sys.argv[1:]):
        try:
            print(f.as_posix()[-48:], await redraw(f), flush=True)
        except Exception as e:  # noqa: BLE001 - one broken old board does not stop the rest
            print(f.as_posix()[-48:], "FAILED", str(e)[:200], flush=True)
    await pcb.close()


asyncio.run(main())
