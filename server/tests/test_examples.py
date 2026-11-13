"""The designer's few-shot examples must build and print cleanly: no errors and no warnings, only notes. The packs'
own examples too: the Pico W case passes its own check, the carrier board routes with 0 DRC errors and a met intent."""
import pytest

from iamodelize3d.agent import elec_tools, examples, pcb_prompt
from iamodelize3d.config import REPO_DIR
from iamodelize3d.geom import GeomPool
from iamodelize3d.pcb import PcbPool

OUTLINE = {"outlines": {"part": [[[70, 110], [140, 110], [140, 128], [88, 128], [88, 155], [70, 155]]]}}


@pytest.fixture
async def pool():
    p = GeomPool(1)
    yield p
    await p.close()


@pytest.mark.parametrize("name", ["SHELF_HOOK", "COPY_FROM_PHOTO", "LAMP_SHADE", "SMOOTH_BODY"])
async def test_example_builds_without_warnings(pool, name):
    r = await pool.build(getattr(examples, name), {}, analyze="full", inputs=OUTLINE)
    # the agent copies these patterns: an overhang or a thin wall in one would come back in its programs
    assert [f"{i['severity']}: {i['message']}" for i in r["checks"]["issues"] if i["severity"] != "info"] == []
    assert r["checks"]["ok"]
    assert r["checks"]["stats"]["volume"] > 500


def test_pack_examples_sit_in_their_packs():
    from iamodelize3d.agent import device_prompt

    assert set(examples.PACK_EXAMPLES) == {"enclosure", "pcb", "device"}
    assert elec_tools.EXAMPLE in examples.PACK_EXAMPLES["enclosure"] and pcb_prompt.EXAMPLE in examples.PACK_EXAMPLES["pcb"]
    assert examples.PACK_EXAMPLES["device"] == device_prompt.EXAMPLE
    # not in the shared, cached prefix
    assert "lib.elec" not in examples.EXAMPLES_TEXT and "<board" not in examples.EXAMPLES_TEXT


async def test_the_case_example_prints_cleanly_around_a_pico_w(pool):
    inputs = {"boards": {"board": elec_tools.dataset_board("rpi-pico-w")}}
    r = await pool.build(elec_tools.EXAMPLE, {}, analyze="full", inputs=inputs)
    assert [f"{i['severity']}: {i['message']}" for i in r["checks"]["issues"] if i["severity"] != "info"] == []
    assert r["checks"]["ok"] and [p["name"] for p in r["parts"]] == ["base", "lid"]
    out = await pool.inspect(elec_tools.EXAMPLE, r["params"], [{"op": "enclosure", "board": "board"}], inputs=inputs)
    assert [f["msg"] for f in out["results"][0]["findings"] if f["severity"] == "error"] == []


@pytest.mark.skipif(not (REPO_DIR / "packages" / "pcb" / "dist" / "pcb-worker.mjs").exists(), reason="PCB bundle not built")
async def test_the_carrier_example_routes_clean_with_its_intent_met():
    p = PcbPool(1)
    try:
        r = await p.build(pcb_prompt.EXAMPLE)
    finally:
        await p.close()
    assert r["ok"] and r["errors"] == [] and r["limits"]["ok"], r["errors"]
    assert r["intent"]["ok"] and r["intent"]["checked"] == 6 and r["counts"]["traces"] >= 20
    # the comments for the model are the only difference from the engine's own fixture
    fixture = (REPO_DIR / "packages" / "pcb" / "test" / "fixtures" / "carrier.tsx").read_text(encoding="utf-8")
    code = lambda s: [ln for ln in s.splitlines() if not ln.lstrip().startswith("//")]  # noqa: E731
    assert code(pcb_prompt.EXAMPLE) == code(fixture)
