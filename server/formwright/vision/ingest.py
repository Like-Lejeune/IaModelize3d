"""Upload ingestion: validate, normalize, strip metadata, thumbnail, transcribe.

Photos keep only what measurement needs from EXIF (35 mm-equivalent focal length,
make, model) in `meta.exif`; the stored file has no metadata at all (no GPS).
"""
from __future__ import annotations

import asyncio
import glob
import io
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import settings
from ..db import get_db, new_id, now
from ..llm.client import CostMeter, meta
from .common import encode_jpeg, write_bytes

log = logging.getLogger(__name__)

IMAGE_KINDS = {"photo", "sketch", "caliper", "concept", "render", "print"}
VIDEO_EXT = {".mp4", ".mov", ".m4v"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".oga", ".webm", ".aac", ".flac", ".opus"}
MAX_SIDE = 4096
THUMB = 512
PRINT_KEYWORDS = ["M2", "M3", "M4", "M5", "M6", "M8", "mm", "PLA", "PETG", "ABS", "ASA", "TPU", "caliper", "thread", "bolt", "screw",
                  "nut", "insert", "bracket", "hook", "shelf", "adapter", "infill", "Gridfinity", "VESA", "E27"]

EXIF_IFD = 0x8769
TAG_MAKE, TAG_MODEL = 0x010F, 0x0110
TAG_FOCAL, TAG_FOCAL35 = 0x920A, 0xA405


def _exif_info(img: Image.Image) -> dict[str, Any]:
    info: dict[str, Any] = {}
    try:
        exif = img.getexif()
    except Exception:  # noqa: BLE001
        return info
    if not exif:
        return info
    for tag, key in ((TAG_MAKE, "make"), (TAG_MODEL, "model")):
        v = exif.get(tag)
        if v:
            info[key] = str(v).strip("\x00 ").strip()
    try:
        sub = exif.get_ifd(EXIF_IFD)
    except Exception:  # noqa: BLE001
        sub = {}
    f35 = sub.get(TAG_FOCAL35)
    f = sub.get(TAG_FOCAL)
    if f35:
        info["focal_35mm"] = float(f35)
    if f:
        try:
            info["focal_mm"] = float(f)
        except (TypeError, ValueError):
            pass
    return info


def _thumb(img: np.ndarray) -> bytes:
    h, w = img.shape[:2]
    k = THUMB / max(h, w)
    if k < 1:
        img = cv2.resize(img, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
    return encode_jpeg(img, 85)


def ffmpeg_bin() -> str | None:
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        hits = glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "**", "bin", "ffmpeg.exe"), recursive=True)
        if hits:
            return hits[0]
    return None


def _ext(filename: str) -> str:
    return Path(filename).suffix.lower()


def detect_kind(kind: str, filename: str, mime: str, data: bytes) -> str:
    ext = _ext(filename)
    if mime.startswith("video/") or ext in VIDEO_EXT:
        return "video"
    if mime.startswith("audio/") or ext in AUDIO_EXT:
        return "audio"
    return kind if kind in IMAGE_KINDS else "photo"


def _decode_photo(data: bytes) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        pil = Image.open(io.BytesIO(data))
        pil.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ValueError("unsupported image (use JPEG, PNG or WebP)") from e
    exif = _exif_info(pil)
    pil = ImageOps.exif_transpose(pil)
    if pil.mode not in ("RGB", "L"):
        bg = Image.new("RGB", pil.size, (255, 255, 255))
        bg.paste(pil.convert("RGBA"), mask=pil.convert("RGBA").split()[-1])
        pil = bg
    rgb = np.asarray(pil.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), exif


async def _blur(img: np.ndarray) -> tuple[np.ndarray, int]:
    if os.environ.get("FW_BLUR_FACES", "1") == "0" or not settings().meta_api_key:
        return img, 0
    from .privacy import blur_people

    try:
        return await blur_people(CostMeter(budget_usd=0.02), img)
    except Exception as e:  # noqa: BLE001 — privacy pass must never block an upload
        log.warning("face blur skipped: %s", e)
        return img, 0


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, timeout=180, check=False)


