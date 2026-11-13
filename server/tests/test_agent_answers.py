"""The reviewer sees what the person answered, and the person sees their own words. A shop order's run opens with the
customer's request (SendMessage.shown) while the model's brief stays in the message's data.brief, which the reviewer
reads; the reviewer gets the designer's questions of the run with the answers quoted verbatim (and a few answered ones
of earlier runs), so it never calls an answered question open; the runner's own lines use the job input's language
before the brief exists. Offline: models are stubs."""
from __future__ import annotations

import asyncio

import pytest

from iamodelize3d import db as dbmod, events, storage
from iamodelize3d.agent import critic, loop, runner, tools
from iamodelize3d.agent.tools import DesignState
from iamodelize3d.llm.client import CostMeter
from iamodelize3d.models import SendMessage
from iamodelize3d.quotas import ModelChoice

from test_loop_handover import FakeMeta, _png, _use, call, fake_tools, fresh_db, offline  # noqa: F401 (fixtures)

QUESTION = "Сколько колёс нужно напечатать для нижней корзины?"
OWN = "Колесо для нижней корзины посудомойки Bosch: диаметр 25 мм, ширина 8 мм, ось 5 мм, надевается со щелчком"
BRIEF = ("Spare part order IM-1002: design a printable replacement part from the photos.\n"
         "The part: dishwasher lower basket wheel.\nMaterial: PETG. Quantity: 1.\n"
         "The intake desk could not tell: Сколько колёс нужно напечатать? If the photos do not answer it, ask the customer.\n"
         "The customer's request:\n" + OWN)
MODELS = ModelChoice(designer="muse-spark-1.3", fast="muse-spark-1.3", contributor=False)


async def _user(db, uid: str = "u1") -> dict:
    await db.insert("users", {"id": uid, "tier": "anon", "created_at": dbmod.now()})
    return await db.one("SELECT * FROM users WHERE id = ?", uid)


async def _project(db, pid: str = "p1", uid: str = "u1", **brief) -> dict:
    t = dbmod.now()
    await db.insert("projects", {"id": pid, "user_id": uid, "title": "Basket wheel", "pack": "household", "brief": brief,
                                 "created_at": t, "updated_at": t})
    return await db.one("SELECT * FROM projects WHERE id = ?", pid)


class Reviewer:
    """The critic's model: keeps what it was shown, answers a pass."""

    def __init__(self):
        self.seen: list[str] = []

    def model_for(self, role, default):
        return default

    async def json(self, meter, *, content, **kw):
        self.seen.append("\n".join(p["text"] for p in content if p["type"] == "input_text"))
        return {"verdict": "pass", "match_score": 9, "issues": []}


def test_send_message_shown_is_optional():
    """CONTRACT: SendMessage.shown, None by default; an unknown field is still ignored."""
    assert SendMessage(text="x").shown is None
    assert SendMessage(text=BRIEF, shown=OWN, language="ru").shown == OWN
    assert SendMessage.model_validate({"text": "x", "shown": "y", "later": 1}).model_dump()["shown"] == "y"


async def _start(db, monkeypatch, body: SendMessage, pid: str) -> str:
    gate = asyncio.Event()

    async def waits(ctx, body):
        await gate.wait()
        return "ok"

    monkeypatch.setattr(loop, "design", waits)
    user = await db.one("SELECT * FROM users WHERE id = 'u1'") or await _user(db)
    jid = await runner.start_design_job(user, await _project(db, pid), body)
    gate.set()
    await asyncio.wait_for(runner._tasks[jid], 10)
    return jid


async def test_a_shop_run_shows_the_customers_words_and_keeps_the_brief(fresh_db, monkeypatch):
    jid = await _start(fresh_db, monkeypatch, SendMessage(text=BRIEF, shown=OWN, language="ru"), "p_shop")
    [m] = await fresh_db.all("SELECT text, data FROM messages WHERE project_id = 'p_shop' AND role = 'user'")
    assert m["text"] == OWN and m["data"] == {"asset_ids": [], "brief": BRIEF}
    [e] = [e for e in await events.since("p_shop", 0) if e["type"] == "user.message"]
    assert e["data"] == {"text": OWN, "asset_ids": []}
    # the job input is what the model got, with the shown words beside it
    req = (await fresh_db.one("SELECT input FROM jobs WHERE id = ?", jid))["input"]
    assert req["text"] == BRIEF and req["shown"] == OWN
    assert runner.model_text(m) == BRIEF


@pytest.mark.parametrize("shown", [None, "", "   ", "make the hook 2 mm longer"])
async def test_a_studio_message_is_stored_as_before(fresh_db, monkeypatch, shown):
    """No shown words (or the same words as the text): the text is the message, and the data has no brief."""
    await _start(fresh_db, monkeypatch, SendMessage(text="make the hook 2 mm longer", shown=shown), "p_studio")
    [m] = await fresh_db.all("SELECT text, data FROM messages WHERE project_id = 'p_studio' AND role = 'user'")
    assert m["text"] == "make the hook 2 mm longer" and m["data"] == {"asset_ids": []}
    [e] = [e for e in await events.since("p_studio", 0) if e["type"] == "user.message"]
    assert e["data"]["text"] == "make the hook 2 mm longer"


