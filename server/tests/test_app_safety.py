"""API hardening: the SPA fallback stays inside web/build, a restart frees stuck jobs, errors are JSON with a code,
Cyrillic titles export, featured runs and link previews come from real rows only."""
import base64
import re
from pathlib import Path

import httpx
import openai
import pytest

from formwright import app as appmod, db as dbmod, events, quotas, sessions
from formwright.app import BodyLimit, _save_user_version, _spa_file, app, recover_interrupted, share_page
from formwright.config import REPO_DIR, settings
from formwright.printing.service import slug


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    db = await dbmod.get_db()
    await db.insert("users", {"id": "u1", "tier": "anon", "ip": "10.0.0.1", "created_at": dbmod.now()})
    yield db
    await dbmod.close_db()


@pytest.fixture
async def client(fresh_db, monkeypatch):
    # nothing here may reach a model: no key, and a base URL nobody listens on
    monkeypatch.setattr(settings(), "meta_api_key", "")
    monkeypatch.setattr(settings(), "meta_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(settings(), "open_base_url", "")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies={sessions.COOKIE: await sessions.issue("u1")}) as c:
        yield c


async def _project(db, pid: str = "p1", **fields) -> None:
    t = dbmod.now()
    await db.insert("projects", {"id": pid, "user_id": "u1", "title": "Bench", "pack": "household", "created_at": t, "updated_at": t, **fields})


def _is_error(r: httpx.Response, status: int) -> dict:
    assert r.status_code == status, r.text
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["code"] and "detail" in body
    return body


# ------------------------------------------------------------------ SPA fallback
def test_spa_fallback_never_leaves_the_build(tmp_path):
    root = (tmp_path / "web" / "build").resolve()
    (root / "_app").mkdir(parents=True)
    (root / "index.html").write_text("<html></html>")
    (root / "favicon.svg").write_text("<svg/>")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "formwright.db").write_bytes(b"SQLite format 3\0")
    (tmp_path / ".env").write_text("META_KEY=secret")
    (tmp_path / "x").write_text("x")
    index = root / "index.html"
    for path in ["../../data/formwright.db", "../../.env", "../.env", "..\\..\\x", "..\\..\\.env", "C:/Windows/win.ini", "/etc/passwd",
                 str(tmp_path / ".env"), "_app", "_app/../../../x", "nope.js", "a\x00b", ""]:
        assert _spa_file(root, path) == index, path
    assert _spa_file(root, "favicon.svg") == root / "favicon.svg"


# ------------------------------------------------------------------ startup recovery
async def test_restart_fails_stuck_jobs_and_frees_projects(fresh_db):
    db = fresh_db
    t = dbmod.now()
    await _project(db, "p1", status="working", brief={"turns": ["a bench"]})
    await _project(db, "p2", status="working", replay_of="p_src")
    await _project(db, "p3")
    await db.insert("jobs", {"id": "j_run", "project_id": "p1", "user_id": "u1", "kind": "design", "status": "running",
                             "input": {"text": "make it longer"}, "reserved_usd": 0.6, "created_at": t})
    await db.insert("jobs", {"id": "j_wait", "project_id": "p3", "user_id": "u1", "kind": "slice", "status": "waiting", "cost_usd": 0.01, "created_at": t})
    await db.insert("jobs", {"id": "j_done", "project_id": "p3", "user_id": "u1", "kind": "design", "status": "done", "created_at": t, "finished_at": t})

    assert await recover_interrupted() == 2

    jobs = {j["id"]: j for j in await db.all("SELECT * FROM jobs")}
    assert jobs["j_run"]["status"] == jobs["j_wait"]["status"] == "failed"
    assert jobs["j_run"]["finished_at"] and jobs["j_run"]["result"]["summary"] == "interrupted: the server restarted"
    assert jobs["j_wait"]["result"]["cost"]["usd"] == 0.01
    assert jobs["j_done"]["status"] == "done"
    assert {p["status"] for p in await db.all("SELECT status FROM projects")} == {"idle"}
    brief = (await db.one("SELECT brief FROM projects WHERE id = 'p1'"))["brief"]
    assert brief["turns"] == ["a bench", "make it longer (interrupted: failed)"]
    finished = [e for e in await events.since("p1", 0) + await events.since("p3", 0) if e["type"] == "job.finished"]
    assert sorted(e["data"]["job_id"] for e in finished) == ["j_run", "j_wait"]
    assert all(e["data"]["status"] == "failed" for e in finished)
    assert await recover_interrupted() == 0


