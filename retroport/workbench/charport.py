"""BfA's character bodies in the 3.3.5 client, in place of the ones it has.

A player's body is ``Character\\<Race>\\<Sex>\\<Race><Sex>.m2``: the client dresses it itself - skin
and face from CharSections painted on texture type 1, hair on type 6, a cape on 2, hair, beards and
armour shapes switched on by geoset number. BfA's HD bodies of the classic races keep WoD's scheme
(the same texture layout, the same geoset groups, a few more variants, their eyes on 1702), so the
body file alone changes: BfA's model, its skeleton folded back in from its .skel, its skins and
.anim files and its own textures (wxl.modern-m2 reads it as retail made it), written under the
client's names into ``Data\\patch-I.MPQ`` - above patch-H, where WoD's bodies usually are.

With the body comes BfA's animation set (ids up to about 1000), what retail's spells play on
their caster.
"""

from __future__ import annotations

import os
import shutil
import time

from ..mpq import ClientData, write_archive
from .creatures import CreatureError, export_display

PATCH_NAME = "patch-I.MPQ"
SEXES = ("Male", "Female")


def body_paths(folder: str, sex: int) -> tuple[str, str]:
    """The client's folder and file stem of a race's body: ``Character\\Human\\Male``, ``HumanMale``."""
    sexed = SEXES[1 if sex else 0]
    return f"Character\\{folder}\\{sexed}", f"{folder}{sexed}"


# The client paints a body's skin on the classic layout (CCharacterComponent::s_sectionInfoRaw: 512 x
# 512, arms, hand and the face strips on the left, torso, legs and feet on the right). BfA's HD
# bodies read the HD layout (CharComponentTextureLayouts 2: 1024 x 512): the same body rectangles in
# its left half, the face one 512 x 512 square in its right half. So a skin vertex's texture
# coordinate moves: the body half stretches to the whole width, the face square squeezes into the
# classic face strips (head upper 0,320 256x64 over head lower 0,384 256x128).
HD_W, HD_H = 1024, 512
CLASSIC = 512
FACE_X, FACE_Y, FACE_W, FACE_H = 0, 320, 256, 192
SKIN_TEXTURE = 1                   # M2 texture type the client puts the composited skin on


def classic_uv(u: float, v: float) -> tuple[float, float]:
    """A texture coordinate on BfA's HD layout, on the client's classic layout."""
    px, py = u * HD_W, v * HD_H
    if px < CLASSIC:
        return px / CLASSIC, py / CLASSIC
    fx, fy = (px - CLASSIC) / CLASSIC, py / HD_H
    return (FACE_X + fx * FACE_W) / CLASSIC, (FACE_Y + fy * FACE_H) / CLASSIC


def section_vertex_starts(skin: bytes) -> list[int]:
    """Each skin section's first vertex. The field is 16 bits and wraps on a skin of more than
    65535 vertices (BfA's bodies have about 74000); sections follow one another, so each start is
    the stored one lifted past the previous section's."""
    import struct
    sm_n, sm_o = struct.unpack_from("<II", skin, 4 + 8 * 3)
    out, prev = [], 0
    for k in range(sm_n):
        vs, = struct.unpack_from("<H", skin, sm_o + k * 0x30 + 4)
        true = (prev & ~0xFFFF) | vs
        if true + 0x8000 < prev:
            true += 0x10000
        out.append(true)
        prev = max(prev, true)
    return out


def remap_skin_uvs(m2: bytes, skin: bytes) -> tuple[bytes, int]:
    """Moves the texture coordinates of every vertex the skin texture covers (batches whose first
    texture is of type 1) from the HD layout to the classic one. Coordinates outside 0..1 (tiled
    details) are left. Returns the model and how many vertices moved."""
    import struct
    pos = 0
    md = None
    while pos + 8 <= len(m2):
        tag, size = m2[pos:pos + 4], struct.unpack_from("<I", m2, pos + 4)[0]
        if tag == b"MD21":
            md = pos + 8
            break
        pos += 8 + size
    if md is None:
        return m2, 0
    out = bytearray(m2)
    tn, to = struct.unpack_from("<II", out, md + 0x50)
    types = [struct.unpack_from("<I", out, md + to + 16 * k)[0] for k in range(tn)]
    ln, lo = struct.unpack_from("<II", out, md + 0x80)
    look = list(struct.unpack_from(f"<{ln}h", out, md + lo)) if ln else []
    vn, vo = struct.unpack_from("<II", out, md + 0x3C)
    vi_n, vi_o = struct.unpack_from("<II", skin, 4)
    vidx = struct.unpack_from(f"<{vi_n}H", skin, vi_o)
    sm_n, sm_o = struct.unpack_from("<II", skin, 4 + 8 * 3)
    bn, bo = struct.unpack_from("<II", skin, 4 + 8 * 4)
    sections = set()
    for k in range(bn):
        sub, = struct.unpack_from("<H", skin, bo + k * 0x18 + 4)
        tcombo, = struct.unpack_from("<H", skin, bo + k * 0x18 + 0x10)
        if tcombo < ln and 0 <= look[tcombo] < tn and types[look[tcombo]] == SKIN_TEXTURE:
            sections.add(sub)
    moved = set()
    starts = section_vertex_starts(skin)
    for sub in sections:
        if sub >= sm_n:
            continue
        vcount, = struct.unpack_from("<H", skin, sm_o + sub * 0x30 + 6)
        first = starts[sub]
        for j in range(first, min(first + vcount, vi_n)):
            v = vidx[j]
            if v in moved or v >= vn:
                continue
            at = md + vo + v * 48 + 32
            u, w = struct.unpack_from("<2f", out, at)
            if 0.0 <= u <= 1.0 and 0.0 <= w <= 1.0:
                struct.pack_into("<2f", out, at, *classic_uv(u, w))
            moved.add(v)
    return bytes(out), len(moved)