def test_the_model_reads_the_brief_of_a_stored_message():
    assert runner.model_text({"text": OWN, "data": {"asset_ids": [], "brief": BRIEF}}) == BRIEF
    # rows written before shown existed, and data that is not what it should be
    assert runner.model_text({"text": "a bracket", "data": {"asset_ids": []}}) == "a bracket"
    for data in (None, "x", [], {"brief": ""}, {"brief": "  "}, {"brief": 3}):
        assert runner.model_text({"text": "a bracket", "data": data}) == "a bracket"


# ---------------------------------------------------------------- the live case: the quantity was answered


async def test_the_reviewer_sees_the_customers_answer_to_the_designers_question(fresh_db, offline, monkeypatch):
    """The RU wheel order: the designer asks how many wheels, the customer answers '1 колесо', and the reviewer reads
    the brief, the question and the answer verbatim, told that an answered question is settled."""
    user = await _user(fresh_db)
    project = await _project(fresh_db)
    fake = fake_tools([])

    async def run_tool(ctx, state, name, args):
        # the real ask (it waits on the job) and the real finish (the review); builds are stubs
        return await (tools.run_tool if name in ("ask_user", "finish") else fake)(ctx, state, name, args)

    monkeypatch.setattr(loop, "run_tool", run_tool)
    monkeypatch.setattr(loop, "_harvest_skill", lambda *a: asyncio.sleep(0))
    _use(monkeypatch, FakeMeta([[call("ask_user", {"question": QUESTION, "options": ["1 колесо", "2 колеса", "4 колеса"]})],
                                [call("write_program", {"source": "x", "summary": "колесо"}, "c2")],
                                [call("finish", {"summary": "Готово: колесо, 1 шт."}, "c3")]]))
    reviewer = Reviewer()
    monkeypatch.setattr(critic, "meta", lambda: reviewer)

    jid = await runner.start_design_job(user, project, SendMessage(text=BRIEF, shown=OWN, language="ru"))
    task = runner._tasks[jid]
    for _ in range(200):
        if any(e["type"] == "ask" for e in await events.since("p1", 0)):
            break
        await asyncio.sleep(0.02)
    assert await runner.deliver_answer(jid, "u1", "1 колесо")
    await asyncio.wait_for(task, 20)

    [seen] = reviewer.seen
    assert seen.startswith("Request: " + BRIEF)
    assert ("Questions the designer asked the person, with the answers quoted verbatim. An answered question is settled: "
            "never report it as unanswered, unclear or still to be confirmed.") in seen
    assert f'- "{QUESTION}" Answer: "1 колесо"' in seen
    # the customer's words are inside the brief already: not repeated
    assert "The person's own words" not in seen
    row = await fresh_db.one("SELECT status FROM jobs WHERE id = ?", jid)
    assert row["status"] == "done"
    [m] = await fresh_db.all("SELECT text FROM messages WHERE project_id = 'p1' AND role = 'user'")
    assert m["text"] == OWN


async def _ask(pid: str, job: str, qid: str, question: str, answer: str | None, *, answered: bool = True) -> None:
    await events.emit(pid, "ask", {"job_id": job, "question_id": qid, "question": question, "options": [], "allow_text": True}, job)
    if answered:
        await events.emit(pid, "answer", {"question_id": qid, "answer": answer}, job)


async def test_answers_of_this_run_and_earlier_runs(fresh_db):
    for n in range(6):  # six earlier runs answered a question each; one more had no answer
        await _ask("p1", f"j_old{n}", f"q_old{n}", f"Earlier question {n}?", f"answer {n}")
    await _ask("p1", "j_old9", "q_old9", "Nobody answered this?", None)
    await _ask("p1", "j_now", "q_1", "Сколько штук?", "1 колесо")
    await _ask("p1", "j_now", "q_2", "Which side is up?", None)
    await _ask("p1", "j_now", "q_3", 'Say "hi"', '  he said "two"\nthen left  ')
    await _ask("p_other", "j_x", "q_x", "Another project?", "no")
    lines = await critic.answered("p1", "j_now")
    assert lines == [
        *[f'- (for an earlier request) "Earlier question {n}?" Answer: "answer {n}"' for n in (2, 3, 4, 5)],
        '- "Сколько штук?" Answer: "1 колесо"',
        '- "Which side is up?" No answer came: the designer went on with an assumption it states.',
        '- "Say \\"hi\\"" Answer: "he said \\"two\\"\\nthen left"',
    ]
    # a question still waiting is not shown; a long answer is cut with an ellipsis
    await _ask("p2", "j_now", "q_w", "Still waiting?", None, answered=False)
    await _ask("p2", "j_now", "q_l", "Long?", "x" * 1500)
    assert await critic.answered("p2", "j_now") == [f'- "Long?" Answer: "{"x" * critic.QUOTE}…"']
    assert await critic.answered("p_none", "j_now") == []


