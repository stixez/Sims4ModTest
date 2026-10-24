# Sims 4 Mod Test

Try Sims 4 mods on their own, find the mod that breaks your game, and put everything back with one click.
For Windows, macOS and Linux.

<a href="https://buymeacoffee.com/stixe"><img src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?logo=buymeacoffee&logoColor=black" alt="Buy Me a Coffee"></a>

<img src="docs/test-new-mods.png" width="420" alt="Testing new mods"> <img src="docs/find-a-broken-mod.png" width="420" alt="Finding a broken mod">

## Download

From [Releases](../../releases/latest):

- **Windows:** `Sims-4-Mod-Test-…-setup.exe`. There's also a portable zip if you'd rather not install.
- **macOS** (Apple silicon): `Sims-4-Mod-Test-…-macos.zip`. Unzip it and move the app to Applications. The app
  isn't signed by Apple, so the first time, right-click it and choose **Open**.
- **Linux** (Steam with Proton): `Sims-4-Mod-Test-…-linux-x86_64.tar.gz`. Unpack it and run `Sims 4 Mod Test`
  inside.

The app tells you when a new version is out.

## Test new mods

1. Drag in what you want to try: packages, script mods, tray files, folders or `.zip` downloads.
2. Press **Start test**. Your own Mods (and Tray, if the test has Sims or lots) are set aside, and a fresh folder
   with only the test files takes their place.
3. Press **Start The Sims 4** and play.
4. Close the game and press **Restore my mods**.

Sims 4 Mod Test warns about files that change the game's own sliders (the usual cause of tiny heads). If the game
writes an error report, it tells you which mod it mentions, and whether that mod was made before the last game
update.

## Find a broken mod

Sims 4 Mod Test first switches all your mods off, then half of them at a time. After each round you close the game and
say whether the problem is still there. A few thousand mods take about 12 rounds. At the end, **Restore without it**
moves the broken mod to `Mods removed by Sims 4 Mod Test`, so nothing is lost.

## Your files are safe

- Files you add are copied, never moved or changed.
- Your save files are backed up before each test. If the game saved over one, you can put the old one back.
- If the app or your computer stops halfway, the next start puts your folders back.
- The Sims 4 folder and the game folder are found by themselves, and you can pick either one in **Settings**.
  Settings also has light and dark mode, and lets you turn the save backup, the thumbnail-cache cleanup, starting
  the game by itself and the update check on or off.
- See [SECURITY.md](SECURITY.md) for exactly what the app touches.

## Build it yourself

```
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # macOS/Linux: .venv/bin/pip
python -m pytest -q tests
python packaging/build.py
```

The Windows installer needs [Inno Setup 6](https://jrsoftware.org/isinfo.php).

## License

[MIT](LICENSE)
