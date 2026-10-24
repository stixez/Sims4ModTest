# Security

## What Mod Tester touches

- Your Sims 4 user folder: it renames `Mods` and `Tray` during a test and renames them back afterwards. Files you
  add to a test are copied, never moved or changed.
- Your save files: the main `Slot_*.save` files are copied to `%LOCALAPPDATA%\Mod Tester` before a test.
- `%LOCALAPPDATA%\Mod Tester`: the state of a running test, save backups and a cache of the game's own resource
  keys.
- The game folder: read only, to find The Sims 4 and to read package indexes.

Mod Tester never connects to the internet. The only link it opens is the "Buy me a coffee" page, in your browser,
when you click it. It doesn't run anything from the mods it copies.

Files from `.zip` downloads are written by their file name only, with characters Windows treats specially
removed, so a zip can't place files outside the test folder.

## Reporting a problem

Please use [private vulnerability reporting](../../security/advisories/new) on GitHub rather than a public issue.
