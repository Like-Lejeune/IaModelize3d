"""Human-readable narration of agent steps for the timeline and Telegram.

Raw tool JSON stays available as `summary` for the details expander; these titles are
what people read: "Measured the bracket: 70.5 × 45.4 mm ±0.6".
"""
from __future__ import annotations

import re
from typing import Any

KIND = {
    "write_program": "build", "edit_program": "edit", "set_params": "params", "inspect_model": "inspect", "look": "look",
    "measure": "measure", "dimensions": "standard", "remember_interface": "memory", "ask_user": "ask", "fit_to_photo": "fit",
    "propose_probe": "probe", "concept_images": "concepts", "load_terrain": "terrain", "compare_print": "compare", "finish": "finish",
    "mesh_write": "build", "mesh_edit": "edit",
    # electronics: a board from a photo or the dataset, the case checked against it, the PCB and its fab files
    "scan_board": "measure", "use_board": "standard", "check_enclosure": "inspect",
    "write_circuit": "build", "check_pcb": "inspect", "export_fab": "export", "make_enclosure": "build",
}

# which stage of the job a tool belongs to
STAGE = {
    "build": "design", "edit": "design", "params": "design", "terrain": "measure", "concepts": "design",
    "measure": "measure", "standard": "measure", "memory": "understand", "ask": "understand",
    "inspect": "check", "look": "check", "fit": "check", "probe": "check",
    "compare": "check", "finish": "review", "export": "design",
}

STAGE_LABEL = {
    "understand": "Understanding the request",
    "measure": "Measuring and looking things up",
    "design": "Designing",
    "check": "Checking against reality",
    "review": "Independent review",
    "done": "Ready",
}

STAGE_LABEL_RU = {
    "understand": "Разбираюсь в задаче",
    "measure": "Измеряю и ищу размеры",
    "design": "Проектирую",
    "check": "Сверяю с реальностью",
    "review": "Независимая проверка",
    "done": "Готово",
}

