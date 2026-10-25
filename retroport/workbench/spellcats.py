"""Where retail files each spell: a class's abilities, a specialization, talents, hero talents, PvP
talents, glyphs, pets, mounts, racial traits, professions and the expansion systems - as Wowhead's
spell menus group them, from retail's own tables. The Spells view filters on it.

  class abilities   SkillLineAbility on the class's skill line (SkillLine category 7, its name)
  specialization    SpecializationSpells (spec -> class: ChrSpecialization)
  talents           TraitDefinition -> TraitNodeEntry -> TraitNode -> TraitTree -> SkillLineXTraitTree
  hero talents      the same, on a node or entry of a TraitSubTree
  pvp talents       PvpTalent (spec)
  glyphs            GlyphProperties (class: SpellClassOptions.SpellClassSet = ChrClasses.SpellClassSet)
  pet abilities     SkillLineAbility on a "Pet - ..." skill line
  companions        BattlePetSpecies.SummonSpellID
  mounts            Mount.SourceSpellID
  racial traits     SkillLineAbility on a "Racial - ..." skill line
  professions       SkillLineAbility on a profession (SkillLine category 11) or one of its parts
  azerite, artifact, conduits, runecarving   their power tables

Each spell gets tags (kind, key): key a class, spec, skill line or sub-tree id, 0 for none.
Cached beside the spell index (spellcats-<build>.pickle).
"""

from __future__ import annotations

import os
import pickle

CATS_VERSION = 1

KINDS = [
    ("Class", [("abilities", "Abilities"), ("spec", "Specialization"), ("talents", "Talents"),
               ("hero", "Hero talents"), ("pvp", "PvP talents"), ("glyphs", "Glyphs")]),
    ("Pets", [("companions", "Companions"), ("mounts", "Mounts"), ("pet", "Pet abilities")]),
    ("Character", [("racial", "Racial traits"), ("profession", "Professions")]),
    ("Expansions", [("azerite", "Azerite traits (BfA)"), ("artifact", "Artifact traits (Legion)"),
                    ("conduit", "Soulbind conduits (Shadowlands)"), ("runecarving", "Runecarving powers (Shadowlands)")]),
]
CLASS_KINDS = {"abilities", "spec", "talents", "hero", "pvp", "glyphs"}


def _rows(src, name):
    try:
        return dict(src.table(name))
    except Exception:
        return {}


def build(src, say=lambda m: None) -> dict:
    say("spells: reading where retail files each spell")
    tags: dict[int, set] = {}

    def tag(spell, kind, key=0):
        if spell:
            tags.setdefault(int(spell), set()).add((kind, int(key or 0)))

    classes = {i: r.get("Name_lang") or r.get("Filename") or f"class {i}" for i, r in _rows(src, "ChrClasses").items()}
    class_set = {r.get("SpellClassSet"): i for i, r in _rows(src, "ChrClasses").items() if r.get("SpellClassSet")}
    specs = {i: (r["ClassID"], r.get("Name_lang") or f"spec {i}") for i, r in _rows(src, "ChrSpecialization").items()
             if r.get("ClassID")}
    lines = _rows(src, "SkillLine")
    by_name = {v.lower(): k for k, v in classes.items()}
    class_line = {i: by_name[r["DisplayName_lang"].lower()] for i, r in lines.items()
                  if r.get("CategoryID") == 7 and (r.get("DisplayName_lang") or "").lower() in by_name}
    pet_lines = {i: r["DisplayName_lang"][6:] for i, r in lines.items()
                 if (r.get("DisplayName_lang") or "").startswith("Pet - ")}
    racial_lines = {i: r["DisplayName_lang"][9:] for i, r in lines.items()
                    if (r.get("DisplayName_lang") or "").startswith("Racial - ")}
    professions = {i: r["DisplayName_lang"] for i, r in lines.items()
                   if r.get("CategoryID") == 11 and not r.get("ParentSkillLineID")}
    prof_of = {}
    for i, r in lines.items():
        p = i
        for _ in range(4):
            if p in professions:
                prof_of[i] = p
                break
            p = lines.get(p, {}).get("ParentSkillLineID") or 0
    for _i, r in _rows(src, "SkillLineAbility").items():
        line, spell = r.get("SkillLine"), r.get("Spell")
        if line in class_line:
            tag(spell, "abilities", class_line[line])
        elif line in pet_lines:
            tag(spell, "pet", line)
        elif line in racial_lines:
            tag(spell, "racial", line)
        elif line in prof_of:
            tag(spell, "profession", prof_of[line])
    for _i, r in _rows(src, "SpecializationSpells").items():
        tag(r.get("SpellID"), "spec", r.get("SpecID"))
    for _i, r in _rows(src, "PvpTalent").items():
        tag(r.get("SpellID"), "pvp", r.get("SpecID"))

    # talents: definition -> entry -> node -> tree -> the class's skill line; a sub-tree is a hero tree
    defs = {i: r.get("SpellID") for i, r in _rows(src, "TraitDefinition").items()}
    entries = _rows(src, "TraitNodeEntry")
    nodes = _rows(src, "TraitNode")
    node_of = {r["TraitNodeEntryID"]: r["TraitNodeID"] for r in _rows(src, "TraitNodeXTraitNodeEntry").values()}
    tree_class = {r["TraitTreeID"]: class_line[r["SkillLineID"]] for r in _rows(src, "SkillLineXTraitTree").values()
                  if r.get("SkillLineID") in class_line}
    subtrees = _rows(src, "TraitSubTree")
    hero = {}
    for eid, e in entries.items():
        spell = defs.get(e.get("TraitDefinitionID"))
        node = nodes.get(node_of.get(eid))
        if not spell or not node:
            continue
        cls = tree_class.get(node.get("TraitTreeID"))
        sub = e.get("TraitSubTreeID") or node.get("TraitSubTreeID")
        if sub and sub in subtrees:
            tag(spell, "hero", sub)
            if cls:
                hero[sub] = (cls, subtrees[sub].get("Name_lang") or f"hero tree {sub}")
        elif cls:
            tag(spell, "talents", cls)

    glyph_class = {}
    for _i, r in _rows(src, "SpellClassOptions").items():
        if r.get("SpellClassSet") in class_set:
            glyph_class[r["SpellID"]] = class_set[r["SpellClassSet"]]
    for _i, r in _rows(src, "GlyphProperties").items():
        tag(r.get("SpellID"), "glyphs", glyph_class.get(r.get("SpellID"), 0))
    for _i, r in _rows(src, "BattlePetSpecies").items():
        tag(r.get("SummonSpellID"), "companions")
    for _i, r in _rows(src, "Mount").items():
        tag(r.get("SourceSpellID"), "mounts")
    for table, kind in (("AzeritePower", "azerite"), ("ArtifactPowerRank", "artifact"),
                        ("SoulbindConduitRank", "conduit"), ("RuneforgeLegendaryAbility", "runecarving")):
        for _i, r in _rows(src, table).items():
            tag(r.get("SpellID"), kind)
    return {"version": CATS_VERSION, "build": src.build, "tags": {k: sorted(v) for k, v in tags.items()},
            "classes": classes, "specs": specs, "hero": hero, "pet": pet_lines, "racial": racial_lines,
            "profession": professions}


