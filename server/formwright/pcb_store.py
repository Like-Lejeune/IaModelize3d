"""PCB versions of a project (contract C7): one row per routed board in pcb_boards, its files under
data/files/<project>/pcb/v<n>/. The table is created on first use, so db.py stays as it is. A version is immutable:
a changed circuit is a new version, and board.json carries source.pcb_job 'pcb:v<n>' so an enclosure built from it
names the board it was made for.
"""
from __future__ import annotations

import asyncio
import json
import weakref
from pathlib import Path
from typing import Any

from . import storage
from .db import get_db, now

# the only names a version has, and the only ones the API serves
ARTIFACTS = (
    "circuit.tsx", "circuit.json", "board.json", "drc.json", "route_frames.json", "pcb_top.svg", "pcb_bottom.svg",
    "schematic.svg", "board.glb", "gerbers.zip", "bom.csv", "cpl.csv",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pcb_boards (
  project_id TEXT NOT NULL,
  version INTEGER NOT NULL,
  source TEXT NOT NULL,
  intent TEXT,
  checks TEXT,
  artifacts TEXT,
  created_at REAL NOT NULL,
  PRIMARY KEY (project_id, version)
)
"""

_ready: weakref.WeakSet = weakref.WeakSet()
_lock = asyncio.Lock()


async def _db():
    db = await get_db()
    if db not in _ready:
        await db.execute(SCHEMA)
        _ready.add(db)
    return db


def _json(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return v
    return v


def _row(r: dict[str, Any] | None) -> dict[str, Any] | None:
    if r is None:
        return None
    out = dict(r)
    for k in ("intent", "checks", "artifacts"):
        if k in out:
            out[k] = _json(out[k])
    return out


def _dump(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _stamp(board: dict[str, Any], version: int) -> dict[str, Any]:
    board = dict(board)
    board["source"] = {**(board.get("source") or {}), "kind": "pcb", "pcb_job": f"pcb:v{version}"}
    board.setdefault("id", f"pcb-v{version}")
    return board


def pack(*, source: str, intent: dict | None, build: dict[str, Any], files: dict[str, Any] | None = None, version: int = 1) -> dict[str, Any]:
    """A build (pcb.pool().build) and its fab files (pcb.pool().export(), or just its "files") as what a version
    stores: {source, intent, checks, files {name: bytes|str}}, board.json stamped with `version`."""
    export = files if isinstance(files, dict) and isinstance(files.get("files"), dict) else {"files": files or {}}
    blobs: dict[str, bytes | str] = {k: v for k, v in export["files"].items() if k in ARTIFACTS}
    intent = intent if intent is not None else (build.get("meta") or {}).get("intent")
    board = _stamp(build["board"], version) if build.get("board") else {}
    outline = (board.get("pcb") or {}).get("outline") or {}
    checks = {
        "ok": bool(build.get("ok")),
        "errors": build.get("errors") or [],
        "warnings": build.get("warnings") or [],
        "suppressed": build.get("suppressed", 0),
        "counts": build.get("counts") or {},
        "intent": build.get("intent") or {"ok": True, "issues": []},
        "limits": build.get("limits") or {"ok": True, "issues": []},
        "ms": build.get("ms"),
        "fab": {k: export[k] for k in ("layers", "lcsc_verified", "rotation_checked", "bom_lines", "cpl_lines", "glb_error") if k in export},
    }
    blobs["circuit.tsx"] = source
    blobs["drc.json"] = _dump({k: checks[k] for k in ("ok", "errors", "warnings", "suppressed", "counts", "intent", "limits")})
    if build.get("circuit_json") is not None:
        blobs["circuit.json"] = _dump(build["circuit_json"])
    if board:
        blobs["board.json"] = json.dumps(board, ensure_ascii=False, indent=1)
    frames = build.get("frames") or []
    blobs["route_frames.json"] = _dump({
        "frames": frames, "total": len(frames),
        # frames are in fw.board/1 mm; svg_map turns them into pcb_top.svg pixels
        "board": {"w": outline.get("w"), "h": outline.get("h")},
        "svg_map": export.get("svg_map") or {},
        "glb_map": export.get("glb_map"),
    })
    return {"source": source, "intent": intent, "checks": checks, "files": blobs}


async def _insert(project_id: str, version: int, packed: dict[str, Any]) -> None:
    db = await _db()
    artifacts: dict[str, str] = {}
    for name, data in packed["files"].items():
        if name not in ARTIFACTS:
            continue
        raw = data.encode() if isinstance(data, str) else bytes(data)
        artifacts[name] = storage.save_bytes(project_id, f"pcb/v{version}", name, raw)
    intent = packed.get("intent")
    await db.execute(
        "INSERT INTO pcb_boards (project_id, version, source, intent, checks, artifacts, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        project_id, version, packed["source"], _dump(intent) if intent is not None else None, _dump(packed["checks"]), _dump(artifacts), now(),
    )


async def _next(project_id: str) -> int:
    row = await (await _db()).one("SELECT MAX(version) AS v FROM pcb_boards WHERE project_id = ?", project_id)
    return int((row or {}).get("v") or 0) + 1


async def save(project_id: str, *, source: str, intent: dict | None, build: dict[str, Any], files: dict[str, Any] | None = None) -> int:
    """Store a build (pcb.pool().build) and its fab files (pcb.pool().export(), or just its "files") as the next
    version; returns the version number."""
    async with _lock:
        version = await _next(project_id)
        await _insert(project_id, version, pack(source=source, intent=intent, build=build, files=files, version=version))
    return version


async def add(project_id: str, packed: dict[str, Any]) -> int:
    """A version packed elsewhere (pack(), e.g. the home page's PCB example, routed once and kept) as the next version
    of this project; its board.json is stamped with the version it gets here. Returns the version number."""
    async with _lock:
        version = await _next(project_id)
        files = dict(packed["files"])
        if "board.json" in files:
            board = json.loads(files["board.json"])
            files["board.json"] = json.dumps(_stamp(board, version), ensure_ascii=False, indent=1)
        await _insert(project_id, version, {**packed, "files": files})
    return version


async def versions(project_id: str) -> list[dict[str, Any]]:
    """Every version of the project, oldest first, without the source."""
    db = await _db()
    rows = await db.all(
        "SELECT project_id, version, intent, checks, artifacts, created_at FROM pcb_boards WHERE project_id = ? ORDER BY version",
        project_id,
    )
    return [_row(r) for r in rows]  # type: ignore[misc]


async def get(project_id: str, version: int | None = None) -> dict[str, Any] | None:
    """One version with its source, the latest when version is None; None when there is none."""
    db = await _db()
    if version is None:
        r = await db.one("SELECT * FROM pcb_boards WHERE project_id = ? ORDER BY version DESC LIMIT 1", project_id)
    else:
        r = await db.one("SELECT * FROM pcb_boards WHERE project_id = ? AND version = ?", project_id, int(version))
    return _row(r)


def artifact_path(project_id: str, version: int, name: str) -> Path | None:
    """The file of one artifact, or None for a name outside ARTIFACTS or a file that is not there."""
    if name not in ARTIFACTS or "/" in project_id or "\\" in project_id or project_id in ("", ".", ".."):
        return None
    path = storage.abs_path(f"{project_id}/pcb/v{int(version)}/{name}")
    return path if path.is_file() else None


def artifact_url(project_id: str, version: int, name: str) -> str:
    return f"/api/projects/{project_id}/pcb/{int(version)}/{name}"