async def to_wav(data: bytes, suffix: str) -> bytes:
    ff = ffmpeg_bin()
    if not ff:
        if suffix == ".wav":
            return data
        raise ValueError("audio conversion needs ffmpeg on the server")
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / f"in{suffix or '.bin'}"
        dst = Path(d) / "out.wav"
        src.write_bytes(data)
        res = await asyncio.to_thread(_run, [ff, "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le",
                                             "-map_metadata", "-1", str(dst)])
        if res.returncode != 0 or not dst.exists():
            raise ValueError(f"could not read audio: {res.stderr.decode(errors='ignore')[-300:]}")
        return dst.read_bytes()


async def transcribe(wav: bytes) -> str:
    if not settings().meta_api_key:
        return ""
    meter = CostMeter(budget_usd=0.05)
    try:
        return await meta().transcribe(meter, wav, keywords=PRINT_KEYWORDS, languages=["English", "Russian"])
    except Exception:  # noqa: BLE001 — retry without language bias (names may not be accepted)
        try:
            return await meta().transcribe(meter, wav, keywords=PRINT_KEYWORDS)
        except Exception as e:  # noqa: BLE001
            log.warning("transcription failed: %s", e)
            return ""


async def ingest_asset(project_id: str, kind: str, filename: str, data: bytes, mime: str) -> dict[str, Any]:
    if not data:
        raise ValueError("empty file")
    kind = detect_kind(kind, filename, mime or "", data)
    aid = new_id("a_")
    base = f"{project_id}/{aid}"
    meta_info: dict[str, Any] = {"original_name": Path(filename).name[:120], "size_bytes": len(data)}
    width = height = None

    if kind in IMAGE_KINDS:
        img, exif = _decode_photo(data)
        h, w = img.shape[:2]
        if max(h, w) > MAX_SIDE:
            k = MAX_SIDE / max(h, w)
            img = cv2.resize(img, (round(w * k), round(h * k)), interpolation=cv2.INTER_AREA)
            meta_info["downscaled_from"] = [w, h]
        if kind in ("photo", "caliper", "print"):
            img, faces = await _blur(img)
            if faces:
                meta_info["faces_blurred"] = faces
        height, width = img.shape[:2]
        if exif:
            meta_info["exif"] = exif
        path = write_bytes(f"{base}.jpg", encode_jpeg(img))  # re-encoded: no metadata survives
        meta_info["thumb"] = write_bytes(f"{base}_thumb.jpg", _thumb(img))
        mime = "image/jpeg"
    elif kind == "video":
        ext = _ext(filename) if _ext(filename) in VIDEO_EXT else ".mp4"
        path = write_bytes(f"{base}{ext}", data)
        from .common import abs_path

        cap = cv2.VideoCapture(str(abs_path(path)))
        if not cap.isOpened():
            raise ValueError("cannot read video (use MP4/MOV with H.264/H.265)")
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frames // 3))
        ok, frame = cap.read()
        cap.release()
        meta_info.update({"fps": round(fps, 3), "frames": frames, "duration_s": round(frames / fps, 3) if fps else None})
        if ok:
            meta_info["thumb"] = write_bytes(f"{base}_thumb.jpg", _thumb(frame))
            meta_info["poster"] = write_bytes(f"{base}_poster.jpg", encode_jpeg(frame))
        try:
            wav = await to_wav(data, ext)
            meta_info["transcript"] = await transcribe(wav)
        except ValueError:
            pass  # silent video or no ffmpeg
        mime = "video/mp4" if ext != ".mov" else "video/quicktime"
    else:  # audio
        wav = await to_wav(data, _ext(filename))
        path = write_bytes(f"{base}.wav", wav)
        meta_info["duration_s"] = round(max(0, len(wav) - 44) / (24000 * 2), 2)
        meta_info["transcript"] = await transcribe(wav)
        mime = "audio/wav"

    db = await get_db()
    await db.insert("assets", {"id": aid, "project_id": project_id, "kind": kind, "path": path, "mime": mime, "width": width, "height": height,
                               "meta": meta_info, "created_at": now()})
    return await db.one("SELECT * FROM assets WHERE id = ?", aid)  # type: ignore[return-value]
