"""The parametric models the demo designer (scripts/g1_demo.py) draws, without any model call: real programs for the
geometry kernel (the format of agent/prompts.py), each with the question it asks first and how the answer sets its
parameters. Demo only: the real designer writes its own programs."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

BOX = r"""
const meta = { title: 'Boîte de rangement', pack: 'household' };
const params = {
  width:    { value: 120, min: 30, max: 220, step: 1, unit: 'mm', label: 'Largeur', source: 'user', group: 'Dimensions' },
  depth:    { value: 80, min: 30, max: 220, step: 1, unit: 'mm', label: 'Profondeur', source: 'user', group: 'Dimensions' },
  height:   { value: 50, min: 15, max: 150, step: 1, unit: 'mm', label: 'Hauteur', source: 'user', group: 'Dimensions' },
  wall:     { value: 2.4, min: 1.2, max: 5, step: 0.2, unit: 'mm', label: 'Épaisseur des parois', source: 'design', group: 'Solidité' },
  radius:   { value: 6, min: 0, max: 20, step: 0.5, unit: 'mm', label: 'Arrondi des coins', source: 'design', group: 'Forme' },
  dividers: { value: 0, min: 0, max: 4, kind: 'int', label: 'Séparations', source: 'design', group: 'Forme' },
};
function build(p, lib) {
  const { std } = lib;
  const r = Math.max(0, Math.min(p.radius, p.width / 2 - 1, p.depth / 2 - 1));
  const outer = std.box([p.width, p.depth, p.height], { r });
  const inner = std.box([p.width - 2 * p.wall, p.depth - 2 * p.wall, p.height], { r: Math.max(0, r - p.wall) }).translate([0, 0, p.wall]);
  let body = outer.subtract(inner);
  for (let i = 1; i <= p.dividers; i++) {
    const x = -p.width / 2 + (i * p.width) / (p.dividers + 1);
    body = body.add(std.box([p.wall, p.depth - p.wall, p.height * 0.85]).translate([x, 0, 0]));
  }
  return body;
}
return { meta, params, build };
"""

STAND = r"""
const meta = { title: 'Support incliné', pack: 'household' };
const params = {
  width:  { value: 70, min: 40, max: 200, step: 1, unit: 'mm', label: 'Largeur', source: 'design', group: 'Dimensions' },
  angle:  { value: 65, min: 45, max: 80, step: 1, unit: '°', label: 'Inclinaison', source: 'user', group: 'Dimensions' },
  back:   { value: 90, min: 50, max: 180, step: 1, unit: 'mm', label: 'Hauteur du dossier', source: 'design', group: 'Dimensions' },
  slot:   { value: 12, min: 6, max: 20, step: 0.5, unit: 'mm', label: "Épaisseur de l'appareil (avec coque)", source: 'user', group: 'Ajustement' },
  lip:    { value: 12, min: 6, max: 30, step: 1, unit: 'mm', label: 'Hauteur du rebord', source: 'design', group: 'Ajustement' },
  t:      { value: 4, min: 2.5, max: 8, step: 0.5, unit: 'mm', label: 'Épaisseur', source: 'design', group: 'Solidité' },
};
function build(p, lib) {
  const { std, M } = lib;
  const a = (p.angle * Math.PI) / 180;
  const reach = p.back * Math.cos(a);
  const depth = p.slot + 2 * p.t + reach + 10;
  const x0 = depth / 2;                       // the front edge
  const base = std.box([depth, p.width, p.t]);
  const lip = std.box([p.t, p.width, p.lip]).translate([x0 - p.t / 2, 0, 0]);
  const pivot = x0 - p.t - p.slot;            // where the back plate meets the base
  const back = M.cube([p.t, p.width, p.back]).translate([-p.t, -p.width / 2, 0]).rotate([0, -(90 - p.angle), 0]).translate([pivot, 0, 0]);
  // a brace under the back plate, from the rear of the base to the middle of the plate
  const mid = [pivot - (p.back / 2) * Math.cos(a), p.back / 2 * Math.sin(a)];
  const brace = M.hull([
    M.cube([p.t, p.width * 0.4, p.t]).translate([-depth / 2, -p.width * 0.2, 0]),
    M.cube([p.t, p.width * 0.4, p.t]).translate([mid[0] - p.t, -p.width * 0.2, mid[1] - p.t]),
  ]);
  const body = M.union([base, lip, back, brace]).trimByPlane([0, 0, 1], 0);
  // the slanted top of the back plate ends in a knife edge no printer lays down: cut it flat 1 mm lower
  const top = body.boundingBox().max[2];
  return body.trimByPlane([0, 0, -1], -(top - 1));
}
return { meta, params, build };
"""

HOOK = r"""
const meta = { title: 'Crochet mural', pack: 'household' };
const params = {
  width:  { value: 24, min: 12, max: 60, step: 1, unit: 'mm', label: 'Largeur', source: 'design', group: 'Dimensions' },
  plate:  { value: 70, min: 40, max: 140, step: 1, unit: 'mm', label: 'Hauteur de la plaque', source: 'design', group: 'Dimensions' },
  reach:  { value: 45, min: 20, max: 120, step: 1, unit: 'mm', label: 'Profondeur du crochet', source: 'user', group: 'Dimensions' },
  tip:    { value: 18, min: 6, max: 40, step: 1, unit: 'mm', label: 'Hauteur de la pointe', source: 'design', group: 'Dimensions' },
  t:      { value: 5, min: 3, max: 10, step: 0.5, unit: 'mm', label: 'Épaisseur', source: 'design', group: 'Solidité' },
  screw:  { value: 4, min: 3, max: 6, step: 0.5, unit: 'mm', label: 'Diamètre des vis', source: 'standard', group: 'Fixation' },
};
function build(p, lib) {
  const { std, CS } = lib;
  // the hook lies on its side to print: its J profile in XY, extruded across its width
  const profile = CS.union([
    CS.square([p.t, p.plate]),
    CS.square([p.reach + p.t, p.t]),
    CS.square([p.t, p.tip + p.t]).translate([p.reach, 0]),
  ]);
  let body = profile.extrude(p.width);
  for (const y of [p.plate * 0.55, p.plate * 0.85]) body = body.subtract(std.holeH(p.screw, p.t * 3, { at: [p.t / 2, y, p.width / 2], dir: 'x' }));
  return body;
}
return { meta, params, build };
"""

KNOB = r"""
const meta = { title: 'Molette de remplacement', pack: 'household' };
const params = {
  d:      { value: 32, min: 15, max: 70, step: 0.5, unit: 'mm', label: 'Diamètre', source: 'user', group: 'Dimensions' },
  h:      { value: 16, min: 8, max: 40, step: 0.5, unit: 'mm', label: 'Hauteur', source: 'user', group: 'Dimensions' },
  shaft:  { value: 6, min: 3, max: 10, step: 0.1, unit: 'mm', label: "Diamètre de l'axe", source: 'user', group: 'Ajustement' },
  flat:   { value: 4.5, min: 2, max: 10, step: 0.1, unit: 'mm', label: 'Cote sur le méplat', source: 'user', group: 'Ajustement' },
  depth:  { value: 12, min: 5, max: 35, step: 0.5, unit: 'mm', label: "Profondeur de l'axe", source: 'user', group: 'Ajustement' },
  ridges: { value: 18, min: 0, max: 40, kind: 'int', label: 'Stries de préhension', source: 'design', group: 'Forme' },
};
function build(p, lib) {
  const { std, M } = lib;
  let body = std.cyl(p.d, p.h, { d2: p.d * 0.92 });
  for (let i = 0; i < p.ridges; i++) {
    const a = (360 * i) / p.ridges;
    body = body.subtract(M.cylinder(p.h * 2, 1.1, 1.1, 12).rotate([0, 0, 0]).translate([p.d / 2 + 0.3, 0, -1]).rotate([0, 0, a]));
  }
  // a D-shaped bore from below, with the printer's clearance
  const bore = std.comp(p.shaft);
  const dShaft = M.cylinder(p.depth, bore / 2, bore / 2, 48).subtract(M.cube([bore, bore, p.depth * 2]).translate([p.flat - bore / 2 + std.fit('snug') / 2, -bore / 2, -1]));
  return body.subtract(dShaft.translate([0, 0, -0.01]));
}
return { meta, params, build };
"""

CUP = r"""
const meta = { title: 'Pot', pack: 'household' };
const params = {
  d:      { value: 75, min: 30, max: 160, step: 1, unit: 'mm', label: 'Diamètre', source: 'design', group: 'Dimensions' },
  h:      { value: 100, min: 30, max: 200, step: 1, unit: 'mm', label: 'Hauteur', source: 'design', group: 'Dimensions' },
  wall:   { value: 2.4, min: 1.2, max: 5, step: 0.2, unit: 'mm', label: 'Épaisseur des parois', source: 'design', group: 'Solidité' },
  sides:  { value: 0, min: 0, max: 12, kind: 'int', label: 'Facettes (0 = rond)', source: 'design', group: 'Forme' },
  twist:  { value: 0, min: 0, max: 90, step: 5, unit: '°', label: 'Torsion', source: 'design', group: 'Forme' },
};
function build(p, lib) {
  const { std } = lib;
  const outline = p.sides >= 3 ? std.ngon(p.sides, p.d) : std.circle(p.d);
  const outer = std.extrude(outline, p.h, { twist: p.twist });
  const inner = std.extrude(outline.offset(-p.wall, 'Round'), p.h, { twist: p.twist }).translate([0, 0, p.wall]);
  return outer.subtract(inner);
}
return { meta, params, build };
"""


def plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


# key -> (program, words that pick it, the first question, its options, what each option sets)
DESIGNS: dict[str, dict[str, Any]] = {
    "box": {"source": BOX, "words": ("boite", "rangement", "bac", "box", "organis", "tiroir", "couvercle"),
            "ask": "Quelle taille vous faut-il (extérieur) ?",
            "options": {"120 × 80 × 50 mm": {"width": 120, "depth": 80, "height": 50},
                        "200 × 150 × 80 mm": {"width": 200, "depth": 150, "height": 80},
                        "80 × 80 × 40 mm, avec 2 séparations": {"width": 80, "depth": 80, "height": 40, "dividers": 2}}},
    "stand": {"source": STAND, "words": ("support", "telephone", "tablette", "stand", "phone", "smartphone"),
              "ask": "Pour quel appareil, et quelle épaisseur avec sa coque ?",
              "options": {"Téléphone, environ 10 mm": {"width": 70, "slot": 11, "back": 90},
                          "Tablette 10 pouces, environ 9 mm": {"width": 150, "slot": 10, "back": 140, "t": 5},
                          "Téléphone avec coque épaisse, 15 mm": {"width": 75, "slot": 16, "back": 95}}},
    "hook": {"source": HOOK, "words": ("crochet", "accroch", "hook", "patere", "suspendre"),
             "ask": "Que doit-il porter ?",
             "options": {"Un casque audio": {"reach": 45, "width": 24, "t": 5},
                         "Des clés": {"reach": 25, "width": 14, "t": 4, "plate": 50},
                         "Un sac lourd": {"reach": 60, "width": 35, "t": 8, "screw": 5}}},
    "knob": {"source": KNOB, "words": ("molette", "bouton", "knob", "poignee de reglage", "potentiometre"),
             "ask": "Quel est le diamètre de l'axe sur lequel elle s'enfonce ?",
             "options": {"6 mm avec un méplat (axe en D)": {"shaft": 6, "flat": 4.5},
                         "4 mm avec un méplat": {"shaft": 4, "flat": 3},
                         "Je ne sais pas, je mesure et je vous dis": {}}},
    "cup": {"source": CUP, "words": ("pot", "stylo", "gobelet", "cup", "vase", "cache-pot"),
            "ask": "Quelle forme préférez-vous ?",
            "options": {"Rond et simple": {"sides": 0, "twist": 0}, "Hexagonal": {"sides": 6, "twist": 0},
                        "Hexagonal torsadé": {"sides": 6, "twist": 45}}},
}


def pick(text: str) -> str:
    t = plain(text)
    for key, d in DESIGNS.items():
        if any(w in t for w in d["words"]):
            return key
    return "box"


def defaults(key: str) -> dict[str, Any]:
    """The program's own default values, read from its params block."""
    out: dict[str, Any] = {}
    for name, value in re.findall(r"^\s*(\w+):\s*\{ value: ([\d.]+)", DESIGNS[key]["source"], re.M):
        out[name] = float(value) if "." in value else int(value)
    return out


