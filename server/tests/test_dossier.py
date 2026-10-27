"""Scale-free measurements used by the dossier: pattern counts and silhouette ratios."""
import math

import numpy as np

from formwright.agent.dossier import depth_for, motif_stats, silhouette_ratios


def cylinder_scene(per_row=16, rows=9, radius=200, height=460, tile=0.75):
    """Orthographic side view of a cylinder covered by a staggered grid of square tiles."""
    W, H = 2 * radius + 40, height + 40
    obj = np.zeros((H, W), bool)
    obj[20:20 + height, 20:20 + 2 * radius] = True
    instances = []
    pitch_angle = 2 * math.pi / per_row
    v_pitch = height / rows
    for r in range(rows):
        cy = 20 + v_pitch * (r + 0.5)
        for j in range(per_row):
            theta = pitch_angle * (j + 0.5 * (r % 2))
            if math.cos(theta) <= 0.15:  # back side / grazing: not visible
                continue
            cx = 20 + radius + radius * math.sin(theta)
            half_w = 0.5 * tile * radius * pitch_angle * math.cos(theta)
            half_h = 0.5 * tile * v_pitch
            m = np.zeros((H, W), bool)
            m[int(cy - half_h):int(cy + half_h), int(cx - half_w):int(cx + half_w) + 1] = True
            instances.append(m)
    return obj, instances


def test_motif_counts_from_a_side_view():
    obj, inst = cylinder_scene(per_row=16, rows=9)
    s = motif_stats(obj, inst)
    assert s["visible_rows"] == 9
    assert abs(s["estimated_per_row"] - 16) <= 1
    assert abs(s["estimated_rows_total"] - 9) <= 1


def test_silhouette_ratios_capture_taper():
    m = np.zeros((300, 300), bool)
    for y in range(50, 250):
        half = int(60 + (y - 50) * 0.2)  # wider at the bottom
        m[y, 150 - half:150 + half] = True
    r = silhouette_ratios(m)
    assert r["width_profile"]["20%"] < r["width_profile"]["80%"]
    assert 0.9 < r["height_to_width"] < 1.3


def test_depth_adapts_to_task():
    photo = [{"kind": "photo"}]
    assert depth_for("copy", photo, "auto") == "full"
    assert depth_for("household", [], "auto") == "short"
    assert depth_for("household", [], "off") == "off"


class FakeCtx:
    def __init__(self):
        self.events = []

    async def status(self, text):
        pass

    async def emit(self, type_, data):
        self.events.append((type_, data))


async def test_failed_must_check_blocks_finish(monkeypatch):
    from formwright.agent import critic, tools

    async def review(ctx, state):
        return {"verdict": "pass", "match_score": 9, "issues": [], "checklist": [
            {"id": "count", "check": "16 studs per row", "must": True, "valid": True, "ok": False, "note": "only 12"},
            {"id": "rim", "check": "rounded rim", "must": False, "valid": True, "ok": False, "note": "sharp"},
            # the photo shows a straight wall: a wrong dossier item must not send the design back
            {"id": "taper", "check": "base narrows to 0.7", "must": True, "valid": False, "ok": False, "note": "photo is straight"},
        ]}

    monkeypatch.setattr(critic, "review", review)
    state = tools.DesignState(pack="copy", source="return {}", last_build={"checks": {"issues": []}})
    res = await tools._finish(FakeCtx(), state, "done")
    assert res["accepted"] is False
    assert [i["text"] for i in res["issues"]] == ["Dossier check failed: 16 studs per row — only 12"]
    assert not state.done