# Russian phrasing for the timeline; keys are English templates' first words.
RU = {
    "Writing the model": "Пишу модель", "Changing": "Меняю", "Adjusting": "Подстраиваю", "Measuring my own model": "Измеряю свою модель",
    "Comparing with the photo": "Сравниваю с фото", "Rendering views": "Рендерю виды", "Taking a closer look at the photo": "Смотрю на фото внимательнее",
    "Reading measurements from the photos": "Беру замеры с фото", "Measuring": "Измеряю", "on the photo": "на фото", "Reading the caliper": "Читаю штангенциркуль",
    "Checking standards": "Смотрю стандарты", "Searching official dimensions": "Ищу официальные размеры", "Checking what I remember about your setup": "Вспоминаю ваши размеры",
    "Remembering": "Запоминаю", "for next time": "на будущее", "Asking you a question": "Задаю вопрос", "Fitting": "Подгоняю",
    "to the photo silhouette": "под силуэт на фото", "Preparing a test print for": "Готовлю пробник для", "Sketching concepts": "Рисую концепты",
    "Loading real elevation data": "Загружаю реальные высоты", "Saving a reusable module": "Сохраняю модуль", "Comparing your print with the target": "Сравниваю отпечаток с целью",
    "Final check before handing over": "Финальная проверка перед выдачей", "first version": "первая версия", "details": "детали", "parameters": "параметры",
    "Version": "Версия", "printable": "печатается", "problems to fix": "проблем", "notes": "замечаний",
    "silhouette match": "совпадение силуэта", "Measured": "Измерено", "holes": "отверстий", "cutouts": "вырезов", "Found": "Найдено",
    "no reference in the photo, sizes in pixels only": "нет эталона на фото, размеры только в пикселях", "Caliper reads": "Штангенциркуль показывает",
    "Couldn't read the caliper": "Не удалось прочитать штангенциркуль", "Dimensions found": "Найдено размеров", "(from memory)": "(из памяти)",
    "Standard values found": "Найдено в стандартах", "Not in the standards tables": "В таблицах стандартов нет",
    "Measured the model": "Модель измерена", "Measurements available": "Доступно замеров", "You answered": "Ваш ответ",
    "No answer — continuing with a stated assumption": "Ответа нет — продолжаю с явным допущением", "Test print ready": "Пробник готов", "variants": "вариантов",
    "Concepts ready": "Концептов готово", "Elevation loaded": "Рельеф загружен", "relief over": "перепад на", "Print deviates": "Отпечаток отклоняется на",
    "on average": "в среднем", "Approved": "Принято", "Not yet": "Пока нет", "the reviewer found major problems": "ревьюер нашёл серьёзные замечания",
    "Handed over; the reviewer still has notes": "Сдано; у ревьюера остались замечания",
    "Handed over without a review: the reviewer did not answer": "Сдано без проверки: ревьюер не ответил",
    "printability errors remain": "остались ошибки печатаемости", "needs fixes": "нужны правки", "Overlay ready": "Наложение готово", "Views rendered": "Виды готовы",
    "Download 3MF": "Скачать 3MF", "Prepare print settings": "Подготовить настройки печати", "Print a 5-minute test piece": "Напечатать 5-минутный пробник",
    "Order a print": "Заказать печать", "Share as a recipe": "Поделиться рецептом",
    "Sculpting the model": "Леплю модель", "Sculpting": "Леплю", "first form": "первая форма",
    "Comparing the model with the photo": "Сравниваю модель с фото", "Looking at the model from all sides": "Смотрю на модель со всех сторон",
    "Looking up dimensions": "Ищу размеры", "Silhouette match": "Совпадение силуэта", "Nothing found": "Ничего не найдено",
    "Finding": "Ищу", "Measuring the photos": "Измеряю фото", "I can't help with this one": "С этим я не помогу", " mm": " мм", " min": " мин", " km": " км", " m relief": " м перепад", "Saved to your setup": "Сохранено в ваших размерах", "Problem": "Проблема", "Done": "Готово",
    "Internal step failed, trying another way": "Внутренний шаг не удался, пробую иначе", "Fixing the program": "Исправляю программу",
    "The model took too long to compute, simplifying": "Модель считалась слишком долго, упрощаю", "Edit didn't apply, retrying": "Правка не применилась, повторяю",
    "The answer was cut off, retrying shorter": "Ответ оборвался, повторяю короче", "No model yet.": "Модели пока нет.",
    "I ran out of steps before finishing; the latest version is in the viewer.": "Шаги закончились раньше, чем я закончил; последняя версия — в просмотре.",
    # electronics: the board, the case checked against it, the PCB
    "Scanning the board on the photo": "Сканирую плату на фото", "Taking the board from the dataset": "Беру плату из базы",
    "Attaching the board from its own numbers": "Подключаю плату по её размерам", "Checking the case against the board": "Сверяю корпус с платой",
    "Board read": "Плата распознана", "Board measured": "Плата измерена", "Board from the dataset": "Плата из базы",
    "Board from its own numbers": "Плата по её размерам", "scale from its holes": "масштаб по её отверстиям",
    "scale from the A4 sheet": "масштаб по листу A4", "scale from the bank card": "масштаб по банковской карте",
    "scale from its outline": "масштаб по контуру платы", "no scale reference": "без эталона масштаба", "; case updated: v": "; корпус обновлён: v",
    "The board does not fit yet": "Плата пока не влезает", " does not fit yet": " пока не влезает", "The board fits": "Плата влезает",
    " fits — ": " влезает — ", "does not fit the board yet": "плата пока не влезает",
    "fits the board": "плата влезает", "the case check did not run": "проверка корпуса не запустилась",
    "all buttons reach": "все кнопки нажимаются", " only with the lid off": " нажимается только без крышки", " plug blocked": " перекрыт",
    "the board hits the case": "плата задевает корпус", " touches a wall": " касается стенки", "the board is not held": "плата не закреплена",
    " button out of reach": " не нажимается", " window blocked": " закрыт пластиком", "the lid does not fit": "крышка не садится",
    "snaps bend": "защёлки гнутся на", "snaps ": "защёлки ", "metal in an antenna keep-out": "металл в зоне антенны",
    "Writing the circuit": "Пишу схему", "Changing the circuit": "Меняю схему", "Fixing the circuit": "Исправляю схему",
    "Routing took too long, simplifying the board": "Трассировка заняла слишком много времени, упрощаю плату",
    "Checking the board": "Проверяю плату", "Checking PCB v": "Проверяю плату v", "Exporting Gerber, BOM and CPL": "Готовлю Gerber, BOM и CPL",
    "Making the case for the board": "Делаю корпус для платы", "Making the case for PCB v": "Делаю корпус для платы v",
    " and a printable mock-up of it": " и макет платы для печати", "Looking at the routed board from the top": "Смотрю на разведённую плату сверху",
    "Looking at the board from below": "Смотрю на плату снизу", "Reading the schematic": "Читаю схему",
    " from the top": " сверху", " from below": " снизу", " schematic": ": схема",
    "Fab files for PCB v": "Файлы для фабрики, плата v", "No fab files for PCB v": "Нет файлов для фабрики у платы v",
    " yet: it still has DRC errors": ": остались ошибки DRC", " yet: the export failed": ": экспорт не удался",
    "no intent stated": "замысел не указан", "intent not met: ": "замысел не выполнен: ", "intent met": "замысел выполнен",
    "fab files ready": "файлы для фабрики готовы", "no fab files": "файлов для фабрики нет", " for PCB v": " для платы v", "PCB v": "Плата v",
    "Case v": "Корпус v", " — print plate ": " — на столе ", "The case did not build": "Корпус не собрался",
    "the board is not ready": "плата ещё не готова", "the case check found errors": "проверка корпуса нашла ошибки",
}

