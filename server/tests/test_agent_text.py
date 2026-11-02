"""What the agent says matches what happened: a finish the reviewer did not approve reads 'handed over', not
'Approved', and the hand-over says the reviewer's notes; every message is answered in its own language; the reviewer
gets a legend of the parts in the renders (names, roles, colours, layout) that agrees with the pixels; a board scan
names the models that read it and keeps its scale inside the timeline's 600 characters. Offline: models are stubs."""
from __future__ import annotations

import base64
import io
import json

import numpy as np
import pytest
from PIL import Image

from formwright import geom as geommod, storage
from formwright.agent import critic, elec_tools as et, loop, narrate as n
from formwright.agent.tools import DesignState
from formwright.config import settings
from formwright.geom import GeomPool
from formwright.models import SendMessage

from test_elec_tools import PICO, FakeCtx
from test_loop_handover import FakeMeta, _events, _png, _project, _use, call, fake_tools, fresh_db, offline, say  # noqa: F401 (fixtures)

LED = {"severity": "major", "text": "LED window missing on the lid", "text_user": "The LED window is missing from the lid.", "fix_hint": "cut it"}
EDGE = {"severity": "minor", "text": "sharp lid edge", "text_user": "The lid edge is sharp.", "fix_hint": "chamfer"}


# ---------------------------------------------------------------- the finish: accepted is not approved


def test_a_finish_reads_how_the_review_ended():
    t = n.result_title
    assert t("finish", {}, {"accepted": True}) == "Approved"
    # tools._finish from the third attempt: accepted, the reviewer's major issues still open
    assert t("finish", {}, {"accepted": True, "unresolved": ["LED window missing on the lid"]}) == "Handed over; the reviewer still has notes"
    assert t("finish", {}, {"accepted": True, "review": "notes"}) == "Handed over; the reviewer still has notes"
    assert t("finish", {}, {"accepted": True, "review": "none"}) == "Handed over without a review: the reviewer did not answer"
    assert n.localize(t("finish", {}, {"accepted": True, "unresolved": ["x"]}), "ru") == "Сдано; у ревьюера остались замечания"
    assert n.localize(t("finish", {}, {"accepted": True, "review": "none"}), "ru") == "Сдано без проверки: ревьюер не ответил"
    assert n.localize(t("finish", {}, {"accepted": False, "reason": "the reviewer found major problems"}), "ru") == "Пока нет: ревьюер нашёл серьёзные замечания"


def test_the_review_state_and_the_line_after_the_summary():
    revise = {"verdict": "revise", "match_score": 4.0, "issues": [EDGE, LED], "version": 8, "reviewer": "primary", "report_only": True}
    assert n.review_of(revise, 8) == "notes" and n.review_of(revise, 9) is None
    assert n.review_of({"verdict": "pass", "version": 8}, 8) is None and n.review_of(None, 8) is None
    gone = {"verdict": "pass", "note": "reviewer unavailable", "reviewer": "unavailable", "version": 8}
    assert n.review_of(gone, 8) == "none"
    # the major issue first, in the person's words
    assert n.review_notes(revise, 8, "en") == ("The independent reviewer still has notes on version 8 (4/10): "
                                               "The LED window is missing from the lid; The lid edge is sharp.")
    ru = {**revise, "issues": [{**LED, "text_user": "В крышке нет окна для светодиода."}], "match_score": 4.5}
    assert n.review_notes(ru, 8, "ru") == "У независимого ревьюера остались замечания к версии 8 (4.5/10): В крышке нет окна для светодиода."
    assert n.review_notes(gone, 8, "ru") == "Независимый ревьюер не ответил, поэтому версия 8 не проверена."
    assert n.review_notes({"verdict": "pass", "version": 8}, 8, "en") == "" and n.review_notes(revise, 7, "en") == ""


def _finish_with(critic_state: dict | None, accepted: dict):
    def outcome(state):
        state.critic = {**critic_state, "version": state.version} if critic_state else None
        state.done, state.summary = True, "Snap-fit case for your Pico W."
        return dict(accepted)

    return outcome


async def _finish_run(fresh_db, monkeypatch, critic_state, accepted, text="Add a window over the LED"):
    ctx = await _project(fresh_db)
    monkeypatch.setattr(loop, "run_tool", fake_tools([], _finish_with(critic_state, accepted)))
    _use(monkeypatch, FakeMeta([[call("write_program", {"source": "x", "summary": "LED window"})], [call("finish", {"summary": "done"}, "c2")]]))
    await loop.design(ctx, SendMessage(text=text))
    evs = await _events()
    res = next(e["data"] for e in evs if e["type"] == "tool.result" and e["data"]["name"] == "finish")
    msg = next(e["data"]["text"] for e in evs if e["type"] == "agent.message")
    return res, msg


