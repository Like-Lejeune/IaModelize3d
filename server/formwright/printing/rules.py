"""Rule base for the justified print profile.

A rule fires only when its evidence kind is present (and passes the thresholds).
Each change says how to move one Orca setting: `to` an exact value, or keep it
`at_least` / `at_most` a bound. Untouched settings stay exactly as in the printer's
stock profile; "no change" is the default.
"""
from __future__ import annotations

from typing import Any

# Settings the profile may touch. type: int | num | percent | bool | enum.
# `limit` ties a numeric range to the machine: accel -> max_acceleration, speed -> max_speed.
SETTINGS: dict[str, dict[str, Any]] = {
    "wall_loops": {"file": "process", "type": "int", "min": 1, "max": 10},
    "top_shell_layers": {"file": "process", "type": "int", "min": 0, "max": 20},
    "bottom_shell_layers": {"file": "process", "type": "int", "min": 0, "max": 20},
    "sparse_infill_density": {"file": "process", "type": "percent", "min": 0, "max": 100},
    "sparse_infill_pattern": {"file": "process", "type": "enum", "options": ["crosshatch", "grid", "gyroid", "honeycomb", "cubic", "adaptivecubic", "lightning", "rectilinear", "zig-zag", "line"]},
    "outer_wall_acceleration": {"file": "process", "type": "num", "min": 200, "limit": "accel"},
    "inner_wall_acceleration": {"file": "process", "type": "num", "min": 200, "limit": "accel"},
    "default_acceleration": {"file": "process", "type": "num", "min": 200, "limit": "accel"},
    "travel_acceleration": {"file": "process", "type": "num", "min": 200, "limit": "accel"},
    "outer_wall_speed": {"file": "process", "type": "num", "min": 10, "limit": "speed"},
    "inner_wall_speed": {"file": "process", "type": "num", "min": 10, "limit": "speed"},
    "sparse_infill_speed": {"file": "process", "type": "num", "min": 10, "limit": "speed"},
    "travel_speed": {"file": "process", "type": "num", "min": 30, "limit": "speed"},
    "initial_layer_speed": {"file": "process", "type": "num", "min": 10, "max": 120},
    "bridge_speed": {"file": "process", "type": "num", "min": 5, "max": 120},
    "bridge_flow": {"file": "process", "type": "num", "min": 0.5, "max": 1.2},
    "enable_support": {"file": "process", "type": "bool"},
    "support_type": {"file": "process", "type": "enum", "options": ["normal(auto)", "tree(auto)"]},
    "support_threshold_angle": {"file": "process", "type": "int", "min": 0, "max": 90},
    "brim_type": {"file": "process", "type": "enum", "options": ["no_brim", "outer_only", "inner_only", "outer_and_inner", "auto_brim", "brim_ears"]},
    "brim_width": {"file": "process", "type": "num", "min": 0, "max": 20},
    "enable_overhang_speed": {"file": "process", "type": "bool"},
    "seam_position": {"file": "process", "type": "enum", "options": ["nearest", "aligned", "back", "random"]},
    "wall_generator": {"file": "process", "type": "enum", "options": ["classic", "arachne"]},
    "detect_thin_wall": {"file": "process", "type": "bool"},
    "ironing_type": {"file": "process", "type": "enum", "options": ["no ironing", "top", "topmost", "solid"]},
    "spiral_mode": {"file": "process", "type": "bool"},
    "elefant_foot_compensation": {"file": "process", "type": "num", "min": 0, "max": 0.5},
    "enable_prime_tower": {"file": "process", "type": "bool"},
    "only_one_wall_top": {"file": "process", "type": "bool"},
    "slow_down_layer_time": {"file": "filament", "type": "num", "min": 1, "max": 30},
    "slow_down_min_speed": {"file": "filament", "type": "num", "min": 5, "max": 60},
    "overhang_fan_speed": {"file": "filament", "type": "int", "min": 0, "max": 100},
    "fan_max_speed": {"file": "filament", "type": "int", "min": 0, "max": 100},
}

# Per-part settings for modifier volumes (applied by the agent as lib.part(..., {role: 'modifier', settings})).
PART_SETTINGS = {"wall_loops", "sparse_infill_density", "top_shell_layers", "bottom_shell_layers", "sparse_infill_pattern"}

WARPING_MATERIALS = {"ABS", "ASA", "PETG", "PC", "PA", "NYLON", "PP"}

