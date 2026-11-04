"""Pick the real agent runs the home page shows, and tidy up projects nobody needs to see.

Dry run by default: it prints what it would change and opens the database read-only.
Add --apply to write. It never deletes anything.

    python scripts/curate_demo.py                       # candidate runs: finished design jobs
    python scripts/curate_demo.py --feature p_a p_b     # p_a first, then p_b (public + featured)
    python scripts/curate_demo.py --unfeature [p_a]     # one run, or every featured run
    python scripts/curate_demo.py --list-empty          # projects with no version, or stuck 'working'
    python scripts/curate_demo.py --archive p_c         # out of its owner's list (undo: --restore p_c)
    python scripts/curate_demo.py --take-down p_d       # a published run off the gallery, its link closed (undo: --put-back p_d)
    python scripts/curate_demo.py --stats               # cost, cache and timing numbers, measured on this database

Featured runs are listed by GET /api/featured: public, featured > 0, not a replay copy, highest number first.
Watching one replays its event log, so it spends nothing. --feature refuses a run whose last finish the reviewer did
not approve ('notes' / 'none', or turned down; a device: without a passed self-check) or whose latest version fails its
checks (--force features it anyway),
and a PCB run whose latest board, built again offline in the sandboxed PCB worker (no model), has DRC errors such as
pcb_button_short_error (no --force for that). Standard library only, except that rebuild (it needs the server package
and packages/pcb/dist), so it runs in the container too:
    docker exec formwright python scripts/curate_demo.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import statistics
import sys
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = SERVER_DIR.parent
ARCHIVE_OWNER = "archived"  # no users row has this id, so no browser can sign in as it
STALE_S = 1800  # a 'working' project with no event for this long has no live job (jobs end by their deadline)


# ------------------------------------------------------------------ settings and database
def env_setting(name: str) -> str | None:
    """A setting as the server reads it: the environment first, then .env in the repo, then one folder up."""
    if os.environ.get(name):
        return os.environ[name]
    for path in (REPO_DIR / ".env", REPO_DIR.parent / ".env"):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            key, sep, value = line.strip().removeprefix("export ").partition("=")
            if sep and key.strip().upper() == name:
                return value.strip().strip("'\"") or None
    return None


def default_db() -> Path:
    data = Path(env_setting("FW_DATA_DIR") or REPO_DIR / "data")
    return (data if data.is_absolute() else SERVER_DIR / data) / "formwright.db"


def connect(path: Path, write: bool) -> sqlite3.Connection:
    if not path.exists():
        sys.exit(f"no database at {path} (pass --db)")
    # read-only unless writing, so a dry run cannot change anything
    conn = sqlite3.connect(path, timeout=10) if write else sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def has_featured(conn: sqlite3.Connection) -> bool:
    return any(r["name"] == "featured" for r in conn.execute("PRAGMA table_info(projects)"))


def require_featured(conn: sqlite3.Connection) -> None:
    if not has_featured(conn):
        sys.exit("projects.featured is missing: this database predates featured runs. Start the server once with the "
                 "current code (it adds the column on startup), then run this again.")


def loads(text: str | None) -> dict:
    try:
        out = json.loads(text) if text else {}
    except json.JSONDecodeError:
        return {}
    return out if isinstance(out, dict) else {}


# ------------------------------------------------------------------ candidates
def language(conn: sqlite3.Connection, p: sqlite3.Row) -> str:
    """The run's language: the brief says it, or the title and requests are Cyrillic."""
    brief = loads(p["brief"])
    if brief.get("language"):
        return str(brief["language"])[:2]
    texts = [p["title"]] + [str(loads(j["input"]).get("text") or "") for j in conn.execute("SELECT input FROM jobs WHERE project_id = ?", (p["id"],))]
    return "ru" if any(re.search("[А-Яа-яЁё]", t) for t in texts) else "en"


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    m, s = divmod(round(seconds), 60)
    return f"{m}m{s:02d}s" if m else f"{s}s"