async def test_a_hand_over_with_the_reviewers_notes_open_never_reads_approved(fresh_db, offline, monkeypatch):
    revise = {"verdict": "revise", "match_score": 4.0, "issues": [EDGE, LED], "reviewer": "primary", "report_only": True}
    res, msg = await _finish_run(fresh_db, monkeypatch, revise, {"accepted": True, "unresolved": [LED["text"]]})
    assert res["ok"] is True and res["title"] == "Handed over; the reviewer still has notes"
    # the web rebuilds the other language from the front of the summary
    assert res["summary"].startswith('{"accepted": true, "review": "notes", "unresolved": [')
    assert msg == ("Snap-fit case for your Pico W.\n\nThe independent reviewer still has notes on version 1 (4/10): "
                   "The LED window is missing from the lid; The lid edge is sharp.")
    assert "Approved" not in msg


async def test_a_hand_over_without_an_answer_from_the_reviewer_says_so(fresh_db, offline, monkeypatch):
    gone = {"verdict": "pass", "match_score": None, "issues": [], "note": "reviewer unavailable", "reviewer": "unavailable"}
    res, msg = await _finish_run(fresh_db, monkeypatch, gone, {"accepted": True})
    assert res["title"] == "Handed over without a review: the reviewer did not answer" and '"review": "none"' in res["summary"]
    assert msg.endswith("The independent reviewer did not answer, so version 1 is not reviewed.")


async def test_a_pass_is_still_approved_and_the_summary_stands_alone(fresh_db, offline, monkeypatch):
    res, msg = await _finish_run(fresh_db, monkeypatch, {"verdict": "pass", "match_score": 9, "issues": [], "reviewer": "primary"}, {"accepted": True})
    assert res["title"] == "Approved" and res["summary"] == '{"accepted": true}' and msg == "Snap-fit case for your Pico W."


async def test_a_russian_hand_over_says_the_notes_in_russian(fresh_db, offline, monkeypatch):
    revise = {"verdict": "revise", "match_score": 4.0, "issues": [{**LED, "text_user": "В крышке нет окна для светодиода."}], "reviewer": "primary"}
    res, msg = await _finish_run(fresh_db, monkeypatch, revise, {"accepted": True}, text="Добавь окно над светодиодом")
    assert res["title"] == "Сдано; у ревьюера остались замечания"
    assert msg.endswith("У независимого ревьюера остались замечания к версии 1 (4/10): В крышке нет окна для светодиода.")


# ---------------------------------------------------------------- the run's language follows the message


def test_the_language_of_a_message():
    ml = loop.message_language
    assert ml("Сделай крышку на 1 мм толще", "en") == "ru"
    assert ml("Корпус для Raspberry Pi Pico W с USB-C", "en") == "ru"  # Latin product names in a Russian request
    assert ml("Make the lid 1 mm thicker", "ru") == "en"
    assert ml("ok", "ru") == "ru" and ml("", "ru") == "ru" and ml("USB-C", "ru") == "ru" and ml("2 mm", "kk") == "kk"
    assert ml("Қақпақты қалыңырақ жаса", "kk") == "kk" and ml("Mach den Deckel dicker", "de") == "de"
    assert ml("Сделай крышку толще", None) == "ru" and ml("a shelf bracket", None) == "en" and ml("", None) == "en"


async def test_a_russian_message_in_an_english_project_is_answered_in_russian(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db, language="en")
    _use(monkeypatch, FakeMeta([[call("write_program", {"source": "x", "summary": "крышка толще"})], [call("finish", {"summary": "Готово"}, "c2")]]))
    await loop.design(ctx, SendMessage(text="Сделай крышку на 1 мм толще"))
    evs = await _events()
    titles = [e["data"]["title"] for e in evs if e["type"] in ("tool.call", "tool.result")]
    assert titles[:3] == ["Пишу модель: крышка толще", "Версия 1 — 40 × 20 × 10 мм, печатается", "Финальная проверка перед выдачей"]
    assert [e["data"]["label"] for e in evs if e["type"] == "job.stage"][:2] == ["Разбираюсь в задаче", "Проектирую"]
    # the tools and the reviewer read the run's language from the brief; so does the runner's own crash line
    assert ctx.project["brief"]["language"] == "ru"
    assert (await fresh_db.one("SELECT brief FROM projects WHERE id = 'p1'"))["brief"]["language"] == "ru"