def _md21(m2: bytes) -> int | None:
    import struct
    if m2[:4] != b"MD21":
        return 0 if m2[:4] == b"MD20" else None
    return 8


def align_attachments(m2: bytes, ref: bytes, tolerance: float = 0.05) -> tuple[bytes, list[int]]:
    """Moves each attachment point the body shares with ``ref`` (the client's own body, the one
    its helms, shoulders and weapons were made for) to where ``ref`` has it, when it is more than
    ``tolerance`` away: BfA's helm point sits 22 cm lower than WoD's, and a WoD helm then sinks into
    the chest. The point stays on its own bone. Returns the model and the ids moved."""
    import math
    import struct
    a, b = _md21(m2), _md21(ref)
    if a is None or b is None:
        return m2, []

    def points(data, base):
        n, o = struct.unpack_from("<II", data, base + 0xF0)
        return {struct.unpack_from("<I", data, base + o + 0x28 * k)[0]: base + o + 0x28 * k + 8 for k in range(n)}
    out = bytearray(m2)
    mine, theirs = points(out, a), points(ref, b)
    moved = []
    for aid, at in mine.items():
        if aid not in theirs:
            continue
        p = struct.unpack_from("<3f", out, at)
        q = struct.unpack_from("<3f", ref, theirs[aid])
        if math.dist(p, q) > tolerance:
            struct.pack_into("<3f", out, at, *q)
            moved.append(aid)
    return bytes(out), sorted(moved)


def client_body(client: str, folder: str, sex: int) -> bytes | None:
    """The client's own body of a race, as it is without this tool's patch."""
    from ..mpq import ClientData
    game_folder, stem = body_paths(folder, sex)
    name = f"{game_folder}\\{stem}.m2"
    cd = ClientData(client)
    for label, src in cd.sources:
        if PATCH_NAME.lower() in label.lower():
            continue
        try:
            if isinstance(src, str):
                path = os.path.join(src, *name.split("\\"))
                if os.path.isfile(path):
                    with open(path, "rb") as fh:
                        return fh.read()
            else:
                data = src.read(name)
                if data:
                    return data
        except Exception:
            continue
    return None


def _skin_vertices(m2: bytes, skin: bytes) -> tuple:
    """Positions and texture coordinates of the vertices the skin texture covers (numpy arrays),
    and their indices in the model."""
    import struct
    import numpy as np
    base = _md21(m2)
    n, o = struct.unpack_from("<II", m2, base + 0x3C)
    raw = np.frombuffer(m2, dtype=np.uint8, count=n * 48, offset=base + o).reshape(n, 48)
    pos = raw[:, 0:12].copy().view(np.float32).reshape(n, 3)
    uv = raw[:, 32:40].copy().view(np.float32).reshape(n, 2)
    tn, to = struct.unpack_from("<II", m2, base + 0x50)
    types = [struct.unpack_from("<I", m2, base + to + 16 * k)[0] for k in range(tn)]
    ln, lo = struct.unpack_from("<II", m2, base + 0x80)
    look = struct.unpack_from(f"<{ln}h", m2, base + lo)
    vi_n, vi_o = struct.unpack_from("<II", skin, 4)
    vidx = np.frombuffer(skin, dtype=np.uint16, count=vi_n, offset=vi_o)
    sm_n, sm_o = struct.unpack_from("<II", skin, 4 + 24)
    bn, bo = struct.unpack_from("<II", skin, 4 + 32)
    starts = section_vertex_starts(skin)
    chosen = set()
    for k in range(bn):
        sub, = struct.unpack_from("<H", skin, bo + k * 0x18 + 4)
        tc, = struct.unpack_from("<H", skin, bo + k * 0x18 + 0x10)
        if sub < sm_n and tc < ln and 0 <= look[tc] < tn and types[look[tc]] == SKIN_TEXTURE:
            vc, = struct.unpack_from("<H", skin, sm_o + sub * 0x30 + 6)
            chosen.update(int(x) for x in vidx[starts[sub]:starts[sub] + vc])
    idx = np.array(sorted(chosen), dtype=np.int64)
    return pos[idx], uv[idx], idx


