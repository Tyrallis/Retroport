"""Retail sounds in the 3.3.5 client: a retail SoundKit (its files, volume and range) as a
SoundEntries row, its files (Ogg Vorbis, which the client's FMOD plays) in the patch.

Spells (patch-S) and creatures (patch-R) both add SoundEntries rows, and the client reads the
table from the highest patch that has it - patch-S. So each tool numbers in a range of its own,
spells build on the table below them (creature rows included), and a creature install puts its
rows into patch-S's copy too (``merge_into``)."""

from __future__ import annotations

import os
import threading

from .. import dbc as D

SOUND_FIELDS = 30                    # 3.3.5 SoundEntries: id, type, name, file[10], freq[10], dir, volume,
                                     # flags, min distance, cutoff, EAX, advanced
SPELL_RANGE = (300000, 400000)
CREATURE_RANGE = (200000, 300000)
TABLE = "DBFilesClient\\SoundEntries.dbc"

_lock = threading.Lock()
_kits: dict[str, tuple] = {}         # build -> (kit rows, kit entries)
_paths: dict[str, dict] = {}         # listfile -> {fdid: path} of its sound files


def _tables(src) -> tuple[dict, dict]:
    with _lock:
        if src.build not in _kits:
            kits = {i: (int(r.get("SoundType") or 0), float(r.get("VolumeFloat") or 1.0),
                        float(r.get("MinDistance") or 8.0), float(r.get("DistanceCutoff") or 45.0))
                    for i, r in src.table("SoundKit")}
            entries: dict[int, list] = {}
            for _i, r in src.table("SoundKitEntry"):
                if r.get("PlayerConditionID"):
                    continue                    # a variant for some players only
                entries.setdefault(r["SoundKitID"], []).append((r["FileDataID"], int(r.get("Frequency") or 1)))
            _kits[src.build] = (kits, entries)
        return _kits[src.build]


def _sound_paths(listfile: str) -> dict[int, str]:
    with _lock:
        if listfile not in _paths:
            out = {}
            if listfile and os.path.isfile(listfile):
                with open(listfile, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        low = line.rstrip().lower()
                        if not (low.endswith(".ogg") or low.endswith(".wav") or low.endswith(".mp3")):
                            continue
                        left, _, right = line.partition(";")
                        if left.isdigit():
                            out[int(left)] = right.strip()
            _paths[listfile] = out
        return _paths[listfile]


def _ext(data: bytes) -> str:
    if data[:4] == b"OggS":
        return ".ogg"
    if data[:4] == b"RIFF":
        return ".wav"
    return ".mp3"


class SoundPort:
    """Retail SoundKits as SoundEntries rows of ``table`` (3.3.5's), numbered in ``span``; the
    files they name collect in ``files`` (game path -> bytes)."""

    def __init__(self, src, listfile: str, table: D.DBCFile, span: tuple[int, int], exists=lambda p: False):
        if table.field_count != SOUND_FIELDS:
            raise ValueError(f"SoundEntries.dbc has {table.field_count} fields, not 3.3.5's {SOUND_FIELDS}")
        self.src, self.listfile, self.table, self.span, self.exists = src, listfile, table, span, exists
        lo, hi = span
        # this tool's own rows from an earlier install go: they are made again
        table.records = [r for r in table.records if not lo <= r[0] < hi]
        self.next = lo
        self.files: dict[str, bytes] = {}
        self.made: dict[int, int] = {}
        self.missing: list[str] = []

    def kit(self, kit_id: int) -> int:
        """The SoundEntries id playing retail SoundKit ``kit_id`` (0 when it has no files)."""
        if not kit_id:
            return 0
        if kit_id in self.made:
            return self.made[kit_id]
        kits, entries = _tables(self.src)
        files = entries.get(kit_id, [])[:10]
        info = kits.get(kit_id)
        if not files or info is None:
            self.made[kit_id] = 0
            return 0
        paths = _sound_paths(self.listfile)
        names, freqs, folder = [], [], ""
        for fdid, freq in files:
            path = paths.get(fdid, "").replace("/", "\\")
            try:
                data = self.src.read(fdid)
            except Exception as e:
                self.missing.append(f"sound {fdid}: {e}")
                continue
            if not data:
                continue
            if not path:
                path = f"Sound\\Retroport\\{fdid}{_ext(data)}"
            d, _, name = path.rpartition("\\")
            if folder and d.lower() != folder.lower():
                # one row has one folder: a file from another goes to a copy beside the first
                d, path = folder, f"{folder}\\{name}"
            folder = folder or d
            if not self.exists(path):
                self.files[path] = data
            names.append(name)
            freqs.append(max(1, freq))
        if not names:
            self.made[kit_id] = 0
            return 0
        while self.table.find_by_id(self.next) is not None:
            self.next += 1
        if self.next >= self.span[1]:
            raise ValueError("no SoundEntries ids left in this tool's range")
        sid = self.next
        self.next += 1
        t = self.table
        F = D.float_to_u32
        stype, volume, mind, cutoff = info
        row = [sid, stype, t.add_string(f"Retroport_{kit_id}")]
        row += [t.add_string(n) for n in names] + [0] * (10 - len(names))
        row += freqs + [0] * (10 - len(freqs))
        row += [t.add_string(folder), F(max(0.05, min(volume, 1.0))), 0, F(mind), F(cutoff), 0, 0]
        t.add_record(row)
        self.made[kit_id] = sid
        return sid


def merge_into(patch_path: str, ours: D.DBCFile, span: tuple[int, int], say=lambda m: None) -> bool:
    """Put our rows (``span``) into the SoundEntries.dbc a higher patch holds, its other rows kept:
    else that patch's copy hides them from the client. False when it holds none."""
    from ..mpq import MPQ, add_files
    if not os.path.isfile(patch_path):
        return False
    a = MPQ(patch_path)
    try:
        data = a.read(TABLE)
    finally:
        a.close()
    if not data:
        return False
    theirs = D.DBCFile.from_bytes(data, "SoundEntries.dbc")
    lo, hi = span
    theirs.records = [r for r in theirs.records if not lo <= r[0] < hi]
    for r in ours.records:
        if lo <= r[0] < hi:
            row = list(r)
            for k in (2, *range(3, 13), 23):              # name, files, folder: strings move tables
                row[k] = theirs.add_string(ours.get_string(r[k])) if r[k] else 0
            theirs.add_record(row)
    add_files(patch_path, {TABLE: theirs.to_bytes()})
    say(f"{os.path.basename(patch_path)}: its SoundEntries.dbc has the creatures' sounds too")
    return True
