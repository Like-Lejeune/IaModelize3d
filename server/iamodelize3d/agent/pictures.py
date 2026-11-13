"""The designer's pictures, by name. Every image a tool shows the model gets a name (img7) it can call back, even after the
provider has left it out of a long history.

grid draws labelled coordinates over a picture, so a place on it is read instead of estimated: a straight model view gets real
mm (the views are orthographic, the engine says what its edges are), anything else the 0-1000 grid `look` crops with. A zoom cuts
the full-resolution original and keeps the numbers, so a place is pinned in two calls. collage lays pictures out on one sheet that
counts as one image, which is also what happens to the images of a turn beyond the ones a turn can show."""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import math
import re
import string
import uuid
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .. import storage
from ..db import get_db

log = logging.getLogger(__name__)

IMAGE_KINDS = ("photo", "sketch", "caliper", "concept", "render", "print")
MAX_SHOWN = 4          # images a turn can show the model
SIDE = 1280            # the longest side the model gets of a picture
UPSCALE_MAX = 3.0      # past this a crop only gets blurrier: a model view is better rendered again
BLURRY = 2.0
SHEET_MAX_ITEMS = 12
SHEET_GAP = 8
CAPTION_H = 24
GRID_LINES = 10        # about this many lines across the longer side
LINE_PX_MIN = 26       # lines closer than this leave no room for their labels
FINEST_PX = 16         # the finest a requested step can go
STEPS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000)
GRID_AXES = {"h": "x", "h0": 0.0, "h1": 1000.0, "v": "y", "v0": 0.0, "v1": 1000.0, "unit": "grid"}
LINE = (255, 214, 10, 150)
SHADOW = (0, 0, 0, 100)
LABEL = (255, 225, 60)
CELL = (255, 255, 255)
MARK = (255, 45, 155)
SHEET_BG = (38, 38, 40)


def _fn(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}


_S = {"type": "string"}
_N = {"type": "number"}
IMAGE = {**_S, "description": "a picture's name from the tool results ('img7') or an input image's asset id"}
VIEW = {**_S, "description": "one view of a sheet, by the name written on it ('FRONT', 'TOP', 'SECTION Y=3')"}
REGION = {"description": "the part to cut out, from the full-resolution original: [x1, y1, x2, y2] in the picture's grid numbers (on a model "
                         "view its two mm axes, e.g. [x1, z1, x2, z2]), or cells of the grid drawn on this image: 'C4' or 'C4:E6'"}
MARKS = {"type": "array", "description": "draw places to check them: {at: [a, b], label} or {box: [a1, b1, a2, b2], label}, in the grid's numbers",
         "items": {"type": "object", "properties": {"at": {"type": "array", "items": _N}, "box": {"type": "array", "items": _N}, "label": _S}}}

GRID = _fn(
    "grid",
    "Read exactly where something is on a picture instead of estimating it: draws a labelled coordinate grid over any image. On a "
    "straight model view (FRONT, RIGHT, TOP, BOTTOM, a section seen straight on, a case view from the top or the side) the labels are "
    "real model mm; on a photo or any other picture they are the 0-1000 grid `look` crops with. Every cell has a name (C4). Zoom with "
    "`region`: the numbers stay the same and it cuts the full-resolution original, so two calls pin a place. Then draw your reading "
    "with `marks` to check it. Model-view numbers go straight into a program, inspect_model {op:'surface'} or a look zoom.",
    {"image": IMAGE, "view": VIEW, "region": REGION,
     "step": {**_N, "description": "distance between lines in the grid's numbers (default: about 10 lines)"},
     "marks": MARKS},
    ["image"])
COLLAGE = _fn(
    "collage",
    "Lay up to 12 pictures side by side on one labelled sheet: two versions of a view, the photo next to the model, several crops of a "
    "photo. A sheet is one image however many it holds, and the only way to compare pictures of different turns. It also brings back an "
    "image left out of the history. Each item is an image, optionally one view or a region of it, your marks and a short English label. "
    "Tiles are fitted to their own size, so with mm views compare numbers (grid: true), not lengths on the sheet.",
    {"items": {"type": "array", "description": "the tiles, in order: A, B, C...", "items": {"type": "object", "properties": {
        "image": IMAGE, "view": VIEW, "region": REGION, "marks": MARKS, "label": _S}, "required": ["image"]}},
     "columns": {"type": "integer", "description": "default: a roughly square layout"},
     "grid": {"type": "boolean", "description": "draw the labelled grid on every tile (default false)"}},
    ["items"])

