"""Mod Tester: try out Sims 4 mods on their own, find a broken mod, then put your own mods back."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QByteArray, QProcess, QSettings, QStandardPaths, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QStackedLayout,
                               QStackedWidget, QVBoxLayout, QWidget)

import core
import risks

APP_NAME = "Mod Tester"
VERSION = "1.0.0"
SUPPORT_URL = "https://buymeacoffee.com/stixe"

# ---------------------------------------------------------------- theme

LIGHT = {
    "bg": "#F6F5F2", "surface": "#FFFFFF", "border": "#E3E1DC", "border_strong": "#C9C6BF",
    "text": "#1D1C1A", "muted": "#64615B", "hover": "#EFEDE9",
    "ink": "#1D1C1A", "ink_hover": "#3A3834", "on_ink": "#FFFFFF",
    "disabled_bg": "#E3E1DC", "disabled_text": "#8C8981", "focus": "#2F64C8",
    "warn_bg": "#FBF4E4", "warn_border": "#EAD7A8", "warn_text": "#6B4A00",
    "error_bg": "#FCEDEC", "error_border": "#EFC4C0", "error_text": "#8A1F17",
    "ok_bg": "#EAF4EC", "ok_border": "#BFDCC6", "ok_text": "#1F5A30",
}
DARK = {
    "bg": "#171716", "surface": "#201F1E", "border": "#32312E", "border_strong": "#4A4844",
    "text": "#EDECE8", "muted": "#A6A39C", "hover": "#2A2927",
    "ink": "#EDECE8", "ink_hover": "#D6D4CE", "on_ink": "#171716",
    "disabled_bg": "#2E2D2B", "disabled_text": "#7D7A74", "focus": "#7FA6F0",
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

_icon_dir = Path(tempfile.mkdtemp(prefix="modtester-"))


def svg_pixmap(svg: str, size: int, ratio: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def current_theme() -> dict:
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


SAVE_WARNING = ("Don’t save your usual households during the test. Without your own CC they lose hair, "
                "clothes and furniture. Mod Tester keeps a copy of your saves from before the test, "
                "so you can put them back afterwards.")


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


class ItemRow(QFrame):
    removed = Signal(object)

    def __init__(self, item: core.ModItem, first: bool, removable: bool, remove_icon: QIcon):
        super().__init__()
        self.setObjectName("row")
        self.setProperty("first", "true" if first else "false")
        self.setToolTip(item.path)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 10 if removable else 16, 10)
        lay.setSpacing(14)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(ElidedLabel(item.title, "rowname"))
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
        except core.TesterError as e:
            self.failed.emit(str(e))
        except Exception as e:  # unexpected: still say what happened and what to check
            self.failed.emit(f"Mod Tester stopped because of an unexpected problem ({type(e).__name__}: {e}). "
                             "Open Mod Tester again; it checks your folders when it starts.")


class GameWatcher(QThread):
    """Checks every two seconds whether the game runs, off the UI thread."""
    changed = Signal(bool, str)  # running, path of the game's exe ("" if unknown)

    def run(self) -> None:
        while not self.isInterruptionRequested():
            exe = ""
            try:
                procs = core.game_processes()
                for proc in procs:
                    try:
                        exe = proc.exe() or ""
                        break
                    except Exception:
                        continue
                self.changed.emit(bool(procs), exe)
            except Exception:
                pass
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
            "Something wrong in your game, like errors, odd heads or a missing menu? Mod Tester switches "
            "half of your mods off. You play, close the game and say whether the problem is still there. "
            "Then it halves again, until one mod is left.", "muted", wrap=True))
        self.count = label("", wrap=True)
        lay.addWidget(self.count)
        self.save_warning = Notice("warn")
        self.save_warning.show_message(SAVE_WARNING)
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
        self.save_warning = Notice("warn")
        self.save_warning.show_message(SAVE_WARNING)
        lay.addWidget(self.save_warning)
        self.errors = Notice("error")
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

        self.save_warning = Notice("warn")
        self.save_warning.show_message(SAVE_WARNING)
        lay.addWidget(self.save_warning)
        self.errors = Notice("error")
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
        self.keep_btn = button("Restore everything")
        self.remove_btn = button("Restore without it", "primary")
        bottom.addWidget(self.stop_btn, 0, Qt.AlignVCenter)
        bottom.addWidget(self.keep_btn)
        bottom.addWidget(self.remove_btn)
        lay.addLayout(bottom)


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
        self.settings = QSettings("Mod Tester", "Mod Tester")
        self.sims_dir: Path | None = None
        self.worker: Worker | None = None
        self.side_jobs: list[Worker] = []
        self.game_on = False
        self.test_started = 0.0
        self.state: dict | None = None
        self.reports: list[Path] = []
        self.game_keys: frozenset[int] | None = None
        self.risk_cache: dict[tuple, list[str]] = {}     # (path, size, mtime, with game index) -> warnings
        self.suspect_cache: dict[tuple, list[str]] = {}  # (report, mtime) -> mods it mentions

        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.addWidget(label(APP_NAME, "title"))
        title_row.addStretch(1)
        coffee = button("Buy me a coffee", "coffee")
        coffee.setIcon(QIcon(svg_pixmap(ICON_CUP, 16)))
        coffee.setToolTip(f"Mod Tester is free. If it helps you, you can support it: {SUPPORT_URL}")
        coffee.setAccessibleName("Buy me a coffee (opens buymeacoffee.com)")
        coffee.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SUPPORT_URL)))
        title_row.addWidget(coffee, 0, Qt.AlignVCenter)
        lay.addLayout(title_row)
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        self.folder_label = ElidedLabel("", "muted")
        folder_row.addWidget(self.folder_label, 1)
        self.change_btn = button("Change", "link")
        self.change_btn.clicked.connect(self.choose_sims_dir)
        folder_row.addWidget(self.change_btn)
        lay.addLayout(folder_row)
        lay.addSpacing(14)

        self.segments = QFrame()
        self.segments.setObjectName("segments")
        sl = QHBoxLayout(self.segments)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.mode_group = QButtonGroup(self)
        for i, text in enumerate(("Test new mods", "Find a broken mod")):
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

        self.after = Notice("ok")  # results of a restore; stays until the next action
        lay.addWidget(self.after)
        self.saves_notice = Notice("warn")
        lay.addWidget(self.saves_notice)
        lay.addSpacing(4)

        self.setup = TestSetupPage()
        self.search_setup = SearchSetupPage()
        self.testing = TestingPage()
        self.search = SearchPage()
        self.pages = QStackedWidget()
        for page in (self.setup, self.search_setup, self.testing, self.search):
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
        QGuiApplication.styleHints().colorSchemeChanged.connect(lambda _: self.apply_theme())

        self.watcher = GameWatcher(self)
        self.watcher.changed.connect(self.game_changed)
        self.watcher.start()
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.check_reports)
        self.timer.start()

        self.set_sims_dir(self.initial_sims_dir())
        self.load_game_index()

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
        found = core.find_sims_dirs(docs)
        return found[0] if found else None

    def set_sims_dir(self, path: Path | None) -> None:
        self.sims_dir = path
        if path is None:
            self.folder_label.set_full_text("Sims 4 folder not found")
            self.show_current_page()
            self.setup.notice.show_message(
                "Mod Tester could not find your Sims 4 folder. Use Change to pick the folder "
                "that holds Mods and Tray, usually Documents\\Electronic Arts\\The Sims 4.", "warn")
            return
        self.settings.setValue("sims_dir", str(path))
        self.folder_label.set_full_text(f"Sims 4 folder: {path}")
        self.setup.notice.hide()
        try:
            core.recover(path)
        except (OSError, core.TesterError) as e:
            self.after.show_message(
                f"Mod Tester found an unfinished swap and could not tidy it up: {e} "
                "Close other programs and open Mod Tester again.", "error")
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
            self.setup.notice.show_message(
                f"“{path.name}” doesn’t look like a Sims 4 folder. Pick the folder that holds "
                "Mods and Tray.", "warn")
            return
        self.set_sims_dir(path)

    def game_dir(self) -> Path | None:
        saved = self.settings.value("game_exe", "", type=str)
        if saved and Path(saved).is_file():
            return risks.game_dir_of(Path(saved))
        found = risks.find_game_dir()
        if found:
            self.settings.setValue("game_exe", str(risks.game_exe(found)))
        return found

    def game_changed(self, running: bool, exe: str) -> None:
        if exe and exe.lower().endswith("ts4_x64.exe") and exe != self.settings.value("game_exe", "", type=str):
            self.settings.setValue("game_exe", exe)  # learned from the running game
            self.load_game_index()
        if running != self.game_on:
            self.game_on = running
            self.refresh()

    def play(self) -> None:
        exe = self.settings.value("game_exe", "", type=str)
        if not exe or not Path(exe).is_file():
            gd = self.game_dir()
            exe = str(risks.game_exe(gd)) if gd else ""
        if not exe:
            picked, _ = QFileDialog.getOpenFileName(
                self, "Find The Sims 4 (Game\\Bin\\TS4_x64.exe)", str(Path.home()), "The Sims 4 (TS4_x64.exe)")
            if not picked:
                return
            exe = picked
            self.settings.setValue("game_exe", exe)
            self.load_game_index()
        started = QProcess.startDetached(exe, [], str(Path(exe).parent))
        if not (started[0] if isinstance(started, tuple) else started):
            page = self.pages.currentWidget()
            page.notice.show_message(f"The Sims 4 did not start from “{exe}”. "
                                     "Start it the usual way.", "error")
            self.settings.remove("game_exe")
            return
        page = self.pages.currentWidget()
        page.status.setText("Starting The Sims 4")

    def load_game_index(self) -> None:
        """Read the game's own CAS parts and sliders in the background, for the override check."""
        gd = self.game_dir()
        if gd is None or getattr(self, "_index_for", None) == gd:
            return
        self._index_for = gd

        def done(keys):
            self.game_keys = keys
            self.check_items()

        self.run_side(Worker(risks.game_index, gd), done)

    # -- pages

    def mode_changed(self, _id: int) -> None:
        self.after.hide()
        self.show_current_page()

    def show_current_page(self) -> None:
        sims = self.sims_dir
        running = bool(sims and core.in_test(sims))
        self.state = core.load_state(sims) if running else None
        self.segments.setVisible(not running)
        self.change_btn.setVisible(not running)
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
        else:
            self.pages.setCurrentWidget(self.setup)
        self.setFocus()  # don't leave keyboard focus on a button that was just rebuilt or hidden
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
        s.keep_btn.setText("Restore my mods" if not_mods else "Restore everything")
        s.remove_btn.setVisible(found is not None)
        if not_mods:
            s.heading.setText("It isn\u2019t a mod")
            s.body.setText("The problem is there even with all of your mods switched off, so no mod causes it. "
                           "Restore your mods, then try Repair for The Sims 4 in the EA app.")
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
            s.body.setText("All of your mods are switched off. Start the game and check whether the problem is "
                           "still there. If it is gone, a mod causes it and the search goes on.")
            return
        total = st["round"] + core.rounds_left(len(candidates)) - 1
        s.heading.setText(f"Round {st['round']} of about {total}")
        on = sum(len(units[i]) for i in st["testing"])
        s.body.setText(f"{on:,} of your mod files are switched on, the rest are off. "
                       f"{plural(len(candidates), 'mod')} could still be the broken one. Start the game and "
                       "check whether the problem is still there.")

    def count_mods(self) -> None:
        sims = self.sims_dir
        if not sims or core.in_test(sims) or not (sims / "Mods").is_dir():
            self.search_setup.count.setText("")
            return

        def done(units):
            n = len(units)
            self.search_setup.count.setText(
                f"Your Mods folder has {plural(n, 'mod')}. Finding one takes about "
                f"{plural(core.rounds_left(n), 'round')}." if n > 1 else "There are not enough mods to search.")

        self.run_side(Worker(core.mod_units, sims / "Mods"), done, touches_sims=True)

    def busy(self) -> bool:
        return self.worker is not None

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
            self.suspect_cache[key] = risks.report_suspects(self.reports[0], names)
        suspects = self.suspect_cache[key]
        if suspects:
            text += " It mentions " + " and ".join(f"“{s}”" for s in suspects[:2]) + "."
        elif page is self.testing:
            text += " One of the test mods may be broken or outdated."
        page.errors.show_message(text, action="Open report", handler=lambda: self.open_path(self.reports[0]))

    def refresh(self) -> None:
        busy = self.busy()
        game = self.game_on
        s = self.setup
        has_dir = self.sims_dir is not None
        for w in (s.add_files_btn, s.add_folder_btn, s.clear_btn, self.change_btn):
            w.setEnabled(not busy)
        for b in self.mode_group.buttons():
            b.setEnabled(not busy)
        s.list.setEnabled(not busy)
        s.start_btn.setEnabled(has_dir and bool(s.items) and not game and not busy)
        if not busy:
            s.status.setText("Close The Sims 4 to start a test." if game else
                             "Your own mods are set aside, not changed." if s.items else "")

        ss = self.search_setup
        ss.start_btn.setEnabled(has_dir and not game and not busy)
        if not busy:
            ss.status.setText("Close The Sims 4 to start a search." if game else "")

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

        self.run_job(Worker(core.inspect_paths, paths, self.sims_dir), ok, fail)

    def check_items(self) -> None:
        """Look for risky files among the test items, in the background."""
        full = self.game_keys is not None

        def key(i: core.ModItem) -> tuple:
            return (os.path.normcase(i.path), i.size, core.mtime(Path(i.path)), full)

        todo = []
        for i in self.setup.items:
            if key(i) in self.risk_cache:
                i.warnings = self.risk_cache[key(i)]
            else:
                todo.append(i)
        self.setup.set_items(self.setup.items)
        if not todo:
            return
        keys, updated = self.game_keys, risks.last_update(self.game_dir(), self.sims_dir)

        def run():
            results = []
            for i in todo:
                if QThread.currentThread().isInterruptionRequested():
                    break  # a test is about to start; unchecked items are checked next time
                results.append((i, key(i), risks.check(i, keys, updated)))
            return results

        def done(results):
            for item, k, warnings in results:
                item.warnings = warnings
                self.risk_cache[k] = warnings
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

    def run_side(self, worker: Worker, on_ok, touches_sims: bool = False) -> None:
        """A read-only job (counting, checking); its errors are not worth interrupting for."""
        worker.touches_sims = touches_sims
        self.side_jobs.append(worker)
        worker.succeeded.connect(on_ok)

        def finished():
            self.side_jobs.remove(worker)
            worker.deleteLater()

        worker.finished.connect(finished)
        worker.start()

    def start_test(self) -> None:
        s = self.setup
        s.notice.hide()
        self.after.hide()
        self.saves_notice.hide()
        s.status.setText("Backing up your saves and copying the test mods")
        s.progress.setRange(0, 100)
        s.progress.setValue(0)
        s.progress.show()
        worker = Worker(core.start_test, self.sims_dir, list(s.items), True, with_progress=True)
        worker.progress.connect(lambda d, t: s.progress.setValue(int(d * 100 / t)))

        def ok(_):
            s.progress.hide()
            self.show_current_page()

        def fail(msg: str):
            s.progress.hide()
            s.notice.show_message(msg, "error")
            self.show_current_page()

        self.run_job(worker, ok, fail)

    def start_search(self) -> None:
        ss = self.search_setup
        ss.notice.hide()
        self.after.hide()
        self.saves_notice.hide()
        ss.status.setText("Backing up your saves and switching your mods off")
        self.run_job(Worker(core.start_search, self.sims_dir, True),
                     lambda _: self.show_current_page(),
                     lambda msg: (ss.notice.show_message(msg, "error"), self.show_current_page()))

    def answer(self, still_broken: bool) -> None:
        se = self.search
        se.notice.hide()
        se.status.setText("Setting up the next round")
        se.progress.show()

        def ok(_):
            se.progress.hide()
            self.show_current_page()

        def fail(msg: str):
            se.progress.hide()
            se.notice.show_message(msg, "error")
            self.show_current_page()

        self.run_job(Worker(core.answer_search, self.sims_dir, still_broken, True), ok, fail)

    def end_test(self, remove_found: bool) -> None:
        page = self.pages.currentWidget()
        page.notice.hide()
        page.status.setText("Putting your mods back")
        page.progress.setRange(0, 0)
        page.progress.show()

        def ok(result: core.EndResult):
            page.progress.hide()
            self.mode_group.button(0 if page is self.testing else 1).setChecked(True)
            self.show_current_page()
            text = "Your own mods are back."
            if result.move_failed:
                text += (f" The broken mod could not be moved out ({result.move_failed}), so it is still in Mods. "
                         "Move or delete it yourself.")
            elif result.removed:
                text += f" The broken mod is in \u201c{result.removed.name}\u201d next to Mods."
            elif page is self.testing:
                text += " The test copies went to the Recycle Bin."
            if result.leftovers:
                text += (" Some test files could not go to the Recycle Bin. You can delete the folders named "
                         "“finished Mod Tester test” next to Mods.")
            self.after.show_message(text, "ok")
            self.offer_saves(result.changed_saves)
            self.count_mods()

        def fail(msg: str):
            page.progress.hide()
            page.notice.show_message(msg, "error")
            self.show_current_page()

        self.run_job(Worker(core.end_test, self.sims_dir, True, remove_found), ok, fail)

    def offer_saves(self, changed: list[dict]) -> None:
        if not changed:
            self.saves_notice.hide()
            return
        if len(changed) == 1:
            c = changed[0]
            text = (f"The game saved over “{Path(c['name']).stem}” during the test ({when(c['saved'])}). "
                    "Its Sims may be missing CC now.")
            action = "Put back the old save"
        else:
            text = f"The game saved over {len(changed)} saves during the test. Their Sims may be missing CC now."
            action = "Put back the old saves"
        self.saves_notice.show_message(text, "warn", action, self.restore_saves,
                                       "Keep the new one" if len(changed) == 1 else "Keep the new ones",
                                       self.keep_new_saves)

    def keep_new_saves(self) -> None:
        core.keep_new_saves(self.sims_dir, [c["name"] for c in core.pending_saves(self.sims_dir)])
        self.saves_notice.hide()

    def restore_saves(self) -> None:
        names = [c["name"] for c in core.pending_saves(self.sims_dir)]

        def ok(_):
            self.saves_notice.show_message(
                "Your saves from before the test are back. The newer versions went to the Recycle Bin.", "ok")

        def fail(msg: str):
            self.saves_notice.show_message(msg, "error", "Try again", self.restore_saves)

        self.run_job(Worker(core.restore_saves, self.sims_dir, names), ok, fail)

    def open_path(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def closeEvent(self, e) -> None:
        if self.busy():
            e.ignore()  # never leave a swap half done
            return
        self.watcher.requestInterruption()
        self.watcher.wait(3000)
        for job in list(self.side_jobs):  # read-only work: safe to stop
            if not job.wait(300):
                job.terminate()
                job.wait(1000)
        super().closeEvent(e)


def _ctime(path: Path) -> float:
    try:
        return path.stat().st_ctime
    except OSError:
        return time.time()


def _first_instance():
    """A named mutex: two windows swapping the same folders at once would trip over each other."""
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\ModTester-single-instance")
    ERROR_ALREADY_EXISTS = 183
    return handle if handle and ctypes.get_last_error() != ERROR_ALREADY_EXISTS else None


def main() -> int:
    mutex = _first_instance()
    if mutex is None:
        import ctypes
        MB_ICONINFORMATION, MB_SETFOREGROUND = 0x40, 0x10000
        ctypes.windll.user32.MessageBoxW(None, "Mod Tester is already open. Look for it in the taskbar.",
                                         APP_NAME, MB_ICONINFORMATION | MB_SETFOREGROUND)
        return 0
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setWindowIcon(QIcon(svg_pixmap(ICON_APP, 64)))
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
