"""Everything that differs between Windows, macOS and Linux: where things are, the trash,
long paths, and starting the game.

Linux means The Sims 4 through Steam with Proton: the game's user folder then sits inside
the Wine prefix of Steam app 1222670. Detection is best effort; the user can pick folders.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Sims 4 Mod Test"
SIMS4_STEAM_APP_ID = "1222670"
WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"

# What the running game is called: TS4_x64.exe on Windows and under Proton, an app on macOS.
GAME_PROCESSES = {"ts4_x64.exe", "ts4.exe", "ts4_dx9_x64.exe", "ts4_x64_fpb.exe", "the sims 4"}


def data_dir() -> Path:
    """Where the app keeps its state, save backups and caches."""
    if WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    elif MACOS:
        base = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / APP_NAME


# ---------------------------------------------------------------- the Sims 4 user folder

def _steam_roots(home: Path) -> list[Path]:
    return [home / ".local" / "share" / "Steam", home / ".steam" / "steam",
            home / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam"]


def documents_folders(qt_documents: Path | None = None) -> list[Path]:
    """Folders that may hold "Electronic Arts\\The Sims 4"."""
    home = Path.home()
    found = [qt_documents] if qt_documents else []
    if WINDOWS:
        try:
            import winreg
            key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:  # follows a OneDrive move
                found.append(Path(os.path.expandvars(winreg.QueryValueEx(k, "Personal")[0])))
        except OSError:
            pass
        found += [home / "Documents", home / "OneDrive" / "Documents"]
    elif MACOS:
        found.append(home / "Documents")
    else:
        found += [root / "steamapps" / "compatdata" / SIMS4_STEAM_APP_ID / "pfx" / "drive_c" / "users"
                  / "steamuser" / "Documents" for root in _steam_roots(home)]
        found.append(home / "Documents")
    unique: list[Path] = []
    for f in found:
        if f not in unique:
            unique.append(f)
    return unique


# ---------------------------------------------------------------- the game install

def game_dir_candidates() -> list[Path]:
    home = Path.home()
    if WINDOWS:
        found: list[Path] = []
        try:
            import winreg
            for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Maxis\The Sims 4",
                                        0, winreg.KEY_READ | view) as k:
                        found.append(Path(winreg.QueryValueEx(k, "Install Dir")[0]))
                except OSError:
                    pass
        except ImportError:
            pass
        for env in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(env)
            if base:
                found += [Path(base) / "EA Games" / "The Sims 4", Path(base) / "Origin Games" / "The Sims 4",
                          Path(base) / "Steam" / "steamapps" / "common" / "The Sims 4"]
        return found
    if MACOS:
        return [Path("/Applications/The Sims 4.app"), home / "Applications" / "The Sims 4.app"]
    return [root / "steamapps" / "common" / "The Sims 4" for root in _steam_roots(home)]


def game_content_root(game_dir: Path) -> Path | None:
    """The folder that holds the game's Data\\Client: the install folder, or one inside the
    macOS app bundle."""
    for root in (game_dir, game_dir / "Contents", game_dir / "Contents" / "Resources"):
        try:
            if (root / "Data" / "Client").is_dir():
                return root
        except OSError:
            return None
    return None


def find_game_dir() -> Path | None:
    return next((d for d in game_dir_candidates() if game_content_root(d)), None)


def game_dir_from_process(exe: str) -> Path | None:
    """...\\The Sims 4\\Game\\Bin\\TS4_x64.exe -> ...\\The Sims 4 (Windows; Proton shows Wine's binary)."""
    p = Path(exe)
    if p.name.lower() == "ts4_x64.exe" and len(p.parents) > 2:
        return p.parents[2]
    if MACOS and ".app" in exe:
        return Path(exe[:exe.index(".app") + 4])
    return None


def game_version_file(game_dir: Path) -> Path | None:
    """A file whose date changes when the game updates."""
    if WINDOWS or not MACOS:
        exe = game_dir / "Game" / "Bin" / "TS4_x64.exe"
        if exe.is_file():
            return exe
    root = game_content_root(game_dir)
    return root / "Data" / "Client" if root else None


def launch_game(game_dir: Path | None) -> bool:
    """Start The Sims 4. Returns False if it could not be started."""
    from PySide6.QtCore import QProcess, QUrl
    from PySide6.QtGui import QDesktopServices

    def detached(program: str, args: list[str], cwd: str = "") -> bool:
        result = QProcess.startDetached(program, args, cwd)
        return bool(result[0] if isinstance(result, tuple) else result)

    if MACOS:
        return game_dir is not None and detached("open", [str(game_dir)])
    if not WINDOWS:  # Steam starts it with the right Proton version
        return QDesktopServices.openUrl(QUrl(f"steam://rungameid/{SIMS4_STEAM_APP_ID}"))
    if game_dir is None:
        return False
    exe = game_dir / "Game" / "Bin" / "TS4_x64.exe"
    return exe.is_file() and detached(str(exe), [], str(exe.parent))


# ---------------------------------------------------------------- files

_LONG_PREFIX = "\\\\?\\"


def long_path(path: Path | str) -> str:
    """A path the OS accepts even past 260 characters (Windows; long CC names are common)."""
    s = os.path.abspath(str(path)) if not str(path).startswith(_LONG_PREFIX) else str(path)
    if not WINDOWS or s.startswith(_LONG_PREFIX):
        return s
    if s.startswith("\\\\"):  # network share: \\server\share -> \\?\UNC\server\share
        return _LONG_PREFIX + "UNC\\" + s[2:]
    return _LONG_PREFIX + s


def recycle(path: Path) -> bool:
    """Move a file or folder to the Recycle Bin / Trash. Returns False (and leaves it) if it can't."""
    full = os.path.abspath(path)
    if WINDOWS:
        return _recycle_windows(full)
    try:
        from send2trash import send2trash
        send2trash(full)
    except Exception:
        return False
    return not os.path.lexists(full)


if WINDOWS:
    import ctypes
    from ctypes import wintypes

    class _SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    class _SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("i64Size", ctypes.c_int64), ("i64NumItems", ctypes.c_int64)]


def _has_recycle_bin(path: str) -> bool:
    """Network shares and some removable drives have no Recycle Bin: deleting there is for good."""
    drive = os.path.splitdrive(path)[0]
    if not drive or drive.startswith("\\\\"):
        return False
    info = _SHQUERYRBINFO(cbSize=ctypes.sizeof(_SHQUERYRBINFO))
    return ctypes.windll.shell32.SHQueryRecycleBinW(drive + "\\", ctypes.byref(info)) == 0


def _recycle_windows(full: str) -> bool:
    """If the Recycle Bin is switched off or the item is too big for it, Windows asks first
    instead of deleting it for good (FOF_WANTNUKEWARNING)."""
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 3, 0x4, 0x10, 0x40, 0x400
    FOF_WANTNUKEWARNING = 0x4000
    if not _has_recycle_bin(full):
        return False
    op = _SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=full + "\0",
                          fFlags=FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
                          | FOF_WANTNUKEWARNING)
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return result == 0 and not op.fAnyOperationsAborted and not os.path.exists(full)


def trash_name() -> str:
    return "Recycle Bin" if WINDOWS else "Trash"
