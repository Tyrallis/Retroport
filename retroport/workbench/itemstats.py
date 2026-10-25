"""The Stats step: what each backported piece is in game.

The kit makes every look a cosmetic copy - any class, level 1, no stats. Here each piece gets
its item level and required level, quality, who may wear it, its armour type, stats, armour,
weapon damage and speed, sockets and socket bonus, durability, price, binding, a description,
and item sets with their set bonuses. The page works the numbers out (WotLK's own rules, see
``wotlk``) and keeps them in ``<data>/item-stats.json``:

    {"global": {field: value},                every piece's value unless the piece says otherwise
     "pieces": {"<retail display>": {...}},    a piece's own values (and its worked-out stats)
     "sets":   [{"key", "name", "pieces": [display...], "bonuses": [[pieces needed, spell]]}]}

A piece is the kit's item for one look (the kit makes one item per retail display id; its
``ids.json`` says which entry). At Install the kit's own output is left as it made it, and:

* ``out/sql/retroport-items.sql`` - the kit's item SQL, then one UPDATE per piece with its stats
  (the one file to apply);
* the kit's ``out/dbc/Item.dbc`` - a piece whose armour type changed gets that subclass (and its
  material) before the kit packs, so the client's and the server's tables agree with the SQL;
* item sets - ``ItemSet.dbc`` rows (ids from 3000, kept per set) added to the client's own table
  inside the kit's patch and to the server's, with ``item_template.itemset`` on their pieces.

Set bonuses are spells the 3.3.5 client already has: the bonuses of its own item sets, with
their text, to choose from.
"""

from __future__ import annotations

import json
import os
import re
import threading

# 3.3.5a's classes (id -> name); AllowableClass bit = 1 << (id - 1)
CLASSES = {1: "Warrior", 2: "Paladin", 3: "Hunter", 4: "Rogue", 5: "Priest", 6: "Death Knight", 7: "Shaman",
           8: "Mage", 9: "Warlock", 11: "Druid"}
ALL_CLASSES = sum(1 << (c - 1) for c in CLASSES)
QUALITIES = {0: "Poor", 1: "Common", 2: "Uncommon", 3: "Rare", 4: "Epic", 5: "Legendary", 6: "Artifact", 7: "Heirloom"}
BONDING = {0: "No binding", 1: "Binds when picked up", 2: "Binds when equipped", 3: "Binds when used"}
ARMOUR_TYPES = {1: "Cloth", 2: "Leather", 3: "Mail", 4: "Plate"}
MATERIAL = {1: 7, 2: 8, 3: 5, 4: 6}                     # the Material an armour type sounds like
SOCKETS = {1: "Meta", 2: "Red", 4: "Yellow", 8: "Blue", 14: "Prismatic"}
# item_template stat types (ItemModType): name, "base" (white +N line) or "equip" (green Equip: line), cost
STATS = {
    0: ("Mana", "base", 0.5), 1: ("Health", "base", 0.5), 3: ("Agility", "base", 1), 4: ("Strength", "base", 1),
    5: ("Intellect", "base", 1), 6: ("Spirit", "base", 1), 7: ("Stamina", "base", 2 / 3),
    12: ("Defense rating", "equip", 1), 13: ("Dodge rating", "equip", 1), 14: ("Parry rating", "equip", 1),
    15: ("Block rating", "equip", 1), 31: ("Hit rating", "equip", 1), 32: ("Critical strike rating", "equip", 1),
    35: ("Resilience rating", "equip", 1), 36: ("Haste rating", "equip", 1), 37: ("Expertise rating", "equip", 1),
    38: ("Attack power", "equip", 0.5), 39: ("Ranged attack power", "equip", 0.4), 43: ("Mana per 5 sec.", "equip", 2),
    44: ("Armor penetration rating", "equip", 1), 45: ("Spell power", "equip", 6 / 7), 46: ("Health per 5 sec.", "equip", 2),
    47: ("Spell penetration", "equip", 1), 48: ("Block value", "equip", 0.65),
    16: ("Melee hit rating", "equip", 1), 17: ("Ranged hit rating", "equip", 1), 18: ("Spell hit rating", "equip", 1),
    19: ("Melee critical strike rating", "equip", 1), 20: ("Ranged critical strike rating", "equip", 1),
    21: ("Spell critical strike rating", "equip", 1), 28: ("Melee haste rating", "equip", 1),
    29: ("Ranged haste rating", "equip", 1), 30: ("Spell haste rating", "equip", 1),
}
RANGED = {2: 2, 3: 3, 18: 2, 16: 0, 19: 0}               # weapon subclass -> ammo type (bow/crossbow arrows, gun bullets)
SET_ID_START = 3000                                      # the client's own item sets end at 901
_lock = threading.Lock()


