"""Sims 4 Mod Test: try out Sims 4 mods on their own, find a broken mod, then put your own mods back."""
from __future__ import annotations

import html
import os
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QLockFile, QSettings, QStandardPaths, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QMessageBox,
                               QLabel, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStackedLayout,
                               QStackedWidget, QVBoxLayout, QWidget)

import psutil

import core
import platforms
import risks
import updates
from version import __version__

APP_NAME = "Sims 4 Mod Test"
REPORT_CHECK_MS = 3000      # how often a running test looks for new error reports
UPDATE_CHECK_DELAY_MS = 3000  # the update check waits until the window is up
SMOKE_TEST_CLOSE_MS = 3000  # CI: how long the built app stays open before closing itself
SUPPORT_URL = "https://buymeacoffee.com/stixe"

# ---------------------------------------------------------------- theme

LIGHT = {
    "bg": "#F6F5F2", "surface": "#FFFFFF", "border": "#E3E1DC", "border_strong": "#C9C6BF",
    "text": "#1D1C1A", "muted": "#64615B", "hover": "#EFEDE9",
    "ink": "#1D1C1A", "ink_hover": "#3A3834", "on_ink": "#FFFFFF",
    "disabled_bg": "#E3E1DC", "disabled_text": "#6B6862", "focus": "#2F64C8",
    "warn_bg": "#FBF4E4", "warn_border": "#EAD7A8", "warn_text": "#6B4A00",
    "error_bg": "#FCEDEC", "error_border": "#EFC4C0", "error_text": "#8A1F17",
    "ok_bg": "#EAF4EC", "ok_border": "#BFDCC6", "ok_text": "#1F5A30",
}
DARK = {
    "bg": "#171716", "surface": "#201F1E", "border": "#32312E", "border_strong": "#4A4844",
    "text": "#EDECE8", "muted": "#A6A39C", "hover": "#2A2927",
    "ink": "#EDECE8", "ink_hover": "#D6D4CE", "on_ink": "#171716",
    "disabled_bg": "#2E2D2B", "disabled_text": "#9A978F", "focus": "#7FA6F0",
    "warn_bg": "#2A2416", "warn_border": "#4D3F1E", "warn_text": "#EBC77A",
    "error_bg": "#2C1917", "error_border": "#552B27", "error_text": "#F0A39B",
    "ok_bg": "#17261B", "ok_border": "#2A4A32", "ok_text": "#93D3A6",
}

ICON_REMOVE = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" '
               'stroke="{c}" stroke-width="1.5" stroke-linecap="round" fill="none"/></svg>')
ICON_CHECK = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><path d="M3.5 8.3l3 3 6-6.6" '
              'stroke="{c}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>')
ICON_CUP = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none" stroke="#1D1C1A" '
            'stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">'
            '<path d="M2.5 6h8.5v4a3 3 0 0 1-3 3h-2.5a3 3 0 0 1-3-3z"/><path d="M11 7h1a1.75 1.75 0 0 1 0 3.5h-1"/>'
            '<path d="M5 2.5c0 .8.8 1 .8 1.8M8 2.5c0 .8.8 1 .8 1.8"/></svg>')
ICON_APP = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
            '<rect x="2" y="2" width="60" height="60" rx="14" fill="#1D1C1A"/>'
            '<rect x="15" y="15" width="22" height="22" rx="5" fill="none" stroke="#FFFFFF" stroke-width="4"/>'
            '<rect x="27" y="27" width="22" height="22" rx="5" fill="#FFFFFF"/></svg>')

_icon_dir = Path(tempfile.mkdtemp(prefix="s4modtest-"))


def svg_pixmap(svg: str, size: int, ratio: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


_appearance = "system"  # "system", "light" or "dark" (Settings)


def current_theme() -> dict:
    if _appearance in ("light", "dark"):
        return LIGHT if _appearance == "light" else DARK
    scheme = QGuiApplication.styleHints().colorScheme()
    return DARK if scheme == Qt.ColorScheme.Dark else LIGHT


def build_qss(t: dict) -> str:
    check = _icon_dir / ("check-dark.svg" if t is DARK else "check-light.svg")
    check.write_text(ICON_CHECK.format(c=t["on_ink"]), encoding="utf-8")
    check_url = check.as_posix()
    return f"""
    QWidget#root {{ background: {t['bg']}; }}
    QLabel {{ color: {t['text']}; background: transparent; }}
    QLabel[role="title"] {{ font-size: 20px; font-weight: 600; }}
    QLabel[role="heading"] {{ font-size: 18px; font-weight: 600; }}
    QLabel[role="section"] {{ font-size: 14px; font-weight: 600; }}
    QLabel[role="muted"] {{ color: {t['muted']}; }}
    QLabel[role="rowname"] {{ font-weight: 500; }}
    QLabel[role="rowwarn"] {{ color: {t['warn_text']}; }}

    QFrame#segments {{ background: {t['border']}; border-radius: 8px; }}
    QPushButton[role="segment"] {{
        background: transparent; border: 1px solid transparent; border-radius: 6px;
        padding: 6px 14px; color: {t['muted']};
    }}
    QPushButton[role="segment"]:hover {{ color: {t['text']}; }}
    QPushButton[role="segment"]:checked {{ background: {t['surface']}; color: {t['text']}; font-weight: 600; }}
    QPushButton[role="segment"]:focus {{ border-color: {t['focus']}; }}

    QFrame#list, QFrame#card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; }}
    QFrame#list[drag="true"] {{ border: 1px solid {t['ink']}; }}
    QFrame#empty {{ border: 1px dashed {t['border_strong']}; border-radius: 8px; background: transparent; }}
    QFrame#list[drag="true"] QFrame#empty {{ border-color: {t['ink']}; background: {t['hover']}; }}
    QFrame#row {{ background: transparent; border: none; }}
    QFrame#row[first="false"] {{ border-top: 1px solid {t['border']}; }}
    QScrollArea, QWidget#listContent {{ background: transparent; border: none; }}

    QPushButton {{
        background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border_strong']};
        border-radius: 6px; padding: 7px 14px;
    }}
    QPushButton:hover {{ background: {t['hover']}; }}
    QPushButton:focus {{ border-color: {t['focus']}; }}
    QPushButton:disabled {{ color: {t['disabled_text']}; border-color: {t['border']}; background: {t['surface']}; }}
    QPushButton[role="primary"] {{
        background: {t['ink']}; color: {t['on_ink']}; border: 1px solid {t['ink']};
        padding: 10px 20px; font-weight: 600;
    }}
    QPushButton[role="primary"]:hover {{ background: {t['ink_hover']}; border-color: {t['ink_hover']}; }}
    QPushButton[role="primary"]:focus {{ border: 1px solid {t['focus']}; }}
    QPushButton[role="primary"]:disabled {{
        background: {t['disabled_bg']}; color: {t['disabled_text']}; border-color: {t['disabled_bg']};
    }}
    QPushButton[role="answer"] {{ padding: 14px 18px; font-size: 14px; font-weight: 600; border-radius: 8px; }}
    QPushButton[role="link"] {{
        background: transparent; border: none; padding: 0; color: {t['text']}; text-decoration: underline;
    }}
    QPushButton[role="link"]:hover {{ color: {t['muted']}; }}
    QPushButton[role="link"]:focus {{ color: {t['focus']}; }}
    QPushButton[role="link"]:disabled {{ color: {t['disabled_text']}; }}
    QPushButton[role="icon"] {{ background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 4px; }}
    QPushButton[role="icon"]:hover {{ background: {t['hover']}; }}
    QPushButton[role="icon"]:focus {{ border-color: {t['focus']}; }}

    QFrame[tone] {{ border-radius: 8px; }}
    QFrame[tone="warn"] {{ background: {t['warn_bg']}; border: 1px solid {t['warn_border']}; }}
    QFrame[tone="warn"] QLabel {{ color: {t['warn_text']}; }}
    QFrame[tone="error"] {{ background: {t['error_bg']}; border: 1px solid {t['error_border']}; }}
    QFrame[tone="error"] QLabel {{ color: {t['error_text']}; }}
    QFrame[tone="ok"] {{ background: {t['ok_bg']}; border: 1px solid {t['ok_border']}; }}
    QFrame[tone="ok"] QLabel {{ color: {t['ok_text']}; }}

    QCheckBox {{ color: {t['text']}; spacing: 10px; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border: 1px solid {t['border_strong']}; border-radius: 4px;
        background: {t['surface']};
    }}
    QCheckBox::indicator:hover {{ border-color: {t['ink']}; }}
    QCheckBox:focus::indicator {{ border-color: {t['focus']}; }}
    QCheckBox::indicator:checked {{ background: {t['ink']}; border-color: {t['ink']}; image: url({check_url}); }}

    QProgressBar {{ background: {t['border']}; border: none; border-radius: 2px; max-height: 4px; }}
    QProgressBar::chunk {{ background: {t['ink']}; border-radius: 2px; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
    QScrollBar::handle:vertical {{ background: {t['border_strong']}; border-radius: 3px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
        background: none; height: 0;
    }}
    QToolTip {{ color: {t['text']}; background: {t['surface']}; border: 1px solid {t['border']}; padding: 4px; }}

    QPushButton[role="coffee"] {{
        background: #FFDD00; color: #1D1C1A; border: 1px solid #FFDD00; border-radius: 13px;
        padding: 4px 12px 4px 10px; font-weight: 500;
    }}
    QPushButton[role="coffee"]:hover {{ background: #F5D000; border-color: #F5D000; }}
    QPushButton[role="coffee"]:focus {{ border-color: {t['focus']}; }}
    """


# ---------------------------------------------------------------- text helpers

def fmt_size(n: int) -> str:
    if n < 1024 * 1024:
        return f"{max(1, round(n / 1024))} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def when(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    if d.date() == datetime.now().date():
        return f"today at {d:%H:%M}"
    return f"{d.day} {d:%b} at {d:%H:%M}"


def describe(item: core.ModItem) -> str:
    if item.kind == "package":
        return "Package"
    if item.kind == "script":
        return "Script mod"
    if item.kind == "tray":
        kinds = set(item.tray_kinds)
        if len(item.tray_names) == 1 and item.tray_kinds and item.tray_kinds[0]:
            what = item.tray_kinds[0].capitalize()
        elif len(kinds) == 1 and "" not in kinds and item.tray_names:
            what = plural(len(item.tray_names), kinds.pop())
        else:
            what = "Tray item" if len(item.tray_names) <= 1 else f"{len(item.tray_names)} tray items"
        return f"{what}, {plural(item.tray_files, 'file')}"
    parts = []
    if item.mod_files:
        parts.append(plural(item.mod_files, "mod file"))
    if item.tray_names:
        parts.append(_tray_phrase(item.tray_names, item.tray_kinds))
    elif item.tray_files:
        parts.append(plural(item.tray_files, "tray file"))
    what = "Folder" if item.kind == "folder" else "Zip file"
    return f"{what} with {' and '.join(parts)}"


def _tray_phrase(names: list[str], kinds: list[str]) -> str:
    """'the household “Rivera”', 'the lot “Spa” and the room “Bath”', '3 households'."""
    kinds = (kinds + [""] * len(names))[:len(names)]
    if len(names) > 2:
        same = set(kinds)
        return plural(len(names), same.pop()) if len(same) == 1 and "" not in same else plural(len(names), "tray item")
    return " and ".join(f"the {k} “{n}”" if k else f"“{n}”" for n, k in zip(names, kinds))


def where_sims_folder_is() -> str:
    if platforms.WINDOWS or platforms.MACOS:
        return "It is usually Electronic Arts, The Sims 4 in your Documents."
    return ("With Steam and Proton it is inside your Steam library: steamapps/compatdata/1222670/pfx/drive_c/"
            "users/steamuser/Documents/Electronic Arts/The Sims 4.")


def save_warning_text(backed_up: bool) -> str:
    text = ("Don\u2019t save your usual households during the test. Without your own CC they lose hair, "
            "clothes and furniture.")
    if backed_up:
        text += " Sims 4 Mod Test keeps a copy of your saves from before the test, so you can put them back afterwards."
    else:
        text += " Your saves are not backed up (see Settings), so quit without saving."
    return text




# ---------------------------------------------------------------- small widgets

def label(text: str = "", role: str | None = None, wrap: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setTextFormat(Qt.PlainText)  # names come from downloads; never let Qt read them as HTML
    if role:
        lab.setProperty("role", role)
    lab.setWordWrap(wrap)
    return lab


def button(text: str, role: str | None = None) -> QPushButton:
    btn = QPushButton(text)
    if role:
        btn.setProperty("role", role)
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFocusPolicy(Qt.TabFocus)  # focus ring for keyboard users, not after every click
    return btn


def coffee_button() -> QPushButton:
    btn = button("Buy me a coffee", "coffee")
    btn.setIcon(QIcon(svg_pixmap(ICON_CUP, 16)))
    btn.setToolTip(f"Sims 4 Mod Test is free. If it helps you, you can support it: {SUPPORT_URL}")
    btn.setAccessibleName("Buy me a coffee (opens buymeacoffee.com)")
    btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SUPPORT_URL)))
    return btn