TOOLS = [GRID, COLLAGE]
NAMES = {t["name"] for t in TOOLS}


class Bad(ValueError):
    """A request that cannot be met: told to the model, not a failure of the job."""


# ------------------------------------------------------------------ names
def note(state: Any, ref: str, frames: list[dict[str, Any]] | None = None, clean: str | None = None, region: list[float] | None = None) -> None:
    """What a tool knows about a picture it returns, until the loop gives it a name: the frames of its views (the engine's render), or
    the original it was cut from and where."""
    state.picture_notes[ref] = {"frames": frames, "clean": clean, "region": region}


def _name_of(state: Any, rel: str) -> str | None:
    return next((k for k, p in state.pictures.items() if p["rel"] == rel), None)


def enroll(ctx: Any, state: Any, ref: str, tool: str, **known: Any) -> str:
    """The picture's name. A data URL is kept as a file, so that it can be called back."""
    noted = state.picture_notes.pop(ref, {})
    if ref.startswith("data:"):
        head, data = ref.split(",", 1)
        ref = storage.save_bytes(ctx.project_id, "renders", f"seen_{uuid.uuid4().hex[:10]}.{'png' if 'png' in head else 'jpg'}", base64.b64decode(data))
    else:
        known_name = _name_of(state, ref)
        if known_name:
            return known_name
    name = f"img{len(state.pictures) + 1}"
    state.pictures[name] = {"rel": ref, "tool": tool, "clean": noted.get("clean") or ref, "frames": noted.get("frames"), "view": None,
                            "region": noted.get("region"), "cells": None, **known}
    return name


def shown(ctx: Any, state: Any, images: list[tuple[str, str]]) -> list[tuple[str, str, str]]:
    """(name, tool, ref) of what this turn shows the model. What does not fit goes on one sheet rather than being lost."""
    named = [(enroll(ctx, state, ref, tool), tool, ref) for tool, ref in images]
    if len(named) <= MAX_SHOWN:
        return named
    keep, rest = named[:MAX_SHOWN - 1], named[MAX_SHOWN - 1:MAX_SHOWN - 1 + SHEET_MAX_ITEMS]
    try:
        result = _make_collage(ctx, state, [({**state.pictures[n], "name": n}, {"image": n}) for n, _, _ in rest], None, False)
    except (OSError, ValueError) as e:
        log.warning("the sheet of a turn's images failed: %s", e)
        return named[:MAX_SHOWN]
    return keep + [(result["image"], "collage of " + ", ".join(n for n, _, _ in rest), state.pictures[result["image"]]["rel"])]


async def _resolve(ctx: Any, state: Any, ref: Any) -> dict[str, Any]:
    ref = str(ref or "").strip()
    if ref in state.pictures:
        return {**state.pictures[ref], "name": ref}
    db = await get_db()
    asset = await db.one("SELECT * FROM assets WHERE id = ? AND project_id = ?", ref, ctx.project_id)
    if asset and asset["kind"] in IMAGE_KINDS:
        return {"rel": asset["path"], "clean": asset["path"], "frames": None, "view": None, "region": None, "cells": None, "name": ref}
    if asset and asset["kind"] == "video":
        raise Bad(f"{ref} is a video: look at it first, its frames get names")
    if asset:
        raise Bad(f"{ref} is {asset['kind']}, not an image")
    raise Bad(f"no picture {ref!r}; the latest ones: {', '.join(list(state.pictures)[-12:]) or 'none yet'}")


# ------------------------------------------------------------------ frames: which numbers a picture's pixels are
def _frames(pic: dict[str, Any], size: tuple[int, int]) -> list[dict[str, Any]]:
    if not pic.get("frames"):
        return [{"name": "image", "box": [0, 0, size[0], size[1]], **GRID_AXES}]
    # an oblique view has no mm: it gets the same 0-1000 grid as a photo
    return [{**GRID_AXES, **f, "unit": f.get("unit") or ("mm" if "h" in f else "grid")} for f in pic["frames"]]


def _pick(frames: list[dict[str, Any]], view: Any) -> dict[str, Any]:
    want = str(view).strip().lower()
    for f in frames:
        if str(f["name"]).lower() == want:
            return f
    raise Bad(f"no view {view!r} here; the views: {', '.join(str(f['name']) for f in frames)}")


