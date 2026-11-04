"""Add to Axo cart: the owner's version goes to the Axo shop (POST /partner/formwright/designs, answered here through an
httpx MockTransport) with its size, volume, the Orca numbers of a quote that sliced exactly it, a preview and the
studio link to edit it; the answer's add_url comes back, with &replace= when the buyer came back from the cart to edit."""
from __future__ import annotations

import base64
import io
import json
import logging
from email import message_from_bytes
from email.policy import HTTP

import httpx
import pytest
from PIL import Image

from formwright import db as dbmod, sessions
from formwright.app import app
from formwright.config import settings
from formwright.integrations import axo
from formwright.shop import store

KEY = "axo-test-key-not-for-logs"
DESIGN = "0123456789abcdef0123456789abcdef"
OLD = "fedcba9876543210fedcba9876543210"


def _png(side: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (side, side), (200, 210, 190)).save(buf, "PNG")
    return buf.getvalue()


class FakeGeom:
    def __init__(self) -> None:
        self.exported: list[str] = []
        self.rendered = 0

    async def export(self, source, params, fmt, **kw):
        self.exported.append(source)
        return {"data": base64.b64encode(b"PK3mf:" + source.encode()).decode(), "mime": "model/3mf"}

    async def render(self, source, params, **kw):
        self.rendered += 1
        return {"png": base64.b64encode(_png(512)).decode()}

    async def build(self, source, params, **kw):
        return {"checks": {"stats": {"size": [30, 20, 10], "volume": 4200.0}}}


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    monkeypatch.setattr(settings(), "meta_api_key", "")
    monkeypatch.setattr(settings(), "meta_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(settings(), "open_base_url", "")
    monkeypatch.setattr(settings(), "public_url", "https://fw.example/")
    monkeypatch.setattr(settings(), "axo_api_url", "https://axo.example/api/")
    monkeypatch.setattr(settings(), "axo_api_key", KEY)
    (tmp_path / "files").mkdir(exist_ok=True)
    await dbmod.close_db()
    db = await dbmod.get_db()
    t = dbmod.now()
    for uid in ("u_owner", "u_visitor"):
        await db.insert("users", {"id": uid, "tier": "anon", "created_at": t})
    await db.insert("projects", {"id": "p_axo", "user_id": "u_owner", "title": "Shelf bracket", "public": 1, "version": 2, "brief": {},
                                 "created_at": t, "updated_at": t})
    # v1: the agent's, with its checks and its iso render on disk; v2: a slider edit with no stats and no render
    await db.insert("programs", {"project_id": "p_axo", "version": 1, "source": "return lib.box(40,20,8)", "params": {}, "inputs": {},
                                 "checks": {"ok": True, "stats": {"size": [40, 20, 8.004], "volume": 6400.04}}, "author": "agent", "created_at": t})
    await db.insert("programs", {"project_id": "p_axo", "version": 2, "source": "return lib.box(30,20,10)", "params": {"w": 30}, "inputs": {},
                                 "checks": None, "author": "user", "created_at": t + 1})
    render = tmp_path / "files" / "p_axo" / "renders" / "v1_iso.png"
    render.parent.mkdir(parents=True)
    render.write_bytes(_png(512))
    # a Formwright Parts quote sliced v1 on Orca (autoquote stamps the slice with its version); an older one of v1 lacks the stamp
    sdb = await store.shop_db()
    for oid, sl, ts in (("o_new", {"version": 1, "stats": {"grams": 41.19, "minutes": 126.43}}, t + 5),
                        ("o_old", {"stats": {"grams": 99.0, "minutes": 999.0}}, t + 9)):
        await sdb.insert("shop_orders", {"id": oid, "ref": f"FW-{oid}", "user_id": "u_owner", "project_id": "p_axo", "version": 1,
                                         "status": "quoted", "slice": sl, "created_at": ts, "updated_at": ts})
    fake = FakeGeom()
    monkeypatch.setattr(axo, "geom", lambda: fake)
    sent: list[httpx.Request] = []
    answer = {"status": 201, "json": {"design_id": DESIGN, "add_url": f"https://axo.example/builder/formwright?add={DESIGN}", "price_kzt": 4990}}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(answer["status"], json=answer["json"])

    monkeypatch.setattr(axo, "_transport", httpx.MockTransport(handler))
    yield {"db": db, "geom": fake, "sent": sent, "answer": answer}
    await dbmod.close_db()


async def client(uid: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", cookies={sessions.COOKIE: await sessions.issue(uid)})


def parts(request: httpx.Request) -> dict[str, tuple[str | None, str, bytes]]:
    """multipart/form-data -> {name: (filename, content type, bytes)}."""
    raw = b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.read()
    out = {}
    for p in message_from_bytes(raw, policy=HTTP).iter_parts():
        out[p.get_param("name", header="content-disposition")] = (p.get_filename(), p.get_content_type(), p.get_payload(decode=True))
    return out


async def test_owner_sends_a_version_and_gets_the_cart_link(env, caplog):
    caplog.set_level(logging.DEBUG)
    async with await client("u_owner") as c:
        r = await c.post("/api/projects/p_axo/axo-cart", json={"version": 1})
    assert r.status_code == 200, r.text
    assert r.json() == {"url": f"https://axo.example/builder/formwright?add={DESIGN}", "design_id": DESIGN, "price_kzt": 4990}
    (req,) = env["sent"]
    assert str(req.url) == "https://axo.example/api/partner/formwright/designs" and req.method == "POST"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    got = parts(req)
    assert got["meta"][0] is None  # a plain form field, the files beside it
    meta = json.loads(got["meta"][2])
    assert meta == {"external_id": "p_axo:v1", "title": "Shelf bracket", "edit_url": "https://fw.example/p/p_axo",
                    "size_mm": [40.0, 20.0, 8.0], "volume_mm3": 6400.0,
                    # the stamped slice of exactly v1, not the newer unstamped one
                    "weight_g": 41.19, "print_time_min": 126.4}
    assert got["model"][:2] == ("model.3mf", "model/3mf") and got["model"][2] == b"PK3mf:return lib.box(40,20,8)"
    # the agent's saved render of v1: nothing rendered again
    assert got["preview"][:2] == ("preview.png", "image/png") and got["preview"][2].startswith(b"\x89PNG") and env["geom"].rendered == 0
    assert KEY not in caplog.text


async def test_newest_version_by_default_and_replace_goes_on_the_link(env):
    async with await client("u_owner") as c:
        r = await c.post("/api/projects/p_axo/axo-cart", json={"replace": OLD})
    assert r.status_code == 200, r.text
    assert r.json()["url"] == f"https://axo.example/builder/formwright?add={DESIGN}&replace={OLD}"
    meta = json.loads(parts(env["sent"][0])["meta"][2])
    # v2 has no checks (a slider edit): measured by a quick build; no quote sliced it, so Axo estimates from the volume
    assert meta["external_id"] == "p_axo:v2" and meta["size_mm"] == [30.0, 20.0, 10.0] and meta["volume_mm3"] == 4200.0
    assert meta["weight_g"] is None and meta["print_time_min"] is None
    assert env["geom"].exported == ["return lib.box(30,20,10)"]
    # no render saved for v2: one made now from the same program
    assert env["geom"].rendered == 1 and "preview" in parts(env["sent"][0])
    # an empty body is the newest version too
    async with await client("u_owner") as c:
        assert (await c.post("/api/projects/p_axo/axo-cart")).status_code == 200


async def test_not_configured(env, monkeypatch):
    monkeypatch.setattr(settings(), "axo_api_url", "")
    async with await client("u_owner") as c:
        r = await c.post("/api/projects/p_axo/axo-cart", json={})
        me = (await c.get("/api/me")).json()
    assert r.status_code == 503 and r.json()["code"] == "not_configured"
    assert me["axo_cart"] is False and env["sent"] == [] and env["geom"].exported == []
    monkeypatch.setattr(settings(), "axo_api_url", "https://axo.example/api")
    async with await client("u_owner") as c:
        assert (await c.get("/api/me")).json()["axo_cart"] is True


@pytest.mark.parametrize("replace", ["ABCDEF0123456789ABCDEF0123456789", "0123", DESIGN + "0", "../../x", DESIGN[:-1] + "g"])
async def test_bad_replace_is_refused_before_anything_is_sent(env, replace):
    async with await client("u_owner") as c:
        r = await c.post("/api/projects/p_axo/axo-cart", json={"replace": replace})
    assert r.status_code == 400 and r.json()["code"] == "bad_replace"
    assert env["sent"] == [] and env["geom"].exported == []


async def test_only_the_owner_and_only_existing_versions(env):
    async with await client("u_visitor") as c:
        r = await c.post("/api/projects/p_axo/axo-cart", json={})
    assert r.status_code == 403 and env["sent"] == []
    async with await client("u_owner") as c:
        r = await c.post("/api/projects/p_axo/axo-cart", json={"version": 7})
    assert r.status_code == 404 and r.json()["code"] == "no_model"


@pytest.mark.parametrize("status, body, code, ours", [
    (401, {"error": {"code": "unauthorized"}}, "axo_auth", 502),
    (400, {"error": {"code": "bad_meta", "message": "title is empty"}}, "axo_rejected", 422),
    (413, {"error": {"code": "too_large"}}, "axo_too_large", 413),
    (500, {}, "axo_unavailable", 502),
    (201, {"design_id": DESIGN, "add_url": "javascript:alert(1)"}, "axo_unavailable", 502),
])
async def test_axo_errors_come_back_short(env, caplog, status, body, code, ours):
    env["answer"].update(status=status, json=body)
    async with await client("u_owner") as c:
        r = await c.post("/api/projects/p_axo/axo-cart", json={})
    assert r.status_code == ours and r.json()["code"] == code
    if code == "axo_rejected":
        assert r.json()["detail"].endswith("title is empty")
    assert KEY not in caplog.text


async def test_axo_unreachable(env, monkeypatch):
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    monkeypatch.setattr(axo, "_transport", httpx.MockTransport(down))
    async with await client("u_owner") as c:
        r = await c.post("/api/projects/p_axo/axo-cart", json={})
    # Axo's own code, not the model service's 'model_busy' that a bare httpx error gets
    assert r.status_code == 502 and r.json()["code"] == "axo_unavailable"
