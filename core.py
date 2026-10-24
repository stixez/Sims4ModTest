"""Folder swapping for Sims 4 Mod Test. No Qt in here, so it can be tested on its own.

A test works like this, for Mods and (when the test has tray files) for Tray:
  1. the chosen files are copied into a staging folder next to the live one,
  2. the live folder is renamed to its backup name,
  3. the staging folder is renamed to the live name.
Ending a test renames the live folder to a "finished" name, the backup back to
the live name, and sends the finished folder to the Recycle Bin (Trash). The Mods backup
existing is what "a test is running" means, so the app survives being closed or
crashing in the middle.

A broken-mod search uses the same swap, but each round's Mods folder is made of
hard links to half of the user's own mods (no copying, no extra disk space).
"""
from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
import zipfile
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Iterator

import psutil

import platforms
from platforms import GAME_PROCESSES, long_path, recycle


@dataclass(frozen=True)
class Slot:
    live: str
    backup: str
    staging: str
    finished: str


MODS = Slot("Mods", "Mods (your mods, set aside by Sims 4 Mod Test)",
            "Mods (Sims 4 Mod Test, preparing)", "Mods (test copies, Sims 4 Mod Test)")
TRAY = Slot("Tray", "Tray (your tray, set aside by Sims 4 Mod Test)",
            "Tray (Sims 4 Mod Test, preparing)", "Tray (test copies, Sims 4 Mod Test)")
SLOTS = (MODS, TRAY)

MOD_EXTENSIONS = {".package", ".ts4script"}
TRAY_EXTENSIONS = {".trayitem", ".householdbinary", ".hhi", ".sgi", ".blueprint", ".bpi", ".room", ".rmi"}
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
JUNK_DIRS = {"__macosx"}
CACHE_FILES = ["localthumbcache.package"]
MAX_ZIP_DEPTH = 3  # zips inside zips inside zips

DEFAULT_RESOURCE_CFG = (
    "Priority 500\n"
    "PackedFile *.package\n"
    "PackedFile */*.package\n"
    "PackedFile */*/*.package\n"
    "PackedFile */*/*/*.package\n"
    "PackedFile */*/*/*/*.package\n"
    "PackedFile */*/*/*/*/*.package\n"
)

DATA_DIR = platforms.data_dir()
STATE_PATH = DATA_DIR / "state.json"
SAVE_BACKUP_DIR = DATA_DIR / "save backup"
REMOVED_NAME = "Mods removed by Sims 4 Mod Test"

# What zipfile raises for damaged data, Deflate64 (big zips made by Windows) and passwords.
ZIP_ERRORS = (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error)


class TesterError(Exception):
    """An error with a message that can be shown to the user as is."""


# ---------------------------------------------------------------- Sims folder

def find_sims_dirs(documents: list[Path]) -> list[Path]:
    """Sims 4 user folders under <Documents>/Electronic Arts (the name is localised)."""
    found: list[Path] = []
    for docs in documents:
        ea = docs / "Electronic Arts"
        try:
            found += [d for d in ea.iterdir() if d.is_dir() and looks_like_sims_dir(d) and d not in found]
        except OSError:  # missing, denied, or an offline OneDrive folder
            continue
    # Prefer the English name, then whichever was played most recently.
    found.sort(key=lambda d: (d.name != "The Sims 4", -mtime(d / "Options.ini")))
    return found


def looks_like_sims_dir(path: Path) -> bool:
    if (path / MODS.backup).is_dir():
        return True
    user_data = (path / "Options.ini").is_file() or (path / "Mods").is_dir()
    # The Sims 3 folder also has Options.ini and Mods; these only exist for The Sims 4.
    sims4 = ((path / "Tray").is_dir() or (path / "GameVersion.txt").is_file()
             or (path / "localthumbcache.package").is_file())
    return user_data and sims4


def game_processes() -> list[psutil.Process]:
    found = []
    for proc in psutil.process_iter(["name"]):
        if (proc.info.get("name") or "").lower() in GAME_PROCESSES:
            found.append(proc)
    return found


def game_running() -> bool:
    return bool(game_processes())


# ---------------------------------------------------------------- mod items

@dataclass
class ModItem:
    path: str
    kind: str                 # "package", "script", "tray", "folder" or "zip"
    mod_files: int            # .package/.ts4script files it brings
    tray_files: int           # tray files it brings
    size: int                 # bytes
    tray_names: list[str] = field(default_factory=list)  # household/lot/room names
    tray_kinds: list[str] = field(default_factory=list)  # "household", "lot", "room" or "" per name
    files: list[str] = field(default_factory=list)       # kind "tray": every file of the group
    has_script: bool = False  # folders/zips: configs next to a script mod come along too
    warnings: list[str] = field(default_factory=list)    # filled in by risks.check

    @property
    def name(self) -> str:
        return Path(self.path).name

    @property
    def title(self) -> str:
        if self.kind == "tray" and self.tray_names:
            return ", ".join(self.tray_names)
        return self.name


@dataclass
class Entry:
    name: str                          # file name only, folders inside zips are dropped
    size: int
    open: Callable[[], BinaryIO]       # only valid until the next entry is taken
    date: float = 0.0                  # zip members: the date stored in the zip