async def test_an_english_message_in_a_russian_project_is_answered_in_english(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db, language="ru")
    fake = _use(monkeypatch, FakeMeta([[call("write_program", {"source": "x", "summary": "thicker lid"})], [call("finish", {"summary": "Done."}, "c2")]]))
    await loop.design(ctx, SendMessage(text="Make the lid 1 mm thicker"))
    titles = [e["data"]["title"] for e in await _events() if e["type"] in ("tool.call", "tool.result")]
    assert titles[:2] == ["Writing the model: thicker lid", "Version 1 — 40 × 20 × 10 mm, printable"]
    assert "reply in language: en" in fake.calls[0]["input"][0]["content"][0]["text"]


async def test_a_message_without_words_keeps_the_projects_language(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db, language="ru")
    _use(monkeypatch, FakeMeta([[call("write_program", {"source": "x", "summary": "M3"})], [call("finish", {"summary": "Готово."}, "c2")]]))
    await loop.design(ctx, SendMessage(text="ok"))
    titles = [e["data"]["title"] for e in await _events() if e["type"] in ("tool.call", "tool.result")]
    assert titles[:2] == ["Пишу модель: M3", "Версия 1 — 40 × 20 × 10 мм, печатается"] and ctx.project["brief"]["language"] == "ru"


def test_the_callers_language_as_a_code():
    h = loop.language_hint
    assert h("ru") == "ru" and h(" RU ") == "ru" and h("ru-RU") == "ru" and h("en_US") == "en" and h("kk") == "kk"
    assert h("Russian") == "ru" and h("русский") == "ru" and h("Kazakh") == "kk"
    assert h(None) is None and h("") is None and h("ru ru") is None and h("<script>") is None and h("x") is None


# a shop order: the design brief is English for the model, the customer wrote in Russian
BRIEF_EN = "Replacement dishwasher rack wheel: 25 mm, axle 5 mm, snaps on. Ask before guessing the axle diameter."


async def test_the_callers_language_wins_over_the_messages_script(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db)
    fake = _use(monkeypatch, FakeMeta([[call("write_program", {"source": "x", "summary": "колесо"})], [call("finish", {"summary": "Готово"}, "c2")]]))
    await loop.design(ctx, SendMessage(text=BRIEF_EN, language="ru"))
    evs = await _events()
    titles = [e["data"]["title"] for e in evs if e["type"] in ("tool.call", "tool.result")]
    assert titles[:3] == ["Пишу модель: колесо", "Версия 1 — 40 × 20 × 10 мм, печатается", "Финальная проверка перед выдачей"]
    assert "reply in language: ru" in fake.calls[0]["input"][0]["content"][0]["text"]
    # written to the brief as usual: the tools, the reviewer and the runner read it there
    assert ctx.project["brief"]["language"] == "ru"
    assert (await fresh_db.one("SELECT brief FROM projects WHERE id = 'p1'"))["brief"]["language"] == "ru"
    # an unreadable one is ignored: the script decides
    ctx = await _project(fresh_db, pid="p2")
    fake = _use(monkeypatch, FakeMeta([[call("write_program", {"source": "x", "summary": "wheel"})], [call("finish", {"summary": "Done"}, "c2")]]))
    await loop.design(ctx, SendMessage(text=BRIEF_EN, language="the customer's"))
    assert ctx.project["brief"]["language"] == "en" and "reply in language: en" in fake.calls[0]["input"][0]["content"][0]["text"]


