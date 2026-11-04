"""Pool of Node geometry workers (packages/geom/src/worker.ts).

Each worker runs with the Node permission model (--permission): it may read only the geom
package and node_modules (so not the repo, .env or data/), and may not write files, spawn
processes, start worker threads or load native addons. The permission model does not cover
network, so the worker itself severs every outbound socket and DNS route at startup
(severNetwork); the container shares the API's network, so this sever is the only network
barrier. Agent- or user-written programs (a program can be uploaded with
PUT /api/projects/{id}/program) also run inside a `vm` context with a timeout, and their params
are rebuilt in that realm. `lib` is still a host object, so a program can reach the worker's
`process` and patch it (stdout, prototypes, timers): a worker therefore serves one program
(source, params and inputs) only and is replaced before it runs another (0.2 s), so no program
can read or rewrite another's calls. A worker that times out or answers out of protocol is
killed and replaced, and every worker is replaced after a number of calls.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import itertools
import json
import logging
import os
from collections import deque
from typing import Any

from .config import REPO_DIR, settings

log = logging.getLogger(__name__)


class GeomError(Exception):
    def __init__(self, stage: str, message: str):
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message


# people read these; what the engine itself said goes to the log
CRASHED = "the geometry engine stopped unexpectedly"
OUT_OF_PROTOCOL = "the geometry engine gave an unusable answer"
# What each method's result carries; a reply without it means the two sides disagree.
EXPECTED = {
    "build": ("ok", "params", "parts"),
    "render": ("png",),
    "export": ("data", "mime"),
    "inspect": ("results",),
    "fit": ("params",),
    "parseMesh": ("stats",),
}


def program_key(params: dict[str, Any]) -> str | None:
    """What a call runs: its program with its params and inputs, or None for a call that runs no program (parseMesh)."""
    if params.get("source") is None:
        return None
    blob = json.dumps([params.get("source"), params.get("params"), params.get("inputs")], sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


class _Worker:
    def __init__(self, recycle_after: int = 200) -> None:
        self.proc: asyncio.subprocess.Process | None = None
        self.lock = asyncio.Lock()
        self.ids = itertools.count(1)
        self.recycle_after = recycle_after
        self.calls = 0
        # the program (program_key) this worker has run; None while it has run none
        self.program: str | None = None
        self.stderr: deque[str] = deque(maxlen=60)
        self._drain: asyncio.Task | None = None

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
        # an unread stderr pipe would fill up and stall the worker, which reads as a program that is too heavy
        self.stderr.clear()
        self._drain = asyncio.create_task(self._read_stderr(self.proc))
        try:
            line = await asyncio.wait_for(self.proc.stdout.readline(), 30)  # type: ignore[union-attr]
        except (TimeoutError, OSError, ValueError) as e:
            await self.kill()
            log.error("geom worker did not start: %s: %s", type(e).__name__, e)
            raise GeomError("crash", CRASHED) from e
        if b"ready" not in line:
            log.error("geom worker failed to start: %r %s", line[:200], await self._tail())
            await self.kill()
            raise GeomError("crash", CRASHED)

    async def _read_stderr(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stderr
        with contextlib.suppress(Exception):
            while line := await proc.stderr.readline():
                self.stderr.append(line.decode(errors="ignore").rstrip()[:500])

    async def _tail(self) -> str:
        """The last of what the worker said; a worker that closed stdout but lives on must not hold the call up."""
        if self._drain:
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(self._drain), 1)
        return "\n".join(self.stderr)[-1500:]

    async def kill(self) -> None:
        if self.proc and self.proc.returncode is None:
            self.proc.kill()
            await self.proc.wait()
        if self._drain:
            self._drain.cancel()
            self._drain = None
        self.proc = None

    async def call(self, method: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
        # the wait for this worker counts: a caller behind a long fit is told the engine is busy, not left waiting for good
        deadline = asyncio.get_running_loop().time() + timeout
        try:
            await asyncio.wait_for(self.lock.acquire(), timeout)
        except TimeoutError:
            raise GeomError("timeout", f"the geometry engine stayed busy for {timeout:.0f}s") from None
        try:
            return await self._call(method, params, timeout, deadline)
        finally:
            self.lock.release()

    async def _call(self, method: str, params: dict[str, Any], timeout: float, deadline: float) -> dict[str, Any]:
        program = program_key(params)
        # an escaped program can patch this process (stdout, prototypes, timers), so a worker serves one program only
        if self.proc is not None and (self.calls >= self.recycle_after or self.program not in (None, program)):
            await self.kill()
        if self.proc is None or self.proc.returncode is not None:
            await self.start()
            self.calls = 0
            self.program = None
        self.calls += 1
        if program is not None:
            self.program = program
        assert self.proc and self.proc.stdin and self.proc.stdout
        req_id = next(self.ids)
        try:
            self.proc.stdin.write((json.dumps({"id": req_id, "method": method, "params": params}) + "\n").encode())
            await self.proc.stdin.drain()
        except (OSError, RuntimeError) as e:  # the worker died between calls
            log.warning("geom worker: write failed: %s: %s %s", type(e).__name__, e, await self._tail())
            await self.kill()
            raise GeomError("crash", CRASHED) from e
        # A reply to an earlier call whose caller was cancelled may still be in the pipe;
        # without matching ids every later call would get the previous call's result.
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
            except ValueError as e:  # a line past the stream's limit: this reply cannot be read
                log.error("geom worker: unreadable reply: %s", e)
                await self.kill()
                raise GeomError("protocol", OUT_OF_PROTOCOL) from e
            if not line:
                log.warning("geom worker exited during %s: %s", method, await self._tail() or "no output")
                await self.kill()
                raise GeomError("crash", CRASHED)
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                log.warning("geom worker: non-JSON output %r", line[:200])
                continue
            if isinstance(msg, dict) and msg.get("id") == req_id:
                break
            log.warning("geom worker: dropping stale reply id=%r (waiting for %d)", msg.get("id") if isinstance(msg, dict) else None, req_id)
        if "error" in msg:
            err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
            raise GeomError(err.get("stage", "runtime"), err.get("message", ""))
        result = msg.get("result")
        missing = [k for k in EXPECTED.get(method, ()) if not isinstance(result, dict) or k not in result]
        if missing:
            log.warning("geom worker: %s reply has no %s", method, ", ".join(missing))
            await self.kill()
            raise GeomError("protocol", OUT_OF_PROTOCOL)
        return result


class GeomPool:
    def __init__(self, size: int, recycle_after: int = 200) -> None:
        self.workers = [_Worker(recycle_after) for _ in range(max(1, size))]
        self.rr = itertools.cycle(range(len(self.workers)))

    async def call(self, method: str, params: dict[str, Any], timeout: float = 60) -> dict[str, Any]:
        # prefer an idle worker that already runs this program, then any idle one, else round-robin
        program = program_key(params)
        for w in sorted((w for w in self.workers if not w.lock.locked()), key=lambda w: w.program != program):
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