def restyle(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)
    for child in w.findChildren(QWidget):
        child.style().unpolish(child)
        child.style().polish(child)


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", role: str | None = None):
        super().__init__()
        self.setTextFormat(Qt.PlainText)
        if role:
            self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(60)
        self._full = ""
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self._elide()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(self._full, Qt.ElideMiddle, max(self.width(), 60)))


class Notice(QFrame):
    """A calm, coloured message box with an optional action button."""

    def __init__(self, tone: str = "warn"):
        super().__init__()
        self.setProperty("tone", tone)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 11, 12, 11)
        lay.setSpacing(12)
        self.text = label(wrap=True)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.text, 1)
        self.second = button("", "link")
        self.second.hide()
        lay.addWidget(self.second, 0, Qt.AlignVCenter)
        self.action = button("")
        self.action.hide()
        lay.addWidget(self.action, 0, Qt.AlignVCenter)
        self._handlers = [None, None]
        self.action.clicked.connect(lambda: self._handlers[0] and self._handlers[0]())
        self.second.clicked.connect(lambda: self._handlers[1] and self._handlers[1]())
        self.hide()

    def show_message(self, text: str, tone: str | None = None, action: str | None = None, handler=None,
                     second: str | None = None, second_handler=None) -> None:
        if tone and tone != self.property("tone"):
            self.setProperty("tone", tone)
            restyle(self)
        self.text.setText(text)
        for btn, caption in ((self.action, action), (self.second, second)):
            btn.setVisible(bool(caption))
            if caption:
                btn.setText(caption)
        self._handlers = [handler, second_handler]
        self.show()


def save_warning_notice() -> "Notice":
    notice = Notice("warn")
    notice.show_message(save_warning_text(True))
    return notice


class ItemRow(QFrame):
    removed = Signal(object)

    def __init__(self, item: core.ModItem, first: bool, removable: bool, remove_icon: QIcon):
        super().__init__()
        self.setObjectName("row")
        self.setProperty("first", "true" if first else "false")
        self.setToolTip(html.escape(item.path))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 10 if removable else 16, 10)
        lay.setSpacing(14)
        text = QVBoxLayout()
        text.setSpacing(1)
        name = ElidedLabel(item.title, "rowname")
        name.setToolTip(html.escape(item.title))
        text.addWidget(name)
        text.addWidget(label(describe(item), "muted"))
        for w in item.warnings:
            text.addWidget(label(w, "rowwarn", wrap=True))
        lay.addLayout(text, 1)
        size = label(fmt_size(item.size), "muted")
        size.setAlignment(Qt.AlignRight | Qt.AlignTop)
        lay.addWidget(size, 0, Qt.AlignTop)
        if removable:
            rm = button("", "icon")
            rm.setIcon(remove_icon)
            rm.setToolTip("Remove from this test")
            rm.setAccessibleName(f"Remove {item.title}")
            rm.clicked.connect(lambda: self.removed.emit(item))
            lay.addWidget(rm, 0, Qt.AlignTop)


class ItemList(QFrame):
    """The list of mods, with an empty state that doubles as the drop target."""
    removed = Signal(object)

    def __init__(self, removable: bool, empty_title: str, empty_hint: str):
        super().__init__()
        self.setObjectName("list")
        self.removable = removable
        self.remove_icon = QIcon()
        self.stack = QStackedLayout(self)

        empty_wrap = QWidget()
        ew = QVBoxLayout(empty_wrap)
        ew.setContentsMargins(12, 12, 12, 12)
        empty = QFrame()
        empty.setObjectName("empty")
        el = QVBoxLayout(empty)
        el.setAlignment(Qt.AlignCenter)
        el.setSpacing(4)
        self.empty_title = label(empty_title, "section")
        self.empty_title.setAlignment(Qt.AlignCenter)
        h = label(empty_hint, "muted", wrap=True)
        h.setAlignment(Qt.AlignCenter)
        el.addWidget(self.empty_title)
        el.addWidget(h)
        ew.addWidget(empty)
        self.stack.addWidget(empty_wrap)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.content = QWidget()
        self.content.setObjectName("listContent")
        self.rows = QVBoxLayout(self.content)
        self.rows.setContentsMargins(0, 2, 0, 2)
        self.rows.setSpacing(0)
        self.rows.addStretch(1)
        self.scroll.setWidget(self.content)
        self.stack.addWidget(self.scroll)

    def set_items(self, items: list[core.ModItem]) -> None:
        while self.rows.count() > 1:
            w = self.rows.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, item in enumerate(items):
            row = ItemRow(item, i == 0, self.removable, self.remove_icon)
            row.removed.connect(self.removed)
            self.rows.insertWidget(i, row)
        self.stack.setCurrentIndex(1 if items else 0)

    def set_dragging(self, on: bool) -> None:
        self.setProperty("drag", "true" if on else "false")
        restyle(self)


