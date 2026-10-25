"""Build Sims 4 Mod Test and its download for this system.

    python packaging/build.py

Windows: dist/Sims-4-Mod-Test-<version>-setup.exe (Inno Setup 6, with ISCC.exe on PATH, in its
         default folder or in $ISCC) and dist/Sims-4-Mod-Test-<version>-windows-portable.zip
macOS:   dist/Sims-4-Mod-Test-<version>-macos.zip (the .app)
Linux:   dist/Sims-4-Mod-Test-<version>-linux-x86_64.tar.gz
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from version import __version__  # noqa: E402

NAME = "Sims 4 Mod Test"
FILE = f"Sims-4-Mod-Test-{__version__}"
DIST = ROOT / "dist"
# Qt modules the app doesn't use; leaving them out keeps the download small.
EXCLUDE = ["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtQml", "PySide6.QtQuick",
           "PySide6.QtMultimedia", "PySide6.QtNetwork", "PySide6.QtPdf", "PySide6.QtSql", "PySide6.QtTest",
           "PySide6.QtDesigner", "tkinter"]
# Qt image plugins for formats the app never opens (its own images are SVG and PNG, which don't need these).
UNUSED_IMAGE_FORMATS = {"qgif", "qicns", "qjpeg", "qtga", "qtiff", "qwbmp", "qwebp"}


def version_file(path: Path) -> Path:
    """Windows file properties (version, product name) for the .exe."""
    nums = (__version__.split(".") + ["0"] * 4)[:4]
    tup = ", ".join(str(int(n)) if n.isdigit() else "0" for n in nums)
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tup}), prodvers=({tup})),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'stixez'),
    StringStruct('FileDescription', '{NAME}'),
    StringStruct('FileVersion', '{__version__}'),
    StringStruct('InternalName', '{NAME}'),
    StringStruct('LegalCopyright', 'Copyright (c) 2026 stixez. MIT License'),
    StringStruct('OriginalFilename', '{NAME}.exe'),
    StringStruct('ProductName', '{NAME}'),
    StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])]
)
""", encoding="utf-8")
    return path


def build_app() -> None:
    import PyInstaller.__main__

    work = ROOT / "build"
    work.mkdir(exist_ok=True)
    args = [str(ROOT / "app.py"), "--name", NAME, "--windowed", "--noconfirm", "--clean",
            "--distpath", str(DIST), "--workpath", str(work / "pyinstaller"), "--specpath", str(work),
            "--paths", str(ROOT)]
    # Our license, the third-party notices and their license texts go into every download.
    sep = ";" if sys.platform == "win32" else ":"
    for name in ("LICENSE", "THIRD-PARTY-NOTICES.md"):
        args += ["--add-data", f"{ROOT / name}{sep}."]
    args += ["--add-data", f"{ROOT / 'licenses'}{sep}licenses"]
    if sys.platform == "win32":
        args += ["--icon", str(ROOT / "assets" / "icon.ico"),
                 "--version-file", str(version_file(work / "version_info.txt"))]
    elif sys.platform == "darwin":
        args += ["--icon", str(ROOT / "assets" / "icon-1024.png"),  # PyInstaller makes the .icns (Pillow)
                 "--osx-bundle-identifier", "io.github.stixez.sims4modtest"]
    for module in EXCLUDE:
        args += ["--exclude-module", module]
    PyInstaller.__main__.run(args)


def drop_unused_plugins() -> None:
    """Less to download and to credit. Not on macOS: changing the .app after PyInstaller signed it
    would break its signature."""
    if sys.platform == "darwin":
        return
    for plugin in (DIST / NAME / "_internal").glob("PySide6/**/imageformats/*"):
        if plugin.stem.removeprefix("lib") in UNUSED_IMAGE_FORMATS:
            plugin.unlink()


def collect_linux_notices() -> None:
    """The Linux download carries system libraries from the build machine (Ubuntu). Copy each one's
    copyright file and write down its package and version, so its exact source can be fetched."""
    internal = DIST / NAME / "_internal"
    out = internal / "licenses" / "linux-system-libraries"
    out.mkdir(parents=True, exist_ok=True)
    packages: dict[str, list[str]] = {}
    for lib in sorted(internal.glob("*.so*")):
        found = subprocess.run(["dpkg-query", "-S", f"*/{lib.name}"], capture_output=True, text=True)
        for line in found.stdout.splitlines():
            owners, _, path = line.partition(": ")
            if path.endswith(f"/x86_64-linux-gnu/{lib.name}") and not line.startswith("diversion"):
                packages.setdefault(owners.split(",")[0].strip(), []).append(lib.name)
                break
        # not found: it came with PySide6 or Python, which THIRD-PARTY-NOTICES.md covers
    rows = []
    for package, libs in sorted(packages.items()):
        name = package.split(":")[0]
        copyright_file = Path("/usr/share/doc") / name / "copyright"
        if not copyright_file.is_file():
            raise SystemExit(f"No copyright file for {package} ({', '.join(libs)}) at {copyright_file}")
        shutil.copyfile(copyright_file, out / f"{name}.txt")
        info = subprocess.run(["dpkg-query", "-W", "-f", "${Version}\t${source:Package}", package],
                              capture_output=True, text=True, check=True).stdout
        rows.append(f"{name}\t{info}\t{' '.join(libs)}")
    (out / "packages.txt").write_text(
        "Ubuntu packages whose libraries are in this download, unmodified.\n"
        "package\tversion\tsource package\tlibraries\n" + "\n".join(rows) + "\n", encoding="utf-8")


def find_iscc() -> Path | None:
    candidates = [os.environ.get("ISCC"), shutil.which("ISCC")]
    for base in (os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if base:
            candidates += [str(Path(base) / "Programs" / "Inno Setup 6" / "ISCC.exe"),
                           str(Path(base) / "Inno Setup 6" / "ISCC.exe")]
    return next((Path(c) for c in candidates if c and Path(c).is_file()), None)


def package() -> list[Path]:
    if sys.platform == "win32":
        iscc = find_iscc()
        if iscc is None:
            raise SystemExit("Inno Setup 6 not found. Install it (winget install JRSoftware.InnoSetup) "
                             "or set ISCC to ISCC.exe's path.")
        subprocess.run([str(iscc), f"/DAppVersion={__version__}", str(ROOT / "packaging" / "Sims4ModTest.iss")],
                       check=True, cwd=ROOT / "packaging")
        portable = shutil.make_archive(str(DIST / f"{FILE}-windows-portable"), "zip", DIST, NAME)
        return [DIST / f"{FILE}-setup.exe", Path(portable)]
    if sys.platform == "darwin":
        out = DIST / f"{FILE}-macos.zip"
        # ditto keeps the app bundle's symlinks and permissions, which a plain zip would lose
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(DIST / f"{NAME}.app"), str(out)], check=True)
        return [out]
    out = DIST / f"{FILE}-linux-x86_64.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(DIST / NAME, arcname=NAME)
    return [out]


def main() -> int:
    build_app()
    drop_unused_plugins()
    if sys.platform.startswith("linux"):
        collect_linux_notices()
    for path in package():
        print(f"Built {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
