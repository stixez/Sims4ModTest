# Security

## What Sims 4 Mod Test touches

- Your Sims 4 user folder: it renames `Mods` and `Tray` during a test and renames them back afterwards. Files you
  add to a test are copied, never moved or changed.
- Your save files: the main `Slot_*.save` files are copied to the app's data folder before a test.
- The app's data folder (`%LOCALAPPDATA%\Sims 4 Mod Test` on Windows, `~/Library/Application Support/Sims 4 Mod
  Test` on macOS, `~/.local/share/Sims 4 Mod Test` on Linux): the state of a running test, save backups and a
  cache of the game's own resource keys.
- The game folder: read only, to start the game and to read package indexes.

Once a day the app asks GitHub's public API whether there is a newer release
(`api.github.com/repos/stixez/Sims4ModTest/releases/latest`). Nothing about you or your files is sent, and nothing
is downloaded or installed by itself: you choose whether to open the download. Apart from that, and the "Buy me a
coffee" page when you click it, the app doesn't go online. It doesn't run anything from the mods it copies.

Files from `.zip` downloads are written by their file name only, with characters that are special to the file
system removed, so a zip can't place files outside the test folder. Members that would unpack to something huge
from almost nothing (zip bombs) are skipped. Names read from downloaded Sims are shown as plain text.

## Reporting a problem

Please use [private vulnerability reporting](../../security/advisories/new) on GitHub rather than a public issue.
