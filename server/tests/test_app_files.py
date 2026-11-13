"""/files serves a private project's media only to whoever may see it: the owner, the farm's operators, and for a shop
order only what its page shows. Example covers and public projects stay open; traversal stays a 404."""
from __future__ import annotations

import httpx
import pytest

from iamodelize3d import db as dbmod, sessions
from iamodelize3d.app import app
from iamodelize3d.config import settings
from iamodelize3d.shop import store


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    monkeypatch.setattr(settings(), "meta_api_key", "")
    monkeypatch.setattr(settings(), "meta_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(settings(), "open_base_url", "")
    (tmp_path / "files").mkdir(exist_ok=True)
    mount = next(r for r in app.routes if getattr(r, "name", None) == "files")
    monkeypatch.setattr(mount.app, "all_directories", [tmp_path / "files"])
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


def _file(rel: str, body: bytes = b"PRIVATE") -> None:
    path = settings().data_dir / "files" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


async def _project(db, pid: str, uid: str, *, public: bool = False, cover: str | None = None, pack: str = "household") -> None:
    t = dbmod.now()
    if not await db.one("SELECT 1 FROM users WHERE id = ?", uid):
        await db.insert("users", {"id": uid, "tier": "anon", "created_at": t})
    await db.insert("projects", {"id": pid, "user_id": uid, "title": pid, "pack": pack, "public": int(public), "cover": cover,
                                 "created_at": t, "updated_at": t})


async def _client(uid: str | None = None) -> httpx.AsyncClient:
    cookies = {sessions.COOKIE: await sessions.issue(uid)} if uid else {}
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", cookies=cookies)


async def _get(uid: str | None, rel: str) -> int:
    async with await _client(uid) as c:
        return (await c.get(f"/files/{rel}")).status_code


async def _raw(path: str) -> tuple[int, bytes]:
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http", "path": path,
             "raw_path": path.encode(), "root_path": "", "query_string": b"", "headers": [], "server": ("test", 80), "client": ("127.0.0.1", 1)}
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent[0]["status"], b"".join(m.get("body", b"") for m in sent[1:])


async def _order(db, oid: str, uid: str, project_id: str, *, org: str | None = None, qc: dict | None = None) -> None:
    sdb = await store.shop_db()
    t = dbmod.now()
    await sdb.insert("shop_orders", {"id": oid, "ref": oid, "user_id": uid, "org_id": org, "project_id": project_id, "status": "printing",
                                     "qc": qc or {}, "created_at": t, "updated_at": t})


async def test_a_private_projects_files_go_to_its_owner_only(fresh_db):
    await _project(fresh_db, "p_a", "u_a")
    await fresh_db.insert("users", {"id": "u_b", "tier": "anon", "created_at": dbmod.now()})
    _file("p_a/secret.txt")
    assert await _get("u_a", "p_a/secret.txt") == 200
    assert await _get(None, "p_a/secret.txt") == 404  # a new visitor with the URL (it was 200 with the body)
    assert await _get("u_b", "p_a/secret.txt") == 404
    # public projects and example covers stay open
    await _project(fresh_db, "p_pub", "u_a", public=True)
    _file("p_pub/renders/v1.png", b"PNG")
    _file("examples/covers/x.png", b"PNG")
    assert await _get(None, "p_pub/renders/v1.png") == 200
    assert await _get(None, "examples/covers/x.png") == 200
    # traversal from an open folder into a private one, or out of data/files (the SQLite file sits next to it), is a 404
    # (raw ASGI paths, as a client that does not normalise them would send; the server sees them decoded)
    for rel in ("p_pub/../p_a/secret.txt", "examples/../p_a/secret.txt", "p_pub\\..\\p_a\\secret.txt", "../iamodelize3d.db", "p_pub/../../iamodelize3d.db"):
        status, body = await _raw(f"/files/{rel}")
        assert status == 404 and b"PRIVATE" not in body and not body.startswith(b"SQLite"), rel


