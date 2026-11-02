"""The fast SAM mask decoder gives the reference decoder's raster bit for bit, and the parser uses it."""
from __future__ import annotations

import numpy as np
import pytest
from meta_sam_parser import _mask_codec as ref
from meta_sam_parser import _segmentation
from meta_sam_parser._types import SegmentationMask

from formwright.vision import maskcodec


def _shapes(w: int, h: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[:h, :w]
    m = np.zeros((h, w), dtype=np.uint8)
    for _ in range(4):
        cx, cy, r = rng.uniform(0, w), rng.uniform(0, h), rng.uniform(1, max(2, max(w, h) / 2))
        m ^= ((xx - cx) ** 2 + (yy - cy) ** 2 < r * r).astype(np.uint8)  # rings and holes
    m[rng.random((h, w)) < 0.01] ^= 1  # speckle the context model has to learn
    return m


@pytest.mark.parametrize("w,h,seed", [(1, 1, 0), (3, 2, 1), (37, 23, 2), (160, 90, 3), (257, 300, 4)])
def test_same_as_reference(w, h, seed):
    bits = _shapes(w, h, seed).ravel().tolist()
    payload = ref._encode_raster(bits, w, h)
    assert maskcodec._decode_one_bit(payload, w, h) == bytes(bits)


def test_empty_and_full():
    for fill in (0, 1):
        bits = [fill] * (64 * 48)
        payload = ref._encode_raster(bits, 64, 48)
        assert maskcodec.decode_mask_to_raster(SegmentationMask(encoding="one_bit", payload=payload, width=64, height=48)) == bytes(bits)


def test_parser_uses_it_and_bad_payloads_still_fail():
    assert _segmentation.decode_mask_to_raster is maskcodec.decode_mask_to_raster
    with pytest.raises(Exception):
        maskcodec.decode_mask_to_raster(SegmentationMask(encoding="one_bit", payload="!00", width=8, height=8))
