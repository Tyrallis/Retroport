"""Spell visuals for a 3.3.5 client: a retail spell's visual on one of the client's own spells.

Retail: a visual is events, each starting a kit at a moment of the cast on the caster, the target
or the ground; a kit attaches models at any attachment point with an offset, a turn, a scale and a
delay (spells.py reads it). 3.3.5: SpellVisual names one kit per moment (``MOMENTS``: PrecastKit,
CastKit, ImpactKit, StateKit, ChannelKit, the area kits) and a missile model; a SpellVisualKit has
fixed model slots (head, chest, base, hands, breath, three specials) and one animation. So:

  * each retail event goes to the 3.3.5 moment that starts at the same point of the cast, for its
    target (``moment``); events of one moment share its kit;
  * each model goes to the slot hanging at its attachment point (``ATTACH_SLOTS``), else a free
    special slot; its scale is the attachment's times the effect's;
  * the first missile becomes the visual's missile, with its attachment points and offsets;
  * the kit's animation is the event's (its initial one, a state's loop), when 3.3.5 has the id.

The models stay retail models (no conversion): they are exported as Creatures exports a creature's
(model, skins, .anim files, textures by FileDataID, multi-texture particles baked) under
``Spells\\Retroport\\<model>\\`` for the client's wxl.modern-m2 mod, and named by new
SpellVisualEffectName rows. The client's Spell.dbc row of the chosen 3.3.5 spell then points at the
new SpellVisual. Everything goes into ``Data\\patch-S.MPQ``, rebuilt from the client's own tables on
every install, so taking a port out restores the spell's own visual. The server needs nothing: the
client draws visuals from its own tables.

Not carried (3.3.5 kits have no field for them, listed per port): an event's start delay, a model's
offset and turn, a precast effect on the target or the ground, sounds, and animation ids past 3.3.5's.
"""

from __future__ import annotations

import os
import re
import shutil
import struct
import time

from .. import dbc as D
from ..mpq import ClientData, write_archive
from .creatures import CreatureError, export_display

PATCH_NAME = "patch-S.MPQ"
ROOT = "Spells\\Retroport"
FLOOR = 60000                       # new SpellVisual / Kit / EffectName ids start here (and above the client's)
NO_ANIM = 0xFFFFFFFF
MAX_ANIM = 505                      # the last animation id the 3.3.5 client plays

SPELL_FIELDS, SPELL_VISUAL, SPELL_NAME = 234, 131, 136
VISUAL_FIELDS, KIT_FIELDS, NAME_FIELDS = 32, 38, 7
V = {"PrecastKit": 1, "CastKit": 2, "ImpactKit": 3, "StateKit": 4, "StateDoneKit": 5, "ChannelKit": 6,
     "HasMissile": 7, "MissileModel": 8, "MissileDestinationAttachment": 10, "CasterImpactKit": 14,
     "TargetImpactKit": 15, "MissileAttachment": 16, "InstantAreaKit": 23, "ImpactAreaKit": 24,
     "PersistentAreaKit": 25, "MissileCastOffset": 26, "MissileImpactOffset": 29}
K = {"StartAnimID": 1, "AnimID": 2, "HeadEffect": 3, "ChestEffect": 4, "BaseEffect": 5, "LeftHandEffect": 6,
     "RightHandEffect": 7, "BreathEffect": 8, "LeftWeaponEffect": 9, "RightWeaponEffect": 10, "SpecialEffect": 11,
     "WorldEffect": 14, "SoundID": 15, "CharProc": 17}
KIT_NAMES = {"PrecastKit": "while casting", "CastKit": "when cast", "ImpactKit": "on impact", "StateKit": "while the aura lasts",
             "StateDoneKit": "when the aura ends", "ChannelKit": "while channelling", "CasterImpactKit": "on the caster at impact",
             "InstantAreaKit": "on the ground when cast", "ImpactAreaKit": "on the ground at impact",
             "PersistentAreaKit": "on the ground while it lasts"}
