"""Moving a modern (MD21) model in place: everything it draws or places, shifted by an offset.

A spell attaches a model at a point with an offset (Black Hole's burst 3 yards under the target);
3.3.5's kits hang a model at the point itself. So the export moves the model instead: its vertices,
bone pivots, attachment points, lights, particle emitters and ribbons, and its bounding boxes (the
model's, its collision box's and each animation's). Bone animation is relative to the pivot, so it
moves with it. The file keeps its size: only values inside the MD21 chunk change.

Record layouts (v272-274, offsets inside the MD20 body): vertices 48 bytes (position first); bones
0x58 (pivot at 0x4C); attachments 0x28 (position at 8); lights 0x9C (position at 4); ribbons 0xB0
(position at 8); particle emitters 0x1EC (position at 8); sequences 0x40 (bounds at 0x20).
"""

from __future__ import annotations

import struct

HEADER = {"sequences": 0x1C, "bones": 0x2C, "vertices": 0x3C, "attachments": 0xF0, "lights": 0x108,
          "ribbons": 0x120, "particles": 0x128, "collision_vertices": 0xE0}
RECORDS = {"vertices": (48, 0), "bones": (0x58, 0x4C), "attachments": (0x28, 8), "lights": (0x9C, 4),
           "ribbons": (0xB0, 8), "particles": (0x1EC, 8), "collision_vertices": (12, 0)}
BOUNDS = (0xA0, 0xBC)                          # bounding box, collision box: two C3Vectors each
SEQ_STRIDE, SEQ_BOUNDS = 0x40, 0x20


def _md21_span(m2: bytes) -> tuple[int, int] | None:
    pos = 0
    while pos + 8 <= len(m2):
        tag = m2[pos:pos + 4]
        size = struct.unpack_from("<I", m2, pos + 4)[0]
        if tag == b"MD21":
            return pos + 8, size
        pos += 8 + size
    return None


def translate(m2: bytes, offset: tuple[float, float, float]) -> bytes:
    """The model moved by ``offset`` (model units). Raises ValueError on a file it can't walk."""
    dx, dy, dz = (float(v) for v in offset)
    if not (dx or dy or dz):
        return m2
    span = _md21_span(m2)
    if span is None:
        raise ValueError("not a chunked (MD21) model")
    base, size = span
    out = bytearray(m2)
    end = base + size

    def shift(at: int) -> None:
        if at + 12 > end:
            raise ValueError(f"position at {at - base:#x} is past the model")
        x, y, z = struct.unpack_from("<3f", out, at)
        struct.pack_into("<3f", out, at, x + dx, y + dy, z + dz)

    for name, hdr in HEADER.items():
        if name == "sequences":
            continue
        count, off = struct.unpack_from("<II", out, base + hdr)
        stride, at = RECORDS[name]
        if count and off + count * stride > size:
            raise ValueError(f"{name}: {count} records at {off:#x} run past the model")
        for k in range(count):
            shift(base + off + k * stride + at)
    for b in BOUNDS:
        shift(base + b)
        shift(base + b + 12)
    count, off = struct.unpack_from("<II", out, base + HEADER["sequences"])
    if count and off + count * SEQ_STRIDE <= size:
        for k in range(count):
            shift(base + off + k * SEQ_STRIDE + SEQ_BOUNDS)
            shift(base + off + k * SEQ_STRIDE + SEQ_BOUNDS + 12)
    return bytes(out)
