"""What retail's own tables don't say, read from Wowhead's pages: an NPC's abilities (its spells, as
Wowhead's "Abilities" tab lists them) and a spell's tooltip (its text with every value filled in).
Each answer is kept on disk: Wowhead is asked once per NPC or spell."""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.request

UA = "Mozilla/5.0"                  # a longer agent string gets an empty 202 from Wowhead
_lock = threading.Lock()

SCHOOLS = {1: "Physical", 2: "Holy", 4: "Fire", 8: "Nature", 16: "Frost", 32: "Shadow", 64: "Arcane"}


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
    if not body:
        raise LookupError("Wowhead sent an empty page: try again in a moment")
    return body.decode("utf-8", errors="replace")


def _cached(cache_dir: str, name: str, make):
    path = os.path.join(cache_dir, "wowhead", name)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        pass
    value = make()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _lock:
        with open(path + ".part", "w", encoding="utf-8") as fh:
            json.dump(value, fh)
        os.replace(path + ".part", path)
    return value


def _array_after(text: str, at: int) -> str | None:
    """The JSON-ish array starting at the first '[' from ``at`` (brackets in strings skipped)."""
    start = text.find("[", at)
    if start < 0:
        return None
    depth, quote, k = 0, False, start
    while k < len(text):
        c = text[k]
        if quote:
            if c == "\\":
                k += 1
            elif c == '"':
                quote = False
        elif c == '"':
            quote = True
        elif c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
            if depth == 0:
                return text[start:k + 1]
        k += 1
    return None


def _loose_json(s: str):
    # Wowhead's listviews mix JSON with bare keys (modes:{...})
    return json.loads(re.sub(r'([{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', s))


def _gathered_spells(page: str) -> dict:
    """Wowhead's spell data on the page (WH.Gatherer.addData(6, ...)): name, icon, description."""
    out = {}
    for m in re.finditer(r"WH\.Gatherer\.addData\(6,\s*\d+,\s*", page):
        start = m.end()
        depth, quote, k = 0, False, start
        while k < len(page):
            c = page[k]
            if quote:
                if c == "\\":
                    k += 1
                elif c == '"':
                    quote = False
            elif c == '"':
                quote = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        try:
            out.update(json.loads(page[start:k + 1]))
        except ValueError:
            pass
    return out


def npc_abilities(npc: int, cache_dir: str) -> dict:
    """{"npc", "abilities": [{id, name, school, icon, description, modes}]} as Wowhead lists them."""
    def make():
        page = _get(f"https://www.wowhead.com/npc={int(npc)}")
        at = page.find("id: 'abilities'")
        rows = []
        if at >= 0:
            data_at = page.find("data:", at)
            arr = _array_after(page, data_at) if data_at >= 0 else None
            try:
                rows = _loose_json(arr) if arr else []
            except ValueError:
                rows = []
        info = _gathered_spells(page)
        out = []
        for r in rows:
            sid = int(r.get("id") or 0)
            g = info.get(str(sid), {})
            school = int(r.get("schools") or 0)
            out.append({"id": sid, "name": r.get("displayName") or r.get("name") or g.get("name_enus") or f"spell {sid}",
                        "school": [n for b, n in SCHOOLS.items() if school & b],
                        "icon": g.get("icon", ""), "description": g.get("description_enus", ""),
                        "class_spell": bool(r.get("reqclass")),
                        "modes": (r.get("modes") or {}).get("mode", [])})
        return {"npc": int(npc), "abilities": out}
    return _cached(cache_dir, f"npc-{int(npc)}.json", make)


def spell_tooltip(spell: int, cache_dir: str) -> dict:
    """Wowhead's tooltip of a retail spell: {name, icon, tooltip (HTML), buff (HTML)}."""
    def make():
        d = json.loads(_get(f"https://nether.wowhead.com/tooltip/spell/{int(spell)}?dataEnv=1&locale=0"))
        return {"id": int(spell), "name": d.get("name", ""), "icon": d.get("icon", ""),
                "tooltip": d.get("tooltip", ""), "buff": d.get("buff", "")}
    return _cached(cache_dir, f"spell-{int(spell)}.json", make)
