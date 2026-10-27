"""Presets from the installed OrcaSlicer and real CLI slicing (skipped without Orca)."""
from pathlib import Path

import pytest

from formwright.config import settings
from formwright.printing import presets, service

FIXTURES = (Path(__file__).resolve().parents[2] / "packages" / "geom" / "test" / "fixtures.ts").read_text(encoding="utf-8")


def fixture(name: str) -> str:
    start = FIXTURES.index(f"export const {name} = `") + len(f"export const {name} = `")
    return FIXTURES[start : FIXTURES.index("`;", start)]


needs_orca = pytest.mark.skipif(not (presets.available() and settings().orca_bin and Path(settings().orca_bin).exists()), reason="OrcaSlicer not installed")


@needs_orca
def test_presets_resolve():
    x1c = presets.printer_by("Bambu Lab X1 Carbon 0.4 nozzle")
    assert x1c and x1c.bed[:2] == [256.0, 256.0] and x1c.nozzle == 0.4
    m = presets.machine(x1c)
    assert "inherits" not in m and presets.limits_of(m)["max_acceleration"] >= 5000
    proc = presets.default_process(x1c)
    assert proc and presets.num(proc["layer_height"]) == pytest.approx(0.2)
    for mat in ("PLA", "PETG", "TPU"):
        f = presets.filament_for(x1c, mat)
        assert f and presets.first(f["filament_type"]).upper() == mat
    mk4 = presets.printer_by("prusa-mk4-0-4-nozzle")
    assert mk4 and mk4.bed[:2] == [250.0, 210.0]


@needs_orca
def test_list_printers_popular_first():
    ps = service.list_printers()
    assert ps[0]["name"] == "Bambu Lab X1 Carbon 0.4 nozzle"
    assert [p["popular"] for p in ps[:5]] == [True] * 5
    assert len(ps) > 100


@needs_orca
def test_printer_profile_uses_presets_and_fingerprint():
    prof = service.printer_profile("bambu-lab-x1-carbon-0-4-nozzle", {"holeDelta": 0.27, "elephantFoot": 0.1}, "PETG")
    assert prof["bed"] == [256.0, 256.0, 250.0] and prof["lineWidth"] == pytest.approx(0.42)
    assert prof["holeDelta"] == 0.27 and prof["elephantFoot"] == 0.1 and prof["maxOverhang"] == 45
    generic = service.printer_profile(None)
    assert generic["layer"] > 0 and generic["nozzle"] == 0.4


def test_gcode_header_parsing():
    text = ("; model printing time: 1h 16m 15s; total estimated time: 1h 23m 31s\n; total layer number: 120\n"
            "; filament used [mm] = 3360.45, 12.5\n; filament used [cm3] = 8.08, 0.03\n")
    h = service.parse_gcode_header(text)
    assert h["minutes"] == pytest.approx(83.5) and h["model_minutes"] == pytest.approx(76.2, abs=0.1)
    assert h["layers"] == 120 and h["filament_m"] == pytest.approx(3.373, abs=0.001) and h["cm3"] == pytest.approx(8.11)


@needs_orca
async def test_slice_bag_hook(monkeypatch, tmp_path):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    from formwright.geom import geom

    try:
        r = await service.slice(None, project_id="p_t", source=fixture("BAG_HOOK"), params={}, inputs={}, title="Bag hook",
                                printer_id="bambu-lab-x1-carbon-0-4-nozzle", material="PLA", goals=["strong"],
                                checks=None, brief={"load": "bags pull down"}, model=None)
    finally:
        await geom().close()
    s = r["stats"]
    assert s["minutes"] > 5 and s["grams"] > 3 and s["layers"] > 50 and s["filament_m"] > 1
    keys = {d["key"] for d in r["diff"]}
    assert {"wall_loops", "sparse_infill_density"} <= keys
    for d in r["diff"]:
        assert d["evidence"] and r["applied"].get(d["key"]) is not None
    assert not [w for w in s["warnings"] if w.startswith("slicer did not apply")]
    gcode = tmp_path / "files" / r["files"]["gcode"].removeprefix("/files/")
    assert gcode.exists() and gcode.stat().st_size > 10000
    assert r["files"]["project_3mf"]


def test_plate_choice():
    assert presets.plate_for({"cool_plate_temp": ["35"], "textured_plate_temp": ["55"]}) == "Cool Plate"
    assert presets.plate_for({"cool_plate_temp": ["0"], "textured_plate_temp": ["70"], "hot_plate_temp": ["70"]}) == "Textured PEI Plate"
    assert presets.plate_for({"cool_plate_temp": ["0"], "hot_plate_temp": ["80"]}) == "High Temp Plate"
    assert presets.plate_for({}) is None


@needs_orca
def test_filament_choice_avoids_random_brands():
    a1m = presets.printer_by("bambu-lab-a1-mini-0-4-nozzle")
    for mat in ("PLA", "PETG", "ABS", "TPU"):
        name = presets.filament_for(a1m, mat)["name"]
        assert name.startswith(("Generic", "Bambu")), name


@needs_orca
async def test_slice_petg_picks_a_plate_that_works(monkeypatch, tmp_path):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    from formwright.geom import geom

    try:
        r = await service.slice(None, project_id="p_t", source=fixture("BAG_HOOK"), params={}, inputs={}, title="hook",
                                printer_id="bambu-lab-a1-mini-0-4-nozzle", material="PETG", goals=[], checks=None, brief={}, model=None)
    finally:
        await geom().close()
    plate = next(d for d in r["diff"] if d["key"] == "curr_bed_type")
    assert plate["to"] != "Cool Plate" and r["applied"]["curr_bed_type"] == plate["to"]
    assert r["stats"]["grams"] > 3