def load(src, cache_dir: str, say=lambda m: None) -> dict:
    path = os.path.join(cache_dir, f"spellcats-{src.build}.pickle")
    if os.path.isfile(path):
        try:
            with open(path, "rb") as fh:
                d = pickle.load(fh)
            if d.get("version") == CATS_VERSION:
                return d
        except (OSError, ValueError, pickle.UnpicklingError, EOFError):
            pass
    d = build(src, say)
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        pickle.dump(d, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)
    return d


def menus(d: dict) -> dict:
    """What the Spells view's filter menus offer."""
    counts: dict = {}
    for tags in d["tags"].values():
        for kind, key in tags:
            counts[(kind, key)] = counts.get((kind, key), 0) + 1
    present = {k for k, _ in counts}
    return {
        "kinds": [{"group": g, "kinds": [{"id": k, "name": n} for k, n in ks if k in present]} for g, ks in KINDS],
        "classes": sorted(({"id": i, "name": n} for i, n in d["classes"].items()), key=lambda x: x["name"]),
        "specs": sorted(({"id": i, "class": c, "name": n} for i, (c, n) in d["specs"].items()), key=lambda x: x["name"]),
        "hero": sorted(({"id": i, "class": c, "name": n} for i, (c, n) in d["hero"].items()), key=lambda x: x["name"]),
        "pet": sorted(({"id": i, "name": n} for i, n in d["pet"].items() if counts.get(("pet", i))), key=lambda x: x["name"]),
        "racial": sorted(({"id": i, "name": n} for i, n in d["racial"].items() if counts.get(("racial", i))), key=lambda x: x["name"]),
        "profession": sorted(({"id": i, "name": n} for i, n in d["profession"].items() if counts.get(("profession", i))),
                             key=lambda x: x["name"]),
    }


def matching(d: dict, kind: str, key: int = 0, sub: int = 0) -> set[int]:
    """The spells filed under ``kind``: for a class kind, ``key`` a class (0 any) and ``sub`` a spec or
    hero tree (0 any); for pets, racial traits and professions, ``key`` the skill line."""
    if not kind:
        return set()
    spec_class = {i: c for i, (c, _n) in d["specs"].items()}
    hero_class = {i: c for i, (c, _n) in d["hero"].items()}
    out = set()
    for spell, tags in d["tags"].items():
        for k, v in tags:
            if k != kind:
                continue
            if kind in ("spec", "pvp"):
                if (sub and v != sub) or (key and spec_class.get(v) != key):
                    continue
            elif kind == "hero":
                if (sub and v != sub) or (key and hero_class.get(v) != key):
                    continue
            elif key and v != key:
                continue
            out.add(spell)
            break
    return out
