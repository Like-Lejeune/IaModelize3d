"""Board scan (vision/board.py) offline: Muse Spark and SAM answers recorded on a photo of a Pico W
(fixtures/board_scan), plus synthetic photos with exact ground truth for the A4 path and the hole fit."""
from __future__ import annotations

import json
import math
from pathlib import Path

import cv2
import numpy as np
import pytest

import test_vision_synth as syn
from iamodelize3d import db as dbmod
from iamodelize3d.config import settings
from iamodelize3d.llm.client import CostMeter
from iamodelize3d.vision import board as vb
from iamodelize3d.vision import sam as vsam
from iamodelize3d.vision.sam import Mask

FIX = Path(__file__).parent / "fixtures" / "board_scan"


class FakeMeta:
    """Muse Spark answers the recorded identification; SAM answers the recorded concept prompts (box prompts: nothing)."""

    def __init__(self, ident: dict | None = None, root: Path = FIX):
        self.root = root
        self.ident = json.loads(json.loads((root / "raw_identify.json").read_text(encoding="utf-8"))["text"]) if ident is None else ident
        self.sam_prompts: list[str] = []

    async def json(self, meter, **kw):
        return self.ident

    async def sam(self, meter, url, prompt, **kw):
        self.sam_prompts.append(prompt)
        f = self.root / ("raw_sam_" + prompt.replace(" ", "_") + ".txt")
        return f.read_text(encoding="utf-8") if f.exists() else ""


@pytest.fixture
def recorded(monkeypatch):
    fake = FakeMeta()
    monkeypatch.setattr(vb, "meta", lambda: fake)
    monkeypatch.setattr(vsam, "meta", lambda: fake)
    return fake


PHOTO = {"id": "a_pico", "kind": "photo", "path": str(FIX / "picow_small.jpg"), "meta": {}}


async def test_the_pico_w_is_read_and_scaled_by_its_own_holes(recorded):
    out = await vb.scan_board(CostMeter(), dict(PHOTO))
    assert out["identified"]["board_id"] == "rpi-pico-w" and "Pico W" in out["identified"]["marking"]
    cal = out["calibration"]
    # no sheet in the photo: the 4 mounting holes are the reference
    assert cal["method"] == "board_holes" and sorted(map(tuple, cal["holes_mm"])) == [(4.8, 2.0), (4.8, 49.0), (16.2, 2.0), (16.2, 49.0)]
    assert cal["pattern_mm"] < 0.2 and cal["parts_matched"] >= 2
    # the castellated pads, never used for the fit, land on the drawing's rows
    rows = cal["pin_rows"]["rows_x"]
    assert rows[0] == pytest.approx(1.6, abs=0.05) and rows[1] == pytest.approx(19.4, abs=0.05)
    assert cal["pin_rows"]["pads"] == [20, 20]
    d = {(x["part"], x["field"]): x for x in out["deltas"]}
    assert d[("usb", "at")]["photo"] == pytest.approx(10.5, abs=0.3)
    assert d[("bootsel", "x")]["source"] == "spark" and abs(d[("bootsel", "y")]["delta"]) < 1.0
    # dataset numbers win: a Spark box (±0.8 mm) does not replace a drawing's verify position (±0.5 mm)
    board = out["board"]
    comps = {c["id"]: c for c in board["components"]}
    assert comps["usb"]["at"] == 10.5 and comps["bootsel"]["x"] == 6.9 and not any(x["applied"] for x in out["deltas"])
    assert comps["usb"]["evidence"]["sam"]["prompt"] == "USB port"
    assert board["source"]["kind"] == "photo+dataset" and board["source"]["dataset_id"] == "rpi-pico-w"
    assert board["source"]["calibration"]["method"] == "board_holes"
    assert vb.schema_errors(board) == [] and out["schema_errors"] == []
    # boxes for the studio: the 4 mounting holes and the USB bright, the 40 edge pads dim
    strong = [b for b in out["boxes"] if b["emphasis"] == "strong"]
    assert sorted(b["kind"] for b in strong) == ["mount"] * 4 + ["port"]
    assert sum(1 for b in out["boxes"] if b["kind"] == "pin") >= 40
    assert {b["label"] for b in out["boxes"] if b["source"] == "spark"} >= {"BOOTSEL", "LED"}
    # SAM looked for the board first (no answer recorded: Spark saw the whole photo), and Spark's BOOTSEL box went
    # to SAM as a box prompt (the concept prompt finds no buttons)
    assert out["view_px"] == [0, 0, 1600, 678] and "circuit board" in recorded.sam_prompts
    assert sum(1 for p in recorded.sam_prompts if p not in ("circuit board", "mounting hole", "USB port")) == 1


