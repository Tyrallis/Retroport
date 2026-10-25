"""Spells: retail spells' visuals from wago.tools, to look at as the game plays them.

A spell shows through its visuals (SpellXSpellVisual). A visual is a set of events
(SpellVisualEvent): each starts a kit at one moment of the cast (precast, cast, travel, impact,
aura, channel, area trigger) on the caster, the target or the ground, and ends it at another - or
when its models have played once (the "one-shot" end). A kit's effects (SpellVisualKitEffect)
attach models (SpellVisualKitModelAttach -> SpellVisualEffectName -> the model file) at an
attachment point with an offset, a turn, a scale and a delay, and play sounds and animations.
Missiles (SpellVisualMissile) fly from the caster to the target between travel start and end.

The tables are big (a third of a million rows each), so they are read once into a compact index
cached beside wago's files (spells-<build>.pickle) and loaded from there afterwards.
"""

from __future__ import annotations

import os
import pickle
import threading

from . import models as M
from .creatures import find_listfile

INDEX_VERSION = 3
PAGE = 60

EVENTS = {1: "Precast start", 2: "Precast end", 3: "Cast", 4: "Travel start", 5: "Travel end", 6: "Impact",
          7: "Aura start", 8: "Aura end", 9: "Area trigger start", 10: "Area trigger end", 11: "Channel start",
          12: "Channel end", 13: "Played once"}
TARGETS = {1: "caster", 2: "target", 3: "ground", 4: "target", 5: "target"}
EFFECT_TYPES = {1: "procedural", 2: "model", 3: "camera", 5: "sound", 6: "animation", 7: "shadowy", 8: "emission",
                9: "outline", 10: "unit sound", 11: "dissolve", 12: "edge glow", 13: "beam"}
# M2 attachment points spells use most
ATTACHMENTS = {-1: "origin", 0: "shield", 1: "right hand", 2: "left hand", 3: "right elbow", 4: "left elbow",
               5: "right shoulder", 6: "left shoulder", 7: "right knee", 8: "left knee", 11: "helm", 12: "back",
               15: "chest", 16: "chest back", 17: "breath", 18: "above head", 19: "base", 20: "head",
               21: "left spell hand", 22: "right spell hand", 23: "special 1", 34: "center", 38: "upper back"}

# the stand-ins the preview casts with: a retail humanoid with every attachment point, and a dummy
CASTER_DISPLAY = 73181          # Lady Jaina Proudmoore (creature/jaina/jaina2.m2)
TARGET_DISPLAY = 28047          # Pet Training Post (creature/object/woodendummy.m2)


class SpellError(LookupError):
    pass


def _first(rows, key):
    return {i: r for i, r in rows if r.get(key, 0) == 0}