def models_text(costs: list[dict]) -> str:
    """Calls per model when every job counted them, else USD per model (older jobs), as GET /api/featured does."""
    key = "calls_by_model" if costs and all("calls_by_model" in c for c in costs) else "by_model"
    total: dict[str, float] = {}
    for c in costs:
        for model, v in (c.get(key) or {}).items():
            total[model] = total.get(model, 0) + v
    ranked = sorted(total.items(), key=lambda kv: -kv[1])
    return ", ".join(f"{m} x{int(v)}" if key == "calls_by_model" else f"{m} ${v:.4f}" for m, v in ranked) or "-"


def candidates(conn: sqlite3.Connection) -> list[dict]:
    featured = has_featured(conn)
    out = []
    for p in conn.execute("SELECT * FROM projects WHERE user_id != ? ORDER BY updated_at DESC", (ARCHIVE_OWNER,)):
        jobs = conn.execute("SELECT * FROM jobs WHERE project_id = ? AND kind = 'design' ORDER BY created_at", (p["id"],)).fetchall()
        done = [j for j in jobs if j["status"] == "done" and j["finished_at"]]
        if not done:
            continue
        versions = conn.execute("SELECT COUNT(*) FROM programs WHERE project_id = ?", (p["id"],)).fetchone()[0]
        critic = conn.execute("SELECT data FROM events WHERE project_id = ? AND type = 'critic' ORDER BY seq DESC LIMIT 1", (p["id"],)).fetchone()
        verdict = loads(critic["data"]) if critic else {}
        costs = [c for j in jobs if (c := loads(j["result"]).get("cost"))]
        lang = language(conn, p)
        notes = []
        if p["replay_of"]:
            notes.append("replay copy")
        if lang != "en":
            notes.append(f"{lang} run")
        if not versions:
            notes.append("no version")
        if not verdict:
            notes.append("not reviewed")
        if not p["cover"]:
            notes.append("no cover")
        out.append({
            "id": p["id"], "title": p["title"], "pack": p["pack"] or "-", "public": p["public"],
            "featured": p["featured"] if featured else None, "lang": lang, "versions": versions,
            "runs": len(done), "duration": duration(done[0]["finished_at"] - done[0]["created_at"]),
            "critic": f"{verdict.get('verdict', '?')} {verdict.get('match_score', '')}".strip() if verdict else "-",
            "cost": sum(j["cost_usd"] for j in jobs), "models": models_text(costs), "notes": ", ".join(notes),
        })
    # featured first in home-page order, then the reviewed runs with the most work in them
    out.sort(key=lambda c: (-(c["featured"] or 0), c["critic"] == "-", -c["versions"]))
    return out


def show_candidates(conn: sqlite3.Connection) -> None:
    if not has_featured(conn):
        print("note: projects.featured is missing (the server adds it on its next start); --feature needs it\n")
    rows = candidates(conn)
    if not rows:
        print("no finished design runs yet")
        return
    print(f"{'project':<20} {'feat':>4} {'pub':>3} {'lang':<4} {'vers':>4} {'runs':>4} {'first run':>9} {'critic':<11} {'usd':>7}  title / models / notes")
    for c in rows:
        feat = "-" if c["featured"] is None else str(c["featured"] or "")
        print(f"{c['id']:<20} {feat:>4} {c['public']:>3} {c['lang']:<4} {c['versions']:>4} {c['runs']:>4} {c['duration']:>9} "
              f"{c['critic'][:11]:<11} {c['cost']:>7.4f}  {c['title'][:40]} [{c['pack']}]")
        print(f"{'':<20} models: {c['models']}" + (f"   ! {c['notes']}" if c["notes"] else ""))
    print("\nFeature the best English runs, best first:  python scripts/curate_demo.py --feature <id> <id> ... --apply")


# ------------------------------------------------------------------ changes
def project_rows(conn: sqlite3.Connection, ids: list[str]) -> list[sqlite3.Row]:
    rows = []
    for pid in ids:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
        if not row:
            sys.exit(f"no project {pid}")
        rows.append(row)
    return rows


# ------------------------------------------------------------------ the feature guard
# the front of a finish step's summary (agent/loop.py): an accepted finish the reviewer did not approve says so first
REVIEW_TAG = re.compile(r'^\{"accepted": true, "review": "(notes|none)"')