def empty() -> dict:
    return {"global": {}, "pieces": {}, "sets": []}


def load(data_dir: str) -> dict:
    try:
        with open(os.path.join(data_dir, "item-stats.json"), encoding="utf-8") as fh:
            d = json.load(fh)
        return {"global": dict(d.get("global") or {}), "pieces": dict(d.get("pieces") or {}),
                "sets": list(d.get("sets") or [])}
    except (OSError, ValueError, AttributeError):
        return empty()


def save(data_dir: str, edits: dict) -> None:
    if not isinstance(edits, dict) or not isinstance(edits.get("pieces", {}), dict):
        raise ValueError("the stats are an object with global, pieces and sets")
    clean = {"global": dict(edits.get("global") or {}), "pieces": dict(edits.get("pieces") or {}),
             "sets": list(edits.get("sets") or [])}
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, "item-stats.json")
    # the page saves as you type: two saves at once must not share the temporary file, and Windows
    # refuses a replace while another reader has the file open for a moment - try again briefly
    with _lock:
        with open(path + ".part", "w", encoding="utf-8") as fh:
            json.dump(clean, fh, indent=1)
        for attempt in range(20):
            try:
                os.replace(path + ".part", path)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                import time
                time.sleep(0.05)


def effective(edits: dict, display, field: str, default=None):
    """A piece's value for ``field``: its own, else every piece's (global), else ``default``.
    "" and None mean "not set"."""
    own = (edits.get("pieces") or {}).get(str(display), {}).get(field)
    if own not in (None, ""):
        return own
    g = (edits.get("global") or {}).get(field)
    return g if g not in (None, "") else default


def touched(edits: dict, display) -> bool:
    """Whether a piece has anything to write (otherwise it stays the kit's cosmetic copy)."""
    p = (edits.get("pieces") or {}).get(str(display), {})
    fields = ("ilvl", "req", "quality", "classes", "armor_type", "bonding")
    return bool((p.get("heirloom") or {}).get("on") or p.get("stats") or p.get("armor") or p.get("dmg_max") or any(effective(edits, display, f) not in (None, "")
                                                                            for f in fields))


# -- the kit's output -------------------------------------------------------------------------
_TOKEN = re.compile(r"'((?:[^'\\]|''|\\.)*)'|(-?\d+(?:\.\d+)?)")


def kit_items(sql_text: str) -> dict[int, dict]:
    """The kit's item_template rows (entry -> {column: value}) from its INSERT."""
    m = re.search(r"INSERT INTO `item_template` \(([^)]*)\) VALUES\s*(.*?);\s*$", sql_text, re.S | re.M)
    if not m:
        return {}
    cols = [c.strip(" `") for c in m.group(1).split(",")]
    out = {}
    for row in re.findall(r"\((.*?)\)(?=,\s*\(|\s*$)", m.group(2).strip(), re.S):
        vals = []
        for s, n in _TOKEN.findall(row):
            vals.append(s.replace("''", "'") if n == "" else (float(n) if "." in n else int(n)))
        if len(vals) == len(cols):
            rec = dict(zip(cols, vals))
            out[int(rec["entry"])] = rec
    return out


def _q(s: str) -> str:
    return "'" + str(s).replace("\\", "\\\\").replace("'", "''") + "'"


