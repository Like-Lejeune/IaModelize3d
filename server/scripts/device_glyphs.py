"""Line drawings of the finished devices, for the pattern behind the home page: the real meshes of the examples kept in the repo
(example_devices/<key>) and any device projects named, from both front corners, reduced to the lines a draughtsman would draw
(sharp edges and the silhouette, hidden parts removed) and written as one SVG path per view. Nothing is drawn by hand, so a new or
changed device only needs this run again. The database is opened read-only.

    python scripts/device_glyphs.py                            # the examples, into web/src/lib/pattern/deviceGlyphs.json
    python scripts/device_glyphs.py --project p_3d9eebdde1324bcb --project p_ed7597059f7c455d --project p_360542b81df54c19 --project p_c17760cce5ef4e34
    python scripts/device_glyphs.py --mode exploded --out some.json
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import numpy as np

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from formwright.agent.device_inspect import case_program  # noqa: E402
from formwright.geom import geom  # noqa: E402

EXAMPLES = SERVER_DIR / "formwright" / "example_devices"
DEFAULT_DB = SERVER_DIR.parent / "data" / "formwright.db"
OUT = SERVER_DIR.parent / "web" / "src" / "lib" / "pattern" / "deviceGlyphs.json"

# view directions: the covers' corner (packages/geom engine.render, view 'iso') and the opposite front corner
LOOKS = {"r": (-1.0, 1.0, -0.8), "l": (1.0, 1.0, -0.8)}
RASTER = 1600              # px on the long side of the depth buffer the visibility test reads
SIZE = 100.0               # a drawing's long side in its own units
SHARP_DEG = 30.0           # facets further apart than this meet in a drawn edge; a rounded corner's facets stay below it
DEPTH_EPS_MM = 0.04        # how far behind the nearest surface a line still counts as lying on it
MIN_LINE = 1.1             # lines shorter than this (drawing units) are specks at the size the pattern shows them
SIMPLIFY = 0.09            # how far (drawing units) a simplified line may leave the real one


def camera(look: tuple[float, float, float]) -> np.ndarray:
    """Rows: picture right, picture down, into the picture (as render.ts's lookAt with z up)."""
    f = np.array(look, dtype=float)
    f /= np.linalg.norm(f)
    r = np.cross(f, [0.0, 0.0, 1.0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return np.array([r, -u, f])


def depth_buffer(xy: np.ndarray, z: np.ndarray, tris: np.ndarray, w: int, h: int) -> np.ndarray:
    """The nearest z per pixel, inf where nothing is."""
    depth = np.full((h, w), np.inf, dtype=np.float32)
    for a, b, c in tris:
        x0, y0, x1, y1, x2, y2 = xy[a, 0], xy[a, 1], xy[b, 0], xy[b, 1], xy[c, 0], xy[c, 1]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-9:
            continue
        lx, hx = max(0, int(min(x0, x1, x2))), min(w - 1, int(max(x0, x1, x2)) + 1)
        ly, hy = max(0, int(min(y0, y1, y2))), min(h - 1, int(max(y0, y1, y2)) + 1)
        if lx > hx or ly > hy:
            continue
        px, py = np.meshgrid(np.arange(lx, hx + 1) + 0.5, np.arange(ly, hy + 1) + 0.5)
        w0 = ((x1 - px) * (y2 - py) - (x2 - px) * (y1 - py)) / area
        w1 = ((x2 - px) * (y0 - py) - (x0 - px) * (y2 - py)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        zz = w0 * z[a] + w1 * z[b] + w2 * z[c]
        view = depth[ly:hy + 1, lx:hx + 1]
        nearer = inside & (zz < view)
        view[nearer] = zz[nearer]
    return depth


def drawn_edges(pos: np.ndarray, tris: np.ndarray, part: np.ndarray, look: np.ndarray) -> np.ndarray:
    """Vertex pairs of the lines to draw: sharp edges, the silhouette and open borders that face the viewer. Vertices weld within
    a part only, so two parts that touch keep their own edges."""
    keyed = np.column_stack([np.round(pos[tris.ravel()] * 500).astype(np.int64), np.repeat(part, 3)])
    _, weld = np.unique(keyed, axis=0, return_inverse=True)
    corner = weld.reshape(-1, 3)
    first = np.zeros(weld.max() + 1, dtype=np.int64)
    first[weld] = tris.ravel()

    n = np.cross(pos[tris[:, 1]] - pos[tris[:, 0]], pos[tris[:, 2]] - pos[tris[:, 0]])
    good = np.linalg.norm(n, axis=1) > 1e-9
    n[good] /= np.linalg.norm(n[good], axis=1, keepdims=True)
    front = n @ look < 0

    pairs: dict[tuple[int, int], list[int]] = {}
    for f, (a, b, c) in enumerate(corner):
        if not good[f]:
            continue
        for u, v in ((a, b), (b, c), (c, a)):
            if u != v:
                pairs.setdefault((min(u, v), max(u, v)), []).append(f)
    cos_sharp = np.cos(np.radians(SHARP_DEG))
    out: list[tuple[int, int]] = []
    for (u, v), fs in pairs.items():
        if not any(front[f] for f in fs):
            continue
        if len(fs) != 2 or front[fs[0]] != front[fs[1]] or n[fs[0]] @ n[fs[1]] < cos_sharp:
            out.append((first[u], first[v]))
    return np.array(out, dtype=np.int64).reshape(-1, 2)


def visible_runs(p: np.ndarray, q: np.ndarray, zp: float, zq: float, depth: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """The stretches of a line that no surface hides, sampled about every pixel."""
    steps = max(2, int(np.hypot(*(q - p))) + 1)
    h, w = depth.shape
    t = (np.arange(steps) + 0.5) / steps
    xs, ys = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
    zs = zp + (zq - zp) * t
    ix, iy = np.clip(xs.astype(int), 1, w - 2), np.clip(ys.astype(int), 1, h - 2)
    # the farthest of the pixel and its neighbours: a line on a surface's rim has that surface or nothing beside it
    far = np.max([depth[iy + dy, ix + dx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)], axis=0)
    seen = zs <= far + DEPTH_EPS_MM
    runs: list[tuple[np.ndarray, np.ndarray]] = []
    i = 0
    while i < steps:
        if not seen[i]:
            i += 1
            continue
        j = i
        while j + 1 < steps and seen[j + 1]:
            j += 1
        a = i / steps if i else 0.0
        b = (j + 1) / steps if j + 1 < steps else 1.0
        runs.append((p + (q - p) * a, p + (q - p) * b))
        i = j + 1
    return runs


def chain(segments: list[tuple[np.ndarray, np.ndarray]]) -> list[np.ndarray]:
    """Segments joined into polylines: through every point where exactly two meet."""
    key = lambda v: (round(float(v[0]), 1), round(float(v[1]), 1))  # noqa: E731
    at: dict[tuple[float, float], list[int]] = {}
    for i, (a, b) in enumerate(segments):
        if key(a) != key(b):
            at.setdefault(key(a), []).append(i)
            at.setdefault(key(b), []).append(i)
    used = [False] * len(segments)

    def walk(start: tuple[float, float], i: int) -> list[np.ndarray]:
        pts: list[np.ndarray] = []
        here = start
        while True:
            used[i] = True
            a, b = segments[i]
            far = b if key(a) == here else a
            pts.append(far)
            here = key(far)
            nxt = [s for s in at.get(here, []) if not used[s]]
            if len(at.get(here, [])) != 2 or not nxt:
                return pts
            i = nxt[0]

    out: list[np.ndarray] = []
    # open ends first, so a line is not cut in its middle
    for k, ss in sorted(at.items(), key=lambda kv: len(kv[1]) == 2):
        for s in ss:
            if used[s]:
                continue
            a, b = segments[s]
            start = key(a) if key(a) == k else key(b)
            first = a if key(a) == k else b
            out.append(np.array([first, *walk(start, s)]))
    return out


def simplify(pts: np.ndarray, eps: float) -> np.ndarray:
    """Douglas-Peucker."""
    keep = np.zeros(len(pts), dtype=bool)
    keep[[0, -1]] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        d = pts[j] - pts[i]
        ln = np.hypot(*d)
        rel = pts[i + 1:j] - pts[i]
        dist = np.abs(d[0] * rel[:, 1] - d[1] * rel[:, 0]) / ln if ln > 1e-9 else np.hypot(rel[:, 0], rel[:, 1])
        m = int(np.argmax(dist))
        if dist[m] > eps:
            keep[i + 1 + m] = True
            stack += [(i, i + 1 + m), (i + 1 + m, j)]
    return pts[keep]


def path(lines: list[np.ndarray]) -> str:
    """Relative commands at a tenth of a unit, the rounding carried along so a long line does not drift."""
    fmt = lambda v: f"{v / 10:g}".replace("0.", ".", 1) if abs(v) < 10 and v >= 0 else f"{v / 10:g}".replace("-0.", "-.", 1)  # noqa: E731
    d: list[str] = []
    for line in lines:
        q = np.round(line * 10).astype(int)
        keep = [q[0]]
        for v in q[1:]:
            if (v != keep[-1]).any():
                keep.append(v)
        if len(keep) < 2:
            continue
        d.append(f"M{fmt(keep[0][0])} {fmt(keep[0][1])}l")
        rel = [f"{fmt(b[0] - a[0])} {fmt(b[1] - a[1])}" for a, b in zip(keep, keep[1:], strict=False)]
        d.append(" ".join(rel).replace(" -", "-"))
    return "".join(d)


def outline(mesh: dict[str, Any], look: tuple[float, float, float]) -> dict[str, Any]:
    pos = np.frombuffer(base64.b64decode(mesh["positions"]), dtype=np.float32).reshape(-1, 3).astype(np.float64)
    tris = np.frombuffer(base64.b64decode(mesh["indices"]), dtype=np.uint32).reshape(-1, 3).astype(np.int64)
    part = np.frombuffer(base64.b64decode(mesh["triPart"]), dtype=np.uint16).astype(np.int64)
    cam = camera(look)
    v = pos @ cam.T
    lo, hi = v[:, :2].min(axis=0), v[:, :2].max(axis=0)
    span = float((hi - lo).max())
    margin = 3
    scale = (RASTER - 2 * margin) / span
    xy = (v[:, :2] - lo) * scale + margin
    w, h = int((hi - lo)[0] * scale) + 2 * margin + 1, int((hi - lo)[1] * scale) + 2 * margin + 1
    depth = depth_buffer(xy, v[:, 2], tris, w, h)

    segments: list[tuple[np.ndarray, np.ndarray]] = []
    for a, b in drawn_edges(pos, tris, part, cam[2]):
        segments += visible_runs(xy[a], xy[b], v[a, 2], v[b, 2], depth)

    unit = SIZE / RASTER
    lines: list[np.ndarray] = []
    for line in chain(segments):
        drawing = line * unit
        if np.hypot(*np.diff(drawing, axis=0).T).sum() >= MIN_LINE:
            lines.append(simplify(drawing, SIMPLIFY))
    return {"w": round(w * unit, 1), "h": round(h * unit, 1), "d": path(lines), "lines": len(lines), "tris": len(tris)}


def devices(args: argparse.Namespace) -> list[tuple[str, dict[str, Any]]]:
    """(name, {source, params, inputs}) of the examples and the projects asked for, each project's latest program."""
    out = []
    for folder in sorted(p for p in EXAMPLES.iterdir() if (p / "example.json").exists()):
        out.append((folder.name, json.loads((folder / "example.json").read_text(encoding="utf-8"))["program"]))
    if args.project:
        conn = sqlite3.connect(f"file:{args.db.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        for pid in args.project:
            r = conn.execute("SELECT source, params, inputs FROM programs WHERE project_id = ? ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
            if r is None:
                raise SystemExit(f"{pid}: no program")
            out.append((pid, {"source": r["source"], "params": json.loads(r["params"]), "inputs": json.loads(r["inputs"] or "{}")}))
    return out


async def run(args: argparse.Namespace) -> None:
    out: list[dict[str, Any]] = []
    for name, program in devices(args):
        source = case_program(program["source"], args.mode)
        params = {**program["params"], "layout": "assembled", "show_board": True}
        built = await geom().build(source, params, analyze="none", mesh=True, inputs=program["inputs"])
        for view, look in LOOKS.items():
            g = outline(built["mesh"], look)
            out.append({"device": name, "view": view, "w": g["w"], "h": g["h"], "d": g["d"]})
            print(f"{name:20} {view} {g['tris']:>7} tris {g['lines']:>5} lines {len(g['d']):>7} chars  {g['w']} x {g['h']}", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8", newline="\n")
    await geom().close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", default="assembled", choices=["assembled", "exploded", "lid_off"])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--project", action="append", help="also this device project's latest program")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    asyncio.run(run(ap.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
