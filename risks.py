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
import winreg
import zipfile
from array import array
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

import core

CASP = 0x034AEECB
SLIDER_TYPES = {0xC5F6763E, 0x0355E0A6, 0xB0118C15}  # SMOD (sim modifier), BOND (bone delta), DMAP
WATCHED = SLIDER_TYPES | {CASP}
GAME_FOLDER_RE = re.compile(r"^(Data|Delta|[EFGS]P\d+)$", re.I)
INDEX_CACHE = core.DATA_DIR / "game index.bin"
_COMP_DELETED = 0xFFE0


# ---------------------------------------------------------------- the game install

def game_exe(game_dir: Path) -> Path:
    return game_dir / "Game" / "Bin" / "TS4_x64.exe"


def game_dir_of(exe: Path) -> Path:
    """C:\\...\\The Sims 4\\Game\\Bin\\TS4_x64.exe -> C:\\...\\The Sims 4"""
    return exe.parents[2]


def find_game_dir() -> Path | None:
    candidates: list[Path] = []
    for key in (r"SOFTWARE\Maxis\The Sims 4", r"SOFTWARE\WOW6432Node\Maxis\The Sims 4"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                candidates.append(Path(winreg.QueryValueEx(k, "Install Dir")[0]))
        except OSError:
            pass
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
        candidates += [Path(base) / "EA Games" / "The Sims 4", Path(base) / "Origin Games" / "The Sims 4",
                       Path(base) / "Steam" / "steamapps" / "common" / "The Sims 4"]
    return next((c for c in candidates if game_exe(c).is_file()), None)


def last_update(game_dir: Path | None, sims_dir: Path | None) -> float | None:
    """When the game was last updated: the date of its exe, else of GameVersion.txt."""
    for p in ([game_exe(game_dir)] if game_dir else []) + ([sims_dir / "GameVersion.txt"] if sims_dir else []):
        try:
            return p.stat().st_mtime
        except OSError:
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


def game_index(game_dir: Path) -> frozenset[int]:
    """Keys of every CAS part and slider in the game's own packages, cached per game version."""
    exe = game_exe(game_dir)
    st = exe.stat()
    packs = ",".join(sorted(p.name for p in game_dir.iterdir() if p.is_dir() and GAME_FOLDER_RE.match(p.name)))
    stamp = f"2|{game_dir}|{st.st_size}|{int(st.st_mtime)}|{packs}".encode("utf-8")
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
    for top in game_dir.iterdir():
        if not (top.is_dir() and GAME_FOLDER_RE.match(top.name)):
            continue
        for pkg in top.rglob("*.package"):
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
        tmp = INDEX_CACHE.with_suffix(".tmp")
        tmp.write_bytes(stamp + b"\n" + a.tobytes())
        os.replace(tmp, INDEX_CACHE)
    except OSError:
        pass
    return frozenset(keys)


# ---------------------------------------------------------------- warnings for test items

def _date(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    return f"{d.day} {d:%b %Y}"


def _script_date(fh: BinaryIO) -> float:
    """Newest file date inside a .ts4script (it is a zip): when the creator built it."""
    try:
        with zipfile.ZipFile(fh) as zf:
            return max((core.zip_date(i) for i in zf.infolist() if not i.is_dir()), default=0.0)
    except (*core.ZIP_ERRORS, OSError):
        return 0.0


def check(item: core.ModItem, game_keys: frozenset[int] | None, updated: float | None) -> list[str]:
    """Plain-language warnings for one item. Reads its packages' indexes and script dates."""
    sliders = cas = old_scripts = 0
    try:
        for e in core.entries(item):
            name = e.name.lower()
            if name.endswith(".package") and game_keys:
                with e.open() as fh:
                    for t, g, i in package_keys(fh, e.size):
                        if _key_int(t, g, i) in game_keys:
                            if t in SLIDER_TYPES:
                                sliders += 1
                            else:
                                cas += 1
            elif name.endswith(".ts4script") and updated:
                with e.open() as fh:
                    built = _script_date(fh)
                if built and built < updated - 86400:
                    old_scripts += 1
    except (OSError, *core.ZIP_ERRORS):
        return []  # unreadable items get their own error when copied
    warnings = []
    if sliders:
        warnings.append("Changes the game\u2019s own sliders or body shapes. "
                        "Old files like this can give Sims odd heads or bodies.")
    if cas:
        warnings.append(f"Replaces {cas} of the game\u2019s own CAS items (a default replacement).")
    if old_scripts:
        if item.kind == "script":
            what = "Made"
        elif old_scripts == 1:
            what = "Has a script mod made"
        else:
            what = f"Has {old_scripts} script mods made"
        warnings.append(f"{what} before the last game update ({_date(updated)}). "
                        "If something breaks, look for a newer version.")
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