def kind_of(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext in MOD_EXTENSIONS:
        return "mod"
    if ext in TRAY_EXTENSIONS:
        return "tray"
    return "other"


def _folder_entries(root: Path) -> Iterator[Entry]:
    for f in walk_files(Path(long_path(root))):
        yield Entry(f.name, _size(f), lambda f=f: open(f, "rb"))
        if f.suffix.lower() == ".zip":
            with open(f, "rb") as fh:
                yield from _zip_entries(fh, 2)


def _zip_entries(fh: BinaryIO, depth: int = 1) -> Iterator[Entry]:
    """Every file in a zip, and in zips inside it, in one pass without loading it into memory.

    A zip inside a folder or another zip that can't be read (damaged, password,
    Deflate64) is skipped, so the rest of the download still works.
    """
    try:
        zf = zipfile.ZipFile(fh)
    except ZIP_ERRORS:
        if depth > 1:
            return
        raise
    with zf:
        for info in _zip_members(zf):
            if depth > 1:
                try:
                    zf.open(info).close()  # fails right away for passwords and unknown packing
                except ZIP_ERRORS:
                    continue
            name = safe_name(Path(info.filename.replace("\\", "/")).name)
            yield Entry(name, info.file_size, lambda info=info: zf.open(info), zip_date(info))
            if name.lower().endswith(".zip") and depth < MAX_ZIP_DEPTH:
                with tempfile.TemporaryFile() as tmp:
                    try:
                        with zf.open(info) as member:
                            shutil.copyfileobj(member, tmp, 1024 * 1024)
                    except ZIP_ERRORS:
                        continue
                    tmp.seek(0)
                    yield from _zip_entries(tmp, depth + 1)


def _looks_like_bomb(info: zipfile.ZipInfo) -> bool:
    """A member that would unpack to something huge from almost nothing (a zip bomb)."""
    return info.file_size > (64 << 20) and info.file_size > 200 * max(info.compress_size, 1)


def zip_date(info: zipfile.ZipInfo) -> float:
    try:
        return time.mktime(info.date_time + (0, 0, -1))
    except (OverflowError, ValueError):
        return 0.0


def entries(item: ModItem) -> Iterator[Entry]:
    """Every file an item brings, for any kind of item."""
    if item.kind == "folder":
        yield from _folder_entries(Path(item.path))
    elif item.kind == "zip":
        with open(long_path(item.path), "rb") as fh:
            yield from _zip_entries(fh)
    else:
        for f in item.files or [item.path]:
            p = Path(f)
            yield Entry(p.name, _size(p), lambda p=p: open(long_path(p), "rb"))


def inspect_paths(paths: list[Path], sims_dir: Path | None) -> tuple[list[ModItem], list[str]]:
    """Turn picked or dropped paths into test items. Returns (items, problems to show)."""
    items: list[ModItem] = []
    problems: list[str] = []
    tray_by_folder: dict[Path, list[Path]] = {}
    for raw in paths:
        try:
            path = Path(os.path.abspath(raw))
            _refuse_live_folders(path, sims_dir)
            if os.path.isfile(long_path(path)) and path.suffix.lower() in TRAY_EXTENSIONS:
                tray_by_folder.setdefault(path.parent, []).append(path)
            else:
                items.append(_inspect_one(path))
        except TesterError as e:
            problems.append(str(e))
        except (OSError, *ZIP_ERRORS) as e:
            problems.append(f"\u201c{raw.name}\u201d could not be read: {reason(e)}.")
    for folder, picked in tray_by_folder.items():
        try:
            items.append(_tray_group(folder, picked))
        except OSError as e:
            problems.append(f"The tray files in \u201c{folder.name}\u201d could not be read: {reason(e)}.")
    return items, problems


def _refuse_live_folders(path: Path, sims_dir: Path | None) -> None:
    if sims_dir is None:
        return
    sims = Path(os.path.abspath(sims_dir))
    for slot in SLOTS:
        live = sims / slot.live
        if path == live or live.is_relative_to(path):
            raise TesterError(f"\u201c{path.name}\u201d is your whole {slot.live} folder. "
                              "Pick single items from it instead.")


def _inspect_one(path: Path) -> ModItem:
    if os.path.isdir(long_path(path)):
        return _inspect_container(ModItem(str(path), "folder", 0, 0, 0))
    if not os.path.isfile(long_path(path)):
        raise TesterError(f"\u201c{path.name}\u201d could not be found.")
    ext = path.suffix.lower()
    if ext == ".package":
        return ModItem(str(path), "package", 1, 0, _size(path))
    if ext == ".ts4script":
        return ModItem(str(path), "script", 1, 0, _size(path), has_script=True)
    if ext == ".zip":
        try:
            return _inspect_container(ModItem(str(path), "zip", 0, 0, _size(path)))
        except zipfile.BadZipFile:
            raise TesterError(f"\u201c{path.name}\u201d is damaged or not a real .zip file.")
        except (NotImplementedError, RuntimeError):
            raise TesterError(f"\u201c{path.name}\u201d is packed in a way Sims 4 Mod Test can\u2019t open, or has a "
                              "password. Unpack it in Windows first, then add what was inside.")
    if ext in {".rar", ".7z"}:
        raise TesterError(f"Unpack \u201c{path.name}\u201d first, then add what was inside. "
                          "Sims 4 Mod Test can only open .zip files.")
    raise TesterError(f"\u201c{path.name}\u201d is not a mod or tray file.")


def _inspect_container(item: ModItem) -> ModItem:
    for e in entries(item):
        kind = kind_of(e.name)
        if kind == "mod":
            item.mod_files += 1
            item.has_script |= e.name.lower().endswith(".ts4script")
        elif kind == "tray":
            item.tray_files += 1
            if e.name.lower().endswith(".trayitem"):
                with e.open() as fh:
                    name, tray_kind = tray_item_info(fh.read(1 << 20))  # the name is near the start
                item.tray_names.append(name or e.name)
                item.tray_kinds.append(tray_kind)
    if item.kind == "folder":
        item.size = sum(_size(f) for f in walk_files(Path(long_path(item.path))))
    if not item.mod_files and not item.tray_files:
        raise TesterError(f"There are no mods or tray files in \u201c{item.name}\u201d.")
    return item


def _tray_id(path: Path) -> str:
    """'0x00000001!0x0058175cd0eb001b.trayitem' -> '0x0058175cd0eb001b'."""
    return path.stem.split("!")[-1].lower()


def _tray_group(folder: Path, picked: list[Path]) -> ModItem:
    """The picked tray files plus the rest of each household, lot or room they belong to."""
    siblings = [folder / e.name for e in os.scandir(long_path(folder))
                if e.is_file() and Path(e.name).suffix.lower() in TRAY_EXTENSIONS]
    trayitems = [p for p in siblings if p.suffix.lower() == ".trayitem"]
    if len(trayitems) == 1:
        group = set(siblings)  # a download folder with one Sim or lot: take all of it
    else:
        ids = {_tray_id(p) for p in picked if p.suffix.lower() == ".trayitem"}
        group = set(picked) | {p for p in siblings if _tray_id(p) in ids}
    files = sorted(group, key=lambda p: (p.suffix.lower() != ".trayitem", p.name))
    infos = [(tray_item_info(_read(p)), p.name) for p in files if p.suffix.lower() == ".trayitem"]
    return ModItem(str(files[0]), "tray", 0, len(files), sum(_size(p) for p in files),
                   tray_names=[name or fname for (name, _), fname in infos],
                   tray_kinds=[kind for (_, kind), _ in infos], files=[str(p) for p in files])


_TRAY_KINDS = {1: "household", 2: "lot", 3: "room"}


def tray_item_info(data: bytes) -> tuple[str | None, str]:
    """(name, kind) of a .trayitem: fields 4 and 2 of the game's TrayMetadata message."""
    def varint(i: int) -> tuple[int, int]:
        result = shift = 0
        while True:
            b = msg[i]
            i += 1
            result |= (b & 0x7F) << shift
            shift += 7
            if b < 0x80:
                return result, i
    name, kind = None, ""
    try:
        length = int.from_bytes(data[4:8], "little")
        msg = data[8:8 + length]
        i = 0
        while i < len(msg) and (name is None or not kind):
            key, i = varint(i)
            wire, number = key & 7, key >> 3
            if wire == 0:
                value, i = varint(i)
                if number == 2:
                    kind = _TRAY_KINDS.get(value, "")
            elif wire == 1:
                i += 8
            elif wire == 5:
                i += 4
            elif wire == 2:
                n, i = varint(i)
                if number == 4:
                    name = msg[i:i + n].decode("utf-8").strip() or None
                i += n
            else:
                break
    except (IndexError, UnicodeDecodeError):
        pass
    return name, kind


# ---------------------------------------------------------------- file helpers

def _read(path: Path, limit: int = 1 << 20) -> bytes:
    with open(long_path(path), "rb") as fh:
        return fh.read(limit)


def _size(path: Path) -> int:
    try:
        return os.stat(long_path(path)).st_size
    except OSError:
        return 0


def mtime(path: Path) -> float:
    try:
        return os.stat(long_path(path)).st_mtime
    except OSError:
        return 0.0


def walk_files(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d.lower() not in JUNK_DIRS]
        for name in filenames:
            if name.lower() not in JUNK_NAMES:
                yield Path(dirpath) / name


def _zip_members(zf: zipfile.ZipFile) -> Iterator[zipfile.ZipInfo]:
    for info in zf.infolist():
        parts = Path(info.filename).parts
        if info.is_dir() or any(p.lower() in JUNK_DIRS for p in parts) or _looks_like_bomb(info):
            continue
        if Path(info.filename).name.lower() in JUNK_NAMES:
            continue
        yield info


_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_BAD_CHARS = set('<>:"/\\|?*') | {chr(c) for c in range(32)}


def safe_name(name: str) -> str:
    """A file name from a zip made safe to write: no folders, no ':' streams, no device names."""
    name = "".join("_" if c in _BAD_CHARS else c for c in name).rstrip(". ")
    if not name or name in (".", ".."):
        return "file"
    if name.split(".")[0].upper() in _RESERVED:
        return "_" + name
    return name


def _unique(folder: Path, name: str) -> Path:
    """folder/name, or folder/'stem (2).ext' etc. if that is taken."""
    target = folder / name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while os.path.exists(long_path(target)):
        target = folder / f"{stem} ({n}){suffix}"
        n += 1
    return target


def _write(src: Callable[[], BinaryIO], dest: Path) -> None:
    with src() as fin, open(long_path(dest), "wb") as fout:
        shutil.copyfileobj(fin, fout, 1024 * 1024)


def _rmtree(path: Path) -> None:
    shutil.rmtree(long_path(path), ignore_errors=True)


def _copy_item(item: ModItem, mods: Path, tray: Path) -> None:
    """Copy one item into the test Mods and Tray folders.

    Mods from folders and zips are flattened into Mods/<name>/ because the game
    only loads script mods at most one folder deep. Tray files always go straight
    into Tray, which the game doesn't search below the top level. Other files
    (configs, readmes) only come along when there is a script mod that may need them.
    """
    src = Path(item.path)
    if item.kind in ("package", "script"):
        shutil.copy2(long_path(src), long_path(_unique(mods, src.name)))
        return
    if item.kind == "tray":
        for f in item.files:
            dest = tray / Path(f).name
            if not os.path.exists(long_path(dest)):  # same file twice: keep one
                shutil.copy2(long_path(f), long_path(dest))
        return

    mod_dir: Path | None = None
    for e in entries(item):
        kind = kind_of(e.name)
        if kind == "tray":
            dest = tray / e.name
            if not os.path.exists(long_path(dest)):
                _write(e.open, dest)
        elif kind == "mod" or (item.has_script and not e.name.lower().endswith(".zip")):
            if mod_dir is None:
                mod_dir = _unique(mods, src.stem if item.kind == "zip" else src.name)
                os.mkdir(long_path(mod_dir))
            _write(e.open, _unique(mod_dir, e.name))


# ---------------------------------------------------------------- state

def in_test(sims_dir: Path) -> bool:
    return (sims_dir / MODS.backup).is_dir()


def tray_in_test(sims_dir: Path) -> bool:
    return (sims_dir / TRAY.backup).is_dir()


def load_state(sims_dir: Path) -> dict | None:
    """The running test or search, or None. Items come back as ModItem."""
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if Path(state.get("sims_dir", "")) != sims_dir:
            return None
        state["items"] = [ModItem(**i) for i in state.get("items", [])]
        return state
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _save_state(state: dict | None, required: bool = False) -> None:
    """Write state.json. For a test it's a convenience (the backup folders are the source of
    truth); a search can't go on without it, so there a failure raises."""
    try:
        if state is None:
            STATE_PATH.unlink(missing_ok=True)
        else:
            state = dict(state, items=[asdict(i) if isinstance(i, ModItem) else i
                                       for i in state.get("items", [])])
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(state), encoding="utf-8")
            os.replace(tmp, STATE_PATH)
    except OSError as e:
        if required:
            raise TesterError(f"Sims 4 Mod Test could not save its progress ({reason(e)}). Nothing was changed.")


