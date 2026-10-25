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

Retail visuals (a port's ``retail_visuals``, on by default): the spell's SpellVisual keeps only the
caster's animations, and the whole retail visual goes into ``WXLRetailSpellVisuals.txt`` in DBFilesClient
(``TABLE_HEADER``) for the client mod wxl.retail-spellvisuals, which plays every event at its moment
with retail's delays, offsets, turns, scales and animations, and flies the missiles.
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
from .m2xform import translate

PATCH_NAME = "patch-S.MPQ"
ROOT = "Spells\\Retroport"
FLOOR = 60000                       # new SpellVisual / Kit / EffectName ids start here (and above the client's)
NO_ANIM = 0xFFFFFFFF
MAX_ANIM = 505                      # the last animation id the 3.3.5 client plays
MAX_ATTACHMENT = 52                 # the last M2 attachment point 3.3.5's models know

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


# Flying everywhere: an area flies when its AreaTable flags have 0x400 and not 0x20000000 - the
# client (IsInFlyableArea) and AzerothCore (AreaTableEntry::IsFlyable, the no-fly-zone checks and
# Dalaran's forced dismount, spell 58600) both read them. Every area of the four continents gets
# the first and loses the second; dungeons, raids and battlegrounds keep their own.
AREA_FLYABLE, AREA_NO_FLY = 0x400, 0x20000000
CONTINENTS = (0, 1, 530, 571)


def fly_everywhere(table_bytes: bytes) -> tuple[bytes, int]:
    """AreaTable.dbc with every continent area flyable; how many rows changed."""
    t = D.DBCFile.from_bytes(table_bytes, "AreaTable.dbc")
    changed = 0
    for r in t.records:
        if r[1] in CONTINENTS:
            new = (r[4] | AREA_FLYABLE) & ~AREA_NO_FLY & 0xFFFFFFFF
            if new != r[4]:
                r[4] = new
                changed += 1
    return t.to_bytes(), changed


def _f(v: float) -> int:
    return struct.unpack("<I", struct.pack("<f", float(v)))[0]


class Anims:
    """Retail's caster animations as the 3.3.5 client plays them.

    Retail names a kit's animation directly (SpellVisualAnim's initial and loop ids) or, in most newer
    spells, through an animation kit: segments played in order, the last one looping
    (AnimKitSegment). ``pair`` reads either as a start and a loop. ``fit`` makes an id one the client
    plays: with ``wod`` (WoD character models, which carry retail's ids) an id past 3.3.5's is kept and
    ``rows`` adds retail's AnimationData rows past 505 so the client walks retail's fallback chain
    itself; without it the id is followed down that chain here, to one 3.3.5's own models have."""

    def __init__(self, segments: dict, data: dict, wod: bool, have: set[int] | None = None):
        self.segments, self.data, self.wod = segments, data, wod
        self.have = have                # the ids every character body in the client has (None: unknown)
        self.used: set[int] = set()

    def pair(self, a: dict) -> tuple[int | None, int | None]:
        start = a.get("initial", -1)
        loop = a.get("loop", -1)
        if (start is None or start < 0) and (loop is None or loop < 0) and a.get("kit"):
            segs = sorted(self.segments.get(a["kit"], []))
            if len(segs) >= 2:
                start, loop = segs[0][1], segs[-1][1]
            elif segs:
                start, loop = -1, segs[0][1]
        return (start if start is not None and start >= 0 else None,
                loop if loop is not None and loop >= 0 else None)

    def fit(self, anim: int | None) -> int | None:
        if anim is None:
            return None
        if self.have:
            # the client's bodies decide: retail's fallback chain down to the first id they all
            # have (a body lacking an id plays nothing in game, it doesn't fall back by itself)
            a, seen = anim, set()
            while a not in self.have and a not in seen:
                seen.add(a)
                row = self.data.get(a)
                if not row:
                    break
                a = int(row["Fallback"])
            if a in self.have:
                if a == 0 and anim != 0:    # the chain ends on Stand: better no animation
                    return None
                if a > MAX_ANIM:
                    self.used.add(a)
                return a
        if anim <= MAX_ANIM:
            return anim
        if self.wod:
            self.used.add(anim)
            return anim
        seen = set()
        while anim > MAX_ANIM and anim not in seen:
            seen.add(anim)
            row = self.data.get(anim)
            if not row:
                return None
            anim = row["Fallback"]
        return anim if 0 < anim <= MAX_ANIM else None

    def rows(self, table) -> int:
        """Retail's AnimationData rows past the client's into ``table`` (3.3.5's 8 columns: id, name,
        weapon flags, body flags, flags, fallback, behavior, tier). Weapon, body and flags come from
        the first 3.3.5 animation down each one's fallback chain. How many were added."""
        have = {r[0]: r for r in table.records}
        top = max(have)
        added = 0
        for aid in sorted(self.data):
            if aid <= top:
                continue
            r = self.data[aid]
            base, seen = aid, set()
            while base not in have and base not in seen and base in self.data:
                seen.add(base)
                base = self.data[base]["Fallback"]
            like = have.get(base) or have[0]
            table.add_record([aid, table.add_string(f"Retail{aid}"), like[2], like[3], like[4],
                              int(r["Fallback"]), int(r["BehaviorID"]), int(r["BehaviorTier"])])
            added += 1
        return added


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


def plan(visual: dict, timing: dict | None = None, anims: "Anims | None" = None) -> dict:
    """Where each part of a retail visual (SpellIndex.visual) goes in 3.3.5, and what can't.
    ``timing`` (SpellIndex.timing): a ground effect retail plays once near the end of the cast
    (Black Hole's burst, 4.5 s into a 5 s cast) goes to the ground kit of the cast itself."""
    kits: dict[str, dict] = {}
    dropped: list[str] = []
    cast = (timing or {}).get("cast", 0)
    for e in visual["events"]:
        col = moment(e["start"], e["target"])
        what = f"{e['start_name']} on the {e['target_name']}"
        late = e["offset"][0] + e["kit_delay"][0]
        moved_to_cast = False
        if col is None and e["start"] == 1 and e["target"] == 3 and e["models"] and \
                (e["end"] == 13 and cast and late >= cast - 1000):
            col, moved_to_cast = "InstantAreaKit", True
        if col is None:
            if e["models"]:
                why = " (it shows on the ground while casting)" if e["start"] == 1 and e["target"] == 3 else ""
                dropped.append(f"{what}: 3.3.5 has no such moment{why} - {len(e['models'])} model(s) left out")
            continue
        kit = kits.setdefault(col, {"slots": {}, "specials": [], "anim": None, "start_anim": None, "events": [],
                                    "sound": 0})
        if not kit["sound"] and e.get("sounds"):
            kit["sound"] = e["sounds"][0]          # retail SoundKit: a SoundEntries row at install
        kit["events"].append(what)
        if moved_to_cast:
            dropped.append(f"{what}: plays when the cast ends ({cast - late} ms after retail's moment)")
        elif late:
            dropped.append(f"{what}: starts {late} ms late in retail; 3.3.5 starts it at once")
        for m in e["models"]:
            slot = ATTACH_SLOTS.get(m["attachment"])
            entry = {"fdid": m["fdid"], "path": m["path"], "scale": round((m["scale"] or 1) * (m["attach_scale"] or 1), 4),
                     "from": m["attachment_name"], "offset": [round(float(x), 4) for x in m["offset"]]}
            if slot and slot not in kit["slots"]:
                kit["slots"][slot] = entry
            elif len(kit["specials"]) < 3:
                kit["specials"].append(entry)
            else:
                dropped.append(f"{what}: no free slot for {m['path'] or m['fdid']}")
                continue
            if any(abs(x) > 0.001 for x in m.get("rotation") or ()):
                dropped.append(f"{(m['path'] or str(m['fdid'])).split('/')[-1]}: turn "
                               f"{[round(x, 2) for x in m['rotation']]} not carried (its offset is)")
            if m["delay"]:
                dropped.append(f"{(m['path'] or str(m['fdid'])).split('/')[-1]}: starts {m['delay']} s late in retail")
        for a in e.get("anims", []):
            if anims is None:
                start = a["initial"] if a["initial"] >= 0 else None
                loop = a["loop"] if a["loop"] >= 0 else None
            else:
                start, loop = anims.pair(a)
            first, main = (start, loop) if start is not None and loop is not None else (None, loop if loop is not None else start)
            if main is None or kit["anim"] is not None:
                continue
            if anims is None:
                if main > MAX_ANIM:
                    dropped.append(f"{what}: animation {main} is past 3.3.5's ({MAX_ANIM})")
                    continue
                first = first if first is not None and first <= MAX_ANIM else None
            else:
                fm, ff = anims.fit(main), anims.fit(first)
                if fm is None:
                    dropped.append(f"{what}: animation {main} has no 3.3.5 animation to stand in for it")
                    continue
                if fm != main:
                    dropped.append(f"{what}: animation {main} plays as 3.3.5's {fm}")
                main, first = fm, ff
            kit["anim"], kit["start_anim"] = main, first
    missile = None
    if visual["missiles"]:
        m = visual["missiles"][0]
        missile = {"fdid": m["fdid"], "path": m["path"], "scale": m["scale"] or 1, "attachment": m["attachment"],
                   "destination": m["destination"], "cast_offset": m["cast_offset"], "impact_offset": m["impact_offset"]}
        if len(visual["missiles"]) > 1:
            dropped.append(f"{len(visual['missiles']) - 1} more missile(s): 3.3.5 flies one")
    return {"kits": kits, "missile": missile, "dropped": dropped,
            "names": {c: KIT_NAMES.get(c, c) for c in kits}}


TABLE_PATH = "DBFilesClient\\WXLRetailSpellVisuals.txt"
TABLE_HEADER = ("# wxl.retail-spellvisuals 1: retail spell visuals, tab-separated. Lines belong to the spell above\n"
                "# them, model lines to the event above them. Times in ms, angles in radians, offsets in yards.\n"
                "# spell    id  retail_id  cast  duration  speed  launch\n"
                "# missile  path  attachment  destination  cast_offset(3)  impact_offset(3)  scale  flags  speed\n"
                "# event    start  end  start_min  start_max  end_min  end_max  target  kit_delay_min  kit_delay_max\n"
                "# model    path  attachment  offset(3)  yaw  pitch  roll  scale  delay  start_anim  anim  end_anim  alpha  flags  upright\n"
                "# area     path  per_second  lifetime  scale  flags  (copies scattered over the area while the event lasts)\n"
                "# glow     fade_in  fade_out  c0(3) c1(3) c2(3)  alpha_middle  alpha_edge  power  halo(3)  halo_px  halo_alpha\n"
                "#          (the event's unit glows while it lasts: C0 -> C1 -> C2 from its middle to its silhouette)")


def _tsv(*values) -> str:
    def one(v):
        if isinstance(v, float):
            return f"{v:.6g}"
        return str(v).replace("\t", " ").replace("\n", " ")
    return "\t".join(one(v) for v in values)


NEW_FLOOR = 200000                  # new spell ids start here (and above any id the client or server has)
INDEX_FLOOR = 900                   # new SpellCastTimes / SpellDuration / SpellRange rows start here
SERVER_TABLES = ("Spell", "SpellCastTimes", "SpellDuration", "SpellRange")

# a template that does what a retail spell of this kind does: (school, kind) -> 3.3.5 spell
# kinds: "missile" (a bolt), "instant" (no cast time, single target), "cast" (cast time, no missile),
# "ground" (area trigger), "aura" (a buff or debuff), "channel"
TEMPLATES = [
    ("missile", 4, 133, "Fireball"), ("missile", 16, 116, "Frostbolt"), ("missile", 32, 686, "Shadow Bolt"),
    ("missile", 64, 44425, "Arcane Barrage"), ("missile", 8, 403, "Lightning Bolt"), ("missile", 2, 585, "Smite"),
    ("cast", 2, 585, "Smite"), ("cast", 8, 403, "Lightning Bolt"), ("cast", 32, 686, "Shadow Bolt"),
    ("cast", 64, 30451, "Arcane Blast"), ("cast", 4, 133, "Fireball"), ("cast", 16, 116, "Frostbolt"),
    ("instant", 4, 2136, "Fire Blast"), ("instant", 32, 589, "Shadow Word: Pain"), ("instant", 16, 122, "Frost Nova"),
    ("instant", 8, 8042, "Earth Shock"), ("instant", 2, 20271, "Judgement of Light"), ("instant", 1, 78, "Heroic Strike"),
    ("ground", 4, 2120, "Flamestrike"), ("ground", 16, 10, "Blizzard"), ("ground", 32, 5740, "Rain of Fire"),
    ("ground", 8, 2484, "Earthbind Totem"), ("ground", 2, 26573, "Consecration"), ("ground", 64, 1449, "Arcane Explosion"),
    ("aura", 0, 1459, "Arcane Intellect"), ("channel", 64, 5143, "Arcane Missiles"), ("channel", 32, 689, "Drain Life"),
]


def spell_kind(visual: dict, timing: dict) -> str:
    if any(e["start"] in (9, 10) or (e["target"] == 3 and e["models"]) for e in visual["events"]):
        return "ground"
    if any(e["start"] in (11, 12) for e in visual["events"]):
        return "channel"
    if visual["missiles"]:
        return "missile"
    if any(e["start"] in (7, 8) for e in visual["events"]) and timing.get("duration", 0) > 0:
        return "aura"
    return "cast" if timing.get("cast", 0) else "instant"


def suggest_templates(visual: dict, timing: dict) -> list[dict]:
    """3.3.5 spells to borrow mechanics from, the likeliest first."""
    kind, school = spell_kind(visual, timing), timing.get("school", 0)
    first = [t for t in TEMPLATES if t[0] == kind and (t[1] & school or not t[1])]
    rest = [t for t in TEMPLATES if t[0] == kind and t not in first]
    seen, out = set(), []
    for _k, _s, sid, name in first + rest:
        if sid not in seen:
            seen.add(sid)
            out.append({"id": sid, "name": name})
    return out[:6]


class SpellPort:
    """New spells: a retail spell's name, text, icon, timing and visual on a 3.3.5 spell's mechanics,
    with ids of their own, in the client (patch-S.MPQ) and the server (its dbc folder)."""

    def __init__(self, wb, spells):
        self.wb, self.spells = wb, spells
        self._client_spells: dict[int, str] | None = None
        self._anim_tables: tuple | None = None

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
        # the first version put visuals on existing spells ({"target": ...}): those are gone
        return [p for p in self._load("ports.json", []) if p.get("template")]

    def installed(self) -> list:
        return [p for p in self._load("installed.json", []) if p.get("template")]

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

    def _layout(self, table: str):
        from ..dbclayout import DbcLayout
        dbd = getattr(self.wb.settings, "dbd", "") or ""
        if not dbd or not os.path.isdir(dbd):
            raise CreatureError("new spells need the WoWDBDefs definitions folder (Settings)")
        return DbcLayout(table, dbd)

    def client_spells(self) -> dict[int, str]:
        if self._client_spells is None:
            cd = self._client()
            t = D.RawDBC.from_bytes(self._base(cd, "DBFilesClient\\Spell.dbc"), "Spell.dbc")
            self._client_spells = {}
            for r in t.records:
                sid, name = struct.unpack_from("<I", r)[0], struct.unpack_from("<I", r, SPELL_NAME * 4)[0]
                self._client_spells[sid] = t.get_string(name)
        return self._client_spells

    def client_spell(self, sid: int) -> dict:
        names = self.client_spells()
        if sid not in names:
            raise CreatureError(f"your client has no spell {sid}")
        return {"id": sid, "name": names[sid]}

    def set_ports(self, entries: list) -> list:
        """The new spells: [{retail, visual, template, name, id?}]. A spell keeps the id it was given
        (.learn <id> keeps working); a new one gets the next free id from NEW_FLOOR."""
        names = self.client_spells()
        used = {int(e["id"]) for e in entries if e.get("id")}
        nxt = max([NEW_FLOOR - 1, *used, *(p["id"] for p in self.installed())]) + 1
        clean = []
        for e in entries:
            tpl = int(e.get("template") or 0)
            if tpl not in names:
                raise CreatureError(f"your client has no spell {tpl} to borrow mechanics from")
            sid = int(e.get("id") or 0)
            if not sid:
                sid, nxt = nxt, nxt + 1
            clean.append({"id": sid, "template": tpl, "template_name": names[tpl], "retail": int(e.get("retail") or 0),
                          "visual": int(e.get("visual") or 0), "name": str(e.get("name") or "")[:100] or f"Spell {sid}",
                          "retail_name": str(e.get("retail_name") or e.get("name") or "")[:100],
                          "retail_visuals": bool(e.get("retail_visuals", True))}
                         | ({"mount": dict(e["mount"])} if isinstance(e.get("mount"), dict) else {}))
        self._save("ports.json", clean)
        return clean

    def options(self) -> dict:
        """Install options: ``wod_models`` -- the client's characters are WoD models, which have
        retail's newer animations (on by default); ``bfa_bodies`` -- Install puts BfA's character
        bodies in the client (charport: Data\\patch-I.MPQ), whose animations spells then play."""
        return {"wod_models": True, "bfa_bodies": False, "fly_everywhere": True} | self._load("options.json", {})

    def set_options(self, opts: dict) -> dict:
        o = self.options()
        for k in ("wod_models", "bfa_bodies", "fly_everywhere"):
            if k in opts:
                o[k] = bool(opts[k])
        self._save("options.json", o)
        return o

    def anims(self, wod: bool | None = None) -> Anims:
        """The caster-animation resolver (retail's AnimKitSegment and AnimationData, read once)."""
        if self._anim_tables is None:
            _key, src = self.spells.source()
            segs: dict[int, list] = {}
            for _i, r in src.table("AnimKitSegment"):
                segs.setdefault(r["ParentAnimKitID"], []).append((r["OrderIndex"], r["AnimID"]))
            data = {i: r for i, r in src.table("AnimationData")}
            self._anim_tables = (segs, data)
        segs, data = self._anim_tables
        o = self.options()
        have = self.body_anims(bool(o["bfa_bodies"]))
        return Anims(segs, data, (o["wod_models"] or o["bfa_bodies"]) if wod is None else wod, have)

    BODY_FOLDERS = ("Human", "Orc", "Dwarf", "NightElf", "Scourge", "Tauren", "Gnome", "Troll", "BloodElf", "Draenei")

    def body_anims(self, bfa: bool) -> set[int] | None:
        """The animation ids every character body of the client has: BfA's (Data\\patch-I.MPQ) with
        ``bfa``, else the ones under it. None when no body could be read."""
        from . import charport as C
        from ..mpq import MPQ
        try:
            cd = ClientData(self.wb.settings.client)
        except Exception:
            return None
        sources = [s for label, s in cd.sources if bfa or C.PATCH_NAME.lower() not in label.lower()]
        out = None
        try:
            for folder in self.BODY_FOLDERS:
                for sex in ("Male", "Female"):
                    rel = f"Character\\{folder}\\{sex}\\{folder}{sex}.m2"
                    data = None
                    for s in sources:
                        if isinstance(s, str):
                            p = os.path.join(s, *rel.split("\\"))
                            if os.path.isfile(p):
                                with open(p, "rb") as fh:
                                    data = fh.read()
                        elif isinstance(s, MPQ):
                            data = s.read(rel)
                        if data:
                            break
                    if not data:
                        continue
                    base = 8 if data[:4] == b"MD21" else 0
                    n, o = struct.unpack_from("<II", data, base + 0x1C)
                    stride = 0x40 if struct.unpack_from("<I", data, base + 4)[0] >= 264 else 0x44
                    ids = {struct.unpack_from("<H", data, base + o + i * stride)[0] for i in range(n)}
                    out = ids if out is None else out & ids
        finally:
            cd.close()
        return out

    def add_many(self, spell_ids: list[int], limit: int = 400) -> dict:
        """New spells from many retail spells at once (a filter's whole list): each with its plain
        visual, the first 3.3.5 spell suggested for its kind as the one it works like, and its own
        name. Spells already made, and ones with no visual or no suggestion, are skipped."""
        idx = self.spells.index()
        have = {p["retail"] for p in self.ports()}
        client = self.client_spells()
        added, skipped = [], []
        for sid in spell_ids:
            if len(added) >= limit:
                skipped.append((sid, "over the limit"))
                continue
            if sid in have:
                skipped.append((sid, "made already"))
                continue
            try:
                d = self.spells.detail(sid)
            except Exception:
                skipped.append((sid, "no such spell"))
                continue
            vis = next((v for v in d["visual_list"] if not v["difficulty"]), None) or (d["visual_list"] or [None])[0]
            if not vis:
                skipped.append((sid, "no visual"))
                continue
            tpl = next((t["id"] for t in suggest_templates(vis, idx.timing(sid)) if t["id"] in client), None)
            if not tpl:
                skipped.append((sid, "no 3.3.5 spell to work like"))
                continue
            added.append({"retail": sid, "retail_name": d["name"], "visual": vis["id"], "template": tpl, "name": d["name"]})
            have.add(sid)
        ports = self.set_ports(self.ports() + added) if added else self.ports()
        return {"added": len(added), "skipped": len(skipped), "ports": ports,
                "skipped_examples": [f"{idx.names.get(s, s)}: {why}" for s, why in skipped[:8]]}

    def preview_plan(self, visual_id: int, spell_id: int = 0) -> dict:
        idx = self.spells.index()
        vis = idx.visual(visual_id)
        try:
            anims = self.anims()
        except Exception:
            anims = None
        out = plan(vis, idx.timing(spell_id) if spell_id else None, anims)
        if spell_id:
            out["templates"] = suggest_templates(vis, idx.timing(spell_id))
            out["kind"] = spell_kind(vis, idx.timing(spell_id))
        return out

    def state(self) -> dict:
        return {"ports": self.ports(), "installed": self.installed(), "patch": PATCH_NAME, "options": self.options()}

    # -- retail's text, cooldowns and icon ---------------------------------------------------
    def _retail(self, src, ids: set[int]) -> dict[int, dict]:
        out = {i: {"desc": "", "aura": "", "cd": 0, "cat_cd": 0, "gcd": 1500} for i in ids}
        for i, r in src.table("Spell"):
            if i in out:
                out[i]["desc"] = r.get("Description_lang") or ""
                out[i]["aura"] = r.get("AuraDescription_lang") or ""
        for _i, r in src.table("SpellCooldowns"):
            sid = r.get("SpellID")
            if sid in out and not r.get("DifficultyID"):
                out[sid].update(cd=r.get("RecoveryTime", 0), cat_cd=r.get("CategoryRecoveryTime", 0),
                                gcd=r.get("StartRecoveryTime", 1500))
        return out

    def _icon_paths(self, fdids: set[int]) -> dict[int, str]:
        from .creatures import find_listfile
        kit = self.wb.kit.cfg
        lf = find_listfile([self.wb.settings.listfile, os.path.join(getattr(kit, "work", "") or "", "listfile.csv")],
                           os.path.join(self.wb.settings.data_dir, "cache"))
        out = {}
        with open(lf, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                left, _, right = line.partition(";")
                if left.isdigit() and int(left) in fdids:
                    out[int(left)] = right.strip()
        return out

    # -- install -------------------------------------------------------------------------------
    def install(self, restart: bool = False, say=lambda m: None, dry: bool = False, wod: bool | None = None) -> dict:
        from .procs import Restart
        if wod is not None:
            self.set_options({"wod_models": wod})
        anims = self.anims()
        idx = self.spells.index()
        _key, src = self.spells.source()
        cd = self._client()
        client = self.wb.settings.client
        kit = self.wb.kit.cfg
        server_dbc = getattr(kit, "server_dbc", "") or ""
        ports = self.ports()
        notes: dict[int, list] = {p["id"]: [] for p in ports}
        LS = self._layout("Spell")

        # the client's tables, without this tool's patch
        spell = D.RawDBC.from_bytes(self._base(cd, "DBFilesClient\\Spell.dbc"), "Spell.dbc")
        if spell.record_size != SPELL_FIELDS * 4:
            raise CreatureError(f"the client's Spell.dbc has {spell.record_size // 4} fields, not 3.3.5's {SPELL_FIELDS}")
        sv = D.DBCFile.from_bytes(self._base(cd, "DBFilesClient\\SpellVisual.dbc"), "SpellVisual.dbc")
        kits = D.DBCFile.from_bytes(self._base(cd, "DBFilesClient\\SpellVisualKit.dbc"), "SpellVisualKit.dbc")
        names = D.DBCFile.from_bytes(self._base(cd, "DBFilesClient\\SpellVisualEffectName.dbc"), "SpellVisualEffectName.dbc")
        icons = D.DBCFile.from_bytes(self._base(cd, "DBFilesClient\\SpellIcon.dbc"), "SpellIcon.dbc")
        small = {t: D.DBCFile.from_bytes(self._base(cd, f"DBFilesClient\\{t}.dbc"), f"{t}.dbc")
                 for t in ("SpellCastTimes", "SpellDuration", "SpellRange")}
        for t, n in ((sv, VISUAL_FIELDS), (kits, KIT_FIELDS), (names, NAME_FIELDS)):
            if t.field_count != n:
                raise CreatureError(f"the client's {t.path} has {t.field_count} fields, not 3.3.5's {n}")
        # the server's own tables, as they were before this tool first wrote them
        server = self._server_bases(server_dbc) if server_dbc else None
        if server_dbc and server is None:
            notes_all = "the server dbc folder has no Spell.dbc: the server was left alone"
        else:
            notes_all = ""

        next_id = {"v": max(FLOOR, sv.max_id() + 1), "k": max(FLOOR, kits.max_id() + 1), "n": max(FLOOR, names.max_id() + 1),
                   "i": max(FLOOR, icons.max_id() + 1)}

        def new(kind):
            next_id[kind] += 1
            return next_id[kind] - 1

        # SpellCastTimes / SpellDuration / SpellRange: a row with these values (the client's own, else
        # a new one, the same id on both sides)
        def index_row(table: str, match, make) -> int:
            t = small[table]
            for r in t.records:
                if match(r):
                    if server is None or any(match(s) and s[0] == r[0] for s in server[table].records):
                        return r[0]
            rid = max(INDEX_FLOOR, t.max_id() + 1, server[table].max_id() + 1 if server else 0)
            row = make(rid)
            t.add_record(row)
            if server:
                server[table].add_record(list(row))
            return rid

        def cast_index(ms: int) -> int:
            return index_row("SpellCastTimes", lambda r: r[1] == ms and r[2] == 0 and r[3] == ms, lambda i: [i, ms, 0, ms])

        def duration_index(ms: int) -> int:
            return index_row("SpellDuration", lambda r: r[1] == ms and r[2] == 0 and r[3] == ms, lambda i: [i, ms, 0, ms])

        def range_index(yd: float) -> int:
            f = _f(yd)
            LR = self._layout("SpellRange")

            def make(i):
                row = [0] * small["SpellRange"].field_count
                row[0] = i
                row[LR.at("RangeMax", 0)] = f
                row[LR.at("RangeMax", 1)] = f
                LR.set_text(small["SpellRange"], row, "DisplayName_lang", f"{yd:g} yards")
                LR.set_text(small["SpellRange"], row, "DisplayNameShort_lang", f"{yd:g} yd")
                return row
            if server:                                     # the server's row needs its own strings
                LRs = LR

                def make_both(i):
                    row = make(i)
                    srow = list(row)
                    LRs.set_text(server["SpellRange"], srow, "DisplayName_lang", f"{yd:g} yards")
                    LRs.set_text(server["SpellRange"], srow, "DisplayNameShort_lang", f"{yd:g} yd")
                    make_both.server_row = srow
                    return row
                rid = None
                t = small["SpellRange"]
                for r in t.records:
                    if r[LR.at("RangeMin", 0)] == 0 and r[LR.at("RangeMax", 0)] == f and r[LR.at("RangeMax", 1)] == f and \
                            any(s[0] == r[0] for s in server["SpellRange"].records):
                        return r[0]
                rid = max(INDEX_FLOOR, t.max_id() + 1, server["SpellRange"].max_id() + 1)
                t.add_record(make_both(rid))
                server["SpellRange"].add_record(make_both.server_row)
                return rid
            return index_row("SpellRange", lambda r: r[LR.at("RangeMin", 0)] == 0 and r[LR.at("RangeMax", 0)] == f, make)

        files: dict[str, bytes] = {}
        exported: dict[int, str] = {}
        from . import sounds as SND
        sound_table = D.DBCFile.from_bytes(self._base(cd, SND.TABLE), "SoundEntries.dbc")
        sounds = SND.SoundPort(src, self.spells.listfile(), sound_table, SND.SPELL_RANGE, cd.exists)
        effect_names: dict[tuple, int] = {}
        stems: set[str] = set()

        moved: dict[tuple, str] = {}            # (fdid, offset) -> the .mdx path of a moved copy
        from . import physics as PH
        phys_of: dict[int, bytes | None] = {}   # fdid -> its retail .phys
        phys_rows: list[tuple] = []             # (keys, .phys, shift) for WXLSpellPhysics.phy2

        def placed(entry, port_notes) -> str:
            """The model's .mdx path as the kit hangs it: its retail offset moved into the file (a copy
            per offset, beside the original: same textures). The kit scales the model, so the offset
            is divided by the scale first."""
            base = exported.get(entry["fdid"], "")
            off = tuple(entry.get("offset") or (0.0, 0.0, 0.0))
            if not base or not any(abs(x) > 0.001 for x in off):
                return base
            key = (entry["fdid"], off, entry["scale"])
            if key in moved:
                return moved[key]
            folder, stem = base.rsplit("\\", 1)[0], base.rsplit("\\", 1)[1].rsplit(".", 1)[0]
            new_stem = f"{stem}_o{len([k for k in moved if k[0] == entry['fdid']]) + 1}"
            scale = entry["scale"] or 1.0
            try:
                for name in [n for n in files if n.startswith(folder + "\\" + stem)]:
                    rest = name[len(folder) + 1 + len(stem):]
                    if not (rest.startswith(".") or rest[:1].isdigit()):
                        continue                    # another model's file (a longer stem in the folder)
                    data = files[name]
                    if rest == ".m2":
                        data = translate(data, tuple(x / scale for x in off))
                    files[f"{folder}\\{new_stem}{rest}"] = data
            except ValueError as e:
                port_notes.append(f"{(entry['path'] or str(entry['fdid'])).split('/')[-1]}: offset not carried ({e})")
                moved[key] = base
                return base
            moved[key] = f"{folder}\\{new_stem}.mdx"
            if phys_of.get(entry["fdid"]):
                phys_rows.append(([moved[key]], phys_of[entry["fdid"]], tuple(x / scale for x in off)))
            return moved[key]

        def export(entry, port_notes) -> str:
            """The model's .mdx path in the patch, exported the first time ('' when it can't be)."""
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
                    return ""
                files.update(ex.files)
                exported[fdid] = ex.dbc_model_name
                try:
                    phys_of[fdid] = PH.phys_bytes(src.read(fdid), src.read)
                except Exception:
                    phys_of[fdid] = None
                if phys_of[fdid]:
                    phys_rows.append(([ex.model_path, ex.dbc_model_name], phys_of[fdid], None))
            return exported[fdid]

        def model(entry, port_notes) -> int:
            if not export(entry, port_notes):
                return 0
            path = placed(entry, port_notes)
            key = (path, entry["scale"])
            if key not in effect_names:
                eid = new("n")
                row = [0] * NAME_FIELDS
                row[0] = eid
                row[1] = names.add_string(path.rsplit("\\", 1)[-1].rsplit(".", 1)[0])
                row[2] = names.add_string(path)
                row[3], row[4], row[5], row[6] = _f(1.0), _f(entry["scale"]), _f(0.01), _f(100.0)
                names.add_record(row)
                effect_names[key] = eid
            return effect_names[key]

        def visual_rows(vis_id: int, port_notes: list, timing: dict | None = None, anims_only: bool = False,
                        channel: bool = False) -> int:
            """A new SpellVisual for the retail visual. ``anims_only``: the caster's animations alone,
            for a spell wxl.retail-spellvisuals draws (its models are in the table it reads)."""
            pl = plan(idx.visual(vis_id), timing, anims)
            if not anims_only:
                port_notes.extend(pl["dropped"])
            # a channelled spell (the 3.3.5 one it works like: Blizzard) plays its channel kit's animation
            # while it lasts, not its precast kit's: retail's cast animation goes there too
            if channel and "PrecastKit" in pl["kits"] and "ChannelKit" not in pl["kits"]:
                pre = pl["kits"]["PrecastKit"]
                pl["kits"]["ChannelKit"] = {"slots": {}, "specials": [], "anim": pre["anim"], "sound": 0,
                                            "start_anim": pre.get("start_anim"), "events": list(pre["events"])}
            vrow = [0] * VISUAL_FIELDS
            vid = new("v")
            vrow[0] = vid
            vrow[V["MissileAttachment"]] = 0xFFFFFFFF
            for col, kt in pl["kits"].items():
                if anims_only:
                    if kt["anim"] is None and not kt.get("sound"):
                        continue
                    kt = kt | {"slots": {}, "specials": []}
                krow = [0] * KIT_FIELDS
                kid = new("k")
                krow[0] = kid
                krow[K["StartAnimID"]] = kt["start_anim"] if kt.get("start_anim") is not None else NO_ANIM
                krow[K["AnimID"]] = kt["anim"] if kt["anim"] is not None else NO_ANIM
                for k in range(4):
                    krow[K["CharProc"] + k] = NO_ANIM
                if kt.get("sound"):
                    try:
                        krow[K["SoundID"]] = sounds.kit(kt["sound"])
                    except Exception as e:
                        port_notes.append(f"sound kit {kt['sound']}: not carried ({e})")
                for slot, entry in kt["slots"].items():
                    krow[K[slot]] = model(entry, port_notes)
                for k, entry in enumerate(kt["specials"]):
                    krow[K["SpecialEffect"] + k] = model(entry, port_notes)
                kits.add_record(krow)
                vrow[V[col]] = kid
            if pl["missile"] and not anims_only:
                m = pl["missile"]
                eid = model(m, port_notes)
                if eid:
                    att, dest = m["attachment"], m["destination"]
                    vrow[V["HasMissile"]] = 1
                    vrow[V["MissileModel"]] = eid
                    vrow[V["MissileAttachment"]] = (att if 0 <= att <= MAX_ATTACHMENT else -1) & 0xFFFFFFFF
                    vrow[V["MissileDestinationAttachment"]] = dest if 0 <= dest <= MAX_ATTACHMENT else 15
                    for k in range(3):
                        vrow[V["MissileCastOffset"] + k] = _f(m["cast_offset"][k])
                        vrow[V["MissileImpactOffset"] + k] = _f(m["impact_offset"][k])
            sv.add_record(vrow)
            return vid

        table: list[str] = [TABLE_HEADER]

        def retail_table(p: dict, t: dict, port_notes: list) -> None:
            """The retail visual, whole, as wxl.retail-spellvisuals plays it (TABLE_HEADER)."""
            vis = idx.visual(p["visual"])
            table.append(_tsv("spell", p["id"], p["retail"], int(t.get("cast", 0)), int(t.get("duration", 0)),
                              float(t.get("speed", 0) or 0), int(t.get("launch", 0))))
            for m in vis["missiles"]:
                path = export(m, port_notes)
                if path:
                    table.append(_tsv("missile", path, m["attachment"], m["destination"], *m["cast_offset"],
                                      *m["impact_offset"], float(m["scale"] or 1), m["flags"],
                                      float(m["missile_speed"] or 0)))
            shown = 0
            for e in vis["events"]:
                table.append(_tsv("event", e["start"], e["end"], *e["offset"], *e["end_offset"], e["target"],
                                  *e["kit_delay"]))
                for m in e["models"]:
                    path = export(m, port_notes)
                    if not path:
                        continue
                    shown += 1
                    table.append(_tsv("model", path, m["attachment"], *[float(x) for x in m["offset"]],
                                      *[float(x) for x in m["rotation"]],
                                      float((m["scale"] or 1) * (m["attach_scale"] or 1)),
                                      round(float(m["delay"] or 0) * 1000), *m["anims"],
                                      float(m["alpha"]) if m["alpha"] else 1.0, m["flags"], int(bool(m.get("upright")))))
                    if m.get("moving", m["positioner"]):
                        port_notes.append(f"{(m['path'] or str(m['fdid'])).split('/')[-1]}: moves along a scripted "
                                          f"path in retail; it stays put here")
                # what the event's kit does to the unit's own body (Avenging Wrath's golden glow)
                try:
                    g = self.wb.creatures.kit_glow(e.get("kit") or 0)
                except Exception as ex:
                    g, _ = None, port_notes.append(f"kit {e.get('kit')}: glow not read ({ex})")
                if g:
                    table.append(_tsv("glow", round(g["fade"][0] * 1000), round(g["fade"][1] * 1000),
                                      *[float(x) for c in g["colors"] for x in c], float(g["alphas"][0]),
                                      float(g["alphas"][1]), float(g["power"]), *[float(x) for x in g["halo"]],
                                      float(g["halo_width"]), float(g["halo_alpha"])))
                    port_notes.append(f"body glow on the {'caster' if e['target'] == 1 else 'target'}")
                for a in e.get("area_models", []):
                    path = export(a, port_notes)
                    if path:
                        shown += 1
                        table.append(_tsv("area", path, float(a["rate"]), int(a["lifetime"]), float(a["scale"] or 1),
                                          int(a["flags"])))
            port_notes.append(f"retail visuals: {shown} model(s) and {len(vis['missiles'])} missile(s), "
                              f"drawn by wxl.retail-spellvisuals")

        retail = self._retail(src, {p["retail"] for p in ports}) if ports else {}
        icon_fdids = {idx.misc.get(p["retail"], (0,) * 7)[6] for p in ports} - {0}
        icon_paths = self._icon_paths(icon_fdids) if icon_fdids else {}
        icon_ids: dict[int, int] = {}

        def icon(fdid: int, port_notes) -> int:
            if not fdid:
                return 0
            if fdid not in icon_ids:
                path = icon_paths.get(fdid, "")
                stem = os.path.splitext(os.path.basename(path))[0] if path else f"retroport_{fdid}"
                game_path = f"Interface\\Icons\\{stem}"
                if not cd.exists(game_path + ".blp"):
                    try:
                        files[game_path + ".blp"] = src.read(fdid)
                    except Exception as e:
                        port_notes.append(f"icon {fdid}: not exported ({e})")
                        icon_ids[fdid] = 0
                        return 0
                iid = new("i")
                icons.add_record([iid, icons.add_string(game_path)])
                icon_ids[fdid] = iid
            return icon_ids[fdid]

        server_ids = {struct.unpack_from("<I", r)[0] for r in server["Spell"].records} if server else set()
        client_ids = set(self.client_spells())
        made = []
        for p in ports:
            pn = notes[p["id"]]
            if p["id"] in client_ids or p["id"] in server_ids:
                pn.append(f"id {p['id']} is taken by a spell of the game: left out")
                continue
            tpl_rec = spell.find_by_id(p["template"])
            if tpl_rec is None:
                pn.append(f"template {p['template']} is not in the client: left out")
                continue
            t = idx.timing(p["retail"])
            r = retail.get(p["retail"], {})
            misc = idx.misc.get(p["retail"], (0,) * 7)
            use_mod = p.get("retail_visuals", True) and bool(p["visual"])
            channel = bool(LS.get(list(struct.unpack(f"<{SPELL_FIELDS}I", tpl_rec)), "AttributesEx") & (0x4 | 0x40))
            vid = visual_rows(p["visual"], pn, t, anims_only=use_mod, channel=channel) if p["visual"] else 0
            if use_mod:
                retail_table(p, t, pn)
            iid = icon(misc[6], pn)

            def build(rec: bytes, table: D.RawDBC) -> list[int]:
                row = list(struct.unpack(f"<{SPELL_FIELDS}I", rec))
                LS.set(row, "ID", p["id"])
                for col in ("Name_lang", "NameSubtext_lang", "Description_lang", "AuraDescription_lang"):
                    start, width = LS[col]
                    row[start:start + width] = [0] * width
                LS.set_text(table, row, "Name_lang", p["name"])
                if r.get("desc"):
                    LS.set_text(table, row, "Description_lang", _plain(r["desc"]))
                if r.get("aura"):
                    LS.set_text(table, row, "AuraDescription_lang", _plain(r["aura"]))
                LS.set(row, "CastingTimeIndex", cast_index(int(t.get("cast", 0))))
                if t.get("duration", 0) > 0 and LS.get(row, "DurationIndex"):
                    LS.set(row, "DurationIndex", duration_index(int(t["duration"])))
                if t.get("range"):
                    LS.set(row, "RangeIndex", range_index(float(t["range"])))
                if t.get("speed"):
                    LS.set(row, "Speed", _f(t["speed"]))
                LS.set(row, "RecoveryTime", int(r.get("cd", 0)))
                LS.set(row, "CategoryRecoveryTime", int(r.get("cat_cd", 0)))
                LS.set(row, "Category", 0)                   # no shared cooldown with the template
                if r.get("gcd") is not None:
                    LS.set(row, "StartRecoveryTime", int(r["gcd"]))
                if t.get("school"):
                    LS.set(row, "SchoolMask", int(t["school"]))
                LS.set(row, "SpellVisualID", vid, 0)
                LS.set(row, "SpellVisualID", 0, 1)
                if iid:
                    LS.set(row, "SpellIconID", iid)
                LS.set(row, "ActiveIconID", 0)
                LS.set(row, "SpellClassSet", 0)              # talents of the template's class don't touch it
                for k in range(3):
                    LS.set(row, "SpellClassMask", 0, k)
                LS.set(row, "DescriptionVariablesID", 0)
                LS.set(row, "SpellLevel", 1)
                LS.set(row, "BaseLevel", 1)
                LS.set(row, "MaxLevel", 0)
                mount = p.get("mount")
                if mount:
                    # a mount (the Mounts page): the mounted aura shows its creature, the speed auras its
                    # speeds (base points: % faster - 1, as 3.3.5's own mount spells have them)
                    for k in range(3):
                        aura = LS.get(row, "EffectAura", k)
                        if aura == 78:
                            LS.set(row, "EffectMiscValue", int(mount.get("entry") or 0), k)
                        elif aura == 32:
                            LS.set(row, "EffectBasePoints", int(mount.get("ground") or 99) & 0xFFFFFFFF, k)
                        elif aura == 207:
                            LS.set(row, "EffectBasePoints", int(mount.get("flying") or 279) & 0xFFFFFFFF, k)
                return row

            spell.add_row(build(tpl_rec, spell))
            if server:
                srec = server["Spell"].find_by_id(p["template"])
                if srec is None:
                    pn.append(f"template {p['template']} is not in the server's Spell.dbc: the server can't cast it")
                else:
                    server["Spell"].add_row(build(srec, server["Spell"]))
            trig = [LS.get(list(struct.unpack(f"<{SPELL_FIELDS}I", tpl_rec)), "EffectTriggerSpell", k) for k in range(3)]
            if any(trig):
                pn.append(f"the template triggers spell(s) {', '.join(str(x) for x in trig if x)}: those keep their own look")
            made.append(p)

        if len(table) > 1:
            files[TABLE_PATH] = ("\n".join(table) + "\n").encode("utf-8")
        if anims.wod and anims.used:
            # the client plays ids past 505 only with their rows (its fallback walk reads them)
            adata = D.DBCFile.from_bytes(self._base(cd, "DBFilesClient\\AnimationData.dbc"), "AnimationData.dbc")
            if adata.field_count == 8:
                n = anims.rows(adata)
                files["DBFilesClient\\AnimationData.dbc"] = adata.to_bytes()
                say(f"AnimationData: {n} retail animation(s) past 3.3.5's for the WoD character models")
            else:
                notes_all = (notes_all + "; " if notes_all else "") + \
                    f"the client's AnimationData.dbc has {adata.field_count} fields: retail's newer animations left out"
        if sounds.made:
            files.update(sounds.files)
            files[SND.TABLE] = sound_table.to_bytes()
            say(f"sounds: {len([x for x in sounds.made.values() if x])} retail sound kit(s), {len(sounds.files)} file(s)")
        if phys_rows:
            try:
                table, pnotes = PH.table(self.wb.kit.cfg.tools, phys_rows)
                for n in pnotes:
                    say(f"  {n}")
                if table:
                    files[PH.SPELL_TABLE] = table
                    say(f"physics: {len(phys_rows)} spell model(s) (wings, ribbons) move live with Equip Plus")
            except Exception as e:
                say(f"spell physics left out: {type(e).__name__}: {e}")
        files["DBFilesClient\\Spell.dbc"] = spell.to_bytes()
        files["DBFilesClient\\SpellVisual.dbc"] = sv.to_bytes()
        files["DBFilesClient\\SpellVisualKit.dbc"] = kits.to_bytes()
        files["DBFilesClient\\SpellVisualEffectName.dbc"] = names.to_bytes()
        files["DBFilesClient\\SpellIcon.dbc"] = icons.to_bytes()
        for tname, t in small.items():
            files[f"DBFilesClient\\{tname}.dbc"] = t.to_bytes()
        fly = self.options().get("fly_everywhere", True)
        server_area = None
        if fly:
            files["DBFilesClient\\AreaTable.dbc"], n = fly_everywhere(self._base(cd, "DBFilesClient\\AreaTable.dbc"))
            say(f"flying everywhere: {n} area(s) of the four continents made flyable (Dalaran too)")
        if server_dbc and os.path.isdir(server_dbc):
            # the server's own table as it was before this tool first changed it
            kept = os.path.join(self.dir, "server-base", "AreaTable.dbc")
            live = os.path.join(server_dbc, "AreaTable.dbc")
            if not os.path.isfile(kept) and os.path.isfile(live):
                os.makedirs(os.path.dirname(kept), exist_ok=True)
                shutil.copy2(live, kept)
            if os.path.isfile(kept):
                with open(kept, "rb") as fh:
                    base = fh.read()
                server_area = fly_everywhere(base)[0] if fly else base

        def result(extra):
            return {"ok": True, "patch": PATCH_NAME, "server": bool(server),
                    "spells": [p | {"notes": notes.get(p["id"], [])} for p in ports], "made": len(made),
                    "models": len([x for x in exported.values() if x]), "note": notes_all} | extra
        if dry:
            return result({"dry": True, "files": {k: len(v) for k, v in files.items()},
                           "table": files.get(TABLE_PATH, b"").decode("utf-8")})

        rs = None
        if restart:
            world_conf = self.wb.creatures.settings().get("world_conf", "") if server else ""
            rs = Restart(client, world_conf, say)
            rs.stop() if server else rs.stop_client()
        started = []
        try:
            backup_dir = os.path.join(self.dir, "backups", time.strftime("%Y%m%d-%H%M%S"))
            os.makedirs(backup_dir, exist_ok=True)
            patch = os.path.join(client, "Data", PATCH_NAME)
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
                say(f"Data\\{PATCH_NAME} removed: no new spells left")
            self._bodies(client, say)
            if server:
                for tname in SERVER_TABLES:
                    dest = os.path.join(server_dbc, f"{tname}.dbc")
                    if os.path.isfile(dest):
                        shutil.copy2(dest, os.path.join(backup_dir, f"server-{tname}.dbc"))
                    server[tname].save(dest)
                say(f"server: {len(made)} new spell(s) in {server_dbc}")
            if server_area is not None:
                dest = os.path.join(server_dbc, "AreaTable.dbc")
                if os.path.isfile(dest):
                    shutil.copy2(dest, os.path.join(backup_dir, "server-AreaTable.dbc"))
                with open(dest + ".part", "wb") as fh:
                    fh.write(server_area)
                os.replace(dest + ".part", dest)
                say("server: AreaTable.dbc " + ("flyable everywhere" if fly else "back to its own"))
            cache = os.path.join(client, "Cache")
            if os.path.isdir(cache):
                shutil.rmtree(cache, ignore_errors=True)
        finally:
            if rs:
                started = rs.start_all() if server else (["client"] if rs.start_client() else [])
        self._save("installed.json", made)
        shadow = [s for s in (cd.shadowed_by(f"DBFilesClient\\{t}.dbc") for t in
                              ("Spell", "SpellVisual", "SpellVisualKit", "SpellVisualEffectName", "SpellIcon")) if s]
        return result({"restarted": started, "shadowed": sorted(set(shadow))})

    def _bodies(self, client: str, say) -> None:
        """BfA's character bodies in or out of the client, as the option says. Built only when they
        are missing or an older export made them: twenty bodies take a few minutes."""
        from . import charport as C
        o = self.options()
        patch = os.path.join(client, "Data", C.PATCH_NAME)
        if not o["bfa_bodies"]:
            if C.remove(client):
                say(f"Data\\{C.PATCH_NAME} removed: the client's own character bodies are back")
            if o.get("bodies_built"):
                self._save("options.json", {k: v for k, v in o.items() if k != "bodies_built"})
            return
        if os.path.isfile(patch) and o.get("bodies_built") == C.BODIES_VERSION:
            return
        bodies = getattr(self.wb, "bodies", None)
        if bodies is None:
            say("BfA character bodies need BfA's data: add the BfA source in Settings")
            return
        exports, notes = C.export_all(bodies, client, say)
        for n in notes:
            say(n)
        if exports:
            C.install(client, exports, say)
            self._save("options.json", o | {"bodies_built": C.BODIES_VERSION})

    def _server_bases(self, server_dbc: str) -> dict | None:
        """The server's spell tables as they were before this tool first wrote them (kept in
        spells/server-base), so every install starts from the server's own rows."""
        base_dir = os.path.join(self.dir, "server-base")
        os.makedirs(base_dir, exist_ok=True)
        out = {}
        for tname in SERVER_TABLES:
            live = os.path.join(server_dbc, f"{tname}.dbc")
            kept = os.path.join(base_dir, f"{tname}.dbc")
            if not os.path.isfile(kept):
                if not os.path.isfile(live):
                    return None
                shutil.copy2(live, kept)
            out[tname] = D.RawDBC.load(kept) if tname == "Spell" else D.DBCFile.load(kept)
        return out


def _plain(text: str) -> str:
    """Retail's description markup the 3.3.5 client doesn't read: $@spelldesc and the like, colour
    codes kept. Its $s1 numbers read the template's effects."""
    text = re.sub(r"\$@\w+\d*", "", text or "")
    return text.strip()
