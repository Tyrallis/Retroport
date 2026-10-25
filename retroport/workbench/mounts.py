"""The Mounts page: retail's mounts in the 3.3.5 client and server.

A mount is four things in 3.3.5, and Install makes each from retail's:

* its creature: the model, skins and sounds as a creature display, made by the Creatures page's
  install (``creatures.py``) - the rider sits on the model's mount attachment (0), as the client
  seats every rider, and its CreatureModelData.MountHeight is retail's;
* its spell: retail's name, icon, text and summon visual on a 3.3.5 mount spell's mechanics
  (Swift Brown Steed for a ground mount, Swift Blue Gryphon for a flyer), made by the Spells page's
  install (``spellport.py``) with the mount's speeds and its creature (the mounted aura's value);
* its item: a copy of a 3.3.5 mount item (the reins) with retail's name, quality and icon, that
  teaches the spell - item_template in the world database, its icon row (ItemDisplayInfo) and its
  Item row in the backport kit's patch;
* its speeds: ground and flight speed, from retail's mount type (a type with a flying capability
  flies), changeable per mount.

The mount list is read once per build from Mount, MountXDisplay, MountTypeXCapability,
MountCapability, ItemEffect, ItemXItemEffect, ItemSparse and Item, and kept in the cache."""

from __future__ import annotations

import json
import os
import shutil
import struct
import threading
import time

from .. import dbc as D

INDEX_VERSION = 1
PAGE = 60
GROUND_TEMPLATE = 23229             # Swift Brown Steed: mounted, +100% mounted speed
FLYING_TEMPLATE = 32242             # Swift Blue Gryphon: mounted, +280% flight, +100% mounted speed
GROUND_ITEM = 18777                 # Swift Brown Steed (the item), copied for a ground mount's item
FLYING_ITEM = 25473                 # Reins of the Swift Blue Gryphon, copied for a flyer's
ITEM_FLOOR = 950000                 # new item entries (the backport kit's start at 900000)
ITEM_DISPLAY_RANGE = (480000, 490000)   # new ItemDisplayInfo rows (the kit's start at 416000)
CAP_GROUND, CAP_FLYING, CAP_FLOAT, CAP_UNDERWATER = 0x1, 0x2, 0x4, 0x8
SPEEDS = {"ground": [59, 99], "flying": [149, 279, 309]}   # % faster, as 3.3.5's mount spells have them


def _cached(path: str, make):
    try:
        with open(path, encoding="utf-8") as fh:
            d = json.load(fh)
        if d.get("version") == INDEX_VERSION:
            return d
    except (OSError, ValueError):
        pass
    d = make() | {"version": INDEX_VERSION}
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(d, fh)
    os.replace(tmp, path)
    return d


def build_index(src, say=lambda m: None) -> dict:
    T = src.table
    say("mounts: reading Mount, MountXDisplay and the mount types")
    mounts = dict(T("Mount"))
    displays: dict[int, list] = {}
    for _i, r in T("MountXDisplay"):
        displays.setdefault(r["MountID"], []).append((0 if not r.get("PlayerConditionID") else 1, r["CreatureDisplayInfoID"]))
    caps = dict(T("MountCapability"))
    type_caps: dict[int, list] = {}
    for _i, r in T("MountTypeXCapability"):
        type_caps.setdefault(r["MountTypeID"], []).append(r["MountCapabilityID"])
    say("mounts: finding the items that teach them")
    spells = {m["SourceSpellID"]: i for i, m in mounts.items() if m.get("SourceSpellID")}
    effects = {i: r["SpellID"] for i, r in T("ItemEffect") if r["SpellID"] in spells and r.get("TriggerType") == 6}
    item_of: dict[int, int] = {}
    for _i, r in T("ItemXItemEffect"):
        sid = effects.get(r["ItemEffectID"])
        if sid and sid not in item_of:
            item_of[sid] = r["ItemID"]
    wanted = set(item_of.values())
    sparse = {i: (r.get("Display_lang") or "", int(r.get("OverallQualityID") or 1)) for i, r in T("ItemSparse") if i in wanted}
    icons = {i: int(r.get("IconFileDataID") or 0) for i, r in T("Item") if i in wanted}
    misc = {}
    for _i, r in T("SpellMisc"):
        if r["SpellID"] in spells and r["SpellID"] not in misc:
            misc[r["SpellID"]] = int(r.get("SpellIconFileDataID") or 0)
    out = {}
    for mid, m in mounts.items():
        sid = m.get("SourceSpellID") or 0
        flags = 0
        skill = 0
        for c in type_caps.get(m.get("MountTypeID"), []):
            cap = caps.get(c) or {}
            flags |= int(cap.get("Flags") or 0)
            skill = max(skill, int(cap.get("ReqRidingSkill") or 0))
        kind = "flying" if flags & CAP_FLYING else ("aquatic" if flags & CAP_UNDERWATER and not flags & CAP_GROUND else "ground")
        item = item_of.get(sid)
        name, quality = sparse.get(item, ("", 1)) if item else ("", 1)
        ds = [d for _c, d in sorted(displays.get(mid, []))]
        if not ds or not sid:
            continue
        out[str(mid)] = {"id": mid, "name": m.get("Name_lang") or f"Mount {mid}", "spell": sid, "kind": kind,
                         "type": m.get("MountTypeID"), "skill": skill, "displays": ds,
                         "description": m.get("Description_lang") or "", "source": m.get("SourceText_lang") or "",
                         "fly_height": float(m.get("MountFlyRideHeight") or 0), "icon": misc.get(sid, 0),
                         "item": {"id": item, "name": name, "quality": quality, "icon": icons.get(item, 0)} if item else None}
    say(f"mounts: {len(out):,} mounts")
    return {"build": src.build, "mounts": out}


