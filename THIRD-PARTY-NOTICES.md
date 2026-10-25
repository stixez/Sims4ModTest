# Third-party notices

Sims 4 Mod Test itself is under the MIT license (see `LICENSE`). The downloads also contain the components
below, each under its own license. The license texts are in the `licenses` folder that comes with the app.

| Component | Version | License | Source |
| --- | --- | --- | --- |
| Qt for Python (PySide6, Essentials) and Shiboken6 | 6.12.0 | LGPL-3.0 (also offered under GPL-2.0 / GPL-3.0) | https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.12.0 |
| Qt libraries included with PySide6 | 6.12.0 | LGPL-3.0 | https://download.qt.io/archive/qt/6.12/6.12.0/single/ |
| psutil | 7.2.2 | BSD-3-Clause | https://github.com/giampaolo/psutil |
| Send2Trash (macOS and Linux) | 2.1.0 | BSD-3-Clause | https://github.com/arsenetar/send2trash |
| certifi (macOS and Linux) | 2026.10.23 | MPL-2.0 | https://github.com/certifi/python-certifi |
| PyInstaller bootloader | 6.22.3 | GPL-2.0 with the bootloader exception | https://github.com/pyinstaller/pyinstaller |
| Python | 3.12 | PSF License | https://www.python.org/downloads/source/ |
| libmpdec (part of Python's `decimal` module) | 2.5.1 | BSD-2-Clause | https://www.bytereef.org/mpdecimal/ |
| Microsoft Visual C++ runtime (Windows) | | Microsoft redistributable | Part of Microsoft Visual C++ |

Python brings its own copies of OpenSSL, libffi, bzip2, xz and zlib (on Linux, these come from the system
libraries listed below). The licenses of OpenSSL, libffi and bzip2 are in `licenses/Python-LICENSE.txt`; xz is in
the public domain, and zlib's license asks for no notice. libmpdec's license is in
`licenses/mpdecimal-LICENSE.txt`.

## Qt and PySide6 (LGPL-3.0)

Qt and PySide6 are Copyright (C) The Qt Company Ltd. and other contributors. They are used unmodified, as
separate libraries. They sit as their own files next to the app (in the `_internal` folder on Windows and Linux,
inside the app bundle on macOS), so you can replace them with your own build of the same version. The complete
source of Sims 4 Mod Test is at https://github.com/stixez/Sims4ModTest, and `packaging/build.py` there shows how
the app is put together. The LGPL-3.0 text is in `licenses/LGPL-3.0.txt`, and it builds on the GPL-3.0 in
`licenses/GPL-3.0.txt`.

## Code inside Qt

The Qt libraries contain code from other projects, each under its own permissive license: among them FreeType,
HarfBuzz, libpng, zlib, PCRE2, md4c, double-conversion, Unicode ICU (Linux), and libjpeg, libtiff and libwebp
(macOS only; the Windows and Linux downloads leave those image plugins out). The full list, with each license
text, is at https://doc.qt.io/qt-6/licenses-used-in-qt.html.

- Portions of this software are copyright © The FreeType Project (https://freetype.org). All rights reserved.
- This software is based in part on the work of the Independent JPEG Group.

## Linux: system libraries

The Linux download includes unmodified libraries from Ubuntu 22.04 that Qt and Python need to run (for example
glib, D-Bus, fontconfig, FreeType, the X11 and xcb libraries, and OpenSSL). The folder
`licenses/linux-system-libraries` in that download has the copyright file of each one's Ubuntu package and, in
`packages.txt`, the exact package and version, so its source can be fetched from Ubuntu
(`apt-get source <package>=<version>`, or https://launchpad.net/ubuntu/+source/<package>). Libraries under the
LGPL (such as glib) can be replaced with your own build in the same way as Qt.

## certifi (MPL-2.0)

certifi is used unmodified. Its source is at the address above, and the MPL-2.0 text is in `licenses/MPL-2.0.txt`.

## Trademarks

Sims 4 Mod Test is a fan-made tool. It is not made by, affiliated with or endorsed by Electronic Arts or Maxis.
The Sims is a trademark of Electronic Arts Inc.