_OLD_NAMES = {  # folder names used before the app was renamed to Sims 4 Mod Test
    "Mods (your mods, set aside by Mod Tester)": MODS.backup,
    "Tray (your tray, set aside by Mod Tester)": TRAY.backup,
    "Mods (Mod Tester, preparing)": MODS.staging,
    "Tray (Mod Tester, preparing)": TRAY.staging,
    "Mods (finished Mod Tester test)": MODS.finished,
    "Tray (finished Mod Tester test)": TRAY.finished,
    "Mods removed by Mod Tester": REMOVED_NAME,
}


def migrate_data_dir() -> None:
    """Move the old app's data folder (state of a running test, save backups) to the new name.
    Runs before anything else creates the new folder."""
    old_data = DATA_DIR.parent / "Mod Tester"
    if old_data.is_dir() and not DATA_DIR.exists():
        try:
            os.rename(old_data, DATA_DIR)
        except OSError:
            pass


def _migrate_old_names(sims_dir: Path) -> None:
    for old, new in _OLD_NAMES.items():
        if (sims_dir / old).is_dir() and not (sims_dir / new).exists():
            _rename(sims_dir / old, sims_dir / new)
    for slot in SLOTS:  # numbered leftovers: "Mods (finished Mod Tester test 2)"
        for old in sims_dir.glob(f"{slot.live} (finished Mod Tester test *)"):
            if old.is_dir():
                _rename(old, _finished_target(sims_dir, slot))
    migrate_data_dir()