def _px(f: dict[str, Any], a: float, b: float) -> tuple[float, float]:
    x, y, w, h = f["box"]
    return x + (a - f["h0"]) / (f["h1"] - f["h0"]) * w, y + (b - f["v0"]) / (f["v1"] - f["v0"]) * h


def _numbers(v: Any, n: int, what: str) -> list[float]:
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except json.JSONDecodeError:
            pass
    try:
        out = [float(x) for x in v]
    except (TypeError, ValueError):
        out = []
    if len(out) != n or not all(math.isfinite(x) for x in out):
        raise Bad(f"{what} must be {n} numbers")
    return out


def _region(f: dict[str, Any], region: Any, cells: dict[str, Any] | None) -> tuple[float, float, float, float]:
    """(left, top, right, bottom) of a region in the frame's numbers, inside the frame."""
    m = re.fullmatch(r"\s*([A-Za-z])(\d+)\s*(?::\s*([A-Za-z])(\d+)\s*)?", region) if isinstance(region, str) else None
    if m:
        if not cells:
            raise Bad(f"{region} names cells, and no grid is drawn on this image yet: call grid on it, or give numbers")
        c1, r1 = string.ascii_uppercase.index(m[1].upper()), int(m[2]) - 1
        c2, r2 = string.ascii_uppercase.index((m[3] or m[1]).upper()), int(m[4] or m[2]) - 1
        c1, c2, r1, r2 = min(c1, c2), max(c1, c2), min(r1, r2), max(r1, r2)
        if r1 < 0 or c2 + 1 >= len(cells["columns"]) or r2 + 1 >= len(cells["rows"]):
            raise Bad(f"{region} is outside the grid: columns A-{string.ascii_uppercase[len(cells['columns']) - 2]}, rows 1-{len(cells['rows']) - 1}")
        return cells["columns"][c1], cells["rows"][r1], cells["columns"][c2 + 1], cells["rows"][r2 + 1]
    a1, b1, a2, b2 = _numbers(region, 4, "region")

    def inside(u: float, w: float, end0: float, end1: float) -> tuple[float, float]:
        lo, hi = min(end0, end1), max(end0, end1)
        u, w = min(max(min(u, w), lo), hi), min(max(max(u, w), lo), hi)
        if w <= u:
            raise Bad(f"the region is outside the picture: it runs {_fmt(end0)} to {_fmt(end1)} across, then down")
        return (u, w) if end1 > end0 else (w, u)

    left, right = inside(a1, a2, f["h0"], f["h1"])
    top, bottom = inside(b1, b2, f["v0"], f["v1"])
    return left, top, right, bottom


def _cut(pic: dict[str, Any], item: dict[str, Any]) -> tuple[Image.Image, list[dict[str, Any]], str | None, list[float] | None]:
    """The asked part of the original: (image, its frames, the view, the region in numbers)."""
    with Image.open(storage.abs_path(pic["clean"])) as src:
        img = src.convert("RGB")
    frames = _frames(pic, img.size)
    view, region = item.get("view") or None, item.get("region") or None
    if region is None and (view is None or str(view).lower() == str(pic.get("view")).lower()):
        region = pic.get("region")  # the image as it was shown: a crop stays that crop
    view = view or pic.get("view")
    if view is None and region is None:
        return img, frames, None, None
    if view is None and len(frames) > 1:
        raise Bad(f"this is a sheet of views: say which one with `view` ({', '.join(str(f['name']) for f in frames)})")
    f = _pick(frames, view) if view is not None else frames[0]
    left, top, right, bottom = _region(f, region, (pic.get("cells") or {}).get(f["name"])) if region is not None else (f["h0"], f["v0"], f["h1"], f["v1"])
    x0, y0 = _px(f, left, top)
    x1, y1 = _px(f, right, bottom)
    box = (int(round(x0)), int(round(y0)), max(int(round(x1)), int(round(x0)) + 8), max(int(round(y1)), int(round(y0)) + 8))
    # the numbers follow the rounding to whole pixels
    across = (f["h1"] - f["h0"]) / f["box"][2]
    down = (f["v1"] - f["v0"]) / f["box"][3]
    out = {**f, "box": [0, 0, box[2] - box[0], box[3] - box[1]], "h0": f["h0"] + (box[0] - f["box"][0]) * across, "h1": f["h0"] + (box[2] - f["box"][0]) * across,
           "v0": f["v0"] + (box[1] - f["box"][1]) * down, "v1": f["v0"] + (box[3] - f["box"][1]) * down}
    return img.crop(box), [out], f["name"] if view is not None else None, [left, top, right, bottom] if region is not None else None