NUMBER = r"(\d+(?:[.,]\d+)?)\s*(?:mm|millim)"
WHICH = (("larg", "width"), ("profond", "depth"), ("haut", "height"), ("diam", "d"), ("epais", "t"), ("axe", "shaft"),
         ("incli", "angle"), ("angle", "angle"))


FRENCH = {"width": "largeur", "depth": "profondeur", "height": "hauteur", "back": "hauteur du dossier", "plate": "hauteur de la plaque",
          "h": "hauteur", "d": "diamètre", "wall": "épaisseur des parois", "t": "épaisseur", "shaft": "diamètre de l'axe"}


def adjust(key: str, values: dict[str, Any], text: str) -> tuple[dict[str, Any], list[str]]:
    """A request for a change, read with keywords: returns the new values and what changed, in French."""
    t = plain(text)
    v = dict(values)
    said: list[str] = []
    spec = defaults(key)

    def scale(names: tuple[str, ...], f: float) -> None:
        for n in names:
            if n in v:
                v[n] = round(v[n] * f, 1)

    main = {"box": ("width", "depth", "height"), "stand": ("width", "back"), "hook": ("plate", "reach", "width"),
            "knob": ("d", "h"), "cup": ("d", "h")}[key]
    tall = {"box": ("height",), "stand": ("back",), "hook": ("plate",), "knob": ("h",), "cup": ("h",)}[key]
    # "largeur 90 mm", "hauteur de 60 mm", "150 mm de largeur"
    pairs = [(m.group(1), m.group(2)) for m in re.finditer(r"(\w+)[^\d]{0,25}?" + NUMBER, t)]
    pairs += [(m.group(2), m.group(1)) for m in re.finditer(NUMBER + r"\s*(?:de|d')?\s*(\w+)", t)]
    done: set[str] = set()
    for word, num_text in pairs:
        num = float(num_text.replace(",", "."))
        for stem, name in WHICH:
            target = {"width": "width", "depth": "depth", "height": tall[0], "d": "d", "t": "wall" if "wall" in spec else "t",
                      "shaft": "shaft", "angle": "angle"}[name]
            if stem in word and target in spec and target not in done:
                v[target] = num
                done.add(target)
                said.append(f"{FRENCH.get(target, target)} à {num:g} mm")
                break
    if re.search(r"(\d+)\s*(?:°|degres)", t) and "angle" in spec:
        v["angle"] = float(re.search(r"(\d+)\s*(?:°|degres)", t).group(1))  # type: ignore[union-attr]
        said.append(f"inclinaison à {v['angle']:g}°")
    if "plus grand" in t or "agrandi" in t or "plus large" in t:
        scale(main, 1.2)
        said.append("agrandi de 20 %")
    if "plus petit" in t or "reduis" in t or "reduire" in t:
        scale(main, 0.8)
        said.append("réduit de 20 %")
    if "plus haut" in t:
        scale(tall, 1.25)
        said.append("plus haut")
    if "plus bas" in t:
        scale(tall, 0.8)
        said.append("plus bas")
    if "solide" in t or "epais" in t or "renforc" in t:
        for n in ("wall", "t"):
            if n in v:
                v[n] = round(v[n] + 1, 1)
        said.append("parois plus épaisses")
    if "arrondi" in t and "radius" in v:
        v["radius"] = v["radius"] + 4
        said.append("coins plus arrondis")
    if ("separation" in t or "compartiment" in t) and "dividers" in v:
        n = re.search(r"(\d)\s*(?:separation|compartiment)", t)
        # "2 séparations" is a count; "3 compartiments" means 2 separations; otherwise one more than now
        v["dividers"] = min(4, (int(n.group(1)) - ("compartiment" in n.group(0))) if n else int(v["dividers"]) + 1)
        said.append(f"{v['dividers']} séparation(s)")
    if "torsad" in t and "twist" in v:
        v["twist"] = 45
        said.append("torsadé")
    if ("hexagon" in t or "6 faces" in t) and "sides" in v:
        v["sides"] = 6
        said.append("hexagonal")
    return v, said
