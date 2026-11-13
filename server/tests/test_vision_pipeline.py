"""Ingest -> calibrate -> select -> scene summary with a temporary database and SAM mocked
by the synthetic ground-truth masks (no network)."""
from __future__ import annotations

import io

import cv2
import numpy as np
import pytest
from PIL import Image

import test_vision_synth as syn


@pytest.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setenv("FW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FW_BLUR_FACES", "0")
    from iamodelize3d import config, db

    config.settings.cache_clear()
    db._db = None
    yield tmp_path
    await db.close_db()
    config.settings.cache_clear()


def jpeg_with_exif(img_bgr: np.ndarray, f35: float | None = None) -> bytes:
    pil = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    exif = Image.Exif()
    exif[0x010F] = "TestCam"
    exif[0x0110] = "Model 1"
    exif[0x8825] = {2: (43.0, 14.0, 0.0)}  # GPS latitude, must not survive
    if f35:
        exif.get_ifd(0x8769)[0xA405] = int(round(f35))
    buf = io.BytesIO()
    pil.save(buf, "JPEG", exif=exif.tobytes(), quality=95)
    return buf.getvalue()


async def test_ingest_strips_metadata_and_keeps_focal(env):
    from iamodelize3d.vision import ingest
    from iamodelize3d.vision.common import abs_path

    img, *_ = syn.scene()
    row = await ingest.ingest_asset("p1", "photo", "IMG_1.jpg", jpeg_with_exif(img, 28), "image/jpeg")
    assert row["kind"] == "photo" and row["width"] == syn.W and row["height"] == syn.H
    assert row["meta"]["exif"]["focal_35mm"] == 28 and row["meta"]["exif"]["make"] == "TestCam"
    stored = Image.open(abs_path(row["path"]))
    assert not stored.getexif()  # no GPS, no camera data in the file
    assert abs_path(row["meta"]["thumb"]).exists()


async def test_ingest_rejects_garbage(env):
    from iamodelize3d.vision import ingest

    with pytest.raises(ValueError):
        await ingest.ingest_asset("p1", "photo", "x.jpg", b"not an image", "image/jpeg")


async def test_select_measures_in_mm(env, monkeypatch):
    from iamodelize3d.db import get_db
    from iamodelize3d.models import Point, SelectRequest
    from iamodelize3d.vision import ingest, scene
    from iamodelize3d.vision.sam import Mask

    img, sheet, part, R, t = syn.scene()
    calls = []

    async def fake_segment(meter, image, *, text=None, points=None, box=None):
        calls.append(text or "points")
        m = sheet if text == "sheet of paper" else part if text is None else None
        if m is None:
            return []
        ys, xs = np.nonzero(m)
        return [Mask(id="0", bbox_px=[int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1], score=0.9, mask=m)]

    monkeypatch.setattr(scene, "segment", fake_segment)
    db = await get_db()
    await db.insert("users", {"id": "u1", "tier": "anon", "created_at": 0})
    user = await db.one("SELECT * FROM users WHERE id = 'u1'")
    asset = await ingest.ingest_asset("p1", "photo", "a.jpg", jpeg_with_exif(img), "image/jpeg")
    cy, cx = np.argwhere(part).mean(axis=0)
    sel = await scene.select(user, "p1", asset, SelectRequest(points=[Point(x=float(cx), y=float(cy))], role="target", name="clip"))
    d = sel["data"]
    assert d["calibrated"] and d["reference"] == "A4"
    assert abs(d["size_mm"][0] - 60) < 0.6 and abs(d["size_mm"][1] - 40) < 0.6
    assert calls == ["points", "sheet of paper"]  # calibrated on demand once
    # thickness known later -> remeasure on the part's top plane
    sel2 = await scene.remeasure("p1", sel["id"], 0.0)
    assert sel2["data"]["uncertainty_mm"] <= d["uncertainty_mm"]
    summary = await scene.scene_summary("p1")
    assert "clip" in summary["inputs"]["outlines"]
    names = [m["name"] for m in summary["measurements"]]
    assert "clip length" in names and any("hole" in n for n in names)
    cam = scene.camera_for_render(await db.one("SELECT * FROM assets WHERE id = ?", asset["id"]))
    assert cam and cam["width"] == syn.W and len(cam["R"]) == 9


