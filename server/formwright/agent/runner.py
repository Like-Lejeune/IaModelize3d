"""Job lifecycle: quota reservation, background task, questions to the user, settlement.

Every job has a wall-clock deadline: past it the agent wraps up (it reads `ctx.deadline`), and
HARD_STOP_S later the task is stopped. Time spent waiting for an answer does not count.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import re
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError

from .. import events, quotas
from ..config import settings
from ..db import get_db, new_id, now
from ..geom import GeomError
from ..llm.client import BudgetExceeded, CostMeter
from ..models import SendMessage
from . import narrate

log = logging.getLogger(__name__)

HARD_STOP_S = 300.0  # past its deadline a job gets this long to hand over: a designer turn in flight may take 240 s
CANCEL_WAIT_S = 5.0  # Stop returns once the job has finished, or after this long
TOO_LONG = "took too long; the latest version is kept"
# kinds that run the designer model and get a design job's deadline; the rest get side_deadline_s
DESIGNER_KINDS = ("design", "visual_edit", "breed")
# a crashed job's summary is read by people (the job card, Telegram): a calm line, never the exception or a path
CRASHED = ("Something broke on our side, so I stopped here.", "У нас что-то сломалось, поэтому я остановился.")
SERVICE_ERRORS = (APIStatusError, APIConnectionError, APITimeoutError, httpx.HTTPError)


def crash_summary(e: BaseException, error_id: str, language: str | None) -> str:
    """'The model service stopped answering, so I stopped here. Error id: e_…': the id finds the full error in the log."""
    en, ru = narrate.HANDOVER["failed"] if isinstance(e, SERVICE_ERRORS) else narrate.HANDOVER["engine"] if isinstance(e, GeomError) else CRASHED
    return f"{ru} Код ошибки: {error_id}." if narrate._ru(language) else f"{en} Error id: {error_id}."


@dataclass
class JobContext:
    job_id: str
    kind: str
    project: dict[str, Any]
    user: dict[str, Any]
    meter: CostMeter
    models: quotas.ModelChoice
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)  # the row, the brief and job.finished are written
    questions: dict[str, asyncio.Future] = field(default_factory=dict)
    # time.monotonic() values; a question moves the deadline by the time it waited
    started: float = field(default_factory=time.monotonic)
    deadline: float = math.inf
    # set by the work to end as 'budget' or 'failed' while still returning its summary
    final_status: str | None = None
    hard_stop: asyncio.Timeout | None = field(default=None, repr=False)

    @property
    def project_id(self) -> str:
        return self.project["id"]

    async def emit(self, type_: str, data: dict[str, Any] | None = None) -> None:
        await events.emit(self.project_id, type_, data or {}, self.job_id)

    async def status(self, text: str) -> None:
        await self.emit("agent.status", {"text": text})

    def _arm(self, wait: float = 0.0) -> None:
        """Puts the hard stop HARD_STOP_S past the deadline (and past a question's `wait`)."""
        if self.hard_stop is None or self.hard_stop.expired():
            return
        left = max(self.deadline - time.monotonic(), wait)
        self.hard_stop.reschedule(None if math.isinf(left) else asyncio.get_running_loop().time() + left + HARD_STOP_S)

    async def ask(self, question: str, options: list[str] | None = None, allow_text: bool = True, timeout: float | None = None) -> str | None:
        timeout = settings().ask_timeout_s if timeout is None else timeout
        qid = new_id("q_")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.questions[qid] = fut
        await self.emit("ask", {"job_id": self.job_id, "question_id": qid, "question": question, "options": options or [], "allow_text": allow_text})
        db = await get_db()
        await db.update("jobs", "id", self.job_id, {"status": "waiting"})
        asked = time.monotonic()
        self._arm(timeout)  # the wait itself never trips the hard stop
        try:
            answer = await asyncio.wait_for(fut, timeout)
        except TimeoutError:
            answer = None
        finally:
            self.questions.pop(qid, None)
            self.deadline += time.monotonic() - asked
            self._arm()
            await db.update("jobs", "id", self.job_id, {"status": "running"})
        await self.emit("answer", {"question_id": qid, "answer": answer})
        return answer

    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise asyncio.CancelledError()


_jobs: dict[str, JobContext] = {}
_tasks: dict[str, asyncio.Task] = {}
# one start at a time per user, so two starts cannot both pass the quota check
_starting: dict[str, asyncio.Lock] = {}


def live_jobs() -> set[str]:
    """The jobs this process runs and nobody has stopped: the only ones quotas count."""
    return {jid for jid, c in _jobs.items() if not c.cancelled.is_set()}


async def _create(user: dict[str, Any], project: dict[str, Any], kind: str, payload: dict[str, Any], budget: float, effort: str = "auto",
                  model: str | None = None, *, models: quotas.ModelChoice | None = None, concurrency: bool = True) -> JobContext:
    s = settings()
    db = await get_db()
    async with _starting.setdefault(user["id"], asyncio.Lock()):
        if concurrency:
            # one agent at a time per project (slices and probes aside): two would interleave versions
            other = next((c for c in _jobs.values() if c.project_id == project["id"] and c.kind not in quotas.LIGHT_KINDS
                          and not c.cancelled.is_set()), None)
            if other:
                raise quotas.QuotaExceeded("this project is already being worked on", code="project_busy", project_id=project["id"], job_id=other.job_id)
        budget = await quotas.reserve(user, budget, live=live_jobs(), concurrency=concurrency)
        models = models or await quotas.choose_models(user, effort, model)
        job_id = new_id("j_")
        await db.insert("jobs", {"id": job_id, "project_id": project["id"], "user_id": user["id"], "kind": kind, "status": "running",
                                 "input": payload, "reserved_usd": budget, "created_at": now()})
        ctx = JobContext(job_id=job_id, kind=kind, project=project, user=user, meter=CostMeter(budget_usd=budget), models=models)
        ctx.deadline = ctx.started + (s.design_deadline_s if kind in DESIGNER_KINDS else s.side_deadline_s)
        _jobs[job_id] = ctx
    await db.update("projects", "id", project["id"], {"status": "working", "updated_at": now()})
    await ctx.emit("job.started", {"job_id": job_id, "kind": kind, "model": models.designer, "contributor": models.contributor})
    return ctx


async def _keep_request(project_id: str, job_id: str, status: str) -> None:
    """Keeps an interrupted design request in the brief, so "Continue" picks up where it stopped."""
    db = await get_db()
    p = await db.one("SELECT brief FROM projects WHERE id = ?", project_id)
    brief = (p or {}).get("brief") or {}
    req = (await db.one("SELECT input FROM jobs WHERE id = ?", job_id) or {}).get("input") or {}
    turns = (brief.get("turns") or []) + [f"{str(req.get('text', ''))[:200]} (interrupted: {status})"]
    await db.update("projects", "id", project_id, {"brief": {**brief, "turns": turns[-10:]}})


async def _language(ctx: JobContext) -> str | None:
    """The person's language for a line the runner writes itself: the one the request named (a shop order's intake,
    SendMessage.language), read from the job input first, so a crash before the loop writes the brief still has it;
    else the brief's, else the script of the person's own words (as the loop guesses)."""
    from .loop import language_hint

    db = await get_db()
    req = (await db.one("SELECT input FROM jobs WHERE id = ?", ctx.job_id) or {}).get("input") or {}
    named = language_hint(req.get("language"))
    if named:
        return named
    brief = (await db.one("SELECT brief FROM projects WHERE id = ?", ctx.project_id) or {}).get("brief") or {}
    said = str(req.get("shown") or req.get("text") or "")
    return brief.get("language") or ("ru" if re.search(r"[А-Яа-яЁё]", said) else None)


def _spawn(ctx: JobContext, work: Callable[[JobContext], Awaitable[str | None]]) -> None:
    async def finalize(status: str, summary: str | None, crash: tuple[BaseException, str] | None = None) -> None:
        try:
            db = await get_db()
            if crash:
                language = None
                with contextlib.suppress(Exception):  # a nicety: the bookkeeping must not fail on it
                    language = await _language(ctx)
                summary = crash_summary(*crash, language)
            cost = ctx.meter.summary()
            await quotas.settle(ctx.user["id"], ctx.meter.usd)
            await db.update("jobs", "id", ctx.job_id, {"status": status, "finished_at": now(), "cost_usd": ctx.meter.usd, "result": {"summary": summary, "cost": cost},
                                                      "tokens_in": ctx.meter.tokens_in, "tokens_out": ctx.meter.tokens_out, "tokens_cached": ctx.meter.tokens_cached})
            await db.update("projects", "id", ctx.project_id, {"status": "idle", "updated_at": now()})
            if ctx.kind == "design" and status in ("failed", "budget", "cancelled"):
                await _keep_request(ctx.project_id, ctx.job_id, status)
            await ctx.emit("cost", cost)
            await ctx.emit("job.finished", {"job_id": ctx.job_id, "status": status, "summary": summary, "cost": cost})
        finally:
            _jobs.pop(ctx.job_id, None)
            _tasks.pop(ctx.job_id, None)
            ctx.finished.set()

    async def run() -> None:
        status, summary = "done", None
        crash: tuple[BaseException, str] | None = None
        hard: asyncio.Timeout | None = None
        try:
            async with asyncio.timeout(None) as hard:
                ctx.hard_stop = hard
                ctx._arm()
                summary = await work(ctx)
            status = ctx.final_status or "done"
        except BudgetExceeded as e:
            status, summary = "budget", str(e)
        except asyncio.CancelledError:
            status, summary = "cancelled", "stopped"
        except Exception as e:  # noqa: BLE001
            if isinstance(e, TimeoutError) and hard is not None and hard.expired():
                log.warning("job %s stopped at its deadline", ctx.job_id)
                status, summary = "failed", TOO_LONG
            else:
                # the full error only goes to the log; finalize writes the summary people read, with this id
                eid = new_id("e_")
                log.error("job %s failed (%s): %s: %s\n%s", ctx.job_id, eid, type(e).__name__, e, traceback.format_exc())
                status, crash = "failed", (e, eid)
        ctx.hard_stop = None
        # the bookkeeping runs to the end even when Stop is pressed again meanwhile
        done = asyncio.ensure_future(finalize(status, summary, crash))
        while True:
            try:
                await asyncio.shield(done)
                return
            except asyncio.CancelledError:
                if done.done():  # the bookkeeping itself was cancelled (shutdown): nothing left to wait for
                    return
                continue
            except Exception:  # noqa: BLE001
                log.exception("job %s: finishing failed", ctx.job_id)
                return

    def never_ran(task: asyncio.Task) -> None:
        # a task cancelled before its first step skips its body, the bookkeeping included
        if task.cancelled() and not ctx.finished.is_set():
            _tasks[ctx.job_id] = asyncio.ensure_future(finalize("cancelled", "stopped"))

    _tasks[ctx.job_id] = asyncio.create_task(run())
    _tasks[ctx.job_id].add_done_callback(never_ran)


async def add_message(project_id: str, role: str, text: str, data: dict[str, Any] | None = None) -> str:
    db = await get_db()
    mid = new_id("msg_")
    await db.insert("messages", {"id": mid, "project_id": project_id, "role": role, "text": text, "data": data or {}, "created_at": now()})
    return mid


def shown_text(body: SendMessage) -> str | None:
    """The words the person sees as their own message, when the caller wrote `text` for the model (SendMessage.shown)."""
    shown = (body.shown or "").strip()
    return shown if shown and shown != body.text.strip() else None


def model_text(message: dict[str, Any]) -> str:
    """What a model reads for a stored user message: the brief it was given (data.brief) when the person was shown
    other words, else the message's text."""
    data = message.get("data")
    brief = data.get("brief") if isinstance(data, dict) else None
    return brief if isinstance(brief, str) and brief.strip() else str(message.get("text") or "")


async def start_design_job(user: dict[str, Any], project: dict[str, Any], body: SendMessage) -> str:
    from .loop import design

    s = settings()
    models = await quotas.choose_models(user, body.effort, body.model)
    # the bigger budget only when the strongest designer really runs (it may be off the plan, or the demo budget near its cap)
    strongest = models.designer == s.model_designer_hard and (body.model == "wonder" or (body.model is None and body.effort == "hard"))
    budget = s.job_budget_usd * (2.5 if strongest else 1.0) * {"high": 1.5, "xhigh": 2.0, "max": 3.0}.get(body.reasoning, 1.0)
    ctx = await _create(user, project, "design", body.model_dump(), budget, models=models)
    # a shop order's run opens with the customer's own words; the model's brief stays in the message for the reviewer
    shown = shown_text(body)
    await add_message(project["id"], "user", shown or body.text, {"asset_ids": body.asset_ids, **({"brief": body.text} if shown else {})})
    await ctx.emit("user.message", {"text": shown or body.text, "asset_ids": body.asset_ids})
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
    ctx = await _create(user, project, kind, payload, budget, concurrency=kind not in quotas.LIGHT_KINDS)
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


async def cancel_job(job_id: str, user_id: str) -> bool:
    """Stops the job and returns once it has finished; False when there was nothing to stop.
    A row with no task behind it (left 'running' by a restart) is closed right here."""
    ctx = _jobs.get(job_id)
    if ctx:
        if ctx.user["id"] != user_id:
            return False
        task = _tasks.get(job_id)
        if not ctx.cancelled.is_set():  # a second Stop must not interrupt the first one's bookkeeping
            ctx.cancelled.set()
            if task:
                task.cancel()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(ctx.finished.wait(), CANCEL_WAIT_S)
        return True
    db = await get_db()
    row = await db.one("SELECT * FROM jobs WHERE id = ? AND user_id = ? AND status IN ('running', 'waiting')", job_id, user_id)
    if not row:
        return False
    cost = (row.get("result") or {}).get("cost") or CostMeter(budget_usd=0).summary()
    await db.update("jobs", "id", job_id, {"status": "cancelled", "finished_at": now(), "result": {"summary": "stopped", "cost": cost}})
    if not any(c.project_id == row["project_id"] for c in _jobs.values()):
        await db.update("projects", "id", row["project_id"], {"status": "idle", "updated_at": now()})
    if row["kind"] == "design":
        await _keep_request(row["project_id"], job_id, "cancelled")
    await events.emit(row["project_id"], "job.finished", {"job_id": job_id, "status": "cancelled", "summary": "stopped", "cost": cost}, job_id)
    return True