def recover(sims_dir: Path) -> None:
    """Put things right after a swap was interrupted (app killed, power cut, locked folder).

    Whenever a backup exists but its live folder doesn't, the user's own folder goes back.
    """
    _migrate_old_names(sims_dir)
    for slot in SLOTS:
        live, backup, staging = sims_dir / slot.live, sims_dir / slot.backup, sims_dir / slot.staging
        if backup.is_dir() and not live.exists():
            _rename(backup, live)
        if staging.is_dir():
            _rmtree(staging)  # only ever holds copies or links
    # A Tray set aside without a running test can only be left over from a failed end.
    if tray_in_test(sims_dir) and not in_test(sims_dir):
        _swap_out(sims_dir, TRAY)
    for slot in SLOTS:
        if not (sims_dir / slot.backup).exists():
            for folder in finished_folders(sims_dir, slot):
                recycle(folder)


def finished_folders(sims_dir: Path, slot: Slot = MODS) -> list[Path]:
    """Test folders from earlier tests that are still there (the Recycle Bin refused them)."""
    stem = slot.finished[:-1]  # "Mods (finished Sims 4 Mod Test test" matches "... test)" and "... test 2)"
    return sorted(p for p in sims_dir.glob(glob_escape(stem) + "*)") if p.is_dir())