def transfer_face_uvs(hd_m2: bytes, m2: bytes, skin: bytes, ref_m2: bytes, ref_skin: bytes) -> tuple[bytes, int, int]:
    """The face as the client's own body maps it: BfA's head is WoD's, refined, and most of its face
    vertices sit exactly on one of WoD's. Those take that vertex's texture coordinate; the others
    an affine fit of their nearest matched neighbours on BfA's face square, so the face stays
    continuous. ``hd_m2`` has BfA's own coordinates (which vertices are the face, and where on the
    square), ``m2`` is written. Returns the model, how many matched and how many were fitted."""
    import struct
    import numpy as np
    bpos, buv, bidx = _skin_vertices(hd_m2, skin)
    wpos, wuv, _w = _skin_vertices(ref_m2, ref_skin)
    face = (buv[:, 0] * HD_W >= CLASSIC) & (buv[:, 1] >= 0) & (buv[:, 1] <= 1)
    wface = (wuv[:, 0] * CLASSIC < FACE_X + FACE_W) & (wuv[:, 1] * CLASSIC >= FACE_Y) & (wuv[:, 1] <= 1)
    if not face.any() or not wface.any():
        return m2, 0, 0
    fp, fu, fi = bpos[face], buv[face], bidx[face]
    wp, wu = wpos[wface], wuv[wface]
    nearest = np.empty(len(fp), dtype=np.int64)
    dist = np.empty(len(fp), dtype=np.float32)
    for s in range(0, len(fp), 256):
        d = ((fp[s:s + 256, None, :] - wp[None, :, :]) ** 2).sum(-1)
        nearest[s:s + 256] = d.argmin(1)
        dist[s:s + 256] = np.sqrt(d.min(1))
    exact = dist < 0.001
    out_uv = np.zeros_like(fu)
    out_uv[exact] = wu[nearest[exact]]
    src_pts, dst_pts = fu[exact], out_uv[exact]
    fitted = 0
    if len(src_pts) >= 3:
        for i in np.nonzero(~exact)[0]:
            d = ((src_pts - fu[i]) ** 2).sum(1)
            near = np.argsort(d)[:8]
            A = np.hstack([src_pts[near], np.ones((len(near), 1), dtype=np.float32)])
            coef, *_ = np.linalg.lstsq(A, dst_pts[near], rcond=None)
            out_uv[i] = np.array([fu[i][0], fu[i][1], 1.0], dtype=np.float32) @ coef
            fitted += 1
    else:
        out_uv[~exact] = wu[nearest[~exact]]
    out = bytearray(m2)
    base = _md21(m2)
    n, o = struct.unpack_from("<II", out, base + 0x3C)
    for v, (u, w) in zip(fi.tolist(), out_uv.tolist()):
        struct.pack_into("<2f", out, base + o + v * 48 + 32, u, w)
    return bytes(out), int(exact.sum()), fitted


def client_skin(client: str, folder: str, sex: int) -> bytes | None:
    """The client's own body's first skin profile, without this tool's patch."""
    game_folder, stem = body_paths(folder, sex)
    return _client_file(client, f"{game_folder}\\{stem}00.skin")


def _client_file(client: str, name: str) -> bytes | None:
    from ..mpq import ClientData
    cd = ClientData(client)
    for label, src in cd.sources:
        if PATCH_NAME.lower() in label.lower():
            continue
        try:
            if isinstance(src, str):
                path = os.path.join(src, *name.split("\\"))
                if os.path.isfile(path):
                    with open(path, "rb") as fh:
                        return fh.read()
            else:
                data = src.read(name)
                if data:
                    return data
        except Exception:
            continue
    return None


