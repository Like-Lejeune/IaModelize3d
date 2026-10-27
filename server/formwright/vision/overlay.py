"""Photo-AR: composite a render made with the photo's camera over the photo."""
from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from ..db import new_id
from .common import asset_image, encode_jpeg, write_bytes


def blend(photo: np.ndarray, render_rgba: np.ndarray, opacity: float = 0.85) -> np.ndarray:
    h, w = photo.shape[:2]
    if render_rgba.shape[:2] != (h, w):
        render_rgba = cv2.resize(render_rgba, (w, h), interpolation=cv2.INTER_LINEAR)
    if render_rgba.shape[2] == 3:
        alpha = np.ones((h, w, 1), np.float32) * opacity
        rgb = render_rgba
    else:
        alpha = render_rgba[..., 3:4].astype(np.float32) / 255.0 * opacity
        rgb = render_rgba[..., :3]
    out = photo.astype(np.float32) * (1 - alpha) + rgb.astype(np.float32) * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def compose(asset: dict[str, Any], render_png: bytes, opacity: float = 0.85) -> str:
    """Overlay a PNG render (RGBA, rendered with `scene.camera_for_render(asset)`) on the photo.

    The renderer writes RGBA; OpenCV decodes PNGs as BGRA, matching the photo's BGR.
    Returns the path relative to the files directory.
    """
    render = cv2.imdecode(np.frombuffer(render_png, np.uint8), cv2.IMREAD_UNCHANGED)
    if render is None:
        raise ValueError("render is not a PNG")
    if render.ndim == 2:
        render = cv2.cvtColor(render, cv2.COLOR_GRAY2BGRA)
    out = blend(asset_image(asset), render, opacity)
    return write_bytes(f"{asset['project_id']}/{asset['id']}_overlay_{new_id()[:8]}.jpg", encode_jpeg(out, 88))
