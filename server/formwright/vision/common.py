"""Shared helpers for the vision pipeline: file locations, image IO, data URLs."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from ..config import settings
from ..storage import write_atomic


def files_dir() -> Path:
    d = settings().data_dir / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def abs_path(rel: str) -> Path:
    return files_dir() / rel


def read_image(src: str | Path | np.ndarray) -> np.ndarray:
    """BGR uint8 image from an array, an absolute path or a path relative to the files dir."""
    if isinstance(src, np.ndarray):
        return src
    p = Path(src)
    if not p.is_absolute():
        p = abs_path(str(src))
    img = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot read image {p}")
    return img


def asset_image(asset: dict[str, Any]) -> np.ndarray:
    return read_image(asset["path"])


def encode_jpeg(img: np.ndarray, quality: int = 92) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ValueError("jpeg encode failed")
    return buf.tobytes()


def encode_png(img: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("png encode failed")
    return buf.tobytes()


def write_bytes(rel: str, data: bytes) -> str:
    p = abs_path(rel)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(p, data)
    return rel


def data_url(img: np.ndarray, max_side: int | None = None, quality: int = 90) -> str:
    """JPEG data URL. With max_side the image is downscaled (coordinates then refer to the small image)."""
    if max_side and max(img.shape[:2]) > max_side:
        k = max_side / max(img.shape[:2])
        img = cv2.resize(img, (round(img.shape[1] * k), round(img.shape[0] * k)), interpolation=cv2.INTER_AREA)
    return "data:image/jpeg;base64," + base64.b64encode(encode_jpeg(img, quality)).decode()


def norm_box_to_px(box: list[float], width: int, height: int) -> list[int]:
    """Muse Spark grounding boxes are on a 0..1000 grid (may slightly overshoot)."""
    x1, y1, x2, y2 = (max(0.0, min(1000.0, float(v))) for v in box[:4])
    return [round(x1 / 1000 * width), round(y1 / 1000 * height), round(x2 / 1000 * width), round(y2 / 1000 * height)]


def as_list(m: np.ndarray, nd: int = 6) -> list:
    return np.round(np.asarray(m, dtype=float), nd).tolist()
