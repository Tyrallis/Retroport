"""Runs Equip Plus's tools/physics_table.py for the workbench (physics.py), as a program of its own.

    python physics_job.py <equip-plus tools folder> <job.json>

job: {"mode": "table" | "parse", "out": <path stem>, "items": [{"keys": [...], "path": <.phys file>}]}
Writes <out>.phy2 (the table) and <out>.json ({"rows", "notes", "model"}).
"""
import json
import os
import sys


def upgrade(blob: bytes) -> bytes:
    """Older .phys files (the Avenging Wrath wings') keep their shoulder joints as SHOJ: SHJ2's
    record (0x7C bytes) without its last two fields, the spring's rate and damping. They become SHJ2
    with both 0 (no spring), which is what physics_table.py reads."""
    import struct
    out, o, changed = bytearray(), 0, False
    while o + 8 <= len(blob):
        tag, n = blob[o:o + 4], struct.unpack_from("<I", blob, o + 4)[0]
        body = blob[o + 8:o + 8 + n]
        if tag[::-1] == b"SHOJ" and n % 0x74 == 0:
            body = b"".join(body[k:k + 0x74] + bytes(8) for k in range(0, n, 0x74))
            tag, changed = b"SHJ2"[::-1], True
        out += tag + struct.pack("<I", len(body)) + body
        o += 8 + n
    return bytes(out) if changed else blob


def main():
    tools, job_path = sys.argv[1], sys.argv[2]
    sys.path.insert(0, tools)
    import physics_table as PT   # noqa: E402  (Equip Plus's own module, from its tools folder)

    with open(job_path, encoding="utf-8") as fh:
        job = json.load(fh)
    rows, notes, model = {}, [], None
    for item in job["items"]:
        with open(item["path"], "rb") as fh:
            blob = upgrade(fh.read())
        try:
            p = PT.parse_phys(blob)
        except Exception as e:
            notes.append(f"{item['keys'][0]}: physics not readable ({e})")
            continue
        if not p["bodies"]:
            continue
        if model is None and job["mode"] == "parse":
            model = p
        for key in item["keys"]:
            rows[PT.norm_key(key)] = PT.encode_row(PT.norm_key(key), p, tuple(item.get("shift") or (0.0, 0.0, 0.0)))
    if rows:
        with open(job["out"] + ".phy2", "wb") as fh:
            fh.write(PT.write_table(rows))
    with open(job["out"] + ".json", "w", encoding="utf-8") as fh:
        json.dump({"rows": len(rows), "notes": notes, "model": model}, fh)


if __name__ == "__main__":
    main()
