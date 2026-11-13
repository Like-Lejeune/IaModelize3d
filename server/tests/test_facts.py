"""Dimension knowledge: a cached fact answers only a question about the same thing, a standard only when the
query names it. The queries are the ones that went wrong in real runs."""
import pytest

from iamodelize3d import db as dbmod
from iamodelize3d.config import settings
from iamodelize3d.knowledge import facts
from iamodelize3d.llm.client import CostMeter


@pytest.fixture
async def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(settings(), "data_dir", tmp_path)
    (tmp_path / "files").mkdir()
    await dbmod.close_db()
    db = await dbmod.get_db()
    for attribute, value in (("length", 164.1), ("width", 75.5), ("thickness", 8.5)):
        await facts.add_fact("Realme 8i", attribute, value, unit="mm", source_kind="search", source_url="https://www.realme.com/8i/specs")
    for subject in ("330ml Coca-Cola can - industry Standard 330ml can", "330ml Standard can - B211-1 DOME - SPEC001273"):
        await facts.add_fact(subject, "height", 115.2, unit="mm", source_kind="search", source_url="https://example.com/can")
        await facts.add_fact(subject, "body diameter", 66.3, unit="mm", source_kind="search", source_url="https://example.com/can")
    yield db
    await dbmod.close_db()


@pytest.mark.parametrize("query", [
    "iPhone 15 Pro thickness",
    "iPhone 15 Pro length width thickness camera",
    "park bench standard dimensions",
    "park bench standard dimensions length seat height width concrete",
    "Samsung Galaxy S23 width",
    "Xiaomi charger width",
    "500ml beer can diameter",
    "IKEA KALLAX shelf thickness",
    "GoPro Hero 12 mount width",
    "phone dimensions",
])
async def test_other_things_get_no_cached_numbers(seeded, query):
    assert await facts.find_facts(query) == []


async def test_the_same_thing_gets_its_cached_numbers(seeded):
    got = await facts.find_facts("Realme 8i thickness")
    assert {f["subject"] for f in got} == {"Realme 8i"} and {f["attribute"] for f in got} == {"length", "width", "thickness"}
    can = await facts.find_facts("330ml can diameter")
    assert can and all("330ml" in f["subject"] for f in can)


async def test_only_accepted_hits_count_as_used(seeded):
    await facts.find_facts("iPhone 15 Pro thickness")
    await facts.find_facts("Realme 8i width")
    rows = await seeded.all("SELECT subject, uses FROM facts")
    assert {r["subject"] for r in rows if r["uses"]} == {"Realme 8i"}


async def test_web_flag_bypasses_the_cache(seeded, monkeypatch):
    asked = []

    class Meta:
        async def search(self, meter, query, model=None):
            asked.append(query)
            return {"text": "Realme 8i: 164.1 x 75.5 x 8.5 mm", "sources": [{"url": "https://www.realme.com/8i/specs"}]}

        async def json(self, meter, **kw):
            return {"facts": [{"subject": "Realme 8i", "attribute": "weight", "value": 194, "unit": "g",
                               "source_url": "https://www.realme.com/8i/specs", "confidence": 0.9}], "notes": ""}

    monkeypatch.setattr(facts, "meta", lambda: Meta())
    cached = await facts.search_dimensions(CostMeter(), "Realme 8i thickness")
    assert cached["from_cache"] and not asked
    fresh = await facts.search_dimensions(CostMeter(), "Realme 8i thickness", force_web=True)
    assert not fresh["from_cache"] and len(asked) == 1 and fresh["facts"][0]["attribute"] == "weight"


def keys(query: str) -> set[tuple[str, str]]:
    return {(h["table"], h["key"]) for h in facts.lookup_standard(query)}


@pytest.mark.parametrize("query, absent", [
    ("garden hose 1/2 inch outer diameter", {("pipe_threads_bsp", "1"), ("pipe_threads_bsp", "1/2")}),
    ("standard aluminum soda can 330ml 12oz diameter height", {("pipe_threads_bsp", "1")}),
    ("phone case for samsung a52", {("references", "A5")}),
    ("phone case for samsung a52 thickness", {("references", "A5")}),
    ("AA battery", {("references", "AAA battery")}),
    ("wall mount for a 10 inch tablet", {("pipe_threads_bsp", "1")}),
    ("M2.5 standoff", {("screws", "M2")}),
    ("BMW M3 badge", {("screws", "M3"), ("metric_coarse_pitch", "M3")}),
])
def test_standards_do_not_match_inside_other_words(query, absent):
    assert not keys(query) & absent


def test_standards_still_answer_what_they_name():
    assert ("screws", "M3") in keys("M3 heat-set insert hole")
    assert {("screws", "M3"), ("metric_coarse_pitch", "M3")} <= keys("M3 screw")
    assert ("screws", "M2.5") in keys("M2.5 screw")
    assert keys("1/2 BSP pipe thread") >= {("pipe_threads_bsp", "1/2")} and ("pipe_threads_bsp", "1") not in keys("1/2 BSP pipe thread")
    assert ("pipe_threads_bsp", "1") in keys("1 inch pipe thread")
    assert ("bearings", "608") in keys("608 bearing")
    assert ("references", "A4") in keys("A4 sheet") and ("references", "A4") in keys("A4")
    assert ("references", "AA battery") in keys("AA battery holder")
    assert ("lamp_sockets", "E27") in keys("E27 lamp holder outer diameter")
    assert ("mounts", "VESA 100") in keys("VESA 100 mount") and ("mounts", "VESA 75") not in keys("VESA 100 mount")
    assert ("fits", "print_in_place") in keys("print in place hinge")
    hits = facts.lookup_standard("M3 screw")
    assert {h["match"] for h in hits} == {"exact"}


def test_a_query_that_is_only_part_of_a_key_is_partial():
    hits = facts.lookup_standard("VESA")
    assert {h["key"] for h in hits} == {"VESA 75", "VESA 100", "VESA 200"} and {h["match"] for h in hits} == {"partial"}


async def test_a_cached_facts_source_is_a_web_address_or_nothing(seeded):
    """Every later run's page links a fact's source: a 'javascript:' one (from a search result's text) is not kept."""
    for url, kept in (("javascript:alert(1)", None), ("realme.com/specs", None), ("HTTPS://www.realme.com/x", "HTTPS://www.realme.com/x")):
        row = await facts.add_fact("Realme 9", "width", 73.3, unit="mm", source_kind="search", source_url=url)
        assert row["source_url"] == kept, url