async def test_shop_orders_see_only_what_their_page_shows(fresh_db):
    # a catalog part: the listing owner's private project, bought by u_buyer
    await _project(fresh_db, "p_part", "u_owner", cover="p_part/renders/v1_iso.png")
    _file("p_part/renders/v1_iso.png", b"PNG")
    _file("p_part/a_plate.jpg", b"RATING PLATE")
    await _project(fresh_db, "p_buyer", "u_buyer")
    await _order(fresh_db, "o_1", "u_buyer", "p_part",
                 qc={"pass": True, "photo_url": "/files/p_ops/a_qc.jpg", "mask_url": "/files/p_ops/a_qc_mask.png"})
    # the farm's QC photos live in the operator's own project
    await _project(fresh_db, "p_ops", "u_op", pack="shop_ops")
    for rel in ("p_ops/a_qc.jpg", "p_ops/a_qc_mask.png", "p_ops/other_qc.jpg"):
        _file(rel, b"QC")
    sdb = await store.shop_db()
    await sdb.insert("shop_orgs", {"id": "org_farm", "name": "Axo", "kind": "farm", "created_at": dbmod.now()})
    await sdb.insert("shop_members", {"org_id": "org_farm", "user_id": "u_op"})

    assert await _get("u_buyer", "p_part/renders/v1_iso.png") == 200  # the order's cover
    assert await _get("u_buyer", "p_part/a_plate.jpg") == 404  # not the owner's photos
    assert await _get("u_buyer", "p_ops/a_qc.jpg") == 200 and await _get("u_buyer", "p_ops/a_qc_mask.png") == 200
    assert await _get("u_buyer", "p_ops/other_qc.jpg") == 404
    await fresh_db.insert("users", {"id": "u_other", "tier": "anon", "created_at": dbmod.now()})
    assert await _get("u_other", "p_ops/a_qc.jpg") == 404
    assert await _get(None, "p_part/renders/v1_iso.png") == 404
    # the operator sees every order's files
    assert await _get("u_op", "p_part/a_plate.jpg") == 200
    # a public catalog card's cover is open; once flagged it is not
    t = dbmod.now()
    await sdb.insert("shop_listings", {"id": "l_1", "project_id": "p_part", "version": 1, "owner_id": "u_owner", "title": "Wheel",
                                       "cover": "p_part/renders/v1_iso.png", "public": 1, "created_at": t, "updated_at": t})
    assert await _get(None, "p_part/renders/v1_iso.png") == 200
    assert await _get(None, "p_part/a_plate.jpg") == 404
    await sdb.update("shop_listings", "id", "l_1", {"flagged": 1})
    assert await _get(None, "p_part/renders/v1_iso.png") == 404


async def test_a_repair_shop_sees_a_colleagues_ordered_project(fresh_db):
    sdb = await store.shop_db()
    await sdb.insert("shop_orgs", {"id": "org_rs", "name": "Fix-it", "kind": "repair_shop", "created_at": dbmod.now()})
    for uid in ("u_1", "u_2"):
        await fresh_db.insert("users", {"id": uid, "tier": "free", "created_at": dbmod.now()})
        await sdb.insert("shop_members", {"org_id": "org_rs", "user_id": uid})
    await _project(fresh_db, "p_1", "u_1")
    _file("p_1/photo.jpg", b"JPG")
    assert await _get("u_2", "p_1/photo.jpg") == 404  # no order: a colleague's other projects stay theirs
    await _order(fresh_db, "o_1", "u_1", "p_1", org="org_rs")
    assert await _get("u_2", "p_1/photo.jpg") == 200


async def test_private_files_stay_out_of_shared_caches(fresh_db):
    """A file only this viewer may read: Cache-Control private, no-store (no proxy keeps it, and the browser does not
    show it again after signing out); public ones keep their default caching (ETag, Last-Modified)."""
    await _project(fresh_db, "p_a", "u_a")
    await _project(fresh_db, "p_pub", "u_a", public=True)
    await _project(fresh_db, "p_ops", "u_op", pack="shop_ops")
    _file("p_a/secret.txt")
    _file("p_pub/renders/v1.png", b"PNG")
    _file("examples/covers/x.png", b"PNG")
    sdb = await store.shop_db()
    await sdb.insert("shop_orgs", {"id": "org_farm", "name": "Axo", "kind": "farm", "created_at": dbmod.now()})
    await sdb.insert("shop_members", {"org_id": "org_farm", "user_id": "u_op"})
    for uid in ("u_a", "u_op"):  # the owner, and the farm's operator
        async with await _client(uid) as c:
            r = await c.get("/files/p_a/secret.txt")
            assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store", uid
            again = await c.get("/files/p_a/secret.txt", headers={"if-none-match": r.headers["etag"]})
            assert again.status_code == 304 and again.headers["cache-control"] == "private, no-store"  # a revalidation too
    for uid, rel in ((None, "p_pub/renders/v1.png"), (None, "examples/covers/x.png"), ("u_a", "p_pub/renders/v1.png")):
        async with await _client(uid) as c:
            r = await c.get(f"/files/{rel}")
            assert r.status_code == 200 and "cache-control" not in r.headers and r.headers.get("etag"), rel


