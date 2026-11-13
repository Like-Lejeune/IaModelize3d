"""The designer's harness: which tools a job gets, and the likeness feedback for copies of a photo."""
import base64

import numpy as np
import pytest

from iamodelize3d.agent.compare import silhouette_agreement, view_camera
from iamodelize3d.agent.tools import tools_for
from iamodelize3d.geom import GeomPool

CYLINDER = "return { params: {}, build: (p, lib) => lib.std.cyl(80, 100) };"
CONE = "return { params: {}, build: (p, lib) => lib.std.cyl(80, 100, { d2: 50 }) };"


def names(tools):
    return [t["name"] for t in tools]


def test_tools_fit_the_job():
    text = names(tools_for("household", photos=False, prints=False))
    assert "measure" not in text and "concept_images" not in text and "load_terrain" not in text
    assert {"write_program", "edit_program", "look", "dimensions", "ask_user", "propose_probe"} <= set(text)
    assert text[-1] == "finish"
    copy = names(tools_for("copy", photos=True, prints=True))
    assert {"measure", "fit_to_photo", "compare_print"} <= set(copy)
    assert "load_terrain" in names(tools_for("terrain", photos=False, prints=False))
    assert len(text) <= 13 and len(copy) <= 16


def test_silhouette_agreement_is_scale_free():
    m = np.zeros((300, 300), bool)
    m[50:250, 100:200] = True
    big = np.zeros((600, 600), bool)
    big[100:500, 200:400] = True
    s = silhouette_agreement(m, big)
    assert s["silhouette_iou"] > 0.97
    # a model whose top is wider than the photo's
    flare = m.copy()
    flare[50:110, 70:230] = True
    s = silhouette_agreement(m, flare)
    assert s["model_width_vs_photo"]["20% from top"] > 1.5
    assert s["model_width_vs_photo"]["80% from top"] == 1.0
    assert s["silhouette_iou"] < 0.9


@pytest.fixture
async def pool():
    p = GeomPool(1)
    yield p
    await p.close()


async def mask(pool, source, elevation):
    b = await pool.build(source, {}, analyze="fast")
    cam = view_camera(b["checks"]["stats"]["bbox"], elevation)
    r = await pool.render(source, {}, camera=cam)
    bits = np.unpackbits(np.frombuffer(base64.b64decode(r["mask"]), np.uint8))[: cam["width"] * cam["height"]]
    return bits.reshape(cam["height"], cam["width"]).astype(bool)


async def test_compare_view_tells_a_cone_from_a_cylinder(pool):
    cyl, cone = await mask(pool, CYLINDER, 15), await mask(pool, CONE, 15)
    assert silhouette_agreement(cyl, await mask(pool, CYLINDER, 15))["silhouette_iou"] > 0.99
    s = silhouette_agreement(cyl, cone)
    assert s["silhouette_iou"] < 0.9
    assert s["model_width_vs_photo"]["20% from top"] < 0.8  # the cone is narrow at the top
    # seen from higher up, the same cylinder shows its top ellipse: the view angle matters
    assert silhouette_agreement(cyl, await mask(pool, CYLINDER, 45))["silhouette_iou"] < 0.97
