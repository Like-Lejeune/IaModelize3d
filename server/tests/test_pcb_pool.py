"""PcbPool against the real bundle (packages/pcb/dist): the carrier board routes clean, a circuit that hangs is
killed and the next one gets a fresh worker, and the sandbox keeps a circuit off the network and the disk."""
import asyncio
import socket
import time
from pathlib import Path

import pytest

from iamodelize3d import pcb
from iamodelize3d.config import REPO_DIR, settings
from iamodelize3d.pcb import PcbError, PcbPool

DIST = REPO_DIR / "packages" / "pcb" / "dist"
# the home page's XIAO carrier (showcase.XIAO_CARRIER)
CARRIER = (REPO_DIR / "packages" / "pcb" / "test" / "fixtures" / "xiao_carrier.tsx").read_text(encoding="utf-8")
SMALL = 'export default () => (<board width="10mm" height="10mm"><resistor name="R1" resistance="1k" footprint="0603" pcbX={0} pcbY={0} /></board>)'
ESCAPE = "const host = React.createElement.constructor('return globalThis')();\n{body}\nexport default () => (<board width=\"10mm\" height=\"10mm\" />)"

needs_bundle = pytest.mark.skipif(not (DIST / "pcb-worker.mjs").exists(), reason="run `npm ci --ignore-scripts && npm run bundle` in packages/pcb")


@pytest.fixture
async def pool():
    p = PcbPool(1)
    yield p
    await p.close()


async def test_a_missing_bundle_says_how_to_build_it(monkeypatch, tmp_path):
    monkeypatch.setattr(settings(), "pcb_dir", tmp_path)
    p = PcbPool(1)
    with pytest.raises(PcbError) as e:
        await p.build(SMALL)
    assert e.value.stage == "crash" and "npm run bundle" in e.value.message
    assert pcb.render_png("<svg xmlns='http://www.w3.org/2000/svg'/>") is None


@needs_bundle
async def test_carrier_routes_clean_and_exports(pool):
    frames = []

    async def on_frame(f):
        frames.append(f)

    t0 = time.monotonic()
    r = await pool.build(CARRIER, on_frame=on_frame)
    assert time.monotonic() - t0 < 30
    assert r["ok"] and r["errors"] == [] and r["warnings"] == [], (r["errors"], r["warnings"])
    assert r["counts"]["traces"] >= 20 and r["counts"]["components"] == 11
    assert r["intent"] == {"ok": True, "issues": [], "checked": 6} and r["limits"]["ok"]
    ports = sorted(f"{c['id']}:{c['edge']}" for c in r["board"]["components"] if c["access"] == "port")
    assert ports == ["J1:-y", "J2:+x", "U1_usb:+y"]
    # live frames arrive while routing, in the event's shape
    assert frames and {"frame", "total", "lines"} <= set(frames[0]) and len(frames) <= 24
    assert all(len(seg) == 4 for seg in frames[-1]["lines"])

    x = await pool.export(r["circuit_json"])
    files = x["files"]
    assert files["gerbers.zip"][:2] == b"PK" and files["board.glb"][:4] == b"glTF"
    assert isinstance(files["bom.csv"], str) and files["bom.csv"].startswith("Comment,Designator,Footprint,LCSC")
    assert {"pcb_top.svg", "pcb_bottom.svg", "schematic.svg", "cpl.csv"} <= set(files)
    assert len(x["layers"]) == 11 and x["svg_map"]["pcb_top.svg"]["matrix"]

    png = await pcb.render_png_async(files["pcb_top.svg"], 600)
    assert png and png[:4] == b"\x89PNG"


@needs_bundle
async def test_a_hang_is_killed_and_the_next_build_gets_a_fresh_worker(pool):
    # the top level runs under the vm timeout and comes back as a timeout from the worker itself
    with pytest.raises(PcbError) as e:
        await pool.build("while (true) {}\nexport default () => (<board width=\"10mm\" height=\"10mm\" />)")
    assert e.value.stage == "timeout"
    assert pool.workers[0].proc is None  # no worker outlives its build
    # a component function runs inside the reconciler, out of the vm timeout's reach: only the kill stops it
    with pytest.raises(PcbError) as e:
        await pool.build("const Busy = () => { while (true) {} }\nexport default () => (<board width=\"10mm\" height=\"10mm\"><Busy /></board>)", timeout=8)
    assert e.value.stage == "timeout"
    assert pool.workers[0].proc is None
    r = await pool.build(SMALL)
    assert r["ok"]


