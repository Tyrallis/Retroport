"""Retail runtime physics (.phys) for the models the workbench ports: creatures, mounts, previews.

Retail moves hair, cloth, tails, chains and plumes with its physics engine; each such model carries
its .phys inline (a PFDC chunk) or names it (PFID). Equip Plus runs that engine live in the client
(``Mods\\wxl.equip-plus``) for every model with a row in a physics table, and the preview runs the
same engine in the browser.

The tables are written by Equip Plus's own ``tools/physics_table.py``. Like the kit and Equip Plus's
other tools it is run as a program, never imported: this module finds each model's .phys itself,
hands the bytes to ``physics_job.py`` (a small runner beside this file, started with the tools'
Python) and reads back the table or the parsed rows.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import tempfile

from . import kit as K

CREATURE_TABLE = "DBFilesClient\\WXLCreaturePhysics.phy2"
SPELL_TABLE = "DBFilesClient\\WXLSpellPhysics.phy2"
JOB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "physics_job.py")


class PhysicsError(Exception):
    pass


def phys_bytes(model: bytes, read) -> bytes | None:
    """A chunked model's .phys: its inline PFDC, else the file its PFID names (read(fdid) -> bytes).
    None for a model without physics."""
    if model[:4] == b"MD20":
        return None
    pos, pfid = 0, 0
    while pos + 8 <= len(model):
        tag = model[pos:pos + 4]
        size = struct.unpack_from("<I", model, pos + 4)[0]
        if tag == b"PFDC":
            return model[pos + 8:pos + 8 + size]
        if tag == b"PFID" and size >= 4:
            pfid = struct.unpack_from("<I", model, pos + 8)[0]
        pos += 8 + size
    if not pfid:
        return None
    try:
        return read(pfid)
    except Exception:
        return None


def _run(tools: str, job: dict) -> dict:
    if not tools or not os.path.isfile(os.path.join(tools, "physics_table.py")):
        raise PhysicsError("Equip Plus's tools are not downloaded (Settings → Downloads)")
    with tempfile.TemporaryDirectory(prefix="retroport-phys-") as tmp:
        for i, item in enumerate(job["items"]):
            path = os.path.join(tmp, f"{i}.phys")
            with open(path, "wb") as fh:
                fh.write(item.pop("phys"))
            item["path"] = path
        job["out"] = os.path.join(tmp, "out")
        job_path = os.path.join(tmp, "job.json")
        with open(job_path, "w", encoding="utf-8") as fh:
            json.dump(job, fh)
        r = subprocess.run([K.python_exe(), "-I", JOB, tools, job_path], capture_output=True, text=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=300)
        if r.returncode != 0:
            raise PhysicsError((r.stderr or r.stdout or "physics_job failed").strip().splitlines()[-1])
        with open(job["out"] + ".json", encoding="utf-8") as fh:
            result = json.load(fh)
        if os.path.isfile(job["out"] + ".phy2"):
            with open(job["out"] + ".phy2", "rb") as fh:
                result["table"] = fh.read()
        return result


def table(tools: str, models: list[tuple]) -> tuple[bytes | None, list[str]]:
    """A PHY2 table for (keys, .phys bytes[, shift]) entries - every key a path the client may report
    for the model; shift, the offset a moved copy's file was moved by. (None, notes) when no model
    had physics that could be read."""
    items = [{"keys": m[0], "phys": m[1], "shift": list(m[2]) if len(m) > 2 and m[2] else None}
             for m in models if m[1]]
    if not items:
        return None, []
    res = _run(tools, {"mode": "table", "items": items})
    return (res.get("table") if res.get("rows") else None), res.get("notes", [])


def parsed(tools: str, phys: bytes) -> dict:
    """One .phys as the engine's table reader wants it ({bodies, shapes, joints, hulls}), and the
    one-row PHY2 table for it (keyed "model.m2"), hex-free: the table as a list of bytes is large, so
    it is returned base64 in "table64"."""
    import base64
    res = _run(tools, {"mode": "parse", "items": [{"keys": ["model.m2"], "phys": phys}]})
    out = {"rows": res.get("rows", 0), "notes": res.get("notes", [])}
    if res.get("table"):
        out["table64"] = base64.b64encode(res["table"]).decode("ascii")
    out["model"] = res.get("model")
    return out


def preview_row(wb, fdid: int) -> dict:
    """The preview's physics for model ``fdid`` (from the retail source): {"table64", "bodies"} or
    {"none": True}. Kept on disk: a model's physics never changes within a build."""
    cache_dir = os.path.join(wb.settings.data_dir, "cache", "physics")
    path = os.path.join(cache_dir, f"{fdid}.json")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        pass
    _key, src = wb.creatures.source()
    phys = phys_bytes(src.read(fdid), src.read)
    out: dict = {"none": True}
    if phys:
        res = parsed(wb.kit.cfg.tools, phys)
        if res.get("table64"):
            out = {"table64": res["table64"], "bodies": len((res.get("model") or {}).get("bodies") or [])}
    os.makedirs(cache_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    return out