# a retail attachment point -> the 3.3.5 kit slot hanging there
ATTACH_SLOTS = {1: "RightHandEffect", 22: "RightHandEffect", 2: "LeftHandEffect", 21: "LeftHandEffect",
                -1: "BaseEffect", 0: "BaseEffect", 19: "BaseEffect", 11: "HeadEffect", 20: "HeadEffect",
                18: "HeadEffect", 15: "ChestEffect", 16: "ChestEffect", 34: "ChestEffect", 17: "BreathEffect"}
SLOT_NAMES = {"RightHandEffect": "right hand", "LeftHandEffect": "left hand", "BaseEffect": "base", "HeadEffect": "head",
              "ChestEffect": "chest", "BreathEffect": "breath", "SpecialEffect": "special"}


def _f(v: float) -> int:
    return struct.unpack("<I", struct.pack("<f", float(v)))[0]


def moment(start: int, target: int) -> str | None:
    """The 3.3.5 SpellVisual kit column for a retail event's start and target (1 caster, 3 ground,
    else the target), or None."""
    ground, caster = target == 3, target == 1
    if start == 1:
        return "PrecastKit" if caster else None
    if start == 3:
        return "CastKit" if caster else "InstantAreaKit" if ground else "ImpactKit"
    if start in (5, 6):
        return "CasterImpactKit" if caster else "ImpactAreaKit" if ground else "ImpactKit"
    if start == 7:
        return "PersistentAreaKit" if ground else "StateKit"
    if start == 8:
        return None if ground else "StateDoneKit"
    if start == 9:
        return "PersistentAreaKit"
    if start == 11:
        return "ChannelKit" if caster else "StateKit"
    return None


def plan(visual: dict) -> dict:
    """Where each part of a retail visual (SpellIndex.visual) goes in 3.3.5, and what can't."""
    kits: dict[str, dict] = {}
    dropped: list[str] = []
    for e in visual["events"]:
        col = moment(e["start"], e["target"])
        what = f"{e['start_name']} on the {e['target_name']}"
        if col is None:
            if e["models"]:
                dropped.append(f"{what}: 3.3.5 has no such moment ({len(e['models'])} model(s) left out)")
            continue
        kit = kits.setdefault(col, {"slots": {}, "specials": [], "anim": None, "events": []})
        kit["events"].append(what)
        if e["offset"][0] or e["kit_delay"][0]:
            dropped.append(f"{what}: starts {e['offset'][0] + e['kit_delay'][0]} ms late in retail; 3.3.5 starts it at once")
        for m in e["models"]:
            slot = ATTACH_SLOTS.get(m["attachment"])
            entry = {"fdid": m["fdid"], "path": m["path"], "scale": round((m["scale"] or 1) * (m["attach_scale"] or 1), 4),
                     "from": m["attachment_name"]}
            if slot and slot not in kit["slots"]:
                kit["slots"][slot] = entry
            elif len(kit["specials"]) < 3:
                kit["specials"].append(entry)
            else:
                dropped.append(f"{what}: no free slot for {m['path'] or m['fdid']}")
                continue
            if any(abs(x) > 0.01 for x in m["offset"]):
                dropped.append(f"{(m['path'] or str(m['fdid'])).split('/')[-1]}: offset "
                               f"{[round(x, 2) for x in m['offset']]} not carried (3.3.5 kits hang a model at its point)")
            if m["delay"]:
                dropped.append(f"{(m['path'] or str(m['fdid'])).split('/')[-1]}: starts {m['delay']} s late in retail")
        for a in e.get("anims", []):
            anim = a["loop"] if col in ("StateKit", "ChannelKit") and a["loop"] >= 0 else a["initial"] if a["initial"] >= 0 else a["loop"]
            if anim is None or anim < 0:
                continue
            if anim > MAX_ANIM:
                dropped.append(f"{what}: animation {anim} is past 3.3.5's ({MAX_ANIM})")
            elif kit["anim"] is None:
                kit["anim"] = anim
        sounds = [o for o in e["other"] if o.startswith("sound")]
        if sounds:
            dropped.append(f"{what}: sounds not carried yet")
    missile = None
    if visual["missiles"]:
        m = visual["missiles"][0]
        missile = {"fdid": m["fdid"], "path": m["path"], "scale": m["scale"] or 1, "attachment": m["attachment"],
                   "destination": m["destination"], "cast_offset": m["cast_offset"], "impact_offset": m["impact_offset"]}
        if len(visual["missiles"]) > 1:
            dropped.append(f"{len(visual['missiles']) - 1} more missile(s): 3.3.5 flies one")
    return {"kits": kits, "missile": missile, "dropped": dropped,
            "names": {c: KIT_NAMES.get(c, c) for c in kits}}