# Russian counts decline their noun ("23 traces" -> "23 трассы"), so these go by pattern before the plain phrases
RU_COUNTED = [(re.compile(rf"\b(\d+) {en}\b"), forms) for en, forms in (
    ("DRC errors?", ("ошибка DRC", "ошибки DRC", "ошибок DRC")), ("traces?", ("трасса", "трассы", "трасс")),
    ("vias?", ("переход", "перехода", "переходов")), ("layers?", ("слой", "слоя", "слоёв")), ("lines?", ("строка", "строки", "строк")),
)]


def _ru_form(n: int, forms: tuple[str, str, str]) -> str:
    m10, m100 = n % 10, n % 100
    return forms[0] if m10 == 1 and m100 != 11 else forms[1] if 2 <= m10 <= 4 and not 12 <= m100 <= 14 else forms[2]


def localize(text: str, language: str | None) -> str:
    if not language or not language.lower().startswith(("ru", "kk")):
        return text
    for rx, forms in RU_COUNTED:
        text = rx.sub(lambda m, forms=forms: f"{m[1]} {_ru_form(int(m[1]), forms)}", text)
    text = re.sub(r"\+(\d+) more\b", r"ещё \1", text)
    for en in sorted(RU, key=len, reverse=True):
        text = text.replace(en, RU[en])
    return text


def _ru(language: str | None) -> bool:
    return bool(language) and language.lower().startswith(("ru", "kk"))  # type: ignore[union-attr]


def stage_label(stage: str, language: str | None) -> str:
    if _ru(language):
        return STAGE_LABEL_RU[stage]
    return STAGE_LABEL[stage]


def _roots() -> list[str]:
    from ..config import REPO_DIR, settings

    out = set()
    for p in (settings().data_dir, REPO_DIR):
        # as written, inside JSON (escaped backslashes) and with forward slashes
        out |= {str(p), str(p).replace("\\", "\\\\"), p.as_posix()}
    return sorted(out, key=len, reverse=True)


def scrub(text: str) -> str:
    """No server paths in what people read: '.../formwright/data/files/p_1/a.mp4' -> 'files/p_1/a.mp4'."""
    for root in _roots():
        text = re.sub(re.escape(root) + r"[\\/]*", "", text, flags=re.IGNORECASE)
    return text


# Endings of a run the agent did not finish itself: why it stopped, then where the person stands.
HANDOVER = {
    "budget": ("Stopped at the spending cap.", "Остановился на лимите расходов."),
    "failed": ("The model service stopped answering, so I stopped here.", "Сервис модели перестал отвечать, поэтому я остановился."),
    "engine": ("The geometry engine failed, so I stopped here.", "Геометрический движок дал сбой, поэтому я остановился."),
    "time": ("Time is up for this run.", "Время на этот запуск вышло."),
    "turns": ("I ran out of steps before the final review.", "Шаги закончились до финальной проверки."),
    "unfinished": ("I stopped before the final review.", "Я остановился до финальной проверки."),
}


def handover(reason: str, version: int, printable: bool, reviewed: bool, language: str | None) -> str:
    """'Stopped at the spending cap. Version 7 is the latest: printable, not reviewed. ...' in the person's language."""
    en, ru = HANDOVER.get(reason, HANDOVER["turns"])
    if _ru(language):
        return (f"{ru} Последняя версия — {version}: {'печатается' if printable else 'есть проблемы печатаемости'}, "
                f"{'проверена' if reviewed else 'не проверена'}. Напишите сообщение, чтобы продолжить.")
    return (f"{en} Version {version} is the latest: {'printable' if printable else 'it still has printability problems'}, "
            f"{'reviewed' if reviewed else 'not reviewed'}. Send a message to keep improving it.")