def glob_escape(text: str) -> str:
    return "".join(f"[{c}]" if c in "[]*?" else c for c in text)


# ---------------------------------------------------------------- swapping

def _locked(folder: str) -> TesterError:
    return TesterError(f"Windows would not let Sims 4 Mod Test rename the {folder} folder. A program is still "
                       "using a file in it, for example Sims 4 Studio or a folder window. Close it and try again.")


def _rename(src: Path, dst: Path) -> None:
    """os.rename, retried for a few seconds: antivirus and the search indexer briefly hold new files."""
    for attempt in range(8):
        try:
            os.rename(src, dst)
            return
        except OSError as e:
            if attempt == 7 or getattr(e, "winerror", None) not in (5, 32, 33):
                raise
            time.sleep(0.25 * (attempt + 1))


def _finished_target(sims: Path, slot: Slot) -> Path:
    target, n = sims / slot.finished, 2
    while target.exists():
        target = sims / f"{slot.finished[:-1]} {n})"
        n += 1
    return target


def _swap_in(sims: Path, slot: Slot) -> None:
    live, backup, staging = sims / slot.live, sims / slot.backup, sims / slot.staging
    had_live = live.exists()
    try:
        if had_live:
            _rename(live, backup)
        else:
            backup.mkdir()  # nothing to set aside: an empty backup still marks the swap
    except OSError:
        raise _locked(slot.live)
    try:
        _rename(staging, live)
    except OSError:
        try:
            if had_live:
                _rename(backup, live)
            else:
                backup.rmdir()
        except OSError:
            pass  # recover() puts the user's folder back
        raise _locked(slot.live)


def _swap_out(sims: Path, slot: Slot) -> Path | None:
    """Put the backup back. Returns the folder with the test copies, if there was one."""
    live, backup = sims / slot.live, sims / slot.backup
    moved_to = None
    if live.exists():
        target = _finished_target(sims, slot)
        try:
            _rename(live, target)
        except OSError:
            raise _locked(slot.live)
        moved_to = target
    try:
        _rename(backup, live)
    except OSError:
        if moved_to:
            try:
                _rename(moved_to, live)
            except OSError:
                pass  # live is missing and the backup is intact: recover() puts it back
        raise TesterError(f"Windows would not let Sims 4 Mod Test move your own {slot.live} folder back. "
                          f"A program is still using a file in \u201c{slot.backup}\u201d. Close it and try again.")
    return moved_to


def _swap_round(sims: Path) -> None:
    """Replace the current test Mods with the freshly built staging folder (search rounds)."""
    live, staging = sims / MODS.live, sims / MODS.staging
    old = _finished_target(sims, MODS)
    try:
        _rename(live, old)
    except OSError:
        _rmtree(staging)
        raise _locked("Mods")
    try:
        _rename(staging, live)
    except OSError:
        try:
            _rename(old, live)
        except OSError:
            pass
        _rmtree(staging)
        raise _locked("Mods")
    _remove_round(old)


def _begin(sims_dir: Path) -> None:
    if game_running():
        raise TesterError("Close The Sims 4 first.")
    recover(sims_dir)
    if in_test(sims_dir):
        raise TesterError("A test is already running.")


def _resource_cfg(source_mods: Path, staging: Path, link: bool = False) -> None:
    cfg = source_mods / "Resource.cfg"
    if cfg.is_file():
        (os.link if link else shutil.copy2)(long_path(cfg), long_path(staging / "Resource.cfg"))
    else:
        (staging / "Resource.cfg").write_text(DEFAULT_RESOURCE_CFG, encoding="ascii")


def start_test(sims_dir: Path, items: list[ModItem], clear_cache: bool,
               progress: Callable[[int, int], None] = lambda done, total: None) -> None:
    if not items:
        raise TesterError("Add at least one mod to test.")
    _begin(sims_dir)
    slots = [MODS] + ([TRAY] if any(i.tray_files for i in items) else [])

    stagings = [sims_dir / s.staging for s in slots]
    for staging in stagings:
        if staging.exists():
            raise TesterError(f"Delete the folder \u201c{staging.name}\u201d, then try again.")
    for staging in stagings:
        staging.mkdir()

    def cleanup() -> None:
        for staging in stagings:
            _rmtree(staging)

    total = sum(i.size for i in items) or 1
    done = 0
    mods_staging, tray_staging = sims_dir / MODS.staging, sims_dir / TRAY.staging
    try:
        _resource_cfg(sims_dir / "Mods", mods_staging)
        for item in items:
            try:
                _copy_item(item, mods_staging, tray_staging)
            except (OSError, *ZIP_ERRORS) as e:
                raise TesterError(f"Could not copy \u201c{item.title}\u201d: {reason(e)}. "
                                  "Nothing was changed.")
            done += item.size
            progress(min(done, total), total)
        saves = backup_saves(sims_dir)
    except BaseException:
        cleanup()
        raise

    swapped: list[Slot] = []
    try:
        for slot in slots:
            _swap_in(sims_dir, slot)
            swapped.append(slot)
    except TesterError:
        for slot in reversed(swapped):
            try:
                leftover = _swap_out(sims_dir, slot)
                if leftover:
                    _rmtree(leftover)  # copies made a moment ago
            except TesterError:
                pass
        cleanup()
        try:
            recover(sims_dir)
        except (OSError, TesterError):
            pass  # the app runs recover() again on its next start
        raise

    _save_state({"mode": "test", "sims_dir": str(sims_dir), "started": time.time(),
                 "items": items, "saves": saves})
    if clear_cache:
        clear_game_cache(sims_dir)


