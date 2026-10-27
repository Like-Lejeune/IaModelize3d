"""Read OrcaSlicer's installed system profiles at runtime and resolve `inherits` chains.

Profiles are never copied into the repo: they are read from the user's Orca install
(`settings().orca_profiles`). Names resolve within the same vendor first, then in
OrcaFilamentLibrary, then anywhere.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import settings

KINDS = ("machine", "process", "filament")
LIBRARY = "OrcaFilamentLibrary"


@dataclass(frozen=True)
class Ref:
    vendor: str
    path: Path
    instantiable: bool | None = None


def profiles_dir() -> Path:
    return Path(settings().orca_profiles)


def available() -> bool:
    return profiles_dir().is_dir()


@lru_cache
def index() -> dict[str, dict[str, list[Ref]]]:
    """kind -> preset name -> refs (one per vendor that defines it)."""
    out: dict[str, dict[str, list[Ref]]] = {k: {} for k in KINDS}
    root = profiles_dir()
    if not root.is_dir():
        return out
    for vendor_file in sorted(root.glob("*.json")):
        vendor = vendor_file.stem
        try:
            data = json.loads(vendor_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for kind in KINDS:
            for item in data.get(f"{kind}_list", []) or []:
                path = root / vendor / item["sub_path"]
                out[kind].setdefault(item["name"], []).append(Ref(vendor, path))
    return out


@lru_cache(maxsize=4096)
def _raw(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def find(kind: str, name: str, vendor: str | None = None) -> Ref | None:
    refs = index()[kind].get(name)
    if not refs:
        return None
    for preferred in (vendor, LIBRARY):
        for r in refs:
            if r.vendor == preferred:
                return r
    return refs[0]


@lru_cache(maxsize=2048)
def resolve(kind: str, name: str, vendor: str | None = None) -> dict[str, Any] | None:
    """Fully resolved preset: parent keys first, child keys override. No `inherits` left."""
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    cur, cur_vendor = name, vendor
    while cur and cur not in seen:
        seen.add(cur)
        ref = find(kind, cur, cur_vendor)
        if ref is None:
            if not chain:
                return None
            break
        data = _raw(ref.path)
        if not data:
            return None
        chain.append(data)
        cur, cur_vendor = data.get("inherits") or "", ref.vendor
    merged: dict[str, Any] = {}
    for layer in reversed(chain):
        merged.update(layer)
    merged.pop("inherits", None)
    merged["name"] = name
    merged["_vendor"] = vendor or (find(kind, name).vendor if find(kind, name) else "")
    return merged


# ------------------------------------------------------------------ value helpers
def first(v: Any) -> Any:
    return v[0] if isinstance(v, list) and v else v


def num(v: Any, default: float = 0.0, *, base: float | None = None) -> float:
    v = first(v)
    if v is None or v == "" or v == "nil":
        return default
    s = str(v).strip()
    try:
        if s.endswith("%"):
            return float(s[:-1]) / 100 * (base if base is not None else 1.0)
        return float(s)
    except ValueError:
        return default


def bed_of(machine: dict[str, Any]) -> list[float]:
    pts = machine.get("printable_area") or ["0x0", "256x0", "256x256", "0x256"]
    xs, ys = [], []
    for p in pts:
        try:
            x, y = (float(c) for c in str(p).split("x"))
        except ValueError:
            continue
        xs.append(x)
        ys.append(y)
    w = (max(xs) - min(xs)) if xs else 256.0
    d = (max(ys) - min(ys)) if ys else 256.0
    return [round(w, 1), round(d, 1), round(num(machine.get("printable_height"), 250.0), 1)]


def limits_of(machine: dict[str, Any]) -> dict[str, float]:
    """Machine limits that a justified profile must not exceed (mm/s, mm/s²)."""
    accel = num(machine.get("machine_max_acceleration_extruding"), 0) or num(machine.get("machine_max_acceleration_x"), 0)
    speed = min(
        [s for s in (num(machine.get("machine_max_speed_x"), 0), num(machine.get("machine_max_speed_y"), 0)) if s > 0] or [500.0]
    )
    return {
        "max_acceleration": accel or 10000.0,
        "max_speed": speed,
        "nozzle": num(machine.get("nozzle_diameter"), 0.4),
        "bed": bed_of(machine),  # type: ignore[dict-item]
    }


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@dataclass
class Printer:
    id: str
    name: str
    vendor: str
    model: str
    bed: list[float]
    nozzle: float


@lru_cache
def printers() -> list[Printer]:
    """All instantiable machine presets that resolve."""
    out: list[Printer] = []
    for name, refs in index()["machine"].items():
        ref = refs[0]
        raw = _raw(ref.path)
        if str(raw.get("instantiation", "")).lower() != "true":
            continue
        m = resolve("machine", name, ref.vendor)
        if not m or "printable_area" not in m:
            continue
        out.append(Printer(slug(name), name, ref.vendor, str(m.get("printer_model") or name), bed_of(m), num(m.get("nozzle_diameter"), 0.4)))
    return out


def printer_by(key: str | None) -> Printer | None:
    if not key:
        return None
    k = key.strip()
    for p in printers():
        if p.id == k or p.name == k or p.id == slug(k):
            return p
    return None


def machine(p: Printer) -> dict[str, Any]:
    return resolve("machine", p.name, p.vendor) or {}


def default_process(p: Printer) -> dict[str, Any] | None:
    m = machine(p)
    name = m.get("default_print_profile")
    if name:
        proc = resolve("process", name, p.vendor)
        if proc:
            return proc
    # fall back: any process compatible with this printer, prefer 0.20mm
    for pname, refs in index()["process"].items():
        if p.vendor not in {r.vendor for r in refs}:
            continue
        raw = _raw(next(r for r in refs if r.vendor == p.vendor).path)
        if p.name in (raw.get("compatible_printers") or []) and "0.20" in pname:
            return resolve("process", pname, p.vendor)
    return None


def _filament_type(f: dict[str, Any]) -> str:
    return str(first(f.get("filament_type")) or "").upper()


def filament_for(p: Printer, material: str = "PLA") -> dict[str, Any] | None:
    """A filament preset of the requested type that is meant for this printer."""
    mat = material.upper().strip()
    m = machine(p)
    for name in m.get("default_filament_profile") or []:
        f = resolve("filament", name, p.vendor)
        if f and _filament_type(f) == mat:
            return f
    # vendor filaments listing this printer explicitly: only generic or the maker's own
    # basic line; a random third-party brand is worse than the library's generic preset
    brand = p.model.split()[0].upper() if p.model else ""
    candidates: list[tuple[int, str]] = []
    for name, refs in index()["filament"].items():
        ref = next((r for r in refs if r.vendor == p.vendor), None)
        if ref is None:
            continue
        up = name.upper()
        if mat not in up.split() and f"{mat} " not in up and not up.endswith(mat):
            continue
        generic = "GENERIC" in up
        own_basic = brand and up.startswith(brand) and ("BASIC" in up or f"{brand} {mat} @" in up)
        if not (generic or own_basic):
            continue
        raw = _raw(ref.path)
        if p.name not in (raw.get("compatible_printers") or []):
            continue
        candidates.append((0 if generic else 1, name))
    for _, name in sorted(candidates):
        f = resolve("filament", name, p.vendor)
        if f and _filament_type(f) == mat:
            return f
    generic = resolve("filament", f"Generic {mat} @System", LIBRARY)
    return generic


# Orca build plates and the filament key holding the bed temperature for each.
PLATES = [
    ("Cool Plate", "cool_plate_temp"),
    ("Textured PEI Plate", "textured_plate_temp"),
    ("High Temp Plate", "hot_plate_temp"),
    ("Engineering Plate", "eng_plate_temp"),
    ("Supertack Plate", "supertack_plate_temp"),
]
DEFAULT_PLATE = "Cool Plate"


def plate_for(filament: dict[str, Any]) -> str | None:
    """Keep the default plate when the filament supports it, else the first one that does.
    None when the filament does not say (the slicer default is then fine)."""
    temps = {name: filament.get(key) for name, key in PLATES}
    if all(v is None for v in temps.values()):
        return None
    if num(temps.get(DEFAULT_PLATE), 0) > 0:
        return DEFAULT_PLATE
    for name, _ in PLATES:
        if num(temps.get(name), 0) > 0:
            return name
    return None