async def test_a_more_precise_measurement_replaces_a_verify_position(recorded, monkeypatch):
    # a SAM mask of the button (here: a 3x4 mm box drawn where the photo shows it) beats the drawing's ±0.5 mm
    async def refine(meter, img, sp):
        x1, y1, x2, y2 = sp["box"]
        m = np.zeros(img.shape[:2], bool)
        m[y1 + 20:y2 - 20, x1 + 10:x2 - 10] = True
        return Mask(id="btn", bbox_px=[x1 + 10, y1 + 20, x2 - 10, y2 - 20], score=0.9, mask=m)

    monkeypatch.setattr(vb, "_refine_button", refine)
    out = await vb.scan_board(CostMeter(), dict(PHOTO))
    d = {(x["part"], x["field"]): x for x in out["deltas"]}
    assert d[("bootsel", "x")]["source"] == "sam" and d[("bootsel", "x")]["applied"]
    bootsel = next(c for c in out["board"]["components"] if c["id"] == "bootsel")
    assert bootsel["x"] == d[("bootsel", "x")]["photo"] and "x" not in bootsel["verify"] and "h" in bootsel["verify"]
    assert vb.schema_errors(out["board"]) == []


@pytest.fixture
async def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    yield await dbmod.get_db()
    await dbmod.close_db()


async def test_the_scan_is_kept_as_a_selection_with_labelled_boxes(recorded, fresh_db):
    await fresh_db.insert("assets", {"id": "a_pico", "project_id": "p1", "kind": "photo", "path": str(FIX / "picow_small.jpg"),
                                     "width": 1600, "height": 678, "meta": {}, "created_at": 0})
    out = await vb.scan_board(CostMeter(), {**PHOTO, "project_id": "p1"})
    sel = out["selection"]
    assert sel["role"] == "context" and sel["name"] == "board" and sel["asset_id"] == "a_pico"
    data = sel["data"]
    assert data["kind"] == "board_scan" and data["board_id"] == "rpi-pico-w" and data["input"] == "inputs.boards.board"
    assert data["calibration"]["method"] == "board_holes" and len(data["boxes"]) == len(out["boxes"])
    row = await fresh_db.one("SELECT * FROM selections WHERE id = ?", sel["id"])
    assert row["data"]["boxes"][0]["box"] == out["boxes"][0]["box"]


async def test_a_real_photo_on_an_a4_sheet(fresh_db, monkeypatch):
    """Recorded on a 3200 x 2400 photo of the Pico W on an A4 sheet (turned 28°, camera tilted): SAM found the board but
    none of its holes on the whole frame, so the sheet and the board's own outline gave the scale."""
    root = FIX / "a4"
    fake = FakeMeta(root=root)
    monkeypatch.setattr(vb, "meta", lambda: fake)
    monkeypatch.setattr(vsam, "meta", lambda: fake)
    await fresh_db.insert("assets", {"id": "a_a4", "project_id": "p1", "kind": "photo", "path": str(root / "picow_a4.jpg"), "width": 3200,
                                     "height": 2400, "meta": {}, "created_at": 0})
    out = await vb.scan_board(CostMeter(), {"id": "a_a4", "project_id": "p1", "kind": "photo", "path": str(root / "picow_a4.jpg"), "meta": {}})
    assert out["identified"]["board_id"] == "rpi-pico-w" and out["identified"]["confidence"] >= 0.9
    # Spark read a crop of the board, not the whole sheet
    vx, vy, vw, vh = out["view_px"]
    assert vw < 800 and vh < 800 and fake.sam_prompts[0] == "circuit board"
    cal = out["calibration"]
    assert cal["method"] == "a4" and cal["reference"] == "A4"
    # the board's outline on the sheet against the drawing's 21 x 51 mm
    assert cal["measured_mm"][0] == pytest.approx(21.0, abs=0.25) and cal["measured_mm"][1] == pytest.approx(51.0, abs=0.25)
    d = {(x["part"], x["field"]): x for x in out["deltas"]}
    assert abs(d[("pcb", "w")]["delta"]) < 0.25 and abs(d[("pcb", "h")]["delta"]) < 0.25
    # Spark's boxes on this crop were several mm off: they turn the board the right way round but replace nothing
    assert cal["parts_matched"] >= 2 and not any(x["applied"] for x in out["deltas"])
    comps = {c["id"]: c for c in out["board"]["components"]}
    assert comps["bootsel"]["x"] == 6.9 and comps["usb"]["at"] == 10.5
    assert vb.schema_errors(out["board"]) == [] and out["warnings"] == []
    x1, y1, x2, y2 = out["board_box_px"]
    assert vx <= x1 and x2 <= vx + vw and all(vx <= b["box"][0] and b["box"][2] <= vx + vw for b in out["boxes"])


