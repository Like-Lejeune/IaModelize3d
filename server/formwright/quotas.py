"""Credits instead of request counts: jobs differ 100x in cost, so limits are in USD.

A job reserves its budget before it starts and settles the real cost from usage
afterwards. A global daily cap protects the API credits; when it gets close, the
service degrades (strong model -> fast model -> replays only).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

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


class QuotaExceeded(Exception):
    pass


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


async def reserve(user: dict, budget: float) -> float:
    """Returns the budget this job may spend: the requested cap, shrunk to what is left today."""
    limit, concurrent, _ = TIERS.get(user["tier"], TIERS["anon"])
    usd, _jobs = await spent_today(user["id"])
    db = await get_db()
    running = await db.one("SELECT COUNT(*) AS n, COALESCE(SUM(reserved_usd), 0) AS r FROM jobs WHERE user_id = ? AND status IN ('running', 'waiting')", user["id"])
    if running and running["n"] >= concurrent:
        raise QuotaExceeded("another job is still running")
    left = limit - usd - (running["r"] if running else 0)
    if user["tier"] == "anon" and user.get("ip"):
        # anonymous sessions are cheap to create; cap what one address spends per day
        row = await db.one("SELECT COALESCE(SUM(s.usd), 0) AS usd FROM spend s JOIN users u ON u.id = s.user_id "
                           "WHERE u.ip = ? AND u.tier = 'anon' AND s.day = ?", user["ip"], _today())
        left = min(left, ANON_PER_IP - float(row["usd"]))
    global_left = settings().daily_budget_usd - await global_spent_today()
    allowed = min(budget, left, global_left)
    if global_left < MIN_JOB_USD:
        raise QuotaExceeded("the demo budget for today is used up; replays and sliders still work")
    if allowed < MIN_JOB_USD:
        raise QuotaExceeded(f"daily limit ${limit:.2f} reached; sliders, checks and downloads still work")
    return allowed


async def settle(user_id: str, usd: float) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO spend (user_id, day, usd, jobs) VALUES (?, ?, ?, 1) "
        "ON CONFLICT(user_id, day) DO UPDATE SET usd = usd + excluded.usd, jobs = jobs + 1",
        user_id, _today(), usd,
    )


async def choose_models(user: dict, effort: str = "auto") -> ModelChoice:
    s = settings()
    _, _, strong = TIERS.get(user["tier"], TIERS["anon"])
    near_cap = await global_spent_today() > s.daily_budget_usd * 0.8
    contributor = bool(user.get("contributor_consent")) and user["tier"] in ("anon", "free")
    fast = s.model_free if contributor else s.model_fast
    designer = s.model_designer_hard if (effort == "hard" and strong and not near_cap) else (s.model_free if contributor else s.model_designer)
    return ModelChoice(designer=designer, fast=fast, contributor=contributor)
