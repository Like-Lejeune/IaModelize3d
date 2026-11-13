"""Fast decoding of SAM's one_bit masks.

The reference decoder in meta_sam_parser reads twelve neighbours per pixel through helper
calls and then re-encodes the mask to check it is canonical; the parser runs that check on
every mask it accepts. On a 1024 px mask that is about 5 s of pure Python per decode, and a
selection used to pay it three times. This is the same adaptive range decoder with the
context kept in rolling bit fields and everything in local variables, run once per payload:
the parser's own check and the caller's decode share the cached raster.
"""
from __future__ import annotations

from collections import OrderedDict

import meta_sam_parser._segmentation as _segmentation
from meta_sam_parser import _mask_codec as _ref
from meta_sam_parser._types import SegmentationMask

_reference_decode = _ref.decode_mask_to_raster
_cache: OrderedDict[tuple[str, int, int], bytes] = OrderedDict()
_CACHE_SIZE = 8


def _decode_one_bit(payload: str, width: int, height: int) -> bytes:
    data = _ref._unpack(payload[1:])
    n = len(data)
    if n < 4:
        raise ValueError("payload is missing its finalization")
    code = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]
    pos = 4
    low = 0
    rng = 0xFFFFFFFF
    counts = [1] * (2 * 4096)
    out = bytearray(width * height)
    pw = width + 5  # two zero columns left, three right (one ahead of the window)
    earlier = bytearray(pw)
    prior = bytearray(pw)
    for y in range(height):
        cur = bytearray(pw)
        # bit fields of the neighbours at x = 0: rows y-1 and y-2 span x-2..x+2
        pf = prior[0] | (prior[1] << 1) | (prior[2] << 2) | (prior[3] << 3) | (prior[4] << 4)
        ef = earlier[0] | (earlier[1] << 1) | (earlier[2] << 2) | (earlier[3] << 3) | (earlier[4] << 4)
        cf = 0  # x-1 in bit 0, x-2 in bit 1
        base = y * width
        for x in range(width):
            off = (cf | (pf << 2) | (ef << 7)) << 1
            zero = counts[off]
            one = counts[off + 1]
            scaled = rng // (zero + one)
            if scaled == 0:
                raise ValueError("invalid coding state")
            value = ((code - low) & 0xFFFFFFFF) // scaled
            if value < zero:
                bit = 0
                rng = scaled * zero
                zero += 14
                counts[off] = zero
            else:
                bit = 1
                low = (low + scaled * zero) & 0xFFFFFFFF
                rng = scaled * one
                one += 14
                counts[off + 1] = one
                out[base + x] = 1
                cur[x + 2] = 1
            if zero + one >= 4096:
                counts[off] = (zero >> 1) or 1
                counts[off + 1] = (one >> 1) or 1
            while True:
                if (low ^ ((low + rng) & 0xFFFFFFFF)) < 0x1000000:
                    pass
                elif rng < 0x10000:
                    rng = (-low) & 0xFFFF
                else:
                    break
                if pos >= n:
                    raise ValueError("payload ended before decoding completed")
                code = ((code << 8) | data[pos]) & 0xFFFFFFFF
                pos += 1
                low = (low << 8) & 0xFFFFFFFF
                rng = (rng << 8) & 0xFFFFFFFF
            cf = ((cf & 1) << 1) | bit
            pf = (pf >> 1) | (prior[x + 5] << 4)
            ef = (ef >> 1) | (earlier[x + 5] << 4)
        earlier, prior = prior, cur
    return bytes(out)


def decode_mask_to_raster(mask: SegmentationMask) -> bytes:
    """Same result as meta_sam_parser.decode_mask_to_raster (0/1 per pixel, row-major), fast and cached."""
    key = (mask.payload, mask.width, mask.height) if isinstance(mask.payload, str) else None
    if key is not None and key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    if mask.encoding != "one_bit" or key is None or not mask.payload.startswith("!") or mask.width <= 0 or mask.height <= 0:
        raster = _reference_decode(mask)
    else:
        try:
            raster = _decode_one_bit(mask.payload, int(mask.width), int(mask.height))
        except Exception:  # noqa: BLE001 - the reference decoder raises the parser's own error
            raster = _reference_decode(mask)
    if key is not None:
        _cache[key] = raster
        if len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return raster


# the parser checks every mask it accepts by decoding it: let it use this decoder (and fill the cache)
_segmentation.decode_mask_to_raster = decode_mask_to_raster