async def test_an_unknown_board_without_a_reference_is_refused(monkeypatch):
    fake = FakeMeta({"board_id": "unknown", "marking": "", "confidence": 0.2, "side": "top", "board_box": [100, 100, 900, 900], "parts": []})
    monkeypatch.setattr(vb, "meta", lambda: fake)
    monkeypatch.setattr(vsam, "meta", lambda: fake)
    with pytest.raises(ValueError, match="A4"):
        await vb.scan_board(CostMeter(), dict(PHOTO))


def test_the_schema_check_catches_what_lib_elec_would_trip_on():
    for b in vb.boards():
        assert vb.schema_errors(b) == [], b["id"]
    carrier = json.loads((Path(settings().geom_dir) / "test" / "data" / "xiao_carrier.board.json").read_text(encoding="utf-8"))
    assert vb.schema_errors(carrier) == []
    bad = vb.find_board("rpi-pico-w")
    usb = next(c for c in bad["components"] if c["id"] == "usb")
    del usb["edge"]  # a port must say which edge it is on
    bad["pcb"]["outline"] = {"kind": "round", "w": 21, "h": 51}
    bad["components"].append({"id": "x", "type": "led_0603", "side": "top", "access": "glow", "w": 1, "h": 1})
    errs = " | ".join(vb.schema_errors(bad))
    assert "components[0]: missing edge" in errs and "outline: must match exactly one" in errs and "access: must be one of" in errs
    assert "components[5]: missing x" in errs


# ---------------------------------------------------------------- synthetic geometry


def _disc(shape, centre, r) -> np.ndarray:
    m = np.zeros(shape, np.uint8)
    cv2.circle(m, (int(round(centre[0] * 8)), int(round(centre[1] * 8))), int(round(r * 8)), 1, -1, shift=3)
    return m.astype(bool)


def _mask(mid: str, m: np.ndarray, score: float = 0.8) -> Mask:
    ys, xs = np.nonzero(m)
    return Mask(id=mid, bbox_px=[int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1], score=score, mask=m)


@pytest.mark.parametrize("turn", [0, 33, 180, 251])
def test_the_hole_fit_finds_the_board_turned_any_way(turn):
    """A Pico W seen from above at any angle: the holes alone fit two ways round; the USB says which."""
    spec = vb.find_board("rpi-pico-w")
    k, a = 30.0, math.radians(turn)  # px per mm
    R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])

    def px(p):  # board mm -> image px (top view: image y runs down)
        q = R @ (np.asarray(p, float) - [10.5, 25.5])
        return [800 + k * q[0], 800 - k * q[1]]

    shape = (1600, 1600)
    holes = [_mask(f"h{i}", _disc(shape, px([h["x"], h["y"]]), 1.1 * k)) for i, h in enumerate(spec["pcb"]["holes"])]
    holes += [_mask(f"p{i}", _disc(shape, px([1.61, 1.37 + 2.54 * i]), 0.5 * k)) for i in range(6)]  # a few edge pads
    usb = np.zeros(shape, np.uint8)
    cv2.fillPoly(usb, [np.round([px(p) for p in ([6.5, 46.6], [14.5, 46.6], [14.5, 52.3], [6.5, 52.3])]).astype(np.int32)], 1)
    cal = vb.calibrate_by_holes(holes, spec, "top", [_mask("usb", usb.astype(bool))], [])
    assert cal and cal["method"] == "board_holes" and set(cal["mask_ids"]) == {"h0", "h1", "h2", "h3"}
    probe = vb.apply_h(cal["H"], [px([3.0, 40.0])])[0]
    assert probe == pytest.approx([3.0, 40.0], abs=0.05)
    assert cal["mm_per_px"] == pytest.approx(1 / k, rel=0.01)