# ---------------------------------------------------------------- background work

class Worker(QThread):
    progress = Signal(int, int)
    failed = Signal(str)
    succeeded = Signal(object)

    def __init__(self, fn, *args, with_progress: bool = False):
        super().__init__()
        self.fn, self.args, self.with_progress = fn, args, with_progress

    def run(self) -> None:
        try:
            if self.with_progress:
                result = self.fn(*self.args, lambda d, t: self.progress.emit(d, t))
            else:
                result = self.fn(*self.args)
            self.succeeded.emit(result)
        except (core.TesterError, updates.CheckFailed) as e:  # expected: said to the user, not logged
            self.failed.emit(str(e))
        except Exception as e:  # unexpected: log it for a bug report, and still say what happened
            core.log_error(traceback.format_exc())
            self.failed.emit(f"Sims 4 Mod Test stopped because of an unexpected problem ({type(e).__name__}: {e}). "
                             "Open Sims 4 Mod Test again; it checks your folders when it starts.")


class GameWatcher(QThread):
    """Checks every two seconds whether the game runs, off the UI thread."""
    changed = Signal(bool, str)  # running, path of the game's exe ("" if unknown)

    def run(self) -> None:
        last_error = ""
        while not self.isInterruptionRequested():
            exe = ""
            try:
                procs = core.game_processes()
                for proc in procs:
                    try:
                        exe = proc.exe() or ""
                        break
                    except (psutil.Error, OSError):
                        continue  # no permission to see the path: still counts as running
                self.changed.emit(bool(procs), exe)
            except Exception as e:  # noqa: BLE001 - the watcher must keep running, or buttons stay disabled
                if repr(e) != last_error:
                    last_error = repr(e)
                    core.log_error(f"checking whether the game runs: {e!r}")
            for _ in range(20):
                if self.isInterruptionRequested():
                    return
                self.msleep(100)


# ---------------------------------------------------------------- pages

class TestSetupPage(QWidget):
    def __init__(self):
        super().__init__()
        self.items: list[core.ModItem] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.addWidget(label("Mods to test", "section"))
        head.addStretch(1)
        self.summary = label("", "muted")
        head.addWidget(self.summary)
        lay.addLayout(head)

        self.list = ItemList(True, "Drag mods or downloaded Sims here",
                             "Packages, script mods, tray files, folders and .zip files")
        self.list.removed.connect(self.remove_item)
        lay.addWidget(self.list, 1)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.add_files_btn = button("Add files")
        self.add_folder_btn = button("Add a folder")
        self.clear_btn = button("Clear list", "link")
        self.clear_btn.clicked.connect(lambda: self.set_items([]))
        tools.addWidget(self.add_files_btn)
        tools.addWidget(self.add_folder_btn)
        tools.addStretch(1)
        tools.addWidget(self.clear_btn)
        lay.addLayout(tools)

        self.notice = Notice("warn")
        lay.addWidget(self.notice)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        lay.addWidget(self.progress)

        bottom = QHBoxLayout()
        self.status = label("", "muted", wrap=True)
        bottom.addWidget(self.status, 1)
        self.start_btn = button("Start test", "primary")
        bottom.addWidget(self.start_btn, 0, Qt.AlignRight)
        lay.addLayout(bottom)

    def set_items(self, items: list[core.ModItem]) -> None:
        self.items = items
        self.list.set_items(items)
        self.clear_btn.setVisible(bool(items))
        if items:
            self.summary.setText(f"{plural(len(items), 'item')}, {fmt_size(sum(i.size for i in items))}")
            self.start_btn.setText(f"Start test with {plural(len(items), 'item')}")
        else:
            self.summary.setText("")
            self.start_btn.setText("Start test")

    def remove_item(self, item: core.ModItem) -> None:
        self.set_items([i for i in self.items if i is not item])


class SearchSetupPage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(label("Find a broken mod", "section"))
        lay.addWidget(label(
            "Something wrong in your game, like errors, odd heads or a missing menu? Sims 4 Mod Test switches "
            "half of your mods off. You play, close the game and say whether the problem is still there. "
            "Then it halves again, until one mod is left.", "muted", wrap=True))
        self.count = label("", wrap=True)
        lay.addWidget(self.count)
        self.save_warning = save_warning_notice()
        lay.addWidget(self.save_warning)
        self.notice = Notice("error")
        lay.addWidget(self.notice)
        lay.addStretch(1)
        bottom = QHBoxLayout()
        self.status = label("", "muted", wrap=True)
        bottom.addWidget(self.status, 1)
        self.start_btn = button("Start search", "primary")
        bottom.addWidget(self.start_btn, 0, Qt.AlignRight)
        lay.addLayout(bottom)


class TestingPage(QWidget):
    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.heading = label("", "heading")
        lay.addWidget(self.heading)
        self.body = label("", "muted", wrap=True)
        lay.addWidget(self.body)
        self.save_warning = save_warning_notice()
        lay.addWidget(self.save_warning)
        self.errors = Notice("warn")
        lay.addWidget(self.errors)

        self.list = ItemList(False, "This test’s list was not saved",
                             "The test mods are in the Mods folder.")
        lay.addWidget(self.list, 1)

        self.notice = Notice("error")
        lay.addWidget(self.notice)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.hide()
        lay.addWidget(self.progress)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.play_btn = button("Start The Sims 4")
        self.open_btn = button("Open Mods folder")
        bottom.addWidget(self.play_btn)
        bottom.addWidget(self.open_btn)
        self.status = label("", "muted", wrap=True)
        bottom.addWidget(self.status, 1)
        self.restore_btn = button("Restore my mods", "primary")
        bottom.addWidget(self.restore_btn, 0, Qt.AlignRight)
        lay.addLayout(bottom)


