"""The designer's pictures (agent/pictures.py): names, the labelled grid and the sheet. The geometry engine is the real one when it
can run: the numbers on a model view have to be the model's real mm. Set FW_PICTURES_OUT to a folder to keep the pictures."""
from __future__ import annotations

import base64
import io
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from formwright import db as dbmod
from formwright import geom as geommod
from formwright import storage
from formwright.agent import narrate, pictures, tools
from formwright.agent.tools import DesignState
from formwright.config import REPO_DIR, settings
from formwright.geom import GeomPool

PID = "p_pictures"
# a block 40 x 20 x 10 mm whose corner is away from the origin, so a wrong sign or offset cannot pass (the engine lands it on z = 0)
BLOCK = """return {
  meta: { name: 'block' }, params: {}, handles: [],
  build(p, lib) { return lib.Manifold.cube([40, 20, 10]).translate([5, 10, 2]); },
};"""


@pytest.fixture
async def ctx(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    await dbmod.get_db()
    yield SimpleNamespace(project_id=PID, project={"title": "t"}, check_cancelled=lambda: None)
    await dbmod.close_db()


def _photo(ctx, name="photo.png", size=(1000, 800)):
    """A dark picture with one bright square at a known place: x 600-700, y 250-350 of the 0-1000 grid."""
    a = np.full((size[1], size[0], 3), 40, np.uint8)
    w, h = size
    a[int(.25 * h):int(.35 * h), int(.6 * w):int(.7 * w)] = (250, 250, 250)
    buf = io.BytesIO()
    Image.fromarray(a).save(buf, "PNG")
    return storage.save_bytes(ctx.project_id, "assets", name, buf.getvalue())


def _named(ctx, state, rel, frames=None):
    if frames:
        pictures.note(state, rel, frames)
    return pictures.enroll(ctx, state, rel, "look")


def _keep(rel, name):
    out = os.environ.get("FW_PICTURES_OUT")
    if out:
        shutil.copy(storage.abs_path(rel), Path(out) / name)


def _img(rel):
    with Image.open(storage.abs_path(rel)) as im:
        return im.convert("RGB")


def _clean_cut(pic):
    img, frames, _, _ = pictures._cut(pic, {})
    return img, frames


async def test_every_picture_gets_a_name_and_a_data_url_a_file(ctx):
    state = DesignState(pack="forms")
    rel = _photo(ctx)
    assert pictures.enroll(ctx, state, rel, "look") == "img1"
    assert pictures.enroll(ctx, state, rel, "look") == "img1"  # the same file, the same name
    url = "data:image/png;base64," + base64.b64encode(storage.abs_path(rel).read_bytes()).decode()
    pictures.note(state, url, clean=rel)
    assert pictures.enroll(ctx, state, url, "look") == "img2"
    kept = state.pictures["img2"]
    assert kept["clean"] == rel and storage.abs_path(kept["rel"]).exists() and not state.picture_notes


async def test_the_grid_numbers_are_the_crop_numbers_of_a_photo(ctx):
    state = DesignState(pack="forms")
    name = _named(ctx, state, _photo(ctx))
    r, images = await pictures.run(ctx, state, "grid", {"image": name})
    assert r["ok"] and r["image"] == "img2" and images == [state.pictures["img2"]["rel"]]
    f = r["frames"][0]
    assert f["x"] == [0, 1000] and f["y"] == [0, 1000] and f["unit"] == "grid" and f["step"] == 100 and f["cells"] == "A1-J10"
    _keep(images[0], "grid_photo.png")
    # lines were drawn; the file it cuts from stays clean
    assert state.pictures["img2"]["clean"] == state.pictures["img1"]["rel"]
    assert (np.asarray(_img(images[0])) != np.asarray(_img(state.pictures["img1"]["rel"]).resize(_img(images[0]).size))).any()


async def test_a_zoom_by_cell_keeps_the_numbers_and_cuts_the_original(ctx):
    state = DesignState(pack="forms")
    rel = _photo(ctx, size=(4000, 3000))
    name = _named(ctx, state, rel)
    r, _ = await pictures.run(ctx, state, "grid", {"image": name})
    # the bright square is at x 600-700, y 250-350: cells G3 and G4
    z, images = await pictures.run(ctx, state, "grid", {"image": r["image"], "region": "G3:G4"})
    assert z["ok"] and z["frames"][0]["x"] == [600, 700] and z["frames"][0]["y"] == [200, 400]
    _keep(images[0], "grid_zoom.png")
    # from the original at full size, no magnifying and none of the first grid's lines
    pic = state.pictures[z["image"]]
    img, frames, view, region = pictures._cut({**pic, "name": z["image"]}, {})
    assert img.size == (400, 600) and frames[0]["h0"] == pytest.approx(600) and region == [600, 200, 700, 400] and view is None
    a = np.asarray(img)
    assert (a[:50, :] == 40).all() and (a[150:450, :] > 200).all()  # y 200-250 dark, y 250-350 the square
    # and a second zoom, by numbers this time
    z2, _ = await pictures.run(ctx, state, "grid", {"image": z["image"], "region": [620, 280, 640, 300]})
    assert z2["frames"][0]["x"] == [620, 640] and z2["frames"][0]["y"] == [280, 300]


async def test_marks_are_drawn_where_the_numbers_say(ctx):
    state = DesignState(pack="forms")
    name = _named(ctx, state, _photo(ctx))
    r, images = await pictures.run(ctx, state, "grid", {"image": name, "marks": [{"at": [300, 500], "label": "hole"}, {"box": [100, 100, 200, 200]}]})
    assert r["ok"]
    a = np.asarray(_img(images[0])).astype(int)
    k = a.shape[1] / 1000
    # the mark's colour on the ring around (300, 500) of the grid
    ring = a[int(.5 * a.shape[0]), int(300 * k + 7 * 1)]
    assert ring[0] > 200 and ring[1] < 120 and ring[2] > 100


async def test_what_cannot_be_done_is_said(ctx):
    state = DesignState(pack="forms")
    name = _named(ctx, state, _photo(ctx))
    r, _ = await pictures.run(ctx, state, "grid", {"image": "img99"})
    assert not r["ok"] and "img1" in r["error"]
    r, _ = await pictures.run(ctx, state, "grid", {"image": name, "region": "C4"})
    assert not r["ok"] and "no grid" in r["error"]
    r, _ = await pictures.run(ctx, state, "grid", {"image": name, "region": [2000, 2000, 3000, 3000]})
    assert not r["ok"] and "outside" in r["error"]
    g, _ = await pictures.run(ctx, state, "grid", {"image": name})
    r, _ = await pictures.run(ctx, state, "grid", {"image": g["image"], "region": "Z9"})
    assert not r["ok"] and "A-J" in r["error"]
    r, _ = await pictures.run(ctx, state, "collage", {"items": []})
    assert not r["ok"]
    r, _ = await pictures.run(ctx, state, "grid", {"image": name, "marks": [{"nowhere": 1}]})
    assert not r["ok"]


async def test_a_collage_is_one_labelled_sheet_and_keeps_the_numbers(ctx):
    state = DesignState(pack="forms")
    a, b = _named(ctx, state, _photo(ctx, "a.png")), _named(ctx, state, _photo(ctx, "b.png", (500, 900)))
    r, images = await pictures.run(ctx, state, "collage", {"grid": True, "items": [
        {"image": a, "label": "whole"}, {"image": b, "region": [500, 200, 800, 400], "label": "the square"}, a]})
    assert r["ok"] and [t["tile"] for t in r["tiles"]] == ["A", "B", "C"]
    assert r["tiles"][1]["frames"][0]["x"] == pytest.approx([500, 800], abs=3)
    _keep(images[0], "collage.png")
    sheet = _img(images[0])
    assert sheet.width <= pictures.SIDE
    # a tile of the sheet can be zoomed by its letter, its numbers are still those of its photo
    z, _ = await pictures.run(ctx, state, "grid", {"image": r["image"], "view": "A", "region": [600, 250, 700, 350]})
    assert z["ok"] and z["frames"][0]["x"] == pytest.approx([600, 700], abs=3)


async def test_past_the_cap_a_turn_shows_a_sheet_not_nothing(ctx):
    state = DesignState(pack="forms")
    images = [("look", _photo(ctx, f"p{i}.png")) for i in range(6)]
    got = pictures.shown(ctx, state, images)
    assert len(got) == pictures.MAX_SHOWN and [g[0] for g in got[:3]] == ["img1", "img2", "img3"]
    assert got[3][1] == "collage of img4, img5, img6" and storage.abs_path(got[3][2]).exists()
    # what fits stays as it was
    assert [g[2] for g in pictures.shown(ctx, DesignState(pack="forms"), images[:4])] == [i[1] for i in images[:4]]


def test_the_tools_are_offered_to_every_pack_and_narrated():
    for pack, kw in (("forms", {}), ("device", {}), ("pcb", {}), ("enclosure", {})):
        names = [t["name"] for t in tools.tools_for(pack, photos=False, prints=False, **kw)]
        assert "grid" in names and "collage" in names, pack
    assert narrate.KIND["grid"] == narrate.KIND["collage"] == "look"
    assert narrate.localize(narrate.call_title("grid", {}), "ru") != narrate.call_title("grid", {})
    assert narrate.localize(narrate.result_title("collage", {}, {"ok": True}), "ru") != narrate.result_title("collage", {}, {"ok": True})


# ---------------------------------------------------------------- the real engine: are the numbers the model's mm?
@pytest.fixture
async def real_geom():
    if not shutil.which("node") or not (REPO_DIR / "packages" / "geom" / "src" / "worker.ts").exists():
        pytest.skip("the geometry engine is not here")
    old = geommod._pool
    geommod._pool = GeomPool(1)
    yield geommod._pool
    await geommod._pool.close()
    geommod._pool = old


async def _sheet(ctx, state, pool, **extra):
    r = await pool.render(BLOCK, {}, view="sheet", **extra)
    rel = storage.save_bytes(ctx.project_id, "renders", f"sheet_{len(state.pictures)}.png", base64.b64decode(r["png"]))
    return _named(ctx, state, rel, r["frames"]), r


def _extent(tile: Image.Image) -> tuple[int, int, int, int]:
    """The drawn block's box in a clean view's pixels, against the sheet's plain background."""
    a = np.asarray(tile).astype(int)
    drawn = (np.abs(a - np.array([246, 246, 243])).sum(axis=2) > 40)
    drawn[:26, :] = False  # the view's name
    drawn[-26:, :] = False  # the scale bar
    ys, xs = np.nonzero(drawn)
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


@pytest.mark.parametrize("view,h,v,want_h,want_v", [
    ("FRONT", "x", "z", (5, 45), (10, 0)),
    ("RIGHT", "y", "z", (10, 30), (10, 0)),
    ("TOP", "x", "y", (5, 45), (30, 10)),
])
async def test_a_straight_view_is_labelled_in_the_models_real_mm(ctx, real_geom, view, h, v, want_h, want_v):
    state = DesignState(pack="forms")
    name, r = await _sheet(ctx, state, real_geom)
    f = next(x for x in pictures._frames(state.pictures[name], (r["width"], r["height"])) if x["name"] == view)
    assert f["h"] == h and f["v"] == v and f["unit"] == "mm"
    img = _img(state.pictures[name]["rel"]).crop(tuple(f["box"][:2]) + (f["box"][0] + f["box"][2], f["box"][1] + f["box"][3]))
    x0, y0, x1, y1 = _extent(img)
    per_px = (f["h1"] - f["h0"]) / f["box"][2], (f["v1"] - f["v0"]) / f["box"][3]
    assert f["h0"] + x0 * per_px[0] == pytest.approx(want_h[0], abs=0.5)
    assert f["h0"] + x1 * per_px[0] == pytest.approx(want_h[1], abs=0.5)
    assert f["v0"] + y0 * per_px[1] == pytest.approx(want_v[0], abs=0.5)
    assert f["v0"] + y1 * per_px[1] == pytest.approx(want_v[1], abs=0.5)
    g, images = await pictures.run(ctx, state, "grid", {"image": name, "view": view})
    assert g["ok"] and g["frames"][0]["unit"] == "mm"
    _keep(images[0], f"grid_{view}.png")


async def test_a_mm_view_zooms_in_mm_and_says_when_it_is_only_magnified(ctx, real_geom):
    state = DesignState(pack="forms")
    name, _ = await _sheet(ctx, state, real_geom)
    r, images = await pictures.run(ctx, state, "grid", {"image": name, "view": "FRONT", "region": [0, 0, 10, 15]})
    assert r["ok"] and r["frames"][0]["x"] == pytest.approx([0, 10], abs=0.2) and r["frames"][0]["z"] == pytest.approx([15, 0], abs=0.2)
    assert "blurry" in r and "look(what='model'" in r["blurry"]
    _keep(images[0], "grid_mm_zoom.png")


async def test_the_whole_sheet_gets_mm_on_its_straight_views_only(ctx, real_geom):
    state = DesignState(pack="forms")
    name, _ = await _sheet(ctx, state, real_geom)
    r, images = await pictures.run(ctx, state, "grid", {"image": name})
    assert r["ok"]
    by_view = {f["view"]: f for f in r["frames"]}
    assert "step" in by_view["FRONT"] and "step" not in by_view["ISO"] and by_view["ISO"]["unit"] == "grid"
    _keep(images[0], "grid_sheet.png")


async def test_an_oblique_close_up_has_no_mm_and_a_straight_one_has(ctx, real_geom):
    state = DesignState(pack="forms")
    name, _ = await _sheet(ctx, state, real_geom, views=[{"azimuth": 0, "elevation": 0, "name": "STRAIGHT"}, {"azimuth": 30, "elevation": 20, "name": "SIDEWAYS"}])
    r, _ = await pictures.run(ctx, state, "grid", {"image": name, "view": "SIDEWAYS"})
    assert r["frames"][0]["unit"] == "grid"
    r, _ = await pictures.run(ctx, state, "grid", {"image": name, "view": "straight"})
    assert r["frames"][0]["unit"] == "mm"


async def test_look_gives_its_frames_and_a_crop_of_a_photo_keeps_its_numbers(ctx, real_geom, monkeypatch):
    state = DesignState(pack="forms", source=BLOCK)
    db = await dbmod.get_db()
    rel = _photo(ctx)
    await db.execute("INSERT INTO projects (id, user_id, title, created_at, updated_at) VALUES (?, 'u', 't', 0, 0)", PID)
    await db.execute("INSERT INTO assets (id, project_id, kind, path, created_at) VALUES ('a_photo', ?, 'photo', ?, 0)", PID, rel)
    result, shots = await tools.run_tool(ctx, state, "look", {"what": "model", "zoom": {"center": [25, 20, 7], "size": 30}, "views": [{"azimuth": 0, "elevation": 0}]})
    assert result["ok"]
    assert [p[0] for p in pictures.shown(ctx, state, [("look", shots[0])])] == ["img1"]
    assert state.pictures["img1"]["frames"][0]["h"] == "x"
    result, shots = await tools.run_tool(ctx, state, "look", {"what": "a_photo", "crop": [500, 200, 800, 400]})
    assert result["ok"]
    pictures.shown(ctx, state, [("look", shots[0])])
    # the crop stays that crop, in the photo's own numbers
    r, _ = await pictures.run(ctx, state, "grid", {"image": "img2"})
    assert r["frames"][0]["x"] == pytest.approx([500, 800], abs=2) and r["frames"][0]["y"] == pytest.approx([200, 400], abs=2)