def review_of(critic: dict[str, Any] | None, version: int) -> str | None:
    """How the reviewer left the version a finish handed over: 'notes' when its verdict is still revise (the review only
    reports from the third finish on, minor issues never block), 'none' when no reviewer answered; None when it passed
    or did not look at this version (a board without a case has no review)."""
    c = critic or {}
    if c.get("version") != version:
        return None
    if c.get("reviewer") == "unavailable" or c.get("note") == "reviewer unavailable":
        return "none"
    return "notes" if c.get("verdict") == "revise" else None


def review_notes(critic: dict[str, Any] | None, version: int, language: str | None) -> str:
    """The line after the agent's own summary when the reviewer did not approve what was handed over: the summary is
    written before the review, so it cannot say so itself. Empty when the reviewer passed this version."""
    state = review_of(critic, version)
    if state == "none":
        return (f"Независимый ревьюер не ответил, поэтому версия {version} не проверена." if _ru(language)
                else f"The independent reviewer did not answer, so version {version} is not reviewed.")
    if state != "notes":
        return ""
    c = critic or {}
    issues = sorted(c.get("issues") or [], key=lambda i: i.get("severity") != "major")
    notes = "; ".join(_short(str(i.get("text_user") or i.get("text") or ""), 200).rstrip(".") for i in issues[:2] if i.get("text_user") or i.get("text"))
    score = c.get("match_score")
    score = f" ({_mm(score)}/10)" if isinstance(score, (int, float)) else ""
    if _ru(language):
        return f"У независимого ревьюера остались замечания к версии {version}{score}" + (f": {notes}." if notes else ".")
    return f"The independent reviewer still has notes on version {version}{score}" + (f": {notes}." if notes else ".")


def sliced(stats: dict[str, Any], changed: int, language: str | None) -> str:
    m, g, layers = stats.get("minutes", 0), stats.get("grams", 0), stats.get("layers", 0)
    if _ru(language):
        return (f"Нарезано: {m:.0f} мин, {g:.1f} г, слоёв: {layers}. Изменено настроек относительно профиля принтера: {changed}, "
                "у каждой есть причина.")
    return f"Sliced: {m:.0f} min, {g:.1f} g, {layers} layers. {changed} setting(s) changed from the printer's default profile, each with a reason."


def concept_title(language: str | None, iou: float | None = None) -> str:
    """The chain a picked concept goes through: Muse Image drew it, SAM cut it out, the model is matched to it."""
    if _ru(language):
        return "Muse Image нарисовала → SAM 3.1 вырезала" + (f" → силуэт {iou:.0%}" if iou is not None else "")
    return "Muse Image drew it → SAM 3.1 cut it out" + (f" → silhouette {iou:.0%}" if iou is not None else "")


# The page a sign-in link opens (app.magic_login): {name} is the account's name, empty when it has none.
LOGIN = {
    "lang": ("en", "ru"),  # the page's lang attribute
    "title": ("Sign in to Formwright", "Вход в Formwright"),
    "as": ("This link signs this browser in as {name}. It works once.", "Ссылка выполнит вход в этом браузере как {name}. Она одноразовая."),
    "plain": ("This link signs this browser in. It works once.", "Ссылка выполнит вход в этом браузере. Она одноразовая."),
    "go": ("Continue", "Продолжить"),
    "gone": ("This sign-in link has expired or was already used. Ask for a new one.",
             "Ссылка для входа устарела или уже использована. Попросите новую."),
    "home": ("Open Formwright", "Открыть Formwright"),
}


def login_text(key: str, language: str | None, **kw: str) -> str:
    en, ru = LOGIN[key]
    return (ru if _ru(language) else en).format(**kw)


def _mm(v: Any) -> str:
    try:
        return f"{float(v):.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(v)


def _size(size: list | None) -> str:
    return " × ".join(_mm(v) for v in (size or [])) + " mm" if size else ""


def _pcb_v(v: Any) -> str:
    """' for PCB v3' when a version was named; the tools default to the latest."""
    return f" for PCB v{v}" if isinstance(v, int) or (isinstance(v, str) and v.isdigit()) else ""


def _own_board(a: dict[str, Any]) -> bool:
    """use_board with a whole board JSON rather than a dataset id: the tool takes spec over board_id (a spec may come as a JSON string)."""
    spec = a.get("spec")
    return bool(spec) and (isinstance(spec, dict) or not a.get("board_id"))