@dataclass
class EndResult:
    leftovers: list[Path]                 # test folders the Recycle Bin refused
    changed_saves: list[dict]             # saves the game wrote during a test (all not put back yet)
    removed: Path | None = None           # where a found broken mod was moved to
    move_failed: str | None = None        # why the found mod could not be moved out


def end_test(sims_dir: Path, clear_cache: bool, remove_found: bool = False) -> EndResult:
    """Put the user's own folders back (after a test or a search)."""
    if not in_test(sims_dir):
        raise TesterError("No test is running.")
    if game_running():
        raise TesterError("Close The Sims 4 before restoring your mods.")
    state = load_state(sims_dir) or {}
    search = state.get("mode") == "search"
    leftovers = []
    # Tray first: the Mods backup is what marks the test as running, so it goes last.
    for slot in (TRAY, MODS):
        if (sims_dir / slot.backup).is_dir():
            folder = _swap_out(sims_dir, slot)
            if folder:
                leftovers.append(folder)

    # From here on the user's folders are back; nothing below may stop the clean-up.
    removed = move_failed = None
    if search and remove_found and state.get("found") is not None:
        try:
            removed = _move_out(sims_dir, state["units"][state["found"]])
        except OSError as e:
            move_failed = reason(e)
    _add_pending_saves(sims_dir, changed_saves(sims_dir, state.get("saves", [])))
    _save_state(None)
    if clear_cache:
        clear_game_cache(sims_dir)
    for folder in leftovers:
        try:
            if search:
                _remove_round(folder)
            else:
                recycle(folder)
        except OSError:
            pass
    return EndResult([f for f in leftovers if f.exists()], pending_saves(sims_dir), removed, move_failed)


# ---------------------------------------------------------------- broken-mod search
#
# Round 0 has every mod switched off: if the problem is still there, it isn't a mod and the
# search stops instead of blaming an innocent one. After that each round switches on half
# of the mods that could still be the broken one.

def mod_units(mods: Path) -> list[list[str]]:
    """The user's mods as units that are switched on and off together, as paths relative to Mods.

    A folder that holds a script mod stays together (scripts usually come with packages
    and configs they need); everything else is one unit per mod file.
    """
    units: list[list[str]] = []
    root = Path(long_path(mods))
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        here = Path(dirpath)
        rel = here.relative_to(root)
        if rel != Path(".") and any(f.lower().endswith(".ts4script") for f in filenames):
            files = sorted(str(p.relative_to(root)) for p in walk_files(here))
            if files:
                units.append(files)
            dirnames[:] = []
            continue
        for name in sorted(filenames):
            if kind_of(name) == "mod":
                units.append([str(rel / name) if rel != Path(".") else name])
    return units


def unit_label(unit: list[str]) -> tuple[str, str]:
    """(title, where) for showing a unit: a file name and its folder, or a script mod folder."""
    if len(unit) == 1:
        p = Path(unit[0])
        return p.name, ("in Mods" if str(p.parent) == "." else f"in {Path('Mods') / p.parent}")
    return Path(os.path.commonpath(unit)).name, f"Script mod folder with {len(unit)} files"


def rounds_left(candidates: int) -> int:
    return max(0, math.ceil(math.log2(candidates))) if candidates > 1 else 0


def start_search(sims_dir: Path, clear_cache: bool) -> None:
    _begin(sims_dir)
    mods = sims_dir / "Mods"
    if not mods.is_dir():
        raise TesterError("There is no Mods folder to search.")
    units = mod_units(mods)
    if len(units) < 2:
        raise TesterError("There are not enough mods in your Mods folder to search through.")
    staging = sims_dir / MODS.staging
    if staging.exists():
        raise TesterError(f"Delete the folder “{staging.name}”, then try again.")
    try:
        _build_round(mods, staging, units, [])
        saves = backup_saves(sims_dir)
        _save_state({"mode": "search", "sims_dir": str(sims_dir), "started": time.time(), "round": 0,
                     "units": units, "candidates": list(range(len(units))), "testing": [],
                     "found": None, "not_mods": False, "saves": saves}, required=True)
    except BaseException:
        _rmtree(staging)
        raise
    try:
        _swap_in(sims_dir, MODS)
    except TesterError:
        _save_state(None)
        _rmtree(staging)
        recover(sims_dir)
        raise
    if clear_cache:
        clear_game_cache(sims_dir)