@needs_bundle
async def test_the_sandbox_keeps_a_circuit_off_the_network_and_the_disk(pool, tmp_path):
    with pytest.raises(PcbError) as e:
        await pool.build(ESCAPE.format(body="host.fetch('https://example.com')"))
    assert "network is disabled" in e.value.message
    with pytest.raises(PcbError) as e:
        await pool.build(ESCAPE.format(body="host.process.getBuiltinModule('net').connect(80, 'example.com')"))
    assert "network is disabled" in e.value.message
    env = str(REPO_DIR.parent / ".env").replace("\\", "/")
    with pytest.raises(PcbError) as e:
        await pool.build(ESCAPE.format(body=f"host.process.getBuiltinModule('fs').readFileSync('{env}', 'utf8')"))
    assert "allow-fs-read" in e.value.message or "ERR_ACCESS_DENIED" in e.value.message
    target = str(tmp_path / "escaped.txt").replace("\\", "/")
    with pytest.raises(PcbError):
        await pool.build(ESCAPE.format(body=f"host.process.getBuiltinModule('fs').writeFileSync('{target}', 'x')"))
    assert not Path(target).exists()
    # the worker never sees the server's keys
    with pytest.raises(PcbError) as e:
        await pool.build(ESCAPE.format(body="throw new Error('ENV:' + Object.keys(host.process.env).join(','))"))
    keys = e.value.message.split("ENV:", 1)[1].split(",")
    assert not [k for k in keys if "KEY" in k.upper() or "TOKEN" in k.upper()]
    # an online footprint is a build error with an offline alternative, not a download
    r = await pool.build(CARRIER.replace('footprint="sod123"', 'footprint="kicad:Diode_SMD/D_SOD-123"'))
    assert not r["ok"] and r["errors"][0]["type"] == "external_footprint_load_error"
    assert "offline" in r["errors"][0]["hint"]
    # a syntax error is a compile error
    with pytest.raises(PcbError) as e:
        await pool.build("export default () => (<board width=\"10mm\"")
    assert e.value.stage == "compile"


@needs_bundle
async def test_cancelling_a_build_kills_the_worker(pool):
    # cancelled while it routes (the first live frame), not after a fixed wait: the carrier routes in about 2 s
    routing = asyncio.Event()

    async def on_frame(f):
        routing.set()

    task = asyncio.create_task(pool.build(CARRIER, on_frame=on_frame))
    await asyncio.wait_for(routing.wait(), 60)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert pool.workers[0].proc is None
    assert (await pool.build(SMALL))["ok"]


@needs_bundle
async def test_udp_and_dns_are_cut_too(pool):
    # dgram.Socket built directly (with its own lookup) never calls createSocket, and resolveTxt is not lookup
    listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    listener.bind(("127.0.0.1", 0))
    listener.settimeout(1.5)
    port = listener.getsockname()[1]
    try:
        send = ("const d = host.process.getBuiltinModule('dgram'); const s = new d.Socket({type: 'udp4', lookup: (a, o, cb) => "
                f"(typeof o === 'function' ? o : cb)(null, a, 4)}}); s.send(host.Buffer.from('leak'), {port}, '127.0.0.1');")
        for body in (send, "host.process.getBuiltinModule('dns').resolveTxt('example.com', () => {});"):
            with pytest.raises(PcbError) as e:
                await pool.build(ESCAPE.format(body=body))
            assert "network is disabled" in e.value.message, e.value.message
        await asyncio.sleep(0.5)
        with pytest.raises(TimeoutError):
            listener.recvfrom(64)  # nothing arrived
    finally:
        listener.close()


@needs_bundle
async def test_a_circuit_cannot_rewrite_a_later_builds_reply(pool):
    # it patches the worker's stdout to rewrite every later build reply; the worker is gone once its build is done
    evil = ("const P = host.process; const w = P.stdout.write.bind(P.stdout); const NL = String.fromCharCode(10);\n"
            "P.stdout.write = (s, ...a) => { try { const m = JSON.parse(String(s)); if (m.result && m.result.counts) "
            "{ m.result.counts.traces = 4242; m.result.meta = {tampered: true}; s = JSON.stringify(m) + NL; } } catch (e) {} return w(s, ...a); };")
    await pool.build(ESCAPE.format(body=evil))
    assert pool.workers[0].proc is None
    r = await pool.build(SMALL)
    assert r["ok"] and r["counts"]["traces"] != 4242 and not (r.get("meta") or {}).get("tampered")


@needs_bundle
async def test_a_build_queued_behind_an_escaped_circuit_gets_a_fresh_worker(pool):
    # two overlapping builds (two users, or a user during the showcase warm-up): the one waiting on the lock must not
    # be handed the process the first circuit patched
    evil = ("const P = host.process; const w = P.stdout.write.bind(P.stdout); const NL = String.fromCharCode(10);\n"
            "P.stdout.write = (s, ...a) => { try { const m = JSON.parse(String(s)); if (m.result && m.result.counts) "
            "{ m.result.counts.traces = 4242; m.result.meta = {tampered: true}; s = JSON.stringify(m) + NL; } } catch (e) {} return w(s, ...a); };")
    starts = []
    orig = pool.workers[0].start

    async def start():
        await orig()
        starts.append(pool.workers[0].proc.pid)

    pool.workers[0].start = start
    _, r = await asyncio.gather(pool.build(ESCAPE.format(body=evil)), pool.build(SMALL))
    assert len(starts) == 2
    assert r["ok"] and r["counts"]["traces"] != 4242 and not (r.get("meta") or {}).get("tampered")
