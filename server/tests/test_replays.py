"""Publishing a run, the replay gallery, the log the browser's player reads, and an admin taking a run down."""
import gzip
import json

import pytest

from formwright import app as appmod, db as dbmod, events
from formwright.config import settings


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


async def run(db, pid, user="u1", status="done", pack="household", **fields):
    t = dbmod.now()
    await db.insert("projects", {"id": pid, "user_id": user, "title": pid, "pack": pack, "created_at": t, "updated_at": t, **fields})
    await db.insert("jobs", {"id": f"j_{pid}", "project_id": pid, "user_id": user, "kind": "design", "status": status, "created_at": t, "finished_at": t + 5})


def gallery_ids(rows):
    return [r["id"] for r in rows]


async def patch(pid, body, user):
    return await appmod.update_project(pid, body, user)


async def test_publishing_has_two_steps_and_closing_the_link_ends_both(fresh_db):
    db = fresh_db
    await run(db, "p1")
    me = {"id": "u1", "tier": "anon"}
    out = await patch("p1", {"public": True}, me)
    assert out["public"] and not out["listed"]
    assert await appmod.replay_gallery() == []  # a link only: not on the gallery
    out = await patch("p1", {"listed": True}, me)
    assert out["public"] and out["listed"]
    assert gallery_ids(await appmod.replay_gallery()) == ["p1"]
    out = await patch("p1", {"public": False}, me)
    assert not out["public"] and not out["listed"]
    assert await appmod.replay_gallery() == []


async def test_listing_at_once_opens_the_link_too(fresh_db):
    db = fresh_db
    await run(db, "p1")
    out = await patch("p1", {"listed": True}, {"id": "u1", "tier": "anon"})
    assert out["public"] and out["listed"]


async def test_the_gallery_shows_only_runs_the_agent_finished(fresh_db):
    db = fresh_db
    await run(db, "good", public=1, listed=1)
    await run(db, "failed", status="failed", public=1, listed=1)
    await run(db, "private", public=0, listed=1)
    await run(db, "copy", public=1, listed=1, replay_of="good")
    await run(db, "refused", public=1, listed=1)
    await events.emit("refused", "job.finished", {"status": "done", "summary": "refused"}, "j_refused")
    assert gallery_ids(await appmod.replay_gallery()) == ["good"]


async def test_the_gallery_filters_and_sorts_with_picked_runs_first(fresh_db):
    db = fresh_db
    t = dbmod.now()
    await run(db, "part", public=1, listed=1, listed_at=t - 30, views=1)
    await run(db, "device", pack="device", public=1, listed=1, listed_at=t - 20, views=9)
    await run(db, "picked", public=1, featured=2, listed_at=t - 40)
    assert gallery_ids(await appmod.replay_gallery()) == ["picked", "device", "part"]
    assert gallery_ids(await appmod.replay_gallery(kind="device")) == ["device"]
    assert gallery_ids(await appmod.replay_gallery(kind="part")) == ["picked", "part"]
    await db.update("projects", "id", "part", {"views": 50})
    assert gallery_ids(await appmod.replay_gallery(sort="popular")) == ["picked", "part", "device"]


async def test_a_person_counts_once_and_the_owner_not_at_all(fresh_db):
    db = fresh_db
    await run(db, "p1", public=1)
    assert (await appmod.replay_viewed("p1", {"id": "u1", "tier": "anon"}))["views"] == 0
    assert (await appmod.replay_viewed("p1", {"id": "u2", "tier": "anon"}))["views"] == 1
    assert (await appmod.replay_viewed("p1", {"id": "u2", "tier": "anon"}))["views"] == 1
    assert (await appmod.replay_viewed("p1", {"id": "u3", "tier": "anon"}))["views"] == 2


async def test_only_an_admin_takes_a_run_down_and_its_owner_cannot_put_it_back(fresh_db):
    db = fresh_db
    await run(db, "p1", public=1, listed=1, featured=1)
    with pytest.raises(appmod.HTTPException) as e:
        await appmod.replay_hide("p1", {"hidden": True}, {"id": "u2", "tier": "anon"})
    assert e.value.status_code == 403
    await appmod.replay_hide("p1", {"hidden": True}, {"id": "root", "tier": "admin"})
    assert await appmod.replay_gallery() == []
    with pytest.raises(appmod.HTTPException):
        await appmod.load_project("p1", {"id": "u2", "tier": "anon"})
    with pytest.raises(appmod.HTTPException) as e:
        await patch("p1", {"public": True}, {"id": "u1", "tier": "anon"})
    assert e.value.detail["code"] == "replay_hidden"
    await appmod.replay_hide("p1", {"hidden": False}, {"id": "root", "tier": "admin"})
    assert (await patch("p1", {"public": True}, {"id": "u1", "tier": "anon"}))["public"]


class Req:
    def __init__(self, encoding=""):
        self.headers = {"accept-encoding": encoding}


async def test_the_log_is_for_those_who_may_read_the_project_and_leaves_out_the_meter(fresh_db):
    db = fresh_db
    await run(db, "p1")
    await events.emit("p1", "job.started", {"kind": "design"}, "j")
    await events.emit("p1", "cost", {"usd": 1.0}, "j")
    await events.emit("p1", "job.heartbeat", {"seconds": 5}, "j")
    await events.emit("p1", "job.finished", {"status": "done"}, "j")
    with pytest.raises(appmod.HTTPException):
        await appmod.replay_log("p1", Req(), {"id": "u2", "tier": "anon"})
    plain = await appmod.replay_log("p1", Req(), {"id": "u1", "tier": "anon"})
    assert [e["type"] for e in json.loads(plain.body)["events"]] == ["job.started", "job.finished"]
    zipped = await appmod.replay_log("p1", Req("gzip, br"), {"id": "u1", "tier": "anon"})
    assert zipped.headers["content-encoding"] == "gzip"
    assert json.loads(gzip.decompress(zipped.body)) == json.loads(plain.body)
    assert isinstance(json.loads(plain.body)["events"][0]["data"], dict)
    await db.update("projects", "id", "p1", {"public": 1})
    assert (await appmod.replay_log("p1", Req(), {"id": "u2", "tier": "anon"})).status_code == 200
    await db.update("projects", "id", "p1", {"public": 0})
    with pytest.raises(appmod.HTTPException):
        await appmod.replay_log("p1", Req(), {"id": "u2", "tier": "anon"})