async def test_an_unknown_board_on_an_a4_sheet(fresh_db, monkeypatch):
    """The A4 path: the sheet gives the plane, SAM's board mask the outline, its hole and port masks the rest."""
    from iamodelize3d.vision import scene

    img, sheet, _, R, t = syn.scene()
    x0, y0, bw, bh = 70.0, 110.0, 50.0, 30.0  # the board on the sheet, mm
    board_px = syn.project(R, t, np.hstack([syn.part_world(x0, y0, bw, bh), np.full((4, 1), 1.6)]))
    board = syn.fill(img.shape[:2], [board_px]).astype(bool)
    holes = []
    for i, (hx, hy) in enumerate([(3.5, 3.5), (46.5, 3.5), (3.5, 26.5), (46.5, 26.5)]):
        ring = syn.project(R, t, np.hstack([syn.circle_pts(x0 + hx, y0 + hy, 1.6), np.full((180, 1), 1.6)]))
        holes.append(_mask(f"h{i}", syn.fill(img.shape[:2], [ring]).astype(bool)))
    usb_w = np.array([[x0 - 1.0, y0 + 11.0], [x0 + 6.0, y0 + 11.0], [x0 + 6.0, y0 + 19.0], [x0 - 1.0, y0 + 19.0]])
    usb = syn.fill(img.shape[:2], [syn.project(R, t, np.hstack([usb_w, np.full((4, 1), 1.6)]))]).astype(bool)

    # SAM sees the whole photo for the board and the sheet, and the crop around the board for its holes and port
    vx, vy, vw, vh = vb._view(board, syn.W, syn.H)

    def crop(m: Mask) -> Mask:
        return _mask(m.id, m.mask[vy:vy + vh, vx:vx + vw], m.score)

    async def fake_segment(meter, image, *, text=None, points=None, box=None):
        whole = image.shape[:2] == img.shape[:2]
        out = {"sheet of paper": [_mask("sheet", sheet.astype(bool), 0.95)], "circuit board": [_mask("board", board, 0.9)],
               "mounting hole": holes, "USB port": [_mask("usb", usb, 0.7)]}.get(text or "", [])
        return out if whole or text in ("sheet of paper", "circuit board") else [crop(m) for m in out]

    monkeypatch.setattr(vb, "segment", fake_segment)
    monkeypatch.setattr(scene, "segment", fake_segment)
    fake = FakeMeta({"board_id": "unknown", "marking": "ACME sensor v2", "confidence": 0.9, "side": "top", "board_box": [0, 0, 1000, 1000],
                     "parts": [{"type": "usb_c", "label": "USB", "box": [0, 0, 1, 1], "at_edge": True}]})
    monkeypatch.setattr(vb, "meta", lambda: fake)
    path = Path(settings().data_dir) / "files" / "p1" / "a4.png"
    path.parent.mkdir(parents=True)
    cv2.imwrite(str(path), img)
    asset = {"id": "a_a4", "project_id": "p1", "kind": "photo", "path": "p1/a4.png", "width": syn.W, "height": syn.H, "meta": {}, "created_at": 0}
    await fresh_db.insert("assets", asset)
    out = await vb.scan_board(CostMeter(), asset)
    b = out["board"]
    # the board is small on the sheet: Spark and SAM looked at a crop around it
    assert out["view_px"] == [vx, vy, vw, vh]
    bx = out["board_box_px"]
    assert vw < syn.W / 2 and vx <= bx[0] and vy <= bx[1] and bx[2] <= vx + vw and bx[3] <= vy + vh
    assert out["calibration"]["method"] == "a4" and b["source"]["kind"] == "photo" and vb.schema_errors(b) == []
    # the board sits 1.6 mm above the sheet: the plane's scale makes it look about 0.4 % bigger from 380 mm
    assert b["pcb"]["outline"]["w"] == pytest.approx(bw, abs=0.4) and b["pcb"]["outline"]["h"] == pytest.approx(bh, abs=0.4)
    # the hole pattern is symmetric, so whichever corner became the origin it reads the same
    got = sorted(((h["x"], h["y"]) for h in b["pcb"]["holes"]), key=lambda p: (p[0] > bw / 2, p[1] > bh / 2))  # by quadrant
    assert np.allclose(got, [(3.5, 3.5), (3.5, 26.5), (46.5, 3.5), (46.5, 26.5)], atol=0.4), got
    assert all(h["d"] == pytest.approx(3.1, abs=0.3) and h["verify"] == ["d"] for h in b["pcb"]["holes"])
    port = next(c for c in b["components"] if c["access"] == "port")
    assert port["type"] == "usb_c" and port["edge"] in ("-x", "+x") and port["at"] == pytest.approx(15, abs=0.5)
    assert port["protrude"] == pytest.approx(1.0, abs=0.4) and "plug" in port["verify"]