async def test_the_callers_language_wins_over_the_intake(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db)
    await fresh_db.update("projects", "id", "p1", {"title": "New project", "pack": None})
    ctx.project.update({"title": "New project", "pack": None})

    class Intake(FakeMeta):
        async def json(self, meter, **kw):
            self.calls.append({"intake": kw["content"][0]["text"]})
            return self.cls

    fake = _use(monkeypatch, Intake([[call("write_program", {"source": "x", "summary": "колесо"})], [call("finish", {"summary": "Готово"}, "c2")]],
                                    cls={"pack": "household", "title": "Колесо корзины", "refuse": False, "language": "en", "engine": "cad"}))
    await loop.design(ctx, SendMessage(text=BRIEF_EN, language="ru"))
    # the intake is told whose language the title is in, and its 'en' (it read an English brief) does not win
    assert fake.calls[0]["intake"].endswith("The person's language is ru: write title, reason and subject in it.")
    assert ctx.project["brief"]["language"] == "ru" and ctx.project["title"] == "Колесо корзины"
    assert [e["data"]["label"] for e in await _events() if e["type"] == "job.stage"][:2] == ["Разбираюсь в задаче", "Проектирую"]

    # it is in the brief before the intake runs, so the runner's line about a failed intake is in Russian too
    class Down(FakeMeta):
        async def json(self, meter, **kw):
            raise RuntimeError("model down")

    ctx = await _project(fresh_db, pid="p2", language="en")
    await fresh_db.update("projects", "id", "p2", {"title": "New project"})
    ctx.project["title"] = "New project"
    _use(monkeypatch, Down([]))
    with pytest.raises(RuntimeError):
        await loop.design(ctx, SendMessage(text=BRIEF_EN, language="ru"))
    assert (await fresh_db.one("SELECT brief FROM projects WHERE id = 'p2'"))["brief"]["language"] == "ru"


# ---------------------------------------------------------------- progress lines say what changes, not 'You're right'


def test_a_leading_agreement_is_taken_off_a_progress_line():
    w = loop.without_agreement
    assert w("You're right — the LED opening isn't showing clearly. Cutting it through the lid.") == (
        "The LED opening isn't showing clearly. Cutting it through the lid.")
    assert w("You are absolutely right that the lid hides the LED; cutting a window.") == "The lid hides the LED; cutting a window."
    assert w("Good catch: the hooks were too short.") == "The hooks were too short."
    assert w("Thanks for the review — lengthening the hooks to 7 mm.") == "Lengthening the hooks to 7 mm."
    assert w("Вы правы, крышка закрывает светодиод. Прорезаю окно.") == "Крышка закрывает светодиод. Прорезаю окно."
    assert w("Вы правы, что окна нет — прорезаю его в крышке.") == "Окна нет — прорезаю его в крышке."
    assert w("Верно: защёлки короткие, удлиняю до 7 мм.") == "Защёлки короткие, удлиняю до 7 мм."
    # what is not an agreement stays, and so does a line that says nothing else
    for same in ("Right side gets the USB window.", "Верно подобранный зазор остаётся 0.3 мм.", "Opening the LED window: the reviewer "
                 "could not see it.", "You're right.", "Agreed."):
        assert w(same) == same


async def test_progress_lines_after_the_review_do_not_open_with_agreement(fresh_db, offline, monkeypatch):
    ctx = await _project(fresh_db)
    rounds = iter([False, True])

    def outcome(state):
        accepted = next(rounds)
        state.critic = {"verdict": "pass" if accepted else "revise", "version": state.version, "issues": [LED]}
        state.done, state.summary = accepted, "Case with an LED window."
        return {"accepted": accepted, **({} if accepted else {"reason": "the reviewer found major problems", "issues": [LED]})}

    monkeypatch.setattr(loop, "run_tool", fake_tools([], outcome))
    _use(monkeypatch, FakeMeta([
        # the first turn answers the person: what they said is theirs to be right about
        [say("You're right, the old lid had no window."), call("write_program", {"source": "x", "summary": "LED window"})],
        [call("finish", {"summary": "done"}, "c2")],
        [say("You're right — the LED opening isn't showing clearly. Cutting it through the lid."), call("edit_program", {"source": "y"}, "c3")],
        [say("Вы правы, окно всё ещё закрыто."), call("finish", {"summary": "done"}, "c4")],
    ]))
    await loop.design(ctx, SendMessage(text="The lid hides the LED"))
    lines = [e["data"]["text"] for e in await _events() if e["type"] == "agent.status" and e["data"].get("say")]
    assert lines == ["You're right, the old lid had no window.", "The LED opening isn't showing clearly. Cutting it through the lid.",
                     "Окно всё ещё закрыто."]


# ---------------------------------------------------------------- the board scan


