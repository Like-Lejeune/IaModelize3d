"""The whole device in the Axo shop's cart: a kept example run packed for the workshop, sent to the partner route (answered here
through an httpx MockTransport) as a batch at the quote's price without delivery; a shop that does not say that price back
never gets the buyer, since it would sell the device at the price of its plastic."""
from __future__ import annotations

import io
import json
import zipfile
from email import message_from_bytes
from email.policy import HTTP

import httpx
import pytest

from formwright import catalog, db as dbmod, deviceapi, device_package, device_store, geom as geommod, pcb as pcbmod
from formwright.config import settings
from formwright.integrations import axo

DESIGN = "0123456789abcdef0123456789abcdef"
OLD = "fedcba9876543210fedcba9876543210"


def quote(pcb_version: int, program_version: int, qty: int = 5) -> dict:
    # the catalogue's live prices are not the point here: deviceapi.quote_for has its own tests
    lines = [{"key": "parts", "kzt": 30000}, {"key": "pcb", "kzt": 2000}, {"key": "case", "kzt": 15000}]
    return {
        "qty": qty, "pcb_version": pcb_version, "program_version": program_version, "board_mm": [46.0, 55.0], "usd_kzt": 520, "total_usd": 100.0,
        "groups": [{"key": "pcb", "usd": 4.0, "note": "", "data": {"boards": 5}}, {"key": "delivery", "usd": 3.85, "note": "", "data": {}}],
        "bom": [{"refs": ["U2"], "name": "BME280", "lcsc": "C92489", "url": None, "assembly": "smt", "qty": qty, "kind": "chip"},
                {"refs": ["DS1"], "name": "OLED", "lcsc": None, "url": "https://example.test/oled", "assembly": "hand", "qty": qty, "kind": "accessory"}],
        "in_order": ["U2: 1 x BME280", "DS1: 1 x OLED"], "drc_ok": True, "eta": "2026-11-20",
        "timeline": [{"key": "pcb_fab", "days": 5}, {"key": "pcb_ship", "days": 25}, {"key": "case_print", "days": 1}, {"key": "delivery", "days": 2}],
        "case": {"grams_each": 39.0, "minutes_each": 120.0},
        "cart": {"lines": lines, "price_kzt": sum(x["kzt"] for x in lines)},
    }


