"""Blur faces before a photo is stored or sent to any other model."""
from __future__ import annotations

import cv2
import numpy as np

from ..llm.client import CostMeter
from .sam import segment


def blur_regions(img: np.ndarray, masks: list[np.ndarray]) -> np.ndarray:
    if not masks:
        return img
    region = np.zeros(img.shape[:2], dtype=np.uint8)
    for m in masks:
        region |= m.astype(np.uint8)
    k = max(3, (max(img.shape[:2]) // 60) | 1)
    region = cv2.dilate(region, np.ones((k, k), np.uint8))
    blurred = cv2.GaussianBlur(img, (0, 0), sigmaX=max(6, k))
    out = img.copy()
    out[region > 0] = blurred[region > 0]
    return out


async def blur_people(meter: CostMeter, image: np.ndarray) -> tuple[np.ndarray, int]:
    """SAM 3.1 'face' concept → blur every match. Returns (image, faces blurred)."""
    masks = [m.mask for m in await segment(meter, image, text="face") if m.score >= 0.4]
    return blur_regions(image, masks), len(masks)
