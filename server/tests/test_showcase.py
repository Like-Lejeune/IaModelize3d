"""Home page examples: every one builds and prints cleanly, and opening one gives a ready project without an agent run."""
from __future__ import annotations

import math
import os
import subprocess
import sys

import httpx
import pytest

from formwright import db as dbmod
from formwright import geom as geommod
from formwright import pcb as pcbmod
from formwright import pcb_store, showcase
from formwright.config import REPO_DIR, settings

HAVE_PCB = (pcbmod.dist_dir() / pcbmod.WORKER).exists()
needs_bundle = pytest.mark.skipif(not HAVE_PCB, reason="run `npm ci --ignore-scripts && npm run bundle` in packages/pcb")
# what the home page lists: everything but the PCB example when the PCB worker is not built
SHOWN = [e["key"] for e in showcase.EXAMPLES if HAVE_PCB or not e.get("circuit")]


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()
    if geommod._pool:
        await geommod._pool.close()
        geommod._pool = None
    await pcbmod.close()


@pytest.fixture
async def client(fresh_db):
    from formwright.app import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.parametrize("key", [pytest.param(e["key"], marks=needs_bundle) if e.get("circuit") else e["key"] for e in showcase.EXAMPLES])
async def test_example_builds_without_errors(fresh_db, key):
    ready = await showcase.prepared(showcase.BY_KEY[key])
    assert ready, "the example must build"
    # examples open green ('Ready to print'): no errors and no warnings, only notes
    assert ready["checks"]["ok"]
    warned = [i["message"] for i in ready["checks"]["issues"] if i["severity"] != "info"]
    intro = showcase.BY_KEY[key].get("intro")
    if intro and warned:  # a device example is a run as it ended: its opening message says what the print check still warns about
        assert "print check" in intro["en"] and "Проверка печати" in intro["ru"]
    else:
        assert warned == []
    stats = ready["checks"]["stats"]
    assert stats["volume"] > 500
    assert stats["layers"] == math.ceil(stats["size"][2] / 0.2 - 1e-6)
    # cached: the second call reads the files instead of building again
    assert await showcase.prepared(showcase.BY_KEY[key]) == ready


async def test_a_device_example_opens_as_the_finished_run_with_its_numbers(client):
    # the cards under the device mode: a kept run opens in the device studio with its document, board and case, nothing spent
    devices = [e for e in showcase.EXAMPLES if e["pack"] == "device"]
    assert [e["key"] for e in devices] == ["device-weather", "device-timer", "device-soil", "device-night", "device-leak", "device-dice", "device-keypad"]
    for ex in devices:
        run = showcase._device_run(ex["device"])
        p = (await client.post(f"/api/examples/{ex['key']}", json={"lang": "en"})).json()
        assert p["pack"] == "device" and p["version"] == run["program"]["version"] and p["cover"]
        d = (await client.get(f"/api/projects/{p['id']}")).json()
        assert d["program"]["source"] == run["program"]["source"] and d["job"] is None
        assert [m["text"] for m in d["messages"]] == [ex["prompt"]["en"], ex["intro"]["en"]]
        s = (await client.get(f"/api/projects/{p['id']}/device")).json()
        assert s["version"] == run["doc"]["version"] and len(s["doc"]["nodes"]) == len(run["doc"]["doc"]["nodes"])
        assert s["pcb"]["version"] == run["pcb"]["version"] and s["pcb"]["ok"] and not s["pcb"]["stale"]
        assert (s["doc"]["firmware"] or {}).get("check", {}).get("ok")
        # the case still names the board it was made for
        assert run["pcb"]["version"] == int(run["program"]["inputs"]["boards"]["board"]["source"]["pcb_job"].removeprefix("pcb:v"))
        names = {v["version"]: v["artifacts"] for v in (await client.get(f"/api/projects/{p['id']}/pcb")).json()}
        assert "board.glb" in names[run["pcb"]["version"]]