def _critic_text(c: dict) -> str:
    score = c.get("match_score")
    return f"{c.get('verdict', '?')}{f' {score:g}/10' if isinstance(score, (int, float)) else ''}"


def last_finish(conn: sqlite3.Connection, pid: str) -> tuple[str, str]:
    """How the project's last finish ended: ('approved' | 'notes' | 'none' | 'rejected' | 'missing', why). Recent runs
    tag the step's summary (review: notes|none); older ones are read from the review that ran inside that finish."""
    steps = [(e["seq"], d) for e in conn.execute("SELECT seq, data FROM events WHERE project_id = ? AND type = 'tool.result' AND data LIKE "
                                                 "'%finish%' ORDER BY seq", (pid,)) if (d := loads(e["data"])).get("name") == "finish"]
    if not steps:
        return "missing", "no finish step: no version went through the independent review"
    seq, d = steps[-1]
    opened = conn.execute("SELECT MAX(seq) FROM events WHERE project_id = ? AND type = 'tool.call' AND seq < ? AND data LIKE ?",
                          (pid, seq, f"%{d.get('id') or 'finish'}%")).fetchone()[0]
    row = conn.execute("SELECT data FROM events WHERE project_id = ? AND type = 'critic' AND seq > ? AND seq < ? ORDER BY seq DESC LIMIT 1",
                       (pid, opened or 0, seq)).fetchone()
    critic = loads(row["data"]) if row else {}
    seen = f" (reviewer: {_critic_text(critic)} on version {critic.get('version')})" if critic.get("verdict") else ""
    summary = str(d.get("summary") or "")
    if d.get("ok") is False:
        return "rejected", f"its last finish was turned down: {d.get('title') or 'not accepted'}{seen}"
    tag = REVIEW_TAG.match(summary)
    if tag:
        state = tag[1]
    elif '"unresolved":' in summary:
        state = "notes"  # older runs: accepted on the third attempt with the reviewer's major issues still open
    elif critic.get("reviewer") == "unavailable" or critic.get("note") == "reviewer unavailable":
        state = "none"
    elif critic:
        state = "notes" if critic.get("verdict") == "revise" else "approved"
    else:
        # no review ran inside this finish (a follow-up that built nothing has no new version to review): the latest
        # version's own review decides, so a run whose reviewer said 'revise' is not approved by a later quiet finish
        return _latest_review(conn, pid)
    why = {"notes": f"its last finish was handed over with the reviewer's notes still open{seen}",
           "none": "its last finish was handed over without a review: the reviewer did not answer",
           "approved": f"approved{seen}"}[state]
    return state, why


def _latest_review(conn: sqlite3.Connection, pid: str) -> tuple[str, str]:
    """The reviewer's last word on the latest version, for a finish that ran no review of its own. A board without a
    case (pack 'pcb' with no review at all) ships without one: nothing to hold against it. A device has no LLM reviewer
    (settings.device_reviewer is off): its finish's own checklist, which the run must have passed, takes that place."""
    version = conn.execute("SELECT MAX(version) FROM programs WHERE project_id = ?", (pid,)).fetchone()[0]
    reviews = [d for e in conn.execute("SELECT data FROM events WHERE project_id = ? AND type = 'critic' ORDER BY seq DESC", (pid,))
               if (d := loads(e["data"]))]
    pack = (conn.execute("SELECT pack FROM projects WHERE id = ?", (pid,)).fetchone() or [None])[0]
    if not reviews and pack == "pcb":
        return "approved", "approved (a board without a case: no review runs)"
    if not reviews and pack == "device":
        row = conn.execute("SELECT data FROM events WHERE project_id = ? AND type = 'device.self_check' ORDER BY seq DESC LIMIT 1", (pid,)).fetchone()
        if row and loads(row["data"]).get("passed"):
            return "approved", "approved (a device: its finish's self-check passed)"
        return "none", "its last finish has no passed self-check, and a device has no reviewer to look at it instead"
    critic = next((c for c in reviews if c.get("version") == version), None)
    if critic is None:
        # older reviews did not record their version: the last of them still tells open notes apart
        old = next((c for c in reviews if c.get("version") is None), None)
        if old and old.get("verdict") == "revise":
            return "notes", f"its last finish ran no review, and the reviewer's last notes are still open (reviewer: {_critic_text(old)})"
        return "none", f"its last finish ran no review, and no review of its latest version v{version} is recorded"
    seen = f" (reviewer: {_critic_text(critic)} on version {version}, before its last finish)"
    if critic.get("reviewer") == "unavailable" or critic.get("note") == "reviewer unavailable":
        return "none", f"its latest version v{version} was handed over without a review: the reviewer did not answer"
    if critic.get("verdict") == "revise":
        return "notes", f"its last finish ran no review, and the reviewer's notes on its latest version are still open{seen}"
    return "approved", f"approved{seen}"


