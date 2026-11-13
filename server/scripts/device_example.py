"""Keep a finished device run as a home page example: its project in one data dir becomes server/iamodelize3d/example_devices/<key>/
(showcase.py opens it as a visitor's own project, free and at once).

What travels is what the device studio reads when the run has ended: the latest device document, program and PCB version
with their numbers (the case names the board it was made for by number), the board's files and the cover. The history, the
events and the people do not. The database is opened read-only. Standard library only, so it runs in the container too:

    python scripts/device_example.py report                                  # the data dir's device projects, newest first
    python scripts/device_example.py export p_0123 --key weather             # into the repo's example_devices/weather
    python scripts/device_example.py export p_0123 --key weather --out /tmp/ex --data-dir /app/data
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import Any

SERVER_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DATA = SERVER_DIR.parent / "data"
DEFAULT_OUT = SERVER_DIR / "iamodelize3d" / "example_devices"


def connect(data_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{(data_dir / 'iamodelize3d.db').as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def loads(v: Any) -> Any:
    return json.loads(v) if isinstance(v, str) and v else v


def latest(conn: sqlite3.Connection, table: str, project_id: str) -> sqlite3.Row | None:
    return conn.execute(f"SELECT * FROM {table} WHERE project_id = ? ORDER BY version DESC LIMIT 1", (project_id,)).fetchone()


def export(conn: sqlite3.Connection, data_dir: Path, project_id: str, folder: Path) -> dict[str, Any]:
    project = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if project is None or project["pack"] != "device":
        raise SystemExit(f"{project_id}: no such device project")
    doc, program, board = (latest(conn, t, project_id) for t in ("device_docs", "programs", "pcb_boards"))
    if not (doc and program and board and project["cover"]):
        raise SystemExit(f"{project_id}: not finished (it needs a document, a program, a board and a cover)")
    job = conn.execute("SELECT result FROM jobs WHERE project_id = ? AND status = 'done' ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    artifacts = loads(board["artifacts"]) or {}
    for name, rel in artifacts.items():
        shutil.copyfile(data_dir / "files" / rel, folder / name)
    shutil.copyfile(data_dir / "files" / project["cover"], folder / "cover.png")
    out = {
        "from": project_id,
        "title": project["title"],
        "summary": (loads(job["result"]) or {}).get("summary", "") if job else "",
        "doc": {"version": doc["version"], "doc": loads(doc["doc"]), "summary": doc["summary"]},
        "program": {"version": program["version"], "source": program["source"], "params": loads(program["params"]),
                    "inputs": loads(program["inputs"]) or {}, "summary": program["summary"], "checks": loads(program["checks"])},
        "pcb": {"version": board["version"], "source": board["source"], "intent": loads(board["intent"]), "checks": loads(board["checks"]),
                "files": sorted(artifacts)},
    }
    (folder / "example.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")
    return out


def report(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT p.id, p.title, p.version, j.status, j.cost_usd FROM projects p LEFT JOIN jobs j ON j.project_id = p.id "
                        "WHERE p.pack = 'device' AND p.cover IS NOT NULL ORDER BY p.created_at DESC").fetchall()
    for r in rows:
        print(r["id"], r["title"], f"v{r['version']}", r["status"], f"${r['cost_usd'] or 0:.3f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["report", "export"])
    ap.add_argument("project", nargs="?")
    ap.add_argument("--key", help="the example's folder name")
    ap.add_argument("--data-dir", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    conn = connect(args.data_dir)
    if args.command == "report":
        report(conn)
        return 0
    if not args.project or not args.key:
        ap.error("export needs a project id and --key")
    out = export(conn, args.data_dir, args.project, args.out / args.key)
    print(f"{args.key}: {out['title']} (device v{out['doc']['version']}, program v{out['program']['version']}, board v{out['pcb']['version']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