def _fit(img: Image.Image, frames: list[dict[str, Any]], w: int, h: int) -> tuple[Image.Image, list[dict[str, Any]], float]:
    k = min(w / img.width, h / img.height, UPSCALE_MAX)
    if abs(k - 1) < 0.01:
        return img, frames, 1.0
    out = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)
    kx, ky = out.width / img.width, out.height / img.height
    return out, [{**f, "box": [f["box"][0] * kx, f["box"][1] * ky, f["box"][2] * kx, f["box"][3] * ky]} for f in frames], k


# ------------------------------------------------------------------ drawing
def _fmt(v: float) -> str:
    return f"{round(v, 2):g}"


def _font(size: int) -> Any:
    return ImageFont.load_default(size)


def _step(f: dict[str, Any], asked: Any) -> float:
    w, h = f["box"][2], f["box"][3]
    da, db = abs(f["h1"] - f["h0"]), abs(f["v1"] - f["v0"])
    roomy = max(da * LINE_PX_MIN / max(w, 1), db * LINE_PX_MIN / max(h, 1), max(da, db) / GRID_LINES)
    finest = max(da * FINEST_PX / max(w, 1), db * FINEST_PX / max(h, 1), da / 25, db / 25)
    try:
        wanted = float(asked)
    except (TypeError, ValueError):
        wanted = 0.0
    if wanted >= finest:
        return wanted
    floor = finest if wanted > 0 else roomy
    return next((s for s in STEPS if s >= floor - 1e-9), STEPS[-1])


def _edges(a: float, b: float, step: float) -> list[float]:
    """The cell edges along an axis in picture order, from end a to end b. No line hugs an end: it would leave a sliver of a cell."""
    lo, hi = min(a, b), max(a, b)
    inner = [round(i * step, 6) for i in range(math.ceil((lo + step / 4) / step), math.floor((hi - step / 4) / step) + 1)]
    return [a, *(inner if b > a else inner[::-1]), b]


def _text(d: ImageDraw.ImageDraw, xy: tuple[float, float], s: str, fill: tuple[int, ...], size: int, anchor: str = "mm") -> None:
    d.text(xy, s, font=_font(size), fill=fill, anchor=anchor, stroke_width=2 if size > 11 else 1, stroke_fill=(0, 0, 0))


def _draw_grid(img: Image.Image, frames: list[dict[str, Any]], asked: Any = None) -> dict[str, dict[str, Any]]:
    """Lines with their numbers, a name in each cell. On a sheet only the views that have mm: the others have nothing to read."""
    d = ImageDraw.Draw(img, "RGBA")
    targets = frames if len(frames) == 1 else [f for f in frames if f["unit"] == "mm"] or frames
    cells: dict[str, dict[str, Any]] = {}
    for f in targets:
        x, y, w, h = f["box"]
        step = _step(f, asked)
        columns, rows = _edges(f["h0"], f["h1"], step), _edges(f["v0"], f["v1"], step)
        # whole pixels: a line and its shadow never land on one
        xs = [round(_px(f, c, f["v0"])[0]) for c in columns]
        ys = [round(_px(f, f["h0"], r)[1]) for r in rows]
        for px in xs[1:-1]:
            d.line([(px + 1, y), (px + 1, y + h)], fill=SHADOW)
            d.line([(px, y), (px, y + h)], fill=LINE)
        for py in ys[1:-1]:
            d.line([(x, py + 1), (x + w, py + 1)], fill=SHADOW)
            d.line([(x, py), (x + w, py)], fill=LINE)
        far = min(w, h) >= 500  # on a big picture the numbers are at every edge, never far from the place being read
        for px, c in zip(xs[1:-1], columns[1:-1]):
            _text(d, (px, y + 9), _fmt(c), LABEL, 12)
            if far:
                _text(d, (px, y + h - 9), _fmt(c), LABEL, 12)
        for py, r in zip(ys[1:-1], rows[1:-1]):
            _text(d, (x + 3, py), _fmt(r), LABEL, 12, "lm")
            if far:
                _text(d, (x + w - 3, py), _fmt(r), LABEL, 12, "rm")
        for i in range(min(len(xs) - 1, 26)):
            for j in range(len(ys) - 1):
                if xs[i + 1] - xs[i] >= 46 and ys[j + 1] - ys[j] >= 28:
                    _text(d, ((xs[i] + xs[i + 1]) / 2, ys[j] + 3), f"{string.ascii_uppercase[i]}{j + 1}", CELL, 11, "ma")
        axes = f"mm: {f['h']} horizontal, {f['v']} vertical" if f["unit"] == "mm" else "0-1000 grid"
        _text(d, (x + w - 4, y + h - 22 if far else y + h - 6), axes, LABEL, 11, "rd")
        cells[str(f["name"])] = {"columns": columns, "rows": rows, "step": step}
    return cells


