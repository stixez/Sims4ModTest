"""Warnings about test items, finding the game, and hints from the game's error reports.

Override check: a package that contains a CAS part or a slider (SMOD, BOND, DMAP) with
the same resource key as one in the game's own packages replaces the game's version.
The game's keys come from the index tables of its packages (read once, then cached).

Package index layout (DBPF 2.1): 96-byte header with the entry
count at 36, legacy index position at 40, index size at 44 and index position at 64. The
index starts with a flags word; bits 0/1/2 mark type/group/instance-high as constant and
stored once. Each entry then holds the other fields of type, group, instance-high,
instance-low, offset, file size, memory size; bit 31 of the file size means a uint16
compression id and a uint16 "committed" word follow.
"""
from __future__ import annotations

import os
import re
import struct
import threading
import zipfile
from array import array
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Callable

import core
import platforms

CASP = 0x034AEECB
SLIDER_TYPES = {0xC5F6763E, 0x0355E0A6, 0xB0118C15}  # SMOD (sim modifier), BOND (bone delta), DMAP
WATCHED = SLIDER_TYPES | {CASP}
GAME_FOLDER_RE = re.compile(r"^(Data|Delta|[EFGS]P\d+)$", re.I)
INDEX_CACHE = core.DATA_DIR / "game index.bin"
INDEX_FORMAT = 3  # bump when what the cache holds changes: older caches are then rebuilt
_COMP_DELETED = 0xFFE0


# ---------------------------------------------------------------- the game install

def last_update(game_dir: Path | None, sims_dir: Path | None) -> float | None:
    """When the game was last updated: the date of its program, else of GameVersion.txt."""
    candidates = [platforms.game_version_file(game_dir)] if game_dir else []
    candidates += [sims_dir / "GameVersion.txt"] if sims_dir else []
    for p in candidates:
        try:
            return p.stat().st_mtime
        except (OSError, AttributeError):
            continue
    return None


# ---------------------------------------------------------------- package index

def package_keys(fh: BinaryIO, size: int) -> list[tuple[int, int, int]]:
    """(type, group, instance) of the watched resource types in a package. [] if unreadable."""
    head = fh.read(96)
    if len(head) < 96 or head[:4] != b"DBPF" or struct.unpack_from("<I", head, 4)[0] != 2:
        return []
    count, pos_legacy, isize = struct.unpack_from("<III", head, 36)
    pos = struct.unpack_from("<I", head, 64)[0] or pos_legacy
    if not count or isize < 4 or isize > (256 << 20) or pos < 96 or pos + isize > size:
        return []
    fh.seek(pos)
    idx = fh.read(isize)
    try:
        return _index_keys(idx, count)
    except struct.error:
        return []


def _index_keys(idx: bytes, count: int) -> list[tuple[int, int, int]]:
    flags = struct.unpack_from("<I", idx, 0)[0]
    p = 4
    const: list[int | None] = [None, None, None]
    for bit in range(3):
        if flags & (1 << bit):
            const[bit] = struct.unpack_from("<I", idx, p)[0]
            p += 4
    if const[0] is not None and const[0] not in WATCHED:
        return []
    variable = [bit for bit in range(3) if const[bit] is None]
    nv = len(variable)

    # Fast path: every entry has the compression field (true for nearly all packages),
    # so entries are fixed-size and unpack in one go. Game packages have millions.
    fmt = struct.Struct("<" + "I" * nv + "IIIIHH")
    end = p + fmt.size * count
    if end <= len(idx):
        out = []
        for r in fmt.iter_unpack(memoryview(idx)[p:end]):
            if not r[nv + 2] & 0x80000000:
                break  # an entry without the compression field: use the slow path
            tgh = list(const)
            for i, bit in enumerate(variable):
                tgh[bit] = r[i]
            if tgh[0] in WATCHED and r[nv + 4] != _COMP_DELETED:
                out.append((tgh[0], tgh[1], (tgh[2] << 32) | r[nv]))
        else:
            return out

    out = []
    for _ in range(count):
        tgh = []
        for bit in range(3):
            if const[bit] is None:
                tgh.append(struct.unpack_from("<I", idx, p)[0])
                p += 4
            else:
                tgh.append(const[bit])
        inst_lo, _off, file_size, _mem = struct.unpack_from("<IIII", idx, p)
        p += 16
        comp = 0
        if file_size & 0x80000000:
            comp = struct.unpack_from("<H", idx, p)[0]
            p += 4
        if tgh[0] in WATCHED and comp != _COMP_DELETED:
            out.append((tgh[0], tgh[1], (tgh[2] << 32) | inst_lo))
    return out


def _key_int(t: int, g: int, i: int) -> int:
    return (t << 96) | (g << 64) | i


