"""Justified profile: rules need evidence, model suggestions are validated."""
from types import SimpleNamespace

import pytest

from formwright.printing import profile
from formwright.printing.profile import apply_diff, features, propose_with_report, rule_diff

BASE = {
    "material": "PLA",
    "process": {
        "wall_loops": "2", "sparse_infill_density": "15%", "outer_wall_acceleration": ["5000", "5000"], "inner_wall_acceleration": ["5000"],
        "enable_support": "0", "support_type": "normal(auto)", "bridge_speed": ["50"], "bridge_flow": "1", "top_shell_layers": "5",
        "bottom_shell_layers": "3", "outer_wall_speed": ["200"], "seam_position": "aligned", "elefant_foot_compensation": "0.15",
    },
    "filament": {"slow_down_layer_time": ["4"], "overhang_fan_speed": ["100"]},
}
LIMITS = {"max_acceleration": 10000, "max_speed": 500}

CHECKS = {
    "issues": [
        {"code": "floating_island", "severity": "error", "message": "island", "z": [20.0, 20.1], "value": 60},
        {"code": "long_bridge", "severity": "warn", "message": "bridge", "z": [40.0, 40.2], "value": 18.5},
        {"code": "short_layer_time", "severity": "info", "message": "short", "z": [140, 149], "value": 2.4},
    ],
    "stats": {"size": [30, 30, 150], "firstLayerArea": 400.0},
}


def by_key(diff):
    return {d["key"]: d for d in diff if not d.get("part")}


def test_no_evidence_no_change():
    assert features({}, {}, {}) == []
    assert rule_diff(BASE, [], LIMITS) == []


def test_features_from_checks_and_brief():
    ev = {e["id"]: e for e in features(CHECKS, None, {"load": "bags pull down", "fits": True, "screws": 2, "material": "petg"})}
    assert ev["tall_thin"]["value"] == pytest.approx(7.5)
    assert ev["floating_island"]["z0"] == 20.0
    assert ev["long_bridge"]["value"] == 18.5
    assert ev["short_layer_time"]["value"] == 2.4
    assert ev["functional_load"]["value"] == "bags pull down"
    assert {"mating_faces", "screw_boss", "material:PETG"} <= set(ev)


def test_rules_are_justified_and_keep_formats():
    ev = features(CHECKS, None, {})
    d = by_key(rule_diff(BASE, ev, LIMITS))
    assert d["enable_support"]["to"] == "1" and d["enable_support"]["evidence"] == ["floating_island"] and d["enable_support"]["required"]
    assert d["support_type"]["to"] == "tree(auto)"
    assert d["outer_wall_acceleration"]["value"] == ["2000", "2000"]  # list format preserved
    assert d["brim_type"]["to"] == "outer_only" and d["brim_type"]["from"] is None
    assert d["bridge_speed"]["value"] == ["25"] and d["bridge_flow"]["to"] == "0.9"
    assert d["slow_down_layer_time"]["file"] == "filament" and d["slow_down_layer_time"]["to"] == "8"
    for item in d.values():
        assert item["evidence"] and item["reason"]
    # top_shell_layers is already 5: a load rule would not change it
    d2 = by_key(rule_diff(BASE, features({}, {}, {"load": "yes"}), LIMITS))
    assert "top_shell_layers" not in d2 and d2["wall_loops"]["to"] == "4" and d2["sparse_infill_density"]["to"] == "30%"


def test_goals_and_conflicts():
    ev = features({}, {}, {"load": "yes"}) + [{"id": "goal:fast", "kind": "goal:fast", "value": "fast"}]
    d = by_key(rule_diff(BASE, ev, LIMITS))
    assert d["wall_loops"]["to"] == "4"  # load beats speed
    d_fast = by_key(rule_diff(BASE, [{"id": "goal:fast", "kind": "goal:fast", "value": "fast"}], LIMITS))
    assert d_fast["sparse_infill_density"]["to"] == "10%"