def piece_sets(edits: dict, set_ids: dict) -> dict[str, int]:
    """retail display -> the item set id its piece belongs to (its first set)."""
    out = {}
    for s in edits.get("sets") or []:
        sid = set_ids.get(s.get("key"))
        if sid:
            for d in s.get("pieces") or []:
                out.setdefault(str(d), sid)
    return out


# AzerothCore's item_template columns, as its worldserver reads them (BuyPrice as int32). MySQL
# refuses an UPDATE with a value outside its column - the whole piece's UPDATE - and the piece stays
# the kit's level-1 copy; so every value is kept inside. (AzerothCore has no StatsCount column: it
# counts the stats it loads.)
INT32, UINT32 = (-2 ** 31, 2 ** 31 - 1), (0, 2 ** 32 - 1)
LIMITS = {"Quality": (0, 7), "ItemLevel": (0, 65535), "RequiredLevel": (0, 255), "bonding": (0, 255),
          "AllowableClass": INT32, "subclass": (0, 255), "Material": (-128, 127), "armor": UINT32, "block": UINT32,
          "MaxDurability": (0, 65535), "SellPrice": UINT32, "BuyPrice": (0, INT32[1]), "dmg_min1": (0, INT32[1]),
          "dmg_max1": (0, INT32[1]), "dmg_type1": (0, 255), "delay": (0, 65535), "ammo_type": (0, 255),
          "maxcount": INT32, "socketBonus": INT32, "itemset": UINT32, "Flags": UINT32,
          "ScalingStatDistribution": (-32768, 32767), "ScalingStatValue": UINT32,
          **{f"stat_type{k}": (0, 255) for k in range(1, 11)}, **{f"stat_value{k}": INT32 for k in range(1, 11)},
          **{f"socketColor_{k}": (-128, 127) for k in range(1, 4)}, **{f"socketContent_{k}": INT32 for k in range(1, 4)}}


def column_value(col: str, v):
    """``v`` kept inside ``col``'s range (text and floats as they are)."""
    lo, hi = LIMITS.get(col, (None, None))
    return min(max(v, lo), hi) if lo is not None and isinstance(v, int) and not isinstance(v, bool) else v