def latest_checks(conn: sqlite3.Connection, pid: str) -> str | None:
    """Why the latest version fails its own checks (printability, and the case against its board), or None."""
    row = conn.execute("SELECT version, checks FROM programs WHERE project_id = ? ORDER BY version DESC LIMIT 1", (pid,)).fetchone()
    if not row:
        return None
    checks = loads(row["checks"])
    out = []
    if checks.get("ok") is False:
        codes = [str(i.get("code") or i.get("text") or "?") for i in checks.get("issues") or [] if i.get("severity") == "error"]
        out.append(f"its latest version v{row['version']} fails the printability checks" + (f" ({', '.join(codes[:4])})" if codes else ""))
    enc = checks.get("enclosure")
    if isinstance(enc, dict) and enc.get("ok") is False:
        codes = [str(f.get("code")) for f in enc.get("findings") or [] if f.get("severity") == "error"]
        out.append(f"the case of v{row['version']} does not pass its board check" + (f" ({', '.join(codes[:4])})" if codes else ""))
    return "; ".join(out) or None


def rebuild_board(source: str, intent: dict | None) -> dict:
    """A stored circuit built again by today's engine, offline in the sandboxed PCB worker (no model is called): the
    stored checks are what the engine said then, and a featured replay must not show a board that fails now."""
    sys.path.insert(0, str(SERVER_DIR))
    from formwright.pcb import PcbPool

    async def build() -> dict:
        pool = PcbPool(1)
        try:
            return await pool.build(source, intent=intent)
        finally:
            await pool.close()

    return asyncio.run(build())


def board_errors(conn: sqlite3.Connection, p: sqlite3.Row) -> tuple[list[str], str | None]:
    """For a PCB run: (why its latest board must not be featured, why it could not be checked)."""
    has_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'pcb_boards'").fetchone()
    row = conn.execute("SELECT * FROM pcb_boards WHERE project_id = ? ORDER BY version DESC LIMIT 1", (p["id"],)).fetchone() if has_table else None
    if row is None:
        return (["it has no PCB version"], None) if p["pack"] == "pcb" else ([], None)
    stored = len(loads(row["checks"]).get("errors") or [])
    sys.path.insert(0, str(SERVER_DIR))
    from formwright.pcb import PcbError

    try:
        intent = json.loads(row["intent"]) if row["intent"] else None
        print(f"rebuilding PCB v{row['version']} of {p['id']} offline (the PCB worker, no model)...")
        build = rebuild_board(row["source"], intent if isinstance(intent, dict) else None)
    except PcbError as e:
        if e.stage in ("compile", "runtime"):  # the circuit itself: worse than a DRC error, and --force does not lift it
            return [f"its PCB v{row['version']} does not build with today's engine: {str(e)[:240]}"], None
        return [], f"its PCB v{row['version']} could not be rebuilt here (PcbError: {str(e)[:200]})"
    except Exception as e:  # noqa: BLE001 - no bundle, no Node, a worker crash: say so, the caller decides
        return [], f"its PCB v{row['version']} could not be rebuilt here ({type(e).__name__}: {str(e)[:200]})"
    errors = build.get("errors") or []
    if not errors:
        print(f"  PCB v{row['version']}: 0 DRC errors today")
        return [], None
    then = f"; it stored {stored} when it was made" if stored != len(errors) else ""
    return [f"its latest board, PCB v{row['version']}, has {len(errors)} DRC error(s) with today's engine{then}: "
            + "; ".join(f"{e.get('type')}{' ' + str(e['ref']) if e.get('ref') else ''}: {str(e.get('message') or '')[:160]}" for e in errors[:3])], None


