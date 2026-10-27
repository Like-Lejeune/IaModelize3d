"""Optional: metric multi-view reconstruction with Meta's MapAnything (Apache-2.0
checkpoint `facebook/map-anything-apache`), served by `infra/modal_mapanything.py`.

Several ordinary photos of a scene (a shelf from three angles) -> camera poses and a
point cloud in metres. The reference object / caliper then fixes the scale exactly.
This measures the scene; it does not generate the model.
"""
from __future__ import annotations

import base64
import os
from typing import Any

import httpx
import numpy as np

from .common import asset_image, encode_jpeg


def endpoint() -> str:
    return os.environ.get("FW_MAPANYTHING_URL", "")


def available() -> bool:
    return bool(endpoint())


async def reconstruct(assets: list[dict[str, Any]], max_side: int = 1024, timeout: float = 600) -> dict[str, Any]:
    """POST the photos; returns {"views": [{"asset_id", "pose" 4x4 cam->world, "intrinsics" 3x3}], "points": Nx3 (m), "colors": Nx3}."""
    if not available():
        raise RuntimeError("MapAnything endpoint not configured (FW_MAPANYTHING_URL)")
    images = []
    for a in assets:
        img = asset_image(a)
        k = max_side / max(img.shape[:2])
        if k < 1:
            import cv2

            img = cv2.resize(img, (round(img.shape[1] * k), round(img.shape[0] * k)), interpolation=cv2.INTER_AREA)
        images.append({"id": a["id"], "jpeg": base64.b64encode(encode_jpeg(img, 90)).decode()})
    headers = {}
    if os.environ.get("FW_MAPANYTHING_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['FW_MAPANYTHING_TOKEN']}"
    async with httpx.AsyncClient(timeout=timeout) as h:
        r = await h.post(endpoint(), json={"images": images}, headers=headers)
        r.raise_for_status()
        return r.json()


def scale_to_mm(points_m: np.ndarray, measured_mm: float, measured_m: float) -> np.ndarray:
    """Fix the metric scale with one known distance (reference edge or caliper reading)."""
    return np.asarray(points_m, float) * (measured_mm / max(measured_m, 1e-9))