@pytest.fixture
async def env(tmp_path, monkeypatch):
    from formwright.app import app

    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    monkeypatch.setattr(settings(), "public_url", "https://fw.example")
    monkeypatch.setattr(settings(), "axo_api_url", "https://axo.example/api")
    monkeypatch.setattr(settings(), "axo_api_key", "k")
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    await dbmod.get_db()
    sent: list[httpx.Request] = []
    answer = {"price": 47000}

    def shop(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(201, json={"design_id": DESIGN, "add_url": f"https://axo.example/builder/formwright?add={DESIGN}", "price_kzt": answer["price"]})

    monkeypatch.setattr(axo, "_transport", httpx.MockTransport(shop))

    async def no_catalogue(code):  # no network here: the state of a device reads its board and document, not live prices
        raise catalog.CatalogError("offline")

    monkeypatch.setattr(catalog, "info", no_catalogue)
    monkeypatch.setattr(catalog, "easyeda", no_catalogue)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        p = (await c.post("/api/examples/device-weather", json={"lang": "en"})).json()
        s = (await c.get(f"/api/projects/{p['id']}/device")).json()
        pcb_version, program_version = s["pcb"]["version"], p["version"]

        async def fake_quote(project_id, qty):
            return quote(pcb_version, program_version, max(1, min(500, int(qty))))

        monkeypatch.setattr(deviceapi, "quote_for", fake_quote)
        yield {"c": c, "id": p["id"], "sent": sent, "answer": answer, "pcb": pcb_version}
    await dbmod.close_db()
    if geommod._pool:
        await geommod._pool.close()
        geommod._pool = None
    await pcbmod.close()


def parts(request: httpx.Request) -> dict:
    raw = b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.read()
    return {p.get_param("name", header="content-disposition"): p.get_payload(decode=True) for p in message_from_bytes(raw, policy=HTTP).iter_parts()}


async def test_the_device_goes_to_the_shop_as_a_batch_at_the_quotes_price(env):
    r = await env["c"].post(f"/api/projects/{env['id']}/device/axo-cart", json={"qty": 5})
    assert r.status_code == 200, r.text
    assert r.json() == {"url": f"https://axo.example/builder/formwright?add={DESIGN}", "design_id": DESIGN, "price_kzt": 47000, "qty": 5}
    got = parts(env["sent"][0])
    meta = json.loads(got["meta"])
    assert meta["device"]["qty"] == 5 and meta["device"]["price_kzt"] == 47000
    # delivery stays out: the shop adds its own, from this parcel
    assert [x["key"] for x in meta["device"]["lines"]] == ["parts", "pcb", "case"]
    assert meta["device"]["parcel_g"] > 5 * 39 and all(v > 0 for v in meta["device"]["parcel_mm"])
    # the fab and the print, without the courier's days the shop adds itself
    assert meta["device"]["lead_days"] == 31
    # the plastic of the whole batch, which is what the shop takes off its stock
    assert meta["weight_g"] == 195.0
    assert got["model"].startswith(b"PK")
    names = set(zipfile.ZipFile(io.BytesIO(got["bundle"])).namelist())
    assert {"README.md", "case/case.3mf", "pcb/gerbers.zip", "pcb/bom.csv", "pcb/cpl.csv", "device.json", "quote.json"} <= names
    assert any(n.startswith("firmware/") for n in names)


@pytest.mark.parametrize("said", [None, 2500])
async def test_a_shop_that_does_not_say_the_price_back_gets_no_buyer(env, said):
    # the storefront before devices ignores `device` and prices the case by its grams
    env["answer"]["price"] = said
    r = await env["c"].post(f"/api/projects/{env['id']}/device/axo-cart", json={"qty": 5})
    assert r.status_code == 502 and r.json()["code"] == "axo_no_device"
    assert "url" not in r.json()


async def test_replace_goes_on_the_link(env):
    r = await env["c"].post(f"/api/projects/{env['id']}/device/axo-cart", json={"qty": 5, "replace": OLD})
    assert r.json()["url"].endswith(f"&replace={OLD}")
    assert (await env["c"].post(f"/api/projects/{env['id']}/device/axo-cart", json={"qty": 5, "replace": "nope"})).status_code == 400


async def test_a_device_changed_after_its_board_is_not_sold(env):
    row = await device_store.latest(env["id"])
    doc = row["doc"]
    doc["nodes"] = [n for n in doc["nodes"] if n["id"] != "R1"]
    await device_store.save(env["id"], doc, author="user", summary="took R1 off")
    r = await env["c"].post(f"/api/projects/{env['id']}/device/axo-cart", json={"qty": 5})
    assert r.status_code == 409 and r.json()["code"] == "device_stale" and env["sent"] == []


async def test_a_device_without_firmware_is_not_sold(env):
    row = await device_store.latest(env["id"])
    doc = row["doc"]
    doc.pop("firmware")
    await device_store.save(env["id"], doc, author="user", summary="no firmware")
    r = await env["c"].post(f"/api/projects/{env['id']}/device/axo-cart", json={"qty": 5})
    assert r.status_code == 409 and r.json()["code"] == "no_firmware" and env["sent"] == []


async def test_the_package_downloads_without_the_shop(env, monkeypatch):
    monkeypatch.setattr(settings(), "axo_api_url", "")
    r = await env["c"].get(f"/api/projects/{env['id']}/device/package?qty=5")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    readme = zipfile.ZipFile(io.BytesIO(r.content)).read("README.md").decode("utf-8")
    assert "5 шт." in readme and "gerbers.zip" in readme and "OLED" in readme
    r = await env["c"].post(f"/api/projects/{env['id']}/device/axo-cart", json={"qty": 5})
    assert r.status_code == 503 and r.json()["code"] == "not_configured"


def test_a_bigger_batch_is_a_heavier_box_that_stays_close_to_a_cube():
    one, one_box = device_package.parcel(1, [46, 55], [56, 61, 16], 39, 1)
    many, many_box = device_package.parcel(27, [46, 55], [56, 61, 16], 39, 27)
    assert 27 * (one - device_package.BOX_G) < many + 1e-6 < 28 * one
    assert all(a <= b for a, b in zip(one_box, many_box))
    assert max(many_box) < 300
