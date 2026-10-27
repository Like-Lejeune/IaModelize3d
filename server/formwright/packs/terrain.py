"""Real terrain from open elevation data (AWS Terrain Tiles, Terrarium encoding).

elevation_m = R*256 + G + B/256 - 32768. Tiles: https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png
"""
from __future__ import annotations

import asyncio
import io
import math
from typing import Any

import cv2
import httpx
import numpy as np
from PIL import Image

from ..llm.client import CostMeter, meta

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

GEO_SCHEMA = {
    "type": "object",
    "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}, "name": {"type": "string"}},
    "required": ["lat", "lon", "name"],
}


def _tile_xy(lat: float, lon: float, z: int) -> tuple[float, float]:
    n = 2**z
    x = (lon + 180) / 360 * n
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
    return x, y


async def geocode(meter: CostMeter, place: str, model: str | None = None) -> dict[str, Any]:
    found = await meta().search(meter, f"Latitude and longitude (decimal degrees) of: {place}", model=model)
    return await meta().json(meter, model=model or "muse-spark-1.3", system="Extract the coordinates of the place.",
                             content=[{"type": "input_text", "text": f"Place: {place}\n{found['text']}"}], schema=GEO_SCHEMA, name="geo", effort="minimal")


async def _fetch(client: httpx.AsyncClient, z: int, x: int, y: int) -> np.ndarray:
    r = await client.get(TILE_URL.format(z=z, x=x, y=y))
    r.raise_for_status()
    rgb = np.asarray(Image.open(io.BytesIO(r.content)).convert("RGB"), dtype=np.float64)
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


async def heightmap(lat: float, lon: float, size_km: float, grid: int = 160) -> dict[str, Any]:
    size_km = max(0.2, min(size_km, 200))
    # pick a zoom where the area spans ~2-4 tiles
    z = int(max(5, min(14, math.log2(40075 * math.cos(math.radians(lat)) / size_km) + 1)))
    half = size_km / 2
    dlat = half / 110.574
    dlon = half / (111.320 * math.cos(math.radians(lat)))
    x0, y0 = _tile_xy(lat + dlat, lon - dlon, z)
    x1, y1 = _tile_xy(lat - dlat, lon + dlon, z)
    tx = range(int(x0), int(x1) + 1)
    ty = range(int(y0), int(y1) + 1)
    async with httpx.AsyncClient(timeout=30) as client:
        rows = []
        for y in ty:
            tiles = await asyncio.gather(*[_fetch(client, z, x, y) for x in tx])
            rows.append(np.concatenate(tiles, axis=1))
    mosaic = np.concatenate(rows, axis=0)
    px0, py0 = (x0 - tx.start) * 256, (y0 - ty.start) * 256
    px1, py1 = (x1 - tx.start) * 256, (y1 - ty.start) * 256
    xs = np.linspace(px0, px1, grid)
    ys = np.linspace(py0, py1, grid)
    xi = np.clip(xs.astype(int), 0, mosaic.shape[1] - 1)
    yi = np.clip(ys.astype(int), 0, mosaic.shape[0] - 1)
    data = mosaic[np.ix_(yi, xi)]
    data = np.maximum(data, -50)  # bathymetry: clamp to near sea level
    # Elevation tiles carry single-cell spikes that print as needles; a light blur removes them.
    data = cv2.GaussianBlur(data.astype(np.float32), (0, 0), sigmaX=0.8).astype(np.float64)
    return {
        "w": grid, "h": grid, "data": [round(float(v), 1) for v in data.flatten()],
        "lat": lat, "lon": lon, "size_km": size_km, "zoom": z,
        "min_m": round(float(data.min()), 1), "max_m": round(float(data.max()), 1),
        "relief_m": round(float(data.max() - data.min()), 1),
        "source": "AWS Terrain Tiles (Terrarium; SRTM/GMTED/ETOPO1 and others)",
        "hint": "use lib.forms.terrain(lib.inputs.heightmaps.terrain, {sizeX, maxHeight, base}); true scale vertical = relief_m / (size_km*1e6/sizeX) mm",
    }


async def load(meter: CostMeter, *, place: str | None, lat: float | None, lon: float | None, size_km: float, model: str | None = None) -> dict[str, Any]:
    name = place
    if lat is None or lon is None:
        if not place:
            raise ValueError("need a place name or lat/lon")
        geo = await geocode(meter, place, model)
        lat, lon, name = geo["lat"], geo["lon"], geo.get("name") or place
    hm = await heightmap(float(lat), float(lon), size_km)
    hm["place"] = name
    return hm