def test_machine_limits_clamp():
    slow = {"max_acceleration": 1500, "max_speed": 150}
    ev = features(CHECKS, None, {}) + [{"id": "goal:quiet", "kind": "goal:quiet", "value": "quiet"}]
    d = by_key(rule_diff(BASE, ev, slow))
    assert float(d["outer_wall_acceleration"]["to"]) <= 1500
    assert float(d["outer_wall_speed"]["to"]) <= 150


def test_part_rules_for_screws():
    diff = rule_diff(BASE, features({}, {}, {"screws": [1, 2]}), LIMITS)
    parts = [d for d in diff if d.get("part")]
    assert {p["key"] for p in parts} == {"wall_loops", "sparse_infill_density"}
    assert all(p["part"] == "screw_zone" and p["evidence"] == ["screw_boss"] for p in parts)
    proc, fil = apply_diff(BASE["process"], BASE["filament"], diff)
    assert proc["wall_loops"] == "2"  # part settings are not global


async def test_model_suggestions_are_validated(monkeypatch):
    suggestions = {
        "add": [
            {"key": "outer_wall_speed", "to": "50", "reason": "feels right", "evidence": ["vibes"]},  # unknown evidence
            {"key": "wall_loops", "to": "8", "reason": "x", "evidence": ["tall_thin"]},  # not decided by rules -> allowed? only if valid
            {"key": "not_a_setting", "to": "1", "reason": "x", "evidence": ["tall_thin"]},  # not whitelisted
            {"key": "travel_acceleration", "to": "50000", "reason": "x", "evidence": ["tall_thin"]},  # over machine limit
            {"key": "bridge_speed", "to": "10", "reason": "x", "evidence": ["long_bridge"]},  # already decided by rules
            {"key": "sparse_infill_pattern", "to": "gyroid", "reason": "stiffer for a tall part", "evidence": ["tall_thin"]},  # valid
        ],
        "drop": [
            {"key": "enable_support", "reason": "no", "evidence": ["floating_island"]},  # required
            {"key": "bridge_flow", "reason": "stock is fine", "evidence": []},  # no evidence
            {"key": "slow_down_layer_time", "reason": "only the last mm is small", "evidence": ["short_layer_time"]},  # valid drop
        ],
    }

    async def fake_json(meter, **kw):
        assert "allowed_settings" in kw["content"][0]["text"]
        return suggestions

    monkeypatch.setattr(profile, "meta", lambda: SimpleNamespace(json=fake_json))
    meter = SimpleNamespace(check=lambda *a: None)
    rep = await propose_with_report(meter, base=BASE, evidence=features(CHECKS, None, {}), goals=[], limits=LIMITS, model="muse-spark-1.3", use_llm=True)
    d = by_key(rep["diff"])
    assert "outer_wall_speed" not in d and "not_a_setting" not in d and "travel_acceleration" not in d
    assert d["bridge_speed"]["to"] == "25"  # rules win
    assert d["sparse_infill_pattern"]["source"] == "model" and d["sparse_infill_pattern"]["evidence"] == ["tall_thin"]
    assert d["wall_loops"]["to"] == "8" and d["wall_loops"]["source"] == "model"
    assert "enable_support" in d and "bridge_flow" in d and "slow_down_layer_time" not in d
    whys = {(r["action"], r["key"]): r["why"] for r in rep["rejected"]}
    assert "evidence" in whys[("add", "outer_wall_speed")]
    assert "not an allowed" in whys[("add", "not_a_setting")]
    assert "outside" in whys[("add", "travel_acceleration")]
    assert whys[("drop", "enable_support")] == "required for printability"
    assert "evidence" in whys[("drop", "bridge_flow")]


async def test_model_failure_falls_back_to_rules(monkeypatch):
    async def boom(meter, **kw):
        raise RuntimeError("api down")

    monkeypatch.setattr(profile, "meta", lambda: SimpleNamespace(json=boom))
    rep = await propose_with_report(SimpleNamespace(), base=BASE, evidence=features(CHECKS, None, {}), goals=[], limits=LIMITS, model="m")
    assert by_key(rep["diff"])["enable_support"]["to"] == "1"
