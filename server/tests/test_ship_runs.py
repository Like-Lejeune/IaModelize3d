"""scripts/ship_runs.py: recorded runs travel from one data dir to another (the live server's volume) under the
founder's account there, with their programs, events, jobs, files and PCB versions; importing twice adds nothing, and
an archive cannot write outside the files dir or onto another project's rows. Scratch data dirs only."""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import zipfile

import httpx
import pytest

from iamodelize3d import db as dbmod, pcb_store, sessions, storage
from iamodelize3d.app import app
from iamodelize3d.config import SERVER_DIR, settings

FOUNDER = "u_founder0123456789"
BOARD = {"schema": "fw.board/1", "id": "pcb", "name": "carrier", "source": {"kind": "pcb"}, "frame": "mm",
         "pcb": {"outline": {"kind": "rect", "w": 44, "h": 36}, "thickness": 1.6, "holes": []}, "components": []}
BUILD = {"ok": True, "errors": [], "warnings": [], "suppressed": 0, "counts": {"components": 11, "nets": 11, "traces": 23, "vias": 13},
         "board": BOARD, "circuit_json": [{"type": "pcb_board"}], "intent": {"ok": True, "issues": [], "checked": 6},
         "limits": {"ok": True, "issues": []}, "frames": [{"lines": [[0, 0, 1, 1]], "progress": 1}], "meta": {}, "ms": 3500}
FILES = {"pcb_top.svg": "<svg xmlns='http://www.w3.org/2000/svg'/>", "pcb_bottom.svg": "<svg/>", "schematic.svg": "<svg/>",
         "board.glb": b"glTF....", "gerbers.zip": b"PK\x03\x04zip", "bom.csv": "Comment\n", "cpl.csv": "Designator\n"}


