"""Structured intake of a spare-part request (text, voice transcript, photos incl. the appliance rating plate).

Verified on 2026-10-30 (intake_probe.py, 7 calls): Muse Spark 1.3 extracted brand/model/quantity/material from a
messy Russian voice-style request, read a rating plate exactly (SMS46GI01E/09) and refused a gas-stove knob with
a correct reason. Muse Spark Open got the same easy cases right but on the gas-knob case returned one unparsable
answer and one wrong object (refuse=false, invented appliance). So the refuse decision is Spark 1.3's alone; Spark
Open (role 'classify') gives a short second opinion and a catalog title, and when it calls a part safety-critical
that Spark accepted, the order waits for the farm operator instead of going to the designer.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from iamodelize3d import quotas, storage
from iamodelize3d.config import settings
from iamodelize3d.llm.client import CostMeter, meta

from .intake_schema import CLASSIFY_SCHEMA, SCHEMA

log = logging.getLogger("iamodelize3d.shop")

SYSTEM = """You are the intake desk of a spare-parts service that 3D-prints replacement plastic parts for appliances and
household items. Read the request (text, a voice-note transcript, or photos) and fill the schema.
Rules:
- Copy brand, model and part numbers exactly as written or as printed on a rating plate; never invent them. Unknown -> "".
- part.name_en: a short English name a segmenter can find in a photo (e.g. "dishwasher lower basket wheel").
- part.name_fr: the same short name in French, for French-speaking customers (e.g. "roulette du panier inférieur de lave-vaisselle").
- refuse=true only for parts where a print failure can hurt someone: gas, pressure vessels, mains-voltage insulation or
  enclosures that carry live parts, brakes, steering, child seats, helmets, medical devices, food contact above 70 C.
  Otherwise refuse=false and explain constraints in notes.
- ip_flags: list brand logos, trademarks or decorative designs that must NOT be reproduced (functional shape is fine).
- questions: at most 2 short follow-up questions in the customer's language, only if the answer changes the part. Never ask
  how many pieces are needed or what it costs: the customer sets the quantity on the order.
- material: PLA for dry indoor parts below 50 C, PETG for wet/dishwasher/fridge, ASA for outdoor/UV or 60-90 C, TPU for flexible.
"""

CLASSIFY_SYSTEM = """You sort requests that reach a farm of 3D printers making replacement plastic parts. Read the request
(text, a voice-note transcript, photos) and answer briefly:
- category: what the part belongs to.
- safety_critical: true when a printed copy that cracks, melts or slips could hurt someone: gas controls, pressure vessels,
  mains-voltage insulation or enclosures around live parts, brakes, steering, child seats, helmets, medical devices,
  food contact above 70 C. A mechanical part of an appliance (a wheel, clip, hinge, knob of a washing machine) is not.