def updates(edits: dict, ids: dict, kit: dict[int, dict], set_ids: dict, names: dict | None = None,
            scalings: dict | None = None) -> list[str]:
    """One UPDATE per touched piece (the kit's row stays as it wrote it otherwise). ``names``: the name
    each look has in the workbench (the item the basket chose): the kit names a look after the first
    retail item of it, which may be another one that shares it - a piece named otherwise gets the
    workbench's name (a name typed on the Stats page wins over both)."""
    out = []
    sets = piece_sets(edits, set_ids)
    for display, entry in sorted(((str(d), e) for d, e in (ids.get("item") or {}).items()), key=lambda t: t[1]):
        row = kit.get(int(entry))
        if row is None:
            continue
        in_set = sets.get(display)
        p = (edits.get("pieces") or {}).get(display, {})
        name = p.get("name") or (names or {}).get(display)
        renamed = bool(name) and name != row.get("name")
        if not (touched(edits, display) or in_set):
            if renamed:                                     # nothing else to give it: its name only
                out.append(f"UPDATE `item_template` SET `name` = {_q(name)} WHERE `entry` = {int(entry)};")
            continue
        cls, sub, inv = row.get("class", 0), row.get("subclass", 0), row.get("InventoryType", 0)
        set_ = {}
        if renamed:
            set_["name"] = _q(name)
        for col, field in (("Quality", "quality"), ("ItemLevel", "ilvl"), ("RequiredLevel", "req"), ("bonding", "bonding")):
            v = (edits.get("global") or {}).get(field)              # for every piece only (the page sets no other)
            if v not in (None, ""):
                set_[col] = int(v)
        classes = effective(edits, display, "classes")
        if classes not in (None, ""):
            classes = int(classes)
            set_["AllowableClass"] = -1 if classes in (0, -1) or classes & ALL_CLASSES == ALL_CLASSES else classes
        at = effective(edits, display, "armor_type")
        if at and cls == 4 and sub in ARMOUR_TYPES and inv != 16 and int(at) in ARMOUR_TYPES:
            set_["subclass"], set_["Material"] = int(at), MATERIAL[int(at)]
        stats = [(int(t), int(v)) for t, v in (p.get("stats") or []) if int(t) in STATS and int(v)][:10]
        for k in range(10):
            t, v = stats[k] if k < len(stats) else (0, 0)
            set_[f"stat_type{k + 1}"], set_[f"stat_value{k + 1}"] = t, v
        for col, field in (("armor", "armor"), ("block", "block"), ("MaxDurability", "durability"), ("SellPrice", "sell")):
            v = p.get(field)
            if v not in (None, ""):
                set_[col] = max(0, int(v))
        if "SellPrice" in set_:
            set_["BuyPrice"] = set_["SellPrice"] * 4
        if cls == 2 and p.get("dmg_max"):
            set_["dmg_min1"], set_["dmg_max1"] = int(p.get("dmg_min") or 0), int(p["dmg_max"])
            set_["dmg_type1"] = 0
            set_["delay"] = int(p.get("delay") or 2000)
            if sub in RANGED:
                set_["RangedModRange"] = 100
                set_["ammo_type"] = RANGED[sub]
        if effective(edits, display, "unique"):
            set_["maxcount"] = 1
        sockets = [int(c) for c in (p.get("sockets") or []) if int(c) in SOCKETS][:3]
        for k in range(3):
            set_[f"socketColor_{k + 1}"] = sockets[k] if k < len(sockets) else 0
            set_[f"socketContent_{k + 1}"] = 0
        set_["socketBonus"] = int(p.get("socket_bonus") or 0) if sockets else 0
        set_["itemset"] = in_set or 0
        if p.get("description") is not None:
            set_["description"] = _q(p.get("description") or "")
        sc = (scalings or {}).get(display)
        if sc:
            # an heirloom: its stats come from its distribution at the wearer's level, none of its own;
            # Heirloom quality, bound to the account
            set_["ScalingStatDistribution"], set_["ScalingStatValue"] = sc["id"], sc["mask"]
            for k in range(10):
                set_[f"stat_type{k + 1}"], set_[f"stat_value{k + 1}"] = 0, 0
            set_["Quality"], set_["bonding"], set_["RequiredLevel"] = 7, 1, 1     # worn from level 1, as Blizzard's
            set_["Flags"] = (int(row.get("Flags") or 0) | BOA_FLAG) & 0xFFFFFFFF
        out.append("UPDATE `item_template` SET " + ", ".join(f"`{k}` = {column_value(k, v)}" for k, v in set_.items()) +
                   f" WHERE `entry` = {int(entry)};")
    return out


def write_sql(work: str, edits: dict, set_ids: dict, names: dict | None = None,
              scalings: dict | None = None) -> str | None:
    """``<work>/out/sql/retroport-items.sql``: the kit's item SQL, then the Stats step's UPDATEs (and
    the workbench's name for each look the kit named after another item - see ``updates``)."""
    kit_path = os.path.join(work, "out", "sql", "item_template.sql")
    ids = _json(os.path.join(work, "ids.json"), {})
    if not os.path.isfile(kit_path):
        return None
    text = open(kit_path, encoding="utf-8").read()
    lines = updates(edits, ids, kit_items(text), set_ids, names, scalings)
    path = os.path.join(work, "out", "sql", "retroport-items.sql")
    with open(path + ".part", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text.rstrip() + "\n\n-- Retroport Workbench, the Stats step: levels, stats, armor, damage, sockets, "
                 f"sets ({len(lines)} items)\n" + "\n".join(lines) + "\n")
    os.replace(path + ".part", path)
    return path