async def test_select_never_returns_the_reference_sheet(env, monkeypatch):
    from iamodelize3d.db import get_db
    from iamodelize3d.models import SelectRequest
    from iamodelize3d.vision import ingest, scene
    from iamodelize3d.vision.sam import Mask

    img, sheet, part, R, t = syn.scene()

    def as_mask(m, score):
        ys, xs = np.nonzero(m)
        return Mask(id=str(score), bbox_px=[int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1], score=score, mask=m)

    async def fake_segment(meter, image, *, text=None, points=None, box=None):
        # a text prompt for a flat part on paper often ranks the sheet itself first
        return [as_mask(sheet, 0.9)] if text == "sheet of paper" else [as_mask(sheet, 0.8), as_mask(part, 0.6)]

    monkeypatch.setattr(scene, "segment", fake_segment)
    db = await get_db()
    await db.insert("users", {"id": "u1", "tier": "anon", "created_at": 0})
    user = await db.one("SELECT * FROM users WHERE id = 'u1'")
    asset = await ingest.ingest_asset("p1", "photo", "a.jpg", jpeg_with_exif(img), "image/jpeg")
    sel = await scene.select(user, "p1", asset, SelectRequest(text="plate", role="target", name="plate"))
    assert abs(sel["data"]["size_mm"][0] - 60) < 0.6 and abs(sel["data"]["size_mm"][1] - 40) < 0.6


async def test_select_says_when_only_the_sheet_matches(env, monkeypatch):
    from iamodelize3d.db import get_db
    from iamodelize3d.models import SelectRequest
    from iamodelize3d.vision import ingest, scene
    from iamodelize3d.vision.sam import Mask

    img, sheet, part, R, t = syn.scene()
    ys, xs = np.nonzero(sheet)
    as_sheet = Mask(id="s", bbox_px=[int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1], score=0.9, mask=sheet)

    async def fake_segment(meter, image, *, text=None, points=None, box=None):
        return [as_sheet]

    async def fake_ground(meter, image, text, model):
        return as_sheet.bbox_px

    monkeypatch.setattr(scene, "segment", fake_segment)
    monkeypatch.setattr(scene, "_ground_box", fake_ground)
    db = await get_db()
    await db.insert("users", {"id": "u1", "tier": "anon", "created_at": 0})
    user = await db.one("SELECT * FROM users WHERE id = 'u1'")
    asset = await ingest.ingest_asset("p1", "photo", "a.jpg", jpeg_with_exif(img), "image/jpeg")
    with pytest.raises(ValueError, match="scale reference"):
        await scene.select(user, "p1", asset, SelectRequest(text="white plate", role="target"))


def test_overlay_blend():
    from iamodelize3d.vision.overlay import blend

    photo = np.full((10, 10, 3), 100, np.uint8)
    render = np.zeros((10, 10, 4), np.uint8)
    render[2:5, 2:5] = (0, 0, 255, 255)
    out = blend(photo, render, opacity=1.0)
    assert tuple(out[3, 3]) == (0, 0, 255) and tuple(out[8, 8]) == (100, 100, 100)