def guard(conn: sqlite3.Connection, p: sqlite3.Row) -> tuple[list[str], list[str]]:
    """Why a run must not be featured: (hard reasons, which --force does not lift; the rest, which it does)."""
    soft = []
    state, why = last_finish(conn, p["id"])
    if state != "approved":
        soft.append(why)
    if bad := latest_checks(conn, p["id"]):
        soft.append(bad)
    hard, unchecked = board_errors(conn, p)
    if unchecked:
        soft.append(unchecked)
    return hard, soft


def feature(conn: sqlite3.Connection, ids: list[str], apply: bool, force: bool = False) -> None:
    require_featured(conn)
    rows = project_rows(conn, ids)
    refused = []
    for p in rows:
        if p["replay_of"]:
            sys.exit(f"{p['id']} is a replay copy of {p['replay_of']}; feature the original")
        hard, soft = guard(conn, p)
        for why in hard + soft:
            print(f"{'refused' if why in hard or not force else 'forced'}  {p['id']}  {why}")
        if hard or (soft and not force):
            refused.append(p["id"])
        if not conn.execute("SELECT 1 FROM jobs WHERE project_id = ? AND kind = 'design' AND status = 'done'", (p["id"],)).fetchone():
            print(f"warning: {p['id']} has no finished design job, so its replay shows no agent work")
        if not conn.execute("SELECT 1 FROM programs WHERE project_id = ?", (p["id"],)).fetchone():
            print(f"warning: {p['id']} has no version, so there is no model to show")
        if (lang := language(conn, p)) != "en":
            print(f"warning: {p['id']} is a {lang} run; judges and the video are in English")
    if refused:
        sys.exit(f"\nnothing changed: {', '.join(refused)} cannot be featured as {'it is' if len(refused) == 1 else 'they are'}. "
                 "Feature another run, or pass --force for a run the reviewer did not approve (never for board errors).")
    # above everything featured before, in the order given
    top = conn.execute(f"SELECT COALESCE(MAX(featured), 0) FROM projects WHERE featured > 0 AND id NOT IN ({','.join('?' * len(ids))})",
                       ids).fetchone()[0]
    for i, p in enumerate(rows):
        rank = top + len(rows) - i
        print(f"{'set' if apply else 'would set'} public=1 featured={rank}  {p['id']}  {p['title']}")
        if apply:
            conn.execute("UPDATE projects SET public = 1, featured = ? WHERE id = ?", (rank, p["id"]))


def unfeature(conn: sqlite3.Connection, ids: list[str], apply: bool) -> None:
    require_featured(conn)
    rows = project_rows(conn, ids) if ids else conn.execute("SELECT * FROM projects WHERE featured > 0").fetchall()
    if not rows:
        print("nothing is featured")
    for p in rows:
        # it stays public: sharing is the owner's choice, made in the studio
        print(f"{'set' if apply else 'would set'} featured=0  {p['id']}  {p['title']}")
        if apply:
            conn.execute("UPDATE projects SET featured = 0 WHERE id = ?", (p["id"],))


def empty_and_stuck(conn: sqlite3.Connection) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    t = time.time()
    empty = conn.execute("SELECT * FROM projects WHERE user_id != ? AND public = 0 AND status != 'working' AND updated_at < ? AND "
                         "NOT EXISTS (SELECT 1 FROM programs WHERE programs.project_id = projects.id) ORDER BY updated_at",
                         (ARCHIVE_OWNER, t - 3600)).fetchall()
    stuck = [p for p in conn.execute("SELECT * FROM projects WHERE status = 'working' ORDER BY updated_at").fetchall()
             if (conn.execute("SELECT MAX(ts) FROM events WHERE project_id = ?", (p["id"],)).fetchone()[0] or p["updated_at"]) < t - STALE_S]
    return empty, stuck


