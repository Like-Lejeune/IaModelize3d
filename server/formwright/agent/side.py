"""Side jobs: slicing with a justified profile, probe prints, concept images,
breeding (LLM as the crossover operator over programs) and visual edits."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

from .. import storage
from ..db import get_db, new_id, now
from ..geom import GeomError, geom
from ..llm.client import meta
from ..models import SendMessage
from .prompts import SYSTEM
from .runner import JobContext, add_message

log = logging.getLogger(__name__)


async def _latest(ctx: JobContext) -> dict[str, Any] | None:
    db = await get_db()
    return await db.one("SELECT * FROM programs WHERE project_id = ? ORDER BY version DESC LIMIT 1", ctx.project_id)


async def slice_job(ctx: JobContext, payload: dict[str, Any]) -> str:
    from ..printing import fingerprint, service

    prog = await _latest(ctx)
    if not prog:
        raise ValueError("nothing to slice yet")
    await ctx.status("Choosing print settings from the geometry")
    db = await get_db()
    brief = ctx.project.get("brief") or {}
    printer_id = payload.get("printer") or brief.get("printer")
    if payload.get("printer"):
        await db.update("projects", "id", ctx.project_id, {"brief": {**brief, "printer": payload["printer"]}})
    # checks=None: re-run them with the chosen printer/material profile
    result = await service.slice(
        ctx.meter, project_id=ctx.project_id, source=prog["source"], params=payload.get("params") or prog["params"], inputs=prog["inputs"],
        title=ctx.project["title"], printer_id=printer_id, material=payload.get("material", "PLA"), goals=payload.get("goals", []),
        checks=None, brief=brief, model=ctx.models.fast, fingerprint=await fingerprint.load(ctx.user["id"], printer_id),
    )
    await ctx.emit("slice", result)
    s = result.get("stats", {})
    changed = len(result.get("diff", []))
    text = f"Sliced: {s.get('minutes', 0):.0f} min, {s.get('grams', 0):.1f} g, {s.get('layers', 0)} layers. {changed} setting(s) changed from the printer's default profile, each with a reason."
    await add_message(ctx.project_id, "agent", text, {"slice": result})
    await ctx.emit("agent.message", {"text": text})
    return text


async def make_probe(ctx: JobContext, args: dict[str, Any]) -> dict[str, Any]:
    from ..printing import probes

    probe = probes.make_probe(args["kind"], float(args["nominal"]), variants=args.get("variants"), extra={"dimension": args.get("dimension")})
    try:
        built = await geom().build(probe["source"], {}, analyze="full")
        png = await geom().render(probe["source"], {}, view="iso", tile=420)
        tmf = await geom().export(probe["source"], {}, "3mf", title=f"probe {args.get('dimension', '')}")
        stl = await geom().export(probe["source"], {}, "stl")
    except GeomError as e:
        return {"ok": False, "error": f"probe failed to build: {e.message}"}
    pid = new_id("probe_")
    render = storage.save_bytes(ctx.project_id, "probes", f"{pid}.png", base64.b64decode(png["png"]))
    f3mf = storage.save_bytes(ctx.project_id, "probes", f"{pid}.3mf", base64.b64decode(tmf["data"]))
    fstl = storage.save_bytes(ctx.project_id, "probes", f"{pid}.stl", base64.b64decode(stl["data"]))
    event = {"dimension": args.get("dimension"), "kind": args["kind"], "nominal": args["nominal"], "variants": probe["variants"],
             "est_minutes": probe.get("est_minutes"), "render": storage.url(render), "files": {"3mf": storage.url(f3mf), "stl": storage.url(fstl)},
             "size_mm": built["checks"]["stats"]["size"]}
    await ctx.emit("probe", event)
    return {"ok": True, "variants": probe["variants"], "est_minutes": probe.get("est_minutes"),
            "next": "ask the user to print it and tell which label fits best (ask_user with the labels as options)"}


async def probe_job(ctx: JobContext, payload: dict[str, Any]) -> str:
    r = await make_probe(ctx, payload)
    return json.dumps(r)[:300]


async def make_concepts(ctx: JobContext, prompt: str, n: int = 3) -> list[str]:
    n = max(1, min(n, 4))
    await ctx.status("Sketching concepts")
    styled = (f"{prompt}. Product concept render of a 3D-printed object in matte PLA, single object on a plain light background, "
              "studio light, full object visible, no text.")
    images = await meta().image(ctx.meter, styled, n=n)
    db = await get_db()
    rels = []
    items = []
    for img in images:
        aid = new_id("a_")
        rel = storage.save_bytes(ctx.project_id, "concepts", f"{aid}.png", img)
        await db.insert("assets", {"id": aid, "project_id": ctx.project_id, "kind": "concept", "path": rel, "mime": "image/png", "meta": {"prompt": prompt}, "created_at": now()})
        rels.append(rel)
        items.append({"url": storage.url(rel), "prompt": prompt, "asset_id": aid})
    await ctx.emit("concepts", {"images": items})
    return rels


async def concepts_job(ctx: JobContext, payload: dict[str, Any]) -> str:
    rels = await make_concepts(ctx, payload.get("prompt", ""), int(payload.get("n", 4)))
    return f"{len(rels)} concepts"


BREED_SCHEMA = {
    "type": "object",
    "properties": {
        "children": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"summary": {"type": "string"}, "source": {"type": "string"}},
                "required": ["summary", "source"],
            },
        }
    },
    "required": ["children"],
}


async def breed_job(ctx: JobContext, payload: dict[str, Any]) -> str:
    """Interactive evolution: the LLM is the mutation/crossover operator over program code."""
    db = await get_db()
    parents = []
    for v in payload.get("parents", [])[:4]:
        p = await db.one("SELECT * FROM programs WHERE project_id = ? AND version = ?", ctx.project_id, int(v))
        if p:
            parents.append(p)
    if not parents:
        prog = await _latest(ctx)
        parents = [prog] if prog else []
    if not parents:
        raise ValueError("no program to breed from")
    n = max(2, min(int(payload.get("n", 6)), 8))
    await ctx.status(f"Breeding {n} variants from {len(parents)} parent(s)")
    text = "Parents the user liked:\n" + "\n\n".join(f"## v{p['version']} ({p['summary']})\n```js\n{p['source']}\n```" for p in parents)
    out = await meta().json(
        ctx.meter, model=ctx.models.designer, system=SYSTEM + "\n\nYou are now the variation operator of an interactive evolution. "
        "Create children that combine traits of the parents (crossover) and add one bold but printable mutation each "
        "(new rhythm, profile, twist, texture, proportion). Keep the program format, params and all exact interfaces. "
        "Every child must be a complete program and visually distinct from the parents and from each other.",
        content=[{"type": "input_text", "text": f"{text}\n\nReturn {n} children."}], schema=BREED_SCHEMA, name="breed", effort="medium", max_output_tokens=16000,
    )
    base = (await _latest(ctx))["version"]  # type: ignore[index]
    items = []
    version = base
    for child in out.get("children", [])[:n]:
        try:
            built = await geom().build(child["source"], {}, analyze="fast")
            png = await geom().render(child["source"], {}, view="iso", tile=384)
        except GeomError as e:
            log.info("child failed: %s", e)
            continue
        version += 1
        rel = storage.save_bytes(ctx.project_id, "renders", f"v{version}_iso.png", base64.b64decode(png["png"]))
        await db.insert("programs", {"project_id": ctx.project_id, "version": version, "source": child["source"], "params": built["params"], "inputs": parents[0]["inputs"],
                                     "summary": "variant: " + child["summary"][:200], "checks": built.get("checks"), "author": "breed", "created_at": now()})
        items.append({"version": version, "render": storage.url(rel), "summary": child["summary"][:200], "ok": built.get("checks", {}).get("ok", True)})
    if items:
        await db.update("projects", "id", ctx.project_id, {"version": version, "updated_at": now()})
    await ctx.emit("variants", {"items": items})
    return f"{len(items)} variants"


async def visual_edit_job(ctx: JobContext, payload: dict[str, Any]) -> str:
    """Strokes on a render + an instruction -> Muse Image paints the target -> the agent edits code to match."""
    from .loop import design

    sketch = base64.b64decode(payload["sketch_png"].split(",")[-1])
    sketch_rel = storage.save_bytes(ctx.project_id, "edits", f"{new_id('s_')}.png", sketch)
    await ctx.status("Painting the requested change")
    target = await meta().image(ctx.meter, f"Edit this product render: {payload['instruction']}. The user's strokes mark where. "
                                           "Keep everything else identical, same view and lighting, remove the strokes.",
                                images=[storage.png_data_url(sketch)], n=1)
    db = await get_db()
    asset_ids = []
    for rel, kind in ((sketch_rel, "sketch"),) + tuple((storage.save_bytes(ctx.project_id, "edits", f"{new_id('t_')}.png", t), "concept") for t in target):
        aid = new_id("a_")
        await db.insert("assets", {"id": aid, "project_id": ctx.project_id, "kind": kind, "path": rel, "mime": "image/png",
                                   "meta": {"visual_edit": payload["instruction"]}, "created_at": now()})
        asset_ids.append(aid)
    await ctx.emit("concepts", {"images": [{"url": storage.url(r["path"]), "prompt": payload["instruction"]} for r in
                                           await db.all("SELECT path FROM assets WHERE id IN (%s)" % ",".join("?" * len(asset_ids)), *asset_ids)]})
    msg = SendMessage(text=f"Visual edit: {payload['instruction']}. The first image shows my strokes on the current render; "
                           "the second is the target look. Change the program so the model looks like the target, keep all fits.",
                      asset_ids=asset_ids)
    await add_message(ctx.project_id, "user", msg.text, {"asset_ids": asset_ids})
    return await design(ctx, msg) or ""
