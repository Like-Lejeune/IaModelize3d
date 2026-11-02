"""Credits instead of request counts: jobs differ 100x in cost, so limits are in USD.

A job reserves its budget before it starts and settles the real cost from usage
afterwards. A global daily cap protects the API credits; when it gets close, the
service degrades (strong model -> fast model -> replays only). Model calls outside
jobs (snaps, spots, selections, the face blur) reserve nothing: they only stop when
today's budget is spent (`check_light`).
"""
from __future__ import annotations

import datetime as dt
import ipaddress
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .config import settings
from .db import get_db

TIERS = {
    # daily USD, concurrent jobs, may use the strongest designer
    "anon": (1.00, 1, False),
    "free": (2.00, 1, False),
    "pro": (8.00, 3, True),
    "axo": (3.00, 2, True),
    "admin": (50.0, 5, True),
}
# side jobs that take seconds: they neither wait for another job nor hold one up
LIGHT_KINDS = ("slice", "probe")


class QuotaExceeded(Exception):
    """`code` names the limit for the client (job_running, project_busy, daily_limit, ip_daily_cap,
    demo_budget); `info` carries what it needs to say so, e.g. the blocking job's project_id and job_id."""

    def __init__(self, message: str, code: str = "quota", **info: Any) -> None:
        super().__init__(message)
        self.code = code
        self.info = info


@dataclass
class ModelChoice:
    designer: str
    fast: str
    contributor: bool


def _today() -> str:
    return dt.date.today().isoformat()


async def spent_today(user_id: str) -> tuple[float, int]:
    db = await get_db()
    row = await db.one("SELECT usd, jobs FROM spend WHERE user_id = ? AND day = ?", user_id, _today())
    return (row["usd"], row["jobs"]) if row else (0.0, 0)


async def global_spent_today() -> float:
    db = await get_db()
    row = await db.one("SELECT COALESCE(SUM(usd), 0) AS usd FROM spend WHERE day = ?", _today())
    return float(row["usd"]) if row else 0.0


MIN_JOB_USD = 0.05
ANON_PER_IP = 3.0


def network(ip: str) -> str:
    """What the per-address cap counts (stored as users.ip): an IPv4 address, or the /64 of an IPv6 one, since a
    single home or phone gets a whole /64 and could otherwise draw a fresh address for every session."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip[:64]
    if addr.version == 6 and addr.ipv4_mapped:
        return str(addr.ipv4_mapped)
    return str(ipaddress.ip_network(f"{addr}/64", strict=False)) if addr.version == 6 else str(addr)


def _live() -> set[str]:
    from .agent import runner  # the runner imports this module

    return runner.live_jobs()


async def active_jobs(user_id: str, live: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """This user's jobs that have a task behind them in this process (`live`: their ids, the
    runner's by default). A row left 'running' by a restart or a hang is not one of them."""
    ids = list(_live() if live is None else live)
    if not ids:
        return []
    db = await get_db()
    return await db.all(f"SELECT id, project_id, kind, status, reserved_usd FROM jobs WHERE user_id = ? AND id IN ({','.join('?' * len(ids))}) "
                        "AND status IN ('running', 'waiting') ORDER BY created_at", user_id, *ids)


