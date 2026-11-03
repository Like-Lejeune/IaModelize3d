"""PCB versions over HTTP (C8) and their storage (C7), with a fake build: no Node worker needed."""
import json

import httpx
import pytest

from formwright import db as dbmod, events, pcb_store, pcbapi, sessions
from formwright.app import app
from formwright.config import settings

BOARD = {"schema": "fw.board/1", "id": "pcb", "name": "carrier", "source": {"kind": "pcb"}, "frame": "mm",
         "pcb": {"outline": {"kind": "rect", "w": 44, "h": 36}, "thickness": 1.6, "holes": []}, "components": []}
BUILD = {
    "ok": True, "errors": [], "warnings": [{"type": "pcb_trace_warning", "message": "thinner than requested"}], "suppressed": 0,
    "counts": {"components": 11, "nets": 11, "connections": 25, "traces": 23, "vias": 13}, "board": BOARD,
    "circuit_json": [{"type": "pcb_board", "width": 44, "height": 36}], "intent": {"ok": True, "issues": [], "checked": 6},
    "limits": {"ok": True, "issues": []}, "frames": [{"lines": [[0, 0, 1, 1]], "progress": 1}], "meta": {"intent": {"edge": {"J1": "-y"}}}, "ms": 3500,
}
EXPORT = {
    "files": {"gerbers.zip": b"PK\x03\x04zip", "board.glb": b"glTF....", "bom.csv": "Comment,Designator\n", "cpl.csv": "Designator\n",
              "pcb_top.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>", "pcb_bottom.svg": "<svg/>", "schematic.svg": "<svg/>",
              "evil.sh": "rm -rf /"},
    "layers": ["board.GTL"], "svg_map": {"pcb_top.svg": {"matrix": [20, 0, 0, -20, 25, 765]}}, "glb_map": {"matrix": []},
}


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    db = await dbmod.get_db()
    t = dbmod.now()
    for uid in ("u1", "u2"):
        await db.insert("users", {"id": uid, "tier": "anon", "ip": "10.0.0.1", "created_at": t})
    await db.insert("projects", {"id": "p1", "user_id": "u1", "title": "Carrier", "pack": "pcb", "created_at": t, "updated_at": t})
    await db.insert("projects", {"id": "p2", "user_id": "u1", "title": "Shared", "pack": "pcb", "public": 1, "created_at": t, "updated_at": t})
    yield db
    await dbmod.close_db()


async def _client(uid: str = "u1") -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test", cookies={sessions.COOKIE: await sessions.issue(uid)})


async def test_save_writes_a_version_with_its_files(fresh_db, tmp_path):
    v1 = await pcb_store.save("p1", source="export default () => <board />", intent=None, build=BUILD, files=EXPORT)
    v2 = await pcb_store.save("p1", source="v2", intent={"gpio": {}}, build=BUILD, files=EXPORT["files"])
    assert (v1, v2) == (1, 2)
    row = await pcb_store.get("p1")
    assert row["version"] == 2 and row["source"] == "v2" and row["intent"] == {"gpio": {}}
    first = await pcb_store.get("p1", 1)
    assert first["intent"] == {"edge": {"J1": "-y"}}  # taken from the circuit's meta when not given
    assert "evil.sh" not in first["artifacts"] and set(first["artifacts"]) <= (set(pcb_store.ARTIFACTS) - {"device.json"})
    board = json.loads(pcb_store.artifact_path("p1", 1, "board.json").read_text())
    assert board["source"] == {"kind": "pcb", "pcb_job": "pcb:v1"}
    frames = json.loads(pcb_store.artifact_path("p1", 1, "route_frames.json").read_text())
    assert frames["total"] == 1 and frames["board"] == {"w": 44, "h": 36} and frames["svg_map"]["pcb_top.svg"]["matrix"]
    assert pcb_store.artifact_path("p1", 1, "gerbers.zip").read_bytes() == b"PK\x03\x04zip"
    assert pcb_store.artifact_path("p1", 1, "../formwright.db") is None
    assert pcb_store.artifact_path("..", 1, "board.json") is None
    assert [r["version"] for r in await pcb_store.versions("p1")] == [1, 2]
    assert await pcb_store.get("p1", 9) is None and await pcb_store.versions("nope") == []



async def test_a_version_packed_elsewhere_is_added_under_its_new_number(fresh_db):
    # the home page's PCB example is packed once (as v1) and added to every project opened from it
    packed = pcb_store.pack(source="example", intent=None, build=BUILD, files=EXPORT)
    assert set(packed["files"]) == (set(pcb_store.ARTIFACTS) - {"device.json"}) and packed["intent"] == {"edge": {"J1": "-y"}}
    assert json.loads(packed["files"]["board.json"])["source"]["pcb_job"] == "pcb:v1"
    assert await pcb_store.add("p1", packed) == 1
    await pcb_store.save("p1", source="v2", intent=None, build=BUILD, files=EXPORT)
    assert await pcb_store.add("p1", packed) == 3
    row = await pcb_store.get("p1", 3)
    assert row["source"] == "example" and row["checks"] == packed["checks"] and set(row["artifacts"]) == (set(pcb_store.ARTIFACTS) - {"device.json"})
    # board.json names the version it is in here, so a case made from it points at v3
    assert json.loads(pcb_store.artifact_path("p1", 3, "board.json").read_text())["source"]["pcb_job"] == "pcb:v3"
    assert pcb_store.artifact_path("p1", 3, "gerbers.zip").read_bytes() == b"PKzip"
    assert json.loads(packed["files"]["board.json"])["source"]["pcb_job"] == "pcb:v1"  # the packed copy is untouched