async def _review(db, monkeypatch, *messages: tuple[str, dict], job: str = "j_now") -> str:
    t = dbmod.now()
    for i, (text, data) in enumerate(messages):
        await db.insert("messages", {"id": f"m{i}", "project_id": "p1", "role": "user", "text": text, "data": data, "created_at": t + i})
    reviewer = Reviewer()
    monkeypatch.setattr(critic, "meta", lambda: reviewer)
    ctx = runner.JobContext(job_id=job, kind="design", project={"id": "p1", "brief": {"language": "ru"}}, user={"id": "u1"},
                            meter=CostMeter(), models=MODELS)
    st = DesignState(pack="household", source="x", version=1, last_build={"checks": {"stats": {"size": [25, 25, 8]}}},
                     last_render=storage.save_bytes("p1", "renders", "v1.png", _png()))
    await critic.review(ctx, st)
    return reviewer.seen[0]


async def test_the_reviewer_reads_briefs_and_the_persons_own_words(fresh_db, monkeypatch):
    """A catalog order's shown line is not inside its brief: the reviewer gets it as the person's own words. A studio
    message from before shown existed reads as it always did."""
    seen = await _review(fresh_db, monkeypatch, ("a wheel", {"asset_ids": []}),
                         ("Заказ IM-1002: Колёсико нижней корзины", {"asset_ids": [], "brief": "Spare part order IM-1002: print listing L1."}))
    lines = seen.split("\n")
    assert lines[0] == "Request: a wheel / Spare part order IM-1002: print listing L1."
    assert lines[1] == 'The person\'s own words: "Заказ IM-1002: Колёсико нижней корзины"'
    assert lines[2] == "Request language: ru (write text_user in it)"
    assert "Questions the designer asked" not in seen


async def test_an_earlier_answer_is_marked_as_one_a_later_request_may_change(fresh_db, monkeypatch):
    await _ask("p1", "j_old", "q_old", "Сколько штук?", "2")
    await _ask("p1", "j_now", "q_now", "Какой цвет?", "белый")
    seen = await _review(fresh_db, monkeypatch, ("колесо", {"asset_ids": []}), ("сделай шире", {"asset_ids": []}))
    lines = seen.split("\n")
    assert lines[1].endswith("never report it as unanswered, unclear or still to be confirmed; a later request may still change an earlier answer.")
    assert lines[2:4] == ['- (for an earlier request) "Сколько штук?" Answer: "2"', '- "Какой цвет?" Answer: "белый"']


# ---------------------------------------------------------------- the runner's own lines: the job input's language first


async def _crash(db, pid: str, payload: dict, brief: dict | None = None) -> str:
    user = await db.one("SELECT * FROM users WHERE id = 'u1'") or await _user(db)
    await _project(db, pid, **(brief or {}))

    async def crashes(ctx):
        raise KeyError("version")

    ctx = await runner._create(user, {"id": pid, "user_id": "u1"}, "design", payload)
    runner._spawn(ctx, crashes)
    await asyncio.wait_for(ctx.finished.wait(), 10)
    [e] = [e for e in await events.since(pid, 0) if e["type"] == "job.finished"]
    return e["data"]["summary"]


@pytest.mark.parametrize("payload, brief, ru", [
    ({"text": BRIEF.split("\n")[0], "language": "ru"}, None, True),  # an English brief, the intake's language: before design() wrote it
    ({"text": "a wheel", "language": "Russian"}, {"language": "en"}, True),  # the job input beats the brief, as a name too
    ({"text": "a wheel", "language": "ru-RU"}, None, True),
    ({"text": "a wheel", "language": "en"}, {"language": "ru"}, False),
    ({"text": "a wheel", "language": "not a language"}, {"language": "ru"}, True),  # not a language: the brief decides
    ({"text": "Spare part order IM-1002", "shown": "Колесо для корзины"}, None, True),  # the person's own words
    ({"text": "Колесо для корзины"}, None, True),
    ({"text": "a wheel"}, None, False),
])
async def test_a_crash_before_the_brief_uses_the_jobs_language(fresh_db, payload, brief, ru):
    summary = await _crash(fresh_db, "p_crash", payload, brief)
    assert summary.startswith(runner.CRASHED[1] if ru else runner.CRASHED[0]), summary


async def test_the_loop_answers_in_the_language_of_the_persons_own_words(fresh_db, offline, monkeypatch):
    """No language from the caller: the shown words decide (an English brief would have said English)."""
    ctx = runner.JobContext(job_id="j1", kind="design", project=await _project(fresh_db), user={"id": "u1"},
                            meter=CostMeter(budget_usd=0.6), models=MODELS)
    _use(monkeypatch, FakeMeta([[call("write_program", {"source": "x", "summary": "колесо"})], [call("finish", {"summary": "Готово"}, "c2")]]))
    await loop.design(ctx, SendMessage(text="Spare part order IM-1002: print the basket wheel.", shown="Заказ IM-1002: Колёсико корзины"))
    brief = (await fresh_db.one("SELECT brief FROM projects WHERE id = 'p1'"))["brief"]
    assert brief["language"] == "ru"
    # the model's own text is what the brief keeps as the request
    assert brief["turns"] == ["Spare part order IM-1002: print the basket wheel."]
