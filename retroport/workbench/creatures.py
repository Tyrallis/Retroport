"""Creatures: retail's creature models, previewed and installed for a 3.3.5a client that reads
modern models natively (WarcraftXL with the ``wxl.modern-m2`` mod).

Nothing here converts a model. ``wxl.modern-m2`` reads retail's MD21 files as they are, so a
creature is exported the way the client will look for it:

* the model and its skin profiles, ``Creature\\Retroport\\<Stem>\\<Stem>.m2`` and ``<Stem>NN.skin``
  (the names the client builds from the model's path);
* each external sequence's ``.anim`` as ``<Stem><anim:04>-<sub:02>.anim``;
* every texture the model or the display names, as ``<Stem>_<FileDataID>.blp``, with a wow.export
  manifest (``<Stem>.manifest.json``) beside the model - what the mod resolves a TXID texture by;
* a model whose skeleton lives in a ``.skel`` file (Shadowlands on) is first made self-contained by
  ``retroport.convert.skel_reinliner``: the mod refuses split-skeleton models.

Install then gives each creature a CreatureModelData and a CreatureDisplayInfo row - in a packed
``Data\\patch-R.MPQ`` built on the client's own tables (read from below that patch), and in the
server's dbc folder (built on a copy of its tables kept the first time) - and its world database rows
(``creature_template``, ``creature_template_model``, ``creature_model_info``), run with the MySQL
client against the database ``worldserver.conf`` names. Ids are kept per retail display
(``<data>\\creatures\\ids.json``), so a creature keeps its numbers from one install to the next, and
everything is rebuilt from those bases each time: installing again, or taking a creature out, never
stacks rows.
"""

from __future__ import annotations

import csv
import glob
import io
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time

from .. import dbc as D
from ..mpq import ClientData, write_archive
from . import models as M
from .procs import Restart
from .wago import http_get

PATCH_NAME = "patch-R.MPQ"
ROOT = "Creature\\Retroport"
LISTFILE_URL = "https://github.com/wowdev/wow-listfile/releases/latest/download/community-listfile.csv"
INDEX_VERSION = 4               # 4: displays keep the fourth creature skin (texture type 5)
FOURTH_SKIN_TYPE = 5            # the M2 texture type modern models give retail's fourth creature skin
DISPLAY_FLOOR = 100000          # new display / model ids start above this and above every id in use
ENTRY_FLOOR = 900000            # new creature_template entries start here
PAGE = 60

# the mod (load/M2Fixups.cpp) renames these sequence ids, and the client names an .anim by the id it sees
ANIM_REMAP = {564: 37, 548: 41, 556: 42, 552: 43, 554: 44, 562: 45, 572: 39, 574: 187}

FACTIONS = {14: "Hostile (monster)", 35: "Friendly to all", 7: "Neutral (creature)", 16: "Hostile (monster, 16)"}
RANKS = {0: "Normal", 1: "Elite", 2: "Rare elite", 3: "Boss", 4: "Rare"}


class CreatureError(RuntimeError):
    pass


def _stem_of(path: str, fallback: str) -> str:
    stem = os.path.splitext(os.path.basename(path.replace("\\", "/")))[0] if path else ""
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_")
    return stem or fallback


# -- the index --------------------------------------------------------------------------------

def find_listfile(candidates: list[str], cache_dir: str, say=lambda m: None) -> str:
    """A community listfile: one already on disk (the kit's project has one), else downloaded."""
    for p in candidates:
        if p and os.path.isfile(p) and os.path.getsize(p) > 1_000_000:
            return p
    dest = os.path.join(cache_dir, "community-listfile.csv")
    if not os.path.isfile(dest):
        say("creatures: downloading the community listfile (model names)")
        http_get(LISTFILE_URL, dest)
    return dest