def _ship():
    spec = importlib.util.spec_from_file_location("ship_runs", SERVER_DIR / "scripts" / "ship_runs.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


async def _open(path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", path)
    (path / "files").mkdir(parents=True, exist_ok=True)
    await dbmod.close_db()
    return await dbmod.get_db()


@pytest.fixture
async def dirs(tmp_path, monkeypatch):
    """A recorded PCB run p_run (featured, with a cover shared from examples/) next to a project nobody ships, and an
    empty live data dir where the founder has an account."""
    monkeypatch.setattr(settings(), "meta_api_key", "")
    monkeypatch.setattr(settings(), "meta_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(settings(), "open_base_url", "")
    src, dst = tmp_path / "local", tmp_path / "live"
    db = await _open(src, monkeypatch)
    t = dbmod.now()
    await db.insert("users", {"id": "u_local", "tier": "pro", "created_at": t})
    storage.save_bytes("examples", "covers", "carrier.png", b"\x89PNG cover")
    storage.save_bytes("examples", "covers", "other.png", b"\x89PNG other")
    await db.insert("projects", {"id": "p_run", "user_id": "u_local", "title": "Плата для XIAO", "pack": "pcb", "public": 1, "featured": 3,
                                 "version": 2, "cover": "examples/covers/carrier.png", "brief": {"summary": "carrier + case", "language": "ru"},
                                 "created_at": t - 100, "updated_at": t})
    await db.insert("projects", {"id": "p_not", "user_id": "u_local", "title": "Not shipped", "created_at": t, "updated_at": t})
    for v in (1, 2):
        await db.insert("programs", {"project_id": "p_run", "version": v, "source": f"// case v{v}", "params": {"wall": 2}, "inputs": {},
                                     "summary": f"v{v}", "checks": {"ok": True}, "author": "agent", "created_at": t - 50 + v})
        storage.save_bytes("p_run", "renders", f"v{v}_iso.png", b"\x89PNG v%d" % v)
    await db.insert("programs", {"project_id": "p_not", "version": 1, "source": "//", "created_at": t})
    storage.save_bytes("p_run", "assets", "a1.jpg", b"jpeg")
    storage.save_bytes("p_run", "assets", "a1_thumb.jpg", b"thumb")
    await db.insert("assets", {"id": "a_1", "project_id": "p_run", "kind": "photo", "path": "p_run/assets/a1.jpg", "mime": "image/jpeg",
                               "width": 10, "height": 10, "meta": {"thumb": "p_run/assets/a1_thumb.jpg"}, "created_at": t - 90})
    storage.save_bytes("p_run", "masks", "s1.png", b"mask")
    await db.insert("selections", {"id": "s_1", "project_id": "p_run", "asset_id": "a_1", "role": "target", "name": "board",
                                   "mask_path": "p_run/masks/s1.png", "data": {"kind": "board_scan"}, "created_at": t - 80})
    await db.insert("jobs", {"id": "j_run", "project_id": "p_run", "user_id": "u_local", "kind": "design", "status": "done",
                             "input": {"text": "carrier board"}, "result": {"cost": {"usd": 0.0042, "calls_by_model": {"muse-spark-1.3": 4}}},
                             "cost_usd": 0.0042, "created_at": t - 90, "finished_at": t - 47})
    for i, kind in enumerate(("job.started", "pcb.route", "program.updated", "job.finished")):
        data = {"i": i, "image": "/files/examples/covers/other.png"} if kind == "pcb.route" else {"i": i}
        await db.insert("events", {"project_id": "p_run", "job_id": "j_run", "type": kind, "data": data, "ts": t - 90 + i})
    await db.insert("events", {"project_id": "p_not", "type": "job.started", "data": {}, "ts": t})
    await db.insert("messages", {"id": "m_1", "project_id": "p_run", "role": "agent", "text": "Готово", "data": {}, "created_at": t - 40})
    await pcb_store.save("p_run", source="export default () => <board />", intent=None, build=BUILD, files=FILES)
    db = await _open(dst, monkeypatch)
    await db.insert("users", {"id": FOUNDER, "tier": "pro", "created_at": t})
    await db.insert("users", {"id": "u_two", "tier": "pro", "created_at": t})
    await dbmod.close_db()
    yield src, dst
    await dbmod.close_db()


def _rows(path, sql, *args):
    conn = sqlite3.connect(path / "iamodelize3d.db")
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


def _export(src, out, *ids):
    _ship().main(["export", *ids, "--out", str(out), "--data-dir", str(src)])


def _import(dst, archive, *extra, user=FOUNDER):
    _ship().main(["import", str(archive), "--user", user, "--data-dir", str(dst), *extra])


def _count(dst, table):
    have = _rows(dst, "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", table)
    return _rows(dst, f"SELECT COUNT(*) AS n FROM {table} WHERE project_id = 'p_run'")[0]["n"] if have else 0


async def test_a_run_travels_whole_and_twice_adds_nothing(dirs, tmp_path, monkeypatch, capsys):
    src, dst = dirs
    archive = tmp_path / "runs.zip"
    _export(src, archive, "p_run")
    names = set(zipfile.ZipFile(archive).namelist())
    assert "projects/p_not.json" not in names
    assert {"files/examples/covers/carrier.png", "files/examples/covers/other.png", "files/p_run/assets/a1_thumb.jpg",
            "files/p_run/pcb/v1/gerbers.zip", "files/p_run/renders/v2_iso.png"} <= names

    _import(dst, archive)  # dry run
    assert "would be added" in capsys.readouterr().out
    assert not _rows(dst, "SELECT id FROM projects") and not (dst / "files" / "p_run").exists()

    _import(dst, archive, "--apply")
    p = _rows(dst, "SELECT * FROM projects WHERE id = 'p_run'")[0]
    assert (p["user_id"], p["public"], p["featured"], p["version"], p["title"]) == (FOUNDER, 1, 3, 2, "Плата для XIAO")
    assert _rows(dst, "SELECT user_id FROM jobs") == [{"user_id": FOUNDER}]
    assert [r["type"] for r in _rows(dst, "SELECT type FROM events ORDER BY seq")] == ["job.started", "pcb.route", "program.updated", "job.finished"]
    assert {t: _count(dst, t) for t in ("programs", "messages", "assets", "selections", "pcb_boards")} == \
        {"programs": 2, "messages": 1, "assets": 1, "selections": 1, "pcb_boards": 1}
    for rel in ("p_run/pcb/v1/gerbers.zip", "p_run/masks/s1.png", "examples/covers/carrier.png", "examples/covers/other.png"):
        assert (dst / "files" / rel).read_bytes() == (src / "files" / rel).read_bytes()
    assert not _rows(dst, "SELECT id FROM projects WHERE id = 'p_not'")

    capsys.readouterr()
    _import(dst, archive, "--apply")
    assert "there already" in capsys.readouterr().out
    assert len(_rows(dst, "SELECT seq FROM events")) == 4 and _count(dst, "programs") == 2 and _count(dst, "pcb_boards") == 1

    # the live server reads it as it reads its own runs: the home page card, the studio, the PCB tab
    await _open(dst, monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                 cookies={sessions.COOKIE: await sessions.issue("u_two")}) as c:
        featured = (await c.get("/api/featured")).json()
        assert [(f["id"], f["duration_s"], f["models"]) for f in featured] == [("p_run", 43, {"muse-spark-1.3": 4})]
        detail = (await c.get("/api/projects/p_run")).json()
        assert detail["program"]["version"] == 2 and detail["messages"][0]["text"] == "Готово" and detail["selections"][0]["name"] == "board"
        pcb = (await c.get("/api/projects/p_run/pcb")).json()
        assert [v["version"] for v in pcb] == [1] and "gerbers.zip" in pcb[0]["artifacts"]
        top = await c.get(pcb[0]["artifacts"]["pcb_top.svg"])
        assert top.status_code == 200 and top.text.startswith("<svg")


async def test_replace_overwrites_the_copy_there_without_doubling_it(dirs, tmp_path):
    src, dst = dirs
    archive = tmp_path / "runs.zip"
    _export(src, archive, "p_run")
    _import(dst, archive, "--apply")
    (dst / "files" / "p_run" / "renders" / "v2_iso.png").write_bytes(b"changed there")
    (dst / "files" / "examples" / "covers" / "carrier.png").write_bytes(b"the live server's own cover")
    _import(dst, archive, "--replace", "--apply", user="u_two")
    assert _rows(dst, "SELECT user_id FROM projects WHERE id = 'p_run'") == [{"user_id": "u_two"}]
    assert len(_rows(dst, "SELECT seq FROM events")) == 4 and _count(dst, "programs") == 2 and _count(dst, "jobs") == 1
    # its own files are rewritten; a shared file the live server already has is never overwritten
    assert (dst / "files" / "p_run" / "renders" / "v2_iso.png").read_bytes() == b"\x89PNG v2"
    assert (dst / "files" / "examples" / "covers" / "carrier.png").read_bytes() == b"the live server's own cover"


async def test_featured_export_and_an_unknown_owner(dirs, tmp_path):
    src, dst = dirs
    archive = tmp_path / "featured.zip"
    _export(src, archive, "--featured")
    assert json.loads(zipfile.ZipFile(archive).read("manifest.json"))["projects"][0]["id"] == "p_run"
    with pytest.raises(SystemExit, match="no user u_nobody"):
        _import(dst, archive, "--apply", user="u_nobody")
    assert not _rows(dst, "SELECT id FROM projects")


def _forged(path, manifest_files, doc, extra=None):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": "fw.runs/1", "projects": [{"id": "p_bad", "title": "x", "files": manifest_files}]}))
        z.writestr("projects/p_bad.json", json.dumps(doc))
        for name, data in (extra or {}).items():
            z.writestr(name, data)


async def test_an_archive_cannot_reach_outside_its_project(dirs, tmp_path):
    _, dst = dirs
    evil = tmp_path / "evil.zip"
    _forged(evil, ["../escape.txt"], {"project": {}, "tables": {}}, {"files/../escape.txt": "x"})
    with pytest.raises(SystemExit, match="bad file entry"):
        _import(dst, evil, "--apply")
    assert not (dst / "escape.txt").exists()
    # rows that name another project, a table outside the list and a column the target lacks: rebound or dropped
    doc = {"project": {"id": "p_victim", "user_id": "u_local", "title": "x", "created_at": 1, "updated_at": 1, "nonsense": 1},
           "tables": {"programs": [{"project_id": "p_victim", "version": 1, "source": "//", "created_at": 1}],
                      "users": [{"id": "u_admin", "tier": "pro", "created_at": 1}]}}
    _forged(evil, [], doc)
    _import(dst, evil, "--apply")
    assert _rows(dst, "SELECT id, user_id FROM projects") == [{"id": "p_bad", "user_id": FOUNDER}]
    assert _rows(dst, "SELECT project_id FROM programs") == [{"project_id": "p_bad"}]
    assert not _rows(dst, "SELECT id FROM users WHERE id = 'u_admin'")
