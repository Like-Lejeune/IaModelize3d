"""Ship recorded agent runs to the live server: export chosen projects from one data dir into a single archive, then
import that archive into another data dir (the live server's volume) under the founder's account there.

A project travels with everything its studio page and its replay read: the project row (title, cover, brief, public
and featured flags), its programs, messages, events, jobs (the featured card's time and models), assets and
selections, its PCB versions and device documents, and its files (data/files/<project>/ plus files it points to elsewhere, such as an
example cover). People do not travel: the owner and the jobs' user become --user, and no users, sessions, spend or
shop rows are written. Export opens the source database read-only and writes only the archive.
Import is a dry run by default (the target is opened read-only); --apply writes. It is idempotent: a project that
is already there is left alone, so a second run adds nothing; --replace overwrites such a project with the
archive's copy (its rows are replaced, its files rewritten; files the archive does not have stay).

    python scripts/ship_runs.py export p_a p_b --out runs.zip          # from FW_DATA_DIR (or data/ in the repo)
    python scripts/ship_runs.py export --featured --out runs.zip       # every featured run there
    python scripts/ship_runs.py show runs.zip                          # what an archive holds
    python scripts/ship_runs.py import runs.zip --user u_0123456789abcdef           # what it would add
    python scripts/ship_runs.py import runs.zip --user u_0123456789abcdef --apply   # add it
    python scripts/ship_runs.py import runs.zip --user u_... --data-dir D:/other/data --replace --apply

On the live server (deploy/compose.yaml; the user id is the one /api/me shows in your browser there):
    docker compose cp runs.zip iamodelize3d:/tmp/runs.zip
    docker compose exec iamodelize3d python scripts/ship_runs.py import /tmp/runs.zip --user u_... --apply
Then order the home page with scripts/curate_demo.py --feature <id> ... --apply.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(SERVER_DIR / "scripts"))

from judge_link import connect, default_db, has_table  # noqa: E402

FORMAT = "fw.runs/1"
# the rows of a project, in the order they are written; each table's rows are keyed by project_id
TABLES = ("programs", "messages", "assets", "selections", "jobs", "events", "pcb_boards", "device_docs")
ORDER = {"programs": "version", "messages": "created_at, id", "assets": "created_at, id", "selections": "created_at, id",
         "jobs": "created_at, id", "events": "seq", "pcb_boards": "version", "device_docs": "version"}
# columns the target numbers itself: event seq is the target's own order
SKIP_COLUMNS = {"events": {"seq"}}
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
FILE_URL = re.compile(r"/files/([A-Za-z0-9_\-./%]+)")
# already compressed: stored as they are
STORED = {".png", ".jpg", ".jpeg", ".webp", ".glb", ".zip", ".3mf", ".gz", ".mp4", ".webm", ".ogg", ".mp3", ".m4a"}


def data_dir_default() -> Path:
    return default_db().parent


# ------------------------------------------------------------------ export
def _value(v: Any) -> Any:
    # no column holds a blob today; one would still travel intact
    return {"$b64": base64.b64encode(v).decode()} if isinstance(v, (bytes, memoryview)) else v


def _unvalue(v: Any) -> Any:
    return base64.b64decode(v["$b64"]) if isinstance(v, dict) and set(v) == {"$b64"} else v


def _rel(path: str) -> str | None:
    """A path relative to data/files that stays inside it, or None."""
    p = PurePosixPath(path.split("?", 1)[0].split("#", 1)[0])
    if not path or "\\" in path or p.is_absolute() or not p.parts or ":" in p.parts[0] or ".." in p.parts:
        return None
    return p.as_posix()


def _referenced(project: dict[str, Any], tables: dict[str, list[dict[str, Any]]]) -> set[str]:
    """Files a project points to: its cover, asset paths and thumbnails, masks, and every /files/ URL in its rows."""
    refs = {project.get("cover")}
    for a in tables.get("assets", []):
        refs.add(a.get("path"))
        try:
            refs.add((json.loads(a.get("meta") or "{}") or {}).get("thumb"))
        except (json.JSONDecodeError, AttributeError):
            pass
    refs.update(s.get("mask_path") for s in tables.get("selections", []))
    for rows in [[project], *tables.values()]:
        for row in rows:
            for v in row.values():
                if isinstance(v, str) and "/files/" in v:
                    refs.update(m.group(1) for m in FILE_URL.finditer(v))
    return {r for ref in refs if isinstance(ref, str) and (r := _rel(ref))}


def collect(conn: sqlite3.Connection, files: Path, pid: str) -> tuple[dict[str, Any], list[str]]:
    """One project's rows and the files it needs (paths relative to files/)."""
    project = dict(conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone())
    tables: dict[str, list[dict[str, Any]]] = {}
    for t in TABLES:
        if not has_table(conn, t):
            continue
        rows = conn.execute(f"SELECT * FROM {t} WHERE project_id = ? ORDER BY {ORDER[t]}", (pid,)).fetchall()
        tables[t] = [{k: _value(r[k]) for k in r.keys()} for r in rows]
    root = files.resolve()
    own = sorted(p.relative_to(root).as_posix() for p in (root / pid).rglob("*") if p.is_file()) if (root / pid).is_dir() else []
    extra = sorted(r for r in _referenced(project, tables) - set(own) if (root / r).is_file() and (root / r).resolve().is_relative_to(root))
    return {"project": {k: _value(v) for k, v in project.items()}, "tables": tables}, own + extra


