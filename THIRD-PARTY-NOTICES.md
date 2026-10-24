# Third-party notices

Sims 4 Mod Test itself is under the MIT license (see `LICENSE`). The downloads also contain the components
below, each under its own license. The license texts are in the `licenses` folder that comes with the app.

| Component | Version | License | Source |
| --- | --- | --- | --- |
| Qt for Python (PySide6, Essentials) and Shiboken6 | 6.12.0 | LGPL-3.0 (also offered under GPL-2.0 / GPL-3.0) | https://code.qt.io/cgit/pyside/pyside-setup.git |
| Qt libraries included with PySide6 | 6.12.0 | LGPL-3.0 | https://download.qt.io/official_releases/qt/ |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| Send2Trash (macOS and Linux) | 2.1.0 | BSD-3-Clause | https://github.com/arsenetar/send2trash |
| certifi (macOS and Linux) | 2026.10.23 | MPL-2.0 | https://github.com/certifi/python-certifi |
| PyInstaller bootloader | 6.22.3 | GPL-2.0 with the bootloader exception | https://github.com/pyinstaller/pyinstaller |
| Python | 3.12 | PSF License | https://www.python.org/downloads/source/ |
| Microsoft Visual C++ runtime (Windows) | | Microsoft redistributable | Part of Microsoft Visual C++ |

## Qt and PySide6 (LGPL-3.0)

Qt and PySide6 are used unmodified, as separate libraries. They sit as their own files next to the app (in the
`_internal` folder on Windows and Linux, inside the app bundle on macOS), so you can replace them with your own
build of the same version. The complete source of Sims 4 Mod Test is at https://github.com/stixez/Sims4ModTest,
and `packaging/build.py` there shows how the app is put together. The LGPL-3.0 text is in
`licenses/LGPL-3.0.txt`, and it builds on the GPL-3.0 in `licenses/GPL-3.0.txt`.

## certifi (MPL-2.0)

certifi is used unmodified. Its source is at the address above, and the MPL-2.0 text is in `licenses/MPL-2.0.txt`.

## Trademarks

Sims 4 Mod Test is a fan-made tool. It is not made by, affiliated with or endorsed by Electronic Arts or Maxis.
The Sims is a trademark of Electronic Arts Inc.