def apply_item_dbc(work: str, edits: dict) -> bool:
    """The kit's ``out/dbc/Item.dbc`` with each piece's armour type (subclass and material) - the
    kit's own values for the others. True when the file changed (the kit must pack again)."""
    from ..dbc import DBCFile
    path = os.path.join(work, "out", "dbc", "Item.dbc")
    kit_sql = os.path.join(work, "out", "sql", "item_template.sql")
    if not (os.path.isfile(path) and os.path.isfile(kit_sql)):
        return False
    ids = _json(os.path.join(work, "ids.json"), {})
    kit = kit_items(open(kit_sql, encoding="utf-8").read())
    dbc = DBCFile.from_bytes(open(path, "rb").read())
    by_id = {r[0]: r for r in dbc.records}
    changed = False
    for display, entry in (ids.get("item") or {}).items():
        row, orig = by_id.get(int(entry)), kit.get(int(entry))
        if row is None or orig is None:
            continue
        sub, mat = orig.get("subclass", row[2]), orig.get("Material", row[4])
        at = effective(edits, display, "armor_type")
        if at and orig.get("class") == 4 and sub in ARMOUR_TYPES and orig.get("InventoryType") != 16 and int(at) in ARMOUR_TYPES:
            sub, mat = int(at), MATERIAL[int(at)]
        if (row[2], row[4]) != (sub, mat):
            row[2], row[4] = sub, mat
            changed = True
    if changed:
        with open(path + ".part", "wb") as fh:
            fh.write(dbc.to_bytes())
        os.replace(path + ".part", path)
    return changed


# -- item sets ----------------------------------------------------------------------------------
def set_ids(data_dir: str, sets: list[dict]) -> dict[str, int]:
    """Each set's ItemSet id, kept per set key (a set keeps its id when it's renamed or changed)."""
    path = os.path.join(data_dir, "item-set-ids.json")
    with _lock:
        known = _json(path, {})
        nxt = max([SET_ID_START - 1, *known.values()]) + 1
        for s in sets:
            k = s.get("key")
            if k and k not in known:
                known[k], nxt = nxt, nxt + 1
        with open(path + ".part", "w", encoding="utf-8") as fh:
            json.dump(known, fh, indent=1)
        os.replace(path + ".part", path)
        return known


def set_rows(edits: dict, ids: dict, sids: dict) -> list[dict]:
    """The sets as ItemSet rows: {id, name, items (entries, 17 at most), bonuses [(needed, spell)]}."""
    entries = {str(d): int(e) for d, e in (ids.get("item") or {}).items()}
    out = []
    for s in edits.get("sets") or []:
        sid = sids.get(s.get("key"))
        items = [entries[str(d)] for d in s.get("pieces") or [] if str(d) in entries][:17]
        if not sid or not items:
            continue
        bonuses = sorted(((int(n), int(sp)) for n, sp in (s.get("bonuses") or []) if int(n) > 0 and int(sp) > 0))[:8]
        out.append({"id": sid, "name": s.get("name") or f"Set {sid}", "items": items, "bonuses": bonuses})
    return out


def itemset_dbc(base: bytes, rows: list[dict], owned: set[int]) -> bytes:
    """``base`` (an ItemSet.dbc) with ``rows`` in it - rows of ids in ``owned`` (ours, from before)
    replaced, every other row kept."""
    from ..dbc import DBCFile
    dbc = DBCFile.from_bytes(base)
    if dbc.field_count != 53:
        raise ValueError(f"ItemSet.dbc has {dbc.field_count} fields, not 3.3.5a's 53")
    flags = dbc.records[0][17] if dbc.records else 0
    dbc.records = [r for r in dbc.records if r[0] not in owned and r[0] not in {x["id"] for x in rows}]
    for x in rows:
        name = dbc.add_string(x["name"])
        rec = [x["id"]] + [name] * 16 + [flags]
        rec += (x["items"] + [0] * 17)[:17]
        rec += ([sp for _n, sp in x["bonuses"]] + [0] * 8)[:8]
        rec += ([n for n, _sp in x["bonuses"]] + [0] * 8)[:8]
        rec += [0, 0]
        dbc.records.append(rec)
    dbc.records.sort(key=lambda r: r[0])
    return dbc.to_bytes()