def export_body(read, fdid: int, folder: str, sex: int, client: str | None = None):
    """BfA's body model ``fdid`` as the client's body of ``folder`` (ChrRaces ClientFileString),
    its skin's texture coordinates on the client's classic layout."""
    game_folder, stem = body_paths(folder, sex)
    ex = export_display(read, {"model": fdid, "t": [0, 0, 0, 0]}, stem, folder=game_folder)
    m2_path = f"{game_folder}\\{stem}.m2"
    skin = ex.files.get(f"{game_folder}\\{stem}00.skin")
    ref = client_body(client, folder, sex) if client else None
    if skin:
        hd = ex.files[m2_path]
        m2, moved = remap_skin_uvs(hd, skin)
        ex.notes.append(f"{moved} skin vertices moved from BfA's 1024x512 layout to the client's 512x512 one")
        ref_skin = client_skin(client, folder, sex) if ref else None
        same_mesh = False
        if ref and ref_skin:
            moved_m2, exact, fitted = transfer_face_uvs(hd, m2, skin, ref, ref_skin)
            # the client's body is WoD's (the one BfA refined) when most face vertices match: only
            # then is its face mapping, and are its attachment points, the right ones to take
            same_mesh = exact >= 0.3 * (exact + fitted) and exact > 50
            if same_mesh:
                m2 = moved_m2
                ex.notes.append(f"face mapped as the client's own body maps it: {exact} vertices matched, {fitted} fitted")
            else:
                ex.notes.append("the client's own body is another mesh (not WoD's): the face keeps the layout mapping "
                                "and the attachment points stay BfA's")
        ex.files[m2_path] = m2
        if not same_mesh:
            ref = None
    if ref:
        m2, ids = align_attachments(ex.files[m2_path], ref)
        ex.files[m2_path] = m2
        if ids:
            ex.notes.append(f"attachment point(s) {ids} moved to where the client's own body has them")
    return ex


BODIES_VERSION = 2                 # raised when the export changes: an install then builds the bodies again
CLASSIC_RACES = (1, 2, 3, 4, 5, 6, 7, 8, 10, 11)   # BfA ChrRaces ids of the races the 3.3.5 client plays


def export_all(bodies, client: str, say=lambda m: None) -> tuple[list, list[str]]:
    """Every classic race's BfA body, both sexes (``bodies``: character.Bodies over BfA's data).
    A body that can't be exported is left out (the client keeps its own) and named in the notes."""
    races = dict(bodies.table("ChrRaces"))
    exports, notes = [], []
    for rid in CLASSIC_RACES:
        r = races.get(rid)
        if not r:
            continue
        for sex in (0, 1):
            name = f"{r['ClientFileString']} {SEXES[sex].lower()}"
            try:
                say(f"exporting the BfA body of {name}")
                ex = export_body(bodies.src.read, bodies._model_fdid(r, sex), r["ClientFileString"], sex, client=client)
                if any("stayed external" in n for n in ex.notes):
                    # part of its skeleton's animation could not be folded in: those would freeze
                    notes.append(f"{name}: left out - some of its animations could not be carried, the client keeps its own body")
                    continue
                exports.append(ex)
            except Exception as e:
                notes.append(f"{name}: not exported ({e}) - the client keeps its own body")
    return exports, notes


def remove(client: str) -> bool:
    """Takes the bodies out (the client's own come back). True when there was a patch."""
    patch = os.path.join(client, "Data", PATCH_NAME)
    if not os.path.isfile(patch):
        return False
    try:
        os.remove(patch)
    except PermissionError:
        raise CreatureError(f"{PATCH_NAME} is in use - close World of Warcraft and install again")
    return True


def install(client: str, exports: list, say=lambda m: None) -> dict:
    """Writes the bodies into Data\\patch-I.MPQ (the previous one kept in Data\\patch-I.MPQ.bak)."""
    files: dict[str, bytes] = {}
    notes = []
    for ex in exports:
        files.update(ex.files)
        notes += [f"{ex.stem}: {n}" for n in ex.notes]
    patch = os.path.join(client, "Data", PATCH_NAME)
    if os.path.isfile(patch):
        shutil.copy2(patch, patch + ".bak")
    tmp = patch + ".part"
    write_archive(tmp, files)
    try:
        os.replace(tmp, patch)
    except PermissionError:
        os.remove(tmp)
        raise CreatureError(f"{PATCH_NAME} is in use - close World of Warcraft and install again")
    say(f"Data\\{PATCH_NAME}: {len(files)} files, {os.path.getsize(patch) / 1048576:.1f} MB")
    cd = ClientData(client)
    shadowed = sorted({s for s in (cd.shadowed_by(f"{ex.folder}\\{ex.stem}.m2") for ex in exports) if s})
    return {"ok": True, "patch": PATCH_NAME, "files": len(files), "notes": notes, "shadowed": shadowed,
            "time": time.strftime("%Y-%m-%d %H:%M")}
