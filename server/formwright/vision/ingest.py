"""Upload ingestion: validate, normalize, strip metadata, thumbnail, transcribe.

Photos keep only what measurement needs from EXIF (35 mm-equivalent focal length,
make, model) in `meta.exif`; the stored file has no metadata at all (no GPS). Videos are
remuxed by ffmpeg without their metadata (a phone's location, camera and time tags).
"""
from __future__ import annotations

import asyncio
import glob
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .. import quotas
from ..config import settings
from ..db import get_db, new_id, now
from ..llm.client import CostMeter, meta
from .common import encode_jpeg, write_bytes

log = logging.getLogger(__name__)

IMAGE_KINDS = {"photo", "sketch", "caliper", "concept", "render", "print"}
VIDEO_EXT = {".mp4", ".mov", ".m4v"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".ogg", ".oga", ".webm", ".aac", ".flac", ".opus"}
MESH_EXT = {".stl", ".obj"}
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
    if ext in MESH_EXT or mime in ("model/stl", "model/obj"):
        return "mesh"
    if mime.startswith("video/") or ext in VIDEO_EXT:
        return "video"
    if mime.startswith("audio/") or ext in AUDIO_EXT:
        return "audio"
    return kind if kind in IMAGE_KINDS else "photo"


def _decode_photo(data: bytes) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        pil = Image.open(io.BytesIO(data))
        pil.load()
    except Image.DecompressionBombError as e:
        raise ValueError("photo is too large") from e
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


async def _owner(project_id: str) -> dict[str, Any] | None:
    db = await get_db()
    return await db.one("SELECT u.* FROM users u JOIN projects p ON p.user_id = u.id WHERE p.id = ?", project_id)


async def _blur(img: np.ndarray, user: dict[str, Any] | None = None) -> tuple[np.ndarray, int]:
    """`user`: whose daily budget pays for it; when that is spent the photo is refused, not kept unblurred."""
    if not settings().blur_faces or not settings().meta_api_key:
        return img, 0
    from .privacy import blur_people

    if user:
        await quotas.check_light(user, 0.005)
    meter = CostMeter(budget_usd=0.02)
    try:
        return await blur_people(meter, img)
    except Exception as e:  # noqa: BLE001 — privacy pass must never block an upload
        log.warning("face blur skipped: %s", e)
        return img, 0
    finally:
        if user:
            await quotas.settle(user["id"], meter.usd, is_job=False)


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


async def _strip_video(data: bytes, suffix: str) -> bytes:
    """The video without its metadata (a phone's GPS location, camera model, time) and chapters; the streams are copied
    as they are. Refused when ffmpeg is missing or cannot read it: a stored video is served as uploaded."""
    ff = ffmpeg_bin()
    if not ff:
        raise ValueError("videos need ffmpeg on the server (it removes their location tags)")
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / f"in{suffix}", Path(d) / f"out{suffix}"
        src.write_bytes(data)
        res = await asyncio.to_thread(_run, [ff, "-y", "-loglevel", "error", "-i", str(src), "-map", "0", "-map_metadata", "-1",
                                             "-map_metadata:s", "-1", "-map_chapters", "-1", "-c", "copy", "-fflags", "+bitexact", str(dst)])
        if res.returncode != 0 or not dst.exists() or not dst.stat().st_size:
            raise ValueError("cannot read video (use MP4/MOV with H.264/H.265)")
        return dst.read_bytes()


UPLOAD_MB_DAY = {"anon": 200}  # stored uploads a day per person, by tier (others: UPLOAD_MB_DAY_OTHER)
UPLOAD_MB_DAY_OTHER = 2000
UPLOAD_MB_NETWORK = 500  # and by every anonymous visitor of one network together (users.ip)


async def upload_quota(project_id: str, size: int) -> None:
    """A day's uploads, counted from the stored assets of the project owner's projects: QuotaExceeded 'upload_quota'
    (a 429) past the limit, so a script cannot fill the server's disk. A new cookie is a new anonymous user, so their
    uploads also count per network."""
    owner = await _owner(project_id)
    if not owner:
        return
    db = await get_db()
    since = now() - 86400
    total = "SELECT COALESCE(SUM(json_extract(a.meta, '$.size_bytes')), 0) AS n FROM assets a JOIN projects p ON p.id = a.project_id "
    row = await db.one(total + "WHERE p.user_id = ? AND a.created_at > ?", owner["id"], since)
    if float((row or {}).get("n") or 0) + size > UPLOAD_MB_DAY.get(owner["tier"], UPLOAD_MB_DAY_OTHER) * 1e6:
        raise quotas.QuotaExceeded("today's uploads for this account are used up; try again tomorrow", code="upload_quota")
    if owner["tier"] == "anon" and owner.get("ip"):
        row = await db.one(total + "JOIN users u ON u.id = p.user_id WHERE u.tier = 'anon' AND u.ip = ? AND a.created_at > ?", owner["ip"], since)
        if float((row or {}).get("n") or 0) + size > UPLOAD_MB_NETWORK * 1e6:
            raise quotas.QuotaExceeded("today's uploads from this network are used up; try again tomorrow", code="upload_quota")


