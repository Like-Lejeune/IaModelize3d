"""Probes, fingerprint coupon and outline comparison."""
import math
from types import SimpleNamespace

import numpy as np
import pytest

from iamodelize3d.geom import GeomPool
from iamodelize3d.printing import fingerprint
from iamodelize3d.printing.compare import compare_outlines
from iamodelize3d.printing.fingerprint import classify, compute_fingerprint, coupon_source
from iamodelize3d.printing.probes import apply_choice, make_probe


@pytest.fixture
async def pool():
    p = GeomPool(1)
    yield p
    await p.close()


@pytest.mark.parametrize("kind,nominal,extra", [
    ("hole", 8.0, {}), ("hole", 32.4, {}), ("peg", 5.0, {}), ("gap", 18.4, {}), ("clip", 18.4, {}), ("thread", 20.0, {"pitch": 2.5}),
])
async def test_probes_build_and_pass_full_checks(pool, kind, nominal, extra):
    pr = make_probe(kind, nominal, extra=extra)
    r = await pool.build(pr["source"], {}, analyze="full")
    errors = [i["message"] for i in r["checks"]["issues"] if i["severity"] == "error"]
    assert errors == []
    assert len(pr["variants"]) >= 4 and pr["est_minutes"] < 40
    assert max(r["checks"]["stats"]["size"][:2]) < 200


def test_probe_variants_and_choice():
    pr = make_probe("hole", 32.4)
    labels = [v["label"] for v in pr["variants"]]
    assert labels == ["32", "32.2", "32.4", "32.6", "32.8"]
    assert apply_choice(pr["variants"], "32.6") == pytest.approx(32.6)
    assert apply_choice(pr["variants"], "2") == pytest.approx(32.2)
    th = make_probe("thread", 28.0, extra={"pitch": 3})
    assert apply_choice(th["variants"], "c0.3") == pytest.approx(0.3)
    with pytest.raises(ValueError):
        apply_choice(pr["variants"], "99")


async def test_coupon_builds(pool):
    r = await pool.build(coupon_source(), {}, analyze="full")
    assert {p["name"] for p in r["parts"]} == {"plate", "block_plain", "block_chamfered", "peg_5", "peg_8"}
    assert [i for i in r["checks"]["issues"] if i["severity"] == "error"] == []


def test_fingerprint_math():
    fp = compute_fingerprint({
        "holes": {"3": 2.8, "5": 4.79, "8": 7.81, "10": 9.8},
        "pegs": {"5": 5.1, "8": 8.1},
        "block": 20.5,
        "block_chamfered": 20.1,
    })
    assert fp["holeDelta"] == pytest.approx(0.2, abs=0.01)
    assert fp["outerDelta"] == pytest.approx(0.1, abs=0.01)
    assert fp["elephantFoot"] == pytest.approx(0.2, abs=0.01)
    assert fp["fitDelta"] == pytest.approx(0.1, abs=0.01)
    assert fp["confidence"] > 0.7
    noisy = compute_fingerprint({"holes": {"3": 2.5, "5": 5.1, "8": 7.7, "10": 10.2}})
    assert noisy["confidence"] < fp["confidence"]


def _circle(cx, cy, d, n=120):
    return np.array([[cx + d / 2 * math.cos(2 * math.pi * k / n), cy + d / 2 * math.sin(2 * math.pi * k / n)] for k in range(n)])


def _square(x, y, s):
    return np.array([[x, y], [x + s, y], [x + s, y + s], [x, y + s]], dtype=float)


def test_classify_coupon_from_outlines():
    plate = {"outer": np.array([[0, 0], [70, 0], [70, 40], [0, 40]], float),
             "holes": [_circle(10, 20, 2.8), _circle(22, 20, 4.8), _circle(37, 20, 7.8), _circle(56, 20, 9.8)]}
    objects = [plate, {"outer": _square(0, 48, 20.5), "holes": []}, {"outer": _square(28, 48, 20.1), "holes": [_circle(38, 58, 4)]},
               {"outer": _circle(60, 54, 5.1), "holes": []}, {"outer": _circle(60, 67, 8.1), "holes": []}]
    m = classify(objects)
    assert m["holes"]["3"] == pytest.approx(2.8, abs=0.02) and m["holes"]["10"] == pytest.approx(9.8, abs=0.02)
    assert m["block"] == pytest.approx(20.5, abs=0.01) and m["block_chamfered"] == pytest.approx(20.1, abs=0.01)
    assert m["pegs"]["8"] == pytest.approx(8.1, abs=0.02)
    fp = compute_fingerprint(m)
    assert fp["holeDelta"] == pytest.approx(0.2, abs=0.02) and fp["elephantFoot"] == pytest.approx(0.2, abs=0.02)


async def test_fingerprint_save_and_load(monkeypatch, tmp_path):
    from iamodelize3d.db import Database

    db = Database(str(tmp_path / "t.db"))
    await db.open()

    async def get():
        return db

    monkeypatch.setattr(fingerprint, "get_db", get)
    await fingerprint.save("u1", "bambu-lab-x1-carbon-0-4-nozzle", {"holeDelta": 0.2})
    await fingerprint.save("u1", "bambu-lab-x1-carbon-0-4-nozzle", {"holeDelta": 0.25})
    assert (await fingerprint.load("u1", "bambu-lab-x1-carbon-0-4-nozzle"))["holeDelta"] == 0.25
    assert await fingerprint.load("u2", "bambu-lab-x1-carbon-0-4-nozzle") is None
    await db.close()