def answer_search(sims_dir: Path, still_broken: bool, clear_cache: bool) -> dict:
    """Record the answer for this round and set up the next one (or the result)."""
    if game_running():
        raise TesterError("Close The Sims 4 first.")
    state = load_state(sims_dir)
    if not state or state.get("mode") != "search" or not in_test(sims_dir):
        raise TesterError("No search is running.")
    if state["found"] is not None or state["not_mods"]:
        return state
    units = state["units"]
    if not _round_intact(sims_dir / "Mods", units, state["testing"]):
        raise TesterError("The Mods folder changed during the search, so Sims 4 Mod Test lost track of this round. "
                          "Restore your mods and start the search again.")
    new = dict(state)
    if state["round"] == 0:
        if still_broken:  # with every mod off: not a mod
            new.update(not_mods=True)
            _save_state(new, required=True)
            return new
        candidates = state["candidates"]
    else:
        testing = set(state["testing"])
        candidates = [c for c in state["candidates"] if (c in testing) == still_broken]
    if len(candidates) == 1:
        new.update(candidates=candidates, found=candidates[0])
        _save_state(new, required=True)
        return new

    testing_next = candidates[:len(candidates) // 2]
    staging = sims_dir / MODS.staging
    _rmtree(staging)
    try:
        _build_round(sims_dir / MODS.backup, staging, units, testing_next)
        new.update(candidates=candidates, testing=testing_next, round=state["round"] + 1, started=time.time())
        _save_state(new, required=True)  # before the swap, so the record never lags behind Mods
    except BaseException:
        _rmtree(staging)
        raise
    try:
        _swap_round(sims_dir)
    except TesterError:
        _save_state(state)
        raise
    if clear_cache:
        clear_game_cache(sims_dir)
    return new


def _round_intact(mods: Path, units: list[list[str]], testing: list[int]) -> bool:
    """Does the live Mods folder still hold this round's mods, and no other half's?

    Checked by path, so a script mod rewriting its own config file doesn't count as a change.
    """
    expected = {os.path.normcase(rel) for i in testing for rel in units[i]}
    root = Path(long_path(mods))
    if not all(os.path.exists(long_path(mods / rel)) for i in testing for rel in units[i]):
        return False
    for f in walk_files(root):
        rel = os.path.normcase(str(f.relative_to(root)))
        try:
            if rel not in expected and kind_of(f.name) == "mod" and os.stat(f).st_nlink > 1:
                return False  # a link from another round: the record and the folder disagree
        except OSError:
            pass
    return True


def _remove_round(folder: Path) -> None:
    """Delete a search round's Mods folder: its hard links go, the user's own files are elsewhere.

    Anything that isn't a link (a file the game or the user put there during the
    round) goes to the Recycle Bin with the folder instead of being deleted.
    """
    root = Path(long_path(folder))
    others = False
    for f in walk_files(root):
        try:
            if os.stat(f).st_nlink > 1 or (f.name == "Resource.cfg" and f.parent == root):
                os.unlink(f)
            else:
                others = True
        except OSError:
            others = True
    if others:
        recycle(folder)
    else:
        _rmtree(folder)


def _build_round(source: Path, staging: Path, units: list[list[str]], testing: list[int]) -> None:
    """A Mods folder of hard links to the chosen units: instant and takes no disk space."""
    staging.mkdir()
    try:
        _resource_cfg(source, staging, link=True)
        made: set[Path] = set()
        for i in testing:
            for rel in units[i]:
                dest = staging / rel
                if dest.parent not in made:
                    os.makedirs(long_path(dest.parent), exist_ok=True)
                    made.add(dest.parent)
                os.link(long_path(source / rel), long_path(dest))
    except OSError as e:
        if getattr(e, "winerror", None) in (1, 17, 50) or e.errno in (errno.EXDEV, errno.EPERM, errno.ENOTSUP,
                                                                       errno.EMLINK):
            raise TesterError("Sims 4 Mod Test can\u2019t search on this drive, because it can\u2019t make hard "
                              "links there. The search needs your Sims 4 folder on a normal drive "
                              "(NTFS on Windows, APFS on a Mac, ext4 or Btrfs on Linux).")
        if isinstance(e, FileNotFoundError):
            raise TesterError("A mod file disappeared while Sims 4 Mod Test was setting up the round. "
                              "Your mods were not changed. Try again.")
        raise


def _move_out(sims_dir: Path, unit: list[str]) -> Path:
    """Move a found broken mod out of Mods into a folder next to it, keeping its subfolders."""
    mods, dest_root = sims_dir / "Mods", sims_dir / REMOVED_NAME
    for rel in unit:
        src, dest = mods / rel, dest_root / rel
        if not os.path.exists(long_path(src)):
            continue
        os.makedirs(long_path(dest.parent), exist_ok=True)
        os.replace(long_path(src), long_path(_unique(dest.parent, dest.name)))
    return dest_root


# ---------------------------------------------------------------- saves
#
# The main save files are copied before every test, into a folder per Sims 4 folder. If the
# game saves over one during a test, it stays "pending" (and its backup is kept, even through
# later tests) until the user puts it back or says to keep the new one.

PENDING_PATH = DATA_DIR / "pending saves.json"


def _backup_dir(sims_dir: Path) -> Path:
    key = hashlib.sha1(os.path.normcase(os.path.abspath(sims_dir)).encode("utf-8")).hexdigest()[:12]
    return SAVE_BACKUP_DIR / key


def _save_files(sims_dir: Path) -> list[Path]:
    saves = sims_dir / "saves"
    if not saves.is_dir():
        return []
    return sorted(p for p in saves.glob("Slot_*.save") if p.is_file())


def _all_pending() -> list[dict]:
    try:
        return json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _same_dir(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def pending_saves(sims_dir: Path) -> list[dict]:
    """Saves of this Sims 4 folder that the game overwrote during a test and that weren't put back."""
    return [p for p in _all_pending() if _same_dir(p.get("sims_dir", ""), sims_dir)]


def _write_pending(pending: list[dict]) -> None:
    try:
        if pending:
            PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
            PENDING_PATH.write_text(json.dumps(pending), encoding="utf-8")
        else:
            PENDING_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def _set_pending(sims_dir: Path, mine: list[dict]) -> None:
    others = [p for p in _all_pending() if not _same_dir(p.get("sims_dir", ""), sims_dir)]
    _write_pending(others + [dict(p, sims_dir=str(sims_dir)) for p in mine])


def _add_pending_saves(sims_dir: Path, changed: list[dict]) -> None:
    mine = {p["name"]: p for p in pending_saves(sims_dir)}
    for c in changed:
        mine[c["name"]] = c
    _set_pending(sims_dir, list(mine.values()))


def keep_new_saves(sims_dir: Path, names: list[str]) -> None:
    """The user keeps the versions saved during the test: forget the offer (and its backup)."""
    _set_pending(sims_dir, [p for p in pending_saves(sims_dir) if p["name"] not in names])
    for n in names:
        (_backup_dir(sims_dir) / n).unlink(missing_ok=True)


def backup_saves(sims_dir: Path) -> list[dict]:
    """Copy the main save files (not the game's .ver copies) before a test.

    Backups of saves still waiting to be put back are kept: they are the good versions.
    """
    keep = {p["name"] for p in pending_saves(sims_dir)}
    folder = _backup_dir(sims_dir)
    folder.mkdir(parents=True, exist_ok=True)
    current = _save_files(sims_dir)
    names = {p.name for p in current}
    for old in folder.iterdir():
        if old.name not in keep and old.name not in names:
            old.unlink(missing_ok=True)
    info = []
    for p in current:
        if p.name not in keep or not (folder / p.name).is_file():
            try:
                shutil.copy2(p, folder / p.name)
            except OSError as e:
                raise TesterError(f"Could not back up your save “{p.stem}”: {reason(e)}. "
                                  "Nothing was changed.")
        st = p.stat()
        info.append({"name": p.name, "size": st.st_size, "mtime": st.st_mtime})
    return info


def changed_saves(sims_dir: Path, before: list[dict]) -> list[dict]:
    """Saves that were overwritten during the test, with the time the game saved them."""
    changed = []
    for s in before:
        p = sims_dir / "saves" / s["name"]
        try:
            st = p.stat()
        except OSError:
            continue  # deleted in the game's menu: nothing we should bring back unasked
        if (st.st_size, round(st.st_mtime)) != (s["size"], round(s["mtime"])):
            if (_backup_dir(sims_dir) / s["name"]).is_file():
                changed.append({"name": s["name"], "saved": st.st_mtime})
    return changed


def restore_saves(sims_dir: Path, names: list[str]) -> None:
    """Put back saves from before the test. The newer versions go to the Recycle Bin."""
    if game_running():
        raise TesterError("Close The Sims 4 before putting saves back.")
    for name in names:
        src, dest = _backup_dir(sims_dir) / name, sims_dir / "saves" / name
        if not src.is_file():
            raise TesterError(f"The backup of “{Path(name).stem}” is gone.")
        tmp = dest.with_name(dest.name + ".modtester")
        shutil.copy2(src, tmp)
        if dest.exists():
            if not recycle(dest) or dest.exists():
                tmp.unlink(missing_ok=True)
                raise TesterError(f"“{dest.stem}” could not go to the {platforms.trash_name()}, so it was left as it "
                                  "is. Close the game and try again.")
        os.replace(tmp, dest)
        _set_pending(sims_dir, [p for p in pending_saves(sims_dir) if p["name"] != name])


# ---------------------------------------------------------------- misc

def clear_game_cache(sims_dir: Path) -> None:
    for name in CACHE_FILES:
        path = sims_dir / name
        if path.exists():
            recycle(path)


def new_error_reports(sims_dir: Path, since: float) -> list[Path]:
    """lastException files the game wrote after `since`, newest first."""
    reports = []
    for pattern in ("lastException*.txt", "lastUIException*.txt"):
        reports += [p for p in sims_dir.glob(pattern) if mtime(p) > since]
    return sorted(reports, key=mtime, reverse=True)


def reason(e: Exception) -> str:
    if isinstance(e, (zipfile.BadZipFile, EOFError, zlib.error)):
        return "the .zip file is damaged"
    if isinstance(e, (NotImplementedError, RuntimeError, zipfile.LargeZipFile)):
        return "it is packed in a way Sims 4 Mod Test can\u2019t open, or has a password"
    if isinstance(e, OSError) and e.errno == 28:
        return "the disk is full"
    if isinstance(e, PermissionError):
        return "access was denied"
    if isinstance(e, FileNotFoundError):
        return "a file is missing"
    return getattr(e, "strerror", None) or str(e)
