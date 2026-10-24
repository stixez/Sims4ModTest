"""Tests for the folder swapping, the broken-mod search, save backups and the risk checks.

Everything runs in a made-up Sims 4 folder under pytest's tmp_path. The Recycle Bin is
replaced by a folder, and the game is never "running".
"""
import io
import os
import shutil
import sys
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import core  # noqa: E402
import platforms  # noqa: E402
import risks  # noqa: E402
import updates  # noqa: E402

L = core.long_path


def trayitem(name: str, kind: int = 1) -> bytes:
    """A minimal .trayitem: header + TrayMetadata with field 2 (type) and field 4 (name)."""
    raw = name.encode()
    msg = bytes([0x10, kind, 0x22, len(raw)]) + raw
    return (0).to_bytes(4, "little") + len(msg).to_bytes(4, "little") + msg


def dbpf(keys) -> bytes:
    """A minimal package whose index lists the given (type, group, instance) keys."""
    idx = (0).to_bytes(4, "little")
    for t, g, i in keys:
        idx += b"".join(v.to_bytes(4, "little") for v in (t, g, i >> 32, i & 0xFFFFFFFF, 96, 0x80000001, 1))
        idx += (0).to_bytes(2, "little") + (1).to_bytes(2, "little")
    head = bytearray(96)
    head[:4] = b"DBPF"
    head[4:8] = (2).to_bytes(4, "little")
    head[8:12] = (1).to_bytes(4, "little")
    head[36:40] = len(keys).to_bytes(4, "little")
    head[44:48] = len(idx).to_bytes(4, "little")
    head[64:68] = (97).to_bytes(4, "little")
    return bytes(head) + b"x" + idx


def later(path: Path) -> None:
    """As if the game wrote the file a minute after the test started."""
    t = time.time() + 60
    os.utime(path, (t, t))


def listing(d: Path) -> list[str]:
    return sorted(str(p.relative_to(d)) for p in d.rglob("*") if p.is_file())


def inodes(d: Path) -> dict[str, int]:
    return {p: os.stat(L(d / p)).st_ino for p in listing(d)}