# ------------------------------------------------------------------ JSON errors
async def test_quota_errors_are_json_with_a_code(client, fresh_db, monkeypatch):
    db = fresh_db
    await _project(db, "p1")
    await db.insert("jobs", {"id": "j_other", "project_id": "p1", "user_id": "u1", "kind": "design", "status": "running", "created_at": dbmod.now()})
    # also blocked once an orphaned row no longer counts: today's demo budget is gone
    monkeypatch.setattr(settings(), "daily_budget_usd", 0.0)
    for path, body in [("slice", {}), ("probe", {}), ("concepts", {"prompt": "a bench"})]:
        r = await client.post(f"/api/projects/p1/{path}", json=body)
        _is_error(r, 429)
    assert not await db.one("SELECT id FROM jobs WHERE id != 'j_other'")


async def test_quota_error_carries_code_and_info(client, fresh_db, monkeypatch):
    await _project(fresh_db, "p1")

    async def blocked(*_a, **_k):
        e = quotas.QuotaExceeded("another job is still running")
        e.code, e.info = "job_running", {"project_id": "p9", "job_id": "j9"}
        raise e

    monkeypatch.setattr(quotas, "headroom", blocked)
    body = _is_error(await client.post("/api/projects/p1/probe", json={}), 429)
    assert body == {"detail": "another job is still running", "code": "job_running", "project_id": "p9", "job_id": "j9"}


@pytest.mark.parametrize("exc, status, code", [
    (RuntimeError("boom"), 500, "internal"),
    (httpx.ConnectError("refused"), 503, "model_busy"),
    (openai.APITimeoutError(request=httpx.Request("POST", "http://model")), 503, "model_busy"),
])
async def test_unexpected_errors_are_json(client, monkeypatch, exc, status, code):
    async def fail(*_a, **_k):
        raise exc

    monkeypatch.setattr(quotas, "spent_today", fail)
    body = _is_error(await client.get("/api/me"), status)
    assert body["code"] == code
    if code == "internal":
        assert body["detail"] == "internal error" and body["id"].startswith("e_")


async def test_http_and_validation_errors_carry_a_code(client):
    assert _is_error(await client.get("/api/projects/nope"), 404)["code"] == "not_found"
    assert _is_error(await client.post("/api/projects", json={"title": 5}), 422)["code"] == "invalid"


async def test_oversized_body_is_refused_before_parsing():
    sent = []

    async def inner(*_a):
        raise AssertionError("the endpoint must not run")

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "method": "POST", "path": "/api/snap", "headers": [(b"content-length", str(10**9).encode())]}
    await BodyLimit(inner)(scope, None, send)
    assert sent[0]["status"] == 413


# ------------------------------------------------------------------ export, versions
async def test_cyrillic_title_exports(client, fresh_db, monkeypatch):
    db = fresh_db
    await _project(db, "p1", title="Скамейка парковая", version=1)
    await db.insert("programs", {"project_id": "p1", "version": 1, "source": "return {}", "created_at": dbmod.now()})

    class Stub:
        async def export(self, *_a, **_k):
            return {"data": base64.b64encode(b"solid").decode(), "mime": "model/3mf"}

    monkeypatch.setattr(appmod, "geom", lambda: Stub())
    r = await client.post("/api/projects/p1/export", json={"format": "3mf"})
    assert r.status_code == 200 and r.content == b"solid"
    cd = r.headers["content-disposition"]
    assert 'filename="model.3mf"' in cd and "filename*=UTF-8''%D0%A1%D0%BA" in cd
    assert slug("Скамейка парковая") == "skameyka_parkovaya"
    assert slug("Park bench!") == "park_bench" and slug("???") == "model"