def _elec_call(name: str, a: dict[str, Any]) -> str:
    if name == "scan_board":
        return "Scanning the board on the photo" + (f": {a['hint']}" if a.get("hint") else "")
    if name == "use_board":
        if _own_board(a):
            spec = a["spec"] if isinstance(a["spec"], dict) else {}
            return "Attaching the board from its own numbers" + (f": {spec['name']}" if isinstance(spec.get("name"), str) and spec["name"] else "")
        return f"Taking the board from the dataset: {a.get('board_id', '')}"
    if name == "check_enclosure":
        return "Checking the case against the board"
    if name == "write_circuit":
        verb = "Changing the circuit" if a.get("edits") and not a.get("source") else "Writing the circuit"
        return f"{verb}: {a.get('summary') or ('details' if verb.startswith('Changing') else 'first version')}"
    if name == "check_pcb":
        return f"Checking PCB v{a['version']}" if _pcb_v(a.get("version")) else "Checking the board"
    if name == "export_fab":
        return "Exporting Gerber, BOM and CPL" + _pcb_v(a.get("version"))
    # make_enclosure: with_mockup defaults to true
    v = _pcb_v(a.get("version"))
    return (f"Making the case{v}" if v else "Making the case for the board") + (
        " and a printable mock-up of it" if a.get("with_mockup") is not False else "")


ELEC_TOOLS = ("scan_board", "use_board", "check_enclosure", "write_circuit", "check_pcb", "export_fab", "make_enclosure")
PCB_LOOKS = {"pcb": "Looking at the routed board from the top", "pcb_bottom": "Looking at the board from below", "schematic": "Reading the schematic"}


def call_title(name: str, args: dict[str, Any]) -> str:
    a = args or {}
    if name in ELEC_TOOLS:
        return _elec_call(name, a)
    return {
        "write_program": f"Writing the model: {a.get('summary') or 'first version'}",
        "edit_program": f"Changing: {a.get('summary') or 'details'}",
        "mesh_write": f"Sculpting the model: {a.get('summary') or 'first form'}",
        "mesh_edit": f"Sculpting: {a.get('summary') or 'details'}",
        "set_params": f"Adjusting {', '.join(a['values'] if isinstance(a.get('values'), dict) else []) or 'parameters'}",
        "inspect_model": "Measuring my own model",
        "look": {"compare": "Comparing the model with the photo", "model": "Looking at the model from all sides", **PCB_LOOKS}.get(
            str(a.get("what")), "Taking a closer look at the photo"),
        "measure": "Reading the caliper" if str(a.get("target", "")).lower() == "caliper" else f"Measuring “{a.get('target', 'the object')}” on the photo",
        "dimensions": f"Looking up dimensions: {a.get('query', '')}",
        "remember_interface": f"Remembering “{a.get('name', '')}” for next time",
        "ask_user": "Asking you a question",
        "fit_to_photo": f"Fitting {', '.join(a.get('params') or []) or 'the outline'} to the photo silhouette",
        "propose_probe": f"Preparing a test print for {a.get('dimension', 'a critical size')}",
        "concept_images": "Sketching concepts",
        "load_terrain": f"Loading real elevation data{(': ' + a['place']) if a.get('place') else ''}",
        "compare_print": "Comparing your print with the target",
        "finish": "Final check before handing over",
    }.get(name, name.replace("_", " "))


def _likeness(r: dict[str, Any]) -> float | None:
    for f in r.get("likeness") or []:
        v = f.get("silhouette_iou", f.get("outline_iou"))
        if isinstance(v, (int, float)):
            return float(v)
    return None


# what broke on our side rather than in the agent's program: people get a calm line, the model the full error
INTERNAL_ERRORS = {"KeyError", "IndexError", "TypeError", "AttributeError", "IntegrityError", "OperationalError", "OSError",
                   "FileNotFoundError", "PermissionError", "UnidentifiedImageError", "DecompressionBombError", "ZeroDivisionError", "error"}
BUILD_TOOLS = ("write_program", "edit_program", "mesh_write", "mesh_edit", "set_params", "fit_to_photo")


def _short(text: str, n: int = 80) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line if len(line) <= n else line[: n - 1].rstrip() + "…"


