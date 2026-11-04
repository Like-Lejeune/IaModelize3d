import asyncio
import socket
import sys
from pathlib import Path

import pytest

from formwright.geom import GeomError, GeomPool, _Worker

FIXTURES = (Path(__file__).resolve().parents[2] / "packages" / "geom" / "test" / "fixtures.ts").read_text(encoding="utf-8")


def fixture(name: str) -> str:
    start = FIXTURES.index(f"export const {name} = `") + len(f"export const {name} = `")
    return FIXTURES[start : FIXTURES.index("`;", start)]


@pytest.fixture
async def pool():
    p = GeomPool(1)
    yield p
    await p.close()


async def test_build_render_export(pool):
    r = await pool.build(fixture("BAG_HOOK"), {"hook": 40}, analyze="full")
    assert r["ok"] and r["params"]["hook"] == 40
    assert not [i for i in r["checks"]["issues"] if i["severity"] == "error"]
    png = await pool.render(fixture("BAG_HOOK"), {}, view="sheet", tile=160)
    assert len(png["png"]) > 500
    tmf = await pool.export(fixture("BAG_HOOK"), {}, "3mf")
    assert tmf["mime"] == "model/3mf"


async def test_errors_and_sandbox(pool):
    with pytest.raises(GeomError) as e:
        await pool.build("return { build: (p, lib) => lib.std.box([1, 2]) .nope() }")
    assert e.value.stage in ("build", "result")
    # programs cannot reach node APIs
    with pytest.raises(GeomError):
        await pool.build("const fs = require('fs'); return { build: () => null }")
    with pytest.raises(GeomError):
        await pool.build("return { build: () => process.exit(1) }")


async def test_escaped_program_is_contained(pool, tmp_path):
    # A program is untrusted (any user can PUT one). Even the classic realm escape -
    # X.constructor.constructor('return process')() - must not let it touch the host.
    def run(body: str, params: str = "{}") -> str:
        # Wrap so the attempt runs, then surfaces its own error (or 'NO-THROW') as a GeomError.
        return (f"return {{ meta: {{}}, params: {params}, build: (p, lib) => {{ let R = 'NO-THROW'; try {{ {body} }} "
                f"catch (e) {{ R = String(e && e.message || e); }} throw new Error('CONTAINED:' + R); }} }};")

    async def attempt(body: str, params: str = "{}") -> str:
        with pytest.raises(GeomError) as e:
            await pool.build(run(body, params))
        msg = e.value.message
        assert "CONTAINED:" in msg, msg
        return msg.split("CONTAINED:", 1)[1]

    reach = "const proc = SRC.constructor.constructor('return process')();"
    read_path = "C:/Windows/win.ini"  # outside the worker's --allow-fs-read allowlist
    write_path = str(tmp_path / "escaped.txt").replace("\\", "/")

    # (a) params are rebuilt in the program's own realm, so the canonical vector dead-ends there:
    # that realm has no `process` and string codegen is disabled.
    via_p = await attempt("const SRC = p; " + reach + " R = typeof proc;")
    assert "disallowed" in via_p or "process is not defined" in via_p, via_p

    # (b) `lib` and the solids it returns are still host-realm objects, so this vector does reach
    # `process` - but the permission model and the worker's network sever leave it powerless.
    via_lib = await attempt("const SRC = lib; " + reach + " R = typeof proc;")
    assert via_lib == "object", via_lib  # reaches process...

    # ...yet cannot read outside its code, write anywhere, spawn, or open the network:
    assert "allow-fs-read" in await attempt(f"const SRC = lib; {reach} proc.getBuiltinModule('fs').readFileSync('{read_path}', 'utf8');")
    assert "allow-fs-write" in await attempt(f"const SRC = lib; {reach} proc.getBuiltinModule('fs').writeFileSync('{write_path}', 'x');")
    assert not (tmp_path / "escaped.txt").exists()
    # child_process is blocked by the permission model; the worker's sever trips first with its message.
    assert "network disabled" in await attempt(f"const SRC = lib; {reach} proc.getBuiltinModule('child_process').execSync('echo hi');")
    assert "network disabled" in await attempt(f"const SRC = lib; {reach} proc.getBuiltinModule('net').connect(80, 'example.com');")
    assert "network disabled" in await attempt(f"const SRC = lib; {reach} proc.getBuiltinModule('dgram').createSocket('udp4');")
    net_binding = await attempt(f"const SRC = lib; {reach} const b = proc.binding('tcp_wrap'); new b.TCP(b.constants.SOCKET).connect();")
    assert "network" in net_binding, net_binding
    fetch_blocked = await attempt(f"const SRC = lib; {reach} const g = proc.constructor.constructor('return globalThis')(); g.fetch('http://example.com');")
    assert "network disabled" in fetch_blocked, fetch_blocked

    # No API keys are in the worker's environment, so reaching process.env yields nothing.
    env_res = await attempt(f"const SRC = lib; {reach} R = 'keys:' + Object.keys(proc.env).filter(k => /KEY|TOKEN|SECRET/i.test(k)).join(',');")
    assert env_res == "keys:", env_res

    # A normal program is unaffected by any of the above.
    ok = await pool.build("return { meta: {}, params: {}, build: (p, lib) => lib.std.box([10, 10, 10]) }", {}, analyze="full")
    assert ok["ok"] and abs(ok["checks"]["stats"]["volume"] - 1000) < 1e-6


async def test_timeout_kills_worker(pool):
    with pytest.raises(GeomError) as e:
        await pool.call("build", {"source": "return { build: () => { while (true) {} } }"}, timeout=3)
    assert e.value.stage in ("timeout", "build")
    r = await pool.build("return { build: (p, lib) => lib.std.box([10, 10, 10]) }")
    assert r["ok"]


