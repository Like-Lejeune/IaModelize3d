"""Human-readable narration of agent steps for the timeline and Telegram.

Raw tool JSON stays available as `summary` for the details expander; these titles are
what people read: "Measured the bracket: 70.5 × 45.4 mm ±0.6".
"""
from __future__ import annotations

from typing import Any

KIND = {
    "write_program": "build", "edit_program": "edit", "set_params": "params", "inspect_model": "inspect", "look": "look",
    "measure": "measure", "dimensions": "standard", "remember_interface": "memory", "ask_user": "ask", "fit_to_photo": "fit",
    "propose_probe": "probe", "concept_images": "concepts", "load_terrain": "terrain", "compare_print": "compare", "finish": "finish",
    "mesh_write": "build", "mesh_edit": "edit",
}

# which stage of the job a tool belongs to
STAGE = {
    "build": "design", "edit": "design", "params": "design", "terrain": "measure", "concepts": "design",
    "measure": "measure", "standard": "measure", "memory": "understand", "ask": "understand",
    "inspect": "check", "look": "check", "fit": "check", "probe": "check",
    "compare": "check", "finish": "review",
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
    "printability errors remain": "остались ошибки печатаемости", "needs fixes": "нужны правки", "Overlay ready": "Наложение готово", "Views rendered": "Виды готовы",
    "Download 3MF": "Скачать 3MF", "Prepare print settings": "Подготовить настройки печати", "Print a 5-minute test piece": "Напечатать 5-минутный пробник",
    "Order a print": "Заказать печать", "Share as a recipe": "Поделиться рецептом",
    "Sculpting the model": "Леплю модель", "Sculpting": "Леплю", "first form": "первая форма",
    "Comparing the model with the photo": "Сравниваю модель с фото", "Looking at the model from all sides": "Смотрю на модель со всех сторон",
    "Looking up dimensions": "Ищу размеры", "Silhouette match": "Совпадение силуэта", "Nothing found": "Ничего не найдено",
    "Finding": "Ищу", "Measuring the photos": "Измеряю фото", " mm": " мм", " min": " мин", " km": " км", " m relief": " м перепад", "Saved to your setup": "Сохранено в ваших размерах", "Problem": "Проблема", "Done": "Готово",
}


def localize(text: str, language: str | None) -> str:
    if not language or not language.lower().startswith(("ru", "kk")):
        return text
    for en in sorted(RU, key=len, reverse=True):
        text = text.replace(en, RU[en])
    return text


def stage_label(stage: str, language: str | None) -> str:
    if language and language.lower().startswith(("ru", "kk")):
        return STAGE_LABEL_RU[stage]
    return STAGE_LABEL[stage]


def _mm(v: Any) -> str:
    try:
        return f"{float(v):.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(v)


def _size(size: list | None) -> str:
    return " × ".join(_mm(v) for v in (size or [])) + " mm" if size else ""


def call_title(name: str, args: dict[str, Any]) -> str:
    a = args or {}
    return {
        "write_program": f"Writing the model: {a.get('summary') or 'first version'}",
        "edit_program": f"Changing: {a.get('summary') or 'details'}",
        "mesh_write": f"Sculpting the model: {a.get('summary') or 'first form'}",
        "mesh_edit": f"Sculpting: {a.get('summary') or 'details'}",
        "set_params": f"Adjusting {', '.join(a['values'] if isinstance(a.get('values'), dict) else []) or 'parameters'}",
        "inspect_model": "Measuring my own model",
        "look": {"compare": "Comparing the model with the photo", "model": "Looking at the model from all sides"}.get(
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


def result_title(name: str, args: dict[str, Any], r: dict[str, Any]) -> str:
    if r.get("ok") is False:
        err = str(r.get("error") or r.get("reason") or "failed")
        return f"Problem: {err[:140]}"
    if name in ("write_program", "edit_program", "mesh_write", "mesh_edit", "set_params", "fit_to_photo"):
        issues = r.get("issues") or []
        errors = sum(1 for i in issues if i.get("severity") == "error")
        warns = sum(1 for i in issues if i.get("severity") == "warn")
        state = "printable" if r.get("printable", True) and not errors else f"problems to fix: {errors}"
        extra = f", notes: {warns}" if warns else ""
        fit = r.get("fit")
        fitted = f" — silhouette match {fit['iou_before']:.0%} → {fit['iou_after']:.0%}" if fit else ""
        like = _likeness(r)
        return f"Version {r.get('version')} — {_size(r.get('size_mm'))}, {state}{extra}{fitted}{f', silhouette match {like:.0%}' if like is not None else ''}"
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
            return "Approved"
        return f"Not yet: {r.get('reason', 'needs fixes')}"
    if name == "remember_interface":
        return "Saved to your setup"
    return "Done"
