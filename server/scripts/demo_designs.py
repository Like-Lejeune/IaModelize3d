"""The parametric models the demo designer (scripts/g1_demo.py) draws, without any model call: real programs for the
geometry kernel (the format of agent/prompts.py), each with the question it asks first and how the answer sets its
parameters. Demo only: the real designer writes its own programs."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

BOX = r"""
const meta = { title: '__TITLE__', pack: 'household' };
const params = {
  width:    { value: 120, min: 30, max: 220, step: 1, unit: 'mm', label: 'Largeur', label_en: 'Width', source: 'user', group: 'Dimensions', group_en: 'Dimensions' },
  depth:    { value: 80, min: 30, max: 220, step: 1, unit: 'mm', label: 'Profondeur', label_en: 'Depth', source: 'user', group: 'Dimensions', group_en: 'Dimensions' },
  height:   { value: 50, min: 15, max: 150, step: 1, unit: 'mm', label: 'Hauteur', label_en: 'Height', source: 'user', group: 'Dimensions', group_en: 'Dimensions' },
  wall:     { value: 2.4, min: 1.2, max: 5, step: 0.2, unit: 'mm', label: 'Épaisseur des parois', label_en: 'Wall thickness', source: 'design', group: 'Solidité', group_en: 'Strength' },
  radius:   { value: 6, min: 0, max: 20, step: 0.5, unit: 'mm', label: 'Arrondi des coins', label_en: 'Corner rounding', source: 'design', group: 'Forme', group_en: 'Shape' },
  dividers: { value: 0, min: 0, max: 4, kind: 'int', label: 'Séparations', label_en: 'Dividers', source: 'design', group: 'Forme', group_en: 'Shape' },
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
const meta = { title: '__TITLE__', pack: 'household' };
const params = {
  width:  { value: 70, min: 40, max: 200, step: 1, unit: 'mm', label: 'Largeur', label_en: 'Width', source: 'design', group: 'Dimensions', group_en: 'Dimensions' },
  angle:  { value: 65, min: 45, max: 80, step: 1, unit: '°', label: 'Inclinaison', label_en: 'Tilt', source: 'user', group: 'Dimensions', group_en: 'Dimensions' },
  back:   { value: 90, min: 50, max: 180, step: 1, unit: 'mm', label: 'Hauteur du dossier', label_en: 'Back height', source: 'design', group: 'Dimensions', group_en: 'Dimensions' },
  slot:   { value: 12, min: 6, max: 20, step: 0.5, unit: 'mm', label: "Épaisseur de l'appareil (avec coque)", label_en: 'Device thickness (with case)', source: 'user', group: 'Ajustement', group_en: 'Fit' },
  lip:    { value: 12, min: 6, max: 30, step: 1, unit: 'mm', label: 'Hauteur du rebord', label_en: 'Lip height', source: 'design', group: 'Ajustement', group_en: 'Fit' },
  t:      { value: 4, min: 2.5, max: 8, step: 0.5, unit: 'mm', label: 'Épaisseur', label_en: 'Thickness', source: 'design', group: 'Solidité', group_en: 'Strength' },
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
const meta = { title: '__TITLE__', pack: 'household' };
const params = {
  width:  { value: 24, min: 12, max: 60, step: 1, unit: 'mm', label: 'Largeur', label_en: 'Width', source: 'design', group: 'Dimensions', group_en: 'Dimensions' },
  plate:  { value: 70, min: 40, max: 140, step: 1, unit: 'mm', label: 'Hauteur de la plaque', label_en: 'Plate height', source: 'design', group: 'Dimensions', group_en: 'Dimensions' },
  reach:  { value: 45, min: 20, max: 120, step: 1, unit: 'mm', label: 'Profondeur du crochet', label_en: 'Hook depth', source: 'user', group: 'Dimensions', group_en: 'Dimensions' },
  tip:    { value: 18, min: 6, max: 40, step: 1, unit: 'mm', label: 'Hauteur de la pointe', label_en: 'Tip height', source: 'design', group: 'Dimensions', group_en: 'Dimensions' },
  t:      { value: 5, min: 3, max: 10, step: 0.5, unit: 'mm', label: 'Épaisseur', label_en: 'Thickness', source: 'design', group: 'Solidité', group_en: 'Strength' },
  screw:  { value: 4, min: 3, max: 6, step: 0.5, unit: 'mm', label: 'Diamètre des vis', label_en: 'Screw diameter', source: 'standard', group: 'Fixation', group_en: 'Mounting' },
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
const meta = { title: '__TITLE__', pack: 'household' };
const params = {
  d:      { value: 32, min: 15, max: 70, step: 0.5, unit: 'mm', label: 'Diamètre', label_en: 'Diameter', source: 'user', group: 'Dimensions', group_en: 'Dimensions' },
  h:      { value: 16, min: 8, max: 40, step: 0.5, unit: 'mm', label: 'Hauteur', label_en: 'Height', source: 'user', group: 'Dimensions', group_en: 'Dimensions' },
  shaft:  { value: 6, min: 3, max: 10, step: 0.1, unit: 'mm', label: "Diamètre de l'axe", label_en: 'Shaft diameter', source: 'user', group: 'Ajustement', group_en: 'Fit' },
  flat:   { value: 4.5, min: 2, max: 10, step: 0.1, unit: 'mm', label: 'Cote sur le méplat', label_en: 'Across the flat', source: 'user', group: 'Ajustement', group_en: 'Fit' },
  depth:  { value: 12, min: 5, max: 35, step: 0.5, unit: 'mm', label: "Profondeur de l'axe", label_en: 'Shaft depth', source: 'user', group: 'Ajustement', group_en: 'Fit' },
  ridges: { value: 18, min: 0, max: 40, kind: 'int', label: 'Stries de préhension', label_en: 'Grip ridges', source: 'design', group: 'Forme', group_en: 'Shape' },
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
const meta = { title: '__TITLE__', pack: 'household' };
const params = {
  d:      { value: 75, min: 30, max: 160, step: 1, unit: 'mm', label: 'Diamètre', label_en: 'Diameter', source: 'design', group: 'Dimensions', group_en: 'Dimensions' },
  h:      { value: 100, min: 30, max: 200, step: 1, unit: 'mm', label: 'Hauteur', label_en: 'Height', source: 'design', group: 'Dimensions', group_en: 'Dimensions' },
  wall:   { value: 2.4, min: 1.2, max: 5, step: 0.2, unit: 'mm', label: 'Épaisseur des parois', label_en: 'Wall thickness', source: 'design', group: 'Solidité', group_en: 'Strength' },
  sides:  { value: 0, min: 0, max: 12, kind: 'int', label: 'Facettes (0 = rond)', label_en: 'Facets (0 = round)', source: 'design', group: 'Forme', group_en: 'Shape' },
  twist:  { value: 0, min: 0, max: 90, step: 5, unit: '°', label: 'Torsion', label_en: 'Twist', source: 'design', group: 'Forme', group_en: 'Shape' },
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


# English and French words that tell the two languages apart in a short request
EN_WORDS = {"a", "an", "the", "my", "for", "with", "and", "of", "to", "i", "it", "is", "make", "want", "need", "taller", "bigger",
            "smaller", "wider", "stronger", "higher", "lower", "rounded", "width", "height", "depth", "thick", "please", "can", "you",
            "phone", "box", "hook", "holder", "stand", "storage", "wall", "knob", "broken", "lid", "desk", "more", "less", "add", "dividers"}
FR_WORDS = {"un", "une", "le", "la", "les", "des", "du", "de", "mon", "ma", "mes", "pour", "avec", "et", "je", "plus", "moins", "est",
            "boite", "support", "crochet", "molette", "pot", "hauteur", "largeur", "profondeur", "epaisseur", "solide", "haut", "bas",
            "grand", "petit", "coins", "arrondis", "rangement", "telephone", "tablette", "cassee", "veux", "faut", "separations", "voici"}


def lang_of(text: str, default: str = "fr") -> str:
    """'en' or 'fr' for a request: the language whose small words it uses most; a message with none (a number, an option
    in both) keeps `default`."""
    words = re.findall(r"[a-z]+", plain(text))
    en = sum(w in EN_WORDS for w in words)
    fr = sum(w in FR_WORDS for w in words)
    if en == fr:
        return default
    return "en" if en > fr else "fr"


# key -> (program, words that pick it, its title, the first question and its options in both languages, what each option sets)
DESIGNS: dict[str, dict[str, Any]] = {
    "box": {"source": BOX, "words": ("boite", "rangement", "bac", "box", "organis", "tiroir", "couvercle", "storage", "lid", "drawer", "bin"),
            "title": {"fr": "Boîte de rangement", "en": "Storage box"},
            "ask": {"fr": "Quelle taille vous faut-il (extérieur) ?", "en": "What size do you need (outside)?"},
            "options": [({"fr": "120 × 80 × 50 mm", "en": "120 × 80 × 50 mm"}, {"width": 120, "depth": 80, "height": 50}),
                        ({"fr": "200 × 150 × 80 mm", "en": "200 × 150 × 80 mm"}, {"width": 200, "depth": 150, "height": 80}),
                        ({"fr": "80 × 80 × 40 mm, avec 2 séparations", "en": "80 × 80 × 40 mm, with 2 dividers"},
                         {"width": 80, "depth": 80, "height": 40, "dividers": 2})]},
    "stand": {"source": STAND, "words": ("support", "telephone", "tablette", "stand", "phone", "smartphone", "tablet", "holder"),
              "title": {"fr": "Support incliné", "en": "Tilted stand"},
              "ask": {"fr": "Pour quel appareil, et quelle épaisseur avec sa coque ?", "en": "For which device, and how thick with its case?"},
              "options": [({"fr": "Téléphone, environ 10 mm", "en": "Phone, about 10 mm"}, {"width": 70, "slot": 11, "back": 90}),
                          ({"fr": "Tablette 10 pouces, environ 9 mm", "en": "10-inch tablet, about 9 mm"}, {"width": 150, "slot": 10, "back": 140, "t": 5}),
                          ({"fr": "Téléphone avec coque épaisse, 15 mm", "en": "Phone with a thick case, 15 mm"}, {"width": 75, "slot": 16, "back": 95})]},
    "hook": {"source": HOOK, "words": ("crochet", "accroch", "hook", "patere", "suspendre", "hang"),
             "title": {"fr": "Crochet mural", "en": "Wall hook"},
             "ask": {"fr": "Que doit-il porter ?", "en": "What will it hold?"},
             "options": [({"fr": "Un casque audio", "en": "Headphones"}, {"reach": 45, "width": 24, "t": 5}),
                         ({"fr": "Des clés", "en": "Keys"}, {"reach": 25, "width": 14, "t": 4, "plate": 50}),
                         ({"fr": "Un sac lourd", "en": "A heavy bag"}, {"reach": 60, "width": 35, "t": 8, "screw": 5})]},
    "knob": {"source": KNOB, "words": ("molette", "bouton", "knob", "poignee de reglage", "potentiometre", "dial", "potentiometer"),
             "title": {"fr": "Molette de remplacement", "en": "Replacement knob"},
             "ask": {"fr": "Quel est le diamètre de l'axe sur lequel elle s'enfonce ?", "en": "What is the diameter of the shaft it pushes onto?"},
             "options": [({"fr": "6 mm avec un méplat (axe en D)", "en": "6 mm with a flat (D shaft)"}, {"shaft": 6, "flat": 4.5}),
                         ({"fr": "4 mm avec un méplat", "en": "4 mm with a flat"}, {"shaft": 4, "flat": 3}),
                         ({"fr": "Je ne sais pas, je mesure et je vous dis", "en": "I don't know, I'll measure and tell you"}, {})]},
    "cup": {"source": CUP, "words": ("pot", "stylo", "gobelet", "cup", "vase", "cache-pot", "pen", "planter"),
            "title": {"fr": "Pot", "en": "Pot"},
            "ask": {"fr": "Quelle forme préférez-vous ?", "en": "Which shape do you prefer?"},
            "options": [({"fr": "Rond et simple", "en": "Round and plain"}, {"sides": 0, "twist": 0}),
                        ({"fr": "Hexagonal", "en": "Hexagonal"}, {"sides": 6, "twist": 0}),
                        ({"fr": "Hexagonal torsadé", "en": "Twisted hexagon"}, {"sides": 6, "twist": 45})]},
}


def source(key: str, lang: str) -> str:
    """The program with its title in the request's language (the parameter labels carry both languages)."""
    return DESIGNS[key]["source"].replace("__TITLE__", DESIGNS[key]["title"][lang].replace("'", "\\'"))


def key_of(program: str) -> str:
    """Which design a saved program is, whatever language its title was written in."""
    for key in DESIGNS:
        if any(source(key, lang).strip() == program.strip() for lang in ("fr", "en")):
            return key
    return "box"


def options(key: str, lang: str) -> list[str]:
    return [names[lang] for names, _ in DESIGNS[key]["options"]]


def option_values(key: str, answer: str) -> dict[str, Any] | None:
    """What a picked option sets, the option named in either language; None for an answer in the person's own words."""
    for names, values in DESIGNS[key]["options"]:
        if answer in names.values():
            return values
    return None


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
WHICH = (("larg", "width"), ("wid", "width"), ("profond", "depth"), ("deep", "depth"), ("depth", "depth"), ("haut", "height"),
         ("heigh", "height"), ("tall", "height"), ("diam", "d"), ("epais", "t"), ("thick", "t"), ("axe", "shaft"), ("shaft", "shaft"),
         ("incli", "angle"), ("tilt", "angle"), ("angle", "angle"))

NAMES = {
    "fr": {"width": "largeur", "depth": "profondeur", "height": "hauteur", "back": "hauteur du dossier", "plate": "hauteur de la plaque",
           "h": "hauteur", "d": "diamètre", "wall": "épaisseur des parois", "t": "épaisseur", "shaft": "diamètre de l'axe"},
    "en": {"width": "width", "depth": "depth", "height": "height", "back": "back height", "plate": "plate height",
           "h": "height", "d": "diameter", "wall": "wall thickness", "t": "thickness", "shaft": "shaft diameter"},
}

# what was changed, said back in the request's language
SAID = {
    "fr": {"set": "{name} à {num:g} mm", "angle": "inclinaison à {num:g}°", "bigger": "agrandi de 20 %", "smaller": "réduit de 20 %",
           "taller": "plus haut", "lower": "plus bas", "stronger": "parois plus épaisses", "rounder": "coins plus arrondis",
           "dividers": "{n} séparation(s)", "twist": "torsadé", "hexagon": "hexagonal"},
    "en": {"set": "{name} to {num:g} mm", "angle": "tilt to {num:g}°", "bigger": "20% bigger", "smaller": "20% smaller",
           "taller": "taller", "lower": "lower", "stronger": "thicker walls", "rounder": "rounder corners",
           "dividers": "{n} divider(s)", "twist": "twisted", "hexagon": "hexagonal"},
}


def adjust(key: str, values: dict[str, Any], text: str, lang: str = "fr") -> tuple[dict[str, Any], list[str]]:
    """A request for a change, read with French and English keywords: returns the new values and what changed, said in
    `lang`."""
    t = plain(text)
    v = dict(values)
    said: list[str] = []
    say = SAID[lang]
    spec = defaults(key)

    def scale(names: tuple[str, ...], f: float) -> None:
        for n in names:
            if n in v:
                v[n] = round(v[n] * f, 1)

    def has(*words: str) -> bool:
        return any(w in t for w in words)

    main = {"box": ("width", "depth", "height"), "stand": ("width", "back"), "hook": ("plate", "reach", "width"),
            "knob": ("d", "h"), "cup": ("d", "h")}[key]
    tall = {"box": ("height",), "stand": ("back",), "hook": ("plate",), "knob": ("h",), "cup": ("h",)}[key]
    # "largeur 90 mm", "hauteur de 60 mm", "150 mm de largeur", "width 90 mm", "150 mm wide", "make it 60 mm tall"
    pairs = [(m.group(1), m.group(2)) for m in re.finditer(r"(\w+)[^\d]{0,25}?" + NUMBER, t)]
    pairs += [(m.group(2), m.group(1)) for m in re.finditer(NUMBER + r"\s*(?:de|d'|of)?\s*(\w+)", t)]
    done: set[str] = set()
    for word, num_text in pairs:
        num = float(num_text.replace(",", "."))
        for stem, name in WHICH:
            target = {"width": "width", "depth": "depth", "height": tall[0], "d": "d", "t": "wall" if "wall" in spec else "t",
                      "shaft": "shaft", "angle": "angle"}[name]
            if stem in word and target in spec and target not in done:
                v[target] = num
                done.add(target)
                said.append(say["set"].format(name=NAMES[lang].get(target, target), num=num))
                break
    deg = re.search(r"(\d+)\s*(?:°|degres|degrees)", t)
    if deg and "angle" in spec:
        v["angle"] = float(deg.group(1))
        said.append(say["angle"].format(num=v["angle"]))
    if has("plus grand", "agrandi", "plus large", "bigger", "larger", "wider"):
        scale(main, 1.2)
        said.append(say["bigger"])
    if has("plus petit", "reduis", "reduire", "smaller", "shrink"):
        scale(main, 0.8)
        said.append(say["smaller"])
    if has("plus haut", "taller", "higher"):
        scale(tall, 1.25)
        said.append(say["taller"])
    if has("plus bas", "lower", "shorter"):
        scale(tall, 0.8)
        said.append(say["lower"])
    if has("solide", "epais", "renforc", "stronger", "sturdier", "thicker"):
        for n in ("wall", "t"):
            if n in v:
                v[n] = round(v[n] + 1, 1)
        said.append(say["stronger"])
    if has("arrondi", "rounded", "rounder", "round the corners") and "radius" in v:
        v["radius"] = v["radius"] + 4
        said.append(say["rounder"])
    if has("separation", "compartiment", "divider", "compartment") and "dividers" in v:
        n = re.search(r"(\d)\s*(separation|compartiment|divider|compartment)", t)
        # "2 séparations" / "2 dividers" is a count; "3 compartiments" / "3 compartments" means 2 dividers; else one more than now
        v["dividers"] = min(4, (int(n.group(1)) - n.group(2).startswith("compart")) if n else int(v["dividers"]) + 1)
        said.append(say["dividers"].format(n=v["dividers"]))
    if has("torsad", "twist") and "twist" in v:
        v["twist"] = 45
        said.append(say["twist"])
    if has("hexagon", "6 faces", "6 sides", "six sides") and "sides" in v:
        v["sides"] = 6
        said.append(say["hexagon"])
    return v, said