# -- what the 3.3.5 client offers ---------------------------------------------------------------
_SUB = re.compile(r"\$(\d*)(s|m)([1-3])|\$(\d*)h|\$(\d*)d")


def _duration(ms: int) -> str:
    if ms <= 0:
        return "until cancelled"
    sec = ms // 1000
    if sec >= 3600 and sec % 3600 == 0:
        return f"{sec // 3600} hour" + ("s" if sec >= 7200 else "")
    if sec >= 60 and sec % 60 == 0:
        return f"{sec // 60} min"
    return f"{sec} sec"


def spell_text(text: str, row: list[int], spells: dict | None = None, durations: dict | None = None) -> str:
    """A spell's description with its numbers in: $s1/$m1 (its effects' points), $h (its proc
    chance), $d (its duration), and $12345s1 (another spell's) - other placeholders are left."""
    def num(m):
        if m.group(5) is not None:                          # $d / $12345d: duration
            r = (spells or {}).get(int(m.group(5))) if m.group(5) else row
            ms = (durations or {}).get(r[40]) if r else None
            return _duration(ms) if ms is not None else m.group(0)
        if m.group(4) is not None:                          # $h / $12345h: proc chance
            r = (spells or {}).get(int(m.group(4))) if m.group(4) else row
            return str(r[35]) if r else m.group(0)
        r = (spells or {}).get(int(m.group(1))) if m.group(1) else row
        if r is None:
            return m.group(0)
        k = int(m.group(3)) - 1
        base, dice = _signed(r[80 + k]), r[74 + k]
        lo = base + 1
        return f"{lo} to {base + dice}" if dice > 1 else str(abs(lo))
    return _SUB.sub(num, text or "")


def _signed(v: int) -> int:
    return v - (1 << 32) if v & 0x80000000 else v


def client_options(client_dir: str, socket_bonus_ids: set[int] | None = None) -> dict:
    """Set bonus spells (every bonus of the client's own item sets, with its text and the sets that
    have it) and socket bonuses (the enchantments WotLK items use as one)."""
    from ..dbc import DBCFile
    from ..mpq import ClientData
    cd = ClientData(client_dir)
    try:
        sets = DBCFile.from_bytes(cd.read("DBFilesClient\\ItemSet.dbc"))
        spells = DBCFile.from_bytes(cd.read("DBFilesClient\\Spell.dbc"))
        enchants = DBCFile.from_bytes(cd.read("DBFilesClient\\SpellItemEnchantment.dbc"))
        durations = {r[0]: _signed(r[1]) for r in DBCFile.from_bytes(cd.read("DBFilesClient\\SpellDuration.dbc")).records}
    finally:
        cd.close()
    by_spell = {r[0]: r for r in spells.records}
    bonus: dict[int, dict] = {}
    for r in sets.records:
        set_name = sets.get_string(r[1])
        for k in range(8):
            sp, need = r[35 + k], r[43 + k]
            row = by_spell.get(sp)
            if not sp or row is None:
                continue
            b = bonus.setdefault(sp, {"spell": sp, "name": spells.get_string(row[136]),
                                      "text": spell_text(spells.get_string(row[170]), row, by_spell, durations),
                                      "sets": [], "pieces": need})
            if len(b["sets"]) < 4:
                b["sets"].append(set_name)
    sockets = []
    for r in enchants.records:
        if socket_bonus_ids is not None and r[0] not in socket_bonus_ids:
            continue
        name = enchants.get_string(r[14])
        if name:
            sockets.append({"id": r[0], "name": name})
    return {"bonuses": sorted(bonus.values(), key=lambda b: b["text"].lower()),
            "socket_bonuses": sorted(sockets, key=lambda s: s["name"].lower())}