class SpellIndex:
    """What the page needs of a build's spell tables, as small tuples."""

    def __init__(self, d: dict):
        self.__dict__.update(d)

    @classmethod
    def build_from(cls, src, listfile: str, say=lambda m: None) -> "SpellIndex":
        T = src.table
        say("spells: reading SpellName")
        names = {i: r.get("Name_lang") or "" for i, r in T("SpellName")}
        say("spells: reading SpellXSpellVisual")
        xv: dict[int, list] = {}
        for _i, r in T("SpellXSpellVisual"):
            xv.setdefault(r["SpellID"], []).append((r["SpellVisualID"], r["DifficultyID"], r["CasterPlayerConditionID"],
                                                    r["CasterUnitConditionID"], r["Priority"]))
        say("spells: reading SpellVisual")
        sv = {i: (r.get("SpellVisualMissileSetID", 0), r.get("MissileAttachment", -1),
                  r.get("MissileDestinationAttachment", -1), r.get("StateKit", 0), r.get("Flags", 0))
              for i, r in T("SpellVisual")}
        say("spells: reading SpellVisualEvent")
        ev: dict[int, list] = {}
        for _i, r in T("SpellVisualEvent"):
            ev.setdefault(r["SpellVisualID"], []).append((r["StartEvent"], r["EndEvent"], r["StartMinOffsetMs"],
                                                          r["StartMaxOffsetMs"], r["EndMinOffsetMs"], r["EndMaxOffsetMs"],
                                                          r["TargetType"], r["SpellVisualKitID"]))
        say("spells: reading SpellVisualKit")
        kit = {i: (r.get("DelayMin", 0), r.get("DelayMax", 0)) for i, r in T("SpellVisualKit")}
        say("spells: reading SpellVisualKitEffect")
        ke: dict[int, list] = {}
        for _i, r in T("SpellVisualKitEffect"):
            ke.setdefault(r["ParentSpellVisualKitID"], []).append((r["EffectType"], r["Effect"]))
        say("spells: reading SpellVisualKitModelAttach")
        ma = {}
        for i, r in T("SpellVisualKitModelAttach"):
            o = r.get("Offset") or [0.0, 0.0, 0.0]
            ma[i] = (r["SpellVisualEffectNameID"], r["AttachmentID"], r["PositionerID"], tuple(o),
                     (r["Yaw"], r["Pitch"], r["Roll"]), r["Scale"] or 1.0, r["StartDelay"],
                     (r["StartAnimID"], r["AnimID"], r["EndAnimID"]), r["Flags"])
        say("spells: reading SpellVisualEffectName")
        en = {i: (r["ModelFileDataID"], r["Scale"] or 1.0, r["Alpha"], r["Flags"], r["TextureFileDataID"], r["Type"],
                  r["BaseMissileSpeed"]) for i, r in T("SpellVisualEffectName")}
        say("spells: reading SpellVisualMissile")
        ms: dict[int, list] = {}
        for i, r in T("SpellVisualMissile"):
            ms.setdefault(r["SpellVisualMissileSetID"], []).append(
                (r["SpellVisualEffectNameID"], r["Attachment"], r["DestinationAttachment"], tuple(r.get("CastOffset") or (0, 0, 0)),
                 tuple(r.get("ImpactOffset") or (0, 0, 0)), r["Flags"]))
        # procedural effects of type 9: models scattered over the area while the kit lasts (Blizzard's
        # falling shards) - SpellVisualKitAreaModel: model, flags, lifetime ms, per second, spacing, scale
        say("spells: reading SpellProceduralEffect")
        proc = {i: int(r["Value"][0]) for i, r in T("SpellProceduralEffect") if r["Type"] == 9}
        aream = {}
        try:
            for i, r in T("SpellVisualKitAreaModel"):
                aream[i] = (r["ModelFileDataID"], r["Flags"], r["LifeTime"], r["EmissionRate"], r["Spacing"],
                            r["ModelScale"] or 1.0)
        except Exception:
            pass
        # positioners: where a model with no attachment of its own hangs (its first state's position
        # entry: an attachment point) and whether it keeps the unit's upright frame (its rotation taken
        # from the base, 19, or from nothing) instead of turning with that point's bone (a held book)
        say("spells: reading Positioner")
        posi = {}
        try:
            PS = dict(T("PositionerState"))
            PE = dict(T("PositionerStateEntry"))
            for pid, p in T("Positioner"):
                s = PS.get(p.get("FirstStateID")) or {}
                pe = PE.get(s.get("PosEntryID")) or {}
                re_ = PE.get(s.get("RotEntryID")) or {}
                at = int(pe.get("SrcVal", -1)) if pe.get("SrcValType") == 1 else -1
                rot_at = int(re_.get("SrcVal", -1)) if re_.get("SrcValType") == 1 else None
                upright = bool(re_) and (re_.get("SrcValType") == 0 or rot_at in (19, 0, -1)) and at not in (19, 0, -1)
                moving = bool(s.get("NextStateID")) or bool(pe.get("CurveID")) or bool(s.get("TransformMatrixID"))
                posi[pid] = (at, upright, moving)
        except Exception:
            pass
        say("spells: reading SpellVisualAnim")
        anim = {i: (r["InitialAnimID"], r["LoopAnimID"], r["AnimKitID"]) for i, r in T("SpellVisualAnim")}
        say("spells: reading SpellMisc")
        misc = {}
        for _i, r in T("SpellMisc"):
            if r.get("DifficultyID", 0) and r["SpellID"] in misc:
                continue
            misc[r["SpellID"]] = (r["CastingTimeIndex"], r["DurationIndex"], r["RangeIndex"], r["Speed"], r["LaunchDelay"],
                                  r["SchoolMask"], r.get("SpellIconFileDataID", 0))
        cast = {i: r["Base"] for i, r in T("SpellCastTimes")}
        dur = {i: r["Duration"] for i, r in T("SpellDuration")}
        rng = {i: (r["RangeMin"][0], r["RangeMax"][0], r.get("DisplayName_lang", "")) for i, r in T("SpellRange")}

        # how many models each spell shows: the search ranks spells with visuals first
        say("spells: counting each spell's models")
        kit_models = {k: {ma[e][0] for t, e in v if t == 2 and e in ma} for k, v in ke.items()}
        kit_area = {k: {aream[proc[e]][0] for t, e in v if t == 1 and e in proc and proc[e] in aream} for k, v in ke.items()}
        counts: dict[int, int] = {}
        for sid, vis in xv.items():
            seen = set()
            for v, *_rest in vis:
                for e in ev.get(v, []):
                    seen |= {en[n][0] for n in kit_models.get(e[7], ()) if n in en and en[n][0]}
                    seen |= {f for f in kit_area.get(e[7], ()) if f}
                setid = sv.get(v, (0,))[0]
                seen |= {en[m[0]][0] for m in ms.get(setid, []) if m[0] in en and en[m[0]][0]}
            if seen:
                counts[sid] = len(seen)
        say("spells: naming models from the listfile")
        wanted = {x[0] for x in en.values() if x[0]} | {x[0] for x in aream.values() if x[0]}
        paths = {}
        with open(listfile, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                left, _, right = line.partition(";")
                if left.isdigit() and int(left) in wanted:
                    paths[int(left)] = right.strip()
        return cls({"version": INDEX_VERSION, "build": src.build, "names": names, "xv": xv, "sv": sv, "ev": ev,
                    "kit": kit, "ke": ke, "ma": ma, "en": en, "ms": ms, "anim": anim, "misc": misc, "cast": cast,
                    "proc": proc, "aream": aream, "posi": posi,
                    "dur": dur, "rng": rng, "counts": counts, "paths": paths, "_order": None})

    # -- answers --------------------------------------------------------------------------
    def _rows(self) -> list:
        if self._order is None:
            # spells with models first (most models first), then by id, newest first
            self._order = sorted(self.names, key=lambda i: (-min(self.counts.get(i, 0), 1), -i))
        return self._order

    def search(self, q: str, page: int, with_models: bool, only: set | None = None) -> tuple[int, list[dict]]:
        hits = self.ids(q, with_models, only)
        return len(hits), [self.row(s) for s in hits[page * PAGE:(page + 1) * PAGE]]

    def ids(self, q: str, with_models: bool, only: set | None = None) -> list[int]:
        """Every spell a search finds, in the view's order (``only``: a filter's spells)."""
        q = q.strip().lower()
        hits = []
        if q.isdigit() and int(q) in self.names and (only is None or int(q) in only):
            hits.append(int(q))
        terms = q.split()
        for sid in self._rows():
            if only is not None and sid not in only:
                continue
            if with_models and sid not in self.counts:
                continue
            if terms and not all(t in self.names[sid].lower() for t in terms):
                continue
            if hits and sid == hits[0]:
                continue
            hits.append(sid)
        return hits

    def row(self, sid: int) -> dict:
        m = self.misc.get(sid)
        return {"id": sid, "name": self.names.get(sid, f"spell {sid}"), "models": self.counts.get(sid, 0),
                "visuals": len(self.xv.get(sid, [])), "icon": m[6] if m else 0}

    def timing(self, sid: int) -> dict:
        m = self.misc.get(sid)
        if not m:
            return {"cast": 0, "duration": 0, "range": 0, "speed": 0, "launch": 0, "school": 0}
        r = self.rng.get(m[2], (0, 0, ""))
        return {"cast": self.cast.get(m[0], 0), "duration": self.dur.get(m[1], 0), "range": r[1], "range_name": r[2],
                "speed": m[3], "launch": round(m[4] * 1000), "school": m[5]}

    def _model(self, name_id: int) -> dict | None:
        n = self.en.get(name_id)
        if not n or not n[0]:
            return None
        return {"fdid": n[0], "path": self.paths.get(n[0], ""), "scale": n[1], "alpha": n[2], "texture": n[4],
                "type": n[5], "missile_speed": n[6], "effect_name": name_id}

    def visual(self, vid: int) -> dict:
        s = self.sv.get(vid, (0, -1, -1, 0, 0))
        events = []
        for start, end, smin, smax, emin, emax, target, kid in sorted(self.ev.get(vid, []), key=lambda e: (e[0], e[7])):
            dmin, dmax = self.kit.get(kid, (0, 0))
            models, other, anims, area, sounds = [], {}, [], [], []
            for t, e in self.ke.get(kid, []):
                if t == 5 and e:
                    sounds.append(e)
                if t == 1 and e in self.proc and self.proc[e] in self.aream:
                    fd, fl, life, rate, spacing, scale = self.aream[self.proc[e]]
                    if fd:
                        area.append({"fdid": fd, "path": self.paths.get(fd, ""), "flags": fl, "lifetime": life,
                                     "rate": rate, "spacing": spacing, "scale": scale, "area_id": self.proc[e]})
                        other["area models"] = other.get("area models", 0) + 1
                        continue
                if t == 2 and e in self.ma:
                    a = self.ma[e]
                    mdl = self._model(a[0])
                    if not mdl:
                        continue
                    att, upright, moving = a[1], False, bool(a[2])
                    if a[2] and a[2] in self.posi:
                        p_at, upright, moving = self.posi[a[2]]
                        if att == -1 and p_at >= 0:
                            att = p_at                  # the positioner says where it hangs
                    models.append(mdl | {"attach_id": e, "attachment": att, "attachment_name": ATTACHMENTS.get(att, f"point {att}"),
                                         "positioner": a[2], "moving": moving, "upright": upright,
                                         "offset": list(a[3]), "rotation": list(a[4]), "attach_scale": a[5],
                                         "delay": a[6], "anims": list(a[7]), "flags": a[8]})
                else:
                    name = EFFECT_TYPES.get(t, f"type {t}")
                    if t == 6 and e in self.anim:
                        name = f"animation {self.anim[e][1]}" if self.anim[e][1] >= 0 else "animation"
                        anims.append({"initial": self.anim[e][0], "loop": self.anim[e][1], "kit": self.anim[e][2]})
                    other[name] = other.get(name, 0) + 1
            events.append({"start": start, "end": end, "start_name": EVENTS.get(start, f"event {start}"),
                           "end_name": EVENTS.get(end, f"event {end}"), "offset": [smin, smax], "end_offset": [emin, emax],
                           "target": target, "target_name": TARGETS.get(target, f"target {target}"), "kit": kid,
                           "kit_delay": [dmin, dmax], "models": models, "anims": anims, "area_models": area,
                           "sounds": sounds,
                           "other": [f"{n} ×{c}" if c > 1 else n for n, c in sorted(other.items())]})
        missiles = []
        for name_id, att, dest, co, io, fl in self.ms.get(s[0], []):
            mdl = self._model(name_id)
            if mdl:
                missiles.append(mdl | {"attachment": att, "attachment_name": ATTACHMENTS.get(att, f"point {att}"),
                                       "destination": dest, "destination_name": ATTACHMENTS.get(dest, f"point {dest}"),
                                       "cast_offset": list(co), "impact_offset": list(io), "flags": fl})
        return {"id": vid, "events": events, "missiles": missiles, "state_kit": s[3],
                "missile_attachment": s[1], "missile_destination": s[2]}

    def detail(self, sid: int) -> dict:
        if sid not in self.names and sid not in self.xv:
            raise SpellError(f"no spell {sid}")
        vis = []
        for v, diff, pcond, ucond, prio in self.xv.get(sid, []):
            vis.append(self.visual(v) | {"difficulty": diff, "player_condition": pcond, "unit_condition": ucond,
                                         "priority": prio})
        # the plain visual first: no difficulty, no condition
        vis.sort(key=lambda x: (bool(x["difficulty"]), bool(x["player_condition"] or x["unit_condition"]), x["id"]))
        return self.row(sid) | {"timing": self.timing(sid), "visual_list": vis}


def load_index(src, cache_dir: str, listfile: str, say=lambda m: None) -> SpellIndex:
    path = os.path.join(cache_dir, f"spells-{src.build}.pickle")
    if os.path.isfile(path):
        try:
            with open(path, "rb") as fh:
                d = pickle.load(fh)
            if d.get("version") == INDEX_VERSION:
                return SpellIndex(d)
        except (OSError, ValueError, pickle.UnpicklingError, EOFError):
            pass
    idx = SpellIndex.build_from(src, listfile, say)
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        pickle.dump({k: v for k, v in idx.__dict__.items() if k != "_order"} | {"_order": None}, fh,
                    protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)
    say(f"spells: {len(idx.names):,} spells, {len(idx.counts):,} with models")
    return idx


class Spells:
    """The Spells view's answers."""

    def __init__(self, wb):
        self.wb = wb
        self._index: SpellIndex | None = None
        self._lock = threading.Lock()
        self._meshes: dict = {}
        self._cats: dict | None = None
        self.state = "idle"
        from .spellport import SpellPort
        self.port = SpellPort(wb, self)

    def source(self):
        return self.wb.creatures.source()

    def listfile(self) -> str:
        """The community listfile the index named its files from."""
        kit = self.wb.kit.cfg
        cands = [self.wb.settings.listfile, os.path.join(getattr(kit, "work", "") or "", "listfile.csv")]
        return find_listfile(cands, os.path.join(self.wb.settings.data_dir, "cache"), self.wb.say)

    def index(self) -> SpellIndex:
        with self._lock:
            if self._index is None:
                self.state = "building"
                _key, src = self.source()
                kit = self.wb.kit.cfg
                cands = [self.wb.settings.listfile, os.path.join(getattr(kit, "work", "") or "", "listfile.csv")]
                cache = os.path.join(self.wb.settings.data_dir, "cache")
                listfile = find_listfile(cands, cache, self.wb.say)
                self._index = load_index(src, cache, listfile, self.wb.say)
                self.state = "ready"
            return self._index

    def cats(self) -> dict:
        """Where retail files each spell (spellcats.py), read once."""
        from . import spellcats as SC
        with self._lock:
            if self._cats is None:
                _key, src = self.source()
                self._cats = SC.load(src, os.path.join(self.wb.settings.data_dir, "cache"), self.wb.say)
            return self._cats

    def filters(self) -> dict:
        from . import spellcats as SC
        return SC.menus(self.cats())

    def _only(self, kind: str, key: int, sub: int) -> set | None:
        from . import spellcats as SC
        return SC.matching(self.cats(), kind, key, sub) if kind else None

    def search(self, q: str, page: int, with_models: bool, kind: str = "", key: int = 0, sub: int = 0) -> dict:
        idx = self.index()
        total, rows = idx.search(q, page, with_models, self._only(kind, key, sub))
        key_, _src = self.source()
        return {"total": total, "page": page, "rows": rows, "source": key_, "build": idx.build}

    def matching_ids(self, q: str, with_models: bool, kind: str = "", key: int = 0, sub: int = 0) -> list[int]:
        return self.index().ids(q, with_models, self._only(kind, key, sub))

    def detail(self, sid: int) -> dict:
        key, _src = self.source()
        d = self.index().detail(sid) | {"source": key}
        # an animation kit's segments as the caster's start and loop animations, retail ids
        try:
            anims = self.port.anims()
        except Exception:
            anims = None
        if anims:
            for v in d["visual_list"]:
                for e in v["events"]:
                    for a in e.get("anims", []):
                        if a.get("kit") and a.get("initial", -1) < 0 and a.get("loop", -1) < 0:
                            start, loop = anims.pair(a)
                            a["initial"] = start if start is not None else -1
                            a["loop"] = loop if loop is not None else -1
        # what each event's kit does to the unit's own body (Avenging Wrath's gold): the preview's glow
        for v in d["visual_list"]:
            for e in v["events"]:
                try:
                    e["glow"] = self.wb.creatures.kit_glow(e.get("kit") or 0)
                except Exception:
                    e["glow"] = None
        d["timing"]["radius"] = self._radius(sid)
        d["summons"] = self.summons(sid)
        d["forms"] = self.forms(sid)
        # the visual a bare 3.3.5 character gets first: retail picks a spell's visual by the caster's
        # talents, auras and spells (PlayerCondition), and a 3.3.5 character has none of retail's
        for v in d["visual_list"]:
            v["baseline"] = self._bare_player_meets(v.get("player_condition") or 0)
        d["visual_list"].sort(key=lambda x: (bool(x["difficulty"]), not x["baseline"],
                                             bool(x["player_condition"] or x["unit_condition"]), x["id"]))
        return d

    def _radius(self, sid: int) -> float:
        """The spell's area, in yards: the widest radius of its effects (SpellEffect -> SpellRadius),
        0 for none. An area's ground model is sized to it (kit flag 0x8), as in game."""
        self._effects()
        return self._radii.get(sid, 0.0)

    SUMMON_EFFECTS = (28, 56)           # SPELL_EFFECT_SUMMON, SUMMON_PET: MiscValue[0] is the creature

    def _effects(self) -> None:
        """One pass over retail's SpellEffect (and SpellShapeshift): each spell's widest radius, the
        creatures it summons, the shapeshift forms it needs."""
        if hasattr(self, "_radii"):
            return
        self._radii, self._summons, self._forms_of, self._form_rows, self._triggers = {}, {}, {}, {}, {}
        try:
            _key, src = self.source()
            radius = {i: float(r.get("Radius") or 0) for i, r in src.table("SpellRadius")}
            for _i, r in src.table("SpellEffect"):
                sid = r["SpellID"]
                for ix in (r.get("EffectRadiusIndex") or [])[:2]:
                    if ix and radius.get(ix, 0) > self._radii.get(sid, 0):
                        self._radii[sid] = radius[ix]
                if r.get("Effect") in self.SUMMON_EFFECTS:
                    npc = int((r.get("EffectMiscValue") or [0])[0] or 0)
                    if npc and npc not in self._summons.setdefault(sid, []):
                        self._summons[sid].append(npc)
                if r.get("EffectTriggerSpell"):
                    self._triggers.setdefault(sid, []).append(int(r["EffectTriggerSpell"]))
            for _i, r in src.table("SpellShapeshift"):
                mask = list(r.get("ShapeshiftMask") or [0, 0])
                forms = [w * 32 + b + 1 for w, m in enumerate(mask[:2]) for b in range(32) if int(m or 0) >> b & 1]
                if forms:
                    self._forms_of[r["SpellID"]] = forms
            self._form_rows = {i: (r.get("Name_lang") or f"form {i}", int(r.get("CreatureDisplayID") or 0))
                               for i, r in src.table("SpellShapeshiftForm")}
        except Exception as e:
            self.wb.say(f"spells: SpellEffect not read ({e})")

    def summons(self, sid: int) -> list[dict]:
        """The creatures the spell summons: retail id, name, and a display of it."""
        self._effects()
        npcs = list(self._summons.get(sid, []))
        # a spell that summons through a spell it casts (Summon Infernal -> Infernal Awakening)
        for t in self._triggers.get(sid, []):
            npcs += [n for n in self._summons.get(t, []) if n not in npcs]
        if not npcs:
            return []
        if not hasattr(self, "_npc_display"):
            self._npc_display = {}
            try:
                for did, lst in self.wb.creatures.index().names.items():
                    for cid, name in lst:
                        self._npc_display.setdefault(int(cid), (did, name))
            except Exception:
                pass
        out = []
        for npc in npcs:
            did, name = self._npc_display.get(npc, (0, ""))
            out.append({"npc": npc, "name": name or f"creature {npc}", "display": did})
        # the newest creature first: retail keeps an old one beside its replacement (Demonic Tyrant)
        out.sort(key=lambda x: (not x["display"], -x["npc"]))
        return out

    # A form's look per race, as the 3.3.5 client picks it (its druids are Night Elves and Tauren; the
    # other races are shown with the Night Elf's): retail still has these displays, with their skins.
    # Retail's own form display (SpellShapeshiftForm) is a newer race's (a Haranir bear) and gets its
    # skin from character customization, which this preview doesn't have.
    FORM_DISPLAYS = {1: {"ni": 892, "ta": 8571}, 2: {"*": 864}, 3: {"*": 632}, 4: {"*": 2428},
                     5: {"ni": 2281, "ta": 2289}, 8: {"ni": 2281, "ta": 2289}, 29: {"ni": 20857, "ta": 20872},
                     27: {"ni": 20857, "ta": 20872}, 31: {"ni": 15374, "ta": 15375}}

    def forms(self, sid: int) -> list[dict]:
        """The shapeshift forms the spell needs (SpellShapeshift): id, name, a display per race
        (``displays``: race key or "*" -> display) and retail's own (``display``)."""
        self._effects()
        out = []
        for f in self._forms_of.get(sid, []):
            name, own = self._form_rows.get(f, (f"form {f}", 0))
            per = self.FORM_DISPLAYS.get(f) or ({"*": own} if own else {})
            if "*" not in per and per:
                per = {**per, "*": per.get("ni") or next(iter(per.values()))}
            out.append({"form": f, "name": name, "display": own, "displays": per})
        return out

    # PlayerCondition lists and the logic field over each: a 3.3.5 character holds none of them
    _HELD = (("SpellID", "SpellLogic"), ("AuraSpellID", "AuraSpellLogic"), ("TraitNodeEntryID", "TraitNodeEntryLogic"))

    def _bare_player_meets(self, cond: int) -> bool:
        """Whether a character with none of retail's spells, auras or talents meets PlayerCondition
        ``cond`` (0: no condition). Each logic field: the low bits the operator (1 all, 2 any), bit
        16 + i turning the i-th term around. Other requirements in the row are not judged."""
        if not cond:
            return True
        if not hasattr(self, "_pc"):
            try:
                _key, src = self.source()
                self._pc = dict(src.table("PlayerCondition"))
            except Exception:
                self._pc = {}
        row = self._pc.get(cond)
        if not row:
            return False
        for list_name, logic_name in self._HELD:
            ids = [x for x in (row.get(list_name) or []) if x]
            if not ids:
                continue
            logic = int(row.get(logic_name) or 0)
            terms = [bool(logic >> (16 + i) & 1) for i in range(len(ids))]   # held: no; turned around: yes
            ok = any(terms) if logic & 0xFFFF == 2 else all(terms)
            if not ok:
                return False
        return True

    def model(self, fdid: int, texture: int = 0) -> dict:
        """One spell model as the viewer's mesh (its Stand - for a spell model, its one animation)."""
        k = (fdid, texture)
        if k not in self._meshes:
            if len(self._meshes) > 60:
                self._meshes.clear()
            key, src = self.source()
            tex = {t: texture for t in (2, 11, 12, 13)} if texture else {}
            self._meshes[k] = {"mesh": M.mesh(src.read, fdid, tex), "source": key}
        return self._meshes[k]

    def model_anims(self, fdid: int, ids: list[int]) -> dict:
        """A spell model's keyframes for the animations asked for that it has: its intro (Stand), its
        loop (Hold), its outro (Decay), or the ones its kit names."""
        k = ("model-anims", fdid, tuple(sorted(set(ids))))
        if k not in self._meshes:
            _key, src = self.source()
            self._meshes[k] = {str(a): v for a, v in M.anim_tracks(src.read, fdid, sorted(set(ids))).items()}
        return self._meshes[k]

    def stage(self) -> dict:
        """The caster and the target the preview casts with (when no character body is available)."""
        cr = self.wb.creatures
        return {"caster": cr.preview(CASTER_DISPLAY), "target": cr.preview(TARGET_DISPLAY)}

    def _game_anims(self, folder: str, sex: int) -> set[int] | None:
        """The animation ids your client's own character model of a race has (the WoD models carry
        retail's ids up to 808): what decides, in game, which animation a fallback lands on. None
        when the client has no such file."""
        import struct
        from ..mpq import ClientData
        k = ("game-anims", folder, sex)
        if k not in self._meshes:
            ids = None
            try:
                sexed = "Female" if sex else "Male"
                data = ClientData(self.wb.settings.client).read(f"Character\\{folder}\\{sexed}\\{folder}{sexed}.m2")
                base = 8 if data[:4] == b"MD21" else 0
                n, o = struct.unpack_from("<II", data, base + 0x1C)
                ver = struct.unpack_from("<I", data, base + 4)[0]
                stride = 0x40 if ver >= 264 else 0x44
                ids = {struct.unpack_from("<H", data, base + o + i * stride)[0] for i in range(n)}
            except Exception:
                ids = None
            self._meshes[k] = ids
        return self._meshes[k]

    def body_anims(self, race: str, sex: int, ids: list[int]) -> dict:
        """A character body's bone keyframes for the animations a spell plays on its caster
        (the body itself: /api/body)."""
        wb = self.wb
        if wb.bodies is None:
            raise LookupError("the character stand-in needs BfA's bodies (Settings: BfA from wago.tools)")
        _item, bfa = wb.race_ids("bfa", race)
        b = wb.bodies
        k = ("anims", bfa, sex, tuple(sorted(set(ids))))
        if k not in self._meshes:
            rrow = dict(b.table("ChrRaces"))[bfa]
            # an id the body lacks (retail's newer ones) plays what retail falls back to, as the game does
            try:
                data = self.port.anims().data
            except Exception:
                data = {}
            chains = {}
            for a in set(ids):
                chain, x = [a], a
                while x in data and data[x]["Fallback"] not in chain and len(chain) < 12:
                    x = data[x]["Fallback"]
                    chain.append(x)
                chains[a] = chain
            # what your game plays: the first id down the chain your client's own model has (with
            # WoD character models off, the install already stepped below 3.3.5's 505)
            game = self._game_anims(rrow.get("ClientFileString") or "", sex)
            wod = self.port.options().get("wod_models", True)
            if game is not None:
                for a, chain in chains.items():
                    keep = [x for x in chain if x in game and (wod or x <= 505)]
                    chains[a] = keep + [x for x in chain if x not in keep]
            want = sorted({x for c in chains.values() for x in c})
            got = M.anim_tracks(b.src.read, b._model_fdid(rrow, sex), want)
            out = {}
            for a, chain in chains.items():
                hit = next((x for x in chain if x in got and (x != 0 or a == 0)), None)
                if hit is not None:
                    out[str(a)] = got[hit]
            self._meshes[k] = out
        return self._meshes[k]