def list_empty(conn: sqlite3.Connection, apply: bool) -> None:
    empty, stuck = empty_and_stuck(conn)
    print(f"{len(empty)} projects without a version (idle for an hour or more):")
    for p in empty:
        print(f"  {p['id']}  user {p['user_id']}  {time.strftime('%Y-%m-%d %H:%M', time.localtime(p['updated_at']))}  {p['title']}")
    print(f"\n{len(stuck)} projects stuck 'working' with no event for {STALE_S // 60} min:")
    for p in stuck:
        print(f"  {p['id']}  user {p['user_id']}  {p['title']}")
    if stuck:
        print("  The server frees these on its next start: it marks their jobs failed and the projects idle.")
    if empty:
        if apply:
            archive(conn, [p["id"] for p in empty], True)
        else:
            print(f"\nArchive the empty ones with --apply, or pick: python scripts/curate_demo.py --archive {' '.join(p['id'] for p in empty)} --apply")


def take_down(conn: sqlite3.Connection, ids: list[str], apply: bool, hidden: bool = True) -> None:
    """What an admin's button on the replay does (POST /api/replays/<id>/hide), for a server with no admin signed in."""
    for p in project_rows(conn, ids):
        print(f"{'set' if apply else 'would set'} hidden={int(hidden)}{' public=0 listed=0 featured=0' if hidden else ''}  {p['id']}  {p['title']}")
        if apply:
            conn.execute("UPDATE projects SET hidden = 1, public = 0, listed = 0, featured = 0 WHERE id = ?" if hidden else "UPDATE projects SET hidden = 0 WHERE id = ?", (p["id"],))


def archive(conn: sqlite3.Connection, ids: list[str], apply: bool) -> None:
    """Moves projects out of their owner's list; the owner is kept in brief.archived_from for --restore."""
    for p in project_rows(conn, ids):
        if p["user_id"] == ARCHIVE_OWNER:
            print(f"already archived  {p['id']}")
            continue
        if p["public"]:
            sys.exit(f"{p['id']} is public; unfeature and unshare it before archiving")
        print(f"{'archived' if apply else 'would archive'}  {p['id']}  (user {p['user_id']})  {p['title']}")
        if apply:
            brief = {**loads(p["brief"]), "archived_from": p["user_id"]}
            conn.execute("UPDATE projects SET user_id = ?, brief = ? WHERE id = ?", (ARCHIVE_OWNER, json.dumps(brief, ensure_ascii=False), p["id"]))


def restore(conn: sqlite3.Connection, ids: list[str], apply: bool) -> None:
    for p in project_rows(conn, ids):
        brief = loads(p["brief"])
        owner = brief.pop("archived_from", None)
        if p["user_id"] != ARCHIVE_OWNER or not owner:
            print(f"not archived  {p['id']}")
            continue
        print(f"{'restored' if apply else 'would restore'}  {p['id']}  to user {owner}  {p['title']}")
        if apply:
            conn.execute("UPDATE projects SET user_id = ?, brief = ? WHERE id = ?", (owner, json.dumps(brief, ensure_ascii=False), p["id"]))


