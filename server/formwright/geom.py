"""Pool of Node geometry workers (packages/geom/src/worker.ts).

Each worker runs with the Node permission model: it may read only its own code and
node_modules, cannot write files, spawn processes or load addons. Agent-written
programs also run inside a `vm` context with a timeout. A worker that times out is
killed and replaced.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
from typing import Any

from .config import REPO_DIR, settings

log = logging.getLogger(__name__)


class GeomError(Exception):
    def __init__(self, stage: str, message: str):
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message


class _Worker:
    def __init__(self) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.ids = itertools.count(1)

    async def start(self) -> None:
        s = settings()
        geom = s.geom_dir
        args = [
            s.node_bin,
            "--permission",
            f"--allow-fs-read={geom}",
            f"--allow-fs-read={REPO_DIR / 'node_modules'}",
            "--max-old-space-size=1024",
            "--disable-warning=ExperimentalWarning",
            str(geom / "src" / "worker.ts"),
        ]
        # Minimal environment: the worker must never see API keys.
        env = {k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "USERPROFILE", "FW_PROGRAM_TIMEOUT_MS")}
        self.proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(geom),
            env=env,
            limit=256 * 1024 * 1024,
        )
        line = await asyncio.wait_for(self.proc.stdout.readline(), 30)  # type: ignore[union-attr]
        if b"ready" not in line:
            err = await self.proc.stderr.read(4000)  # type: ignore[union-attr]
            raise RuntimeError(f"geom worker failed to start: {line!r} {err.decode(errors='ignore')}")

    async def kill(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()
        self.proc = None

    async def call(self, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        async with self.lock:
            if self.proc is None or self.proc.returncode is not None:
                await self.start()
            assert self.proc and self.proc.stdin and self.proc.stdout
            req_id = next(self.ids)
            self.proc.stdin.write((json.dumps({"id": req_id, "method": method, "params": params}) + "\n").encode())
            await self.proc.stdin.drain()
            # A reply to an earlier call whose caller was cancelled may still be in the pipe;
            # without matching ids every later call would get the previous call's result.
            deadline = asyncio.get_running_loop().time() + timeout
            while True:
                try:
                    line = await asyncio.wait_for(self.proc.stdout.readline(), max(0.0, deadline - asyncio.get_running_loop().time()))
                except TimeoutError:
                    await self.kill()
                    raise GeomError("timeout", f"geometry took longer than {timeout:.0f}s") from None
                except asyncio.CancelledError:
                    # the worker is still busy with this call; a fresh one is cheaper than waiting
                    await self.kill()
                    raise
                if not line:
                    err = (await self.proc.stderr.read(4000)).decode(errors="ignore") if self.proc.stderr else ""
                    await self.kill()
                    raise GeomError("crash", err[-1500:] or "worker exited")
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("geom worker: non-JSON output %r", line[:200])
                    continue
                if isinstance(msg, dict) and msg.get("id") == req_id:
                    break
                log.warning("geom worker: dropping stale reply id=%r (waiting for %d)", msg.get("id") if isinstance(msg, dict) else None, req_id)
            if "error" in msg:
                raise GeomError(msg["error"].get("stage", "runtime"), msg["error"].get("message", ""))
            return msg["result"]


class GeomPool:
    def __init__(self, size: int) -> None:
        self.workers = [_Worker() for _ in range(max(1, size))]
        self.rr = itertools.cycle(range(len(self.workers)))

    async def call(self, method: str, params: dict[str, Any], timeout: float = 60) -> dict[str, Any]:
        # prefer an idle worker, else round-robin
        for w in self.workers:
            if not w.lock.locked():
                return await w.call(method, params, timeout)
        return await self.workers[next(self.rr)].call(method, params, timeout)

    async def close(self) -> None:
        for w in self.workers:
            await w.kill()

    # convenience wrappers ---------------------------------------------------
    async def build(self, source: str, params: dict | None = None, *, analyze: str = "fast", mesh: bool = False, **extra: Any) -> dict:
        return await self.call("build", {"source": source, "params": params or {}, "analyze": analyze, "mesh": mesh, **extra})

    async def render(self, source: str, params: dict | None = None, **extra: Any) -> dict:
        return await self.call("render", {"source": source, "params": params or {}, **extra})

    async def export(self, source: str, params: dict | None = None, fmt: str = "3mf", **extra: Any) -> dict:
        return await self.call("export", {"source": source, "params": params or {}, "format": fmt, **extra}, timeout=120)

    async def inspect(self, source: str, params: dict | None = None, ops: list | None = None, **extra: Any) -> dict:
        return await self.call("inspect", {"source": source, "params": params or {}, "ops": ops or [], **extra})

    async def fit(self, source: str, params: dict | None = None, **extra: Any) -> dict:
        return await self.call("fit", {"source": source, "params": params or {}, **extra}, timeout=180)

    async def parse_mesh(self, data: bytes, fmt: str) -> dict:
        """STL/OBJ bytes -> welded {positions, triangles, stats}."""
        import base64

        return await self.call("parseMesh", {"data": base64.b64encode(data).decode(), "format": fmt}, timeout=120)


_pool: GeomPool | None = None


def geom() -> GeomPool:
    global _pool
    if _pool is None:
        _pool = GeomPool(settings().geom_workers)
    return _pool