def test_compare_outlines_aligns_and_reports():
    rect = [[0, 0], [40, 0], [40, 20], [0, 20]]
    hole = _circle(30, 10, 8).tolist()
    target = [rect, hole]
    # printed: 0.2 mm bigger per side, hole 0.2 mm smaller, rotated 30°, moved, mirrored
    big = np.array([[-0.2, -0.2], [40.2, -0.2], [40.2, 20.2], [-0.2, 20.2]])
    small_hole = _circle(30, 10, 7.8)
    a = math.radians(30)
    r = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    move = lambda p: ((np.asarray(p) * np.array([-1, 1])) @ r.T + np.array([100, 50])).tolist()  # noqa: E731
    rep = compare_outlines(target, [move(big), move(small_hole)])
    assert rep["bias_mm"] == pytest.approx(0.2, abs=0.05)
    assert rep["max_mm"] < 0.35
    assert rep["holes"] and rep["holes"][0]["delta"] == pytest.approx(-0.2, abs=0.05)
    params = {s["param"]: s["delta"] for s in rep["suggestions"] if s["param"]}
    assert params["outerDelta"] == pytest.approx(0.4, abs=0.1)
    assert params["holeDelta"] == pytest.approx(0.2, abs=0.08)


def test_compare_identical_is_ok():
    rect = [[0, 0], [40, 0], [40, 20], [0, 20]]
    rep = compare_outlines(rect, rect)
    assert rep["ok"] and rep["max_mm"] < 0.05 and rep["suggestions"] == []


async def test_measure_uses_calibration_and_sam(monkeypatch, tmp_path):
    """End to end on a synthetic photo: stored calibration + mocked SAM masks -> fingerprint."""
    import base64

    import cv2
    import meta_sam_parser as msp

    from iamodelize3d.config import settings
    from iamodelize3d.vision import maskcodec

    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files" / "p").mkdir(parents=True)
    img = np.full((900, 1000, 3), 230, np.uint8)
    cv2.imwrite(str(tmp_path / "files" / "p" / "a.jpg"), img)
    s = 0.1  # mm per px
    asset = {"id": "a", "project_id": "p", "path": "p/a.jpg", "meta": {"calibration": {"ok": True, "H_px2mm": [[s, 0, 0], [0, s, 0], [0, 0, 1]]}}}

    def rec(mask_full):
        ys, xs = np.nonzero(mask_full)
        l, t, r, b = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        crop = mask_full[t:b, l:r]
        return SimpleNamespace(bounds=SimpleNamespace(left=int(l), top=int(t), right=int(r), bottom=int(b)),
                               mask=SimpleNamespace(width=int(r - l), height=int(b - t), raw=crop.astype(np.uint8).tobytes()))

    def blank():
        return np.zeros((900 * 4, 1000 * 4), np.uint8)

    K = 4  # draw at 4x and area-downsample: unbiased pixel-center coverage, like a camera

    def poly(mask, pts_mm, value):
        cv2.fillPoly(mask, [np.round(np.asarray(pts_mm) / s * K).astype(np.int32)], value)
        return mask

    def done(hi):
        return (cv2.resize(hi.astype(np.float32), (1000, 900), interpolation=cv2.INTER_AREA) > 0.5).astype(np.uint8)

    def circ(cx, cy, d, n=180):
        return [[cx + d / 2 * math.cos(2 * math.pi * k / n), cy + d / 2 * math.sin(2 * math.pi * k / n)] for k in range(n)]

    def sq(x, y, w):
        return [[x, y], [x + w, y], [x + w, y + w], [x, y + w]]

    plate = poly(blank(), [[10, 10], [80, 10], [80, 50], [10, 50]], 1)
    for cx, d in ((20, 2.8), (32, 4.8), (47, 7.8), (66, 9.8)):
        poly(plate, circ(cx, 30, d), 0)
    a = poly(blank(), sq(10, 58, 20.5), 1)
    b = poly(poly(blank(), sq(40, 58, 20.1), 1), circ(50, 68, 4), 0)
    p5 = poly(blank(), circ(72, 64, 5.1), 1)
    p8 = poly(blank(), circ(72, 80, 8.1), 1)
    records = [rec(done(m)) for m in (plate, a, b, p5, p8)]

    class FakeParser:
        def push(self, raw):
            pass

        def finish(self, outcome):
            return SimpleNamespace(result=SimpleNamespace(records=records))

    monkeypatch.setattr(msp, "image_segmentation_format", lambda: SimpleNamespace(create_parser=FakeParser))
    monkeypatch.setattr(msp, "SegmentationMaskRecord", SimpleNamespace)
    monkeypatch.setattr(msp, "decode_mask_to_raster", lambda m: m.raw)
    monkeypatch.setattr(maskcodec, "decode_mask_to_raster", lambda m: m.raw)

    async def fake_sam(meter, url, prompt):
        assert url.startswith("data:image/jpeg;base64,") and base64.b64decode(url.split(",", 1)[1])
        return "raw"

    from iamodelize3d.llm import client

    monkeypatch.setattr(client, "meta", lambda: SimpleNamespace(sam=fake_sam))
    out = await fingerprint.measure(SimpleNamespace(), {"id": "u"}, asset)
    fp, m = out["fingerprint"], out["measured"]
    # rasterizing at 0.1 mm/px costs a few hundredths of a mm
    assert set(m["holes"]) == {"3", "5", "8", "10"} and set(m["pegs"]) == {"5", "8"}
    assert fp["holeDelta"] == pytest.approx(0.2, abs=0.05)
    assert fp["elephantFoot"] == pytest.approx(0.2, abs=0.05)
    assert fp["outerDelta"] == pytest.approx(0.1, abs=0.05)