async def test_slider_save_takes_the_next_free_version(fresh_db):
    db = fresh_db
    t = dbmod.now()
    await _project(db, "p1", version=1)
    await db.insert("programs", {"project_id": "p1", "version": 1, "source": "a", "author": "agent", "created_at": t})
    prog = await db.one("SELECT * FROM programs WHERE project_id = 'p1' AND version = 1")
    # an agent step committed v2 after the browser read v1
    await db.insert("programs", {"project_id": "p1", "version": 2, "source": "b", "author": "agent", "created_at": t})
    assert await _save_user_version("p1", prog, "a", {"h": 1}, None, "parameters changed", None) == 3
    assert (await db.one("SELECT version FROM projects WHERE id = 'p1'"))["version"] == 3


# ------------------------------------------------------------------ featured runs, gallery
async def test_featured_lists_only_curated_public_originals(client, fresh_db):
    db = fresh_db
    assert (await client.get("/api/featured")).json() == []
    t = dbmod.now()
    await _project(db, "p_owl", title="Owl", public=1, featured=2, version=4, cover="p_owl/renders/v4_iso.png", brief={"summary": "A stylized owl " * 30})
    await _project(db, "p_hook", title="Hook", public=1, featured=1, version=2)
    await _project(db, "p_copy", title="Owl", public=1, featured=3, replay_of="p_owl")
    await _project(db, "p_private", featured=5)
    await _project(db, "p_plain", public=1)
    cost = {"usd": 0.3, "by_model": {"muse-spark-1.3": 0.29, "sam-3.1": 0.01}, "calls_by_model": {"muse-spark-1.3": 12, "sam-3.1": 2}}
    await db.insert("jobs", {"id": "j1", "project_id": "p_owl", "user_id": "u1", "kind": "design", "status": "done", "created_at": t,
                             "finished_at": t + 312.4, "result": {"summary": "ok", "cost": cost}})
    await db.insert("jobs", {"id": "j2", "project_id": "p_owl", "user_id": "u1", "kind": "slice", "status": "done", "created_at": t + 400,
                             "finished_at": t + 410, "result": {"cost": {"by_model": {"muse-spark-1.3": 0.01}, "calls_by_model": {"muse-spark-1.3": 1}}}})
    # an older job without per-model calls: USD per model for the whole project, never mixed units
    await db.insert("jobs", {"id": "j3", "project_id": "p_hook", "user_id": "u1", "kind": "design", "status": "done", "created_at": t,
                             "finished_at": t + 60, "result": {"cost": {"by_model": {"muse-spark-1.3": 0.2}}}})
    await db.insert("jobs", {"id": "j4", "project_id": "p_hook", "user_id": "u1", "kind": "probe", "status": "done", "created_at": t,
                             "finished_at": t + 5, "result": {"cost": {"by_model": {"sam-3.1": 0.01}, "calls_by_model": {"sam-3.1": 1}}}})
    items = (await client.get("/api/featured")).json()
    assert [i["id"] for i in items] == ["p_owl", "p_hook"]
    owl = items[0]
    assert set(owl) == {"id", "title", "cover", "pack", "versions", "summary", "duration_s", "models", "views", "featured"}
    assert owl["cover"] == "/files/p_owl/renders/v4_iso.png" and owl["versions"] == 4 and len(owl["summary"]) == 200
    assert owl["duration_s"] == 312
    assert owl["models"] == {"muse-spark-1.3": 13, "sam-3.1": 2}
    assert items[1]["models"] == {"muse-spark-1.3": 0.2, "sam-3.1": 0.01} and items[1]["duration_s"] == 60
    gallery = {p["id"] for p in (await client.get("/api/gallery")).json()}
    assert gallery == {"p_owl", "p_hook", "p_plain"}


