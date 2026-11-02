"""QC of a printed part: the operator photographs it on the A4 sheet, SAM 3.1 outlines it in mm (the same
calibrated path as the intake photo), and printing/compare.py aligns it with the model's footprint.
Pass when the worst deviation stays inside the part's tolerance. Reuses agent/tools.py _compare_print logic
without an agent job (no designer call: one SAM select, about $0.005-0.01).

It checks the outline in plan only: heights, snaps and threads are not seen from above, so a pass reads
"outline within ±0.6 mm", never "will fit". The report (contract C10) carries both outlines on the sheet's
own millimetre grid, the model's already moved onto the print, so the web draws them straight over the photo. A photo
that cannot be measured gives {pass: false, error, error_code: not_found | model_unavailable | no_sheet | version_gone}.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from formwright import quotas
from formwright.db import now
from formwright.printing import compare
from formwright.printing.compare import compare_outlines

DEFAULT_TOL_MM = 0.6  # FDM 0.4 mm nozzle on a calibrated printer; mating features use the probe flow instead
A4 = (210.0, 297.0)
MAX_POINTS = 400


def _thin(loop: np.ndarray, n: int = MAX_POINTS) -> list[list[float]]:
    step = max(1, int(np.ceil(len(loop) / n)))
    return [[round(float(x), 2), round(float(y), 2)] for x, y in loop[::step]]


def align_target(target_mm: Any, printed_mm: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """The model's outer outline moved onto the printed one, by the same PCA + ICP fit compare_outlines makes
    (it is deterministic, so this is the transform behind its numbers). Returns (target on the sheet, printed, r, t)
    with the printed outline mapped into the model frame as p @ r.T + t."""
    tl, pl = compare._loops(target_mm), compare._loops(printed_mm)
    if not tl or not pl:
        raise ValueError("both outlines need at least one closed loop")
    t_s, p_s = compare._resample(tl[0], 400), compare._resample(pl[0], 400)
    best = None
    for start in compare._pca_starts(p_s, t_s, True):
        aligned, err = compare._icp(start, t_s)
        if best is None or err < best[1]:
            best = (aligned, err)
    assert best is not None
    r, t = compare._rigid(p_s, best[0], allow_reflection=True)
    # the inverse of a rigid move: model frame -> sheet, (a - t) @ r
    return (tl[0] - t) @ r, pl[0], r, t


def build_report(target_mm: Any, printed_mm: Any, *, tolerance_mm: float = DEFAULT_TOL_MM, sheet: tuple[float, float] = A4,
                 photo_url: str | None = None, mask_url: str | None = None) -> dict[str, Any]:
    """The C10 QC report from the model footprint and the measured print outline (both in mm)."""
    report = compare_outlines(target_mm, printed_mm)
    on_sheet, printed, r, t = align_target(target_mm, printed_mm)
    # the regions are measured along the model outline: give their centres on the sheet too, for the overlay
    for reg in report["regions"]:
        c = (np.asarray(reg["center"], dtype=float) - t) @ r
        reg["center_sheet"] = [round(float(c[0]), 1), round(float(c[1]), 1)]
    report.update({
        "pass": report["max_mm"] <= tolerance_mm,
        "tolerance_mm": tolerance_mm,
        "photo_url": photo_url,
        "mask_url": mask_url,
        "printed_mm": _thin(printed),
        "target_mm": _thin(on_sheet),
        "sheet": {"w": float(sheet[0]), "h": float(sheet[1])},
        "note": "контур в плане",
        "note_en": "outline in plan view",
        "compared_with": "model footprint",
        "at": now(),
    })
    report.pop("ok", None)  # compare's own 0.5 mm verdict; `pass` against the part's tolerance is the one that counts
    return report


async def ops_project(user: dict[str, Any]) -> str:
    """The operator's own project that holds QC and calibration photos, so nothing lands in a customer's studio."""
    from formwright.db import get_db, new_id

    db = await get_db()
    row = await db.one("SELECT id FROM projects WHERE user_id = ? AND pack = 'shop_ops' ORDER BY created_at LIMIT 1", user["id"])
    if row:
        return row["id"]
    pid = new_id("p_")
    t = now()
    await db.insert("projects", {"id": pid, "user_id": user["id"], "title": "Axo farm: QC and calibration photos", "pack": "shop_ops",
                                 "created_at": t, "updated_at": t})
    return pid


async def check_print(user: dict, order: dict, data: bytes, filename: str, mime: str) -> dict[str, Any]:
    from formwright.db import get_db
    from formwright.geom import geom
    from formwright.models import SelectRequest
    from formwright.vision import ingest, scene

    db = await get_db()
    pid = await ops_project(user)
    asset = await ingest.ingest_asset(pid, "print", filename, data, mime)
    photo_url = f"/files/{asset['path']}"
    try:
        sel = await scene.select(user, pid, asset, SelectRequest(text="3D printed plastic part", role="context", name=f"qc_{order['ref']}"))
    except ValueError as e:
        return {"pass": False, "error": str(e)[:300], "error_code": "not_found", "asset_id": asset["id"], "photo_url": photo_url, "at": now()}
    except quotas.QuotaExceeded:
        raise
    except Exception as e:  # noqa: BLE001 - SAM down or unreachable: the print is not measured, so it neither passes nor fails
        return {"pass": False, "error": f"the measuring model is unavailable ({type(e).__name__}); try the photo again", "error_code": "model_unavailable",
                "asset_id": asset["id"], "photo_url": photo_url, "at": now()}
    sel_data = sel.get("data") or {}
    printed = sel_data.get("outline_mm")
    mask_url = f"/files/{sel['mask_path']}" if sel.get("mask_path") else None
    if not printed:
        return {"pass": False, "error": "no A4 sheet or card in the photo, so the print cannot be measured in mm", "error_code": "no_sheet",
                "asset_id": asset["id"], "photo_url": photo_url, "mask_url": mask_url, "at": now()}
    prog = await db.one("SELECT * FROM programs WHERE project_id = ? AND version = ?", order["project_id"], order["version"])
    if not prog:
        return {"pass": False, "error": f"version {order['version']} of the model is gone", "error_code": "version_gone", "photo_url": photo_url, "at": now()}
    out = await geom().inspect(prog["source"], prog["params"], [{"op": "outline"}], inputs=prog["inputs"])
    target = out["results"][0]["polygons"]
    tol = float(((order.get("intake") or {}).get("tolerance_mm")) or DEFAULT_TOL_MM)
    fresh = await db.one("SELECT meta FROM assets WHERE id = ?", asset["id"])
    size = (((fresh or {}).get("meta") or {}).get("calibration") or {}).get("size_mm")
    sheet = (float(size[0]), float(size[1])) if isinstance(size, list) and len(size) == 2 else A4
    report = build_report(target, printed, tolerance_mm=tol, sheet=sheet, photo_url=photo_url, mask_url=mask_url)
    report.update({"asset_id": asset["id"], "selection_id": sel.get("id"), "version": order["version"],
                   "uncertainty_mm": sel_data.get("uncertainty_mm"), "reference": sel_data.get("reference")})
    return report