def failure_title(name: str, r: dict[str, Any]) -> str:
    err = scrub(str(r.get("error") or r.get("reason") or "failed"))
    head, low = err.split(":", 1)[0].strip(), err.lower()
    if r.get("infra") or head in INTERNAL_ERRORS or r.get("stage") in ("crash", "protocol"):
        return "Internal step failed, trying another way"
    if name == "write_circuit" and r.get("stage") == "timeout":
        return "Routing took too long, simplifying the board"
    if r.get("stage") == "timeout" or head == "TimeoutError" or "timed out" in low or "timeout" in low:
        return "The model took too long to compute, simplifying"
    if "not valid json" in low:
        return "The answer was cut off, retrying shorter"
    if name in BUILD_TOOLS or name == "write_circuit":
        if name in ("edit_program", "write_circuit") and low.startswith(("not found", "ambiguous", "edit ")):
            return "Edit didn't apply, retrying"
        return f"{'Fixing the circuit' if name == 'write_circuit' else 'Fixing the program'}: {_short(err)}"
    if name == "make_enclosure" and r.get("stage"):
        return f"The case did not build: {_short(err)}"
    return f"Problem: {_short(err, 140)}"


# ------------------------------------------------------------------ electronics: the board, its case, the PCB
def _mm2(v: Any) -> str:
    """Clearances to 0.01 mm: 0.268 -> '0.27'."""
    try:
        return f"{float(v):.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(v)