def _draw_marks(img: Image.Image, frames: list[dict[str, Any]], marks: Any) -> None:
    if not marks:
        return
    if isinstance(marks, str):
        try:
            marks = json.loads(marks)
        except json.JSONDecodeError as e:
            raise Bad("marks must be a list of {at: [a, b], label} or {box: [a1, b1, a2, b2], label}") from e
    if len(frames) > 1:
        raise Bad("marks need one view: say which with `view`")
    f, d = frames[0], ImageDraw.Draw(img, "RGBA")
    for m in marks if isinstance(marks, list) else [marks]:
        if not isinstance(m, dict) or not (m.get("at") or m.get("box")):
            raise Bad("a mark is {at: [a, b], label} or {box: [a1, b1, a2, b2], label}")
        if m.get("box"):
            a1, b1, a2, b2 = _numbers(m["box"], 4, "a mark's box")
            (x0, y0), (x1, y1) = _px(f, a1, b1), _px(f, a2, b2)
            d.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], outline=MARK, width=2)
            px, py = min(x0, x1), min(y0, y1) - 2
        else:
            a, b = _numbers(m["at"], 2, "a mark's at")
            px, py = _px(f, a, b)
            d.ellipse([px - 7, py - 7, px + 7, py + 7], outline=MARK, width=2)
            d.line([(px - 11, py), (px + 11, py)], fill=MARK)
            d.line([(px, py - 11), (px, py + 11)], fill=MARK)
            px, py = px + 10, py - 8
        if m.get("label"):
            _text(d, (px, py), str(m["label"])[:40], MARK, 13, "ld")


def _save(ctx: Any, img: Image.Image, kind: str, png: bool) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True) if png else img.save(buf, "JPEG", quality=88)
    return storage.save_bytes(ctx.project_id, "renders", f"{kind}_{uuid.uuid4().hex[:10]}.{'png' if png else 'jpg'}", buf.getvalue())