async def test_a_showcase_order_opens_its_cover_and_qc_photo_to_anyone(fresh_db):
    """The farm shows a delivered order to anyone: its project's cover and its QC photo and mask, nothing else of the
    project, and no other order's QC photo."""
    await _project(fresh_db, "p_part", "u_owner", cover="p_part/renders/v1_iso.png")
    await _project(fresh_db, "p_ops", "u_op", pack="shop_ops")
    _file("p_part/renders/v1_iso.png", b"PNG")
    _file("p_part/a_plate.jpg", b"RATING PLATE")
    for rel in ("p_ops/a_qc.jpg", "p_ops/a_qc_mask.png", "p_ops/b_qc.jpg"):
        _file(rel, b"QC")
    sdb = await store.shop_db()
    t = dbmod.now()
    qc = {"pass": True, "photo_url": "/files/p_ops/a_qc.jpg", "mask_url": "/files/p_ops/a_qc_mask.png"}
    await sdb.insert("shop_orders", {"id": "o_show", "ref": "IM-1", "user_id": "u_owner", "project_id": "p_part", "version": 1, "status": "delivered",
                                     "qc": qc, "created_at": t, "updated_at": t})
    await sdb.insert("shop_orders", {"id": "o_other", "ref": "IM-2", "user_id": "u_owner", "project_id": "p_part", "status": "delivered",
                                     "qc": {"pass": True, "photo_url": "/files/p_ops/b_qc.jpg"}, "created_at": t, "updated_at": t})
    assert await _get(None, "p_ops/a_qc.jpg") == 404 and await _get(None, "p_part/renders/v1_iso.png") == 404  # not shown yet
    await sdb.update("shop_orders", "id", "o_show", {"showcase": 1})
    await fresh_db.insert("users", {"id": "u_x", "tier": "anon", "created_at": t})
    for uid in (None, "u_x"):
        assert await _get(uid, "p_ops/a_qc.jpg") == 200 and await _get(uid, "p_ops/a_qc_mask.png") == 200
        assert await _get(uid, "p_part/renders/v1_iso.png") == 200
        assert await _get(uid, "p_part/a_plate.jpg") == 404  # the customer's own photos stay theirs
        assert await _get(uid, "p_ops/b_qc.jpg") == 404  # another order's QC photo
    # an order that is not shipped yet is no showcase even with the flag; switched off, it closes again
    await sdb.update("shop_orders", "id", "o_show", {"status": "qc"})
    assert await _get(None, "p_ops/a_qc.jpg") == 404
    await sdb.update("shop_orders", "id", "o_show", {"status": "delivered", "showcase": 0})
    assert await _get(None, "p_ops/a_qc.jpg") == 404 and await _get(None, "p_part/renders/v1_iso.png") == 404