def stats(conn: sqlite3.Connection) -> None:
    """Cost, cache and timing numbers, measured on this database (read-only)."""
    jobs = conn.execute("SELECT * FROM jobs").fetchall()
    if not jobs:
        print("no jobs yet")
        return
    kinds: dict[str, int] = {}
    for j in jobs:
        kinds[f"{j['kind']} {j['status']}"] = kinds.get(f"{j['kind']} {j['status']}", 0) + 1
    first, last = min(j["created_at"] for j in jobs), max(j["created_at"] for j in jobs)
    print(f"{len(jobs)} jobs from {time.strftime('%d %b', time.localtime(first))} to {time.strftime('%d %b %Y', time.localtime(last))}: "
          + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    tin, cached = sum(j["tokens_in"] for j in jobs), sum(j["tokens_cached"] for j in jobs)
    print(f"total ${sum(j['cost_usd'] for j in jobs):.3f}; input tokens served from cache: {cached / tin:.0%} ({cached:,} of {tin:,})" if tin else "no tokens")
    done = [j for j in jobs if j["kind"] == "design" and j["status"] == "done" and j["finished_at"]]
    if done:
        costs = [j["cost_usd"] for j in done]
        took = [j["finished_at"] - j["created_at"] for j in done]
        print(f"{len(done)} finished designs: median ${statistics.median(costs):.4f} (max ${max(costs):.4f}), "
              f"median {duration(statistics.median(took))} (range {duration(min(took))} to {duration(max(took))})")
    first_model = [ts - j["created_at"] for j in jobs if j["kind"] == "design"
                   and (ts := conn.execute("SELECT MIN(ts) FROM events WHERE job_id = ? AND type = 'program.updated'", (j["id"],)).fetchone()[0])]
    if first_model:
        print(f"time to the first model: median {duration(statistics.median(first_model))} "
              f"(range {duration(min(first_model))} to {duration(max(first_model))}, {len(first_model)} design jobs that built one)")
    usd: dict[str, float] = {}
    calls: dict[str, int] = {}
    for j in jobs:
        cost = loads(j["result"]).get("cost") or {}
        for model, v in (cost.get("by_model") or {}).items():
            usd[model] = usd.get(model, 0) + v
        for model, n in (cost.get("calls_by_model") or {}).items():
            calls[model] = calls.get(model, 0) + n
    print("by model: " + ", ".join(f"{m} ${v:.4f}" + (f" ({calls[m]} calls)" if m in calls else "") for m, v in sorted(usd.items(), key=lambda kv: -kv[1])))
    if calls.keys() - usd.keys():
        print("also called (no USD price): " + ", ".join(f"{m} x{calls[m]}" for m in sorted(calls.keys() - usd.keys())))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # titles are in the user's language
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=None, help="formwright.db (default: FW_DATA_DIR or data/ in the repo)")
    ap.add_argument("--apply", action="store_true", help="write the changes (without it nothing is written)")
    ap.add_argument("--force", action="store_true", help="--feature a run the reviewer did not approve or whose checks fail "
                                                         "(never a board with DRC errors)")
    act = ap.add_mutually_exclusive_group()
    act.add_argument("--feature", nargs="+", metavar="ID", help="make public and featured, first one shown first")
    act.add_argument("--unfeature", nargs="*", metavar="ID", help="stop featuring these (all when none given)")
    act.add_argument("--list-empty", action="store_true", help="projects without a version or stuck 'working'; --apply archives the empty ones")
    act.add_argument("--archive", nargs="+", metavar="ID", help="hide projects from their owner's list (reversible)")
    act.add_argument("--restore", nargs="+", metavar="ID", help="give archived projects back to their owner")
    act.add_argument("--take-down", nargs="+", metavar="ID", help="take published runs down: off the gallery, their links closed")
    act.add_argument("--put-back", nargs="+", metavar="ID", help="let their owners publish taken-down runs again")
    act.add_argument("--stats", action="store_true", help="cost, cache and timing numbers of the recorded runs")
    args = ap.parse_args()

    path = args.db or default_db()
    writes = args.feature or args.unfeature is not None or args.list_empty or args.archive or args.restore or args.take_down or args.put_back
    conn = connect(path, write=bool(args.apply and writes))
    print(f"database: {path}{'' if args.apply or not writes else '  (dry run: add --apply to write)'}\n")
    with conn:
        if args.feature:
            feature(conn, args.feature, args.apply, args.force)
        elif args.unfeature is not None:
            unfeature(conn, args.unfeature, args.apply)
        elif args.list_empty:
            list_empty(conn, args.apply)
        elif args.archive:
            archive(conn, args.archive, args.apply)
        elif args.restore:
            restore(conn, args.restore, args.apply)
        elif args.take_down:
            take_down(conn, args.take_down, args.apply)
        elif args.put_back:
            take_down(conn, args.put_back, args.apply, hidden=False)
        elif args.stats:
            stats(conn)
        else:
            show_candidates(conn)
    conn.close()


if __name__ == "__main__":
    main()
