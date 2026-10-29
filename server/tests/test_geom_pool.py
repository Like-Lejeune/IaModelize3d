import asyncio
from pathlib import Path

import pytest

from formwright.geom import GeomError, GeomPool

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