def _n(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _part(pid: Any) -> str:
    """A board part as people name it, like the studio does: 'usb' -> 'USB', 'btn_reset' -> 'RESET'."""
    s = re.sub(r"(^|_)(btn|button)_", r"\1", str(pid or ""), flags=re.IGNORECASE).replace("_", " ")
    return s.upper() if len(s) <= 8 else s


CASE_PROBLEM = {
    "port_blocked": "{p} plug blocked", "board_collision": "the board hits the case", "component_clear": "{p} touches a wall",
    "pcb_seated": "the board is not held", "button_reach": "{p} button out of reach", "button_unreachable": "{p} button out of reach",
    "light_window": "{p} window blocked", "lid_fit": "the lid does not fit", "snap_strain": "snaps bend {v} %",
    "metal_in_keepout": "metal in an antenna keep-out",
}
SCALE = {"board_holes": "scale from its holes", "a4": "scale from the A4 sheet", "card": "scale from the bank card",
         "board_outline": "scale from its outline", "none": "no scale reference"}


def _usb(mm: Any) -> str:
    # the check's bisection stops at 2 mm: 1.998 means "2 mm or more"
    return "USB ≥ 2 mm" if isinstance(mm, (int, float)) and mm >= 1.99 else f"USB {_mm2(mm)} mm"


def _case_problems(enc: dict[str, Any]) -> list[str]:
    """The error findings of a case check (elec_tools.brief) in a few words each; past three, the first two and a count."""
    out = []
    for f in enc.get("errors") or []:
        v = f.get("value")
        out.append(CASE_PROBLEM.get(f.get("code"), str(f.get("code", "error")).replace("_", " ")).format(
            p=_part(f.get("part")), v=f"{v:.1f}" if isinstance(v, (int, float)) else v))
    return out if len(out) <= 3 else out[:2] + [f"+{len(out) - 2} more"]


def _case_details(enc: dict[str, Any]) -> list[str]:
    """What a passing case check measured: USB clearance, buttons, snap strain."""
    s = enc.get("summary") or {}
    out = [_usb(s["usb_clearance_mm"])] if isinstance(s.get("usb_clearance_mm"), (int, float)) else []
    aside = [w for w in enc.get("warnings") or [] if w.get("code") == "button_unreachable"]
    if aside:
        out.append(f"{_part(aside[0].get('part'))} only with the lid off")
    elif isinstance(s.get("button_gap_mm"), (int, float)):
        out.append("all buttons reach")
    if isinstance(s.get("snap_strain_pct"), (int, float)):
        out.append(f"snaps {s['snap_strain_pct']:.1f} %")
    return out


def _case_check(enc: Any) -> bool:
    """A case check that ran (elec_tools.brief), as opposed to an engine failure."""
    return isinstance(enc, dict) and ("errors" in enc or "summary" in enc)


def _case_suffix(enc: Any) -> str:
    """How a build of a case did against its board, after the build's own line."""
    if not isinstance(enc, dict):
        return ""
    if not _case_check(enc):
        return "; the case check did not run"
    if enc.get("errors"):
        return f"; does not fit the board yet: {', '.join(_case_problems(enc))}"
    usb = (enc.get("summary") or {}).get("usb_clearance_mm")
    return "; fits the board" + (f", {_usb(usb)}" if isinstance(usb, (int, float)) else "")


def _drc(r: dict[str, Any]) -> int:
    """DRC errors of a PCB brief, the suppressed follow-ups included ('3 DRC error(s): ...')."""
    m = re.match(r"(\d+) DRC", str(r.get("error") or ""))
    return int(m[1]) if m else len(r.get("errors") or [])


def _pcb(r: dict[str, Any]) -> str:
    """'PCB v3 — 0 DRC errors, 23 traces, 13 vias' (+ the intent when it is missing or not met)."""
    c = r.get("counts") or {}
    parts = [_n(_drc(r), "DRC error", "DRC errors")] + [_n(int(c[k]), one, many) for k, one, many in (
        ("traces", "trace", "traces"), ("vias", "via", "vias")) if isinstance(c.get(k), (int, float))]
    intent = r.get("intent") or {}
    if intent and not intent.get("checked"):
        parts.append("no intent stated")
    elif intent and not intent.get("ok", True):
        parts.append(f"intent not met: {len(intent.get('issues') or []) or 1}")
    return f"PCB v{r.get('version')} — {', '.join(parts)}"


def _elec_result(name: str, args: dict[str, Any], r: dict[str, Any]) -> str | None:
    """The electronics tools' results with their numbers; None leaves a plain failure to failure_title."""
    if name in ("scan_board", "use_board") and r.get("ok") is not False and isinstance(r.get("board"), dict):
        b = r["board"]
        size = _size((b.get("size_mm") or [])[:2])
        built = r.get("build") or {}
        case = f"; case updated: v{built['version']}" if built.get("ok") and built.get("version") else ""
        if name == "use_board":
            head = "Board from its own numbers" if _own_board(args) else "Board from the dataset"
            return f"{head}: {b.get('name', 'board')}{', ' + size if size else ''}{case}"
        cal = r.get("calibration") or {}
        scale = SCALE.get(cal.get("method"), SCALE["none"])
        unc = cal.get("uncertainty_mm")
        scale += f" ±{_mm2(unc)} mm" if isinstance(unc, (int, float)) and cal.get("method") not in (None, "none") else ""
        if b.get("source") == "photo":  # not in the dataset: the photo is all there is
            return f"Board measured: {size or b.get('name', 'board')}, {scale}{case}"
        return f"Board read: {b.get('name', 'board')}, {scale}{case}"
    if name == "check_enclosure" and _case_check(r):
        # the call line already says what was checked, so the result starts with the verdict (the studio's own words);
        # brief() has no board name yet, a later one may carry it
        board = r.get("board_name") or "The board"
        if r.get("errors"):
            return f"{board} does not fit yet — {', '.join(_case_problems(r))}"
        others = [w for w in r.get("warnings") or [] if w.get("code") != "button_unreachable"]
        details = ", ".join(_case_details(r) + ([f"notes: {len(others)}"] if others else []))
        return f"{board} fits" + (f" — {details}" if details else "")
    if name == "write_circuit" and r.get("version") is not None and "counts" in r:
        return _pcb(r)
    if name == "check_pcb" and r.get("version") is not None and "counts" in r:
        intent = r.get("intent") or {}
        state = ("no intent stated" if not intent.get("checked") else "intent met" if intent.get("ok", True)
                 else f"intent not met: {len(intent.get('issues') or []) or 1}")
        fab = "fab files ready" if str(r.get("fab", "")).startswith("ready") else "no fab files"
        return f"PCB v{r['version']}: {_n(_drc(r), 'DRC error', 'DRC errors')}, {state}, {fab}"
    if name == "export_fab" and r.get("version") is not None:
        if r.get("ok") is False:
            why = "it still has DRC errors" if "DRC" in str(r.get("error")) else "the export failed"
            return f"No fab files for PCB v{r['version']} yet: {why}"
        what = [f"Gerber zip ({_n(len(r['layers']), 'layer', 'layers')})" if isinstance(r.get("layers"), list) else "Gerber zip"]
        what += [f"{k.upper()} ({_n(int(r[k + '_lines']), 'line', 'lines')})" if isinstance(r.get(k + "_lines"), int) else k.upper() for k in ("bom", "cpl")]
        return f"Fab files for PCB v{r['version']}: {', '.join(what)}"
    if name == "make_enclosure" and r.get("ok") is not False and r.get("version") is not None:
        state = "printable" if r.get("printable", True) else "problems to fix: " + str(sum(1 for i in r.get("issues") or [] if i.get("severity") == "error"))
        # the call line names the PCB version when the model gave one
        of = f" for PCB v{r['pcb_version']}" if r.get("pcb_version") and not _pcb_v(args.get("version")) else ""
        # size_mm is the print plate (base, lid and the board mock-up laid out), not the case as it stands assembled
        return f"Case v{r['version']}{of} — print plate {_size(r.get('size_mm'))}, {state}{_case_suffix(r.get('enclosure'))}"
    return None


def result_title(name: str, args: dict[str, Any], r: dict[str, Any]) -> str:
    if name in ELEC_TOOLS:
        # a board saved with DRC errors or a case that does not fit yet is a result, not a failed step
        title = _elec_result(name, args or {}, r)
        if title:
            return title
    if r.get("ok") is False:
        return failure_title(name, r)
    if name in ("write_program", "edit_program", "mesh_write", "mesh_edit", "set_params", "fit_to_photo"):
        issues = r.get("issues") or []
        errors = sum(1 for i in issues if i.get("severity") == "error")
        warns = sum(1 for i in issues if i.get("severity") == "warn")
        state = "printable" if r.get("printable", True) and not errors else f"problems to fix: {errors}"
        extra = f", notes: {warns}" if warns else ""
        fit = r.get("fit")
        fitted = f" — silhouette match {fit['iou_before']:.0%} → {fit['iou_after']:.0%}" if fit else ""
        like = _likeness(r)
        # in pack 'enclosure' every build is checked against its board at once (elec_tools.after_build)
        return (f"Version {r.get('version')} — {_size(r.get('size_mm'))}, {state}{extra}{fitted}"
                f"{f', silhouette match {like:.0%}' if like is not None else ''}{_case_suffix(r.get('enclosure'))}")
    if name == "measure":
        if str(args.get("target", "")).lower() == "caliper":
            return f"Caliper reads {_mm(r.get('value_mm'))} mm" if r.get("value_mm") else "Couldn't read the caliper"
        unc = r.get("uncertainty_mm")
        holes = [h for h in (r.get("holes_mm") or []) if h.get("circular", True)]
        cutouts = len(r.get("holes_mm") or []) - len(holes)
        hole_txt = f", holes: {len(holes)} × Ø{_mm(holes[0]['d'])}" if holes else ""
        hole_txt += f", cutouts: {cutouts}" if cutouts else ""
        if r.get("calibrated") and r.get("size_mm"):
            return f"Measured {r.get('name', 'object')}: {_size(r['size_mm'])}{f' ±{_mm(unc)}' if unc else ''}{hole_txt}"
        return f"Found {r.get('name', 'the object')} (no reference in the photo, sizes in pixels only)"
    if name == "dimensions":
        n, web = len(r.get("standards") or []), len(r.get("web") or [])
        if not n and not web:
            return "Nothing found"
        return ", ".join(t for t in (f"Standard values found: {n}" if n else "", f"Dimensions found: {web}" if web else "") if t)
    if name == "look":
        what = str((args or {}).get("what"))
        if what in PCB_LOOKS and r.get("version") is not None:
            return f"PCB v{r['version']}" + {"pcb": " from the top", "pcb_bottom": " from below"}.get(what, " schematic")
        like = _likeness(r)
        return f"Silhouette match {like:.0%}" if like is not None else "Done"
    if name == "inspect_model":
        return "Measured the model"
    if name == "ask_user":
        return f"You answered: {r.get('answer')}" if r.get("answer") else "No answer — continuing with a stated assumption"
    if name == "propose_probe":
        v = r.get("variants") or []
        return f"Test print ready, variants: {len(v)}, ~{_mm(r.get('est_minutes'))} min"
    if name == "concept_images":
        return f"Concepts ready: {r.get('count', 0)}"
    if name == "load_terrain":
        return f"Elevation loaded: {_mm(r.get('relief_m'))} m relief over {_mm(r.get('size_km'))} km"
    if name == "compare_print":
        return f"Print deviates {_mm(r.get('mean_mm'))} mm on average (max {_mm(r.get('max_mm'))})"
    if name == "finish":
        if r.get("accepted"):
            # from the third finish on the review only reports (tools._finish): accepted is not approved
            if r.get("unresolved") or r.get("review") == "notes":
                return "Handed over; the reviewer still has notes"
            if r.get("review") == "none":
                return "Handed over without a review: the reviewer did not answer"
            return "Approved"
        return f"Not yet: {r.get('reason', 'needs fixes')}"
    if name == "remember_interface":
        return "Saved to your setup"
    return "Done"
