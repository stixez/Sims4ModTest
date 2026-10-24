# Mod Tester

Try Sims 4 mods on their own, find the mod that breaks your game, and put everything back with one click.

<a href="https://buymeacoffee.com/stixe"><img src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?logo=buymeacoffee&logoColor=black" alt="Buy Me a Coffee"></a>

<img src="docs/test-new-mods.png" width="420" alt="Testing new mods"> <img src="docs/find-a-broken-mod.png" width="420" alt="Finding a broken mod">

## Download

Get `Mod Tester.exe` from [Releases](../../releases) and double-click it. No installer. Windows only.

## Test new mods

1. Drag in what you want to try: packages, script mods, tray files, folders or `.zip` downloads.
2. Press **Start test**. Your own Mods (and Tray, if the test has Sims or lots) are set aside, and a fresh folder
   with only the test files takes their place.
3. Press **Start The Sims 4** and play.
4. Close the game and press **Restore my mods**.

Mod Tester warns about files that change the game's own sliders (the usual cause of tiny heads) and script mods
made before the last game update. If the game writes an error report, it tells you which mod it mentions.

## Find a broken mod

Mod Tester first switches all your mods off, then half of them at a time. After each round you close the game and
say whether the problem is still there. A few thousand mods take about 12 rounds. At the end, **Restore without it**
moves the broken mod to `Mods removed by Mod Tester`, so nothing is lost.

## Your files are safe

- Files you add are copied, never moved or changed.
- Your save files are backed up before each test. If the game saved over one, you can put the old one back.
- If the app or your PC stops halfway, the next start puts your folders back.
- Nothing is sent anywhere. See [SECURITY.md](SECURITY.md).

## Build it yourself

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m pytest -q tests
.venv\Scripts\python -m PyInstaller --noconfirm --onefile --windowed --name "Mod Tester" --icon assets/icon.ico app.py
```

## License

[MIT](LICENSE)
