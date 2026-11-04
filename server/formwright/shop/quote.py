"""Quotes for printed spare parts: material, grams, print time, price with margin, delivery ETA.

Two stages, because the kernel's own estimate is fast but rough:
  instant  - from the build's checks.stats (estGrams/estMinutes) times a calibration factor, shown as a range;
  firm     - from an OrcaSlicer run of the pinned version on the assigned printer profile (median 12 s).
Calibration (the same 17 models from the local DB, PLA, Orca default process, 2026-10-30):
  Bambu Lab A1 0.4 (the farm's printer)  Orca/kernel grams median 1.10, range 0.97-1.77; minutes median 1.44, range 0.81-3.55
  Bambu X1C 0.4                          Orca/kernel grams median 1.12, range 0.69-1.47; minutes median 1.15, range 0.66-3.14
  (the A1 bedslinger prints the same file about 23 % slower; kernel MAPE 11 % on grams, 34 % on minutes)
So the instant price is never binding: it is a range, and the order can be paid only on a firm quote.

Money: the farm (Axo, Kazakhstan) prices in tenge. Every amount also comes in US dollars at a fixed demo rate
(FW_USD_KZT, default 520 KZT per USD) for readers outside Kazakhstan; the tenge figure is the binding one.
The tariff is the prototype's USD tariff at 520 KZT/USD, rounded to tenge amounts a price tag would show.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from formwright.config import REPO_DIR

# Orca/kernel ratios as measured: (the A1's median, low, high); the band covers every calibration
# point of both printers (tests/fixtures/shop/calibration.json and calibration_a1.json)
KERNEL_G = (1.10, 0.69, 1.78)
KERNEL_MIN = (1.44, 0.66, 3.55)


class ShopSettings(BaseSettings):
    """Shop settings, read like formwright.config.Settings (FW_ prefix, the same .env files)."""
    model_config = SettingsConfigDict(env_file=(REPO_DIR.parent / ".env", REPO_DIR / ".env"), env_prefix="FW_", extra="ignore")

    usd_kzt: float = 520.0  # tenge per US dollar, for the USD figures next to every price
    # the farm's Orca preset when no farm printer is registered yet (Axo prints on a Bambu Lab A1)
    farm_preset: str = "bambu-lab-a1-0-4-nozzle"


@lru_cache
def shop_settings() -> ShopSettings:
    return ShopSettings()


@dataclass(frozen=True)
class Material:
    kzt_per_kg: float
    density: float  # g/cm3, same table as printing/service.py DENSITY


@dataclass(frozen=True)
class Tariff:
    """Every number here is a business assumption, overridable per deployment (env or admin page)."""
    currency: str = "KZT"
    materials: dict[str, Material] = field(default_factory=lambda: {
        "PLA": Material(9000.0, 1.24), "PETG": Material(10000.0, 1.27), "ASA": Material(13500.0, 1.07), "TPU": Material(16500.0, 1.21),
    })
    machine_per_h: float = 150.0          # A1/P1S-class printer ~250 000 KZT over ~4000 h + maintenance + ~0.12 kWh
    handling_per_order: float = 800.0     # plate swap, support removal, QC photo, packing: ~10 min
    handling_per_extra_unit: float = 130.0
    packaging: float = 300.0
    failure_rate: float = 0.07            # reprints and purge waste, priced into every unit
    margin: dict[str, float] = field(default_factory=lambda: {"consumer": 0.65, "repair_shop": 0.50})
    min_unit: dict[str, float] = field(default_factory=lambda: {"consumer": 2990.0, "repair_shop": 1990.0})
    # first print of a part that is not in the catalog yet: measurement, design checks, critic, a probe if needed
    new_part_fee: dict[str, float] = field(default_factory=lambda: {"consumer": 2000.0, "repair_shop": 1000.0})
    royalty_share: float = 0.10           # of the parts subtotal, to the owner of a public listing
    printers_online: int = 1
    hours_per_day: float = 18.0
    qc_hours: float = 2.0
    # (price, days): a city courier in Almaty or Astana, Kazpost elsewhere
    delivery: dict[str, tuple[float, int]] = field(default_factory=lambda: {
        "pickup": (0.0, 0), "courier": (2000.0, 1), "post": (1500.0, 4),
    })


DEFAULT = Tariff()
MATERIALS = tuple(DEFAULT.materials)
DELIVERY = tuple(DEFAULT.delivery)


def _round_price(x: float) -> float:
    """Tenge prices end in 90 (whole tens below 1000 KZT)."""
    if x < 1000:
        return float(math.ceil(x / 10) * 10)
    up = math.ceil(x / 100) * 100
    return float(up - 10 if up - 10 >= x else up + 90)


def usd(kzt: float, rate: float | None = None) -> float:
    return round(kzt / (rate or shop_settings().usd_kzt), 2)


def unit_cost(grams: float, minutes: float, material: str, t: Tariff = DEFAULT) -> dict[str, float]:
    m = t.materials.get(material.upper(), t.materials["PLA"])
    mat = grams * m.kzt_per_kg / 1000
    machine = minutes / 60 * t.machine_per_h
    return {"material": round(mat, 2), "machine": round(machine, 2)}


def price(*, grams: float, minutes: float, material: str = "PLA", quantity: int = 1, customer: str = "consumer",
          new_part: bool = True, delivery: str = "courier", listing_royalty: bool = False, queue_hours: float = 0.0,
          printers: int | None = None, today: dt.date | None = None, rate: float | None = None, t: Tariff = DEFAULT) -> dict[str, Any]:
    """Price breakdown for `quantity` copies of one part. Deterministic: the same inputs give the same quote."""
    q = max(1, int(quantity))
    rate = rate or shop_settings().usd_kzt
    u = unit_cost(grams, minutes, material, t)
    variable = (u["material"] + u["machine"]) * q
    handling = t.handling_per_order + t.handling_per_extra_unit * (q - 1)
    cost = (variable + handling + t.packaging) / (1 - t.failure_rate)
    margin = t.margin.get(customer, t.margin["consumer"])
    unit_price = _round_price(max(t.min_unit.get(customer, t.min_unit["consumer"]), cost / q / (1 - margin)))
    parts = round(unit_price * q, 2)
    fee = t.new_part_fee.get(customer, t.new_part_fee["consumer"]) if new_part else 0.0
    ship, ship_days = t.delivery.get(delivery, t.delivery["courier"])
    total = round(parts + fee + ship, 2)
    royalty = round(parts * t.royalty_share, 2) if listing_royalty else 0.0
    # ETA: the queue ahead plus this job, spread over the printers online, plus QC
    print_h = minutes * q / 60
    farm_h_per_day = max(1, printers or t.printers_online) * t.hours_per_day
    prod_days = math.ceil((queue_hours + print_h + t.qc_hours) / farm_h_per_day * 10) / 10
    today = today or dt.date.today()
    ready = today + dt.timedelta(days=math.ceil(prod_days))
    arrive = ready + dt.timedelta(days=ship_days)
    gross = parts + fee - cost - royalty
    return {
        "currency": t.currency,
        "quantity": q,
        "material": material.upper(),
        "grams_each": round(grams, 1),
        "minutes_each": round(minutes, 1),
        "unit_price": unit_price,
        "parts": parts,
        "new_part_fee": fee,
        "delivery": {"method": delivery, "price": ship, "days": ship_days},
        "total": total,
        "usd": {"rate": rate, "unit_price": usd(unit_price, rate), "parts": usd(parts, rate), "new_part_fee": usd(fee, rate),
                "delivery": usd(ship, rate), "total": usd(total, rate)},
        "cost": {"material": round(u["material"] * q, 2), "machine": round(u["machine"] * q, 2), "handling": round(handling, 2),
                 "packaging": t.packaging, "failure_allowance": round(cost - (variable + handling + t.packaging), 2),
                 "total": round(cost, 2)},
        "royalty": royalty,
        "gross_profit": round(gross, 2),
        "gross_margin": round(gross / (parts + fee), 3) if parts + fee else 0.0,
        "eta": {"production_days": prod_days, "ready_by": ready.isoformat(), "arrive_by": arrive.isoformat()},
    }


# what a customer never sees of a quote: the farm's costs and margin
INTERNAL = ("cost", "royalty", "gross_profit", "gross_margin")


def instant(stats: dict[str, Any], **kw: Any) -> dict[str, Any]:
    """From the kernel's checks.stats: a calibrated point estimate and a low-high band. Not payable."""
    g, m = float(stats.get("estGrams") or 0), float(stats.get("estMinutes") or 0)
    if g <= 0:
        raise ValueError("no mass estimate in checks.stats")
    mid = price(grams=g * KERNEL_G[0], minutes=m * KERNEL_MIN[0], **kw)
    lo = price(grams=g * KERNEL_G[1], minutes=m * KERNEL_MIN[1], **kw)
    hi = price(grams=g * KERNEL_G[2], minutes=m * KERNEL_MIN[2], **kw)
    rate = mid["usd"]["rate"]
    return {"source": "kernel", "binding": False, **mid, "range": {
        "total": [lo["total"], hi["total"]], "total_usd": [usd(lo["total"], rate), usd(hi["total"], rate)],
        "grams_each": [lo["grams_each"], hi["grams_each"]], "minutes_each": [lo["minutes_each"], hi["minutes_each"]]}}


def firm(slice_result: dict[str, Any], **kw: Any) -> dict[str, Any]:
    """From printing.service.slice(): Orca's grams and minutes for the exact file that will be printed."""
    s = slice_result.get("stats") or {}
    if not s.get("grams") or not s.get("minutes"):
        raise ValueError("slice has no grams/minutes")
    material = slice_result.get("material") or kw.pop("material", "PLA")
    kw.pop("material", None)
    out = price(grams=float(s["grams"]), minutes=float(s["minutes"]), material=material, **kw)
    return {"source": "orca", "binding": True, **out, "slice_id": slice_result.get("id"), "printer": slice_result.get("printer"),
            "supports": bool(s.get("supports")), "slice_seconds": s.get("slice_seconds"), "files": slice_result.get("files"),
            "warnings": s.get("warnings", [])}


def manual(grams: float, minutes: float, **kw: Any) -> dict[str, Any]:
    """An operator's quote when no slicer runs on this server (grams and minutes from their own slicer)."""
    return {"source": "operator", "binding": True, **price(grams=grams, minutes=minutes, **kw)}