class SpellPort:
    """The ports (retail visual -> a 3.3.5 spell) and their install."""

    def __init__(self, wb, spells):
        self.wb, self.spells = wb, spells
        self._client_spells: dict[int, str] | None = None

    @property
    def dir(self) -> str:
        d = os.path.join(self.wb.settings.data_dir, "spells")
        os.makedirs(d, exist_ok=True)
        return d

    def _load(self, name, default):
        import json
        try:
            with open(os.path.join(self.dir, name), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return default

    def _save(self, name, value) -> None:
        import json
        p = os.path.join(self.dir, name)
        with open(p + ".part", "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=1)
        os.replace(p + ".part", p)

    def ports(self) -> list:
        return self._load("ports.json", [])

    def installed(self) -> list:
        return self._load("installed.json", [])

    def _client(self) -> ClientData:
        """The client as this tool's patch sees it, the patch itself left out: what an install
        builds on (else every install would build on its own last rows)."""
        client = self.wb.settings.client
        if not client or not os.path.isdir(os.path.join(client, "Data")):
            raise CreatureError("Settings has no 3.3.5 client folder")
        cd = ClientData(client, top=PATCH_NAME)
        cd.sources = [s for s in cd.sources
                      if os.path.basename(s[1] if isinstance(s[1], str) else s[1].path).lower() != PATCH_NAME.lower()]
        return cd

    def _base(self, cd: ClientData, name: str) -> bytes:
        hit = cd.find(name)
        if hit is None:
            raise CreatureError(f"the client has no {name}")
        return hit[1]

    def client_spells(self) -> dict[int, str]:
        if self._client_spells is None:
            cd = self._client()
            data = self._base(cd, "DBFilesClient\\Spell.dbc")
            t = D.DBCFile.from_bytes(data, "Spell.dbc")
            self._client_spells = {r[0]: t.get_string(r[SPELL_NAME]) for r in t.records}
        return self._client_spells

    def client_spell(self, sid: int) -> dict:
        names = self.client_spells()
        if sid not in names:
            raise CreatureError(f"your client has no spell {sid}")
        return {"id": sid, "name": names[sid]}

    def set_ports(self, entries: list) -> list:
        clean, seen = [], set()
        names = self.client_spells()
        for e in entries:
            target = int(e.get("target") or 0)
            if not target or target in seen:
                continue
            if target not in names:
                raise CreatureError(f"your client has no spell {target}")
            seen.add(target)
            clean.append({"target": target, "target_name": names[target], "retail": int(e.get("retail") or 0),
                          "visual": int(e.get("visual") or 0), "name": str(e.get("name") or "")[:100]})
        self._save("ports.json", clean)
        return clean

    def preview_plan(self, visual_id: int) -> dict:
        return plan(self.spells.index().visual(visual_id))

    def state(self) -> dict:
        return {"ports": self.ports(), "installed": self.installed(), "patch": PATCH_NAME}

    # -- install -------------------------------------------------------------------------------
    def install(self, restart: bool = False, say=lambda m: None, dry: bool = False) -> dict:
        from .procs import Restart
        idx = self.spells.index()
        _key, src = self.spells.source()
        cd = self._client()
        client = self.wb.settings.client
        ports = self.ports()
        notes: dict[int, list] = {}

        # the client's tables, without this tool's patch
        spell = bytearray(self._base(cd, "DBFilesClient\\Spell.dbc"))
        sv = D.DBCFile.from_bytes(self._base(cd, "DBFilesClient\\SpellVisual.dbc"), "SpellVisual.dbc")
        kits = D.DBCFile.from_bytes(self._base(cd, "DBFilesClient\\SpellVisualKit.dbc"), "SpellVisualKit.dbc")
        names = D.DBCFile.from_bytes(self._base(cd, "DBFilesClient\\SpellVisualEffectName.dbc"), "SpellVisualEffectName.dbc")
        for t, n in ((sv, VISUAL_FIELDS), (kits, KIT_FIELDS), (names, NAME_FIELDS)):
            if t.field_count != n:
                raise CreatureError(f"the client's {t.path} has {t.field_count} fields, not 3.3.5's {n}")
        next_id = {"v": max(FLOOR, sv.max_id() + 1), "k": max(FLOOR, kits.max_id() + 1), "n": max(FLOOR, names.max_id() + 1)}

        def new(kind):
            next_id[kind] += 1
            return next_id[kind] - 1

        files: dict[str, bytes] = {}
        exported: dict[int, str] = {}           # model FileDataID -> its .mdx path
        effect_names: dict[tuple, int] = {}     # (fdid, scale) -> SpellVisualEffectName id
        stems: set[str] = set()

        def model(entry, port_notes) -> int:
            fdid = entry["fdid"]
            if fdid not in exported:
                stem = re.sub(r"[^A-Za-z0-9_]+", "_", os.path.splitext(os.path.basename(entry["path"] or f"model{fdid}"))[0]) or f"model{fdid}"
                if stem.lower() in stems:
                    stem = f"{stem}_{fdid}"
                stems.add(stem.lower())
                say(f"exporting {entry['path'] or fdid}")
                try:
                    ex = export_display(src.read, {"model": fdid, "t": [0, 0, 0, 0]}, stem, ROOT)
                except Exception as e:
                    port_notes.append(f"{entry['path'] or fdid}: not exported ({e})")
                    exported[fdid] = ""
                    return 0
                files.update(ex.files)
                port_notes.extend(n for n in ex.notes if "baked" in n or "inlined" in n or "stayed external" in n)
                exported[fdid] = ex.dbc_model_name
            if not exported[fdid]:
                return 0
            key = (fdid, entry["scale"])
            if key not in effect_names:
                eid = new("n")
                row = [0] * NAME_FIELDS
                row[0] = eid
                row[1] = names.add_string(os.path.basename(exported[fdid]).rsplit(".", 1)[0])
                row[2] = names.add_string(exported[fdid])
                row[3], row[4], row[5], row[6] = _f(1.0), _f(entry["scale"]), _f(0.01), _f(100.0)
                names.add_record(row)
                effect_names[key] = eid
            return effect_names[key]

        visual_of: dict[int, int] = {}
        for p in ports:
            port_notes = notes.setdefault(p["target"], [])
            if not p["visual"]:
                continue
            pl = plan(idx.visual(p["visual"]))
            port_notes.extend(pl["dropped"])
            vrow = [0] * VISUAL_FIELDS
            vid = new("v")
            vrow[0] = vid
            vrow[V["MissileAttachment"]] = 0xFFFFFFFF
            for col, kit in pl["kits"].items():
                krow = [0] * KIT_FIELDS
                kid = new("k")
                krow[0] = kid
                krow[K["StartAnimID"]] = NO_ANIM
                krow[K["AnimID"]] = kit["anim"] if kit["anim"] is not None else NO_ANIM
                for k in range(4):
                    krow[K["CharProc"] + k] = NO_ANIM
                for slot, entry in kit["slots"].items():
                    krow[K[slot]] = model(entry, port_notes)
                for k, entry in enumerate(kit["specials"]):
                    krow[K["SpecialEffect"] + k] = model(entry, port_notes)
                kits.add_record(krow)
                vrow[V[col]] = kid
            if pl["missile"]:
                m = pl["missile"]
                eid = model(m, port_notes)
                if eid:
                    vrow[V["HasMissile"]] = 1
                    vrow[V["MissileModel"]] = eid
                    vrow[V["MissileAttachment"]] = m["attachment"] & 0xFFFFFFFF
                    vrow[V["MissileDestinationAttachment"]] = max(0, m["destination"])
                    for k in range(3):
                        vrow[V["MissileCastOffset"] + k] = _f(m["cast_offset"][k])
                        vrow[V["MissileImpactOffset"] + k] = _f(m["impact_offset"][k])
            sv.add_record(vrow)
            visual_of[p["target"]] = vid

        # the 3.3.5 spells: their first visual -> the new one
        recs, fields, size = struct.unpack_from("<3I", spell, 4)
        if fields != SPELL_FIELDS:
            raise CreatureError(f"the client's Spell.dbc has {fields} fields, not 3.3.5's {SPELL_FIELDS}")
        found = set()
        for i in range(recs):
            at = 20 + i * size
            sid = struct.unpack_from("<I", spell, at)[0]
            if sid in visual_of:
                struct.pack_into("<I", spell, at + SPELL_VISUAL * 4, visual_of[sid])
                found.add(sid)
        for sid in set(visual_of) - found:
            notes.setdefault(sid, []).append("not in the client's Spell.dbc: nothing changed")

        files["DBFilesClient\\Spell.dbc"] = bytes(spell)
        files["DBFilesClient\\SpellVisual.dbc"] = sv.to_bytes()
        files["DBFilesClient\\SpellVisualKit.dbc"] = kits.to_bytes()
        files["DBFilesClient\\SpellVisualEffectName.dbc"] = names.to_bytes()

        if dry:                                 # a test build: what it would write
            return {"ok": True, "dry": True, "files": {k: len(v) for k, v in files.items()},
                    "ports": [p | {"visual_id": visual_of.get(p["target"]), "notes": notes.get(p["target"], [])} for p in ports],
                    "rows": {"visual": sv.records[-len(visual_of):] if visual_of else [], "kits": kits.records[-12:],
                             "names": [(r[0], names.get_string(r[2]), struct.unpack("<f", struct.pack("<I", r[4]))[0])
                                       for r in names.records if r[0] >= FLOOR]}}
        # the client holds its patches open: close it for the write when asked, start it after
        rs = None
        if restart:
            rs = Restart(client, "", say)
            rs.stop_client()
        try:
            patch = os.path.join(client, "Data", PATCH_NAME)
            backup_dir = os.path.join(self.dir, "backups", time.strftime("%Y%m%d-%H%M%S"))
            os.makedirs(backup_dir, exist_ok=True)
            if os.path.isfile(patch):
                shutil.copy2(patch, os.path.join(backup_dir, PATCH_NAME))
            if ports:
                tmp = patch + ".part"
                write_archive(tmp, files)
                try:
                    os.replace(tmp, patch)
                except PermissionError:
                    os.remove(tmp)
                    raise CreatureError(f"{PATCH_NAME} is in use - close World of Warcraft and install again")
                say(f"Data\\{PATCH_NAME}: {len(files)} files, {os.path.getsize(patch) / 1048576:.1f} MB")
            elif os.path.isfile(patch):
                os.remove(patch)
                say(f"Data\\{PATCH_NAME} removed: no ports left")
            cache = os.path.join(client, "Cache")
            if os.path.isdir(cache):
                shutil.rmtree(cache, ignore_errors=True)
        finally:
            restarted = rs.start_client() if rs else False
        self._save("installed.json", ports)
        shadow = [s for s in (cd.shadowed_by(f"DBFilesClient\\{t}.dbc") for t in
                              ("Spell", "SpellVisual", "SpellVisualKit", "SpellVisualEffectName")) if s]
        return {"ok": True, "patch": PATCH_NAME, "ports": [p | {"visual_id": visual_of.get(p["target"]),
                                                               "notes": notes.get(p["target"], [])} for p in ports],
                "models": len([x for x in exported.values() if x]), "restarted": restarted,
                "shadowed": sorted(set(shadow))}