class World:
    def __init__(self, root: Path):
        self.root = root
        self.sims = root / "Electronic Arts" / "The Sims 4"
        self.mods, self.tray, self.saves = self.sims / "Mods", self.sims / "Tray", self.sims / "saves"
        self.dl = root / "Downloads"
        self.bin = root / "Recycle Bin"
        for d in (self.mods / "_CAS" / "Hair", self.mods / "MCCC", self.tray, self.saves, self.dl, self.bin):
            d.mkdir(parents=True)
        (self.mods / "Resource.cfg").write_text("Priority 500\nPackedFile *.package\n")
        for n in range(10):
            (self.mods / "_CAS" / "Hair" / f"hair{n}.package").write_bytes(b"h%d" % n)
        (self.mods / "root.package").write_bytes(b"r")
        (self.mods / "MCCC" / "mc_cmd.ts4script").write_bytes(b"s")
        (self.mods / "MCCC" / "mc_cas.package").write_bytes(b"p")
        (self.mods / "MCCC" / "mc_settings.cfg").write_text("x")
        (self.mods / "notes.txt").write_text("not a mod")
        (self.tray / "0x00000001!0x00000000000000aa.trayitem").write_bytes(trayitem("Rivera"))
        (self.tray / "0x00000001!0x00000000000000aa.householdbinary").write_bytes(b"hb")
        (self.tray / "0x00000001!0x00000000000000bb.trayitem").write_bytes(trayitem("Hart"))
        (self.saves / "Slot_00000001.save").write_bytes(b"save one")
        (self.saves / "Slot_00000002.save").write_bytes(b"save two")
        (self.saves / "Slot_00000002.save.ver0").write_bytes(b"old")
        (self.sims / "Options.ini").write_text("")
        (self.sims / "GameVersion.txt").write_text("1.0")
        (self.sims / "localthumbcache.package").write_bytes(b"c")

        self.long = "(Creator) " + "a very long item title " * 10 + ".package"
        with open(L(self.dl / self.long), "wb") as fh:
            fh.write(b"L" * 2000)
        (self.dl / "b.ts4script").write_bytes(b"b" * 300)
        inner = io.BytesIO()
        with zipfile.ZipFile(inner, "w") as z:
            z.writestr("More CC/deep/hair.package", "h")
            z.writestr("More CC/dress.package", "d")
        with zipfile.ZipFile(self.dl / "Rivera.zip", "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Rivera/Mods/top.package", "t")
            z.writestr("Rivera/Mods/Scripts/thing.ts4script", "s")
            z.writestr("Rivera/Mods/Scripts/thing.cfg", "cfg")
            z.writestr("Rivera/Tray/0x00000001!0x0000000000000011.trayitem", trayitem("Rivera"))
            z.writestr("Rivera/Tray/0x00000001!0x0000000000000011.householdbinary", "hb")
            z.writestr("Rivera/Tray/0x00000013!0x0000000000000099.sgi", "sgi")
            z.writestr("Rivera/more.zip", inner.getvalue())
            z.writestr("__MACOSX/Rivera/._top.package", "junk")
            z.writestr("readme.txt", "r")
            z.writestr("../../escape.package", "e")
            z.writestr("stream.package:hidden", "s")
        self.deflate64 = self._deflate64()
        (self.dl / "deflate64.zip").write_bytes(self.deflate64)

    @staticmethod
    def _deflate64() -> bytes:
        """zipfile can't read Deflate64 (what Windows uses for big zips): fake one by patching the method."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("a.trayitem", trayitem("X"))
        raw = bytearray(buf.getvalue())
        raw[8:10] = (9).to_bytes(2, "little")
        cd = raw.find(b"PK\x01\x02")
        raw[cd + 10:cd + 12] = (9).to_bytes(2, "little")
        return bytes(raw)

    def recycle(self, path: Path) -> bool:
        shutil.move(L(path), L(self.bin / f"{len(list(self.bin.iterdir()))} {Path(path).name}"))
        return True

    def items(self):
        items, problems = core.inspect_paths(
            [self.dl / self.long, self.dl / "b.ts4script", self.dl / "Rivera.zip"], self.sims)
        assert not problems
        tray_items, _ = core.inspect_paths([self.tray / "0x00000001!0x00000000000000aa.trayitem"], self.sims)
        return items + tray_items


@pytest.fixture
def w(tmp_path, monkeypatch):
    world = World(tmp_path)
    data = tmp_path / "appdata"
    monkeypatch.setattr(core, "DATA_DIR", data)
    monkeypatch.setattr(core, "STATE_PATH", data / "state.json")
    monkeypatch.setattr(core, "SAVE_BACKUP_DIR", data / "save backup")
    monkeypatch.setattr(core, "PENDING_PATH", data / "pending saves.json")
    monkeypatch.setattr(core, "recycle", world.recycle)
    monkeypatch.setattr(core, "game_processes", lambda: [])
    monkeypatch.setattr(core, "game_running", lambda: False)
    return world


# ---------------------------------------------------------------- picking items

def test_items_are_described_and_bad_ones_explained(w):
    items, problems = core.inspect_paths(
        [w.dl / "Rivera.zip", w.dl / "deflate64.zip", w.mods, w.tray, w.dl / "nope.rar"], w.sims)
    assert len(items) == 1 and len(problems) == 4
    z = items[0]
    assert (z.mod_files, z.tray_files, z.tray_names, z.tray_kinds, z.has_script) == (5, 3, ["Rivera"], ["household"], True)
    assert "packed in a way" in problems[0] and "whole Mods folder" in problems[1]


def test_one_tray_file_brings_its_household_only(w):
    items, _ = core.inspect_paths([w.tray / "0x00000001!0x00000000000000aa.trayitem"], w.sims)
    assert items[0].kind == "tray" and items[0].tray_files == 2 and items[0].title == "Rivera"


def test_unreadable_zip_inside_a_folder_is_skipped(w):
    pack = w.dl / "CC pack"
    pack.mkdir()
    (pack / "good.package").write_bytes(b"g")
    (pack / "deflate64.zip").write_bytes(w.deflate64)
    items, problems = core.inspect_paths([pack], w.sims)
    assert not problems and items[0].mod_files == 1


def test_zip_names_are_made_safe():
    assert core.safe_name("stream.package:hidden") == "stream.package_hidden"
    assert core.safe_name("..") == "file" and core.safe_name("CON.package") == "_CON.package"


@pytest.mark.skipif(not platforms.WINDOWS, reason="long paths are a Windows matter")
def test_network_paths_get_the_long_path_prefix():
    assert core.long_path(r"\\server\share\x") == "\\\\?\\UNC\\server\\share\\x"


def test_sims3_folder_is_not_mistaken_for_sims4(w):
    s3 = w.root / "Electronic Arts" / "The Sims 3"
    (s3 / "Mods").mkdir(parents=True)
    (s3 / "Options.ini").write_text("")
    assert core.find_sims_dirs([w.root]) == [w.sims]


# ---------------------------------------------------------------- tests

def test_test_swaps_mods_and_tray_and_puts_them_back(w):
    before_mods, before_tray = inodes(w.mods), inodes(w.tray)
    core.start_test(w.sims, w.items(), True)
    assert core.in_test(w.sims) and core.tray_in_test(w.sims)
    assert os.path.exists(L(w.mods / w.long))
    rivera = w.mods / "Rivera"
    assert {"thing.ts4script", "thing.cfg", "hair.package", "escape.package", "stream.package_hidden"} <= set(
        p.name for p in rivera.iterdir())
    assert not (w.root / "escape.package").exists() and not (w.sims / "escape.package").exists()
    assert len(list(w.tray.iterdir())) == 5
    assert not (w.sims / "localthumbcache.package").exists()
    result = core.end_test(w.sims, True)
    assert not result.leftovers and not result.changed_saves
    assert inodes(w.mods) == before_mods and inodes(w.tray) == before_tray
    assert not core.in_test(w.sims) and core.load_state(w.sims) is None


def test_test_without_tray_files_leaves_tray_alone(w):
    core.start_test(w.sims, w.items()[:1], False)
    assert not core.tray_in_test(w.sims) and (w.tray / "0x00000001!0x00000000000000bb.trayitem").exists()
    core.end_test(w.sims, False)


def test_failed_tray_swap_rolls_back_everything(w, monkeypatch):
    before = inodes(w.mods)
    orig = core._swap_in

    def flaky(sims, slot):
        if slot is core.TRAY:
            raise core._locked("Tray")
        orig(sims, slot)

    monkeypatch.setattr(core, "_swap_in", flaky)
    with pytest.raises(core.TesterError):
        core.start_test(w.sims, w.items(), False)
    assert not core.in_test(w.sims) and inodes(w.mods) == before
    assert not (w.sims / core.MODS.staging).exists() and not core.finished_folders(w.sims)


def test_double_failure_is_put_right_on_next_start(w, monkeypatch):
    orig, calls = core._rename, []

    def bad(a, b):
        calls.append(b)
        if Path(a).name == core.MODS.staging or (len(calls) > 2 and Path(b).name == "Mods"):
            raise PermissionError(5, "locked")
        orig(a, b)

    monkeypatch.setattr(core, "_rename", bad)
    with pytest.raises(core.TesterError):
        core.start_test(w.sims, w.items()[:1], False)
    monkeypatch.setattr(core, "_rename", orig)
    core.recover(w.sims)  # what the app does when it starts
    assert not core.in_test(w.sims) and (w.mods / "MCCC").is_dir()


def test_interrupted_end_is_finished_on_next_start(w):
    core.start_test(w.sims, w.items(), False)
    os.rename(w.mods, w.sims / core.MODS.finished)
    os.rename(w.tray, w.sims / core.TRAY.finished)
    core.recover(w.sims)
    assert not core.in_test(w.sims) and not core.tray_in_test(w.sims) and (w.mods / "MCCC").is_dir()
    assert not core.finished_folders(w.sims) and not core.finished_folders(w.sims, core.TRAY)


def test_leftover_that_recycle_bin_refuses_does_not_block(w, monkeypatch):
    (w.sims / core.MODS.finished).mkdir()
    monkeypatch.setattr(core, "recycle", lambda p: None)
    core.start_test(w.sims, w.items()[:1], False)
    (w.mods / "dropped in during the test.package").write_bytes(b"x")  # so the folder needs the bin
    result = core.end_test(w.sims, False)
    assert not core.in_test(w.sims) and [p.name for p in result.leftovers] == ["Mods (test copies, Sims 4 Mod Test 2)"]


def test_no_mods_or_tray_folder_yet(w):
    shutil.rmtree(w.mods)
    shutil.rmtree(w.tray)
    core.start_test(w.sims, [i for i in w.items() if i.kind != "tray"], False)
    core.end_test(w.sims, False)
    assert w.mods.is_dir() and not any(w.mods.iterdir()) and w.tray.is_dir() and not any(w.tray.iterdir())


# ---------------------------------------------------------------- saves

def test_overwritten_save_must_be_decided_before_the_next_test(w):
    core.start_test(w.sims, w.items()[:1], False)
    (w.saves / "Slot_00000002.save").write_bytes(b"saved during the test")
    later((w.saves / "Slot_00000002.save"))
    result = core.end_test(w.sims, False)
    assert [c["name"] for c in result.changed_saves] == ["Slot_00000002.save"]
    # Another test would leave the version saved during this one without a copy: refused.
    with pytest.raises(core.TesterError, match="First choose what to do with the save"):
        core.start_test(w.sims, w.items()[:1], False)
    with pytest.raises(core.TesterError, match="First choose what to do with the save"):
        core.start_search(w.sims, False)
    assert not core.in_test(w.sims)
    assert core.restore_saves(w.sims, ["Slot_00000002.save"]) == []
    assert (w.saves / "Slot_00000002.save").read_bytes() == b"save two" and core.pending_saves(w.sims) == []
    core.start_test(w.sims, w.items()[:1], False)  # decided: a new test may start
    core.end_test(w.sims, False)


def test_a_missing_save_backup_is_reported_not_retried(w):
    core.start_test(w.sims, w.items()[:1], False)
    (w.saves / "Slot_00000002.save").write_bytes(b"saved during the test")
    later((w.saves / "Slot_00000002.save"))
    core.end_test(w.sims, False)
    (core._backup_dir(w.sims) / "Slot_00000002.save").unlink()
    assert core.restore_saves(w.sims, ["Slot_00000002.save"]) == ["Slot_00000002.save"]
    assert core.pending_saves(w.sims) == [] and (w.saves / "Slot_00000002.save").read_bytes() == b"saved during the test"


def test_keeping_the_new_save_forgets_the_offer(w):
    core.start_test(w.sims, w.items()[:1], False)
    (w.saves / "Slot_00000001.save").write_bytes(b"new")
    later((w.saves / "Slot_00000001.save"))
    core.end_test(w.sims, False)
    core.keep_new_saves(w.sims, ["Slot_00000001.save"])
    assert core.pending_saves(w.sims) == [] and (w.saves / "Slot_00000001.save").read_bytes() == b"new"


# ---------------------------------------------------------------- broken-mod search

def run_search(w, broken: str | None) -> dict:
    core.start_search(w.sims, False)
    st = core.load_state(w.sims)
    while st["found"] is None and not st["not_mods"]:
        on = listing(w.mods)
        for p in on:
            if p != "Resource.cfg":
                assert os.stat(L(w.mods / p)).st_nlink == 2, p  # hard links, not copies
        (w.mods / "game wrote this.log").write_text("log")
        still = broken is None or broken in on
        st = core.answer_search(w.sims, still, False)
    return st


def test_search_finds_the_broken_mod_and_moves_it_out(w):
    before = inodes(w.mods)
    culprit = os.path.join("_CAS", "Hair", "hair7.package")
    units = core.mod_units(w.mods)
    assert len(units) == 12
    assert [os.path.join("MCCC", n) for n in ("mc_cas.package", "mc_cmd.ts4script", "mc_settings.cfg")] in units
    st = run_search(w, culprit)
    assert st["units"][st["found"]] == [culprit] and st["round"] <= core.rounds_left(12)
    result = core.end_test(w.sims, False, remove_found=True)
    assert (result.removed / culprit).exists() and not (w.mods / culprit).exists()
    after = inodes(w.mods)
    assert {k: v for k, v in before.items() if k != culprit} == after  # the same files, not copies
    assert all(os.stat(L(w.mods / p)).st_nlink == 1 for p in after)
    assert any("game wrote this.log" in p.name or p.is_dir() for p in w.bin.iterdir())


def test_problem_with_all_mods_off_is_not_a_mod(w):
    before = inodes(w.mods)
    st = run_search(w, None)
    assert st["not_mods"] and st["round"] == 0
    result = core.end_test(w.sims, False, remove_found=True)
    assert not result.removed and inodes(w.mods) == before


def test_search_refuses_when_its_folder_was_changed(w):
    before = inodes(w.mods)
    core.start_search(w.sims, False)
    core.answer_search(w.sims, False, False)
    victim = next(p for p in listing(w.mods) if p != "Resource.cfg")
    os.unlink(L(w.mods / victim))
    with pytest.raises(core.TesterError, match="lost track"):
        core.answer_search(w.sims, True, False)
    core.end_test(w.sims, False)
    assert inodes(w.mods) == before


def test_script_mod_rewriting_its_config_does_not_stop_the_search(w):
    (w.mods / "MCCC" / "Resource.cfg").write_text("x")  # odd, but seen in the wild
    core.start_search(w.sims, False)
    st = core.answer_search(w.sims, False, False)
    while st["found"] is None:
        cfg = w.mods / "MCCC" / "mc_settings.cfg"
        if cfg.exists():  # the script mod saves its settings by replacing the file
            tmp = cfg.with_suffix(".tmp")
            tmp.write_text("new settings")
            os.replace(tmp, cfg)
        st = core.answer_search(w.sims, os.path.join("MCCC", "mc_cmd.ts4script") in listing(w.mods), False)
    assert os.path.join("MCCC", "mc_cmd.ts4script") in st["units"][st["found"]]
    core.end_test(w.sims, False)


def test_saves_of_two_sims_folders_are_kept_apart(w, tmp_path):
    other = tmp_path / "Electronic Arts" / "Les Sims 4"
    (other / "saves").mkdir(parents=True)
    (other / "Tray").mkdir()
    (other / "saves" / "Slot_00000002.save").write_bytes(b"other folder's save")
    core.start_test(w.sims, w.items()[:1], False)
    (w.saves / "Slot_00000002.save").write_bytes(b"changed")
    later((w.saves / "Slot_00000002.save"))
    core.end_test(w.sims, False)
    assert core.pending_saves(w.sims) and not core.pending_saves(other)
    core.backup_saves(other)
    assert (core._backup_dir(w.sims) / "Slot_00000002.save").read_bytes() == b"save two"


def test_zip_bomb_members_are_skipped(w):
    with zipfile.ZipFile(w.dl / "bomb.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ok.package", "fine")
        z.writestr("huge.package", b"\0" * (80 << 20))
    items, problems = core.inspect_paths([w.dl / "bomb.zip"], w.sims)
    assert not problems and items[0].mod_files == 1


def test_locked_found_mod_still_finishes_the_restore(w, monkeypatch):
    run_search(w, "root.package")
    monkeypatch.setattr(core, "_move_out", lambda s, u: (_ for _ in ()).throw(PermissionError(13, "in use")))
    result = core.end_test(w.sims, False, remove_found=True)
    assert result.move_failed and not core.in_test(w.sims) and core.load_state(w.sims) is None


# ---------------------------------------------------------------- risks

def test_override_and_old_script_warnings(w):
    (w.dl / "slider.package").write_bytes(dbpf([(0xC5F6763E, 0, 0x1234), (0x034AEECB, 0, 0x99)]))
    game_keys = frozenset({risks._key_int(0xC5F6763E, 0, 0x1234)})
    item = core.inspect_paths([w.dl / "slider.package"], w.sims)[0][0]
    assert [x.split(".")[0] for x in risks.check(item, game_keys)] == ["Changes the game\u2019s own sliders or body shapes"]
    with zipfile.ZipFile(w.dl / "old.ts4script", "w") as z:
        z.writestr(zipfile.ZipInfo("x.pyc", (2019, 5, 1, 0, 0, 0)), "c")
    assert risks.check(core.inspect_paths([w.dl / "old.ts4script"], w.sims)[0][0], game_keys) == []
    assert "before the last game update" in risks.outdated_note(w.dl / "old.ts4script", time.time())
    assert risks.outdated_note(w.dl / "old.ts4script", time.mktime((2018, 1, 1, 0, 0, 0, 0, 0, -1))) == ""


def test_error_report_names_the_script(w):
    rep = w.sims / "lastException_1.txt"
    rep.write_text('File "C:\\Users\\x\\Mods\\Tiny\\Tiny_SleepMod.ts4script\\sleep.py", line 3\n', encoding="utf-8")
    assert risks.report_suspects(rep, []) == ["Tiny_SleepMod.ts4script"]


# ---------------------------------------------------------------- updates and platforms

def test_update_is_offered_only_when_newer_and_only_from_this_repo():
    base = f"https://github.com/{updates.REPO}/releases/download/v1.2.0/"
    data = {"tag_name": "v1.2.0", "html_url": f"https://github.com/{updates.REPO}/releases/tag/v1.2.0",
            "assets": [{"name": "Sims-4-Mod-Test-1.2.0-setup.exe", "browser_download_url": base + "a-setup.exe"},
                       {"name": "Sims-4-Mod-Test-1.2.0-macos.zip", "browser_download_url": base + "b-macos.zip"},
                       {"name": "Sims-4-Mod-Test-1.2.0-linux-x86_64.tar.gz",
                        "browser_download_url": base + "c-linux-x86_64.tar.gz"}]}
    assert updates.parse_release(data, "win32").download.endswith("-setup.exe")
    assert updates.parse_release(data, "darwin").download.endswith("-macos.zip")
    assert updates.parse_release(data, "linux").download.endswith(".tar.gz")
    evil = dict(data, assets=[{"name": "x-setup.exe", "browser_download_url": "https://evil.example/x-setup.exe"}])
    assert updates.parse_release(evil, "win32").download.startswith(f"https://github.com/{updates.REPO}/")
    assert updates.parse_release(dict(data, draft=True)) is None
    assert updates.is_newer("1.2.0", "1.0.0") and not updates.is_newer("1.0.0", "1.0.0")
    assert not updates.is_newer("v0.9", "1.0.0") and updates.parse_version("banana") is None


def test_game_folder_is_found_in_a_mac_app_bundle(tmp_path):
    app = tmp_path / "The Sims 4.app"
    (app / "Contents" / "Data" / "Client").mkdir(parents=True)
    assert platforms.game_content_root(app) == app / "Contents"
    win = tmp_path / "The Sims 4"
    (win / "Data" / "Client").mkdir(parents=True)
    assert platforms.game_content_root(win) == win and platforms.game_content_root(tmp_path) is None
    exe = os.path.join(str(win), "Game", "Bin", "TS4_x64.exe")
    assert platforms.game_dir_from_process(exe) == win


def test_folders_from_the_old_mod_tester_name_are_taken_over(w, tmp_path, monkeypatch):
    old_backup = w.sims / "Mods (your mods, set aside by Mod Tester)"
    os.rename(w.mods, old_backup)
    (w.mods).mkdir()  # the old app's test Mods
    (w.sims / "Mods (finished Mod Tester test 2)").mkdir()
    old_data = core.DATA_DIR.parent / "Mod Tester"
    old_data.mkdir(parents=True)
    (old_data / "state.json").write_text("{}")
    core.recover(w.sims)
    assert core.in_test(w.sims) and (w.sims / core.MODS.backup / "MCCC").is_dir()
    assert not (w.sims / "Mods (finished Mod Tester test 2)").exists()
    assert (core.DATA_DIR / "state.json").exists()
    core.end_test(w.sims, False)
    assert (w.mods / "MCCC").is_dir()


# ---------------------------------------------------------------- guards and limits

def test_nothing_moves_while_the_game_runs(w, monkeypatch):
    core.start_test(w.sims, w.items()[:1], False)
    monkeypatch.setattr(core, "game_running", lambda: True)
    for call in (lambda: core.end_test(w.sims, False),
                 lambda: core.restore_saves(w.sims, []),
                 lambda: core.answer_search(w.sims, True, False)):
        with pytest.raises(core.TesterError, match="Close The Sims 4"):
            call()
    monkeypatch.setattr(core, "game_running", lambda: False)
    core.end_test(w.sims, False)
    monkeypatch.setattr(core, "game_running", lambda: True)
    for call in (lambda: core.start_test(w.sims, w.items()[:1], False), lambda: core.start_search(w.sims, False)):
        with pytest.raises(core.TesterError, match="Close The Sims 4"):
            call()
    assert not core.in_test(w.sims)


def test_not_enough_disk_space_is_refused_before_anything_moves(w, monkeypatch):
    monkeypatch.setattr(core.shutil, "disk_usage", lambda p: shutil._ntuple_diskusage(1, 1, 1000))
    with pytest.raises(core.TesterError, match="enough free space"):
        core.start_test(w.sims, w.items(), False)
    assert not core.in_test(w.sims) and not (w.sims / core.MODS.staging).exists()


def test_downloads_that_are_far_too_big_or_compress_absurdly_are_refused(w, monkeypatch):
    with zipfile.ZipFile(w.dl / "sneaky.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ok.package", "fine")
        for n in range(3):  # each under 64 MB but packed 1000s of times over
            z.writestr(f"zeros{n}.package", b"\0" * (8 << 20))
    items, _ = core.inspect_paths([w.dl / "sneaky.zip"], w.sims)
    assert items[0].mod_files == 1
    monkeypatch.setattr(core, "MAX_ITEM_FILES", 3)
    _, problems = core.inspect_paths([w.dl / "Rivera.zip"], w.sims)
    assert problems and "far more than a mod download" in problems[0]


def test_a_crafted_trayitem_cannot_stall_the_app():
    msg = bytes([0x10]) + b"\xff" * 200_000  # field 2 with a never-ending number
    data = (0).to_bytes(4, "little") + len(msg).to_bytes(4, "little") + msg
    started = time.time()
    assert core.tray_item_info(data) == (None, "")
    assert time.time() - started < 5  # without the limit this took about 45 s


def test_links_in_dropped_folders_are_not_followed(w):
    pack = w.dl / "Linked pack"
    pack.mkdir()
    (pack / "real.package").write_bytes(b"r")
    try:
        os.symlink(w.mods / "root.package", pack / "link.package")
        os.symlink(w.mods, pack / "loop", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this system doesn't allow creating symlinks")
    items, problems = core.inspect_paths([pack], w.sims)
    assert not problems and items[0].mod_files == 1


def test_unpackable_formats_say_what_to_do(w):
    (w.dl / "pack.7z").write_bytes(b"7z")
    _, problems = core.inspect_paths([w.dl / "pack.7z", w.dl / "notes.txt"], w.sims)
    assert "Unpack" in problems[0] and ".zip" in problems[0]


# ---------------------------------------------------------------- files that appear during a test or round

def test_files_added_during_a_test_are_counted(w):
    core.start_test(w.sims, w.items(), False)
    (w.tray / "0x00000001!0x00000000000000ee.trayitem").write_bytes(trayitem("Saved During Test"))
    (w.mods / "game wrote this.log").write_text("log")
    result = core.end_test(w.sims, False)
    assert result.added_files == 2


def test_an_edited_resource_cfg_in_a_round_is_kept_not_deleted(w):
    core.start_search(w.sims, False)
    cfg = w.mods / "Resource.cfg"
    cfg.unlink()  # an editor that saves by replacing the file breaks the hard link
    cfg.write_text("Priority 500\nPackedFile *.package\n# my edit\n")
    core.end_test(w.sims, False)
    kept = [p for p in w.bin.rglob("Resource.cfg") if "my edit" in p.read_text()]
    assert kept, "the edited file should be in the Recycle Bin, not deleted"


def test_config_files_at_the_top_of_mods_are_in_every_round(w):
    (w.mods / "top_script.ts4script").write_bytes(b"s")
    (w.mods / "top_script_settings.cfg").write_text("x")
    core.start_search(w.sims, False)
    assert (w.mods / "top_script_settings.cfg").exists()  # round 0: all mods off, configs still there
    core.end_test(w.sims, False)
    assert (w.mods / "top_script_settings.cfg").read_text() == "x"


def test_the_old_data_folder_is_brought_over_even_after_a_failed_first_try(w):
    old = core.DATA_DIR.parent / "Mod Tester"
    (old / "save backup").mkdir(parents=True)
    (old / "pending saves.json").write_text("[]")
    core.DATA_DIR.mkdir(parents=True, exist_ok=True)  # the new folder exists already
    core.migrate_data_dir()
    assert (core.DATA_DIR / "pending saves.json").exists() and (core.DATA_DIR / "save backup").is_dir()
    assert not old.exists()


# ---------------------------------------------------------------- update check and Steam libraries

def test_update_check_failures_are_told_apart_from_no_update(monkeypatch):
    def offline(*a, **k):
        raise updates.urllib.error.URLError("offline")

    monkeypatch.setattr(updates.urllib.request, "urlopen", offline)
    with pytest.raises(updates.CheckFailed):
        updates.find_update()


def test_steam_libraries_on_other_drives_are_found(tmp_path, monkeypatch):
    steam = tmp_path / "Steam"
    (steam / "steamapps").mkdir(parents=True)
    other = tmp_path / "Games" / "SteamLibrary"
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n "0" { "path" "' + str(steam).replace("\\", "\\\\") + '" }\n'
        ' "1" { "path" "' + str(other).replace("\\", "\\\\") + '" }\n}\n', encoding="utf-8")
    monkeypatch.setattr(platforms, "_steam_roots", lambda home: [steam])
    assert platforms.steam_libraries() == [steam, other]



# ---------------------------------------------------------------- round 2 of the review

def test_a_households_sims_come_along_from_a_shared_tray_folder(w):
    hb = w.tray / "0x00000001!0x00000000000000aa.householdbinary"
    hb.write_bytes(b"head" + (0x0E00000000000001).to_bytes(8, "little") + b"tail")
    (w.tray / "0x00000013!0x0e00000000000001.sgi").write_bytes(b"this household's Sim")
    (w.tray / "0x00000013!0x0e00000000000099.sgi").write_bytes(b"someone else's Sim")
    items, _ = core.inspect_paths([w.tray / "0x00000001!0x00000000000000aa.trayitem"], w.sims)
    names = sorted(Path(f).name for f in items[0].files)
    assert "0x00000013!0x0e00000000000001.sgi" in names and "0x00000013!0x0e00000000000099.sgi" not in names


def test_the_games_mod_switches_are_read(w):
    (w.sims / "Options.ini").write_text("[options]\nmodsdisabled = 1\nscriptmodsenabled = 0\n")
    assert core.game_mod_settings(w.sims) == (False, False)
    (w.sims / "Options.ini").write_text("modsdisabled = 0\nscriptmodsenabled = 1\n")
    assert core.game_mod_settings(w.sims) == (True, True)
    (w.sims / "Options.ini").unlink()
    assert core.game_mod_settings(w.sims) == (None, None)


def test_cache_files_and_the_script_cache_are_cleared(w):
    (w.sims / "avatarcache.package").write_bytes(b"a")
    (w.sims / "cachestr").mkdir()
    (w.sims / "cachestr" / "x.cache").write_bytes(b"c")
    core.clear_game_cache(w.sims)
    assert not (w.sims / "localthumbcache.package").exists() and not (w.sims / "avatarcache.package").exists()
    assert (w.sims / "cachestr").is_dir() and not any((w.sims / "cachestr").iterdir())


def test_unchanged_saves_are_not_copied_again(w, monkeypatch):
    core.backup_saves(w.sims)
    calls = []
    real = core.shutil.copy2
    monkeypatch.setattr(core.shutil, "copy2", lambda a, b, **k: (calls.append(Path(a).name), real(a, b, **k)))
    core.backup_saves(w.sims)
    assert calls == []
    (w.saves / "Slot_00000001.save").write_bytes(b"played since")
    later(w.saves / "Slot_00000001.save")
    core.backup_saves(w.sims)
    assert calls == ["Slot_00000001.save"]


def test_test_copies_are_deleted_and_only_new_files_go_to_the_bin(w):
    core.start_test(w.sims, w.items(), False)
    assert (w.sims / core.README_NAME).exists()  # in case the test is forgotten
    (w.mods / "game wrote this.log").write_text("log")
    result = core.end_test(w.sims, False)
    assert not (w.sims / core.README_NAME).exists()
    binned = [f.name for f in w.bin.rglob("*") if f.is_file()]
    assert result.added_files == 1 and binned == ["game wrote this.log"]


def test_a_stale_read_me_goes_when_no_test_runs(w):
    (w.sims / core.README_NAME).write_text("left over")
    core.recover(w.sims)
    assert not (w.sims / core.README_NAME).exists()


def test_package_indexes_are_read_once_while_inspecting(w, monkeypatch):
    (w.dl / "slider.package").write_bytes(dbpf([(0xC5F6763E, 0, 0x1234)]))
    item = core.inspect_paths([w.dl / "slider.package"], w.sims, risks.package_keys)[0][0]
    monkeypatch.setattr(core, "entries", lambda i: (_ for _ in ()).throw(AssertionError("read again")))
    game_keys = frozenset({risks._key_int(0xC5F6763E, 0, 0x1234)})
    assert risks.check(item, game_keys)[0].startswith("Changes the game")


def test_a_test_copy_replaced_during_the_test_is_kept_not_deleted(w):
    core.start_test(w.sims, w.items()[:1], False)
    copy = next(p for p in w.mods.iterdir() if p.suffix == ".package")
    with open(L(copy), "wb") as fh:  # the first item has a very long name
        fh.write(b"the user's own newer version, put over the test copy")
    result = core.end_test(w.sims, False)
    binned = [open(L(f), "rb").read() for f in Path(L(w.bin)).rglob("*") if f.is_file()]
    assert b"the user's own newer version, put over the test copy" in binned and result.added_files == 1


def test_recovery_clears_the_note_and_a_record_of_a_test_that_never_started(w):
    core.start_test(w.sims, w.items()[:1], False)
    os.rename(w.mods, w.sims / core.MODS.finished)  # killed halfway through the end
    core.recover(w.sims)
    assert not core.in_test(w.sims) and not (w.sims / core.README_NAME).exists()
    core._save_state({"mode": "test", "sims_dir": str(w.sims), "started": 0, "items": []})  # power cut mid-start
    core.recover(w.sims)
    assert core.load_state(w.sims) is None and not core.STATE_PATH.exists()


def test_odd_sim_file_names_dont_break_adding_tray_files(w):
    (w.tray / "0x00000013!0x1234567890abcdef12.sgi").write_bytes(b"x")
    items, problems = core.inspect_paths([w.tray / "0x00000001!0x00000000000000aa.trayitem"], w.sims)
    assert items and not problems