def export(conn: sqlite3.Connection, files: Path, ids: list[str], out: Path) -> dict[str, Any]:
    """Write the archive; returns its manifest."""
    manifest: dict[str, Any] = {"format": FORMAT, "created_at": time.time(), "projects": []}
    packed: list[tuple[str, dict[str, Any], list[str]]] = []
    for pid in ids:
        if not SAFE_ID.fullmatch(pid):
            sys.exit(f"not a project id: {pid!r}")
        row = conn.execute("SELECT id, title, status, replay_of FROM projects WHERE id = ?", (pid,)).fetchone()
        if not row:
            sys.exit(f"no project {pid}")
        busy = has_table(conn, "jobs") and conn.execute("SELECT 1 FROM jobs WHERE project_id = ? AND status IN ('running', 'waiting')", (pid,)).fetchone()
        if busy:
            sys.exit(f"{pid} {row['title']!r} has a job still running; ship it once the run has ended")
        if row["replay_of"]:
            print(f"note: {pid} is a replay copy of {row['replay_of']}; the original is the run to ship")
        doc, paths = collect(conn, files, pid)
        packed.append((pid, doc, paths))
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".part")
    root = files.resolve()
    written: set[str] = set()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for pid, doc, paths in packed:
            z.writestr(f"projects/{pid}.json", json.dumps(doc, ensure_ascii=False))
            size = 0
            for rel in paths:
                size += (root / rel).stat().st_size
                if rel not in written:  # two projects can point at the same example cover
                    stored = PurePosixPath(rel).suffix.lower() in STORED
                    z.write(root / rel, f"files/{rel}", zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
                    written.add(rel)
            p = doc["project"]
            manifest["projects"].append({
                "id": pid, "title": p.get("title"), "pack": p.get("pack"), "version": p.get("version"), "public": p.get("public"),
                "featured": p.get("featured") or 0, "rows": {t: len(r) for t, r in doc["tables"].items()}, "files": paths, "bytes": size,
            })
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    tmp.replace(out)
    return manifest


# ------------------------------------------------------------------ import
class Archive:
    """An export, checked before anything is written: known format, safe ids, file entries inside files/."""

    def __init__(self, path: Path):
        try:
            self.zip = zipfile.ZipFile(path)
            self.manifest = json.loads(self.zip.read("manifest.json"))
        except (OSError, KeyError, zipfile.BadZipFile, json.JSONDecodeError) as e:
            sys.exit(f"{path} is not a runs archive: {e}")
        if self.manifest.get("format") != FORMAT:
            sys.exit(f"{path}: format {self.manifest.get('format')!r}, expected {FORMAT}")
        names = set(self.zip.namelist())
        for entry in self.manifest.get("projects", []):
            pid = str(entry.get("id"))
            if not SAFE_ID.fullmatch(pid) or f"projects/{pid}.json" not in names:
                sys.exit(f"{path}: bad project entry {pid!r}")
            for rel in entry.get("files", []):
                if _rel(rel) != rel or f"files/{rel}" not in names:
                    sys.exit(f"{path}: bad file entry {rel!r} in {pid}")

    @property
    def projects(self) -> list[dict[str, Any]]:
        return self.manifest.get("projects", [])

    def doc(self, pid: str) -> dict[str, Any]:
        return json.loads(self.zip.read(f"projects/{pid}.json"))

    def read(self, rel: str) -> bytes:
        return self.zip.read(f"files/{rel}")


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def _insert(conn: sqlite3.Connection, table: str, row: dict[str, Any], cols: list[str]) -> None:
    keep = [c for c in cols if c in row and c not in SKIP_COLUMNS.get(table, ())]
    conn.execute(f"INSERT INTO {table} ({', '.join(keep)}) VALUES ({', '.join('?' * len(keep))})", [_unvalue(row[c]) for c in keep])


def _same(path: Path, data: bytes) -> bool:
    return path.is_file() and path.stat().st_size == len(data) and hashlib.sha256(path.read_bytes()).digest() == hashlib.sha256(data).digest()


def _write_files(archive: Archive, files: Path, pid: str, paths: list[str]) -> tuple[int, int]:
    """The project's own files are written (rewritten when they differ); a file elsewhere, such as a shared example
    cover, only when the target lacks it, so nothing of another project is overwritten. Returns (written, same)."""
    root = files.resolve()
    written = same = 0
    for rel in paths:
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            sys.exit(f"refusing {rel!r}: outside {root}")
        own = PurePosixPath(rel).parts[0] == pid
        data = archive.read(rel)
        if (not own and target.exists()) or _same(target, data):
            same += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(target)
        written += 1
    return written, same


def _ensure_pcb_table(conn: sqlite3.Connection) -> None:
    """pcb_boards as the server creates it on first use (iamodelize3d.pcb_store.SCHEMA)."""
    if not has_table(conn, "pcb_boards"):
        from iamodelize3d.pcb_store import SCHEMA

        conn.execute(SCHEMA)


def _ensure_device_tables(conn: sqlite3.Connection) -> None:
    """device_docs as the server creates it on first use (iamodelize3d.device_store.SCHEMA)."""
    if not has_table(conn, "device_docs"):
        from iamodelize3d.device_store import SCHEMA

        conn.executescript(SCHEMA)


def import_archive(conn: sqlite3.Connection, files: Path, archive: Archive, user: str, *, apply: bool, replace: bool = False) -> dict[str, list[str]]:
    """Add the archive's projects to this database and files dir as `user`'s. Returns {added, replaced, skipped}."""
    if not conn.execute("SELECT 1 FROM users WHERE id = ?", (user,)).fetchone():
        sys.exit(f"no user {user} here (open the app once in that browser; /api/me shows the id)")
    if "featured" not in _columns(conn, "projects"):
        print("note: projects.featured is missing (this database predates featured runs; the server adds it on its next start)")
    out: dict[str, list[str]] = {"added": [], "replaced": [], "skipped": []}
    for entry in archive.projects:
        pid = entry["id"]
        doc = archive.doc(pid)
        rows = {t: r for t, r in doc["tables"].items() if t in TABLES}
        have = conn.execute("SELECT user_id, title FROM projects WHERE id = ?", (pid,)).fetchone()
        counts = ", ".join(f"{len(r)} {t}" for t, r in rows.items() if r)
        line = f"{pid} {entry.get('title')!r} (featured {entry.get('featured') or 0}, public {entry.get('public') or 0}; {counts}; {len(entry['files'])} files)"
        if have and not replace:
            whose = "" if have["user_id"] == user else f", owned by {have['user_id']}"
            print(f"  there already{whose}: {line} (--replace overwrites it)")
            out["skipped"].append(pid)
            continue
        verb = "replaced" if have else "added"
        print(f"  {verb if apply else 'would be ' + verb}: {line} as {user}")
        out[verb].append(pid)
        if not apply:
            continue
        written, same = _write_files(archive, files, pid, entry["files"])
        with conn:
            if rows.get("pcb_boards"):
                _ensure_pcb_table(conn)
            if rows.get("device_docs"):
                _ensure_device_tables(conn)
            if have:
                for t in TABLES:
                    if has_table(conn, t):
                        conn.execute(f"DELETE FROM {t} WHERE project_id = ?", (pid,))
                conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
            # every row lands on this project, whatever ids the archive's rows carry
            project = {**doc["project"], "id": pid, "user_id": user}
            if project.get("status") == "working":
                project["status"] = "idle"  # nothing runs it here
            _insert(conn, "projects", project, _columns(conn, "projects"))
            for t, trs in rows.items():
                if not trs or not has_table(conn, t):
                    continue
                cols = _columns(conn, t)
                for r in trs:
                    _insert(conn, t, {**r, "project_id": pid, **({"user_id": user} if t == "jobs" else {})}, cols)
        print(f"      files: {written} written, {same} already there")
    return out


# ------------------------------------------------------------------ cli
def show(archive: Archive) -> None:
    m = archive.manifest
    print(f"{m['format']}, made {time.strftime('%Y-%m-%d %H:%M', time.localtime(m.get('created_at', 0)))}, {len(archive.projects)} projects")
    for e in archive.projects:
        rows = ", ".join(f"{n} {t}" for t, n in e.get("rows", {}).items() if n)
        print(f"  {e['id']}  {e.get('title')!r} [{e.get('pack') or '-'}] v{e.get('version')}  featured {e.get('featured') or 0}  "
              f"public {e.get('public') or 0}\n      {rows}; {len(e['files'])} files, {e.get('bytes', 0) / 1e6:.1f} MB")


def main(argv: list[str] | None = None) -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # titles are in the user's language
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="projects from a data dir into an archive (reads only)")
    ex.add_argument("ids", nargs="*", help="project ids")
    ex.add_argument("--featured", action="store_true", help="also every featured run (public, featured > 0)")
    ex.add_argument("--out", type=Path, required=True, help="the archive to write (a zip)")
    ex.add_argument("--data-dir", type=Path, default=None, help="source data dir (default: FW_DATA_DIR or data/ in the repo)")
    sh = sub.add_parser("show", help="what an archive holds")
    sh.add_argument("archive", type=Path)
    im = sub.add_parser("import", help="an archive into a data dir (dry run without --apply)")
    im.add_argument("archive", type=Path)
    im.add_argument("--user", required=True, help="the owner there: your user id on that server (/api/me)")
    im.add_argument("--data-dir", type=Path, default=None, help="target data dir (default: FW_DATA_DIR or data/ in the repo)")
    im.add_argument("--replace", action="store_true", help="overwrite projects that are already there with the archive's copy")
    im.add_argument("--apply", action="store_true", help="write (without it nothing is written)")
    args = ap.parse_args(argv)

    if args.cmd == "show":
        show(Archive(args.archive))
        return
    data = args.data_dir or data_dir_default()
    path = data / "iamodelize3d.db"
    if args.cmd == "export":
        conn = connect(path, write=False)
        ids = list(dict.fromkeys(args.ids))
        if args.featured:
            if not any(r["name"] == "featured" for r in conn.execute("PRAGMA table_info(projects)")):
                sys.exit("projects.featured is missing: this database predates featured runs")
            ids += [r["id"] for r in conn.execute("SELECT id FROM projects WHERE public = 1 AND featured > 0 AND replay_of IS NULL "
                                                  "ORDER BY featured DESC") if r["id"] not in ids]
        if not ids:
            sys.exit("no projects to export (give ids, or --featured)")
        print(f"database: {path}\n")
        manifest = export(conn, data / "files", ids, args.out)
        conn.close()
        show(Archive(args.out))
        total = sum(e["bytes"] for e in manifest["projects"])
        print(f"\nwrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB, {total / 1e6:.1f} MB of files)")
        return
    archive = Archive(args.archive)
    conn = connect(path, write=args.apply)
    print(f"database: {path}\n")
    out = import_archive(conn, data / "files", archive, args.user, apply=args.apply, replace=args.replace)
    conn.close()
    if not (out["added"] or out["replaced"]):
        print("\nnothing to add")
    elif not args.apply:
        print("\nadd --apply to write")


if __name__ == "__main__":
    main()