async def test_opening_an_example_gives_a_ready_project(client):
    listed = (await client.get("/api/examples")).json()
    assert [e["key"] for e in listed] == SHOWN
    assert all(e["cover"].startswith("/files/examples/") for e in listed)

    r = await client.post("/api/examples/phone-stand", json={"lang": "ru"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["title"] == "Подставка для телефона" and p["version"] == 1 and p["cover"]

    d = (await client.get(f"/api/projects/{p['id']}")).json()
    assert d["program"]["source"] == showcase.PHONE_STAND
    assert d["program"]["params"]["angle"] == 68
    assert [m["role"] for m in d["messages"]] == ["user", "agent"]
    assert d["job"] is None  # nothing was spent
    assert (await client.post("/api/examples/nope", json={})).status_code == 404


async def test_the_spare_part_comes_first_with_its_fit_on_the_axle_checked(fresh_db):
    # the first card is what the farm prints for people: a replacement part, its fit measured on the built model
    assert showcase.EXAMPLES[0]["key"] == "rack-wheel"
    ex = showcase.BY_KEY["rack-wheel"]
    assert ex["caption"]["en"].startswith("Replacement part: 25 mm, axle 4 mm, snaps on")
    ready = await showcase.prepared(ex)
    assert ready["params"]["diameter"] == 25 and ready["params"]["axle"] == 4
    fit = ready["fit"]
    # the hole: the wire, a sliding fit and the printer's hole compensation; the neck: narrower than the wire
    assert fit["ok"] and fit["axle"] == 4 and fit["shrink"] == showcase.HOLE_SHRINK
    assert fit["hole"] == pytest.approx(4.4, abs=0.03) and fit["play"] == pytest.approx(0.25, abs=0.03)
    assert fit["neck"] == pytest.approx(3.2, abs=0.02) and fit["grip"] == pytest.approx(0.4, abs=0.01)

    # measured, not read back from the params: a wider clip opening comes out as a wider neck, and one wider than
    # the wire grips nothing, so the opening message falls back to the plain one
    wider = await showcase._axle_fit(ex, {**ready["params"], "clip_open": 3.6})
    assert wider["neck"] == pytest.approx(3.6, abs=0.02) and wider["grip"] == pytest.approx(0.2, abs=0.01) and wider["ok"]
    loose = await showcase._axle_fit(ex, {**ready["params"], "clip_open": 4.4})
    assert loose["grip"] < 0 and not loose["ok"]
    assert showcase.intro(ex, {**ready, "fit": loose}, "en") == showcase.INTRO["en"]


async def test_the_opened_spare_part_says_its_own_numbers(client):
    listed = (await client.get("/api/examples")).json()
    assert listed[0]["key"] == "rack-wheel" and listed[0]["title"]["ru"] == "Колёсико корзины посудомойки"
    assert len(listed) == len(SHOWN) and "shelf-hook" not in SHOWN

    r = await client.post("/api/examples/rack-wheel", json={"lang": "ru"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["title"] == "Колёсико корзины посудомойки" and p["pack"] == "household" and p["cover"]
    d = (await client.get(f"/api/projects/{p['id']}")).json()
    assert d["program"]["source"] == showcase.RACK_WHEEL and d["program"]["checks"]["ok"]
    assert d["job"] is None  # nothing was spent
    msgs = d["messages"]
    assert [m["role"] for m in msgs] == ["user", "agent"] and "4 мм" in msgs[0]["text"]
    ru = msgs[1]["text"]
    assert "25 мм в диаметре и 8 мм шириной" in ru and "проволочной оси 4 мм" in ru
    assert "отверстие под ось 4.39 мм" in ru and "зазором 0.24 мм" in ru and "горловина защёлки 3.20 мм — на 0.40 мм уже" in ru
    assert "PETG" in ru and "Axo" in ru

    en = (await client.post("/api/examples/rack-wheel", json={"lang": "en"})).json()
    msgs = (await client.get(f"/api/projects/{en['id']}")).json()["messages"]
    assert en["title"] == "Dishwasher rack wheel"
    assert msgs[1]["text"].startswith("This is a ready example: a replacement wheel for a dishwasher's lower rack, 25 mm across")
    assert "the axle hole is 4.39 mm" in msgs[1]["text"] and "0.24 mm of play" in msgs[1]["text"]
    assert "the snap neck is 3.20 mm, 0.40 mm narrower than the wire on each side" in msgs[1]["text"]


async def test_the_board_case_comes_checked_against_its_board(fresh_db):
    ex = showcase.BY_KEY["pico-w-case"]
    assert ex["inputs"]["boards"]["board"]["id"] == "rpi-pico-w" and ex["pack"] == "enclosure"
    ready = await showcase.prepared(ex)
    # print layout: base and lid; the case check (C5) is there before any agent run, for the studio's rays
    enc = ready["checks"]["enclosure"]
    assert enc["ok"] and enc["board"] == "board" and enc["version"] == 1 and enc["rays"]
    s = enc["summary"]
    assert s["usb_clearance_mm"] == pytest.approx(0.27, abs=0.05) and s["button_gap_mm"] == pytest.approx(0.3, abs=0.05) and s["snap_strain_pct"] < 2
    assert not [f for f in enc["findings"] if f["severity"] != "info"]
    assert ready["params"]["layout"] == "print" and ready["params"]["show_board"] is False


async def test_the_board_case_builds_even_without_its_inputs(fresh_db):
    # a project whose inputs went missing (opened before app.py stored them): the program's own copy of the board
    from formwright.geom import geom

    built = await geom().build(showcase.PICO_W_CASE, {}, analyze="full")
    assert built["checks"]["ok"] and [p["name"] for p in built["parts"]] == ["base", "lid"]
    ready = await showcase.prepared(showcase.BY_KEY["pico-w-case"])
    assert built["checks"]["stats"]["size"] == ready["checks"]["stats"]["size"]


async def test_the_opened_case_project_carries_its_board(client):
    r = await client.post("/api/examples/pico-w-case", json={"lang": "ru"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["title"] == "Корпус для Pico W"
    d = (await client.get(f"/api/projects/{p['id']}")).json()
    assert d["program"]["checks"]["enclosure"]["ok"]
    assert d["program"]["inputs"]["boards"]["board"]["id"] == "rpi-pico-w"
    # its first message says what was checked against the board, with the numbers
    intro = next(m["text"] for m in d["messages"] if m["role"] == "agent")
    assert "Raspberry Pi Pico W" in intro and "разъёма USB 0." in intro and "BOOTSEL" in intro and "защёлки гнутся на 1." in intro
    en = showcase.intro(showcase.BY_KEY["pico-w-case"], await showcase.prepared(showcase.BY_KEY["pico-w-case"]), "en")
    assert en.startswith("This is a ready example: a snap-fit case checked against the Raspberry Pi Pico W") and "LED window open" in en


@needs_bundle
async def test_the_pcb_example_opens_with_its_routed_board_and_the_case_made_from_it(client, monkeypatch):
    listed = (await client.get("/api/examples")).json()
    card = next(e for e in listed if e["key"] == "xiao-carrier")
    assert card["pack"] == "pcb" and card["title"]["ru"] == "Плата для XIAO ESP32-C3 + корпус" and card["cover"].startswith("/files/examples/")
    assert len([e for e in listed if e["pack"] != "device"]) == 6  # two rows of three on the home page

    # routed once at warm-up: opening only copies the version, so it is instant and never runs the PCB worker
    async def routed_again(*a, **k):
        raise AssertionError("the example was routed again")

    monkeypatch.setattr(pcbmod.PcbPool, "build", routed_again)
    monkeypatch.setattr(pcbmod.PcbPool, "export", routed_again)
    r = await client.post("/api/examples/xiao-carrier", json={"lang": "ru"})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["pack"] == "pcb" and p["version"] == 1 and p["cover"]
    d = (await client.get(f"/api/projects/{p['id']}")).json()
    assert d["job"] is None  # nothing was spent

    # the case: the agent's own case program, around the board.json of PCB v1, checked with rays through its 3 ports
    prog = d["program"]
    assert prog["source"] == showcase.XIAO_CASE and "lib.elec" in prog["source"]
    board = prog["inputs"]["boards"]["board"]
    assert board["source"]["pcb_job"] == "pcb:v1"
    assert sorted(f"{c['id']}:{c['edge']}" for c in board["components"] if c["access"] == "port") == ["J1:-y", "J2:+x", "U1_usb:+y"]
    enc = prog["checks"]["enclosure"]
    assert enc["ok"] and {ray["port"] for ray in enc["rays"]} == {"J1", "J2", "U1_usb"}
    assert enc["summary"]["usb_clearance_mm"] == pytest.approx(0.27, abs=0.05)
    assert prog["checks"]["ok"] and prog["params"]["mockup"] is True and prog["params"]["layout"] == "print"

    # PCB v1: DRC 0, intent met, every artifact served, and the case was made from exactly that board.json
    versions = (await client.get(f"/api/projects/{p['id']}/pcb")).json()
    assert [v["version"] for v in versions] == [1]
    v = versions[0]
    assert v["drc"]["errors"] == 0 and v["intent_ok"] and v["limits_ok"] and v["counts"]["traces"] >= 20
    # no engine notes next to DRC 0 on the card (the button legs and the power path width are right)
    assert v["drc"]["warnings"] == 0
    assert set(v["artifacts"]) == set(pcb_store.ARTIFACTS) - {"device.json"}  # only a device build carries its graph
    for name, url in v["artifacts"].items():
        got = await client.get(url)
        assert got.status_code == 200 and got.content, name
    assert (await client.get(v["artifacts"]["board.json"])).json() == board
    frames = (await client.get(v["artifacts"]["route_frames.json"])).json()
    assert frames["frames"] and frames["svg_map"]["pcb_top.svg"]["matrix"] and frames["glb_map"]["matrix"]
    assert (await client.get(v["artifacts"]["circuit.tsx"])).text == showcase.XIAO_CARRIER
    row = await pcb_store.get(p["id"], 1)
    assert row["checks"]["intent"]["checked"] == 6 and row["intent"]["edge"] == {"J1": "-y", "J2": "+x", "U1": "+y"}

    # the first message says what is there, with the board's own numbers
    msgs = d["messages"]
    assert [m["role"] for m in msgs] == ["user", "agent"]
    assert f"трасс: {v['counts']['traces']}" in msgs[1]["text"] and "«Плата»" in msgs[1]["text"]

    # every visitor gets their own copy
    other = (await client.post("/api/examples/xiao-carrier", json={"lang": "en"})).json()
    assert other["id"] != p["id"]
    mine, theirs = pcb_store.artifact_path(p["id"], 1, "gerbers.zip"), pcb_store.artifact_path(other["id"], 1, "gerbers.zip")
    assert mine != theirs and mine.read_bytes() == theirs.read_bytes()


async def test_without_the_pcb_bundle_the_pcb_card_stays_off(fresh_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "pcb_dir", tmp_path / "no-pcb")
    monkeypatch.setattr(showcase, "_failed", {})
    assert await showcase.prepared(showcase.BY_KEY["xiao-carrier"]) is None
    assert not (tmp_path / "files" / "examples").exists()


@needs_bundle
async def test_a_pcb_example_that_does_not_route_is_not_tried_on_every_visit(fresh_db, monkeypatch):
    calls = []

    async def failing(self, source, **kw):
        calls.append(source)
        return {"ok": False, "errors": [{"type": "pcb_trace_error", "message": "x"}], "intent": {"ok": True, "issues": []}}

    monkeypatch.setattr(pcbmod.PcbPool, "build", failing)
    monkeypatch.setattr(showcase, "_failed", {})
    ex = showcase.BY_KEY["xiao-carrier"]
    assert await showcase.prepared(ex) is None and await showcase.prepared(ex) is None
    assert len(calls) == 1


def test_a_broken_case_module_takes_only_the_board_examples_away():
    env = {**os.environ, "META_API_KEY": "", "META_KEY": "", "FW_META_API_KEY": "", "FW_OPEN_BASE_URL": "", "FW_TELEGRAM_TOKEN": ""}
    code = ("import logging, sys\n"
            "logging.basicConfig(level=logging.ERROR, stream=sys.stdout, format='%(levelname)s %(message)s')\n"
            "sys.modules['formwright.agent.elec_tools'] = None\n"
            "import formwright.app\n"
            "from formwright import showcase\n"
            "print('KEYS', [e['key'] for e in showcase.EXAMPLES])\n")
    r = subprocess.run([sys.executable, "-c", code], cwd=str(REPO_DIR / "server"), env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "ERROR showcase: the electronics modules did not import, the board examples are off" in r.stdout
    assert "KEYS ['rack-wheel', 'lamp-shade', 'soap-dish', 'phone-stand']" in r.stdout