def model_paths(listfile: str, fdids: set[int]) -> dict[int, str]:
    """The listfile's path of each model FileDataID asked for."""
    out = {}
    with open(listfile, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.rstrip().lower().endswith(".m2"):
                continue
            left, _, right = line.partition(";")
            try:
                fdid = int(left)
            except ValueError:
                continue
            if fdid in fdids:
                out[fdid] = right.strip()
    return out


class CreatureIndex:
    """Every retail creature display a modern model can stand in for: its model, scale, textures,
    and the creatures that use it (names from Creature.db2)."""

    def __init__(self, d: dict):
        self.build = d["build"]
        self.displays: dict[int, dict] = {int(k): v for k, v in d["displays"].items()}
        self.models: dict[int, dict] = {int(k): v for k, v in d["models"].items()}
        self.paths: dict[int, str] = {int(k): v for k, v in d["paths"].items()}
        self.names: dict[int, list] = {int(k): v for k, v in d["names"].items()}   # display -> [[creature, name], ...]
        self._rows = None

    def to_json(self) -> dict:
        return {"version": INDEX_VERSION, "build": self.build, "displays": self.displays, "models": self.models,
                "paths": self.paths, "names": self.names}

    @classmethod
    def build_from(cls, src, listfile: str, say=lambda m: None) -> "CreatureIndex":
        say("creatures: reading CreatureModelData, CreatureDisplayInfo and Creature")
        models = {}
        for mid, r in src.table("CreatureModelData"):
            fd = int(r.get("FileDataID") or 0)
            if not fd:
                continue
            geo = r.get("GeoBox") or [0.0] * 6
            models[mid] = {"f": fd, "flags": int(r.get("Flags") or 0), "scale": float(r.get("ModelScale") or 1.0),
                           "cw": float(r.get("CollisionWidth") or 0.5), "ch": float(r.get("CollisionHeight") or 2.0),
                           "geo": [round(float(x), 4) for x in geo][:6], "mount": float(r.get("MountHeight") or 0.0)}
        displays = {}
        for did, r in src.table("CreatureDisplayInfo"):
            mid = int(r.get("ModelID") or 0)
            if mid not in models:
                continue
            tex = [int(x or 0) for x in (r.get("TextureVariationFileDataID") or [0, 0, 0, 0])]
            displays[did] = {"m": mid, "s": round(float(r.get("CreatureModelScale") or 1.0), 4),
                             "a": int(r.get("CreatureModelAlpha") or 255), "t": (tex + [0] * 4)[:4],
                             "x": int(r.get("ExtendedDisplayInfoID") or 0)}
        names: dict[int, list] = {}
        for cid, r in src.table("Creature"):
            name = (r.get("Name_lang") or "").strip()
            for did in (r.get("DisplayID") or []):
                did = int(did or 0)
                if did and did in displays and name:
                    names.setdefault(did, []).append([cid, name])
        say("creatures: naming models from the listfile")
        paths = model_paths(listfile, {m["f"] for m in models.values()})
        return cls({"build": src.build, "displays": displays, "models": models, "paths": paths, "names": names})

    # -- answers --------------------------------------------------------------------------
    def label(self, did: int) -> str:
        n = self.names.get(did)
        if n:
            return n[0][1]
        d = self.displays[did]
        return _stem_of(self.paths.get(self.models[d["m"]]["f"], ""), f"display {did}")

    def _all_rows(self) -> list[tuple]:
        if self._rows is None:
            rows = []
            for did, d in self.displays.items():
                model = self.models[d["m"]]
                path = self.paths.get(model["f"], "")
                names = self.names.get(did, [])
                hay = " ".join([str(did), str(model["f"]), path.lower()] + [n[1].lower() for n in names] +
                               [str(n[0]) for n in names])
                rows.append((did, hay, bool(names), path))
            # named creatures first, newest displays first
            rows.sort(key=lambda r: (not r[2], -r[0]))
            self._rows = rows
        return self._rows

    def search(self, q: str = "", page: int = 0, humanoids: bool = False, named: bool = False) -> tuple[int, list[dict]]:
        terms = [t for t in q.lower().split() if t]
        hits = []
        seen: set[tuple] = set()      # one card per look: a model with the same texture files
        for did, hay, has_name, _path in self._all_rows():
            if named and not has_name:
                continue
            d = self.displays[did]
            if not humanoids and d["x"]:
                continue
            if all(t in hay for t in terms):
                look = (self.models[d["m"]]["f"], tuple(t for t in d["t"] if t), d["x"])
                if look in seen:
                    continue
                seen.add(look)
                hits.append(did)
        return len(hits), [self.row(did) for did in hits[page * PAGE:(page + 1) * PAGE]]

    def row(self, did: int) -> dict | None:
        d = self.displays.get(did)
        if d is None:
            return None
        model = self.models[d["m"]]
        path = self.paths.get(model["f"], "")
        return {"display": did, "name": self.label(did), "creatures": self.names.get(did, [])[:12],
                "model": model["f"], "model_data": d["m"], "path": path, "stem": _stem_of(path, f"display{did}"),
                "scale": d["s"], "alpha": d["a"], "textures": [t for t in d["t"] if t], "t": list(d["t"]),
                "humanoid": bool(d["x"]), "geo": model["geo"], "model_scale": model["scale"],
                "mount_height": model.get("mount", 0.0),
                "collision": [model["cw"], model["ch"]]}

    def variations(self, did: int) -> list[dict]:
        """The skins of this display's model: one entry per distinct set of texture files (retail
        gives one look many displays - Sylvanas has twenty with the same skin), the display shown
        for each the one a named creature uses where there is one - the opened display for its own
        skin. Labels are the creature's name, numbered when two skins share one."""
        d = self.displays[did]
        model = self.models[d["m"]]["f"]
        groups: dict[tuple, list[int]] = {}
        for x, v in self.displays.items():
            if v["x"] or self.models.get(v["m"], {}).get("f") != model:
                continue
            groups.setdefault(tuple(t for t in v["t"] if t), []).append(x)
        out = []
        for skin, members in groups.items():
            members.sort()
            named = [x for x in members if x in self.names]
            pick = did if did in members else (named[0] if named else members[0])
            out.append({"display": pick, "name": self.label(pick), "textures": list(skin), "displays": len(members)})
        out.sort(key=lambda e: (e["display"] != did, e["name"].lower(), e["display"]))
        seen: dict[str, int] = {}
        for e in out:
            seen[e["name"]] = seen.get(e["name"], 0) + 1
        counter: dict[str, int] = {}
        for e in out:
            if seen[e["name"]] > 1:
                counter[e["name"]] = counter.get(e["name"], 0) + 1
                e["label"] = f"{e['name']} · skin {counter[e['name']]}"
            else:
                e["label"] = e["name"]
        return out[:60]


def load_index(src, cache_dir: str, listfile_candidates: list[str], say=lambda m: None) -> CreatureIndex:
    path = os.path.join(cache_dir, f"creatures-{src.build}.json")
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("version") == INDEX_VERSION:
                return CreatureIndex(d)
        except (OSError, ValueError):
            pass
    listfile = find_listfile(listfile_candidates, cache_dir, say)
    idx = CreatureIndex.build_from(src, listfile, say)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(idx.to_json(), fh)
    os.replace(tmp, path)
    say(f"creatures: {len(idx.displays):,} displays of {len(idx.models):,} models indexed")
    return idx


def textures_of(row: dict) -> dict[int, int]:
    """The display's creature skins as the viewer's texture-type map (types 11, 12, 13, and 5 for the
    fourth skin modern models use)."""
    out = {11 + k: t for k, t in enumerate(row_textures(row)) if t}
    if row_fourth_texture(row):
        out[FOURTH_SKIN_TYPE] = row_fourth_texture(row)
    return out


def _row_slots(row: dict) -> list[int]:
    t = list(row.get("t") or row.get("textures") or [])
    return (t + [0, 0, 0, 0])[:4]


def row_textures(row: dict) -> list[int]:
    """The three creature skins a 3.3.5 CreatureDisplayInfo row can name (texture types 11-13)."""
    return _row_slots(row)[:3]


def row_fourth_texture(row: dict) -> int:
    """Retail's fourth creature skin (TextureVariationFileDataID[3]). Modern models take it on texture
    type 5, which the 3.3.5 client never fills - so the export bakes it into the model."""
    return _row_slots(row)[3]


# -- one model's files ----------------------------------------------------------------------------

def _chunks(data: bytes) -> dict[str, bytes]:
    out, pos = {}, 0
    while pos + 8 <= len(data):
        tag = data[pos:pos + 4].decode("ascii", "replace")
        size = struct.unpack_from("<I", data, pos + 4)[0]
        out.setdefault(tag, data[pos + 8:pos + 8 + size])
        pos += 8 + size
    return out


def _u32s(b: bytes) -> list[int]:
    return list(struct.unpack(f"<{len(b) // 4}I", b[:len(b) // 4 * 4]))


def bake_texture_type(m2: bytes, tex_type: int, fdid: int) -> tuple[bytes, int]:
    """Turn every texture of ``tex_type`` into a hardcoded one (type 0) whose TXID entry is ``fdid``:
    what the client cannot fill from a creature row, the model then names itself. Returns the model
    and how many textures changed."""
    out = bytearray(m2)
    spans, pos = {}, 0
    while pos + 8 <= len(out):
        tag = bytes(out[pos:pos + 4])
        size = struct.unpack_from("<I", out, pos + 4)[0]
        spans.setdefault(tag, (pos + 8, size))
        pos += 8 + size
    if b"MD21" not in spans or b"TXID" not in spans:
        return m2, 0
    md, md_size = spans[b"MD21"]
    tx, tx_size = spans[b"TXID"]
    count, off = struct.unpack_from("<II", out, md + 0x50)
    if off + 16 * count > md_size:
        return m2, 0
    baked = 0
    for i in range(min(count, tx_size // 4)):
        entry = md + off + 16 * i
        if struct.unpack_from("<I", out, entry)[0] == tex_type:
            struct.pack_into("<I", out, entry, 0)
            struct.pack_into("<I", out, tx + 4 * i, fdid)
            baked += 1
    return bytes(out), baked


PARTICLE_STRIDE = 0x1EC            # a modern (272-274) particle emitter record
PARTICLE_MULTITEX = 0x10000000     # emitter flag: the texture slot packs three layer ids (5 bits each)


def _texture_users(md20: bytes) -> dict[int, set]:
    """Which parts of the model use each texture: 'batch' (texture lookup), 'ribbon', or an emitter
    key (its packed texture slot)."""
    users: dict[int, set] = {}
    n, off = struct.unpack_from("<II", md20, 0x80)
    for k in range(n):
        users.setdefault(struct.unpack_from("<H", md20, off + 2 * k)[0], set()).add("batch")
    n, off = struct.unpack_from("<II", md20, 0x120)
    for k in range(n):
        # ribbon: textureIndices M2Array at 0x14
        tn, to = struct.unpack_from("<II", md20, off + 0xB0 * k + 0x14)
        for j in range(min(tn, 8)):
            if to + 2 * j + 2 <= len(md20):
                users.setdefault(struct.unpack_from("<H", md20, to + 2 * j)[0], set()).add("ribbon")
    n, off = struct.unpack_from("<II", md20, 0x128)
    for k in range(n):
        r = off + PARTICLE_STRIDE * k
        flags = struct.unpack_from("<I", md20, r + 4)[0]
        slot = struct.unpack_from("<H", md20, r + 0x16)[0]
        if flags & PARTICLE_MULTITEX:
            users.setdefault(slot & 0x1F, set()).add(("multi", slot))
        else:
            users.setdefault(slot, set()).add("single")
    return users


def _neutral(img) -> bool:
    """A texture that only fades or brightens what it multiplies: near white and unsaturated where
    it is not transparent (Blizzard's fade bands under a colour layer)."""
    px = [p for p in img.convert("RGBA").resize((32, 32)).getdata() if p[3] > 16]
    if not px:
        return True
    bright = sum(max(p[:3]) for p in px) / (255.0 * len(px))
    sat = sum((max(p[:3]) - min(p[:3])) / max(1, max(p[:3])) for p in px) / len(px)
    return bright > 0.7 and sat < 0.15


def bake_projected(m2: bytes, skins: dict[str, bytes], files: dict[str, bytes], tex_file: dict[int, str]) -> list[str]:
    """A batch flagged projected (0x4) is laid onto the terrain by the client, which projects one
    texture -- its first, mapped as the batch's first UVs map it -- over the ground under it. Retail's
    projected batches combine two or three (a colour, a detail layer, a shape mask on the second
    UVs). So the others are baked into the first texture's image, each sampled where the batch's
    second UVs put it, combined as the batch's packed shader says (op 3 adds, op 1 multiplies, the
    rest multiply twice), the third multiplying colour and alpha; the batch becomes one texture.
    The layers' scrolling stops. Only a first texture no other batch reads is rewritten. Skins are
    changed in ``skins`` (path -> bytes); returns notes."""
    from PIL import Image
    from ..formats import blp
    md20 = _chunks(m2).get("MD21", b"")
    if len(md20) < 0x130:
        return []
    tn, to = struct.unpack_from("<II", md20, 0x80)
    look = list(struct.unpack_from(f"<{tn}h", md20, to)) if tn else []
    vn, vo = struct.unpack_from("<II", md20, 0x3C)
    notes, baked = [], set()
    users: dict[int, int] = {}
    parsed = {}
    for path, skin in skins.items():
        if len(skin) < 0x2C:
            continue
        bn, bo = struct.unpack_from("<II", skin, 4 + 8 * 4)
        rows = [struct.unpack_from("<BbHHHhHHHHHHH", skin, bo + k * 0x18) for k in range(bn)]
        parsed[path] = (bo, rows)
    # who reads each texture: the first skin is the whole model (the others are its lower details)
    for r in (parsed[min(parsed)][1] if parsed else []):
        for k in range(r[8]):
            if r[9] + k < tn:
                users[look[r[9] + k]] = users.get(look[r[9] + k], 0) + 1
    baked_combos: set[int] = set()
    for path, (bo, rows) in parsed.items():
        skin = bytearray(skins[path])
        vi_n, vi_o = struct.unpack_from("<II", skin, 4)
        sm_n, sm_o = struct.unpack_from("<II", skin, 4 + 8 * 3)
        for k, (flags, _p, shader, sub, _g, _c, _m, _l, tcount, tcombo, _tc, _w, _tt) in enumerate(rows):
            if not (flags & 4) or tcount < 2 or shader & 0x8000 or tcombo + tcount > tn or sub >= sm_n:
                continue
            if tcombo in baked_combos:                 # baked already, from another skin
                struct.pack_into("<H", skin, bo + k * 0x18 + 0x0E, 1)
                continue
            first = look[tcombo]
            if first in baked or users.get(first, 0) > 1 + (look[tcombo + 1] == first) or first not in tex_file:
                continue
            vstart, vcount = struct.unpack_from("<HH", skin, sm_o + sub * 0x30 + 4)
            if vcount < 3:
                continue
            uv = []
            for j in range(3):
                v = struct.unpack_from("<H", skin, vi_o + 2 * (vstart + j))[0]
                uv.append((struct.unpack_from("<2f", md20, vo + v * 48 + 32), struct.unpack_from("<2f", md20, vo + v * 48 + 40)))
            # the affine map from the first UVs to the second, from the batch's first three vertices
            (a0, a1), (b0, b1), (c0, c1) = uv
            d = (b0[0] - a0[0]) * (c0[1] - a0[1]) - (c0[0] - a0[0]) * (b0[1] - a0[1])
            if abs(d) < 1e-9:
                continue

            def second(u, w):
                s = ((u - a0[0]) * (c0[1] - a0[1]) - (c0[0] - a0[0]) * (w - a0[1])) / d
                t = ((b0[0] - a0[0]) * (w - a0[1]) - (u - a0[0]) * (b0[1] - a0[1])) / d
                return (a1[0] + s * (b1[0] - a1[0]) + t * (c1[0] - a1[0]),
                        a1[1] + s * (b1[1] - a1[1]) + t * (c1[1] - a1[1]))
            try:
                base = blp.decode_bytes(files[tex_file[first]]).convert("RGBA")
                layers = []
                for j in range(1, tcount):
                    idx = look[tcombo + j]
                    if idx not in tex_file:
                        raise ValueError(f"layer {idx} has no file")
                    layers.append(blp.decode_bytes(files[tex_file[idx]]).convert("RGBA"))
            except Exception as e:
                notes.append(f"projected batch {k}: not baked ({e})")
                continue
            W, H = base.size
            on_second = bool(shader & 0x4000)
            op = shader & 0x7
            bp = base.load()
            lp = [(l.load(), l.size) for l in layers]
            out = Image.new("RGBA", (W, H))
            op_px = out.load()

            def sample(px, size, u, w):
                x = int((u % 1.0) * size[0]) % size[0]
                y = int((w % 1.0) * size[1]) % size[1]
                return px[x, y]
            for y in range(H):
                for x in range(W):
                    u, w = (x + 0.5) / W, (y + 0.5) / H
                    r, g, b, a = (c / 255.0 for c in bp[x, y])
                    su, sw = second(u, w) if on_second else (u, w)
                    for j, (px, size) in enumerate(lp):
                        lr, lg, lb, la = (c / 255.0 for c in sample(px, size, su, sw))
                        if j == 0 and op == 3:          # adds
                            r, g, b = r + lr * la, g + lg * la, b + lb * la
                        elif j == 0 and op == 1:        # multiplies
                            r, g, b, a = r * lr, g * lg, b * lb, a * la
                        elif j == 0:                    # multiplies twice (Mod2x, its no-alpha form keeps alpha)
                            r, g, b = r * lr * 2, g * lg * 2, b * lb * 2
                            if op != 6:
                                a = a * la * 2
                        else:                           # the mask: nothing past its edges
                            if not (0.0 <= su <= 1.0 and 0.0 <= sw <= 1.0):
                                lr = lg = lb = la = 0.0
                            r, g, b, a = r * lr, g * lg, b * lb, a * la
                    op_px[x, y] = tuple(int(max(0.0, min(1.0, c)) * 255) for c in (r, g, b, a))
            files[tex_file[first]] = blp.encode_dxt(out, alpha=True)
            struct.pack_into("<H", skin, bo + k * 0x18 + 0x0E, 1)
            baked.add(first)
            baked_combos.add(tcombo)
            notes.append(f"projected batch {k}: {tcount} textures baked into {first} (laid onto the terrain)")
        skins[path] = bytes(skin)
    return notes


def colour_before_fade(m2: bytes, skins: list[bytes], files: dict[str, bytes], tex_file: dict[int, str]) -> tuple[bytes, list[str]]:
    """Retail draws some batches from three textures; the 3.3.5 client (through wxl.modern-m2) keeps
    the first and the third, the mask. Where the first is only a white fade band and the second
    carries the colour (a dark void under a swirl mask), the two swap places in the batch's texture
    and transform lookups, so the colour survives. Only lookup entries no other batch reads differently
    are swapped. Returns the model and notes."""
    from ..formats import blp
    pos = 0
    md = None
    while pos + 8 <= len(m2):
        tag, size = m2[pos:pos + 4], struct.unpack_from("<I", m2, pos + 4)[0]
        if tag == b"MD21":
            md = pos + 8
            break
        pos += 8 + size
    if md is None:
        return m2, []
    out = bytearray(m2)
    tn, to = struct.unpack_from("<II", out, md + 0x80)
    xn, xo = struct.unpack_from("<II", out, md + 0x98)
    look = list(struct.unpack_from(f"<{tn}h", out, md + to)) if tn else []
    # every batch's (texture start, count, transform start), over every skin
    batches = []
    for skin in skins:
        if len(skin) < 0x2C:
            continue
        bn, bo = struct.unpack_from("<II", skin, 4 + 8 * 4)
        for k in range(bn):
            shader, = struct.unpack_from("<H", skin, bo + k * 0x18 + 2)
            tcount, tcombo = struct.unpack_from("<HH", skin, bo + k * 0x18 + 0x0E)
            ttrans, = struct.unpack_from("<H", skin, bo + k * 0x18 + 0x16)
            batches.append((shader, tcount, tcombo, ttrans))
    notes, done = [], set()
    for shader, tcount, tcombo, ttrans in batches:
        if tcount != 3 or shader & 0x8000 or tcombo in done or tcombo + 2 >= tn:
            continue
        done.add(tcombo)
        # nobody else may read these two entries as anything but this batch's first two
        if any((t != tcombo or c != 3) and t <= tcombo + 1 and tcombo < t + c for s, c, t, x in batches):
            continue
        a, b = look[tcombo], look[tcombo + 1]
        if a == b or a not in tex_file or b not in tex_file:
            continue
        try:
            fade = _neutral(blp.decode_bytes(files[tex_file[a]]))
            colour = not _neutral(blp.decode_bytes(files[tex_file[b]]))
        except Exception:
            continue
        if not (fade and colour):
            continue
        struct.pack_into("<hh", out, md + to + 2 * tcombo, b, a)
        if ttrans != 0xFFFF and ttrans + 1 < xn and \
                not any((x != ttrans or c != 3) and x <= ttrans + 1 and ttrans < x + c for s, c, t, x in batches):
            x0, x1 = struct.unpack_from("<hh", out, md + xo + 2 * ttrans)
            struct.pack_into("<hh", out, md + xo + 2 * ttrans, x1, x0)
        notes.append(f"three-texture batch: colour layer {b} put before fade layer {a} (the client keeps two)")
    return bytes(out), notes


def bake_multitex_particles(m2: bytes, files: dict[str, bytes], tex_file: dict[int, str]) -> list[str]:
    """The 3.3.5 client draws one texture per particle; a modern multi-texture emitter multiplies its
    first layer (often a white shape mask) by two more (e.g. dark scrolling clouds). Bake those two into
    the first layer's file, per flipbook cell, where nothing else in the model uses that texture.
    The layers' scrolling is lost. ``tex_file``: texture index -> path in ``files``. Returns notes."""
    from PIL import Image, ImageChops
    from ..formats import blp
    md20 = _chunks(m2).get("MD21", b"")
    if len(md20) < 0x130:
        return []
    notes = []
    for tex, who in _texture_users(md20).items():
        slots = {u[1] for u in who if isinstance(u, tuple)}
        if not slots or len(slots) != len(who) or len(slots) > 1:
            continue                       # not a multi-texture mask, or shared with other uses
        slot = slots.pop()
        layers = [(slot >> 5) & 0x1F, (slot >> 10) & 0x1F]
        path = tex_file.get(tex)
        if not path or path not in files or any(l == tex or l not in tex_file or tex_file[l] not in files
                                                for l in layers):
            continue
        # the emitter's flipbook grid: the layers cover each cell, not the whole sheet
        n, off = struct.unpack_from("<II", md20, 0x128)
        rows = cols = 1
        for k in range(n):
            r = off + PARTICLE_STRIDE * k
            if struct.unpack_from("<H", md20, r + 0x16)[0] == slot:
                rows, cols = max(1, struct.unpack_from("<H", md20, r + 0x30)[0]), \
                             max(1, struct.unpack_from("<H", md20, r + 0x32)[0])
                break
        try:
            base = blp.decode_bytes(files[path]).convert("RGBA")
            cw, ch = max(1, base.width // cols), max(1, base.height // rows)
            rgb = base.convert("RGB")
            for l in layers:
                cell = blp.decode_bytes(files[tex_file[l]]).convert("RGB").resize((cw, ch), Image.LANCZOS)
                sheet = Image.new("RGB", base.size)
                for y in range(0, base.height, ch):
                    for x in range(0, base.width, cw):
                        sheet.paste(cell, (x, y))
                # a patterned layer modulates at 2x, as the client's own two-texture combiners do; a
                # flat one (Blizzard's 8x8 white or grey) is a plain tint -- doubled, white blows the
                # particle out to a white square
                lo, hi = zip(*cell.getextrema())
                flat = max(hi) - min(lo) <= 8
                rgb = ImageChops.multiply(rgb, sheet)
                if not flat:
                    rgb = rgb.point(lambda v: min(255, v * 2))
            baked = Image.merge("RGBA", (*rgb.split(), base.getchannel("A")))
            files[path] = blp.encode_dxt(baked, alpha=True)
            notes.append(f"particle texture {tex}: layers {layers[0]} and {layers[1]} baked in (they no longer scroll)")
        except Exception as e:  # a texture this can't decode keeps its first layer only
            notes.append(f"particle texture {tex}: layers not baked ({e})")
    return notes


def bake_multitex_ribbons(m2: bytes, files: dict[str, bytes], tex_file: dict[int, str]) -> tuple[bytes, list[str]]:
    """Retail gives a ribbon several textures: a base streak and masks multiplied over it (a noise
    that breaks the trail into sparkles). The 3.3.5 client draws a ribbon once per texture it names,
    added on top of each other: the masks come out as wide bright bands (Blizzard's falling shards
    leave white beams). So each ribbon keeps its first texture alone, the masks multiplied into it
    (2x for a patterned one, as the particle bake does) where no batch or particle reads that image.
    Their scrolling is lost. Returns the model and notes."""
    from PIL import Image, ImageChops
    from ..formats import blp
    pos, md = 0, None
    while pos + 8 <= len(m2):
        tag, size = m2[pos:pos + 4], struct.unpack_from("<I", m2, pos + 4)[0]
        if tag == b"MD21":
            md = pos + 8
            break
        pos += 8 + size
    if md is None:
        return m2, []
    out = bytearray(m2)
    users = _texture_users(bytes(out[md:]))
    n, off = struct.unpack_from("<II", out, md + 0x120)
    notes, baked = [], set()
    for k in range(n):
        at = md + off + 0xB0 * k + 0x14
        tn, to = struct.unpack_from("<II", out, at)
        if tn < 2 or md + to + 2 * tn > len(out):
            continue
        idx = [struct.unpack_from("<H", out, md + to + 2 * j)[0] for j in range(tn)]
        base, layers = idx[0], []
        for t in idx[1:]:
            if t != base and t not in layers:
                layers.append(t)
        struct.pack_into("<I", out, at, 1)              # the ribbon draws once, with its base texture
        path = tex_file.get(base)
        if base in baked or not path or path not in files or users.get(base, set()) - {"ribbon"}:
            notes.append(f"ribbon {k}: drawn with its first texture only")
            continue
        try:
            img = blp.decode_bytes(files[path]).convert("RGBA")
            rgb = img.convert("RGB")
            for t in layers:
                if t not in tex_file or tex_file[t] not in files:
                    continue
                layer = blp.decode_bytes(files[tex_file[t]]).convert("RGB").resize(img.size, Image.LANCZOS)
                lo, hi = zip(*layer.getextrema())
                rgb = ImageChops.multiply(rgb, layer)
                if max(hi) - min(lo) > 8:
                    rgb = rgb.point(lambda v: min(255, v * 2))
            files[path] = blp.encode_dxt(Image.merge("RGBA", (*rgb.split(), img.getchannel("A"))), alpha=True)
            baked.add(base)
            notes.append(f"ribbon {k}: texture layers {layers} baked into its first (they no longer scroll)")
        except Exception as e:
            notes.append(f"ribbon {k}: drawn with its first texture only ({e})")
    return bytes(out), notes


class Export:
    """A display's files, as the client and the mod will look for them."""

    def __init__(self, stem: str, root: str = ROOT, folder: str | None = None):
        self.stem = stem
        self.folder = folder or f"{root}\\{stem}"
        self.files: dict[str, bytes] = {}
        self.notes: list[str] = []
        self.variations = ["", "", ""]
        self.textures = 0
        self.anims = 0
        self.reinlined = False

    @property
    def model_path(self) -> str:
        return f"{self.folder}\\{self.stem}.m2"

    @property
    def dbc_model_name(self) -> str:
        # CreatureModelData names a model as the 3.3.5 client's own rows do: .mdx, read as .m2
        return f"{self.folder}\\{self.stem}.mdx"

    def put(self, name: str, data: bytes) -> None:
        self.files[f"{self.folder}\\{name}"] = data


def export_display(read, row: dict, stem: str, root: str = ROOT, folder: str | None = None) -> Export:
    """Every file the client needs for this display (``row`` as CreatureIndex.row gives it; a spell
    model passes {"model": fdid} and its own ``root``; a character body its game ``folder``)."""
    ex = Export(stem, root, folder)
    m2 = read(row["model"])
    if m2[:4] != b"MD21":
        raise CreatureError(f"model {row['model']} is not a chunked (MD21) model; nothing modern to port")
    ch = _chunks(m2)
    md20 = ch.get("MD21", b"")
    version = struct.unpack_from("<I", md20, 4)[0] if len(md20) >= 8 else 0
    if not 272 <= version <= 274:
        raise CreatureError(f"model {row['model']} is version {version}; wxl.modern-m2 reads 272-274")

    if "SKID" in ch:
        from ..convert.skel_reinliner import reinline
        from ..formats.m2 import M2File
        from ..formats.skel import parse_skel
        skel_id = struct.unpack_from("<I", ch["SKID"])[0]
        skel = parse_skel(read(skel_id))
        if skel.parent_skel_file_id:
            raise CreatureError(f"model {row['model']}'s skeleton ({skel_id}) builds on a shared one "
                                f"({skel.parent_skel_file_id}); that kind is not supported yet")

        def anim(fdid):
            try:
                return read(fdid)
            except Exception:
                return None
        f = M2File(m2)
        res = reinline(f, skel, stem, anim_loader=anim, m2_afid=ch.get("AFID"))
        fails = [x.detail for x in res.findings if x.severity.name == "FAIL"]
        if not res.success:
            raise CreatureError(f"model {row['model']}: its .skel could not be inlined ({'; '.join(fails) or 'see the log'})")
        if not res.fully_inline:
            ex.notes.append(f"{res.external_tracks} animation track(s) of the .skel stayed external: those animations "
                            "show the bind pose")
        f.chunks = [c for c in f.chunks if c[0] not in ("SKID", "AFID")]
        m2 = f.to_bytes()
        ch = _chunks(m2)
        md20 = ch["MD21"]
        ex.reinlined = True
        ex.notes.append(f"skeleton inlined from .skel {skel_id} ({res.bones} bones, {res.sequences} sequences, "
                        f"{res.inlined_anims} .anim file(s))")

    ex.put(f"{stem}.m2", m2)

    # skins: the profiles the header counts (the chooser may pick any of the first four)
    profiles = struct.unpack_from("<I", md20, 0x44)[0] if len(md20) > 0x48 else 1
    sfid = _u32s(ch.get("SFID", b""))
    if not sfid:
        raise CreatureError(f"model {row['model']} names no skin file (SFID)")
    for k, fdid in enumerate(sfid[:min(max(profiles, 1), 4)]):
        ex.put(f"{stem}{k:02d}.skin", read(fdid))

    # external sequences
    afid = ch.get("AFID", b"")
    for k in range(len(afid) // 8):
        anim_id, sub, fdid = struct.unpack_from("<HHI", afid, k * 8)
        if not fdid:
            continue
        try:
            data = read(fdid)
        except Exception as e:
            ex.notes.append(f".anim {anim_id}-{sub} ({fdid}): {e}")
            continue
        ex.put(f"{stem}{anim_id:04d}-{sub:02d}.anim", data)
        if anim_id in ANIM_REMAP:
            ex.put(f"{stem}{ANIM_REMAP[anim_id]:04d}-{sub:02d}.anim", data)
        ex.anims += 1

    # textures: the model's own (TXID) and the display's skins
    manifest = []
    names: dict[int, str] = {}

    def texture(fdid: int) -> str:
        if fdid in names:
            return names[fdid]
        name = f"{stem}_{fdid}"
        try:
            ex.put(f"{name}.blp", read(fdid))
        except Exception as e:
            ex.notes.append(f"texture {fdid}: {e}")
            names[fdid] = ""
            return ""
        names[fdid] = name
        manifest.append({"fileDataID": fdid, "file": f"{name}.blp"})
        ex.textures += 1
        return name

    for fdid in _u32s(ch.get("TXID", b"")):
        if fdid:
            texture(fdid)
    for k, fdid in enumerate(row_textures(row)):
        if fdid:
            ex.variations[k] = texture(fdid)
    tex_file = {i: f"{ex.folder}\\{names[f]}.blp" for i, f in enumerate(_u32s(ch.get("TXID", b"")))
                if f and names.get(f)}
    ex.notes += bake_multitex_particles(m2, ex.files, tex_file)
    skin_files = {k: v for k, v in ex.files.items() if k.startswith(f"{ex.folder}\\{stem}") and k.endswith(".skin")}
    ex.notes += bake_projected(m2, skin_files, ex.files, tex_file)
    ex.files.update(skin_files)
    skins = list(skin_files.values())
    m2, swapped = colour_before_fade(m2, skins, ex.files, tex_file)
    if swapped:
        ex.put(f"{stem}.m2", m2)
        ex.notes += swapped
    m2, ribbons = bake_multitex_ribbons(m2, ex.files, tex_file)
    if ribbons:
        ex.put(f"{stem}.m2", m2)
        ex.notes += ribbons
    fourth = row_fourth_texture(row)
    if fourth and texture(fourth):
        m2, baked = bake_texture_type(m2, FOURTH_SKIN_TYPE, fourth)
        if baked:
            ex.put(f"{stem}.m2", m2)
            ex.notes.append(f"fourth creature skin {fourth} baked into {baked} texture(s) of type {FOURTH_SKIN_TYPE}")
    ex.put(f"{stem}.manifest.json", json.dumps({"fileDataID": row["model"], "textures": manifest}, indent=1).encode())
    return ex


# -- the world database -----------------------------------------------------------------------

def find_world_conf(server_dbc: str, override: str = "") -> str:
    if override and os.path.isfile(override):
        return override
    if not server_dbc:
        return ""
    base = os.path.dirname(os.path.dirname(os.path.abspath(server_dbc)))      # <server>\Data\dbc -> <server>
    for p in (os.path.join(base, "configs", "worldserver.conf"), os.path.join(base, "worldserver.conf"),
              os.path.join(base, "etc", "worldserver.conf")):
        if os.path.isfile(p):
            return p
    return ""


def world_db(conf: str) -> dict | None:
    """``WorldDatabaseInfo`` of a worldserver.conf: host, port, user, password, database."""
    try:
        with open(conf, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r'\s*WorldDatabaseInfo\s*=\s*"([^"]*)"', line)
                if m:
                    parts = m.group(1).split(";")
                    if len(parts) >= 5:
                        return {"host": parts[0], "port": parts[1], "user": parts[2], "password": parts[3],
                                "database": parts[4]}
    except OSError:
        pass
    return None


def find_mysql(override: str = "") -> str:
    if override and os.path.isfile(override):
        return override
    found = shutil.which("mysql")
    if found:
        return found
    pats = [r"C:\Program Files\MySQL\*\bin\mysql.exe", r"C:\Program Files\MariaDB*\bin\mysql.exe",
            r"C:\Program Files (x86)\MySQL\*\bin\mysql.exe"]
    for pat in pats:
        hits = sorted(glob.glob(pat), reverse=True)
        if hits:
            return hits[0]
    return ""


def run_sql(mysql: str, db: dict, sql: str, timeout: int = 120) -> str:
    """``sql`` through the MySQL client; its output. The password goes in an option file only this
    process reads, removed straight after - never on a command line."""
    fd, opt = tempfile.mkstemp(suffix=".cnf", prefix="retroport-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write("[client]\n")
            fh.write(f"host={db['host']}\nport={db['port']}\nuser={db['user']}\n")
            fh.write(f"password=\"{db['password']}\"\n")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        p = subprocess.run([mysql, f"--defaults-extra-file={opt}", "--default-character-set=utf8mb4", "--batch",
                            db["database"]], input=sql.encode("utf-8"), capture_output=True, timeout=timeout,
                           creationflags=flags)
        out = (p.stdout + p.stderr).decode("utf-8", "replace")
        out = "\n".join(l for l in out.splitlines() if "Using a password on the command line" not in l)
        if p.returncode != 0:
            raise CreatureError(f"MySQL refused the SQL: {out.strip()[-600:]}")
        return out
    finally:
        try:
            os.remove(opt)
        except OSError:
            pass


def _q(s: str) -> str:
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def creature_sql(c: dict, ids: dict) -> list[str]:
    """One creature's world rows, replacing whatever an earlier install wrote for it."""
    e, d = ids["entry"], ids["display"]
    level = max(1, min(int(c.get("level") or 80), 255))
    scale = float(c.get("scale") or 1.0)
    radius = max(0.3, float(c.get("radius") or 0.5)) * scale
    reach = max(1.5, float(c.get("reach") or 1.5)) * scale
    rank = int(c.get("rank") or 0)
    faction = int(c.get("faction") or 14)
    return [
        f"-- {c.get('name')} (retail display {c['display']})",
        f"DELETE FROM creature_template_model WHERE CreatureID = {e};",
        f"DELETE FROM creature_template WHERE entry = {e};",
        "INSERT INTO creature_template (entry, name, subname, minlevel, maxlevel, faction, speed_walk, speed_run, "
        "`rank`, unit_class, BaseAttackTime, RangeAttackTime, type, HealthModifier, DamageModifier, "
        "ExperienceModifier, RegenHealth, VerifiedBuild) VALUES "
        f"({e}, {_q(c.get('name') or 'Creature')[:102]}, {_q(c.get('subname') or '') if c.get('subname') else 'NULL'}, "
        f"{level}, {level}, {faction}, 1, 1.14286, {rank}, 1, 2000, 2000, {int(c.get('type') or 10)}, "
        f"{float(c.get('health') or 1.0)}, {float(c.get('damage') or 1.0)}, 1, 1, 0);",
        "INSERT INTO creature_template_model (CreatureID, Idx, CreatureDisplayID, DisplayScale, Probability, VerifiedBuild) "
        f"VALUES ({e}, 0, {d}, {scale}, 1, 0);",
        f"DELETE FROM creature_model_info WHERE DisplayID = {d};",
        "INSERT INTO creature_model_info (DisplayID, BoundingRadius, CombatReach, Gender, DisplayID_Other_Gender) "
        f"VALUES ({d}, {radius:.4f}, {reach:.4f}, 2, 0);",
        "",
    ]


def removal_sql(ids: dict) -> list[str]:
    e, d = ids["entry"], ids["display"]
    return [f"DELETE FROM creature_template_model WHERE CreatureID = {e};",
            f"DELETE FROM creature_template WHERE entry = {e};",
            f"DELETE FROM creature_model_info WHERE DisplayID = {d};", ""]


# -- the DBC rows ---------------------------------------------------------------------------------

def add_rows(md: D.DBCFile, di: D.DBCFile, ids: dict, ex: Export, c: dict) -> None:
    F = D.float_to_u32
    g = c.get("geo") or [-1, -1, 0, 1, 1, 2.5]
    cw, chh = (c.get("collision") or [0.6, 2.2])[:2]
    md.add_record([
        ids["model"], 0, md.add_string(ex.dbc_model_name), 1, F(float(c.get("model_scale") or 1.0)),
        1, 0, F(12.0), F(10.0), F(1.0), 0, 0, 0, 0,
        F(float(cw) or 0.6), F(float(chh) or 2.2), F(float(c.get("mount_height") or 1.87)),
        F(g[0]), F(g[1]), F(g[2]), F(g[3]), F(g[4]), F(g[5]),
        F(1.0), F(1.0), 0, 0, 0,
    ])
    t1, t2, t3 = ex.variations
    di.add_record([
        ids["display"], ids["model"], 0, 0, F(float(c.get("display_scale") or 1.0)),
        max(1, min(int(c.get("alpha") or 255), 255)),
        di.add_string(t1), di.add_string(t2), di.add_string(t3), 0,
        1, 0, 0, 0, 0, 0,
    ])


# -- the creature workbench -----------------------------------------------------------------------

class Creatures:
    """The Creatures page's state: the index, the basket, what is in the game, Install."""

    def __init__(self, wb):
        self.wb = wb
        self._index: CreatureIndex | None = None
        self._lock = threading.Lock()
        self.job = {"state": "idle", "log": [], "steps": [], "result": None}
        self._meshes: dict = {}

    # -- paths and settings ----------------------------------------------------------------
    @property
    def dir(self) -> str:
        d = os.path.join(self.wb.settings.data_dir, "creatures")
        os.makedirs(d, exist_ok=True)
        return d

    def _load(self, name: str, default):
        p = os.path.join(self.dir, name)
        try:
            with open(p, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return default

    def _save(self, name: str, value) -> None:
        p = os.path.join(self.dir, name)
        tmp = p + ".part"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(value, fh, indent=1)
        os.replace(tmp, p)

    def settings(self) -> dict:
        s = self._load("settings.json", {})
        kit = self.wb.kit.cfg
        conf = find_world_conf(getattr(kit, "server_dbc", "") or "", s.get("world_conf", ""))
        db = world_db(conf) if conf else None
        mysql = find_mysql(s.get("mysql", ""))
        return {"world_conf": conf, "world_conf_set": s.get("world_conf", ""), "mysql": mysql,
                "mysql_set": s.get("mysql", ""), "run_sql": s.get("run_sql", True),
                "restart": s.get("restart", False),
                "database": (f"{db['user']}@{db['host']}:{db['port']}/{db['database']}" if db else ""),
                "client": self.wb.settings.client, "server_dbc": getattr(kit, "server_dbc", "") or "",
                "modern_m2": self.modern_m2_state()}

    def set_settings(self, v: dict) -> dict:
        s = self._load("settings.json", {})
        for k in ("world_conf", "mysql"):
            if k in v:
                s[k] = (v[k] or "").strip().strip('"')
        for k in ("run_sql", "restart"):
            if k in v:
                s[k] = bool(v[k])
        self._save("settings.json", s)
        return self.settings()

    def modern_m2_state(self) -> str:
        client = self.wb.settings.client
        if not client:
            return "no client set"
        mod = os.path.join(client, "Mods", "wxl.modern-m2", "mod.json")
        if os.path.isfile(mod):
            return "installed"
        if os.path.isfile(os.path.join(client, "WarcraftXL.dll")):
            return "missing: copy wxl.modern-m2 into the client's Mods folder"
        return "missing: the client needs WarcraftXL (x64) with wxl.modern-m2"

    # -- browsing --------------------------------------------------------------------------
    def source(self):
        key = next((k for k in self.wb.sources if k != "bfa"), None) or next(iter(self.wb.sources), None)
        src = self.wb.reader(key) if key else None
        if src is None:
            raise LookupError("no retail source is loaded yet")
        return key, src

    def index(self) -> CreatureIndex:
        with self._lock:
            if self._index is None:
                _key, src = self.source()
                kit = self.wb.kit.cfg
                cands = [self.wb.settings.listfile, os.path.join(getattr(kit, "work", "") or "", "listfile.csv")]
                self._index = load_index(src, os.path.join(self.wb.settings.data_dir, "cache"), cands, self.wb.say)
            return self._index

    def search(self, q: str, page: int, humanoids: bool, named: bool) -> dict:
        idx = self.index()
        total, rows = idx.search(q, page, humanoids, named)
        key, _src = self.source()
        return {"total": total, "page": page, "rows": rows, "source": key, "build": idx.build}

    def detail(self, did: int) -> dict:
        idx = self.index()
        row = idx.row(did)
        if row is None:
            raise LookupError(f"no creature display {did}")
        key, _src = self.source()
        return row | {"variations": idx.variations(did), "source": key}

    def preview(self, did: int) -> dict:
        idx = self.index()
        row = idx.row(did)
        if row is None:
            raise LookupError(f"no creature display {did}")
        key, src = self.source()
        k = (did,)
        if k not in self._meshes:
            if len(self._meshes) > 40:
                self._meshes.clear()
            notes = []
            data = src.read(row["model"])
            if data[:4] != b"MD21":
                notes.append("Not a chunked (MD21) model: wxl.modern-m2 has nothing to read here.")
            elif "SKID" in _chunks(data):
                notes.append("Its skeleton lives in a .skel file: Install makes it self-contained for the client.")
            self._meshes[k] = {"mesh": M.mesh(src.read, row["model"], textures_of(row)), "notes": notes}
        return {"display": did, "source": key, "row": row, "glow": self.glow(did),
                "state_models": self.state_models(did)} | self._meshes[k]

    def state_models(self, did: int) -> list[dict]:
        """The models the display's state kit hangs on the creature for good (a red ghost's fog, a
        demon's fel flames): {fdid, attachment, scale, offset}."""
        self.glow(did)
        state, kits = self._glow_tables[0], self._glow_tables[1]
        ma, en = self._glow_tables[6], self._glow_tables[7]
        out = []
        for kind, eid in kits.get(state.get(did, 0), []):
            if kind == 2 and eid in ma:
                a = ma[eid]
                fd = int((en.get(a.get("SpellVisualEffectNameID")) or {}).get("ModelFileDataID") or 0)
                if fd:
                    out.append({"fdid": fd, "attachment": int(a.get("AttachmentID", -1)),
                                "scale": float(a.get("Scale") or 1.0) * float((en.get(a.get("SpellVisualEffectNameID")) or {}).get("Scale") or 1.0),
                                "offset": list(a.get("Offset") or [0, 0, 0])})
        return out

    def glow(self, did: int) -> dict | None:
        """The display's state effects that colour the creature itself (its StateSpellVisualKit):
        GradientEffect (kit effect 16: a glow ramping through three colours toward its silhouette, and
        an edge colour) and OutlineEffect (9: an outline in a HighlightColor). For the viewer's glow
        option; None when it has neither."""
        if not hasattr(self, "_glow_tables"):
            _key, src = self.source()
            state = {i: int(r.get("StateSpellVisualKitID") or 0) for i, r in src.table("CreatureDisplayInfo")
                     if r.get("StateSpellVisualKitID")}
            kits: dict[int, list] = {}
            for _i, r in src.table("SpellVisualKitEffect"):
                if r["EffectType"] in (2, 7, 9, 12, 16):
                    kits.setdefault(r["ParentSpellVisualKitID"], []).append((r["EffectType"], r["Effect"]))
            grad = dict(src.table("GradientEffect"))
            outl = dict(src.table("OutlineEffect"))
            hl = dict(src.table("HighlightColor"))
            shad = dict(src.table("ShadowyEffect"))
            wanted = {e for v in kits.values() for t, e in v if t == 2}
            ma = {i: r for i, r in src.table("SpellVisualKitModelAttach") if i in wanted}
            names = {r.get("SpellVisualEffectNameID") for r in ma.values()}
            en = {i: r for i, r in src.table("SpellVisualEffectName") if i in names}
            edge = dict(src.table("EdgeGlowEffect"))
            self._glow_tables = (state, kits, grad, outl, hl, shad, ma, en, edge)
        state, kits, grad, outl, hl, shad = self._glow_tables[:6]
        out = {}

        def argb(v):
            v = int(v or 0) & 0xFFFFFFFF
            return [(v >> 16 & 255) / 255, (v >> 8 & 255) / 255, (v & 255) / 255]
        for kind, eid in kits.get(state.get(did, 0), []):
            if kind == 7 and eid in shad and "colors" not in out:
                # ShadowyEffect: a rim of its primary colour (Fel Corruption's green), its inner and outer
                # strengths how much it fills the body and how bright its edge is
                s = shad[eid]
                c = argb(s.get("PrimaryColor"))
                if any(c):
                    inner = float(s.get("InnerStrength") or 1.0)
                    outer = float(s.get("OuterStrength") or 1.0)
                    out["colors"] = [[x * 0.15 for x in c], [x * 0.6 for x in c], c]
                    out["alphas"] = [min(1.0, 0.25 * inner), min(1.0, 0.9 * outer)]
                    out.setdefault("edge", c)
                continue
            if kind == 16 and eid in grad:
                g = grad[eid]
                rgb = lambda p: [float(g.get(f"{p}_r") or 0), float(g.get(f"{p}_g") or 0), float(g.get(f"{p}_b") or 0)]
                out["colors"] = [rgb("Colors0"), rgb("Colors1"), rgb("Colors2")]
                out["alphas"] = [float(g.get("Alpha1") or 0.5), float(g.get("Alpha2") or 0.8)]
                edge = rgb("EdgeColor")
                if any(edge):
                    out["edge"] = edge
            elif kind == 9 and eid in outl:
                c = hl.get(int(outl[eid].get("HighlightColorID") or 0)) or {}
                out.setdefault("edge", argb(c.get("StartColor") if c.get("StartColor") is not None else -1))
        return out or None

    def kit_glow(self, kit: int) -> dict | None:
        """What a spell visual kit does to the unit's own body, as one set of numbers the game
        (wxl.retail-spellvisuals) and the preview both draw: a fresnel ramp over the body from its
        middle to its silhouette (``colors`` C0 -> C1 -> C2, ``alphas`` middle and edge, ``power`` the
        ramp's exponent) and a halo just outside it (``halo`` colour, ``halo_width`` pixels,
        ``halo_alpha``), fading in and out over ``fade`` seconds. From EdgeGlowEffect (12: Avenging
        Wrath's gold, Bestial Wrath's red), ShadowyEffect (7: Combustion), GradientEffect (16) and
        OutlineEffect (9). None for a kit that does none of these."""
        self.glow(0)                                      # loads the tables
        _state, kits, grad, outl, hl, shad, _ma, _en, edge = self._glow_tables

        def argb(v):
            v = int(v or 0) & 0xFFFFFFFF
            return [(v >> 16 & 255) / 255, (v >> 8 & 255) / 255, (v & 255) / 255]
        out: dict = {}
        for kind, eid in kits.get(int(kit or 0), []):
            if kind == 12 and eid in edge and "colors" not in out:
                g = edge[eid]
                mult = float(g.get("GlowMultiplier") or 1.0)
                c = [float(g.get(k) or 0) * mult for k in ("GlowRed", "GlowGreen", "GlowBlue")]
                a = float(g.get("GlowAlpha") or 1.0)
                out.update(colors=[c, c, c], alphas=[0.3 * a, a], power=max(0.1, float(g.get("FresnelCoefficient") or 1.0)),
                           halo=[x * 0.5 for x in c], halo_width=6, halo_alpha=0.6 * a,
                           fade=[float(g.get("FadeIn") or 0), float(g.get("FadeOut") or 0)])
            elif kind == 7 and eid in shad and "colors" not in out:
                g = shad[eid]
                p, q = argb(g.get("PrimaryColor")), argb(g.get("SecondaryColor"))
                inner, outer = float(g.get("InnerStrength") or 1.0), float(g.get("OuterStrength") or 1.0)
                out.update(colors=[[x * 0.5 for x in q], q, p], alphas=[0.3 * inner, outer], power=1.0,
                           halo=p, halo_width=7, halo_alpha=0.7 * outer,
                           fade=[float(g.get("FadeInTime") or 0), float(g.get("FadeOutTime") or 0)])
            elif kind == 16 and eid in grad and "colors" not in out:
                g = grad[eid]
                rgb = lambda k: [float(g.get(f"{k}_r") or 0), float(g.get(f"{k}_g") or 0), float(g.get(f"{k}_b") or 0)]
                out.update(colors=[rgb("Colors0"), rgb("Colors1"), rgb("Colors2")],
                           alphas=[0.0, float(g.get("Alpha2") or 0.8)], power=1.0, fade=[0.25, 0.5])
                e = rgb("EdgeColor")
                if any(e):
                    out.update(halo=e, halo_width=2, halo_alpha=1.0)
            elif kind == 9 and eid in outl and "halo" not in out:
                c = hl.get(int(outl[eid].get("HighlightColorID") or 0)) or {}
                out.update(halo=argb(c.get("StartColor") if c.get("StartColor") is not None else -1),
                           halo_width=2, halo_alpha=1.0)
                out.setdefault("fade", [0.25, 0.5])
        if not out:
            return None
        out.setdefault("colors", [[0, 0, 0]] * 3)
        out.setdefault("alphas", [0.0, 0.0])
        out.setdefault("power", 1.0)
        out.setdefault("halo", [0, 0, 0])
        out.setdefault("halo_width", 0)
        out.setdefault("halo_alpha", 0.0)
        return out

    # -- the basket and the game -----------------------------------------------------------
    def basket(self) -> list:
        return self._load("basket.json", [])

    def set_basket(self, entries: list) -> list:
        clean = []
        seen = set()
        for e in entries:
            did = int(e.get("display") or 0)
            if not did or did in seen:
                continue
            seen.add(did)
            clean.append({k: e[k] for k in ("display", "name", "subname", "level", "faction", "rank", "scale",
                                              "health", "damage", "type", "out", "mount") if k in e})
        self._save("basket.json", clean)
        return clean

    def installed(self) -> list:
        return self._load("installed.json", [])

    def ids(self) -> dict:
        return self._load("ids.json", {})

    def state(self) -> dict:
        ids = self.ids()
        installed = [e | {"ids": ids.get(str(e["display"]))} for e in self.installed()]
        return {"basket": self.basket(), "installed": installed, "settings": self.settings(), "job": self.job_view(0),
                "factions": FACTIONS, "ranks": RANKS}

    # -- Install -------------------------------------------------------------------------------
    def job_view(self, since: int) -> dict:
        j = self.job
        return {"state": j["state"], "steps": j["steps"], "result": j["result"], "log": j["log"][since:],
                "at": len(j["log"])}

    # CreatureSoundData columns that hold no SoundKit
    _NOT_SOUNDS = {"ID", "NPCSoundID", "CreatureImpactType", "SoundFootstepID", "SoundInjuryCrushingBlowID",
                   "FidgetDelaySecondsMin", "FidgetDelaySecondsMax", "CreatureSoundDataIDPet"}

    def _sounds(self, src, client: str, displays: dict[int, int], di: D.DBCFile, files: dict) -> D.DBCFile | None:
        """Retail's creature sounds (aggro, attack, wound, death, fidgets, greetings) for the new
        displays: CreatureSoundData and NPCSounds rows made from retail's, column by column, each
        SoundKit a SoundEntries row (sounds.SoundPort). The SoundEntries table, or None."""
        from ..dbclayout import DbcLayout
        from . import sounds as SND
        dbd = getattr(self.wb.settings, "dbd", "") or ""
        if not dbd or not os.path.isdir(dbd):
            self._say("creature sounds need the WoWDBDefs folder (Settings)")
            return None
        rcdi = {i: dict(r) for i, r in src.table("CreatureDisplayInfo") if i in displays}
        # a display without a sound set of its own plays its model's (CreatureModelData.SoundID)
        bare = {int(r.get("ModelID") or 0) for r in rcdi.values() if not r.get("SoundID")}
        if bare:
            model_sound = {i: int(r.get("SoundID") or 0) for i, r in src.table("CreatureModelData") if i in bare}
            for r in rcdi.values():
                if not r.get("SoundID"):
                    r["SoundID"] = model_sound.get(int(r.get("ModelID") or 0), 0)
        want_csd = {int(r.get("SoundID") or 0) for r in rcdi.values()} - {0}
        want_npc = {int(r.get("NPCSoundID") or 0) for r in rcdi.values()} - {0}
        if not want_csd and not want_npc:
            return None
        rcsd = {i: r for i, r in src.table("CreatureSoundData") if i in want_csd}
        rnpc = {i: r for i, r in src.table("NPCSounds") if i in want_npc} if want_npc else {}
        cd = ClientData(client, top=PATCH_NAME)
        cd.sources = [s for s in cd.sources
                      if os.path.basename(s[1] if isinstance(s[1], str) else s[1].path).lower() != PATCH_NAME.lower()]
        try:
            entries = D.DBCFile.from_bytes(cd.read(SND.TABLE), "SoundEntries.dbc")
            csd = D.DBCFile.from_bytes(cd.read("DBFilesClient\\CreatureSoundData.dbc"), "CreatureSoundData.dbc")
            npc = D.DBCFile.from_bytes(cd.read("DBFilesClient\\NPCSounds.dbc"), "NPCSounds.dbc")
            kit = self.wb.kit.cfg
            listfile = find_listfile([self.wb.settings.listfile, os.path.join(getattr(kit, "work", "") or "", "listfile.csv")],
                                     os.path.join(self.wb.settings.data_dir, "cache"), self._say)
            sp = SND.SoundPort(src, listfile, entries, SND.CREATURE_RANGE, cd.exists)
            L = DbcLayout("CreatureSoundData", dbd)
            if L.field_count != csd.field_count:
                raise CreatureError(f"CreatureSoundData.dbc has {csd.field_count} fields, WoWDBDefs says {L.field_count}")
            made_csd, made_npc = {}, {}
            for rid, r in rcsd.items():
                row = L.blank()
                nid = max(30000, csd.max_id() + 1)
                row[0] = nid
                for name, (start, width) in L.columns.items():
                    if name == "ID":
                        continue
                    vals = r.get(name)
                    vals = list(vals) if isinstance(vals, (list, tuple)) else [vals]
                    for k in range(min(width, len(vals))):
                        v = vals[k] or 0
                        if name.startswith("FidgetDelay"):
                            row[start + k] = D.float_to_u32(float(v))
                        elif name == "CreatureImpactType":
                            row[start + k] = int(v)
                        elif name not in self._NOT_SOUNDS:
                            row[start + k] = sp.kit(int(v))
                csd.add_record(row)
                made_csd[rid] = nid
            for rid, r in rnpc.items():
                kits = list(r.get("SoundID") or [])
                nid = max(30000, npc.max_id() + 1)
                npc.add_record([nid] + [sp.kit(int(x or 0)) for x in (kits + [0] * 4)[:4]])
                made_npc[rid] = nid
            for did, new_display in displays.items():
                r = rcdi.get(did)
                rec = di.find_by_id(new_display) if r else None
                if rec is None:
                    continue
                rec[2] = made_csd.get(int(r.get("SoundID") or 0), 0)
                rec[12] = made_npc.get(int(r.get("NPCSoundID") or 0), 0)    # 3.3.5: after SizeClass, BloodID
            files.update(sp.files)
            files[SND.TABLE] = entries.to_bytes()
            files["DBFilesClient\\CreatureSoundData.dbc"] = csd.to_bytes()
            files["DBFilesClient\\NPCSounds.dbc"] = npc.to_bytes()
            self._say(f"sounds: {len(made_csd)} creature sound set(s), {len([x for x in sp.made.values() if x])} "
                      f"sound kit(s), {len(sp.files)} file(s)")
            for m in sp.missing[:5]:
                self._say(f"  {m}")
            return entries
        finally:
            cd.close()

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
            raise CreatureError("an install is already running")
        self.job = {"state": "running", "log": [], "steps": [], "result": None}
        threading.Thread(target=self._install_guarded, daemon=True, name="creature-install").start()
        return self.job_view(0)

    def _install_guarded(self) -> None:
        self._restart = None
        try:
            result = self.install()
        except Exception as e:
            self._say(f"stopped: {type(e).__name__}: {e}")
            for s in self.job["steps"]:
                if s["state"] == "running":
                    s["state"] = "failed"
            result = {"ok": False, "error": f"{e}"}
        # what Install closed is started again, also when the install stopped half-way
        if self._restart is not None:
            name = "Start the worldserver and client"
            self._step(name, "running")
            try:
                result["restarted"] = self._restart.start_all()
                self._step(name, "done")
            except Exception as e:
                self._say(f"could not start them again: {e}")
                self._step(name, "failed")
            self._restart = None
        self.job["result"] = result
        self.job["state"] = "done" if result.get("ok") else "failed"

    def install_list(self) -> list:
        """What the game will hold: what's in it, minus what's taken out, then the basket."""
        basket = {int(e["display"]): e for e in self.basket()}
        out = []
        for e in self.installed():
            d = int(e["display"])
            if d in basket:
                continue
            if not e.get("out"):
                out.append(e)
        for e in basket.values():
            if not e.get("out"):
                out.append(e)
        return out

    def install(self) -> dict:
        wb, kit = self.wb, self.wb.kit.cfg
        client, server_dbc = wb.settings.client, getattr(kit, "server_dbc", "") or ""
        if not client or not os.path.isdir(os.path.join(client, "Data")):
            raise CreatureError("Settings has no 3.3.5 client folder")
        st = self.settings()
        if st["modern_m2"] != "installed":
            self._say(f"warning: wxl.modern-m2 is {st['modern_m2']} - the creatures will not load without it")
        wanted = self.install_list()
        idx = self.index()
        _key, src = self.source()

        # 1. export
        self._step("Export models and textures", "running")
        exports: dict[int, Export] = {}
        rows: dict[int, dict] = {}
        notes: dict[int, list] = {}
        stems: set[str] = set()
        for e in wanted:
            did = int(e["display"])
            row = idx.row(did)
            if row is None:
                raise CreatureError(f"retail display {did} is not in {idx.build}")
            stem = row["stem"]
            if stem.lower() in stems:
                stem = f"{stem}_{did}"
            stems.add(stem.lower())
            self._say(f"export {e.get('name') or row['name']} (display {did}, model {row['model']})")
            ex = export_display(src.read, row, stem)
            for n in ex.notes:
                self._say(f"  {n}")
            exports[did], rows[did], notes[did] = ex, row, ex.notes
            self._say(f"  {len(ex.files)} files: {ex.textures} textures, {ex.anims} .anim")
        self._step("Export models and textures", "done")

        # 2. ids
        self._step("Number the creatures", "running")
        cd = ClientData(client, top=PATCH_NAME)
        # ClientData's `top` keeps the named patch itself among the sources: the base is what lies
        # strictly below ours, or every install would build on its own last rows (and renumber them)
        cd.sources = [s for s in cd.sources
                      if os.path.basename(s[1] if isinstance(s[1], str) else s[1].path).lower() != PATCH_NAME.lower()]
        try:
            base_md = D.load_dbc(cd.read("DBFilesClient\\CreatureModelData.dbc"), "CreatureModelData.dbc",
                                 D.CREATURE_MODEL_DATA_FIELDS)
            base_di = D.load_dbc(cd.read("DBFilesClient\\CreatureDisplayInfo.dbc"), "CreatureDisplayInfo.dbc",
                                 D.CREATURE_DISPLAY_INFO_FIELDS)
            shadow = [cd.shadowed_by(n) for n in ("DBFilesClient\\CreatureModelData.dbc",
                                                  "DBFilesClient\\CreatureDisplayInfo.dbc")]
        finally:
            cd.close()
        for s in shadow:
            if s:
                self._say(f"warning: {s} outranks {PATCH_NAME} and has its own creature tables - the client "
                          "reads those instead")
        sbase = self._server_bases(server_dbc)
        ids = self.ids()
        retired = set(self._load("retired.json", []))     # display ids this tool gave out and no longer uses
        used_d = {i["display"] for i in ids.values()} | retired
        used_m = {i["model"] for i in ids.values()}
        used_e = {i["entry"] for i in ids.values()}
        floor_d = max([DISPLAY_FLOOR, base_di.max_id()] + ([sbase["di"].max_id()] if sbase else []))
        floor_m = max([DISPLAY_FLOOR, base_md.max_id()] + ([sbase["md"].max_id()] if sbase else []))
        db = world_db(st["world_conf"]) if st["world_conf"] else None
        max_entry = ENTRY_FLOOR
        if db and st["mysql"] and st["run_sql"]:
            try:
                out = run_sql(st["mysql"], db, "SELECT MAX(entry) FROM creature_template;")
                vals = [l for l in out.splitlines() if l.strip().isdigit()]
                if vals:
                    max_entry = max(max_entry, int(vals[-1]) + 1)
            except Exception as e:
                self._say(f"could not ask the database for its highest entry ({e}); numbering from {max_entry}")

        def free(start, used, taken_in=None):
            n = start + 1
            while n in used or (taken_in is not None and taken_in.find_by_id(n) is not None):
                n += 1
            return n
        for did in exports:
            k = str(did)
            have = ids.get(k)
            if have and base_di.find_by_id(have["display"]) is None and base_md.find_by_id(have["model"]) is None:
                continue                                    # its numbers are still its own
            if have:
                retired.add(have["display"])            # its world rows are dropped by the SQL below
            dn = free(floor_d, used_d, base_di)
            mn = free(floor_m, used_m, base_md)
            en = have["entry"] if have else free(max_entry - 1, used_e)
            ids[k] = {"display": dn, "model": mn, "entry": en}
            used_d.add(dn), used_m.add(mn), used_e.add(en)
        current = {i["display"] for i in ids.values()}
        self._save("ids.json", ids)
        self._save("retired.json", sorted(retired - current))
        self._step("Number the creatures", "done")

        # the client holds the patch open and the worldserver reads its tables at start: close both
        # now, after the slow export, and start them when Install is done (_install_guarded)
        if st["restart"] and not getattr(self, "no_restart", False):      # the Mounts page closed them itself
            self._step("Close the client and worldserver", "running")
            self._restart = Restart(client, st["world_conf"], self._say)
            self._restart.stop()
            self._step("Close the client and worldserver", "done")

        # 3. client patch
        self._step(f"Build Data\\{PATCH_NAME}", "running")
        md, di = base_md, base_di
        files: dict[str, bytes] = {}
        for did, ex in exports.items():
            c = self._creature(did, wanted, rows[did])
            add_rows(md, di, ids[str(did)], ex, c)
            files.update(ex.files)
        sound_table = None
        try:
            sound_table = self._sounds(src, client, {did: ids[str(did)]["display"] for did in exports}, di, files)
        except Exception as e:
            self._say(f"creature sounds left out: {type(e).__name__}: {e}")
        try:
            self._physics(src, exports, rows, files)
        except Exception as e:
            self._say(f"creature physics left out: {type(e).__name__}: {e}")
        files["DBFilesClient\\CreatureModelData.dbc"] = md.to_bytes()
        files["DBFilesClient\\CreatureDisplayInfo.dbc"] = di.to_bytes()
        patch = os.path.join(client, "Data", PATCH_NAME)
        backup_dir = os.path.join(self.dir, "backups", time.strftime("%Y%m%d-%H%M%S"))
        os.makedirs(backup_dir, exist_ok=True)
        if os.path.isfile(patch):
            shutil.copy2(patch, os.path.join(backup_dir, PATCH_NAME))
        if exports:
            tmp = patch + ".part"
            write_archive(tmp, files)
            try:
                os.replace(tmp, patch)
            except PermissionError:
                os.remove(tmp)
                raise CreatureError(f"{PATCH_NAME} is in use - close World of Warcraft and install again")
            size = os.path.getsize(patch)
            self._say(f"Data\\{PATCH_NAME}: {len(files)} files, {size / 1048576:.1f} MB")
            if sound_table is not None:
                # the spells' patch outranks ours and has a SoundEntries.dbc of its own: ours go in it too
                from . import sounds as SND
                from .spellport import PATCH_NAME as SPELL_PATCH
                try:
                    SND.merge_into(os.path.join(client, "Data", SPELL_PATCH), sound_table, SND.CREATURE_RANGE, self._say)
                except PermissionError:
                    self._say(f"{SPELL_PATCH} is in use: the creature sounds play after the next spell install")
        elif os.path.isfile(patch):
            os.remove(patch)
            self._say(f"Data\\{PATCH_NAME} removed: no creatures left")
        self._step(f"Build Data\\{PATCH_NAME}", "done")

        # 4. server tables
        if sbase:
            self._step("Server creature tables", "running")
            smd, sdi = sbase["md"], sbase["di"]
            for did, ex in exports.items():
                add_rows(smd, sdi, ids[str(did)], ex, self._creature(did, wanted, rows[did]))
            for name, t in (("CreatureModelData.dbc", smd), ("CreatureDisplayInfo.dbc", sdi)):
                dest = os.path.join(server_dbc, name)
                if os.path.isfile(dest):
                    shutil.copy2(dest, os.path.join(backup_dir, "server-" + name))
                t.save(dest)
            self._say(f"server: {len(exports)} creature(s) in {server_dbc}")
            self._step("Server creature tables", "done")
        else:
            self._say("no server dbc folder in Settings: the server's creature tables were left alone")

        # 5. SQL
        self._step("World database", "running")
        lines = ["-- Retroport Workbench: creatures. Run against the world database.", ""]
        # a display this tool numbered before and no longer uses has no row in any creature table
        # now: AzerothCore stops at boot on a creature_model_info row whose display it can't find
        gone = sorted(retired - current)
        if gone:
            lines += ["-- display ids given out by earlier installs and since renumbered or taken out",
                      f"DELETE FROM creature_template_model WHERE CreatureDisplayID IN ({', '.join(map(str, gone))});",
                      f"DELETE FROM creature_model_info WHERE DisplayID IN ({', '.join(map(str, gone))});", ""]
        installed_before = {int(e["display"]) for e in self.installed()}
        for did in installed_before - set(exports):
            if str(did) in ids:
                lines += [f"-- taken out: retail display {did}"] + removal_sql(ids[str(did)])
        for did in exports:
            lines += creature_sql(self._creature(did, wanted, rows[did]) | {"display": did}, ids[str(did)])
        sql = "\n".join(lines)
        sql_path = os.path.join(self.dir, "retroport-creatures.sql")
        with open(sql_path, "w", encoding="utf-8") as fh:
            fh.write(sql)
        ran = False
        if db and st["mysql"] and st["run_sql"]:
            run_sql(st["mysql"], db, sql)
            ran = True
            self._say(f"SQL applied to {db['database']} ({len(exports)} creature(s))")
        else:
            why = "turned off" if not st["run_sql"] else ("no worldserver.conf found" if not db else "no MySQL client found")
            self._say(f"SQL not run ({why}): apply {sql_path} yourself")
        self._step("World database", "done")

        # 6. the client's cache (it keeps creature names and models it was told about)
        cache = os.path.join(client, "Cache")
        if os.path.isdir(cache):
            shutil.rmtree(cache, ignore_errors=True)
            self._say("cleared the client's Cache folder")

        # 7. what's in the game now
        now = []
        for e in wanted:
            did = int(e["display"])
            now.append({k: v for k, v in e.items() if k != "out"} | {"name": e.get("name") or rows[did]["name"]})
        self._save("installed.json", now)
        self._save("basket.json", [])
        result = {"ok": True, "sql": sql_path, "sql_ran": ran, "patch": patch, "backup": backup_dir,
                  "creatures": [{"display": int(e["display"]), "name": e["name"], **ids[str(e["display"])],
                                 "notes": notes.get(int(e["display"]), [])} for e in now],
                  "restart": bool(sbase) or ran}
        self._say("done: .npc add <entry> in game" if st["restart"] else
                  "done: restart the worldserver, start the client, and .npc add <entry> in game")
        return result

    def _physics(self, src, exports: dict, rows: dict, files: dict) -> None:
        """Retail physics (hair, cloth, tails, chains) for every creature whose model has a .phys:
        DBFilesClient\\WXLCreaturePhysics.phy2, which Equip Plus runs live in the client."""
        from . import physics as PH
        models = []
        for did, ex in exports.items():
            phys = PH.phys_bytes(src.read(rows[did]["model"]), src.read)
            if phys:
                # every name the client may report: the file it loads, the DBC's .mdx, the bare name
                models.append(([ex.model_path, ex.dbc_model_name, f"{ex.stem}.m2"], phys))
        if not models:
            return
        table, notes = PH.table(self.wb.kit.cfg.tools, models)
        for n in notes:
            self._say(f"  {n}")
        if table:
            files[PH.CREATURE_TABLE] = table
            self._say(f"physics for {len(models)} creature(s): moved live by Equip Plus (F9 to switch it)")

    def _creature(self, did: int, wanted: list, row: dict) -> dict:
        e = next((x for x in wanted if int(x["display"]) == did), {})
        scale = float(e.get("scale") or 1.0)
        geo = row["geo"]
        span = max(abs(geo[3] - geo[0]), abs(geo[4] - geo[1]), 0.5) if geo and len(geo) == 6 else 1.0
        return {"name": e.get("name") or row["name"], "subname": e.get("subname", ""), "level": e.get("level", 80),
                "faction": e.get("faction", 14), "rank": e.get("rank", 0), "scale": scale,
                "health": e.get("health", 1.0), "damage": e.get("damage", 1.0), "type": e.get("type", 10),
                "geo": geo, "collision": row["collision"], "model_scale": row["model_scale"],
                "display_scale": row["scale"], "alpha": row["alpha"], "mount_height": row.get("mount_height") or 0.0,
                "radius": span * row["scale"] * row["model_scale"] / 2, "reach": span * row["scale"] * row["model_scale"] / 2}

    def _server_bases(self, server_dbc: str) -> dict | None:
        """The server's creature tables as they were before the first creature install (a copy kept
        then), so every install builds on the same rows."""
        if not server_dbc or not os.path.isdir(server_dbc):
            return None
        base_dir = os.path.join(self.dir, "server-base")
        os.makedirs(base_dir, exist_ok=True)
        out = {}
        for key, name, fields in (("md", "CreatureModelData.dbc", D.CREATURE_MODEL_DATA_FIELDS),
                                  ("di", "CreatureDisplayInfo.dbc", D.CREATURE_DISPLAY_INFO_FIELDS)):
            kept = os.path.join(base_dir, name)
            if not os.path.isfile(kept):
                live = os.path.join(server_dbc, name)
                if not os.path.isfile(live):
                    return None
                shutil.copy2(live, kept)
            with open(kept, "rb") as fh:
                out[key] = D.load_dbc(fh.read(), name, fields)
        return out
