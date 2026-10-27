"""The designer's few-shot examples must build and print cleanly."""
import pytest

from formwright.agent import examples
from formwright.geom import GeomPool

OUTLINE = {"outlines": {"part": [[[70, 110], [140, 110], [140, 128], [88, 128], [88, 155], [70, 155]]]}}


@pytest.fixture
async def pool():
    p = GeomPool(1)
    yield p
    await p.close()


@pytest.mark.parametrize("name", ["SHELF_HOOK", "COPY_FROM_PHOTO", "LAMP_SHADE", "SMOOTH_BODY"])
async def test_example_builds_without_errors(pool, name):
    r = await pool.build(getattr(examples, name), {}, analyze="full", inputs=OUTLINE)
    errors = [i["message"] for i in r["checks"]["issues"] if i["severity"] == "error"]
    assert errors == []
    assert r["checks"]["stats"]["volume"] > 500