def blocking(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The jobs that count toward the concurrency limit: one waiting for an answer holds nobody up."""
    return [r for r in rows if r["status"] == "running" and r["kind"] not in LIGHT_KINDS]


async def _left(user: dict) -> tuple[float, float, float]:
    """What is left today on the user's plan, for their address (anonymous users) and in the demo budget (for
    anonymous users, in the share of it they have together)."""
    limit = TIERS.get(user["tier"], TIERS["anon"])[0]
    usd, _jobs = await spent_today(user["id"])
    ip_left = math.inf
    s = settings()
    global_left = s.daily_budget_usd - await global_spent_today()
    if user["tier"] == "anon":
        db = await get_db()
        if user.get("ip"):
            # anonymous sessions are cheap to create; cap what one address spends per day
            row = await db.one("SELECT COALESCE(SUM(s.usd), 0) AS usd FROM spend s JOIN users u ON u.id = s.user_id "
                               "WHERE u.ip = ? AND u.tier = 'anon' AND s.day = ?", user["ip"], _today())
            ip_left = ANON_PER_IP - float(row["usd"])
        # and what all of them spend together, which no number of addresses gets around
        row = await db.one("SELECT COALESCE(SUM(s.usd), 0) AS usd FROM spend s JOIN users u ON u.id = s.user_id "
                           "WHERE u.tier = 'anon' AND s.day = ?", _today())
        global_left = min(global_left, s.daily_budget_usd * s.anon_budget_share - float(row["usd"]))
    return limit - usd, ip_left, global_left


def _check(user: dict, left: float, ip_left: float, global_left: float, need: float) -> None:
    if global_left < need:
        raise QuotaExceeded("the demo budget for today is used up; replays and sliders still work", code="demo_budget")
    if ip_left < need:
        raise QuotaExceeded(f"today's ${ANON_PER_IP:.2f} for anonymous use from this network is spent; sliders, checks and downloads still work",
                            code="ip_daily_cap", limit_usd=ANON_PER_IP)
    if left < need:
        limit = TIERS.get(user["tier"], TIERS["anon"])[0]
        raise QuotaExceeded(f"daily limit ${limit:.2f} reached; sliders, checks and downloads still work", code="daily_limit", limit_usd=limit)


async def reserve(user: dict, budget: float, *, live: Iterable[str] | None = None, concurrency: bool = True) -> float:
    """Returns the budget this job may spend: the requested cap, shrunk to what is left today.
    `concurrency`: False for light side jobs, which may run next to another job."""
    _, concurrent, _ = TIERS.get(user["tier"], TIERS["anon"])
    rows = await active_jobs(user["id"], live)
    running = blocking(rows)
    if concurrency and len(running) >= concurrent:
        raise QuotaExceeded("another job is still running", code="job_running", project_id=running[0]["project_id"], job_id=running[0]["id"])
    left, ip_left, global_left = await _left(user)
    if concurrency:
        # a light job beside a design job is checked against what was really spent, not the design job's reservation
        left -= sum(r["reserved_usd"] for r in rows)
    _check(user, left, ip_left, global_left, MIN_JOB_USD)
    return min(budget, left, ip_left, global_left)


async def check_light(user: dict, est: float = 0.01) -> None:
    """Before a model call outside a job. Running jobs' reservations are not subtracted: the
    agent's own selections come through here too, and its job may have reserved all that is left."""
    _check(user, *await _left(user), need=est)


async def settle(user_id: str, usd: float, is_job: bool = True) -> None:
    """Adds the real cost; `is_job`: False for calls outside jobs, which do not count as jobs."""
    if not usd and not is_job:
        return
    db = await get_db()
    await db.execute(
        "INSERT INTO spend (user_id, day, usd, jobs) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, day) DO UPDATE SET usd = usd + excluded.usd, jobs = jobs + excluded.jobs",
        user_id, _today(), usd, int(is_job),
    )


def _strong(user: dict) -> bool:
    # judges try the service anonymously: FW_DEMO_WONDER opens the strongest designer to every plan
    return TIERS.get(user["tier"], TIERS["anon"])[2] or settings().demo_wonder


def model_options(user: dict) -> list[dict]:
    s = settings()
    options = [
        {"key": "contributor", "id": s.model_free, "available": True},
        {"key": "spark", "id": s.model_designer, "available": True},
        {"key": "wonder", "id": s.model_designer_hard, "available": _strong(user)},
    ]
    # dev configs may route the designer to the contributor model too; do not list it twice
    return [o for i, o in enumerate(options) if o["id"] not in {p["id"] for p in options[:i]}]


async def choose_models(user: dict, effort: str = "auto", model: str | None = None) -> ModelChoice:
    s = settings()
    near_cap = await global_spent_today() > s.daily_budget_usd * 0.8
    if model is None:
        consent = bool(user.get("contributor_consent")) and user["tier"] in ("anon", "free")
        model = "wonder" if effort == "hard" else "contributor" if consent else "spark"
    contributor = model == "contributor"
    fast = s.model_free if contributor else s.model_fast
    designer = s.model_designer_hard if (model == "wonder" and _strong(user) and not near_cap) else (s.model_free if contributor else s.model_designer)
    return ModelChoice(designer=designer, fast=fast, contributor=contributor)