# ------------------------------------------------------------------ link previews
async def test_share_page_fills_previews_for_public_projects(fresh_db):
    db = fresh_db
    template = (REPO_DIR / "web" / "src" / "app.html").read_text(encoding="utf-8")
    await _project(db, "p_pub", title='Owl "Hoot" <b>', public=1, cover="p_pub/renders/v2_iso.png", brief={"summary": "A stylized owl & stand"})
    await _project(db, "p_priv", title="Secret", cover="p_priv/renders/v1_iso.png")

    def meta(page: str, key: str) -> str:
        return re.search(rf'<meta (?:property|name)="{re.escape(key)}" content="([^"]*)"', page).group(1)

    home = await share_page(template, "", "https://fw.example.org")
    assert meta(home, "og:image") == "https://fw.example.org/og.png" and meta(home, "og:title") == "Formwright"
    page = await share_page(template, "r/p_pub", "https://fw.example.org")
    assert meta(page, "og:image") == "https://fw.example.org/files/p_pub/renders/v2_iso.png"
    assert meta(page, "og:title") == "Owl &quot;Hoot&quot; &lt;b&gt;"
    assert meta(page, "og:description") == "A stylized owl &amp; stand"
    assert "<title>Owl &quot;Hoot&quot; &lt;b&gt; · Formwright</title>" in page
    assert meta(await share_page(template, "p/p_pub/", "http://h"), "og:title").startswith("Owl")
    private = await share_page(template, "r/p_priv", "https://fw.example.org")
    assert "Secret" not in private and meta(private, "og:image") == "https://fw.example.org/og.png"


async def test_phone_capture_link_is_absolute_and_tags_uploads(client, fresh_db, monkeypatch):
    await _project(fresh_db, "p1")
    monkeypatch.setattr(settings(), "public_url", "http://localhost:5400")
    assert (await client.post("/api/projects/p1/capture-token")).json()["url"].startswith("/c/p1?t=")
    monkeypatch.setattr(settings(), "public_url", "https://fw.example.org/")
    token = (await client.post("/api/projects/p1/capture-token")).json()
    assert token["url"] == f"https://fw.example.org/c/p1?t={token['token']}"

    from formwright.vision import ingest

    async def fake_ingest(project_id, kind, filename, data, mime):
        row = {"id": "a1", "project_id": project_id, "kind": kind, "path": f"{project_id}/a1.jpg", "mime": mime, "width": 4, "height": 3,
               "meta": {"thumb": f"{project_id}/a1_thumb.jpg"}, "created_at": dbmod.now()}
        await fresh_db.insert("assets", row)
        return row

    monkeypatch.setattr(ingest, "ingest_asset", fake_ingest)
    # the phone has its own session: only the capture token lets it in
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as phone:
        r = await phone.post(f"/api/projects/p1/assets?capture={token['token']}", files={"file": ("a.jpg", b"jpeg", "image/jpeg")}, data={"kind": "photo"})
    assert r.status_code == 200 and r.json()["meta"]["via"] == "phone"
    assert (await fresh_db.one("SELECT meta FROM assets WHERE id = 'a1'"))["meta"]["via"] == "phone"
    added = [e for e in await events.since("p1", 0) if e["type"] == "asset.added"]
    assert added[0]["data"]["meta"]["via"] == "phone"


def test_app_html_has_preview_tags():
    template = (REPO_DIR / "web" / "src" / "app.html").read_text(encoding="utf-8")
    for key in ("description", "og:title", "og:description", "og:image", "twitter:card"):
        assert re.search(rf'<meta (?:property|name)="{re.escape(key)}" content="[^"]+"', template), key
    assert Path(REPO_DIR / "web" / "static" / "og.png").stat().st_size > 10_000