class Mounts:
    """The Mounts page's state: the index, the mount basket, Install."""

    def __init__(self, wb):
        self.wb = wb
        self._index: dict | None = None
        self._lock = threading.Lock()
        self.job = {"state": "idle", "log": [], "steps": [], "result": None}

    # -- files -------------------------------------------------------------------------------------
    @property
    def dir(self) -> str:
        d = os.path.join(self.wb.settings.data_dir, "mounts")
        os.makedirs(d, exist_ok=True)
        return d

    def _load(self, name, default):
        try:
            with open(os.path.join(self.dir, name), encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return default

    def _save(self, name, value) -> None:
        p = os.path.join(self.dir, name)
        with open(p + ".part", "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=1)
        os.replace(p + ".part", p)

    # -- browsing ----------------------------------------------------------------------------------
    def index(self) -> dict:
        with self._lock:
            if self._index is None:
                _key, src = self.wb.creatures.source()
                path = os.path.join(self.wb.settings.data_dir, "cache", f"mounts-{src.build}.json")
                self._index = _cached(path, lambda: build_index(src, self.wb.say))
            return self._index

    def search(self, q: str, page: int, kind: str = "") -> dict:
        terms = [t for t in (q or "").lower().split() if t]
        rows = []
        for m in sorted(self.index()["mounts"].values(), key=lambda m: -m["id"]):
            if kind and m["kind"] != kind:
                continue
            hay = f"{m['name']} {m['id']} {m['spell']} {(m['item'] or {}).get('name', '')}".lower()
            if all(t in hay for t in terms):
                rows.append(m)
        key, _src = self.wb.creatures.source()
        return {"total": len(rows), "page": page, "rows": rows[page * PAGE:(page + 1) * PAGE], "source": key}

    def detail(self, mid: int) -> dict:
        m = self.index()["mounts"].get(str(mid))
        if not m:
            raise LookupError(f"no mount {mid}")
        cidx = self.wb.creatures.index()
        looks = []
        for did in m["displays"]:
            row = cidx.row(did)
            if row:
                looks.append({"display": did, "model": row["model"], "path": row["path"],
                              "textures": row["textures"]})
        return m | {"looks": looks, "speeds": SPEEDS,
                    "default_speed": {"ground": 99, "flying": 279 if m["kind"] == "flying" else 0}}

    # -- the basket --------------------------------------------------------------------------------
    def basket(self) -> list:
        return self._load("basket.json", [])

    def set_basket(self, entries: list) -> list:
        clean, seen = [], set()
        idx = self.index()["mounts"]
        for e in entries:
            mid = int(e.get("id") or 0)
            if mid in seen or str(mid) not in idx:
                continue
            seen.add(mid)
            m = idx[str(mid)]
            display = int(e.get("display") or m["displays"][0])
            clean.append({"id": mid, "name": str(e.get("name") or m["name"])[:100], "display": display,
                          "ground": int(e.get("ground") or 99),
                          "flying": int(e.get("flying") if e.get("flying") is not None else (279 if m["kind"] == "flying" else 0))})
        self._save("basket.json", clean)
        return clean

    def installed(self) -> list:
        return self._load("installed.json", [])

    def state(self) -> dict:
        return {"basket": self.basket(), "installed": self.installed(), "ids": self._load("ids.json", {}),
                "job": self.job_view(0), "creature_settings": self.wb.creatures.settings()}

    # -- Install -----------------------------------------------------------------------------------
    def job_view(self, since: int) -> dict:
        j = self.job
        return {"state": j["state"], "steps": j["steps"], "result": j["result"], "log": j["log"][since:],
                "at": len(j["log"])}

    def _say(self, msg: str) -> None:
        self.job["log"].append(time.strftime("%H:%M:%S ") + msg)
        self.wb.say(msg)

    def _step(self, name: str, state: str) -> None:
        for s in self.job["steps"]:
            if s["name"] == name:
                s["state"] = state
                return
        self.job["steps"].append({"name": name, "state": state})

    def start_install(self) -> dict:
        if self.job["state"] == "running":
            raise RuntimeError("an install is already running")
        self.job = {"state": "running", "log": [], "steps": [], "result": None}
        threading.Thread(target=self._install_guarded, daemon=True, name="mount-install").start()
        return self.job_view(0)

    def _install_guarded(self) -> None:
        from .procs import Restart
        restart = None
        try:
            st = self.wb.creatures.settings()
            if st["restart"]:
                self._step("Close the client and worldserver", "running")
                restart = Restart(self.wb.settings.client, st["world_conf"], self._say)
                restart.stop()
                self._step("Close the client and worldserver", "done")
            result = self.install()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._say(f"stopped: {type(e).__name__}: {e}")
            for s in self.job["steps"]:
                if s["state"] == "running":
                    s["state"] = "failed"
            result = {"ok": False, "error": f"{e}"}
        if restart is not None:
            self._step("Start the worldserver and client", "running")
            try:
                result["restarted"] = restart.start_all()
                self._step("Start the worldserver and client", "done")
            except Exception as e:
                self._say(f"could not start them again: {e}")
                self._step("Start the worldserver and client", "failed")
        self.job["result"] = result
        self.job["state"] = "done" if result.get("ok") else "failed"

    def install_list(self) -> list:
        basket = {int(e["id"]): e for e in self.basket()}
        out = [e for e in self.installed() if int(e["id"]) not in basket]
        return out + list(basket.values())

    def install(self) -> dict:
        wb = self.wb
        mounts = self.install_list()
        if not mounts:
            raise RuntimeError("the mount basket is empty")
        idx = self.index()["mounts"]
        cr, port = wb.creatures, wb.spells.port

        # 1. the creatures: each mount's display through the Creatures page's install
        self._step("Mount models, skins and sounds (creatures)", "running")
        basket = [e for e in cr.basket() if not e.get("mount")]
        in_game = {int(e["display"]) for e in cr.installed()}
        for m in mounts:
            if int(m["display"]) in in_game and not any(int(e["display"]) == int(m["display"]) for e in basket):
                continue                                # in the game already: kept as it is
            basket.append({"display": int(m["display"]), "name": m["name"], "subname": "Mount", "level": 1,
                           "faction": 35, "mount": True})
        cr.set_basket(basket)
        cr.job = {"state": "running", "log": [], "steps": [], "result": None}
        cr.no_restart = True
        try:
            cr._install_guarded()
        finally:
            cr.no_restart = False
        for line in cr.job["log"]:
            self.job["log"].append(line)
        if not (cr.job.get("result") or {}).get("ok"):
            raise RuntimeError(f"the creature install stopped: {(cr.job.get('result') or {}).get('error')}")
        entries = {int(k): v["entry"] for k, v in cr.ids().items()}
        self._step("Mount models, skins and sounds (creatures)", "done")

        # 2. the spells
        self._step("Mount spells", "running")
        ports = [p for p in port.ports() if not p.get("mount")]
        have = {p.get("mount", {}).get("id"): p for p in port.ports() if p.get("mount")}
        for m in mounts:
            info = idx[str(m["id"])]
            flying = int(m.get("flying") or 0) > 0
            vis = 0
            try:
                d = wb.spells.detail(info["spell"])
                vis = (d["visual_list"][0]["id"] if d["visual_list"] else 0)
            except Exception:
                pass
            old = have.get(m["id"]) or {}
            ports.append({"id": old.get("id"), "retail": info["spell"], "retail_name": info["name"], "visual": vis,
                          "template": FLYING_TEMPLATE if flying else GROUND_TEMPLATE, "name": m["name"],
                          "mount": {"id": m["id"], "display": int(m["display"]),
                                    "entry": entries.get(int(m["display"]), 0),
                                    "ground": int(m.get("ground") or 99), "flying": int(m.get("flying") or 0)}})
        port.set_ports(ports)
        res = port.install(restart=False, say=self._say)
        if not res.get("ok"):
            raise RuntimeError(f"the spell install stopped: {res.get('error')}")
        spell_of = {p["mount"]["id"]: p["id"] for p in port.ports() if p.get("mount")}
        self._step("Mount spells", "done")

        # 3. the items
        self._step("Mount items", "running")
        items = self._items(mounts, spell_of)
        self._step("Mount items", "done")

        now = [m | {"spell_id": spell_of.get(m["id"]), "item_entry": items.get(m["id"], {}).get("entry"),
                    "entry": entries.get(int(m["display"]))} for m in mounts]
        self._save("installed.json", now)
        self._save("basket.json", [])
        self._say("done: .additem <item> or .learn <spell> in game")
        return {"ok": True, "mounts": now}

    # -- items ---------------------------------------------------------------------------------------
    def _items(self, mounts: list, spell_of: dict) -> dict:
        """Each mount's item: item_template copied from a 3.3.5 mount item (the ground one or the
        flyer's), with retail's name, quality and icon, teaching the new spell; its icon row and Item
        row in the backport kit's patch (merged in, the kit's own rows kept)."""
        from .creatures import run_sql, world_db
        wb = self.wb
        idx = self.index()["mounts"]
        ids = self._load("ids.json", {})
        used = {v.get("item") for v in ids.values()}
        nxt = max([ITEM_FLOOR - 1, *[u for u in used if u]]) + 1
        lo, hi = ITEM_DISPLAY_RANGE
        disp_used = {v.get("item_display") for v in ids.values()}
        dnext = max([lo - 1, *[u for u in disp_used if u]]) + 1
        _key, src = wb.creatures.source()
        icon_paths = wb.spells.port._icon_paths({(idx[str(m["id"])].get("item") or {}).get("icon") or idx[str(m["id"])]["icon"]
                                                 for m in mounts} - {0, None})
        rows, icon_files, sql = [], {}, ["-- Retroport Workbench: mount items. Run against the world database.", ""]
        out = {}
        for m in mounts:
            info = idx[str(m["id"])]
            k = str(m["id"])
            have = ids.get(k) or {}
            entry = have.get("item")
            if not entry:
                entry, nxt = nxt, nxt + 1
            disp = have.get("item_display")
            if not disp:
                disp, dnext = dnext, dnext + 1
            ids[k] = {"item": entry, "item_display": disp}
            item = info.get("item") or {}
            icon_fdid = item.get("icon") or info["icon"]
            path = icon_paths.get(icon_fdid, "")
            stem = os.path.splitext(os.path.basename(path))[0] if path else f"retroport_{icon_fdid}"
            game_icon = f"Interface\\Icons\\{stem}.blp"
            if icon_fdid and game_icon not in icon_files:
                try:
                    icon_files[game_icon] = src.read(icon_fdid)
                except Exception as e:
                    self._say(f"{m['name']}: icon {icon_fdid} not exported ({e})")
            rows.append((disp, stem, entry))
            spell = spell_of.get(m["id"])
            tpl = FLYING_ITEM if int(m.get("flying") or 0) > 0 else GROUND_ITEM
            name = (item.get("name") or m["name"]).replace("\\", "\\\\").replace("'", "''")[:100]
            quality = max(1, min(int(item.get("quality") or 4), 5))
            sql += [f"-- {m['name']} (retail mount {m['id']})",
                    f"DELETE FROM item_template WHERE entry = {entry};",
                    "DROP TEMPORARY TABLE IF EXISTS retroport_mount_item;",
                    f"CREATE TEMPORARY TABLE retroport_mount_item SELECT * FROM item_template WHERE entry = {tpl};",
                    f"UPDATE retroport_mount_item SET entry = {entry}, name = '{name}', displayid = {disp}, "
                    f"Quality = {quality}, spellid_2 = {int(spell or 0)}, description = '', VerifiedBuild = 0;",
                    "INSERT INTO item_template SELECT * FROM retroport_mount_item;", ""]
            out[m["id"]] = {"entry": entry, "display": disp}
        self._save("ids.json", ids)
        sql_text = "\n".join(sql)
        sql_path = os.path.join(self.dir, "retroport-mounts.sql")
        with open(sql_path, "w", encoding="utf-8") as fh:
            fh.write(sql_text)
        st = wb.creatures.settings()
        db = world_db(st["world_conf"]) if st["world_conf"] else None
        if db and st["mysql"] and st["run_sql"]:
            run_sql(st["mysql"], db, sql_text)
            self._say(f"items: SQL applied to {db['database']} ({len(out)} item(s))")
        else:
            self._say(f"items: apply {sql_path} to your world database yourself")
        self._client_rows(rows, icon_files)
        return out

    def _client_rows(self, rows: list, icon_files: dict) -> None:
        """The mount items' icon rows (ItemDisplayInfo) and Item rows in the backport kit's patch:
        the client reads both from it, so they go in beside the kit's own (which stay)."""
        from ..mpq import MPQ, add_files
        kit = self.wb.kit
        name = kit.patch_name() if kit else ""
        client = self.wb.settings.client
        target = os.path.join(client, "Data", name) if name else ""
        if not target or not os.path.isfile(target):
            self._say("items: the backport kit has no patch in your client yet - their icons show as "
                      "question marks until it has one (install the kit once, then the mounts again)")
            return
        a = MPQ(target)
        try:
            idi = a.read("DBFilesClient\\ItemDisplayInfo.dbc")
            itm = a.read("DBFilesClient\\Item.dbc")
        finally:
            a.close()
        if not idi or not itm:
            from ..mpq import ClientData
            cd = ClientData(client)
            try:
                idi = idi or cd.read("DBFilesClient\\ItemDisplayInfo.dbc")
                itm = itm or cd.read("DBFilesClient\\Item.dbc")
            finally:
                cd.close()
        # the icons are kept beside the mount list: a kit install writes its patch again without them
        icons = os.path.join(self.dir, "icons")
        os.makedirs(icons, exist_ok=True)
        for game_path, data in icon_files.items():
            with open(os.path.join(icons, os.path.basename(game_path)), "wb") as fh:
                fh.write(data)
        files = {}
        for _d, stem, _e in rows:
            f = os.path.join(icons, f"{stem}.blp")
            if os.path.isfile(f):
                with open(f, "rb") as fh:
                    files[f"Interface\\Icons\\{stem}.blp"] = fh.read()
        files.update(self.merge_rows(idi, itm, rows))
        add_files(target, files)
        self._save("client_rows.json", {"rows": rows})
        self._say(f"items: {len(rows)} icon row(s) and item row(s) in {name}")

    @staticmethod
    def merge_rows(idi_bytes: bytes, item_bytes: bytes, rows: list) -> dict:
        """ItemDisplayInfo.dbc and Item.dbc with the mount items' rows: ours (the range, and the item
        entries) replaced, the others kept. ``rows``: [(display id, icon name, item entry)]."""
        idi = D.DBCFile.from_bytes(idi_bytes, "ItemDisplayInfo.dbc")
        itm = D.DBCFile.from_bytes(item_bytes, "Item.dbc")
        if idi.field_count != 25 or itm.field_count != 8:
            raise ValueError(f"ItemDisplayInfo.dbc has {idi.field_count} fields and Item.dbc {itm.field_count}, "
                             "not 3.3.5a's 25 and 8")
        lo, hi = ITEM_DISPLAY_RANGE
        entries = {e for _d, _s, e in rows}
        idi.records = [r for r in idi.records if not lo <= r[0] < hi]
        itm.records = [r for r in itm.records if r[0] not in entries]
        for disp, stem, entry in rows:
            rec = [0] * 25
            rec[0] = disp
            rec[5] = idi.add_string(stem)
            idi.add_record(rec)
            # a mount item as the client's own are (the reins it copies): Miscellaneous (15), Mount (5)
            tpl = next((r for r in itm.records if r[0] == GROUND_ITEM), None)
            itm.add_record([entry, 15, 5, tpl[3] if tpl else 0xFFFFFFFF, tpl[4] if tpl else 0xFFFFFFFF, disp, 0, 0])
        idi.records.sort(key=lambda r: r[0])
        itm.records.sort(key=lambda r: r[0])
        return {"DBFilesClient\\ItemDisplayInfo.dbc": idi.to_bytes(), "DBFilesClient\\Item.dbc": itm.to_bytes()}

    def reapply(self, say=lambda m: None) -> None:
        """After the backport kit wrote its patch again: the mount items' rows go back in."""
        rows = [tuple(r) for r in self._load("client_rows.json", {}).get("rows", [])]
        if not rows:
            return
        try:
            self._client_rows(rows, {})
            say(f"   mounts: {len(rows)} item row(s) put back in the kit's patch")
        except Exception as e:
            say(f"!! mounts: item rows not put back ({e})")