def _scan_result(*, ok: bool = True) -> dict:
    board = {**PICO, "id": "photo-rpi-pico-w", "source": {"kind": "photo+dataset", "dataset_id": "rpi-pico-w"}}
    return {"board": board, "boxes": [], "warnings": [], "schema_errors": [], "selection": None,
            "calibration": {"method": "board_holes", "residual_mm": 0.031, "pattern_mm": 0.052, "mm_per_px": 0.0412, "uncertainty_mm": 0.04,
                            "pin_rows": {"rows_x": [1.62, 19.41], "dataset_rows_x": [1.61, 19.39], "pads": [20, 20]}, "H": [[1, 0, 0]] * 3},
            "deltas": [{"part": "usb", "field": "at", "dataset": 10.5, "photo": 10.57, "delta": 0.07, "source": "sam", "applied": False}] * 3,
            "identified": {"board_id": "rpi-pico-w", "marking": "Raspberry Pi Pico W", "confidence": 0.93, "side": "top", "parts": 5}}


async def test_the_scan_puts_what_it_read_and_the_scale_before_the_board(fresh_db, monkeypatch):
    from formwright.vision import board as vb

    await fresh_db.insert("assets", {"id": "a1", "project_id": "p_case", "kind": "photo", "path": "p_case/a1.jpg", "width": 1600, "height": 678,
                                     "meta": {}, "created_at": 0})

    async def scan(meter, asset, hint=None, name="board", *, model=None, refine=True):
        return _scan_result()

    monkeypatch.setattr(vb, "scan_board", scan)
    r, _ = await et.run(FakeCtx(), DesignState(pack="enclosure"), "scan_board", {"asset_id": "a1"})
    assert list(r)[:3] == ["ok", "identified", "calibration"] and r["ok"] is True and "board" in r and "deltas" in r
    # what the timeline keeps of it still names the scale, the board and its size
    cut = n.scrub(json.dumps(r, ensure_ascii=False))[:600]
    assert '"method": "board_holes"' in cut and '"uncertainty_mm": 0.04' in cut and '"name": "Raspberry Pi Pico W"' in cut and '"size_mm": [' in cut
    assert n.result_title("scan_board", {}, r) == "Board read: Raspberry Pi Pico W, scale from its holes ±0.04 mm"


async def test_the_scan_step_names_sam_and_the_fast_model(fresh_db, offline, monkeypatch):
    async def tool(ctx, state, name, args):
        if args.get("asset_id") == "nope":
            return {"ok": False, "error": "unknown asset id; give the id of a photo of this project"}, []
        return {"ok": True, "identified": {"board_id": "rpi-pico-w"}, "calibration": {"method": "board_holes", "uncertainty_mm": 0.04},
                "board": et.board_brief(PICO)}, []

    ctx = await _project(fresh_db)
    monkeypatch.setattr(loop, "run_tool", tool)
    _use(monkeypatch, FakeMeta([[call("scan_board", {"asset_id": "a1"})], [call("scan_board", {"asset_id": "nope"}, "c2")], [say("Done.")]]))
    await loop.design(ctx, SendMessage(text="a case for this Pico W"))
    scans = [e["data"] for e in await _events() if e["type"] == "tool.result" and e["data"]["name"] == "scan_board"]
    assert scans[0]["models"] == [settings().model_sam, "muse-spark-1.3"] and scans[0]["title"].startswith("Board read: Raspberry Pi Pico W")
    assert "models" not in scans[1]  # no photo, no model looked at it


# ---------------------------------------------------------------- the reviewer's legend of the parts


def test_colour_names_of_the_render_palette():
    assert [critic.colour_name(c) for c in critic.PALETTE] == ["light grey", "orange", "blue", "green", "pink", "yellow"]
    assert critic.colour_name((58, 125, 68)) == "green" and critic.colour_name((30, 30, 30)) == "dark grey"
    assert critic.colour_name((128, 128, 128)) == "grey" and critic.colour_name((200, 30, 30)) == "red"


def _parts(*specs) -> list[dict]:
    return [{"name": nm, "role": role, "color": color, "bbox": {"min": lo, "max": hi}} for nm, role, color, lo, hi in specs]