def spell_lookup(client_dir: str, spell_id: int) -> dict | None:
    from ..dbc import DBCFile
    from ..mpq import ClientData
    cd = ClientData(client_dir)
    try:
        spells = DBCFile.from_bytes(cd.read("DBFilesClient\\Spell.dbc"))
        durations = {r[0]: _signed(r[1]) for r in DBCFile.from_bytes(cd.read("DBFilesClient\\SpellDuration.dbc")).records}
    finally:
        cd.close()
    row = spells.find_by_id(spell_id)
    if row is None:
        return None
    by_spell = {r[0]: r for r in spells.records}
    return {"spell": spell_id, "name": spells.get_string(row[136]),
            "text": spell_text(spells.get_string(row[170]), row, by_spell, durations)}


def _json(path: str, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


# -- heirlooms: stats that grow with the wearer's level --------------------------------------------
# A piece with "heirloom" on gets a ScalingStatDistribution row (its stats as shares of a budget, up
# to a max level) and item_template.ScalingStatDistribution/ScalingStatValue: the client and the
# server work its stats out from ScalingStatValues.dbc at the wearer's level (AzerothCore:
# value = Bonus * budget(level) / 10000). Its stats on the page are what it has at its max level.
SCALING_ID_START = 3000                     # the client's own distributions end in the hundreds
SSD_FIELDS, SSV_FIELDS = 22, 24
BOA_FLAG = 0x08000000                       # ITEM_FLAG_IS_BOUND_TO_ACCOUNT
# ScalingStatValues columns (3.3.5: id, level, then these) and the ScalingStatValue bit naming each
SSV_COLUMNS = ["ShoulderBudget", "TrinketBudget", "WeaponBudget1H", "RangedBudget", "ClothShoulderArmor",
               "LeatherShoulderArmor", "MailShoulderArmor", "PlateShoulderArmor", "WeaponDPS1H", "WeaponDPS2H",
               "SpellcasterDPS1H", "SpellcasterDPS2H", "RangedDPS", "WandDPS", "SpellPower", "PrimaryBudget",
               "TertiaryBudget", "ClothCloakArmor", "ClothChestArmor", "LeatherChestArmor", "MailChestArmor",
               "PlateChestArmor"]
BUDGET_BITS = {0x1: "ShoulderBudget", 0x2: "TrinketBudget", 0x4: "WeaponBudget1H", 0x8: "PrimaryBudget",
               0x10: "RangedBudget", 0x40000: "TertiaryBudget"}
SHOULDER_ARMOR = {1: 0x20, 2: 0x40, 3: 0x80, 4: 0x100}
CHEST_ARMOR = {1: 0x100000, 2: 0x200000, 3: 0x400000, 4: 0x800000}
CASTER_ROLES = ("caster", "healer")


def scaling_mask(inv: int, cls: int, sub: int, armor_type: int | None, role: str | None) -> int:
    """The ScalingStatValue a piece of this slot and kind gets, as Blizzard's heirlooms have them:
    the budget its stats scale with, and its armor or weapon damage. (3.3.5 has armor columns for
    shoulders, chests and cloaks only: other slots keep the armor the item has.)"""
    at = int(armor_type or sub or 0)
    caster = (role or "") in CASTER_ROLES
    if cls == 2:                                        # weapons
        if sub == 19:
            return 0x10 | 0x4000                          # wand
        if sub in (2, 3, 18, 16) or inv in (15, 25, 26):
            return 0x10 | 0x2000                          # bow, gun, crossbow, thrown
        two_hand = inv == 17
        if caster:
            return 0x8 | (0x1000 if two_hand else 0x800) | 0x8000
        return (0x8 | 0x400) if two_hand else (0x4 | 0x200)
    if inv == 3:
        return 0x1 | SHOULDER_ARMOR.get(at, 0)
    if inv in (5, 20):
        return 0x8 | CHEST_ARMOR.get(at, 0)
    if inv == 16:
        return 0x8 | 0x80000
    if inv == 12:
        return 0x2
    return 0x8


def budget_column(mask: int) -> str:
    for bit, name in BUDGET_BITS.items():
        if mask & bit:
            return name
    return "PrimaryBudget"


def scaling_values(client_dir: str) -> dict[int, dict]:
    """The client's ScalingStatValues: level -> {column: value}."""
    from ..dbc import DBCFile
    from ..mpq import ClientData
    cd = ClientData(client_dir)
    try:
        t = DBCFile.from_bytes(cd.read("DBFilesClient\\ScalingStatValues.dbc"))
    finally:
        cd.close()
    if t.field_count != SSV_FIELDS:
        raise ValueError(f"ScalingStatValues.dbc has {t.field_count} fields, not 3.3.5a's {SSV_FIELDS}")
    return {r[1]: dict(zip(SSV_COLUMNS, r[2:])) for r in t.records}


def scaling_ids(data_dir: str, keys: list[str]) -> dict[str, int]:
    """Each heirloom piece's ScalingStatDistribution id, kept per piece."""
    path = os.path.join(data_dir, "item-scaling-ids.json")
    with _lock:
        known = _json(path, {})
        nxt = max([SCALING_ID_START - 1, *known.values()]) + 1
        for k in keys:
            if k not in known:
                known[k], nxt = nxt, nxt + 1
        with open(path + ".part", "w", encoding="utf-8") as fh:
            json.dump(known, fh, indent=1)
        os.replace(path + ".part", path)
        return known


HEIRLOOM_QUALITY = 7


def heirloom_pieces(edits: dict, displays=None) -> list[str]:
    """The heirloom pieces: those with their own box ticked, and every piece (``displays``, the kit's
    looks) when Heirloom is every piece's quality."""
    own = [d for d, p in (edits.get("pieces") or {}).items() if (p.get("heirloom") or {}).get("on")]
    if str((edits.get("global") or {}).get("quality")) == str(HEIRLOOM_QUALITY) and displays is not None:
        return sorted({*own, *(str(d) for d in displays)})
    return own


def scaling_rows(edits: dict, ids: dict, kit: dict[int, dict], ssv: dict[int, dict], sids: dict) -> dict[str, dict]:
    """retail display -> {id, mask, max, stats [(stat, bonus)]} for every heirloom piece the kit built."""
    out = {}
    for display in heirloom_pieces(edits, (ids.get("item") or {}).keys()):
        entry = (ids.get("item") or {}).get(display) or (ids.get("item") or {}).get(int(display) if display.isdigit() else display)
        row = kit.get(int(entry)) if entry else None
        sid = sids.get(display)
        if row is None or not sid:
            continue
        p = (edits.get("pieces") or {}).get(display, {})
        h = p.get("heirloom") or {}
        top = max(1, min(int(h.get("max") or (edits.get("global") or {}).get("heirloom_max") or 80), 80))
        mask = int(h.get("mask") or 0) or scaling_mask(row.get("InventoryType", 0), row.get("class", 0), row.get("subclass", 0),
                                                       effective(edits, display, "armor_type"),
                                                       effective(edits, display, "profile") or h.get("role"))
        budget = (ssv.get(top) or {}).get(budget_column(mask)) or 0
        stats = []
        for t, v in (p.get("stats") or [])[:10]:
            t, v = int(t), int(v)
            if t in STATS and v and budget:
                stats.append((t, max(1, round(v * 10000 / budget))))
        out[display] = {"id": sid, "mask": mask, "max": top, "stats": stats}
    return out


def ssd_dbc(base: bytes, rows: list[dict], owned: set[int]) -> bytes:
    """``base`` (a ScalingStatDistribution.dbc) with ``rows`` in it - ours from before replaced."""
    from ..dbc import DBCFile
    dbc = DBCFile.from_bytes(base)
    if dbc.field_count != SSD_FIELDS:
        raise ValueError(f"ScalingStatDistribution.dbc has {dbc.field_count} fields, not 3.3.5a's {SSD_FIELDS}")
    mine = {x["id"] for x in rows}
    dbc.records = [r for r in dbc.records if r[0] not in owned and r[0] not in mine]
    for x in rows:
        stats = (x["stats"] + [(-1, 0)] * 10)[:10]
        dbc.records.append([x["id"]] + [t & 0xFFFFFFFF for t, _b in stats] + [b for _t, b in stats] + [x["max"]])
    dbc.records.sort(key=lambda r: r[0])
    return dbc.to_bytes()
