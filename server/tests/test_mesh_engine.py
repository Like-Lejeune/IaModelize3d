"""The mesh engine through the sandboxed Node worker and the agent's mesh tools."""
import base64
import json

import pytest

from iamodelize3d.agent.tools import is_mesh_doc, mesh_markers, op_anchor, tools_for
from iamodelize3d.geom import GeomError, GeomPool

DOC = {
    "engine": "mesh", "meta": {"title": "pebble cat"}, "symmetry": "x",
    "params": {"height": {"value": 40, "min": 20, "max": 80, "unit": "mm"}},
    "ops": [
        {"id": "body", "op": "clay", "smooth": 6, "shapes": [{"shape": "ellipsoid", "at": [0, 0, 14], "size": [26, 30, 28]},
                                                            {"shape": "sphere", "at": [0, -6, 30], "d": 18}]},
        {"id": "ear", "op": "clay", "blend": 2, "shapes": [{"shape": "cone", "d1": 7, "d2": 1.5, "h": 7, "at": [5, -6, 40]}]},
        {"id": "nose", "op": "sculpt", "brush": "grab", "at": [0, -15, 30], "radius": 4, "dir": [0, -1, 0], "strength": 1.5},
        {"id": "base", "op": "base", "depth": 1},
        {"id": "size", "op": "transform", "fit": {"height": "$height"}},
    ],
}


@pytest.fixture
async def pool():
    p = GeomPool(1)
    yield p
    await p.close()


async def test_mesh_document_builds_renders_and_inspects_in_the_sandbox(pool):
    src = json.dumps(DOC)
    r = await pool.build(src, {"height": 50}, analyze="full")
    assert r["ok"] and abs(r["checks"]["stats"]["size"][2] - 50) < 0.6
    assert r["paramSpecs"]["height"]["value"] == 40
    sheet = await pool.render(src, {"height": 50}, view="sheet", tile=160, markers=[{"at": [0, -15, 30], "label": "3 nose"}])
    assert len(base64.b64decode(sheet["png"])) > 1000
    out = await pool.inspect(src, {"height": 50}, [{"op": "surface", "from": "front", "points": [[0, 25], [60, 25]]}, {"op": "extremes"}])
    front, ext = out["results"]
    assert front["hits"][0]["hit"] is not None and front["hits"][0]["normal"][1] < -0.5  # the front faces -Y
    assert front["hits"][1]["hit"] is None
    assert ext["points"]["+z"][2] > 45


async def test_mesh_document_errors_name_the_op(pool):
    bad = {**DOC, "ops": DOC["ops"][:1] + [{"id": "oops", "op": "sculpt", "brush": "draw", "radius": 3}]}
    with pytest.raises(GeomError, match=r"op 2 \(oops\).*at is required"):
        await pool.build(json.dumps(bad), {}, analyze="none")


def test_markers_and_tools():
    assert is_mesh_doc(json.dumps(DOC)) and not is_mesh_doc("return { build: () => 1 }")
    assert op_anchor(DOC["ops"][2], {}) == [0, -15, 30]
    marks = mesh_markers(DOC, {"nose", "ear"}, {})
    assert [m["label"] for m in marks] == ["2 ear", "3 nose"]
    # "$name" positions resolve from param specs
    assert op_anchor({"op": "sculpt", "at": [0, "$y", 3]}, {"y": -4}) == [0, -4, 3]
    names = [t["name"] for t in tools_for("stylize", photos=False, prints=False, engine="mesh")]
    assert names[:2] == ["mesh_write", "mesh_edit"] and "write_program" in names
    assert "mesh_write" not in [t["name"] for t in tools_for("household", photos=False, prints=False)]


async def test_empty_mesh_edit_is_refused():
    from iamodelize3d.agent.tools import DesignState, _mesh_edit

    state = DesignState(pack="stylize", source=json.dumps(DOC))
    r, images = await _mesh_edit(None, state, {"summary": "details"})  # type: ignore[arg-type]
    assert r["ok"] is False and "nothing to change" in r["error"] and not images