def test_the_legend_names_each_part_its_colour_and_where_it_sits():
    st = DesignState(pack="enclosure", source="const E = lib.elec; return E.parts(enc, { layout: p.layout })", params={"layout": "print"})
    st.last_build = {"params": {"layout": "print"}, "parts": _parts(
        ("base", "model", None, [0, 0, 0], [56, 65.7, 8.9]), ("lid", "model", "#e8965a", [62, 0, 0], [118, 65.7, 2.6]),
        ("cut", "negative", None, [0, 0, 0], [5, 5, 5]))}
    text = critic.legend(st)
    assert text.splitlines()[:3] == ["Parts in the renders (name: colour, role, size):",
                                     "- base: light grey #d6d8de, printed part, 56 x 65.7 x 8.9 mm",
                                     "- lid: orange #e8965a, brown on shaded faces, printed part, 56 x 65.7 x 2.6 mm"]
    assert "left to right: base, lid; BOTTOM and ISO BACK show them mirrored" in text
    assert "The lid is printed upside down" in text and "cut" not in text and "red tint" in text
    # assembled with the board ghost: they overlap, so no left-to-right claim
    st.last_build = {"params": {"layout": "assembled"}, "parts": _parts(
        ("base", "model", None, [0, 0, 0], [56, 65.7, 8.9]), ("lid", "model", "#e8965a", [0, 0, 7], [56, 65.7, 9.5]),
        ("board", "reference", "#4f8df7", [3, 3, 4], [24, 54, 5.6]))}
    text = critic.legend(st)
    assert "- board: translucent blue reference, shown for context and never printed, 21 x 51 x 1.6 mm" in text
    assert "left to right" not in text and "Layout: assembled, the parts sit together as in use, the lid on the base." in text
    # one printed part needs no legend
    st.last_build = {"params": {}, "parts": _parts(("body", "model", None, [0, 0, 0], [10, 10, 10]))}
    assert critic.legend(st) == ""


async def test_the_reviewer_gets_the_legend_next_to_the_renders(fresh_db, monkeypatch):
    seen = []

    class Meta:
        def model_for(self, role, default):
            return default

        async def json(self, meter, *, content, **kw):
            seen.append(content)
            return {"verdict": "pass", "match_score": 9, "issues": []}

    monkeypatch.setattr(critic, "meta", lambda: Meta())
    st = DesignState(pack="enclosure", source="lib.elec", version=1, params={"layout": "print"})
    st.last_build = {"params": {"layout": "print"}, "checks": {"stats": {"size": [118, 65.7, 8.9]}}, "parts": _parts(
        ("base", "model", None, [0, 0, 0], [56, 65.7, 8.9]), ("lid", "model", "#e8965a", [62, 0, 0], [118, 65.7, 2.6]))}
    st.last_render = storage.save_bytes("p_case", "renders", "v1.png", _png())
    await critic.review(FakeCtx(), st)
    text = next(p["text"] for p in seen[0] if p["type"] == "input_text" and p["text"].startswith("Renders of the model"))
    assert "- lid: orange #e8965a" in text and "left to right: base, lid" in text


@pytest.fixture
async def real_geom():
    old = geommod._pool
    geommod._pool = GeomPool(1)
    yield geommod._pool
    await geommod._pool.close()
    geommod._pool = old


def _tile(png: str, col: int, row: int, size: int) -> np.ndarray:
    """One view of the sheet without its label (top) and its red 10 mm scale bar (bottom)."""
    img = np.array(Image.open(io.BytesIO(base64.b64decode(png))).convert("RGB")).astype(int)
    return img[row * size + 24:(row + 1) * size - 22, col * size:(col + 1) * size]


def _warm(px: np.ndarray) -> float:
    """How far the drawn pixels lean to orange (red over blue), background left out."""
    drawn = px[np.abs(px - [246, 246, 243]).sum(axis=2) > 30]
    return float((drawn[:, 0] - drawn[:, 2]).mean())


async def test_the_legend_of_the_case_example_agrees_with_its_render(real_geom):
    inputs = {"boards": {"board": PICO}}
    built = await real_geom.build(et.EXAMPLE, {}, analyze="fast", inputs=inputs)
    st = DesignState(pack="enclosure", source=et.EXAMPLE, version=1, params=built["params"], last_build=built)
    text = critic.legend(st)
    assert "- base: light grey #d6d8de, printed part" in text and "- lid: orange #e8965a, brown on shaded faces, printed part" in text
    assert "left to right: base, lid" in text and "The lid is printed upside down" in text
    # the sheet the reviewer sees (as commit_build renders it): TOP has the grey base left of the orange lid, BOTTOM mirrors them
    size = 200
    sheet = await real_geom.render(et.EXAMPLE, built["params"], view="sheet", tile=size, heat=True, inputs=inputs)
    top, bottom = _tile(sheet["png"], 1, 1, size), _tile(sheet["png"], 2, 1, size)
    half = size // 2
    assert abs(_warm(top[:, :half])) < 25 < 60 < _warm(top[:, half:])
    assert abs(_warm(bottom[:, half:])) < 25 < 60 < _warm(bottom[:, :half])