- why: one sentence.
- title_en, title_ru, title_fr: a short catalog title for the part itself in English, in Russian and in French, without any
  brand name (e.g. "Dishwasher lower basket wheel" / "Колёсико нижней корзины посудомойки" / "Roulette du panier inférieur
  de lave-vaisselle").
"""

PHOTO_ROLE = {"part": "the part (on an A4 sheet when the customer followed the hint)", "plate": "the appliance rating plate"}

# a question about how many pieces, in English or Russian wording: the order carries the quantity (the form's, else
# what the request says, else 1), so neither the intake desk nor the designer asks it ('Сколько колёс нужно напечатать?').
# 'you' alone is not enough: 'How many screw holes do you see?' is a question about the part
_QUANTITY_ASK = re.compile(
    r"\bquantit|\bhow many\b[^?]*\b(pieces|pcs|copies|units|spares|replacements|sets|of them|in total|to (print|order|make)"
    r"|(do|would|will|shall|should) (you|we) (need|want|like|order|print|make)|you (need|want))\b"
    r"|\bnumber of (pieces|pcs|copies|units|items|sets|replacements)\b"
    r"|\b(one|a single) \w+ or (several|more|multiple)\b"
    r"|\bсколько\b[^?]*(штук|\bшт\b|экземпляр|копи[йияю]|комплект|напечатать|печатать|заказать|заказыва|изготовить"
    r"|\b(вам|вы)\s+(нужн|надо|хотите|закаж))"
    r"|\bколичеств\w*\b(?!\s+(зуб|спиц|отверст|винт|р[её]бер|паз|лопаст|витк|шлиц|защ[её]л))|\bшт(ук|\.)"
    r"|\b(одн[аоуиы]\w*|один) \w+ или несколько\b", re.I)


def asks_quantity(question: str) -> bool:
    return bool(_QUANTITY_ASK.search(question or ""))


def _content(text: str, photos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "input_text", "text": text or "(no text; see the photos)"}]
    for i, a in enumerate(photos[:4], 1):
        content.append({"type": "input_text", "text": f"Photo {i}: {PHOTO_ROLE.get(a.get('role', 'part'), 'a photo')}"})
        content.append({"type": "input_image", "image_url": storage.data_url(a["path"], 1600)})
    return content


def combine(spark: dict[str, Any] | BaseException | None, second: dict[str, Any] | BaseException | None, *,
            spark_model: str = "", open_model: str | None = None) -> dict[str, Any]:
    """One intake from Spark 1.3's answer and the open model's classification (pure, so fixtures can test it).

    Spark alone decides `refuse`. `review` is set when the order should wait for the operator: Spark gave no usable
    answer (the safety gate did not run), or the open model calls safety-critical what Spark accepted."""
    usable = isinstance(spark, dict) and isinstance(spark.get("refuse"), bool)
    out: dict[str, Any] = dict(spark) if usable else {  # type: ignore[arg-type]
        "refuse": False, "error": f"{type(spark).__name__}: {spark}"[:300] if isinstance(spark, BaseException) else "no usable intake answer"}
    out["model"] = spark_model
    part = out.get("part") if isinstance(out.get("part"), dict) else {}
    if part:
        part["quantity"] = max(1, min(200, int(part.get("quantity") or 1)))
    if out.get("material") not in SCHEMA["properties"]["material"]["enum"]:
        out["material"] = "PLA"
    if isinstance(out.get("questions"), list):
        out["questions"] = [q for q in out["questions"] if isinstance(q, str) and q.strip() and not asks_quantity(q)]
    cls = None
    if isinstance(second, dict) and isinstance(second.get("safety_critical"), bool):
        cls = {**second, "model": open_model}
    elif second is not None:
        cls = {"error": (f"{type(second).__name__}: {second}" if isinstance(second, BaseException) else "no usable answer")[:300], "model": open_model}
    out["classify"] = cls
    review = None
    if not usable:
        review = {"code": "intake_failed", "why": "the intake model gave no usable answer, so the safety check did not run"}
    elif not out["refuse"] and cls and cls.get("safety_critical"):
        review = {"code": "safety_disagreement", "why": cls.get("why") or "the second model calls this part safety-critical"}
    out["review"] = review
    return out


async def extract(user: dict[str, Any], text: str, photos: list[dict[str, Any]]) -> dict[str, Any]:
    """`photos`: asset rows with a 'role' key ('part' or 'plate'). Two calls at once: Spark 1.3 fills the intake,
    the open model (when one serves 'classify') gives its second opinion."""
    choice = await quotas.choose_models(user)
    spark = choice.fast
    second = meta().model_for("classify", spark)
    await quotas.check_light(user, 0.01)
    meter = CostMeter(budget_usd=0.05)
    content = _content(text, photos)

    async def classify() -> dict[str, Any] | None:
        if second == spark:
            return None  # no open model configured: asking Spark twice adds nothing
        return await meta().json(meter, model=second, system=CLASSIFY_SYSTEM, content=content, schema=CLASSIFY_SCHEMA, name="intake_classify",
                                 max_output_tokens=8000, purpose="classify", fallback=False)

    try:
        a, b = await asyncio.gather(
            meta().json(meter, model=spark, system=SYSTEM, content=content, schema=SCHEMA, name="intake", effort="low",
                        max_output_tokens=4000, purpose="intake"),
            classify(), return_exceptions=True)
    finally:
        await quotas.settle(user["id"], meter.usd, is_job=False)
    for r in (a, b):
        if isinstance(r, BaseException):
            log.warning("intake call failed: %s: %s", type(r).__name__, r)
    out = combine(a, b, spark_model=spark, open_model=None if second == spark else second)
    out["cost_usd"] = round(meter.usd, 5)
    return out


UNNAMED = ("Spare part", "Запчасть")  # a part nothing has named yet (no words, no intake read), in English and in Russian


def title_for(intake: dict[str, Any], fallback: str = UNNAMED[0]) -> str:
    """The person-facing title: the part as the customer named it, and the appliance it fits."""
    part, app = intake.get("part") or {}, intake.get("appliance") or {}
    name = (part.get("name_user") or part.get("name_en") or fallback).strip()
    fits = " ".join(x for x in (app.get("brand"), app.get("model")) if x).strip()
    return (f"{name[:1].upper()}{name[1:]} · {fits}" if fits else f"{name[:1].upper()}{name[1:]}")[:80]


def titles(intake: dict[str, Any], fallback: str) -> tuple[str, str]:
    """The title in English and in Russian, so the UI follows its own language: the customer's own words in their
    language, else the open model's catalog title (classify), else Spark's English name, and the appliance it fits.
    When the two models disagree about the part, Spark's reading names it. `fallback` where nothing is known (the
    unnamed 'Spare part' in either language is said in both: a text request whose intake failed reads 'Запчасть')."""
    part, app = intake.get("part") or {}, intake.get("appliance") or {}
    cls = intake.get("classify") or {}
    if cls.get("error") or (intake.get("review") or {}).get("code") == "safety_disagreement":
        cls = {}
    lang = str(intake.get("language") or "")[:2].lower()
    own = part.get("name_user") or ""
    fits = " ".join(x for x in (app.get("brand"), app.get("model")) if x).strip()
    fallbacks = UNNAMED if fallback in UNNAMED else (fallback, fallback)

    def one(name: str, default: str) -> str:
        name = (name or "").strip()
        if not name:
            return default
        return (f"{name[:1].upper()}{name[1:]} · {fits}" if fits else f"{name[:1].upper()}{name[1:]}")[:80]

    return (one((own if lang == "en" else "") or cls.get("title_en") or part.get("name_en") or "", fallbacks[0]),
            one((own if lang == "ru" else "") or cls.get("title_ru") or "", fallbacks[1]))


UNNAMED_FR = "Pièce détachée"  # a part nothing has named yet, in French


def title_fr(intake: dict[str, Any], fallback: str = UNNAMED_FR) -> str:
    """The title in French (the G1 front's language): the customer's own words when they wrote French, else the open
    model's French catalog title, else the intake's French name, else `fallback`; with the appliance it fits."""
    part, app = intake.get("part") or {}, intake.get("appliance") or {}
    cls = intake.get("classify") or {}
    if cls.get("error") or (intake.get("review") or {}).get("code") == "safety_disagreement":
        cls = {}
    lang = str(intake.get("language") or "")[:2].lower()
    name = ((part.get("name_user") if lang == "fr" else "") or cls.get("title_fr") or part.get("name_fr") or "").strip()
    if not name:
        return fallback[:80]
    fits = " ".join(x for x in (app.get("brand"), app.get("model")) if x).strip()
    return (f"{name[:1].upper()}{name[1:]} · {fits}" if fits else f"{name[:1].upper()}{name[1:]}")[:80]


def design_brief(intake: dict[str, Any], request_text: str, ref: str, *, quantity: int | None = None, material: str | None = None) -> str:
    """What the designer agent gets (English): the part, what it fits, how it lives, what not to copy. `quantity` and
    `material` are the order's (the form's, else what the intake read): the quantity is the order's to set, never a
    design question."""
    part, app, env = intake.get("part") or {}, intake.get("appliance") or {}, intake.get("environment") or {}
    lines = [f"Spare part order {ref}: design a printable replacement part from the photos."]
    name = part.get("name_en") or "the broken part in the photo"
    lines.append(f"The part: {name}" + (f" (the customer calls it '{part['name_user']}')" if part.get("name_user") else "") + ".")
    fits = " ".join(x for x in (app.get("brand"), app.get("model")) if x)
    if fits:
        lines.append(f"It fits a {app.get('kind') or 'appliance'} {fits}. This is a compatible part: never put the brand name, a logo "
                     "or any trademark on it.")
    if part.get("part_number"):
        lines.append(f"OEM part number (for reference only, not to be printed): {part['part_number']}.")
    flags = [f for f in intake.get("ip_flags") or [] if f]
    if flags:
        lines.append("Do not reproduce: " + "; ".join(flags) + ". The functional shape is fine.")
    if part.get("failure"):
        lines.append(f"What failed: {part['failure']}. Make that spot stronger if the fit allows it.")
    mat = str(material or intake.get("material") or "PLA").upper()
    life = [f"up to {env['max_temp_c']:g} C" if isinstance(env.get("max_temp_c"), (int, float)) else "",
            "wet" if env.get("wet") else "", f"load: {env['load']}" if env.get("load") else ""]
    said = f"Material: {mat}" + (f" ({', '.join(x for x in life if x)})" if any(life) else "")
    if intake.get("material") and intake["material"] != mat and not intake.get("error"):
        said += f", the customer's choice (the intake desk would pick {intake['material']})"
    n = max(1, int(quantity or part.get("quantity") or 1))
    lines.append(f"{said}. Quantity: {n}, set on the order: never ask the customer how many they need.")
    questions = [q for q in intake.get("questions") or [] if q and not asks_quantity(q)]
    if questions:
        lines.append("The intake desk could not tell: " + " / ".join(questions) + " If the photos do not answer it, ask the customer.")
    if settings().provider["sam"]:
        lines.append("Measure the part from the photo on the A4 sheet, keep every mating dimension, and check that it prints.")
    else:
        # another provider than Meta: no SAM, so no measure/fit_to_photo tools (agent/tools.tools_for)
        lines.append("No measuring tool runs on this server: read the part against the A4 sheet in the photo (210 x 297 mm), "
                     "ask the customer for any mating dimension you cannot read with confidence, and check that it prints.")
    # the form's own 'Quantity: N' line is said above as the order's (an operator's 'Let through' may have changed it)
    request_text = "\n".join(x for x in request_text.splitlines() if not x.startswith("Quantity: "))
    if request_text.strip():
        lines.append("The customer's request:\n" + request_text.strip()[:1500])
    return "\n".join(lines)


FORM_LINES = ("Appliance: ", "Part number: ", "Quantity: ", "Voice note: ")  # what order_part adds to the request text


def customer_words(req: dict[str, Any]) -> str:
    """What the customer typed and said themselves: the form's text, the appliance and part number fields, the voice
    note's transcript, without the English labels the request text gives the models."""
    if "words" in req:
        typed = str(req.get("words") or "")
    else:  # an order from before the words were kept apart: its text without the lines the form added
        typed = "\n".join(x for x in str(req.get("text") or "").splitlines() if not x.startswith(FORM_LINES))
    fits = " · ".join(x for x in (str(req.get("appliance") or "").strip(), str(req.get("part_number") or "").strip()) if x)
    return "\n".join(x for x in (typed.strip(), fits, str(req.get("transcript") or "").strip()) if x)[:2000]


def shown_line(intake: dict[str, Any], ref: str) -> str:
    """The first message of the order's design run as the customer sees it (SendMessage.shown): their own words, or,
    with none (photos alone, a catalog part, a ready model), a short line in their language: 'Заказ IM-1004: Ручка'."""
    words = customer_words(intake.get("request") or {})
    if words:
        return words
    en, ru = titles(intake, UNNAMED[0])
    return f"Заказ {ref}: {ru}" if str(intake.get("language") or "").lower().startswith("ru") else f"Order {ref}: {en}"