def game_index(game_dir: Path, stop: Callable[[], bool] = lambda: False) -> frozenset[int] | None:
    """Keys of every CAS part and slider in the game's own packages, cached per game version.
    None if `stop` said to give up (the app is closing); nothing is cached then."""
    root = platforms.game_content_root(game_dir)
    if root is None:
        return frozenset()
    version = platforms.game_version_file(game_dir)
    try:
        st = version.stat() if version else root.stat()
        packs = ",".join(sorted(p.name for p in root.iterdir() if p.is_dir() and GAME_FOLDER_RE.match(p.name)))
    except OSError as e:
        core.log_error(f"reading the game folder {game_dir}: {e}")
        return frozenset()
    stamp = f"{INDEX_FORMAT}|{game_dir}|{st.st_size}|{int(st.st_mtime)}|{packs}".encode("utf-8")
    try:
        data = INDEX_CACHE.read_bytes()
        head, _, body = data.partition(b"\n")
        if head == stamp:
            a = array("Q")
            a.frombytes(body)
            return frozenset((a[n] << 64) | a[n + 1] for n in range(0, len(a), 2))
    except (OSError, ValueError):
        pass

    keys: set[int] = set()
    for top in root.iterdir():
        if not (top.is_dir() and GAME_FOLDER_RE.match(top.name)):
            continue
        for pkg in top.rglob("*.package"):
            if stop():
                return None
            try:
                with open(pkg, "rb") as fh:
                    for t, g, i in package_keys(fh, os.fstat(fh.fileno()).st_size):
                        keys.add(_key_int(t, g, i))
            except OSError:
                continue
    a = array("Q")
    for k in keys:
        a.append(k >> 64)
        a.append(k & 0xFFFFFFFFFFFFFFFF)
    try:
        INDEX_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = INDEX_CACHE.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")  # two builds can overlap
        try:
            tmp.write_bytes(stamp + b"\n" + a.tobytes())
            os.replace(tmp, INDEX_CACHE)
        finally:
            tmp.unlink(missing_ok=True)  # a partial file from a failed write (e.g. a full disk)
    except OSError:
        pass
    return frozenset(keys)


# ---------------------------------------------------------------- warnings for test items

def _date(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    return f"{d.day} {d:%b %Y}"


def script_built(path: Path) -> float:
    """Newest file date inside a .ts4script (it is a zip): when the creator built it. 0 if unknown."""
    try:
        with open(core.long_path(path), "rb") as fh, zipfile.ZipFile(fh) as zf:
            return max((core.zip_date(i) for i in zf.infolist() if not i.is_dir()), default=0.0)
    except (*core.ZIP_ERRORS, OSError):
        return 0.0


def outdated_note(script: Path, updated: float | None) -> str:
    """'It was made before the last game update (\u2026).' for a script an error report names, else ''.

    Only said next to an error report: plenty of older script mods still work, so on its own
    the age isn't worth a warning.
    """
    built = script_built(script)
    if updated and built and built < updated - 86400:
        return f" It was made before the last game update ({_date(updated)}), so look for a newer version."
    return ""


def check(item: core.ModItem, game_keys: frozenset[int] | None) -> list[str]:
    """Plain-language warnings for one item, from its packages' indexes."""
    sliders = cas = 0
    if not game_keys:
        return []
    keys = getattr(item, "package_keys", None)  # read while inspecting: no second pass over the files
    if keys is None:
        keys = []
        try:
            for e in core.entries(item):
                if e.name.lower().endswith(".package"):
                    with e.open() as fh:
                        keys += package_keys(fh, e.size)
        except (OSError, *core.ZIP_ERRORS):
            return []  # unreadable items get their own error when copied
    for t, g, i in keys:
        if _key_int(t, g, i) in game_keys:
            if t in SLIDER_TYPES:
                sliders += 1
            else:
                cas += 1
    warnings = []
    if sliders:
        warnings.append("Changes the game\u2019s own sliders or body shapes. "
                        "Old files like this can give Sims odd heads or bodies.")
    if cas:
        warnings.append(f"Replaces {cas} of the game\u2019s own CAS items (a default replacement).")
    return warnings


# ---------------------------------------------------------------- error reports

_SCRIPT_RE = re.compile(r"[\\/]([^\\/:*?\"<>|\r\n]+?\.ts4script)", re.I)


def report_suspects(report: Path, names: list[str]) -> list[str]:
    """Mods an error report mentions: script files in its tracebacks, plus any of `names`."""
    try:
        with open(report, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read(4 * 1024 * 1024)
    except OSError:
        return []
    found: list[str] = []
    for m in _SCRIPT_RE.finditer(text):
        name = m.group(1).strip()
        if name.lower() not in (f.lower() for f in found):
            found.append(name)
    lower = text.lower()
    for n in names:
        if len(n) >= 6 and n.lower() in lower and n.lower() not in (f.lower() for f in found):
            found.append(n)
    return found[:3]
