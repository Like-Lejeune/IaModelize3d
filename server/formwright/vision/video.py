"""Video: SAM 3.1 tracking across frames and Muse Spark video+audio understanding.

A 15-second "show and tell" clip (turn the part, say what's wrong) replaces a form:
SAM follows the part through the frames, Spark watches and listens.
"""
from __future__ import annotations

import base64
from typing import Any

import cv2
import meta_sam_parser as msp
import numpy as np

from ..config import settings
from ..llm import pricing
from ..llm.client import CostMeter, meta
from .common import abs_path
from .maskcodec import decode_mask_to_raster
from .sam import fit_raster, object_prompt

INLINE_LIMIT = 45 * 1024 * 1024


def _video_bytes(asset: dict[str, Any]) -> bytes:
    if asset["kind"] != "video":
        raise ValueError("not a video")
    return abs_path(asset["path"]).read_bytes()


def frames(asset: dict[str, Any], every: int = 1, max_frames: int | None = None) -> list[tuple[int, np.ndarray]]:
    cap = cv2.VideoCapture(str(abs_path(asset["path"])))
    out: list[tuple[int, np.ndarray]] = []
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if i % every == 0:
            out.append((i, fr))
            if max_frames and len(out) >= max_frames:
                break
        i += 1
    cap.release()
    return out


def stills(asset: dict[str, Any], n: int = 3) -> list[np.ndarray]:
    """n frames spread over the clip, for a look at what it shows without decoding every frame."""
    cap = cv2.VideoCapture(str(abs_path(asset["path"])))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    out = []
    for k in range(n):
        if total > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int((k + 0.5) / n * total))
        ok, fr = cap.read()
        if ok:
            out.append(fr)
    cap.release()
    return out


def decode_video(raw: str, width: int, height: int, keep_masks: bool = False, every: int = 1) -> dict[str, Any]:
    parser = msp.video_segmentation_format().create_parser()
    parser.push(raw)
    records = parser.finish(msp.CompletedOutcome()).result.records
    by_frame: dict[int, list[dict[str, Any]]] = {}
    masks: dict[tuple[int, str], np.ndarray] = {}
    for r in records:
        if not isinstance(r, msp.SegmentationMaskRecord):
            continue
        fi = r.frame.frame_index if r.frame else 0
        l, t = int(round(r.bounds.left)), int(round(r.bounds.top))
        bw, bh = int(round(r.bounds.right)) - l, int(round(r.bounds.bottom)) - t
        raster = fit_raster(decode_mask_to_raster(r.mask), r.mask.width, r.mask.height, bw, bh)
        by_frame.setdefault(fi, []).append({"id": str(r.object_id), "bbox": [l, t, l + bw, t + bh],
                                            "score": r.confidence, "area": int(raster.sum())})
        if keep_masks and fi % every == 0:
            full = np.zeros((height, width), bool)
            h = min(raster.shape[0], height - t)
            w = min(raster.shape[1], width - l)
            if h > 0 and w > 0:
                full[t : t + h, l : l + w] = raster[:h, :w] > 0
            masks[(fi, str(r.object_id))] = full
    out: dict[str, Any] = {"frames": {k: by_frame[k] for k in sorted(by_frame)}, "objects": sorted({o["id"] for v in by_frame.values() for o in v})}
    if keep_masks:
        out["masks"] = masks
    return out


async def track(meter: CostMeter, asset: dict[str, Any], *, text: str | None = None, points: list[dict[str, Any]] | None = None,
                box: list[float] | None = None, frame: int = 0, keep_masks: bool = False, every: int = 5) -> dict[str, Any]:
    """Track an object (concept phrase, or points/box on `frame`) through the clip.

    Billing is per frame with a 50-frame minimum per request; the budget is checked
    against the clip's frame count before upload.
    """
    m = asset.get("meta") or {}
    n_frames = int(m.get("frames") or 0) or 300
    cost = max(n_frames, pricing.SAM_MIN_FRAMES) * pricing.SAM_PER_FRAME
    meter.check(cost)
    w, h = int(asset.get("width") or 0), int(asset.get("height") or 0)
    if text:
        prompt = text
    else:
        p = object_prompt(w, h, points, box)
        prompt = p.replace("<0f>", f"<{int(frame)}f>", 1)
    file_id = await meta().upload(_video_bytes(asset), "clip.mp4", "video/mp4")
    raw = await meta().sam_video(meter, file_id, prompt, n_frames)
    res = decode_video(raw, w, h, keep_masks=keep_masks, every=every)
    res["frames_billed"] = max(n_frames, pricing.SAM_MIN_FRAMES)
    return res


async def understand(meter: CostMeter, asset: dict[str, Any], question: str) -> str:
    """Muse Spark 1.2 watches the clip with its sound (1.3 audio is degraded per docs)."""
    data = _video_bytes(asset)
    if len(data) <= INLINE_LIMIT:
        part = {"type": "input_video", "video_url": "data:video/mp4;base64," + base64.b64encode(data).decode()}
    else:
        part = {"type": "input_file", "file_id": await meta().upload(data, "clip.mp4", "video/mp4")}
    transcript = (asset.get("meta") or {}).get("transcript")
    text = question + (f"\n\nSpeech transcript (may help): {transcript}" if transcript else "")
    resp = await meta().respond(
        meter,
        model=settings().model_audio,
        input=[{"type": "message", "role": "user", "content": [{"type": "input_text", "text": text}, part]}],
        max_output_tokens=4000,
        purpose="video",
    )
    return resp.output_text or ""
