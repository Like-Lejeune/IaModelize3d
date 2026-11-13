"""Render the covers of finished devices again, after the cover itself changed: the examples kept in the repo
(example_devices/<key>/cover.png) and every device project of a data dir (the file its row names, in place). The database is
opened read-only and nothing but those pictures is written. A project that does not build keeps the cover it has.

    python scripts/refresh_device_covers.py                 # the examples and the data dir's device projects
    python scripts/refresh_device_covers.py --examples      # the examples only
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

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from iamodelize3d.agent.device_inspect import cover_render  # noqa: E402
from iamodelize3d.geom import GeomError, geom  # noqa: E402

DEFAULT_DATA = SERVER_DIR.parent / "data"
EXAMPLES = SERVER_DIR / "iamodelize3d" / "example_devices"


async def cover(source: str, params: dict[str, Any], inputs: dict[str, Any]) -> bytes:
    src, ps = cover_render(source, params)
    out = await geom().render(src, ps, view="iso", tile=640, transparent=True, inputs=inputs)
    return base64.b64decode(out["png"])


async def examples() -> None:
    for folder in sorted(p for p in EXAMPLES.iterdir() if (p / "example.json").exists()):
        program = json.loads((folder / "example.json").read_text(encoding="utf-8"))["program"]
        (folder / "cover.png").write_bytes(await cover(program["source"], program["params"], program["inputs"]))
        print("example", folder.name)


async def projects(data_dir: Path) -> None:
    conn = sqlite3.connect(f"file:{(data_dir / 'iamodelize3d.db').as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, cover FROM projects WHERE pack = 'device' AND cover IS NOT NULL").fetchall()
    for row in rows:
        program = conn.execute("SELECT source, params, inputs FROM programs WHERE project_id = ? ORDER BY version DESC LIMIT 1", (row["id"],)).fetchone()
        if program is None:
            continue
        try:
            png = await cover(program["source"], json.loads(program["params"]), json.loads(program["inputs"] or "{}"))
        except GeomError as e:
            print("kept", row["id"], e.stage)
            continue
        (data_dir / "files" / row["cover"]).write_bytes(png)
        print("project", row["id"])


async def run(args: argparse.Namespace) -> None:
    await examples()
    if not args.examples:
        await projects(args.data_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--examples", action="store_true", help="the examples kept in the repo only")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    asyncio.run(run(ap.parse_args()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
