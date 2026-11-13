"""Pool of Node PCB workers (packages/pcb/dist/pcb-worker.mjs, contract C6).

A circuit is TSX the model writes; the worker transpiles it, evaluates it in a vm context, places, autoroutes and
checks the board, and on request writes the fab files and previews. It runs like the geometry worker: the Node
permission model with read access to the bundle directory only (no repo, .env or data/, no file writes, child
processes, worker threads or addons), the network cut inside the process, and an environment without keys. The vm
timeout covers only the top level of a circuit: component functions run inside the reconciler, so a circuit that
hangs there is caught here by the call timeout, which kills the worker and starts a fresh one. One worker: routing
holds a core for 3-9 s. A circuit can escape its vm realm (React is a host object) and patch the worker process, so a
worker that ran a build is killed right after it: no other build ever reads a reply through it (a fresh start is 0.7 s).

Routing frames stream while a build runs ({id, frame} lines) and go to on_frame, which the caller turns into
'pcb.route' events.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import inspect
import itertools
import json
import logging
import os
import subprocess
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .config import settings

log = logging.getLogger(__name__)

WORKER = "pcb-worker.mjs"
SVG_PNG = "svg-png.mjs"
ENV_KEEP = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE")


class PcbError(Exception):
    """stage: compile | runtime | timeout | crash | protocol. hint: what to change, when the worker knows."""

    def __init__(self, stage: str, message: str, hint: str | None = None):
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message
        self.hint = hint


EXPECTED = {
    "build": ("ok", "errors", "counts", "circuit_json", "intent", "limits", "frames"),
    "export": ("files",),
}

FrameCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


def dist_dir() -> Path:
    return settings().pcb_dir / "dist"


def _env() -> dict[str, str]:
    # the worker must never see API keys
    return {k: v for k, v in os.environ.items() if k.upper() in ENV_KEEP}


def _decode_files(files: dict[str, Any]) -> dict[str, bytes | str]:
    out: dict[str, bytes | str] = {}
    for name, v in files.items():
        out[name] = base64.b64decode(v["b64"]) if isinstance(v, dict) and "b64" in v else v
    return out


class _Worker:
    def __init__(self, recycle_after: int = 25) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.ids = itertools.count(1)
        self.recycle_after = recycle_after
        self.calls = 0
        self.stderr: deque[str] = deque(maxlen=60)
        self._drain: asyncio.Task | None = None

    async def start(self) -> None:
        s = settings()
        dist = dist_dir()
        script = dist / WORKER
        if not script.exists():
            log.error("PCB worker bundle not found at %s", script)
            raise PcbError("crash", "the PCB worker is not built here: run `npm ci --ignore-scripts && npm run bundle` in packages/pcb")
        args = [
            s.node_bin,
            "--permission",
            f"--allow-fs-read={dist}",
            "--max-old-space-size=1536",
            "--disable-warning=ExperimentalWarning",
            str(script),
        ]
        self.proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(dist),
            env=_env(),
            limit=256 * 1024 * 1024,
        )
        # tscircuit logs stack traces freely; an unread stderr pipe would fill up and stall the worker
        self.stderr.clear()
        self._drain = asyncio.create_task(self._read_stderr(self.proc))
        try:
            line = await asyncio.wait_for(self.proc.stdout.readline(), 60)  # type: ignore[union-attr]
        except TimeoutError:
            await self.kill()
            raise PcbError("crash", "PCB worker did not start within 60 s") from None
        if b"ready" not in line:
            await asyncio.sleep(0.2)
            tail = self.tail()
            await self.kill()
            log.error("PCB worker failed to start: %r %s", line[:200], tail)
            raise PcbError("crash", "the PCB engine could not start")

    async def _read_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr
        with contextlib.suppress(Exception):
            while line := await proc.stderr.readline():
                self.stderr.append(line.decode(errors="ignore").rstrip()[:500])

    def tail(self) -> str:
        return "\n".join(self.stderr)[-1500:]

    async def kill(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()
        if self._drain:
            self._drain.cancel()
            self._drain = None
        self.proc = None

    async def _call(self, method: str, params: dict[str, Any], timeout: float, on_frame: FrameCallback | None = None) -> dict[str, Any]:
        if self.proc is not None and self.calls >= self.recycle_after:
            await self.kill()
        if self.proc is None or self.proc.returncode is not None:
            await self.start()
            self.calls = 0
        self.calls += 1
        assert self.proc and self.proc.stdin and self.proc.stdout
        req_id = next(self.ids)
        self.proc.stdin.write((json.dumps({"id": req_id, "method": method, "params": params}) + "\n").encode())
        await self.proc.stdin.drain()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            try:
                line = await asyncio.wait_for(self.proc.stdout.readline(), max(0.0, deadline - loop.time()))
            except TimeoutError:
                await self.kill()
                raise PcbError("timeout", f"the PCB build took longer than {timeout:.0f} s") from None
            except asyncio.CancelledError:
                # the worker is still routing this call; a fresh one is cheaper than waiting
                await self.kill()
                raise
            if not line:
                await asyncio.sleep(0.1)
                log.warning("pcb worker exited during %s: %s", method, self.tail() or "no output")
                await self.kill()
                raise PcbError("crash", "the PCB engine stopped unexpectedly")
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                log.warning("pcb worker: non-JSON output %r", line[:200])
                continue
            if not isinstance(msg, dict) or msg.get("id") != req_id:
                log.warning("pcb worker: dropping stale reply id=%r (waiting for %d)", msg.get("id") if isinstance(msg, dict) else None, req_id)
                continue
            if "frame" in msg:
                if on_frame:
                    try:
                        r = on_frame(msg["frame"])
                        if inspect.isawaitable(r):
                            await r
                    except Exception:  # noqa: BLE001 - an animation frame never fails the build
                        log.exception("pcb on_frame failed")
                continue
            break
        if "error" in msg:
            err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
            raise PcbError(err.get("stage", "runtime"), err.get("message", ""), err.get("hint"))
        result = msg.get("result")
        missing = [k for k in EXPECTED.get(method, ()) if not isinstance(result, dict) or k not in result]
        if missing:
            await self.kill()
            raise PcbError("protocol", f"{method} reply has no {', '.join(missing)}")
        return result

    async def call(self, method: str, params: dict[str, Any], timeout: float, on_frame: FrameCallback | None = None) -> dict[str, Any]:
        async with self.lock:
            try:
                return await self._call(method, params, timeout, on_frame)
            finally:
                if method == "build":
                    # a circuit that escaped its realm can patch this process (stdout, timers): no later build may share
                    # it, so it dies before the lock goes to the next build waiting on it
                    await self.kill()


class PcbPool:
    def __init__(self, size: int = 1, recycle_after: int = 25) -> None:
        self.workers = [_Worker(recycle_after) for _ in range(max(1, size))]
        self.rr = itertools.cycle(range(len(self.workers)))

    async def call(self, method: str, params: dict[str, Any], timeout: float, on_frame: FrameCallback | None = None) -> dict[str, Any]:
        for w in self.workers:
            if not w.lock.locked():
                return await w.call(method, params, timeout, on_frame)
        return await self.workers[next(self.rr)].call(method, params, timeout, on_frame)

    async def close(self) -> None:
        for w in self.workers:
            await w.kill()

    async def build(self, source: str, *, intent: dict | None = None, on_frame: FrameCallback | None = None, timeout: float | None = None,
                    name: str | None = None, lcsc: dict | None = None) -> dict[str, Any]:
        """TSX -> {ok, errors[{type, message, hint, ref?}], warnings, counts, board (fw.board/1), circuit_json, intent,
        limits, frames[{lines, progress}], nets, meta, ms}. on_frame({frame, total, progress, lines, w, h}) per live frame."""
        timeout = timeout or settings().pcb_timeout
        params: dict[str, Any] = {"source": source, "timeoutMs": int(max(5.0, timeout - 5) * 1000), "frames": on_frame is not None}
        if intent is not None:
            params["intent"] = intent
        if name:
            params["name"] = name
        if lcsc:
            # catalogue footprints (catalog.easyeda) the circuit names as footprint="lcsc:C123": the worker has no network
            params["lcsc"] = lcsc
        return await self.call("build", params, timeout, on_frame)

    async def export(self, circuit_json: list, *, timeout: float = 90, models: dict[str, Any] | None = None) -> dict[str, Any]:
        """Circuit JSON -> {files: {gerbers.zip, board.glb: bytes; bom.csv, cpl.csv, pcb_top.svg, pcb_bottom.svg,
        schematic.svg: str}, layers, svg_map, glb_map, ms}. models: what the board's 3D view draws its parts from
        (packages/pcb/src/models.mjs): {objs: {uuid: OBJ text}, parts: {ref: {prims} | {h}}}."""
        params: dict[str, Any] = {"circuit_json": circuit_json}
        if models:
            params["models"] = models
        r = await self.call("export", params, timeout)
        r["files"] = _decode_files(r["files"])
        return r


_pool: PcbPool | None = None


def pool() -> PcbPool:
    global _pool
    if _pool is None:
        _pool = PcbPool(settings().pcb_pool_size)
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def render_png(svg: str, width: int = 1200, background: str | None = None, timeout: float = 30) -> bytes | None:
    """One of our own SVGs (pcb_top.svg, schematic.svg) -> PNG for the model to look at, or None when the bundle is not
    built or rendering fails. A one-shot process with resvg compiled to wasm, read access to dist/ only."""
    dist = dist_dir()
    script = dist / SVG_PNG
    if not script.exists() or not (dist / "resvg.wasm").exists():
        return None
    args = [settings().node_bin, "--permission", f"--allow-fs-read={dist}", "--disable-warning=ExperimentalWarning", str(script), str(int(width))]
    if background:
        args.append(background)
    try:
        r = subprocess.run(args, input=svg.encode(), capture_output=True, timeout=timeout, cwd=str(dist), env=_env(), check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("render_png failed: %s", e)
        return None
    if r.returncode != 0 or not r.stdout.startswith(b"\x89PNG"):
        log.warning("render_png failed: %s", r.stderr.decode(errors="ignore")[-300:])
        return None
    return r.stdout


async def render_png_async(svg: str, width: int = 1200, background: str | None = None) -> bytes | None:
    return await asyncio.to_thread(render_png, svg, width, background)
