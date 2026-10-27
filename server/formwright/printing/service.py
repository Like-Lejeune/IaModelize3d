"""Printers, printer profiles for checks, and slicing with a justified profile."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from ..config import settings
from ..db import new_id
from ..geom import geom
from ..llm.client import CostMeter
from . import presets
from .profile import apply_diff, features, propose_with_report

log = logging.getLogger(__name__)

POPULAR = [
    "Bambu Lab X1 Carbon 0.4 nozzle",
    "Bambu Lab P1S 0.4 nozzle",
    "Bambu Lab A1 0.4 nozzle",
    "Bambu Lab A1 mini 0.4 nozzle",
    "Prusa MK4 0.4 nozzle",
    "Prusa MINI 0.4 nozzle",
    "Creality K1 (0.4 nozzle)",
    "Creality Ender-3 V3 0.4 nozzle",
    "Elegoo Neptune 4 0.4 nozzle",
    "Voron 2.4 350 0.4 nozzle",
]
DEFAULT_PRINTER = POPULAR[0]

# max overhang (deg from vertical) and bridge (mm) that print cleanly, by material
MATERIAL_LIMITS = {"PLA": (50, 12), "PETG": (45, 8), "ABS": (45, 8), "ASA": (45, 8), "TPU": (40, 5), "PC": (45, 8), "PA": (45, 8)}
DENSITY = {"PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07, "TPU": 1.21, "PC": 1.20, "PA": 1.14}


class SliceError(Exception):
    pass


def list_printers() -> list[dict[str, Any]]:
    printers = presets.printers()
    by_name = {p.name: p for p in printers}
    popular = [by_name[n] for n in POPULAR if n in by_name]
    rest = sorted((p for p in printers if p.name not in POPULAR), key=lambda p: (p.vendor.lower(), p.name.lower()))
    return [
        {"id": p.id, "name": p.name, "vendor": p.vendor, "model": p.model, "bed": p.bed, "nozzle": p.nozzle, "popular": p.name in POPULAR}
        for p in popular + rest
    ]


def resolve_printer(printer_id: str | None) -> presets.Printer | None:
    return presets.printer_by(printer_id) or presets.printer_by(DEFAULT_PRINTER) or (presets.printers()[0] if presets.printers() else None)


def printer_profile(printer_id: str | None, fingerprint: dict | None = None, material: str = "PLA") -> dict[str, Any]:
    """geom PrinterProfile for checks and stdlib compensation."""
    mat = (material or "PLA").upper()
    max_overhang, max_bridge = MATERIAL_LIMITS.get(mat, (50, 10))
    prof: dict[str, Any] = {
        "name": "generic 0.4", "bed": [256, 256, 256], "nozzle": 0.4, "layer": 0.2, "lineWidth": 0.42,
        "maxOverhang": max_overhang, "maxBridge": max_bridge, "minLayerTime": 6, "holeDelta": 0.15, "outerDelta": 0.0,
        "fitDelta": 0.0, "elephantFoot": 0.2, "material": mat, "speed": 120,
    }
    p = resolve_printer(printer_id) if presets.available() else None
    if p is not None:
        m = presets.machine(p)
        proc = presets.default_process(p) or {}
        fil = presets.filament_for(p, mat) or {}
        nozzle = presets.num(m.get("nozzle_diameter"), 0.4)
        lw = proc.get("outer_wall_line_width") or proc.get("line_width")
        prof.update({
            "name": p.name,
            "bed": p.bed,
            "nozzle": nozzle,
            "layer": presets.num(proc.get("layer_height"), 0.2),
            "lineWidth": round(presets.num(lw, nozzle * 1.05, base=nozzle) or nozzle * 1.05, 3),
            "minLayerTime": presets.num(fil.get("slow_down_layer_time"), 6),
            "speed": presets.num(proc.get("outer_wall_speed"), 120),
        })
    for k in ("holeDelta", "outerDelta", "fitDelta", "elephantFoot"):
        if fingerprint and fingerprint.get(k) is not None:
            prof[k] = float(fingerprint[k])
    return prof


# ------------------------------------------------------------------ CLI
def _orca_cmd(args: list[str]) -> list[str]:
    exe = settings().orca_bin
    if not exe or not Path(exe).exists():
        raise SliceError("OrcaSlicer is not installed on this server (set FW_ORCA_BIN)")
    cmd = [exe, *args]
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a", *cmd]
    return cmd


async def run_orca(workdir: Path, model_3mf: Path, machine: Path, process: Path, filament: Path, *, timeout: float = 240) -> Path:
    cmd = _orca_cmd([
        "--slice", "0",
        "--load-settings", f"{machine};{process}",
        "--load-filaments", str(filament),
        "--outputdir", str(workdir),
        "--export-3mf", "project.3mf",
        str(model_3mf),
    ])
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=str(workdir), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise SliceError(f"slicer took longer than {timeout:.0f}s") from None
    gcode = workdir / "plate_1.gcode"
    if not gcode.exists():
        tail = (err or out or b"").decode(errors="ignore")[-1500:]
        log_txt = "".join(p.read_text(errors="ignore")[-800:] for p in workdir.glob("*.log"))
        raise SliceError(f"slicer produced no G-code (exit {proc.returncode}) {tail} {log_txt}".strip())
    return gcode


_TIME = re.compile(r"(?:(\d+)d\s*)?(?:(\d+)h\s*)?(?:(\d+)m\s*)?(?:(\d+)s)?")


def _minutes(text: str) -> float | None:
    m = _TIME.search(text.strip())
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(g or 0) for g in m.groups())
    return round(d * 1440 + h * 60 + mi + s / 60, 1)


def parse_gcode_header(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if m := re.search(r"total estimated time:\s*([^\n;]+)", text):
        out["minutes"] = _minutes(m.group(1))
    if m := re.search(r"model printing time:\s*([^\n;]+)", text):
        out["model_minutes"] = _minutes(m.group(1))
    if m := re.search(r";\s*total layer number:\s*(\d+)", text):
        out["layers"] = int(m.group(1))
    if m := re.search(r";\s*filament used \[mm\]\s*=\s*([\d.,\s]+)", text):
        out["filament_m"] = round(sum(float(x) for x in m.group(1).replace(" ", "").split(",") if x) / 1000, 3)
    if m := re.search(r";\s*filament used \[cm3\]\s*=\s*([\d.,\s]+)", text):
        out["cm3"] = round(sum(float(x) for x in m.group(1).replace(" ", "").split(",") if x), 3)
    if m := re.search(r";\s*filament used \[g\]\s*=\s*([\d.,\s]+)", text):
        out["grams_header"] = round(sum(float(x) for x in m.group(1).replace(" ", "").split(",") if x), 2)
    return out


def applied_settings(text: str, keys: list[str]) -> dict[str, str]:
    """What the slicer actually used, from the config block at the end of the G-code."""
    found = {}
    for k in keys:
        if m := re.search(rf"^;\s*{re.escape(k)}\s*=\s*(.*)$", text, re.MULTILINE):
            found[k] = m.group(1).strip()
    return found


def parse_slice_info(project_3mf: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(project_3mf) as z:
            xml = z.read("Metadata/slice_info.config").decode(errors="ignore")
    except (OSError, KeyError, zipfile.BadZipFile):
        return {}
    out: dict[str, Any] = {}
    if m := re.search(r'key="prediction" value="([\d.]+)"', xml):
        out["minutes"] = round(float(m.group(1)) / 60, 1)
    if m := re.search(r'key="weight" value="([\d.]+)"', xml):
        out["grams"] = float(m.group(1))
    out["outside"] = 'key="outside" value="true"' in xml
    out["support_used"] = 'key="support_used" value="true"' in xml
    out["filaments"] = [
        {"id": int(a), "type": t, "color": c, "used_m": float(m_), "used_g": float(g)}
        for a, t, c, m_, g in re.findall(r'<filament id="(\d+)"[^>]*type="([^"]*)" color="([^"]*)" used_m="([\d.]+)" used_g="([\d.]+)"', xml)
    ]
    return out


def _clean(preset: dict) -> dict:
    return {k: v for k, v in preset.items() if not k.startswith("_")}


async def slice(
    meter: CostMeter | None,
    *,
    project_id: str,
    source: str,
    params: dict | None,
    inputs: dict | None,
    title: str,
    printer_id: str | None,
    material: str,
    goals: list[str],
    checks: dict | None,
    brief: dict | None,
    model: str | None,
    fingerprint: dict | None = None,
    use_llm: bool | None = None,
) -> dict[str, Any]:
    if not presets.available():
        raise SliceError("OrcaSlicer profiles not found (set FW_ORCA_PROFILES)")
    p = resolve_printer(printer_id)
    if p is None:
        raise SliceError("no printer presets available")
    mat = (material or "PLA").upper()
    machine = presets.machine(p)
    process = presets.default_process(p)
    filament = presets.filament_for(p, mat)
    if not process or not filament:
        raise SliceError(f"no {mat} profile for {p.name}")
    profile = printer_profile(p.id, fingerprint, mat)
    if checks is None:
        built = await geom().build(source, params or {}, analyze="full", inputs=inputs or {}, printer=profile, vaseMode=bool((brief or {}).get("vase_mode")))
        checks = built.get("checks") or {}
        parts = built.get("parts") or []
    else:
        parts = (brief or {}).get("parts") or []
    t0 = time.monotonic()
    evidence = features(checks, checks.get("stats"), {**(brief or {}), "material": mat, "parts": parts})
    limits = presets.limits_of(machine)
    report = await propose_with_report(
        meter, base={"process": process, "filament": filament, "material": mat}, evidence=evidence, goals=goals, limits=limits,
        model=model, use_llm=bool(model) if use_llm is None else use_llm,
    )
    diff = report["diff"]
    plate = presets.plate_for(filament)
    if plate and plate != presets.DEFAULT_PLATE:
        diff.append({"key": "curr_bed_type", "from": presets.DEFAULT_PLATE, "to": plate, "value": plate, "file": "process",
                     "reason": f"{mat} does not stick to the {presets.DEFAULT_PLATE.lower()}; the slicer refuses it there.",
                     "evidence": [f"material:{mat}"], "source": "rules:bed_type", "required": True})
    proc2, fil2 = apply_diff(process, filament, diff)

    exported = await geom().export(source, params or {}, "3mf", inputs=inputs or {}, title=title, printer=profile)
    slice_id = new_id("s_")
    rel = Path(project_id) / "slices" / slice_id
    dest = settings().data_dir / "files" / rel
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fw-slice-") as tmp:
        work = Path(tmp)
        model_3mf = work / "model.3mf"
        model_3mf.write_bytes(base64.b64decode(exported["data"]))
        files = {}
        for name, data in (("machine", machine), ("process", proc2), ("filament", fil2)):
            path = work / f"{name}.json"
            path.write_text(json.dumps(_clean(data), ensure_ascii=False), encoding="utf-8")
            files[name] = path
        gcode = await run_orca(work, model_3mf, files["machine"], files["process"], files["filament"])
        text = gcode.read_text(errors="ignore")
        header = parse_gcode_header(text)
        info = parse_slice_info(work / "project.3mf") if (work / "project.3mf").exists() else {}
        used = applied_settings(text, [d["key"] for d in diff if not d.get("part")])
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", title)[:40] or "model"
        shutil.copy(gcode, dest / f"{safe}.gcode")
        if (work / "project.3mf").exists():
            shutil.copy(work / "project.3mf", dest / f"{safe}.3mf")
    density = presets.num(filament.get("filament_density"), DENSITY.get(mat, 1.24))
    grams = info.get("grams") or header.get("grams_header") or round((header.get("cm3") or 0) * density, 2)
    warnings: list[str] = []
    if info.get("outside"):
        warnings.append("model is outside the printable area")
    if info.get("support_used"):
        warnings.append("supports are used")
    for d in diff:
        if d.get("part") or d["key"] not in used:
            continue
        got = [x.strip().strip('"') for x in used[d["key"]].split(",")]
        if str(d["to"]) not in got:
            warnings.append(f"slicer did not apply {d['key']}={d['to']} (got {used[d['key']]})")
    for issue in (checks or {}).get("issues", []):
        if issue.get("severity") == "error":
            warnings.append(issue.get("message", issue.get("code", "")))
    stats = {
        "minutes": info.get("minutes") or header.get("minutes"),
        "grams": round(float(grams), 2) if grams else None,
        "filament_m": header.get("filament_m"),
        "layers": header.get("layers"),
        "warnings": warnings,
        "filaments": info.get("filaments", []),
        "slice_seconds": round(time.monotonic() - t0, 2),
    }
    base_url = f"/files/{rel.as_posix()}"
    return {
        "id": slice_id,
        "printer": {"id": p.id, "name": p.name},
        "material": mat,
        "presets": {"process": process.get("name"), "filament": filament.get("name")},
        "stats": stats,
        "diff": [{k: v for k, v in d.items() if k != "value"} for d in diff],
        "rejected": report["rejected"],
        "evidence": report["evidence"],
        "applied": used,
        "files": {"gcode": f"{base_url}/{safe}.gcode", "project_3mf": f"{base_url}/{safe}.3mf" if (dest / f'{safe}.3mf').exists() else None},
    }