def _brief(f: dict[str, Any], cell: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {"view": f["name"], f["h"]: [round(f["h0"], 2), round(f["h1"], 2)], f["v"]: [round(f["v0"], 2), round(f["v1"], 2)], "unit": f["unit"]}
    if cell:
        n = min(len(cell["columns"]) - 1, 26)
        out.update(step=cell["step"], cells=f"A1-{string.ascii_uppercase[n - 1]}{len(cell['rows']) - 1}")
    return out


# ------------------------------------------------------------------ the tools
def _make_grid(ctx: Any, state: Any, pic: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    img, frames, view, region = _cut(pic, args)
    img, frames, k = _fit(img, frames, SIDE, SIDE)
    cells = _draw_grid(img, frames, args.get("step"))
    _draw_marks(img, frames, args.get("marks"))
    rel = _save(ctx, img, "grid", str(pic["clean"]).lower().endswith(".png"))
    # the name keeps the original: a zoom on it cuts that, not this drawing
    name = enroll(ctx, state, rel, "grid", clean=pic["clean"], frames=pic.get("frames"), view=view, region=region, cells=cells)
    mm = any(f["unit"] == "mm" for f in frames)
    out = {"ok": True, "image": name, "of": pic["name"], "frames": [_brief(f, cells.get(str(f["name"]))) for f in frames],
           "next": f"zoom: grid(image='{name}', region='<cell or cells>'); check a reading with marks"}
    if mm:
        out["read"] = "the numbers are model mm of the two axes in `frames`; the left and top edges come first in each"
    if k > BLURRY:
        out["blurry"] = (f"this cut is magnified x{k:.1f}: look(what='model', zoom=...) renders it sharp" if mm else
                         f"this cut is magnified x{k:.1f}: the original has no more detail here")
    return out


def _make_collage(ctx: Any, state: Any, pieces: list[tuple[dict[str, Any], dict[str, Any]]], columns: Any, with_grid: bool) -> dict[str, Any]:
    n = len(pieces)
    try:
        cols = max(1, min(int(columns), n))
    except (TypeError, ValueError):
        cols = n if n <= 3 else min(4, math.ceil(math.sqrt(n)))
    tile_w = (SIDE - SHEET_GAP * (cols + 1)) // cols
    tile_h = tile_w if cols > 1 else 900
    tiles = []
    for (pic, item), letter in zip(pieces, string.ascii_uppercase):
        img, frames, view, _ = _cut(pic, item)
        img, frames, _ = _fit(img, frames, tile_w, tile_h)
        _draw_marks(img, frames, item.get("marks"))
        caption = " ".join(str(s)[:40] for s in (letter, pic["name"], view, item.get("label")) if s)
        tiles.append({"letter": letter, "img": img, "frames": frames, "caption": caption, "pic": pic["name"], "view": view})
    rows = [tiles[i:i + cols] for i in range(0, n, cols)]
    heights = [max(t["img"].height for t in row) + CAPTION_H for row in rows]
    sheet = Image.new("RGB", (SHEET_GAP + cols * (tile_w + SHEET_GAP), SHEET_GAP + sum(h + SHEET_GAP for h in heights)), SHEET_BG)
    d = ImageDraw.Draw(sheet)
    placed: list[dict[str, Any]] = []
    y = SHEET_GAP
    for row, height in zip(rows, heights):
        for i, t in enumerate(row):
            x = SHEET_GAP + i * (tile_w + SHEET_GAP)
            d.text((x + 2, y + CAPTION_H / 2), t["caption"], font=_font(14), fill=(235, 235, 235), anchor="lm")
            ox, oy = x + (tile_w - t["img"].width) // 2, y + CAPTION_H + (height - CAPTION_H - t["img"].height) // 2
            sheet.paste(t["img"], (ox, oy))
            t["placed"] = [{**f, "name": t["letter"] if len(t["frames"]) == 1 else f"{t['letter']}.{f['name']}",
                            "box": [f["box"][0] + ox, f["box"][1] + oy, f["box"][2], f["box"][3]]} for f in t["frames"]]
            placed += t["placed"]
        y += height + SHEET_GAP
    # pictures with mm stay sharp as PNG; a photo on the sheet would make it huge
    png = all(str(pic["clean"]).lower().endswith(".png") for pic, _ in pieces)
    known: dict[str, Any] = {}
    cells = None
    if with_grid:
        known["clean"] = _save(ctx, sheet, "sheet", png)
        cells = _draw_grid(sheet, placed)
    rel = _save(ctx, sheet, "sheet", png)
    name = enroll(ctx, state, rel, "collage", frames=placed, cells=cells, **known)
    return {"ok": True, "image": name,
            "tiles": [{"tile": t["letter"], "image": t["pic"], **({"view": t["view"]} if t["view"] else {}),
                       "frames": [_brief(f, (cells or {}).get(str(f["name"]))) for f in t["placed"]] if with_grid else None} for t in tiles]}


async def run(ctx: Any, state: Any, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    try:
        if name == "grid":
            pic = await _resolve(ctx, state, args.get("image"))
            result = await asyncio.to_thread(_make_grid, ctx, state, pic, args)
        else:
            raw = args.get("items")
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except json.JSONDecodeError:
                    raw = None
            if not isinstance(raw, list) or not raw:
                raise Bad("items must be a list of {image, view?, region?, marks?, label?}")
            if len(raw) > SHEET_MAX_ITEMS:
                raise Bad(f"at most {SHEET_MAX_ITEMS} pictures on a sheet")
            items = [it if isinstance(it, dict) else {"image": it} for it in raw]
            pieces = [(await _resolve(ctx, state, it.get("image")), it) for it in items]
            result = await asyncio.to_thread(_make_collage, ctx, state, pieces, args.get("columns"), bool(args.get("grid")))
    except Bad as e:
        return {"ok": False, "error": str(e)}, []
    except FileNotFoundError:
        return {"ok": False, "error": "that picture's file is gone"}, []
    return result, [state.pictures[result["image"]]["rel"]]
