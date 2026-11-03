"""PCB versions over HTTP (contract C8) and the project events a build sends.

GET /api/projects/{id}/pcb lists the versions; GET /api/projects/{id}/pcb/{v}/{name} serves one artifact, by a fixed
list of names only (v may be 'latest'). Access is the project's own (app.load_project): a public project's boards
are readable by anyone, a private one only by its owner. While a build routes, 'pcb.route' {frame, total, lines}
events carry the animation frames (fw.board/1 mm; route_frames.json has the map to pcb_top.svg pixels); a saved
version is announced with 'pcb.version' {version, counts, drc}.

Mounted by app.py (ROUTERS); this module reaches app lazily, because app imports it while it is being built.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse

from . import events, pcb_store

router = APIRouter()

MEDIA = {
    ".svg": "image/svg+xml", ".glb": "model/gltf-binary", ".zip": "application/zip", ".csv": "text/csv; charset=utf-8",
    ".json": "application/json", ".tsx": "text/plain; charset=utf-8",
}
DOWNLOADS = {"gerbers.zip", "bom.csv", "cpl.csv"}
# versions never change; an SVG of ours still must not run anything if opened on its own
SVG_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"


def _app():
    from formwright import app as app_module

    return app_module


async def _user(request: Request, response: Response) -> dict[str, Any]:
    return await _app().current_user(request, response)


def _not_found(what: str) -> HTTPException:
    return HTTPException(404, {"detail": what, "code": "not_found"})


def version_out(project_id: str, row: dict[str, Any]) -> dict[str, Any]:
    checks = row.get("checks") or {}
    names = list((row.get("artifacts") or {}).keys())
    v = int(row["version"])
    return {
        "version": v,
        "created_at": row.get("created_at"),
        "counts": checks.get("counts") or {},
        "drc": {"errors": len(checks.get("errors") or []), "warnings": len(checks.get("warnings") or [])},
        "intent_ok": bool((checks.get("intent") or {}).get("ok", True)),
        "limits_ok": bool((checks.get("limits") or {}).get("ok", True)),
        # a device build's BOM numbers come from the LCSC catalogue; a hand-written circuit's are as the model wrote them
        "lcsc_verified": bool((checks.get("fab") or {}).get("lcsc_verified")),
        "artifacts": {n: pcb_store.artifact_url(project_id, v, n) for n in pcb_store.ARTIFACTS if n in names},
    }


@router.get("/api/projects/{project_id}/pcb")
async def list_pcb_versions(project_id: str, user=Depends(_user)) -> list[dict[str, Any]]:
    await _app().load_project(project_id, user)
    return [version_out(project_id, r) for r in await pcb_store.versions(project_id)]


@router.get("/api/projects/{project_id}/pcb/{version}/{name}")
async def pcb_artifact(project_id: str, version: str, name: str, user=Depends(_user)):
    if name not in pcb_store.ARTIFACTS:
        raise _not_found("no such PCB file")
    await _app().load_project(project_id, user)
    if version == "latest":
        row = await pcb_store.get(project_id)
        if not row:
            raise _not_found("no PCB version yet")
        v = int(row["version"])
    elif version.isdigit():
        v = int(version)
    else:
        raise _not_found("no such PCB version")
    path = pcb_store.artifact_path(project_id, v, name)
    if path is None:
        raise _not_found("no such PCB file")
    ext = name[name.rindex("."):]
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=3600" if version != "latest" else "no-store"}
    if ext == ".svg":
        headers["Content-Security-Policy"] = SVG_CSP
    if name in DOWNLOADS:
        return FileResponse(path, media_type=MEDIA[ext], headers=headers, filename=f"{project_id}-pcb-v{v}-{name}")
    return FileResponse(path, media_type=MEDIA[ext], headers=headers)


# ------------------------------------------------------------------ events and the build -> version path
async def emit_route(project_id: str, frame: dict[str, Any], job_id: str | None = None) -> None:
    """One live routing frame (pcb.pool().build's on_frame) as a 'pcb.route' event."""
    data = {"frame": frame.get("frame"), "total": frame.get("total"), "lines": frame.get("lines") or []}
    for k in ("progress", "w", "h"):
        if frame.get(k) is not None:
            data[k] = frame[k]
    await events.emit(project_id, "pcb.route", data, job_id)


async def emit_version(project_id: str, version: int, build: dict[str, Any], job_id: str | None = None) -> None:
    await events.emit(project_id, "pcb.version", {
        "version": version,
        "counts": build.get("counts") or {},
        "drc": {"errors": len(build.get("errors") or []), "warnings": len(build.get("warnings") or [])},
        "intent_ok": bool((build.get("intent") or {}).get("ok", True)),
    }, job_id)


async def build_version(project_id: str, source: str, *, intent: dict | None = None, job_id: str | None = None,
                        timeout: float | None = None, save_failed: bool = False) -> tuple[dict[str, Any], int | None]:
    """Build with live 'pcb.route' events; a build without errors (or any, with save_failed) is exported, saved as the
    next version and announced with 'pcb.version'. Returns (build, version or None). Raises pcb.PcbError."""
    from .pcb import pool

    async def frame(f: dict[str, Any]) -> None:
        await emit_route(project_id, f, job_id)

    build = await pool().build(source, intent=intent, on_frame=frame, timeout=timeout)
    if not build["ok"] and not save_failed:
        return build, None
    exported = await pool().export(build["circuit_json"]) if build["ok"] else None
    version = await pcb_store.save(project_id, source=source, intent=intent, build=build, files=exported)
    await emit_version(project_id, version, build, job_id)
    return build, version