class SearchPage(QWidget):
    """A search round, or the result once one mod is left."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.heading = label("", "heading")
        lay.addWidget(self.heading)
        self.body = label("", "muted", wrap=True)
        lay.addWidget(self.body)

        self.found = QFrame()
        self.found.setObjectName("card")
        fl = QVBoxLayout(self.found)
        fl.setContentsMargins(16, 14, 16, 14)
        fl.setSpacing(2)
        self.found_name = ElidedLabel("", "rowname")
        self.found_where = label("", "muted", wrap=True)
        fl.addWidget(self.found_name)
        fl.addWidget(self.found_where)
        lay.addWidget(self.found)

        self.save_warning = save_warning_notice()
        lay.addWidget(self.save_warning)
        self.errors = Notice("warn")
        lay.addWidget(self.errors)
        self.notice = Notice("error")
        lay.addWidget(self.notice)

        self.answers = QWidget()
        al = QVBoxLayout(self.answers)
        al.setContentsMargins(0, 4, 0, 0)
        al.setSpacing(8)
        al.addWidget(label("After playing, close the game and answer:", "section"))
        row = QHBoxLayout()
        row.setSpacing(10)
        self.broken_btn = button("The problem is still there", "answer")
        self.fine_btn = button("The problem is gone", "answer")
        row.addWidget(self.broken_btn, 1)
        row.addWidget(self.fine_btn, 1)
        al.addLayout(row)
        lay.addWidget(self.answers)
        lay.addStretch(1)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.hide()
        lay.addWidget(self.progress)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.play_btn = button("Start The Sims 4")
        bottom.addWidget(self.play_btn)
        self.status = label("", "muted", wrap=True)
        bottom.addWidget(self.status, 1)
        self.stop_btn = button("Stop and restore my mods", "link")
        self.keep_btn = button("Restore and keep it")
        self.remove_btn = button("Restore without it", "primary")
        bottom.addWidget(self.stop_btn, 0, Qt.AlignVCenter)
        bottom.addWidget(self.keep_btn)
        bottom.addWidget(self.remove_btn)
        lay.addLayout(bottom)


class SettingsPage(QWidget):
    """Folders, appearance, what happens around a test, updates, and about."""

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("listContent")
        lay = QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(8)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        self.notice = Notice("warn")
        lay.addWidget(self.notice)

        lay.addWidget(label("Folders", "section"))
        folders = self._card(lay)
        self.sims_path, self.change_sims_btn = self._folder_row(
            folders, "Sims 4 folder, where your Mods, Tray and saves are", "Change the Sims 4 folder")
        self.game_path, self.change_game_btn = self._folder_row(
            folders, "Game folder, where The Sims 4 is installed", "Change the game folder")
        lay.addSpacing(10)

        lay.addWidget(label("Appearance", "section"))
        seg = QFrame()
        seg.setObjectName("segments")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.appearance = QButtonGroup(self)
        for i, text in enumerate(("Match system", "Light", "Dark")):
            b = button(text, "segment")
            b.setCheckable(True)
            self.appearance.addButton(b, i)
            sl.addWidget(b)
        row = QHBoxLayout()
        row.addWidget(seg)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addSpacing(10)

        lay.addWidget(label("During a test", "section"))
        test_card = self._card(lay)
        self.backup_saves = self._toggle(
            test_card, "Back up my saves first",
            "If the game saves over one of your saves during a test, you can put the old one back. "
            "Turn this off if your saves are very large.")
        self.clear_cache = self._toggle(
            test_card, "Clear the game’s cache files",
            "Before and after each test, so new CC shows the right pictures and script mods start fresh. "
            "The game rebuilds them.")
        self.auto_start = self._toggle(
            test_card, "Start The Sims 4 when a test is ready", "Also for each round of a broken-mod search.")
        lay.addSpacing(10)

        lay.addWidget(label("Updates", "section"))
        upd = self._card(lay)
        self.check_updates = self._toggle(upd, "Look for a new version once a day",
                                          "Only asks GitHub for the latest version number. Nothing installs by itself.")
        urow = QHBoxLayout()
        urow.setContentsMargins(16, 4, 16, 12)
        self.version_label = label(f"You have version {__version__}.", "muted")
        urow.addWidget(self.version_label, 1)
        self.check_now_btn = button("Check now")
        urow.addWidget(self.check_now_btn)
        upd.addLayout(urow)
        lay.addSpacing(10)

        lay.addWidget(label("About", "section"))
        about = self._card(lay)
        text = label("Sims 4 Mod Test is free and open source (MIT license), and includes other open source "
                     "parts under their own licenses. It is a fan-made tool, not made by or affiliated with "
                     "Electronic Arts or Maxis.", "muted", wrap=True)
        text.setContentsMargins(16, 12, 16, 4)
        about.addWidget(text)
        arow = QHBoxLayout()
        arow.setContentsMargins(16, 4, 16, 12)
        arow.setSpacing(8)
        self.project_btn = button("Project page")
        self.data_btn = button("Open the app’s data folder")
        self.data_btn.setToolTip("Save backups and the state of a running test live here.")
        self.licenses_btn = button("Licenses")
        arow.addWidget(self.project_btn)
        arow.addWidget(self.data_btn)
        arow.addWidget(self.licenses_btn)
        arow.addStretch(1)
        about.addLayout(arow)
        lay.addStretch(1)

    @staticmethod
    def _card(parent: QVBoxLayout) -> QVBoxLayout:
        card = QFrame()
        card.setObjectName("card")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(0, 4, 0, 4)
        inner.setSpacing(0)
        parent.addWidget(card)
        return inner

    @staticmethod
    def _folder_row(card: QVBoxLayout, title: str, accessible: str) -> tuple[ElidedLabel, QPushButton]:
        row = QHBoxLayout()
        row.setContentsMargins(16, 10, 12, 10)
        row.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(title, "rowname"))
        path = ElidedLabel("", "muted")
        text.addWidget(path)
        row.addLayout(text, 1)
        change = button("Change")
        change.setAccessibleName(accessible)  # starts with the visible "Change"
        row.addWidget(change, 0, Qt.AlignVCenter)
        card.addLayout(row)
        return path, change

    @staticmethod
    def _toggle(card: QVBoxLayout, title: str, hint: str) -> QCheckBox:
        box = QVBoxLayout()
        box.setContentsMargins(16, 10, 16, 10)
        box.setSpacing(2)
        check = QCheckBox(title)
        check.setFocusPolicy(Qt.TabFocus)
        box.addWidget(check)
        h = label(hint, "muted", wrap=True)
        h.setContentsMargins(26, 0, 0, 0)  # under the text, not the box
        box.addWidget(h)
        card.addLayout(box)
        return check


# ---------------------------------------------------------------- window

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("root")
        self.setWindowTitle(APP_NAME)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.resize(640, 720)
        self.setMinimumSize(500, 580)
        self.settings = QSettings("Sims 4 Mod Test", "Sims 4 Mod Test")
        self.migrate_old_settings()
        self.sims_dir: Path | None = None
        self.worker: Worker | None = None
        self.side_jobs: list[Worker] = []
        self.game_on = False
        self.test_started = 0.0
        self.state: dict | None = None
        self.reports: list[Path] = []
        self.game_keys: frozenset[int] | None = None
        self.closing = False  # set when the window closes: no new background work after that
        self.deferred: list[tuple] = []  # readers waiting for a folder move to finish
        self.mod_count: int | None = None  # mods in the Mods folder (for the search), None while unknown
        self.risk_cache: dict[tuple, list[str]] = {}     # (path, size, mtime, with game index) -> warnings
        self.suspect_cache: dict[tuple, list[str]] = {}  # (report, mtime) -> mods it mentions

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.addWidget(label(APP_NAME, "title"))
        title_row.addStretch(1)
        title_row.addWidget(coffee_button(), 0, Qt.AlignVCenter)
        lay.addLayout(title_row)
        lay.addSpacing(14)

        self.prefs = SettingsPage()
        p = self.prefs
        self.folder_label, self.change_btn = p.sims_path, p.change_sims_btn
        self.game_label, self.change_game_btn = p.game_path, p.change_game_btn
        self.change_btn.clicked.connect(self.choose_sims_dir)
        self.change_game_btn.clicked.connect(self.choose_game_dir)
        self.bind_toggle(p.backup_saves, "backup_saves")
        self.bind_toggle(p.clear_cache, "clear_cache")
        self.bind_toggle(p.auto_start, "auto_start_game")
        self.bind_toggle(p.check_updates, "check_updates")
        p.check_now_btn.clicked.connect(lambda: self.check_for_update(manual=True))
        p.project_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"https://github.com/{updates.REPO}")))
        p.data_btn.clicked.connect(lambda: self.open_path(core.DATA_DIR))
        p.licenses_btn.clicked.connect(self.open_licenses)
        choice = self.settings.value("appearance", "system", type=str)
        p.appearance.button({"system": 0, "light": 1, "dark": 2}.get(choice, 0)).setChecked(True)
        p.appearance.idClicked.connect(self.appearance_changed)
        self.set_appearance(choice)

        self.segments = QFrame()
        self.segments.setObjectName("segments")
        sl = QHBoxLayout(self.segments)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.mode_group = QButtonGroup(self)
        for i, text in enumerate(("Test new mods", "Find a broken mod", "Settings")):
            b = button(text, "segment")
            b.setCheckable(True)
            self.mode_group.addButton(b, i)
            sl.addWidget(b)
        self.mode_group.button(0).setChecked(True)
        self.mode_group.idClicked.connect(self.mode_changed)
        seg_row = QHBoxLayout()
        seg_row.addWidget(self.segments)
        seg_row.addStretch(1)
        lay.addLayout(seg_row)
        lay.addSpacing(10)

        self.update_notice = Notice("ok")
        lay.addWidget(self.update_notice)
        self.after = Notice("ok")  # results of a restore; stays until the next action
        lay.addWidget(self.after)
        self.saves_notice = Notice("warn")
        lay.addWidget(self.saves_notice)
        self.game_settings_notice = Notice("warn")
        lay.addWidget(self.game_settings_notice)
        lay.addSpacing(4)

        self.setup = TestSetupPage()
        self.search_setup = SearchSetupPage()
        self.testing = TestingPage()
        self.search = SearchPage()
        self.pages = QStackedWidget()
        for page in (self.setup, self.search_setup, self.testing, self.search, self.prefs):
            self.pages.addWidget(page)
        lay.addWidget(self.pages, 1)

        self.setup.add_files_btn.clicked.connect(self.pick_files)
        self.setup.add_folder_btn.clicked.connect(self.pick_folder)
        self.setup.start_btn.clicked.connect(self.start_test)
        self.search_setup.start_btn.clicked.connect(self.start_search)
        self.testing.restore_btn.clicked.connect(lambda: self.end_test(False))
        self.testing.open_btn.clicked.connect(lambda: self.open_path(self.sims_dir / "Mods"))
        self.testing.play_btn.clicked.connect(self.play)
        self.search.play_btn.clicked.connect(self.play)
        self.search.broken_btn.clicked.connect(lambda: self.answer(True))
        self.search.fine_btn.clicked.connect(lambda: self.answer(False))
        self.search.stop_btn.clicked.connect(lambda: self.end_test(False))
        self.search.keep_btn.clicked.connect(lambda: self.end_test(False))
        self.search.remove_btn.clicked.connect(lambda: self.end_test(True))
        for page in (self.testing, self.search):
            page.errors.action.setText("Open report")

        self.apply_theme()
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _: self.system_scheme_changed())

        self.watcher = GameWatcher(self)
        self.watcher.changed.connect(self.game_changed)
        self.watcher.start()
        self.timer = QTimer(self)
        self.timer.setInterval(REPORT_CHECK_MS)
        self.timer.timeout.connect(self.check_reports)
        self.timer.start()

        self.set_sims_dir(self.initial_sims_dir())
        self.show_game_dir()
        self.load_game_index()
        QTimer.singleShot(UPDATE_CHECK_DELAY_MS, self.check_for_update)

    # -- theme

    def apply_theme(self) -> None:
        t = current_theme()
        QApplication.instance().setStyleSheet(build_qss(t))
        icon = QIcon(svg_pixmap(ICON_REMOVE.format(c=t["muted"]), 16))
        for lst in (self.setup.list, self.testing.list):
            lst.remove_icon = icon
        self.setup.set_items(self.setup.items)

    # -- Sims folder and game

    def initial_sims_dir(self) -> Path | None:
        saved = self.settings.value("sims_dir", "", type=str)
        if saved and core.looks_like_sims_dir(Path(saved)):
            return Path(saved)
        docs = Path(QStandardPaths.writableLocation(QStandardPaths.DocumentsLocation))
        found = core.find_sims_dirs(platforms.documents_folders(docs))
        return found[0] if found else None

    def set_sims_dir(self, path: Path | None) -> None:
        self.sims_dir = path
        if path is None:
            self.folder_label.set_full_text("Not found. Pick the folder that holds Mods and Tray.")
            self.show_current_page()
            self.setup.notice.show_message(
                "Sims 4 Mod Test could not find your Sims 4 folder. If you have never started The Sims 4 on this "
                "computer, start it once and open Sims 4 Mod Test again. Otherwise pick the folder that holds "
                "Mods and Tray in Settings. " + where_sims_folder_is(), "warn",
                "Open Settings", lambda: self.open_tab(2))
            return
        self.prefs.notice.hide()
        self.settings.setValue("sims_dir", str(path))
        self.folder_label.set_full_text(str(path))
        self.setup.notice.hide()
        try:
            core.recover(path)
        except (OSError, core.TesterError) as e:
            self.after.show_message(
                f"Sims 4 Mod Test found an unfinished swap and could not tidy it up: {e} "
                "Close other programs and open Sims 4 Mod Test again.", "error")
        self.show_current_page()
        self.count_mods()
        if not core.in_test(path):
            self.offer_saves(core.pending_saves(path))

    def choose_sims_dir(self) -> None:
        start = str(self.sims_dir or Path.home())
        picked = QFileDialog.getExistingDirectory(self, "Choose your Sims 4 folder", start)
        if not picked:
            return
        path = Path(picked)
        if path.name.lower() in ("mods", "tray") and core.looks_like_sims_dir(path.parent):
            path = path.parent
        if not core.looks_like_sims_dir(path):
            self.pages.currentWidget().notice.show_message(
                f"“{path.name}” doesn’t look like a Sims 4 folder. Pick the folder that holds "
                "Mods and Tray.", "warn")
            return
        self.set_sims_dir(path)

    def migrate_old_settings(self) -> None:
        """Bring over what the app remembered under its old name (Mod Tester): the chosen Sims 4
        folder above all, since a test may be running there."""
        if self.settings.value("migrated", False, type=bool):
            return
        old = QSettings("Mod Tester", "Mod Tester")
        for key in ("sims_dir", "last_pick"):
            if old.value(key) and not self.settings.value(key):
                self.settings.setValue(key, old.value(key))
        exe = old.value("game_exe", "", type=str)
        learned = platforms.game_dir_from_process(exe) if exe else None
        if learned and not self.settings.value("game_dir"):
            self.settings.setValue("game_dir", str(learned))
        self.settings.setValue("migrated", True)

    def game_dir(self) -> Path | None:
        """The game folder the user picked, else one found in the usual places."""
        saved = self.settings.value("game_dir", "", type=str)
        if saved and platforms.game_content_root(Path(saved)):
            return Path(saved)
        return platforms.find_game_dir()

    def set_game_dir(self, path: Path) -> None:
        self.prefs.notice.hide()
        self.settings.setValue("game_dir", str(path))
        self.show_game_dir()
        self.load_game_index()

    def show_game_dir(self) -> None:
        gd = self.game_dir()
        self.game_label.set_full_text(str(gd) if gd else "Not found. Pick it to start the game from here.")

    def choose_game_dir(self) -> None:
        start = str(self.game_dir() or Path.home())
        # The Mac's own dialog won't pick "The Sims 4.app" as a folder (it's an app bundle); Qt's will.
        options = QFileDialog.Option.DontUseNativeDialog if platforms.MACOS else QFileDialog.Option(0)
        picked = QFileDialog.getExistingDirectory(self, "Choose where The Sims 4 is installed", start, options)
        if not picked:
            return
        path = Path(picked)
        for candidate in (path, *path.parents[:3]):  # also accept Game\Bin or Data picked by mistake
            if platforms.game_content_root(candidate):
                self.set_game_dir(candidate)
                return
        self.pages.currentWidget().notice.show_message(
            f"“{path.name}” doesn’t look like the game’s folder. Pick the folder (or on a Mac, "
            "the app) The Sims 4 is installed in. It holds Data and Game.", "warn")

    def game_changed(self, running: bool, exe: str) -> None:
        learned = platforms.game_dir_from_process(exe) if exe else None
        if learned and platforms.game_content_root(learned) and learned != self.game_dir():
            self.set_game_dir(learned)  # learned from the running game
        if running != self.game_on:
            self.game_on = running
            self.refresh()
            if not running:
                self.check_game_settings()  # the game writes its options when it closes

    def play(self, interactive: bool = True) -> None:
        gd = self.game_dir()
        page = self.pages.currentWidget()
        if gd is None and (platforms.WINDOWS or platforms.MACOS):
            if not interactive:  # starting by itself must never pop up a dialog
                page.status.setText("Pick the game folder in Settings to start the game from here.")
                return
            self.choose_game_dir()
            gd = self.game_dir()
            if gd is None:
                return
        if not platforms.launch_game(gd):
            page.notice.show_message("The Sims 4 did not start. Start it the usual way, or pick the game "
                                     "folder in Settings.", "error")
            return
        page.status.setText("Starting The Sims 4")

    # -- settings

    OPTIONS = {"backup_saves": True, "clear_cache": True, "auto_start_game": False, "check_updates": True}

    def opt(self, key: str) -> bool:
        return self.settings.value(key, self.OPTIONS[key], type=bool)

    def bind_toggle(self, box: QCheckBox, key: str) -> None:
        box.setChecked(self.opt(key))
        box.toggled.connect(lambda on: self.settings.setValue(key, on))

    def set_appearance(self, choice: str) -> None:
        """Light, dark or the system's: Qt switches its own colours (menus, dialogs, title bar) too."""
        global _appearance
        _appearance = choice
        scheme = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}.get(choice, Qt.ColorScheme.Unknown)
        QGuiApplication.styleHints().setColorScheme(scheme)

    def appearance_changed(self, index: int) -> None:
        choice = ("system", "light", "dark")[index]
        button = self.prefs.appearance.button(index)
        if not button.isChecked():
            button.setChecked(True)  # when called from code rather than a click
        self.settings.setValue("appearance", choice)
        self.set_appearance(choice)
        self.apply_theme()

    def system_scheme_changed(self) -> None:
        if _appearance == "system":  # a chosen Light/Dark is already applied
            self.apply_theme()

    def open_tab(self, index: int) -> None:
        self.mode_group.button(index).setChecked(True)
        self.mode_changed(index)

    def auto_start_game(self) -> None:
        if self.opt("auto_start_game") and not self.game_on:
            self.play(interactive=False)

    def check_for_update(self, manual: bool = False) -> None:
        """Once a day: is there a newer version on GitHub? Offered calmly; nothing is installed.
        `manual` is the Check now button: it ignores the daily limit and "Not now"."""
        today = time.strftime("%Y-%m-%d")
        if not manual:
            if not self.opt("check_updates") or self.settings.value("update_checked", "", type=str) == today:
                return
        skipped = "" if manual else self.settings.value("update_skipped", "", type=str)
        if manual:
            self.prefs.version_label.setText("Looking for a new version")
            self.prefs.check_now_btn.setEnabled(False)

        def done(release):
            self.settings.setValue("update_checked", today)  # only once GitHub answered
            if manual:
                self.prefs.check_now_btn.setEnabled(True)
                self.prefs.version_label.setText(
                    f"You have version {__version__}." + ("" if release else " It is the latest one."))
            if release is None:
                return
            show(release)

        def failed(_msg: str):
            if manual:
                self.prefs.check_now_btn.setEnabled(True)
                self.prefs.version_label.setText(f"You have version {__version__}. GitHub couldn’t be "
                                                 "reached, so try again later.")

        def show(release):

            def not_now():
                self.settings.setValue("update_skipped", release.version)
                self.update_notice.hide()

            self.update_notice.show_message(
                f"Sims 4 Mod Test {release.version} is out. You have {__version__}.", "ok",
                "Download", lambda: QDesktopServices.openUrl(QUrl(release.download)), "Not now", not_now)

        self.run_side(Worker(updates.find_update, skipped), done, on_fail=failed)

    def load_game_index(self) -> None:
        """Read the game's own CAS parts and sliders in the background, for the override check."""
        gd = self.game_dir()
        if gd is None or getattr(self, "_index_for", None) == gd:
            return
        self._index_for = gd
        self.game_keys = None  # until this game's keys are read, nothing is checked against the old ones

        def done(keys):
            if keys is None or gd != self._index_for:
                return  # stopped (closing), or another game folder was picked meanwhile
            self.game_keys, self._keys_for = keys, gd
            self.check_items()

        def build():
            return risks.game_index(gd, stop=QThread.currentThread().isInterruptionRequested)

        def failed(msg: str):
            core.log_error(f"reading the game's own files in {gd}: {msg}")

        self.run_side(Worker(build), done, on_fail=failed)

    # -- pages

    def mode_changed(self, _id: int) -> None:
        self.after.hide()
        self.prefs.notice.hide()
        self.show_current_page()

    def show_current_page(self) -> None:
        sims = self.sims_dir
        running = bool(sims and core.in_test(sims))
        self.state = core.load_state(sims) if running else None
        self.segments.setVisible(not running)
        if running and self.state and self.state.get("mode") == "search":
            self.show_search_round()
            self.pages.setCurrentWidget(self.search)
        elif running:
            items = self.state["items"] if self.state else []
            self.test_started = self.state["started"] if self.state else _ctime(sims / "Mods")
            t = self.testing
            t.heading.setText(f"Testing {plural(len(items), 'item')}" if items else "A test is running")
            t.list.set_items(items)
            t.notice.hide()
            if core.tray_in_test(sims):
                t.body.setText("Your own mods and Tray are set aside, untouched. The library in the game shows only "
                               "the test’s households and lots. When you are done, close the game and restore here.")
            else:
                t.body.setText("Your own mods are set aside, untouched. Start The Sims 4 and try the test mods. "
                               "When you are done, close the game and restore your mods here.")
            self.pages.setCurrentWidget(self.testing)
            if not self.setup.items:
                self.setup.set_items(items)  # ready for the next round after restoring
        elif self.mode_group.checkedId() == 1:
            self.pages.setCurrentWidget(self.search_setup)
        elif self.mode_group.checkedId() == 2:
            self.pages.setCurrentWidget(self.prefs)
        else:
            self.pages.setCurrentWidget(self.setup)
        self.search_setup.save_warning.text.setText(save_warning_text(self.opt("backup_saves")))
        backed_up = bool(self.state and self.state.get("saves"))  # what this test really did
        for page in (self.testing, self.search):
            page.save_warning.text.setText(save_warning_text(backed_up))
        self.setFocus()  # don't leave keyboard focus on a button that was just rebuilt or hidden
        self.check_game_settings()
        self.check_reports()
        self.refresh()

    def show_search_round(self) -> None:
        s, st = self.search, self.state
        self.test_started = st["started"]
        units, candidates = st["units"], st["candidates"]
        found, not_mods = st.get("found"), st.get("not_mods")
        done = found is not None or not_mods
        s.notice.hide()
        s.found.setVisible(found is not None)
        s.answers.setVisible(not done)
        s.save_warning.setVisible(not done)
        s.stop_btn.setVisible(not done)
        s.play_btn.setVisible(not done)
        s.keep_btn.setVisible(done)
        s.keep_btn.setText("Restore my mods" if not_mods else "Restore and keep it")
        s.remove_btn.setVisible(found is not None)
        if not_mods:
            s.heading.setText("It isn\u2019t a mod")
            s.body.setText("The problem is there even with all of your mods switched off, so no mod causes it. "
                           "It can come from a household or lot in your Tray, or from the game itself. Restore "
                           "your mods, then repair the game: in the EA app choose Repair for The Sims 4; on "
                           "Steam use Properties, Installed Files, Verify integrity.")
            return
        if found is not None:
            title, where = core.unit_label(units[found])
            s.heading.setText("Found it")
            s.body.setText("This is most likely the mod that brings the problem back. Restore without it to move "
                           f"it into \u201c{core.REMOVED_NAME}\u201d next to Mods, so nothing is lost. Then look "
                           "for a newer version from its creator.")
            s.found_name.set_full_text(title)
            s.found_where.setText(where[0].upper() + where[1:])
            return
        if st["round"] == 0:
            s.heading.setText("First, a round with all mods off")
            s.body.setText("All of your mods are switched off. Start the game and do exactly what caused the "
                           "problem. If it is gone, a mod causes it and the search goes on.")
            return
        total = st["round"] + core.rounds_left(len(candidates)) - 1
        s.heading.setText(f"Round {st['round']} of about {total}")
        on = sum(len(units[i]) for i in st["testing"])
        s.body.setText(f"{on:,} of your mod files are switched on, the rest are off. "
                       f"{plural(len(candidates), 'mod')} could still be the broken one. Start the game and "
                       "do exactly what caused the problem. If it doesn\u2019t show up right away, play a "
                       "little longer before you answer: one wrong answer sends the search the wrong way.")

    def count_mods(self) -> None:
        sims = self.sims_dir
        if not sims or core.in_test(sims) or not (sims / "Mods").is_dir():
            self.mod_count = 0 if sims and not (sims / "Mods").is_dir() else None
            self.search_setup.count.setText("")
            return

        def done(units):
            if sims != self.sims_dir:
                return  # the user picked another folder meanwhile
            n = len(units)
            self.mod_count = n
            self.refresh()
            self.search_setup.count.setText(
                f"Your Mods folder has {plural(n, 'mod')}. Finding one takes about "
                f"{plural(core.rounds_left(n), 'round')}." if n > 1 else
                "A search needs at least two mods in your Mods folder.")

        self.run_side(Worker(core.mod_units, sims / "Mods"), done, touches_sims=True)

    def busy(self) -> bool:
        return self.worker is not None

    def check_game_settings(self) -> None:
        """Game updates switch off custom content and script mods; a test with them off shows nothing."""
        mods_on, scripts_on = core.game_mod_settings(self.sims_dir) if self.sims_dir else (None, None)
        where = "in the game, under Game Options, Other"
        if mods_on is False:
            self.game_settings_notice.show_message(
                f"Custom content is switched off in the game, so no mods will load. Turn on \u201cEnable Custom "
                f"Content and Mods\u201d {where}, then restart the game.")
        elif scripts_on is False:
            self.game_settings_notice.show_message(
                f"Script mods are switched off in the game. Turn on \u201cScript Mods Allowed\u201d {where}, "
                "then restart the game.")
        else:
            self.game_settings_notice.hide()

    def check_reports(self) -> None:
        page = self.pages.currentWidget()
        if page not in (self.testing, self.search) or not self.sims_dir:
            return
        self.reports = core.new_error_reports(self.sims_dir, self.test_started)
        if not self.reports:
            page.errors.hide()
            return
        n = len(self.reports)
        text = ("The game wrote an error report during this test." if n == 1 else
                f"The game wrote {n} error reports during this test.")
        names = [i.name for i in (self.state or {}).get("items", [])]
        key = (str(self.reports[0]), core.mtime(self.reports[0]))
        if key not in self.suspect_cache:
            suspects = risks.report_suspects(self.reports[0], names)
            note = ""
            if suspects and suspects[0].lower().endswith(".ts4script"):
                # the game only loads scripts from Mods or one folder below it, so that's all to look at
                mods, name = self.sims_dir / "Mods", core.glob_escape(suspects[0])
                found = next(iter([*mods.glob(name), *mods.glob(f"*/{name}")]), None)
                if found:
                    note = risks.outdated_note(found, risks.last_update(self.game_dir(), self.sims_dir))
            self.suspect_cache[key] = (suspects, note)
        suspects, note = self.suspect_cache[key]
        if suspects:
            text += " It mentions " + " and ".join(f"\u201c{s}\u201d" for s in suspects[:2]) + "." + note
            if page is self.testing:
                text += " Restore your mods, then remove or update that mod before you test again."
        elif page is self.testing:
            text += " One of the test mods may be broken or outdated."
        page.errors.show_message(text, action="Open report", handler=lambda: self.open_path(self.reports[0]))

    def refresh(self) -> None:
        busy = self.busy()
        game = self.game_on
        s = self.setup
        has_dir = self.sims_dir is not None
        for w in (s.add_files_btn, s.add_folder_btn, s.clear_btn, self.change_btn, self.change_game_btn):
            w.setEnabled(not busy)
        for b in self.mode_group.buttons():
            b.setEnabled(not busy)
        s.list.setEnabled(not busy)
        s.start_btn.setEnabled(has_dir and bool(s.items) and not game and not busy)
        if not busy:
            s.status.setText("Pick your Sims 4 folder in Settings first." if not has_dir else
                             "Close The Sims 4 to start a test." if game else
                             "Your own mods are set aside, not changed." if s.items else "")

        ss = self.search_setup
        enough = self.mod_count is None or self.mod_count >= 2  # None: still counting
        ss.start_btn.setEnabled(has_dir and enough and not game and not busy)
        if not busy:
            ss.status.setText("Pick your Sims 4 folder in Settings first." if not has_dir else
                              "Close The Sims 4 to start a search." if game else "")

        t = self.testing
        t.restore_btn.setEnabled(not game and not busy)
        t.open_btn.setEnabled(not busy)
        t.play_btn.setEnabled(not game and not busy)
        if not busy:
            t.status.setText("Close the game to restore your mods." if game else "")

        se = self.search
        for b in (se.broken_btn, se.fine_btn, se.keep_btn, se.remove_btn, se.stop_btn):
            b.setEnabled(not game and not busy)
        se.play_btn.setEnabled(not game and not busy)
        if not busy:
            se.status.setText("Close the game to answer." if game else "")
        for n in self.findChildren(Notice):
            n.action.setEnabled(not busy)
            n.second.setEnabled(not busy)

    # -- adding mods

    def pick_files(self) -> None:
        start = self.settings.value("last_pick", str(Path.home() / "Downloads"), type=str)
        exts = " ".join(f"*{e}" for e in sorted(core.TRAY_EXTENSIONS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Choose mods to test", start,
            f"Mods and tray files (*.package *.ts4script *.zip {exts});;All files (*)")
        if files:
            self.settings.setValue("last_pick", str(Path(files[0]).parent))
            self.add_paths([Path(f) for f in files])

    def pick_folder(self) -> None:
        start = self.settings.value("last_pick", str(Path.home() / "Downloads"), type=str)
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder of mods to test", start)
        if folder:
            self.settings.setValue("last_pick", str(Path(folder).parent))
            self.add_paths([Path(folder)])

    def add_paths(self, paths: list[Path]) -> None:
        if self.busy():
            return
        s = self.setup
        s.notice.hide()
        self.after.hide()
        s.status.setText(f"Reading {plural(len(paths), 'item')}")
        s.progress.setRange(0, 0)
        s.progress.show()

        def ok(result):
            s.progress.hide()
            new, problems = result
            items = list(s.items)
            known = {os.path.normcase(i.path) for i in items}
            for item in new:
                if os.path.normcase(item.path) not in known:
                    known.add(os.path.normcase(item.path))
                    items.append(item)
            s.set_items(items)
            if problems:
                text = problems[0]
                if len(problems) > 1:
                    text += (f" {plural(len(problems) - 1, 'other item')} "
                             f"{'was' if len(problems) == 2 else 'were'} skipped too.")
                s.notice.show_message(text, "warn")
            self.check_items()

        def fail(msg: str):
            s.progress.hide()
            s.notice.show_message(msg, "error")

        reader = risks.package_keys if self.game_keys is not None else None  # else checked later, interruptibly
        self.run_job(Worker(core.inspect_paths, paths, self.sims_dir, reader), ok, fail)

    def check_items(self) -> None:
        """Look for files that replace the game's own sliders or CAS items, in the background.
        Needs the game's own keys; until they're read there's nothing to compare with."""
        if self.game_keys is None:
            return

        keys_for = self._keys_for  # the game these keys belong to, fixed for this run

        def key(i: core.ModItem) -> tuple:
            return (os.path.normcase(i.path), i.size, core.mtime(Path(i.path)), str(keys_for))

        todo = []
        for i in self.setup.items:
            if key(i) in self.risk_cache:
                i.warnings = self.risk_cache[key(i)]
            else:
                todo.append(i)
        self.setup.set_items(self.setup.items)
        if not todo:
            return
        keys = self.game_keys

        def run():
            results = []
            for i in todo:
                if QThread.currentThread().isInterruptionRequested():
                    break  # a test is about to start; unchecked items are checked next time
                results.append((i, key(i), risks.check(i, keys)))
            return results

        def done(results):
            if keys_for != self._keys_for:
                return  # another game folder was picked meanwhile; its own check follows
            current = {id(i) for i in self.setup.items}
            for item, k, warnings in results:
                self.risk_cache[k] = warnings
                if id(item) in current:
                    item.warnings = warnings
            self.setup.set_items(self.setup.items)

        self.run_side(Worker(run), done, touches_sims=True)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls() and self.pages.currentWidget() is self.setup and not self.busy():
            e.acceptProposedAction()
            self.setup.list.set_dragging(True)

    def dragLeaveEvent(self, e) -> None:
        self.setup.list.set_dragging(False)

    def dropEvent(self, e) -> None:
        self.setup.list.set_dragging(False)
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            e.acceptProposedAction()
            self.add_paths(paths)

    # -- jobs

    def run_job(self, worker: Worker, on_ok, on_fail) -> None:
        """A job that changes folders: everything else waits for it."""
        if self.busy():
            return
        self.worker = worker
        worker.succeeded.connect(on_ok)
        worker.failed.connect(on_fail)
        worker.finished.connect(self.job_finished)
        self.refresh()
        self.start_when_clear()

    def start_when_clear(self) -> None:
        """Start the job once no background check holds files open in the Sims folder
        (open files would stop Windows from renaming Mods). Checks are asked to stop early."""
        readers = [j for j in self.side_jobs if j.touches_sims]
        if readers:
            for j in readers:
                j.requestInterruption()
            QTimer.singleShot(100, self.start_when_clear)
            return
        if self.worker is not None and not self.worker.isRunning() and not self.worker.isFinished():
            self.worker.start()

    def job_finished(self) -> None:
        self.worker.deleteLater()
        self.worker = None
        self.refresh()
        waiting, self.deferred = self.deferred, []
        for worker, on_ok, on_fail in waiting:
            self.run_side(worker, on_ok, touches_sims=True, on_fail=on_fail)

    def run_side(self, worker: Worker, on_ok, touches_sims: bool = False, on_fail=None) -> None:
        """A read-only job (counting, checking); its errors are not worth interrupting for,
        unless the caller asks to hear about them."""
        if self.closing:
            return  # e.g. the update check's timer firing while the window closes
        if touches_sims and self.busy():
            self.deferred.append((worker, on_ok, on_fail))  # its open files could block the move
            return
        worker.touches_sims = touches_sims
        self.side_jobs.append(worker)
        worker.succeeded.connect(on_ok)
        if on_fail:
            worker.failed.connect(on_fail)

        def finished():
            self.side_jobs.remove(worker)
            worker.deleteLater()

        worker.finished.connect(finished)
        worker.start()

    def start_test(self) -> None:
        if self.busy():
            return
        s = self.setup
        s.notice.hide()
        self.after.hide()
        s.status.setText("Backing up your saves and copying the test mods" if self.opt("backup_saves")
                         else "Copying the test mods")
        s.progress.setRange(0, 100)
        s.progress.setValue(0)
        s.progress.show()
        worker = Worker(core.start_test, self.sims_dir, list(s.items), self.opt("clear_cache"),
                        self.opt("backup_saves"), with_progress=True)
        def progress(done: int, total: int) -> None:
            if done >= total:  # copying is done; the backup and the swap have no steps to show
                s.progress.setRange(0, 0)
                s.status.setText("Backing up your saves and setting your mods aside" if self.opt("backup_saves")
                                 else "Setting your mods aside")
            else:
                s.progress.setValue(int(done * 100 / total))

        worker.progress.connect(progress)

        def ok(_):
            s.progress.hide()
            self.saves_notice.hide()
            self.show_current_page()
            self.auto_start_game()

        def fail(msg: str):
            s.progress.hide()
            s.notice.show_message(msg, "error")
            self.offer_saves(core.pending_saves(self.sims_dir))  # the choice it may be waiting for
            self.show_current_page()

        self.run_job(worker, ok, fail)

    def start_search(self) -> None:
        if self.busy():
            return
        ss = self.search_setup
        ss.notice.hide()
        self.after.hide()
        ss.status.setText("Backing up your saves and switching your mods off" if self.opt("backup_saves")
                          else "Switching your mods off")
        self.run_job(Worker(core.start_search, self.sims_dir, self.opt("clear_cache"), self.opt("backup_saves")),
                     lambda _: (self.saves_notice.hide(), self.show_current_page(), self.auto_start_game()),
                     lambda msg: (ss.notice.show_message(msg, "error"),
                                  self.offer_saves(core.pending_saves(self.sims_dir)), self.show_current_page()))

    def answer(self, still_broken: bool) -> None:
        if self.busy():
            return
        se = self.search
        se.notice.hide()
        se.status.setText("Setting up the next round")
        se.progress.show()

        def ok(state):
            se.progress.hide()
            self.show_current_page()
            if state and state.get("found") is None and not state.get("not_mods"):
                self.auto_start_game()  # a new round is ready

        def fail(msg: str):
            se.progress.hide()
            se.notice.show_message(msg, "error")
            self.show_current_page()

        self.run_job(Worker(core.answer_search, self.sims_dir, still_broken, self.opt("clear_cache")), ok, fail)

    def end_test(self, remove_found: bool) -> None:
        if self.busy():
            return
        page = self.pages.currentWidget()
        stopped_early = page is self.search and not (self.state and (self.state.get("found") is not None
                                                                     or self.state.get("not_mods")))
        page.notice.hide()
        page.status.setText("Putting your mods back")
        page.progress.setRange(0, 0)
        page.progress.show()

        def ok(result: core.EndResult):
            page.progress.hide()
            self.mode_group.button(0 if page is self.testing else 1).setChecked(True)
            self.show_current_page()
            text = ("Search stopped. Your own mods are back; a new search starts from the beginning."
                    if stopped_early else "Your own mods are back.")
            if result.move_failed:
                text += (f" The broken mod could not be moved out ({result.move_failed}), so it is still in Mods. "
                         "Move or delete it yourself.")
            elif result.removed:
                text += f" The broken mod is in \u201c{result.removed.name}\u201d next to Mods."
            elif page is self.testing:
                text += (" The test copies were removed." if result.copies_removed
                         else f" The test copies went to the {platforms.trash_name()}.")
            if result.added_files:
                text += (f" {plural(result.added_files, 'file')} {'was' if result.added_files == 1 else 'were'} "
                         "added to the test folders during the test (by the game or by you), for example "
                         f"households saved to the library. They went to the {platforms.trash_name()}.")
            if result.leftovers:
                text += (f" Some test files could not go to the {platforms.trash_name()}. You can delete the folders named "
                         "“test copies” next to Mods.")
            self.after.show_message(text, "ok")
            self.offer_saves(result.changed_saves)
            self.count_mods()

        def fail(msg: str):
            page.progress.hide()
            page.notice.show_message(msg, "error")
            self.show_current_page()

        self.run_job(Worker(core.end_test, self.sims_dir, self.opt("clear_cache"), remove_found), ok, fail)

    def offer_saves(self, changed: list[dict]) -> None:
        if not changed:
            self.saves_notice.hide()
            return
        if len(changed) == 1:
            c = changed[0]
            text = (f"The game saved over \u201c{Path(c['name']).stem}\u201d during the test "
                    f"({when(c['saved'])}). Its Sims may have lost hair, clothes or furniture from your own CC. "
                    "Put back the old save to get them back (what you played in the test is lost), or keep "
                    "the new one.")
            action = "Put back the old save"
        else:
            text = (f"The game saved over {len(changed)} saves during the test. Their Sims may have lost hair, "
                    "clothes or furniture from your own CC. Put back the old saves to get them back (what you "
                    "played in the test is lost), or keep the new ones.")
            action = "Put back the old saves"
        self.saves_notice.show_message(text, "warn", action, self.restore_saves,
                                       "Keep the new one" if len(changed) == 1 else "Keep the new ones",
                                       self.keep_new_saves)

    def keep_new_saves(self) -> None:
        core.keep_new_saves(self.sims_dir, [c["name"] for c in core.pending_saves(self.sims_dir)])
        self.saves_notice.hide()

    def restore_saves(self) -> None:
        if self.busy():
            return
        names = [c["name"] for c in core.pending_saves(self.sims_dir)]

        def ok(missing: list[str]):
            if missing:
                names = ", ".join(f"\u201c{Path(n).stem}\u201d" for n in missing)
                self.saves_notice.show_message(
                    f"The backup of {names} is missing, so it couldn\u2019t be put back. That save stays as it "
                    "is now.", "warn")
            else:
                self.saves_notice.show_message(
                    "Your saves from before the test are back. The newer versions went to the "
                    f"{platforms.trash_name()}.", "ok")

        def fail(msg: str):
            self.saves_notice.show_message(msg, "error", "Try again", self.restore_saves)

        self.run_job(Worker(core.restore_saves, self.sims_dir, names), ok, fail)

    def open_licenses(self) -> None:
        """The third-party notices that ship with the app (next to the code when run from source)."""
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        notices = base / "THIRD-PARTY-NOTICES.md"
        if notices.is_file():
            self.open_path(notices)
        else:
            QDesktopServices.openUrl(QUrl(f"https://github.com/{updates.REPO}/blob/main/THIRD-PARTY-NOTICES.md"))

    def open_path(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def closeEvent(self, e) -> None:
        if self.busy():
            e.ignore()  # never leave a swap half done
            self.after.show_message("Sims 4 Mod Test is still moving your folders. Close it again when it "
                                    "has finished.", "warn")
            return
        # Gone for the user right away; the read-only checks get a few seconds to end by themselves
        # (each one stops when asked, and the update check gives up after a few seconds).
        self.closing = True
        self.hide()
        threads = [self.watcher, *self.side_jobs]
        for t in threads:
            t.requestInterruption()
        deadline = time.monotonic() + 8
        for t in threads:
            t.wait(max(0, int((deadline - time.monotonic()) * 1000)))
        super().closeEvent(e)
        # Hidden above, so Qt may not count this as the last window closing: end the loop ourselves.
        QApplication.instance().quit()


def _ctime(path: Path) -> float:
    try:
        return path.stat().st_ctime
    except OSError:
        return time.time()


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    if platforms.WINDOWS:
        app.setFont(QFont("Segoe UI", 10))  # elsewhere the system font is the right one
    app.setWindowIcon(QIcon(svg_pixmap(ICON_APP, 64)))

    # One window at a time: two windows swapping the same folders would trip over each other.
    # That includes the app under its old name, which used a different lock.
    if any((p.info.get("name") or "").lower() == "mod tester.exe" for p in psutil.process_iter(["name"])):
        QMessageBox.information(None, APP_NAME, "The older Mod Tester is still open. Close it first, "
                                "then open Sims 4 Mod Test again.")
        return 0
    core.migrate_data_dir()  # before the lock below creates the new data folder
    core.DATA_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(core.DATA_DIR / "app.lock"))
    lock.setStaleLockTime(0)  # a crashed app's lock is noticed by its dead process, not by age
    if not lock.tryLock(200):
        QMessageBox.information(None, APP_NAME, "Sims 4 Mod Test is already open. Look for it in the taskbar.")
        return 0

    win = MainWindow()
    win.show()
    if os.environ.get("SIMS4MODTEST_SMOKE_TEST"):  # CI: the built app starts, shows its window, quits
        QTimer.singleShot(SMOKE_TEST_CLOSE_MS, win.close)
    code = app.exec()
    if win.watcher.isRunning() or any(job.isRunning() for job in win.side_jobs):
        # A read-only check is still stuck (a very slow network). Python would wait for it or abort
        # over a running QThread, and nothing it does needs saving, so leave now.
        win.settings.sync()
        lock.unlock()
        _leave_now(code)
    return code


def _leave_now(code: int) -> None:
    """End the process at once. On Windows without DLL clean-up: os._exit runs it and can crash
    while another thread is inside a system library (seen with the certificate store)."""
    if platforms.WINDOWS:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE  # a 64-bit handle, not ctypes' default int
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), code)
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