async def transcribe(wav: bytes, user: dict[str, Any] | None = None) -> str:
    """The spoken text; raises when the speech could not be transcribed (or `user`, who pays for it, has
    spent today's budget)."""
    if not settings().meta_api_key:
        raise RuntimeError("speech recognition is not set up on this server")
    if user:
        await quotas.check_light(user, 0.005)
    meter = CostMeter(budget_usd=0.05)
    try:
        return await meta().transcribe(meter, wav, keywords=PRINT_KEYWORDS, languages=["English", "Russian"])
    except Exception:  # noqa: BLE001 — retry without language bias (names may not be accepted)
        return await meta().transcribe(meter, wav, keywords=PRINT_KEYWORDS)
    finally:
        if user:
            await quotas.settle(user["id"], meter.usd, is_job=False)


async def _transcript(wav: bytes, user: dict[str, Any] | None = None) -> dict[str, str]:
    """meta.transcript, plus meta.transcript_error when the speech could not be read (the upload still succeeds)
    and meta.transcript_code when today's limit stopped it (the QuotaExceeded code, e.g. 'daily_limit').
    `user`: the project's owner, billed for it; with nobody to bill it is the plain one-argument call."""
    try:
        return {"transcript": await (transcribe(wav, user) if user else transcribe(wav))}
    except quotas.QuotaExceeded as e:
        return {"transcript": "", "transcript_error": str(e)[:200], "transcript_code": e.code}
    except Exception as e:  # noqa: BLE001
        log.warning("transcription failed: %s", e)
        return {"transcript": "", "transcript_error": str(e)[:200] or type(e).__name__}


async def ingest_asset(project_id: str, kind: str, filename: str, data: bytes, mime: str) -> dict[str, Any]:
    if not data:
        raise ValueError("empty file")
    await upload_quota(project_id, len(data))
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
            img, faces = await _blur(img, await _owner(project_id))
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
        data = await _strip_video(data, ext)  # a phone writes where and with what it was filmed; photos lose it too
        path = write_bytes(f"{base}{ext}", data)
        from .common import abs_path

        cap = cv2.VideoCapture(str(abs_path(path)))
        if not cap.isOpened():
            cap.release()
            abs_path(path).unlink(missing_ok=True)  # a refused upload leaves nothing on disk
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
        except ValueError:
            wav = None  # silent video or no ffmpeg
        if wav:
            meta_info.update(await _transcript(wav, await _owner(project_id)))
        mime = "video/mp4" if ext != ".mov" else "video/quicktime"
    elif kind == "mesh":
        from ..geom import GeomError, geom

        ext = _ext(filename) if _ext(filename) in MESH_EXT else ".stl"
        try:
            parsed = await geom().parse_mesh(data, ext)
        except GeomError as e:
            raise ValueError(f"cannot read the mesh: {e.message[:200]}") from e
        stats = parsed["stats"]
        if stats["triangles"] > 400_000:
            raise ValueError("mesh is too dense (over 400k triangles): decimate it first")
        b = stats["bbox"]
        meta_info["mesh"] = {"vertices": stats["vertices"], "triangles": stats["triangles"], "closed": stats["closed"],
                             "volume_mm3": round(stats["volume"], 1), "size_mm": [round(b["max"][i] - b["min"][i], 2) for i in range(3)],
                             "name": re.sub(r"[^A-Za-z0-9_]+", "_", Path(filename).stem)[:40].strip("_") or "mesh"}
        if not stats["closed"]:
            meta_info["mesh"]["problem"] = stats.get("reason", "")[:200]
        path = write_bytes(f"{base}{ext}", data)
        mime = "model/stl" if ext == ".stl" else "model/obj"
    else:  # audio
        wav = await to_wav(data, _ext(filename))
        path = write_bytes(f"{base}.wav", wav)
        meta_info["duration_s"] = round(max(0, len(wav) - 44) / (24000 * 2), 2)
        meta_info.update(await _transcript(wav, await _owner(project_id)))
        mime = "audio/wav"

    db = await get_db()
    await db.insert("assets", {"id": aid, "project_id": project_id, "kind": kind, "path": path, "mime": mime, "width": width, "height": height,
                               "meta": meta_info, "created_at": now()})
    return await db.one("SELECT * FROM assets WHERE id = ?", aid)  # type: ignore[return-value]