async def test_versions_and_artifacts_over_http(fresh_db):
    await pcb_store.save("p1", source="tsx", intent=None, build=BUILD, files=EXPORT)
    async with await _client() as c:
        r = await c.get("/api/projects/p1/pcb")
        assert r.status_code == 200, r.text
        [v] = r.json()
        assert v["version"] == 1 and v["counts"]["traces"] == 23 and v["drc"] == {"errors": 0, "warnings": 1}
        assert v["intent_ok"] is True and v["artifacts"]["gerbers.zip"] == "/api/projects/p1/pcb/1/gerbers.zip"
        r = await c.get(v["artifacts"]["gerbers.zip"])
        assert r.status_code == 200 and r.content == b"PK\x03\x04zip"
        assert r.headers["content-type"] == "application/zip" and "attachment" in r.headers["content-disposition"]
        r = await c.get("/api/projects/p1/pcb/1/pcb_top.svg")
        assert r.headers["content-type"].startswith("image/svg+xml") and "default-src 'none'" in r.headers["content-security-policy"]
        assert r.headers["x-content-type-options"] == "nosniff"
        r = await c.get("/api/projects/p1/pcb/latest/circuit.tsx")
        assert r.status_code == 200 and r.text == "tsx" and r.headers["content-type"].startswith("text/plain")
        assert (await c.get("/api/projects/p1/pcb/1/board.json")).json()["source"]["pcb_job"] == "pcb:v1"


async def test_names_outside_the_list_never_reach_the_disk(fresh_db):
    await pcb_store.save("p1", source="tsx", intent=None, build=BUILD, files=EXPORT)
    async with await _client() as c:
        for path in ("/api/projects/p1/pcb/1/..%2F..%2F..%2Fformwright.db", "/api/projects/p1/pcb/1/..%5Cformwright.db",
                     "/api/projects/p1/pcb/1/evil.sh", "/api/projects/p1/pcb/x/board.json",
                     "/api/projects/p1/pcb/7/board.json", "/api/projects/p1/pcb/-1/board.json"):
            r = await c.get(path)
            assert r.status_code == 404, (path, r.status_code)
            assert r.headers["content-type"].startswith("application/json"), path  # not the SPA's index.html
        assert (await c.get("/api/projects/p9/pcb")).status_code == 404


async def test_access_follows_the_project(fresh_db):
    await pcb_store.save("p1", source="tsx", intent=None, build=BUILD, files=EXPORT)
    await pcb_store.save("p2", source="tsx", intent=None, build=BUILD, files=EXPORT)
    async with await _client("u2") as c:
        assert (await c.get("/api/projects/p1/pcb")).status_code == 403
        assert (await c.get("/api/projects/p1/pcb/1/gerbers.zip")).status_code == 403
        assert (await c.get("/api/projects/p2/pcb")).status_code == 200  # public
        assert (await c.get("/api/projects/p2/pcb/1/schematic.svg")).status_code == 200


async def test_build_version_streams_frames_and_announces_the_version(fresh_db, monkeypatch):
    class FakePool:
        async def build(self, source, *, intent=None, on_frame=None, timeout=None):
            for i in range(3):
                await on_frame({"frame": i, "total": 24, "progress": 0.5 + i / 4, "lines": [[0, 0, i, i]], "w": 44, "h": 36})
            return {**BUILD, "ok": source != "bad", "errors": [] if source != "bad" else [{"type": "x", "message": "m", "hint": None}]}

        async def export(self, circuit_json):
            return EXPORT

    monkeypatch.setattr("formwright.pcb.pool", lambda: FakePool())
    build, version = await pcbapi.build_version("p1", "good", job_id="j1")
    assert build["ok"] and version == 1
    evs = await events.since("p1", 0)
    assert [e["type"] for e in evs] == ["pcb.route"] * 3 + ["pcb.version"]
    assert evs[0]["data"] == {"frame": 0, "total": 24, "lines": [[0, 0, 0, 0]], "progress": 0.5, "w": 44, "h": 36}
    assert evs[-1]["data"]["version"] == 1 and evs[-1]["data"]["drc"] == {"errors": 0, "warnings": 1} and evs[-1]["job_id"] == "j1"
    build, version = await pcbapi.build_version("p1", "bad")
    assert not build["ok"] and version is None and len(await pcb_store.versions("p1")) == 1