# required: the change keeps the part printable at all, so a model may not remove it.
RULES: list[dict[str, Any]] = [
    {"id": "floating_supports", "evidence": "floating_island", "required": True,
     "changes": [{"key": "enable_support", "to": True}, {"key": "support_type", "to": "tree(auto)"}],
     "reason": "A region starts in mid-air (z {z0:.1f} mm); it cannot print without support."},
    {"id": "tall_thin_accel", "evidence": "tall_thin", "min": 4.0,
     "changes": [{"key": "outer_wall_acceleration", "at_most": 2000}, {"key": "inner_wall_acceleration", "at_most": 3000}],
     "reason": "Tall, narrow part (height/base {value:.1f}): hard wall moves make it wobble and shift layers."},
    {"id": "tall_thin_brim", "evidence": "tall_thin", "min": 6.0,
     "changes": [{"key": "brim_type", "to": "outer_only"}, {"key": "brim_width", "at_least": 5}],
     "reason": "Height/base {value:.1f}: a brim keeps it from tipping over."},
    {"id": "small_contact_brim", "evidence": "small_contact",
     "changes": [{"key": "brim_type", "to": "outer_only"}, {"key": "brim_width", "at_least": 5}],
     "reason": "First layer touches the bed with only {value:.0f} mm²: a brim adds grip."},
    {"id": "warp_brim", "evidence": "large_footprint", "materials": WARPING_MATERIALS,
     "changes": [{"key": "brim_type", "to": "outer_only"}, {"key": "brim_width", "at_least": 6}],
     "reason": "{material} on a {value:.0f} mm footprint tends to lift at the corners; a brim holds it down."},
    {"id": "overhang_slowdown", "evidence": "overhang", "min": 30,
     "changes": [{"key": "enable_overhang_speed", "to": True}, {"key": "overhang_fan_speed", "at_least": 100}],
     "reason": "{value:.0f} mm² of steep overhang (from z {z0:.1f} mm): slow down and full fan on overhangs."},
    {"id": "bridge_slow", "evidence": "long_bridge",
     "changes": [{"key": "bridge_speed", "at_most": 25}, {"key": "bridge_flow", "at_most": 0.9}],
     "reason": "Bridge spans {value:.1f} mm at z {z0:.1f}: slower, thinner bridge lines sag less."},
    {"id": "short_layer_cooling", "evidence": "short_layer_time",
     "changes": [{"key": "slow_down_layer_time", "at_least": 8}],
     "reason": "Some layers print in {value:.1f} s (z {z0:.1f}+): give each layer time to cool."},
    {"id": "thin_arachne", "evidence": "thin_features",
     "changes": [{"key": "wall_generator", "to": "arachne"}, {"key": "detect_thin_wall", "to": True}],
     "reason": "Walls thinner than two lines ({value:.1f} mm² of them): variable-width walls keep them."},
    {"id": "load_walls", "evidence": "functional_load",
     "changes": [{"key": "wall_loops", "at_least": 4}, {"key": "sparse_infill_density", "at_least": 30},
                 {"key": "top_shell_layers", "at_least": 5}, {"key": "bottom_shell_layers", "at_least": 4}],
     "reason": "The part carries load ({value}): strength lives in the perimeters, so add walls and infill."},
    {"id": "goal_strong", "evidence": "goal:strong",
     "changes": [{"key": "wall_loops", "at_least": 4}, {"key": "sparse_infill_density", "at_least": 35}, {"key": "sparse_infill_pattern", "to": "gyroid"}],
     "reason": "You asked for a strong print."},
    {"id": "goal_fast", "evidence": "goal:fast", "unless": ["functional_load", "goal:strong"],
     "changes": [{"key": "sparse_infill_density", "at_most": 10}, {"key": "wall_loops", "at_most": 2}],
     "reason": "You asked for speed and nothing here carries load."},
    {"id": "goal_cheap", "evidence": "goal:cheap", "unless": ["functional_load", "goal:strong"],
     "changes": [{"key": "sparse_infill_density", "at_most": 10}],
     "reason": "You asked for less plastic and nothing here carries load."},
    {"id": "goal_pretty", "evidence": "goal:pretty",
     "changes": [{"key": "outer_wall_speed", "at_most": 120}, {"key": "seam_position", "to": "back"}],
     "reason": "You asked for a nice surface: slower outer wall, seam hidden at the back."},
    {"id": "pretty_ironing", "evidence": "flat_top", "requires": ["goal:pretty"],
     "changes": [{"key": "ironing_type", "to": "top"}],
     "reason": "Large flat top surface and you want it pretty: ironing smooths it."},
    {"id": "goal_quiet", "evidence": "goal:quiet",
     "changes": [{"key": "outer_wall_speed", "at_most": 120}, {"key": "inner_wall_speed", "at_most": 150}, {"key": "travel_speed", "at_most": 250},
                 {"key": "default_acceleration", "at_most": 3000}, {"key": "outer_wall_acceleration", "at_most": 2000}, {"key": "inner_wall_acceleration", "at_most": 3000}],
     "reason": "You asked for a quiet print: lower speeds and accelerations."},
    {"id": "vase_mode", "evidence": "vase_eligible",
     "changes": [{"key": "spiral_mode", "to": True}],
     "reason": "One closed outline per layer and no top: spiral vase mode prints it as a single seamless wall."},
    {"id": "mating_ef", "evidence": "mating_faces",
     "changes": [{"key": "elefant_foot_compensation", "at_least": 0.15}],
     "reason": "Fitting faces touch the bed: compensate the squished first layer so the fit stays true."},
    {"id": "multicolor_tower", "evidence": "multicolor",
     "changes": [{"key": "enable_prime_tower", "to": True}],
     "reason": "{value} colors: a prime tower keeps color changes clean."},
    {"id": "tpu_slow", "evidence": "material:TPU",
     "changes": [{"key": "outer_wall_speed", "at_most": 40}, {"key": "inner_wall_speed", "at_most": 50}, {"key": "sparse_infill_speed", "at_most": 60}],
     "reason": "TPU is flexible and buckles in the extruder when pushed fast."},
]

PART_RULES: list[dict[str, Any]] = [
    {"id": "screw_zone", "evidence": "screw_boss", "part": "screw_zone",
     "changes": [{"key": "wall_loops", "to": 6}, {"key": "sparse_infill_density", "to": "100%"}],
     "reason": "{value} screw hole(s)/boss(es): solid plastic around them stops the screw from cracking the part. Add a modifier volume around each."},
]
