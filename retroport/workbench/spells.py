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

INDEX_VERSION = 1
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
        counts: dict[int, int] = {}
        for sid, vis in xv.items():
            seen = set()
            for v, *_rest in vis:
                for e in ev.get(v, []):
                    seen |= {en[n][0] for n in kit_models.get(e[7], ()) if n in en and en[n][0]}
                setid = sv.get(v, (0,))[0]
                seen |= {en[m[0]][0] for m in ms.get(setid, []) if m[0] in en and en[m[0]][0]}
            if seen:
                counts[sid] = len(seen)
        say("spells: naming models from the listfile")
        wanted = {x[0] for x in en.values() if x[0]}
        paths = {}
        with open(listfile, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                left, _, right = line.partition(";")
                if left.isdigit() and int(left) in wanted:
                    paths[int(left)] = right.strip()
        return cls({"version": INDEX_VERSION, "build": src.build, "names": names, "xv": xv, "sv": sv, "ev": ev,
                    "kit": kit, "ke": ke, "ma": ma, "en": en, "ms": ms, "anim": anim, "misc": misc, "cast": cast,
                    "dur": dur, "rng": rng, "counts": counts, "paths": paths, "_order": None})

    # -- answers --------------------------------------------------------------------------
    def _rows(self) -> list:
        if self._order is None:
            # spells with models first (most models first), then by id, newest first
            self._order = sorted(self.names, key=lambda i: (-min(self.counts.get(i, 0), 1), -i))
        return self._order

    def search(self, q: str, page: int, with_models: bool) -> tuple[int, list[dict]]:
        q = q.strip().lower()
        hits = []
        if q.isdigit() and int(q) in self.names:
            hits.append(int(q))
        terms = q.split()
        for sid in self._rows():
            if with_models and sid not in self.counts:
                continue
            if terms and not all(t in self.names[sid].lower() for t in terms):
                continue
            if hits and sid == hits[0]:
                continue
            hits.append(sid)
        return len(hits), [self.row(s) for s in hits[page * PAGE:(page + 1) * PAGE]]

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
            models, other, anims = [], {}, []
            for t, e in self.ke.get(kid, []):
                if t == 2 and e in self.ma:
                    a = self.ma[e]
                    mdl = self._model(a[0])
                    if not mdl:
                        continue
                    models.append(mdl | {"attach_id": e, "attachment": a[1], "attachment_name": ATTACHMENTS.get(a[1], f"point {a[1]}"),
                                         "positioner": a[2], "offset": list(a[3]), "rotation": list(a[4]), "attach_scale": a[5],
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
                           "kit_delay": [dmin, dmax], "models": models, "anims": anims,
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
        self.state = "idle"
        from .spellport import SpellPort
        self.port = SpellPort(wb, self)

    def source(self):
        return self.wb.creatures.source()

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

    def search(self, q: str, page: int, with_models: bool) -> dict:
        idx = self.index()
        total, rows = idx.search(q, page, with_models)
        key, _src = self.source()
        return {"total": total, "page": page, "rows": rows, "source": key, "build": idx.build}

    def detail(self, sid: int) -> dict:
        key, _src = self.source()
        return self.index().detail(sid) | {"source": key}

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

    def stage(self) -> dict:
        """The caster and the target the preview casts with (when no character body is available)."""
        cr = self.wb.creatures
        return {"caster": cr.preview(CASTER_DISPLAY), "target": cr.preview(TARGET_DISPLAY)}

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
            self._meshes[k] = {str(a): v for a, v in M.anim_tracks(b.src.read, b._model_fdid(rrow, sex), sorted(set(ids))).items()}
        return self._meshes[k]
