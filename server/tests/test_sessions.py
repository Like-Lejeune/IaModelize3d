"""Who a browser is. The cookie is a random session token, never the user id (a Telegram user's id is easy to guess);
a cookie from before sessions is swapped for one once; a sign-in link works once and only through its page's button;
the per-address cap reads an address a proxy of ours wrote, and anonymous visitors together keep to their share."""
from __future__ import annotations

import asyncio
import importlib.util
import re
import sqlite3

import httpx
import pytest
from starlette.requests import Request

from formwright import db as dbmod, quotas, sessions
from formwright.app import _safe_next, app, client_ip
from formwright.config import SERVER_DIR, settings

JUDGE = "u_judge_0123456789abcdef"


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    # nothing here may reach a model: no key, and a base URL nobody listens on
    monkeypatch.setattr(settings(), "meta_api_key", "")
    monkeypatch.setattr(settings(), "meta_base_url", "http://127.0.0.1:9/v1")
    monkeypatch.setattr(settings(), "open_base_url", "")
    (tmp_path / "files").mkdir(exist_ok=True)
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


def _client(**cookies: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", cookies=cookies)


async def _user(db, uid: str, tier: str = "anon", name: str | None = None, ip: str | None = None) -> dict:
    t = dbmod.now()
    await db.insert("users", {"id": uid, "tier": tier, "name": name, "ip": ip, "created_at": t})
    return await db.one("SELECT * FROM users WHERE id = ?", uid)


async def _me(c: httpx.AsyncClient, **kw) -> str:
    r = await c.get("/api/me", **kw)
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


# ------------------------------------------------------------------ the cookie
async def test_a_user_id_in_the_cookie_signs_nobody_in(fresh_db):
    await _user(fresh_db, "tg_424242", tier="free")
    t = dbmod.now()
    await fresh_db.insert("projects", {"id": "p_victim", "user_id": "tg_424242", "title": "Victim private project", "created_at": t, "updated_at": t})
    for cookies in ({sessions.LEGACY_COOKIE: "tg_424242"}, {sessions.COOKIE: "tg_424242"}):
        async with _client(**cookies) as c:
            assert await _me(c) != "tg_424242"
            assert (await c.get("/api/projects")).json() == []
            assert (await c.get("/api/projects/p_victim")).status_code == 403


async def test_a_new_visitor_gets_an_opaque_session_that_can_be_revoked(fresh_db):
    async with _client() as c:
        uid = await _me(c)
        token = c.cookies[sessions.COOKIE]
        assert uid not in token and sessions.LEGACY_COOKIE not in c.cookies
        assert await _me(c) == uid  # the same person on the next request
    row = await fresh_db.one("SELECT * FROM sessions WHERE user_id = ?", uid)
    assert row and token not in str(row)  # only its digest is stored
    await sessions.revoke(uid)
    async with _client(**{sessions.COOKIE: token}) as c:
        assert await _me(c) != uid


async def test_an_idle_session_is_renewed_once_a_day(fresh_db):
    await _user(fresh_db, "u_idle")
    token = await sessions.issue("u_idle")
    async with _client(**{sessions.COOKIE: token}) as c:
        r = await c.get("/api/me")
        assert r.json()["user_id"] == "u_idle" and "set-cookie" not in r.headers  # fresh: nothing to send
        await fresh_db.execute("UPDATE sessions SET last_seen = last_seen - ?", sessions.TOUCH_S + 1)
        r = await c.get("/api/me")
        assert r.json()["user_id"] == "u_idle" and f"{sessions.COOKIE}={token}" in r.headers["set-cookie"]
        await fresh_db.execute("UPDATE sessions SET expires_at = ?", dbmod.now() - 1)
        assert await _me(c) != "u_idle"  # expired


async def test_a_cookie_from_before_sessions_is_swapped_once(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    monkeypatch.setattr(settings(), "meta_api_key", "")
    (tmp_path / "files").mkdir()
    old = "u_0123456789abcdef"
    # a database from before sessions: its browsers hold fw_uid=<user id>
    con = sqlite3.connect(tmp_path / "formwright.db")
    con.execute("CREATE TABLE users (id TEXT PRIMARY KEY, tier TEXT NOT NULL DEFAULT 'anon', name TEXT, "
                "contributor_consent INTEGER NOT NULL DEFAULT 0, created_at REAL NOT NULL)")
    con.executemany("INSERT INTO users (id, tier, created_at) VALUES (?, ?, 0)", [(old, "anon"), (JUDGE, "pro"), ("tg_77", "free")])
    con.commit()
    con.close()
    await dbmod.close_db()
    db = await dbmod.get_db()
    try:
        await _user(db, "u_fedcba9876543210")  # made after the migration: never had such a cookie
        # a page load sends several requests at once, all with the old cookie: each is that person
        async with _client(**{sessions.LEGACY_COOKIE: old}) as c:
            rs = await asyncio.gather(*(c.get("/api/me") for _ in range(4)))
        assert {r.json()["user_id"] for r in rs} == {old}
        for r in rs:  # each gets a session and drops the old cookie
            cookies = r.headers.get_list("set-cookie")
            assert any(h.startswith(f"{sessions.COOKIE}=") for h in cookies) and any(h.startswith(f'{sessions.LEGACY_COOKIE}=""') for h in cookies)
        token = re.search(rf"{sessions.COOKIE}=([^;]+)", rs[-1].headers["set-cookie"]).group(1)  # type: ignore[union-attr]
        async with _client(**{sessions.COOKIE: token}) as c:
            assert await _me(c) == old  # now by its session
        swapped = (await db.one("SELECT legacy_cookie FROM users WHERE id = ?", old))["legacy_cookie"]
        assert swapped and swapped > 1
        # once the window after the first swap is over, the bare id signs nobody in
        await db.execute("UPDATE users SET legacy_cookie = ? WHERE id = ?", dbmod.now() - sessions.LEGACY_GRACE_S - 1, old)
        for uid in (old, "tg_77", "u_fedcba9876543210"):  # nor does a guessable id, or a user without such a cookie
            async with _client(**{sessions.LEGACY_COOKIE: uid}) as c:
                assert await _me(c) != uid
        # revoking a judge closes the old cookie's way in too
        await sessions.revoke(JUDGE)
        async with _client(**{sessions.LEGACY_COOKIE: JUDGE}) as c:
            assert await _me(c) != JUDGE
    finally:
        await dbmod.close_db()


# ------------------------------------------------------------------ sign-in links
async def _link(db, token: str, uid: str = JUDGE, ttl: float = 3600) -> None:
    await db.insert("logins", {"token": token, "user_id": uid, "expires_at": dbmod.now() + ttl})


def _nonce(page: httpx.Response) -> str:
    return re.search(r'name="nonce" value="([^"]+)"', page.text).group(1)  # type: ignore[union-attr]


async def test_a_sign_in_link_works_once_and_only_by_its_button(fresh_db):
    await _user(fresh_db, JUDGE, tier="pro", name="judge 1")
    await _link(fresh_db, "l_tok")
    async with _client() as c:
        # link previews and mail scanners open the page: nothing is used up, nobody is signed in
        for _ in range(2):
            page = await c.get("/api/login/l_tok?next=/p/p_1")
            assert page.status_code == 200 and "judge 1" in page.text and 'method="post"' in page.text
            assert page.headers["cache-control"] == "no-store" and page.headers["referrer-policy"] == "no-referrer"
        assert await fresh_db.one("SELECT * FROM logins WHERE token = 'l_tok'")
        assert await _me(c) != JUDGE
        nonce = _nonce(page)
        # a form on another site cannot send the page's cookie: it lands on the page again, the link unused
        async with _client() as other:
            r = await other.post("/api/login/l_tok?next=/p/p_1", data={"nonce": nonce})
            assert r.status_code == 303 and r.headers["location"] == "/api/login/l_tok?next=/p/p_1"
        assert await fresh_db.one("SELECT * FROM logins WHERE token = 'l_tok'")
        r = await c.post("/api/login/l_tok?next=/p/p_1", data={"nonce": nonce})
        assert r.status_code == 303 and r.headers["location"] == "/p/p_1"
        assert await _me(c) == JUDGE
    assert await fresh_db.one("SELECT * FROM logins WHERE token = 'l_tok'") is None
    # replayed later (a log, a shared screen): the link is gone, even with a cookie and nonce of one's own
    async with _client(**{"fw_login": "x"}) as c:
        assert (await c.get("/api/login/l_tok")).status_code == 404
        r = await c.post("/api/login/l_tok", data={"nonce": "x"})
        assert r.status_code == 404 and "already used" in r.text
        assert await _me(c) != JUDGE


async def test_two_clicks_on_one_link_sign_in_one_browser(fresh_db):
    await _user(fresh_db, JUDGE, tier="pro")
    await _link(fresh_db, "l_race")
    async with _client() as c:
        nonce = _nonce(await c.get("/api/login/l_race"))
        rs = await asyncio.gather(*(c.post("/api/login/l_race", data={"nonce": nonce}) for _ in range(2)))
    assert sorted(r.status_code for r in rs) == [303, 404]
    assert len(await fresh_db.all("SELECT * FROM sessions WHERE user_id = ?", JUDGE)) == 1


async def test_the_sign_in_page_speaks_russian_and_expired_links_say_so(fresh_db):
    await _user(fresh_db, JUDGE, tier="pro")
    await _link(fresh_db, "l_ru")
    await _link(fresh_db, "l_old", ttl=-1)
    async with _client() as c:
        page = await c.get("/api/login/l_ru", headers={"accept-language": "ru-RU,ru;q=0.9,en;q=0.8"})
        assert "Вход в Formwright" in page.text and 'lang="ru"' in page.text and "Продолжить" in page.text
        gone = await c.get("/api/login/l_old")
        assert gone.status_code == 404 and "expired" in gone.text and 'href="/"' in gone.text


def test_after_sign_in_only_this_site():
    assert _safe_next("/p/p_1?ideas=a%20vase") == "/p/p_1?ideas=a%20vase"
    for bad in ("//evil.example", "/\\evil.example", "https://evil.example", "p/1", "/ x"):
        assert _safe_next(bad) == "/"


def _judge_link():
    spec = importlib.util.spec_from_file_location("judge_link", SERVER_DIR / "scripts" / "judge_link.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


async def test_revoking_judges_signs_their_browsers_out(fresh_db, tmp_path):
    await _user(fresh_db, JUDGE, tier="pro")
    token = await sessions.issue(JUDGE)
    await _link(fresh_db, "l_unused")
    conn = sqlite3.connect(tmp_path / "formwright.db")
    conn.row_factory = sqlite3.Row
    with conn:
        _judge_link().revoke(conn, True)
    conn.close()
    assert (await fresh_db.one("SELECT expires_at FROM logins WHERE token = 'l_unused'"))["expires_at"] <= dbmod.now()
    async with _client(**{sessions.COOKIE: token}) as c:
        assert await _me(c) != JUDGE


# ------------------------------------------------------------------ addresses and the anonymous budget
def _request(xff: str | None, peer: str) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": headers, "client": (peer, 5000)})


def test_the_address_is_one_a_proxy_of_ours_wrote(monkeypatch):
    monkeypatch.setattr(settings(), "proxy_hops", -1)
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    # uvicorn trusting only the proxy (dev.ps1) already resolved it: taken as it is
    assert client_ip(_request("6.6.6.6, 203.0.113.7", peer="203.0.113.7")) == "203.0.113.7"
    # trusting every sender (the container), uvicorn hands over the leftmost entry, which the visitor writes
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    assert client_ip(_request("6.6.6.6, 203.0.113.7", peer="6.6.6.6")) == "203.0.113.7"
    assert client_ip(_request("[2001:db8::5]:443", peer="2001:db8::5")) == "2001:db8::5"
    assert client_ip(_request("198.51.100.4:61000", peer="198.51.100.4")) == "198.51.100.4"
    assert client_ip(_request(None, peer="198.51.100.9")) == "198.51.100.9"  # straight to the API
    monkeypatch.setattr(settings(), "proxy_hops", 2)  # a CDN in front of Caddy
    assert client_ip(_request("6.6.6.6, 203.0.113.7, 172.16.0.1", peer="6.6.6.6")) == "203.0.113.7"
    monkeypatch.setattr(settings(), "proxy_hops", 0)
    assert client_ip(_request("6.6.6.6", peer="6.6.6.6")) == "6.6.6.6"


async def test_a_spoofed_forwarded_for_does_not_make_a_new_address(fresh_db, monkeypatch):
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    monkeypatch.setattr(settings(), "proxy_hops", -1)
    ips = set()
    for i in range(3):
        async with _client() as c:
            uid = await _me(c, headers={"x-forwarded-for": f"10.9.{i}.1, 203.0.113.7"})
        ips.add((await fresh_db.one("SELECT ip FROM users WHERE id = ?", uid))["ip"])
    assert ips == {"203.0.113.7"}


def test_an_ipv6_visitor_counts_as_its_64():
    assert quotas.network("2001:db8:1:2:aaaa::1") == quotas.network("2001:db8:1:2:bbbb::9") == "2001:db8:1:2::/64"
    assert quotas.network("2001:db8:1:3::1") != quotas.network("2001:db8:1:2::1")
    assert quotas.network("::ffff:203.0.113.7") == "203.0.113.7" and quotas.network("203.0.113.7") == "203.0.113.7"
    assert quotas.network("unknown") == "unknown"


async def test_anonymous_visitors_together_keep_to_their_share(fresh_db, monkeypatch):
    monkeypatch.setattr(settings(), "daily_budget_usd", 4.0)
    monkeypatch.setattr(settings(), "anon_budget_share", 0.5)
    # sessions from many addresses, each within its own caps
    for i in range(4):
        await _user(fresh_db, f"u_a{i}", ip=f"10.0.{i}.1")
        await quotas.settle(f"u_a{i}", 0.5)
    with pytest.raises(quotas.QuotaExceeded) as e:
        await quotas.headroom(await _user(fresh_db, "u_next", ip="10.0.9.1"), live=set())
    assert e.value.code == "demo_budget"
    # a judge with a sign-in link still has the rest of the day's budget
    assert await quotas.headroom(await _user(fresh_db, JUDGE, tier="pro"), live=set()) == pytest.approx(2.0)
