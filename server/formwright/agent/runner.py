"""Job lifecycle: quota reservation, background task, questions to the user, settlement."""
from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .. import events, quotas
from ..config import settings
from ..db import get_db, new_id, now
from ..llm.client import BudgetExceeded, CostMeter
from ..models import SendMessage

log = logging.getLogger(__name__)


@dataclass
class JobContext:
    job_id: str
    kind: str
    project: dict[str, Any]
    user: dict[str, Any]
    meter: CostMeter
    models: quotas.ModelChoice
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    questions: dict[str, asyncio.Future] = field(default_factory=dict)

    @property
    def project_id(self) -> str:
        return self.project["id"]

    async def emit(self, type_: str, data: dict[str, Any] | None = None) -> None:
        await events.emit(self.project_id, type_, data or {}, self.job_id)

    async def status(self, text: str) -> None:
        await self.emit("agent.status", {"text": text})

    async def ask(self, question: str, options: list[str] | None = None, allow_text: bool = True, timeout: float = 900) -> str | None:
        qid = new_id("q_")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.questions[qid] = fut
        await self.emit("ask", {"job_id": self.job_id, "question_id": qid, "question": question, "options": options or [], "allow_text": allow_text})
        db = await get_db()
        await db.update("jobs", "id", self.job_id, {"status": "waiting"})
        try:
            answer = await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            answer = None
        finally:
            self.questions.pop(qid, None)
            await db.update("jobs", "id", self.job_id, {"status": "running"})
        await self.emit("answer", {"question_id": qid, "answer": answer})
        return answer

    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise asyncio.CancelledError()


_jobs: dict[str, JobContext] = {}
_tasks: dict[str, asyncio.Task] = {}


async def _create(user: dict[str, Any], project: dict[str, Any], kind: str, payload: dict[str, Any], budget: float, effort: str = "auto") -> JobContext:
    await quotas.reserve(user, budget)
    db = await get_db()
    job_id = new_id("j_")
    await db.insert("jobs", {"id": job_id, "project_id": project["id"], "user_id": user["id"], "kind": kind, "status": "running",
                             "input": payload, "reserved_usd": budget, "created_at": now()})
    models = await quotas.choose_models(user, effort)
    ctx = JobContext(job_id=job_id, kind=kind, project=project, user=user, meter=CostMeter(budget_usd=budget), models=models)
    _jobs[job_id] = ctx
    await db.update("projects", "id", project["id"], {"status": "working", "updated_at": now()})
    await ctx.emit("job.started", {"job_id": job_id, "kind": kind, "model": models.designer, "contributor": models.contributor})
    return ctx


def _spawn(ctx: JobContext, work: Callable[[JobContext], Awaitable[str | None]]) -> None:
    async def run() -> None:
        status, summary = "done", None
        try:
            summary = await work(ctx)
        except BudgetExceeded as e:
            status, summary = "budget", str(e)
        except asyncio.CancelledError:
            status, summary = "cancelled", "stopped"
        except Exception as e:  # noqa: BLE001
            log.error("job %s failed: %s\n%s", ctx.job_id, e, traceback.format_exc())
            status, summary = "failed", f"{type(e).__name__}: {e}"[:500]
        finally:
            db = await get_db()
            cost = ctx.meter.summary()
            await quotas.settle(ctx.user["id"], ctx.meter.usd)
            await db.update("jobs", "id", ctx.job_id, {"status": status, "finished_at": now(), "cost_usd": ctx.meter.usd, "result": {"summary": summary, "cost": cost},
                                                      "tokens_in": ctx.meter.tokens_in, "tokens_out": ctx.meter.tokens_out, "tokens_cached": ctx.meter.tokens_cached})
            await db.update("projects", "id", ctx.project_id, {"status": "idle", "updated_at": now()})
            await ctx.emit("cost", cost)
            await ctx.emit("job.finished", {"job_id": ctx.job_id, "status": status, "summary": summary, "cost": cost})
            _jobs.pop(ctx.job_id, None)
            _tasks.pop(ctx.job_id, None)

    _tasks[ctx.job_id] = asyncio.create_task(run())


async def add_message(project_id: str, role: str, text: str, data: dict[str, Any] | None = None) -> str:
    db = await get_db()
    mid = new_id("msg_")
    await db.insert("messages", {"id": mid, "project_id": project_id, "role": role, "text": text, "data": data or {}, "created_at": now()})
    return mid


async def start_design_job(user: dict[str, Any], project: dict[str, Any], body: SendMessage) -> str:
    from .loop import design

    budget = settings().job_budget_usd * (2.5 if body.effort == "hard" else 1.0)
    ctx = await _create(user, project, "design", body.model_dump(), budget, body.effort)
    await add_message(project["id"], "user", body.text, {"asset_ids": body.asset_ids})
    await ctx.emit("user.message", {"text": body.text, "asset_ids": body.asset_ids})
    _spawn(ctx, lambda c: design(c, body))
    return ctx.job_id


async def start_side_job(user: dict[str, Any], project: dict[str, Any], kind: str, payload: dict[str, Any]) -> str:
    from . import side

    work = {
        "slice": side.slice_job,
        "probe": side.probe_job,
        "concepts": side.concepts_job,
        "breed": side.breed_job,
        "visual_edit": side.visual_edit_job,
    }[kind]
    budget = {"slice": 0.08, "probe": 0.05, "concepts": 0.12, "breed": 0.5, "visual_edit": settings().job_budget_usd}[kind]
    ctx = await _create(user, project, kind, payload, budget)
    _spawn(ctx, lambda c: work(c, payload))
    return ctx.job_id


async def deliver_answer(job_id: str, user_id: str, answer: str) -> bool:
    ctx = _jobs.get(job_id)
    if not ctx or ctx.user["id"] != user_id:
        return False
    for fut in list(ctx.questions.values()):
        if not fut.done():
            fut.set_result(answer)
            return True
    return False


async def cancel_job(job_id: str, user_id: str) -> None:
    ctx = _jobs.get(job_id)
    if ctx and ctx.user["id"] == user_id:
        ctx.cancelled.set()
        task = _tasks.get(job_id)
        if task:
            task.cancel()