async def test_worker_has_no_secrets(pool):
    import os

    os.environ["META_API_KEY_TEST_LEAK"] = "secret"
    r = await pool.build("const leaked = typeof process === 'undefined' ? '' : JSON.stringify(process.env); "
                         "return { meta: { title: leaked }, params: {}, build: (p, lib) => lib.std.box([1, 1, 1]) }")
    assert "secret" not in r["meta"].get("title", "")


async def test_cancelled_call_does_not_shift_replies(pool):
    # a job stopped mid-build used to leave its reply in the pipe, so the next render got a
    # build result (KeyError: 'png') and the build after it a render result (KeyError: 'params')
    await pool.build(fixture("BAG_HOOK"), {})  # worker is up, so the cancel lands mid-call
    task = asyncio.create_task(pool.build(fixture("BAG_HOOK"), {}, analyze="full"))
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    png = await pool.render(fixture("BAG_HOOK"), {}, view="iso", tile=128)
    assert "png" in png
    r = await pool.build(fixture("BAG_HOOK"), {"hook": 40})
    assert r["params"]["hook"] == 40


async def test_workers_are_recycled_after_n_calls():
    pool = GeomPool(1, recycle_after=2)
    try:
        src = "return { build: (p, lib) => lib.std.box([10, 10, 10]) }"
        await pool.build(src)
        first = pool.workers[0].proc.pid
        await pool.build(src)
        assert pool.workers[0].proc.pid == first
        r = await pool.build(src, analyze="full")  # the third call gets a fresh worker
        assert pool.workers[0].proc.pid != first
        assert r["ok"] and abs(r["checks"]["stats"]["volume"] - 1000) < 1e-6
    finally:
        await pool.close()


async def test_reply_without_its_keys_is_a_protocol_error(monkeypatch):
    # a reply of the wrong shape is the engine's fault, not the program's (the designer retries on 'protocol')
    script = ("import json, sys\n"
              "print(json.dumps({'ready': True}), flush=True)\n"
              "for line in sys.stdin:\n"
              "    print(json.dumps({'id': json.loads(line)['id'], 'result': {'ok': True}}), flush=True)\n")

    async def start(self):
        pipe = asyncio.subprocess.PIPE
        self.proc = await asyncio.create_subprocess_exec(sys.executable, "-c", script, stdin=pipe, stdout=pipe, stderr=pipe)
        await self.proc.stdout.readline()

    monkeypatch.setattr(_Worker, "start", start)
    pool = GeomPool(1)
    try:
        with pytest.raises(GeomError) as e:
            await pool.render("return {}", {}, view="iso")
        assert e.value.stage == "protocol"
        assert pool.workers[0].proc is None  # killed: the next call starts clean
    finally:
        await pool.close()


# an escaped program reaches the worker's `process` through `lib` (see test_escaped_program_is_contained)
REACH = "const proc = lib.constructor.constructor('return process')(); const g = proc.constructor.constructor('return globalThis')();"


def _udp_listener() -> tuple[socket.socket, int]:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    s.settimeout(1.5)
    return s, s.getsockname()[1]


async def test_udp_and_dns_are_cut_too(pool):
    # dgram.Socket built directly (with its own lookup) never calls createSocket, and resolveTxt is not lookup
    listener, port = _udp_listener()
    try:
        send = (f"const d = proc.getBuiltinModule('dgram'); const s = new d.Socket({{type: 'udp4', lookup: (a, o, cb) => "
                f"(typeof o === 'function' ? o : cb)(null, a, 4)}}); s.send(g.Buffer.from('leak'), {port}, '127.0.0.1');")
        for body in (send, "proc.getBuiltinModule('dns').resolveTxt('example.com', () => {});",
                     "proc.getBuiltinModule('dns').promises.resolveMx('example.com');",
                     "new (proc.getBuiltinModule('net').Server)().listen(0);"):
            with pytest.raises(GeomError) as e:
                await pool.build("return { meta: {}, params: {}, build: (p, lib) => { let R = 'NO-THROW'; try { " + REACH + body +
                                 " } catch (e) { R = String(e && e.message || e); } throw new Error('CONTAINED:' + R); } }")
            assert "network disabled" in e.value.message, (body, e.value.message)
        await asyncio.sleep(0.5)
        with pytest.raises(TimeoutError):
            listener.recvfrom(64)  # nothing arrived
    finally:
        listener.close()


async def test_a_program_cannot_rewrite_another_programs_reply(pool):
    # it patches the worker's stdout so every later reply carries its meta; the next program gets a fresh worker
    evil = ("return { meta: {}, params: {}, build: (p, lib) => { " + REACH + " const w = proc.stdout.write.bind(proc.stdout);"
            " proc.stdout.write = (s, ...a) => { try { const m = g.JSON.parse(String(s)); if (m.result && m.result.params) {"
            " m.result.meta = { tampered: true }; s = g.JSON.stringify(m) + '\\n'; } } catch (e) {} return w(s, ...a); };"
            " return lib.std.box([10, 10, 10]); } }")
    await pool.build(evil)
    first = pool.workers[0].proc
    r = await pool.build("return { meta: { title: 'victim' }, params: {}, build: (p, lib) => lib.std.box([5, 5, 5]) }")
    assert r["meta"] == {"title": "victim"}
    assert pool.workers[0].proc is not first
    # the same program again keeps its worker (build, render, export of one version share it)
    src = "return { build: (p, lib) => lib.std.box([10, 10, 10]) }"
    await pool.build(src)
    pid = pool.workers[0].proc.pid
    await pool.render(src, {}, view="iso", tile=64)
    assert pool.workers[0].proc.pid == pid
    await pool.build(src, {"x": 1})  # other params: another program
    assert pool.workers[0].proc.pid != pid