def test_visual_hull_of_a_box():
    from iamodelize3d.vision import hull

    box = np.array([[x, y, z] for x in (-20, 20) for y in (-15, 15) for z in (0, 20)], float)
    views = []
    eyes = [(180 * np.cos(2 * np.pi * k / 8), 180 * np.sin(2 * np.pi * k / 8), 110) for k in range(8)]
    eyes.append((5, -40, 260))  # one high view pins the top; side views alone overestimate height
    for eye in eyes:
        R, t = syn.look_at(eye, (0, 0, 10))
        px = syn.project(R, t, box)
        mask = syn.fill((syn.H, syn.W), [cv2.convexHull(px.astype(np.float32)).reshape(-1, 2)]) > 0
        cam = {"width": syn.W, "height": syn.H, "R": R.reshape(-1).tolist(), "t": t.tolist(), "fx": syn.F, "fy": syn.F, "cx": syn.W / 2, "cy": syn.H / 2}
        views.append({"camera": cam, "mask": mask})
    res = hull.carve(views, ((-30, -25, 0), (30, 25, 30)), 1.0)
    true_vol = 40 * 30 * 20
    assert 0.95 * true_vol < res["volume_mm3"] < 1.25 * true_vol, res["volume_mm3"]
    hm = hull.heightmap(res)
    tops = np.array([v for v in hm["data"] if v > 0])
    # a visual hull is an envelope: the bulk of the top is right, edges may bulge upwards
    assert hm["w"] == 60 and abs(np.median(tops) - 20) <= 2 and tops.max() <= 30
    assert len(hull.surface_points(res, 500)) == 500


def test_turntable_pose_from_aruco_ring():
    from iamodelize3d.vision import hull

    sheet = hull.ring_sheet()
    px_per_mm = 300 / 25.4
    Hs, Ws = sheet.shape
    R, t = syn.look_at((0, -260, 260), (0, 0, 0))
    # map sheet pixels -> world mm (centre of the sheet is the world origin, y up)
    src = np.array([[0, 0], [Ws, 0], [Ws, Hs], [0, Hs]], np.float32)
    world = np.array([[(x - Ws / 2) / px_per_mm, (Hs / 2 - y) / px_per_mm] for x, y in src])
    dst = syn.project(R, t, world).astype(np.float32)
    frame = cv2.warpPerspective(sheet, cv2.getPerspectiveTransform(src, dst), (syn.W, syn.H), borderValue=90)
    pose = hull.turntable_pose(cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR), syn.K, hull.ring_layout())
    assert pose and pose["markers"] >= 4 and pose["reproj_px"] < 2
    C = -np.asarray(pose["camera"]["R"]).reshape(3, 3).T @ np.asarray(pose["camera"]["t"])
    assert np.linalg.norm(C - np.array([0, -260, 260])) < 10


async def test_ingest_video_and_audio(env, monkeypatch, tmp_path):
    from iamodelize3d.vision import ingest

    if not ingest.ffmpeg_bin():
        pytest.skip("ffmpeg not installed")  # a video is stored only once ffmpeg has removed its metadata
    path = tmp_path / "clip.mp4"
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    for i in range(20):
        fr = np.full((240, 320, 3), 40, np.uint8)
        cv2.circle(fr, (40 + i * 10, 120), 20, (0, 0, 255), -1)
        vw.write(fr)
    vw.release()
    v = await ingest.ingest_asset("p1", "photo", "clip.mp4", path.read_bytes(), "video/mp4")
    assert v["kind"] == "video" and v["meta"]["frames"] == 20 and v["meta"]["thumb"]

    async def fake_transcribe(wav):
        return "shelf is 18 mm thick"

    monkeypatch.setattr(ingest, "transcribe", fake_transcribe)
    sr = 16000
    tone = (np.sin(np.linspace(0, 2 * np.pi * 440, sr)) * 8000).astype(np.int16)
    wav = io.BytesIO()
    import wave

    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(tone.tobytes())
    a = await ingest.ingest_asset("p1", "photo", "note.wav", wav.getvalue(), "audio/wav")
    assert a["kind"] == "audio" and a["meta"]["transcript"].startswith("shelf") and abs(a["meta"]["duration_s"] - 1.0) < 0.05


def test_blur_regions_only_touches_masks():
    from iamodelize3d.vision.privacy import blur_regions

    rng = np.random.default_rng(0)
    img = rng.integers(0, 255, (200, 200, 3), dtype=np.uint8)
    m = np.zeros((200, 200), bool)
    m[50:100, 50:100] = True
    out = blur_regions(img, [m])
    assert np.array_equal(out[150:, 150:], img[150:, 150:])
    assert out[60:90, 60:90].std() < img[60:90, 60:90].std() / 2