async def test_a_showcase_opens_the_version_it_printed_not_the_customers_later_one(fresh_db):
    """The customer took the studio project on to v3 after v1 was printed and shipped: the public page shows v1's
    render, and v3 (the project's cover now) and its title stay theirs."""
    from iamodelize3d.shop import routes

    await _project(fresh_db, "p_studio", "u_cust", cover="p_studio/renders/v3_iso.png")
    await fresh_db.execute("UPDATE projects SET version = 3, title = 'Подарок для Айгуль' WHERE id = 'p_studio'")
    for v in (1, 2, 3):
        _file(f"p_studio/renders/v{v}_iso.png", b"PNG")
    sdb = await store.shop_db()
    t = dbmod.now()
    intake = {"request": {"kind": "project"}, "refuse": False, "language": "ru",
              "classify": {"title_en": "Dishwasher basket wheel", "title_ru": "Колёсико корзины посудомойки", "safety_critical": False}}
    await sdb.insert("shop_orders", {"id": "o_show", "ref": "IM-1", "user_id": "u_cust", "project_id": "p_studio", "version": 1,
                                     "status": "delivered", "showcase": 1, "intake": intake, "qc": {"pass": True}, "created_at": t, "updated_at": t})
    assert await _get(None, "p_studio/renders/v1_iso.png") == 200
    assert await _get(None, "p_studio/renders/v3_iso.png") == 404 and await _get(None, "p_studio/renders/v2_iso.png") == 404
    await store.log(sdb, "o_show", "requested", "requested", "system", None, code="intake_read",
                    params={"model": "spark", "title": "Подарок для Айгуль", "title_en": "Gift for Aigul", "title_ru": "Подарок для Айгуль"})
    view = await routes.public_view(sdb, await store.get(sdb, "o_show"))
    assert view["project"] == {"cover": "/files/p_studio/renders/v1_iso.png", "version": 1} and view["version"] == 1
    assert (view["title_en"], view["title_ru"], view["title"]) == ("Dishwasher basket wheel", "Колёсико корзины посудомойки", "Колёсико корзины посудомойки")
    assert "Айгуль" not in str(view) and "Aigul" not in str(view) and view["listing_id"] is None
    # the project made public by its owner: the page can link to how it was designed
    await fresh_db.execute("UPDATE projects SET public = 1 WHERE id = 'p_studio'")
    assert (await routes.public_view(sdb, await store.get(sdb, "o_show")))["project"]["id"] == "p_studio"


async def test_a_catalog_buyer_opens_the_cards_picture_not_the_owners_later_cover(fresh_db):
    """A buyer of someone's public card (anyone, no payment needed) gets the card's picture and the render of the
    version it prints, not the project's cover after the owner went on to a private v2 (wave-6 security review)."""
    await _project(fresh_db, "p_part", "u_owner", cover="p_part/renders/v2_iso.png")
    await fresh_db.execute("UPDATE projects SET version = 2 WHERE id = 'p_part'")
    for v in (1, 2):
        _file(f"p_part/renders/v{v}_iso.png", b"PNG")
    await fresh_db.insert("users", {"id": "u_buyer", "tier": "anon", "created_at": dbmod.now()})
    sdb = await store.shop_db()
    t = dbmod.now()
    await sdb.insert("shop_listings", {"id": "l_1", "project_id": "p_part", "version": 1, "owner_id": "u_owner", "title": "Wheel",
                                       "cover": "p_part/renders/v1_iso.png", "public": 1, "created_at": t, "updated_at": t})
    await sdb.insert("shop_orders", {"id": "o_b", "ref": "IM-9", "user_id": "u_buyer", "project_id": "p_part", "version": 1, "listing_id": "l_1",
                                     "status": "cancelled", "created_at": t, "updated_at": t})
    assert await _get("u_buyer", "p_part/renders/v2_iso.png") == 404  # was 200, also after cancelling
    assert await _get("u_buyer", "p_part/renders/v1_iso.png") == 200
    await sdb.update("shop_listings", "id", "l_1", {"flagged": 1})  # taken down later: the buyer's own order still shows it
    assert await _get(None, "p_part/renders/v1_iso.png") == 404 and await _get("u_buyer", "p_part/renders/v1_iso.png") == 200
    assert await _get("u_owner", "p_part/renders/v2_iso.png") == 200


async def test_files_are_served_as_their_type_and_an_svg_runs_nothing(fresh_db):
    _file("examples/pcb/board/pcb_top.svg", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    _file("examples/covers/x.png", b"PNG")
    async with await _client() as c:
        svg = await c.get("/files/examples/pcb/board/pcb_top.svg")
        assert svg.status_code == 200 and svg.headers["x-content-type-options"] == "nosniff"
        assert svg.headers["content-security-policy"] == "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
        png = await c.get("/files/examples/covers/x.png")
        assert png.headers["x-content-type-options"] == "nosniff" and "content-security-policy" not in png.headers
