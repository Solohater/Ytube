"""PySide6 main window for the You-T downloader."""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSystemTrayIcon,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import downloader
import runtime

DARK_QSS = """
QWidget {
    background-color: #1e1f24;
    color: #e6e6e6;
    font-size: 14px;
}
QLineEdit, QComboBox, QSpinBox {
    background-color: #2a2b31;
    border: 1px solid #3d3e46;
    border-radius: 6px;
    padding: 7px 9px;
    selection-background-color: #3a6ea5;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #5b8def; }
QPushButton {
    background-color: #3a6ea5;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
}
QPushButton:hover { background-color: #4a7fbb; }
QPushButton:disabled { background-color: #3a3b42; color: #8a8a92; }
QPushButton#danger { background-color: #a04545; }
QPushButton#danger:hover { background-color: #b85454; }
QPushButton#secondary { background-color: #35363d; }
QPushButton#secondary:hover { background-color: #45464f; }
QProgressBar {
    background-color: #2a2b31;
    border: 1px solid #3d3e46;
    border-radius: 6px;
    text-align: center;
    height: 22px;
}
QProgressBar::chunk { background-color: #4f8f5a; border-radius: 5px; }
QGroupBox {
    border: 1px solid #3d3e46;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QLabel#info { color: #a9c7e8; }
QLabel#status { color: #9fd0a5; }
QLabel#status.error { color: #e88a8a; }
QFrame#hline { background-color: #3d3e46; max-height: 1px; }
QTableWidget {
    background-color: #24252b;
    border: 1px solid #3d3e46;
    border-radius: 8px;
    gridline-color: #33343b;
    selection-background-color: #2f3b4d;
}
QTableWidget::item { padding: 4px 6px; }
QHeaderView::section {
    background-color: #2a2b31;
    color: #a9c7e8;
    border: none;
    border-bottom: 1px solid #3d3e46;
    padding: 6px 8px;
    font-weight: bold;
}
QMenu {
    background-color: #2a2b31;
    border: 1px solid #3d3e46;
    padding: 4px;
}
QMenu::item { padding: 6px 18px; border-radius: 4px; }
QMenu::item:selected { background-color: #3a6ea5; }
"""

_CHECK_ICON = (runtime.resource_dir() / "assets" / "check.svg").as_posix()

DARK_QSS += f"""
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #4a4b55;
    border-radius: 4px;
    background-color: #2a2b31;
}}
QCheckBox::indicator:hover {{ border-color: #5b8def; }}
QCheckBox::indicator:checked {{
    background-color: #3a6ea5;
    border-color: #5b8def;
    image: url("{_CHECK_ICON}");
}}
"""

TERMINAL_STATES = ("finished", "failed", "cancelled")
CONNECTION_CHOICES = (8, 16, 24, 32)
# Fragment connections are shared by all active downloads. Going much above
# this total makes YouTube throttle or stall individual fragments.
TOTAL_CONNECTION_BUDGET = 32
MIN_JOB_CONNECTIONS = 4


class Bridge(QObject):
    info_ok = Signal(dict)
    info_err = Signal(str)
    status = Signal(int, str)
    progress = Signal(int, dict)
    done = Signal(int, str)
    error = Signal(int, str)


@dataclass
class DownloadEntry:
    id: int
    url: str
    title: str
    quality: str
    output_dir: str
    use_cookies: bool
    browser: Optional[str]
    connections: int = 0
    state: str = "queued"
    path: Optional[str] = None
    error: str = ""
    job: Optional[downloader.DownloadJob] = None
    summarized: bool = False
    progress: Optional[QProgressBar] = None
    title_item: Optional[QTableWidgetItem] = None
    speed_item: Optional[QTableWidgetItem] = None
    status_item: Optional[QTableWidgetItem] = None
    action_btn: Optional[QPushButton] = None


def _fmt_duration(seconds) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class SettingsDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        *,
        parallel: int,
        connections: int,
        notify: bool,
    ):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setSpacing(10)

        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 5)
        self.parallel_spin.setValue(parallel)
        self.parallel_spin.setSuffix(" files")
        form.addRow("Simultaneous downloads:", self.parallel_spin)

        self.connections_combo = QComboBox()
        for value in CONNECTION_CHOICES:
            self.connections_combo.addItem(f"{value} connections", value)
        index = self.connections_combo.findData(connections)
        self.connections_combo.setCurrentIndex(index if index >= 0 else 2)
        form.addRow("Connections per file:", self.connections_combo)

        self.notify_check = QCheckBox("Notify me when a download finishes")
        self.notify_check.setChecked(notify)
        form.addRow(self.notify_check)

        layout.addLayout(form)

        hint = QLabel(
            "Connections are shared across active downloads: extra files get "
            "fewer connections, and wait in the queue if the budget is full. "
            "Very high values can trigger YouTube throttling or HTTP 429 errors."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8a8a92; font-size: 12px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("You-T — Video Downloader")
        self.setMinimumSize(860, 680)

        self.bridge = Bridge()
        self._entries: dict[int, DownloadEntry] = {}
        self._next_id = 0
        self._fetching = False
        self._summary_open = False
        self._last_error = ""
        self.tray: Optional[QSystemTrayIcon] = None

        settings = QSettings()
        self.max_parallel = self._setting_int("downloads/max_parallel", 3, 1, 5)
        connections = self._setting_int(
            "downloads/connections", downloader.CONCURRENT_FRAGMENTS, 8, 32
        )
        if connections not in CONNECTION_CHOICES:
            connections = downloader.CONCURRENT_FRAGMENTS
        self.connections = connections
        self.notify_enabled = str(
            settings.value("downloads/notify", "true")
        ).lower() in ("true", "1", "yes")

        self._build_ui()
        self._connect()
        self._setup_tray()
        self._update_status()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title_row = QHBoxLayout()
        title = QLabel("You-T")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #5b8def;")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.settings_btn = QPushButton("Settings")
        self.settings_btn.setObjectName("secondary")
        title_row.addWidget(self.settings_btn)
        layout.addLayout(title_row)

        # URL row
        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("Paste a video URL, e.g. https://www.youtube.com/watch?v=…")
        self.fetch_btn = QPushButton("Fetch info")
        self.fetch_btn.setObjectName("secondary")
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(self.fetch_btn)
        layout.addLayout(url_row)

        self.info_label = QLabel("No video loaded.")
        self.info_label.setObjectName("info")
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        hline = QFrame()
        hline.setObjectName("hline")
        hline.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(hline)

        # Options
        opts = QGroupBox("Options")
        opts_grid = QVBoxLayout(opts)
        opts_grid.setSpacing(10)

        q_row = QHBoxLayout()
        q_row.addWidget(QLabel("Quality:"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(list(downloader.QUALITY_CHOICES))
        self.quality_combo.setCurrentText("Best")
        q_row.addWidget(self.quality_combo, 1)
        opts_grid.addLayout(q_row)

        d_row = QHBoxLayout()
        d_row.addWidget(QLabel("Save to:"))
        self.dir_edit = QLineEdit(str(Path.home() / "Downloads"))
        self.dir_edit.setReadOnly(True)
        browse_btn = QPushButton("Browse")
        browse_btn.setObjectName("secondary")
        self.dir_btn = browse_btn
        d_row.addWidget(self.dir_edit, 1)
        d_row.addWidget(browse_btn)
        opts_grid.addLayout(d_row)

        c_row = QHBoxLayout()
        self.cookies_check = QCheckBox("Use cookies from browser")
        self.cookies_check.setToolTip(
            "Only enable when YouTube shows \"Sign in to confirm you're not a bot\". "
            "Cookies can break downloads on current YouTube — the app automatically "
            "retries without them if that happens."
        )
        self.browser_combo = QComboBox()
        self.browser_combo.addItems(list(downloader.BROWSER_CHOICES))
        self.browser_combo.setEnabled(False)
        c_row.addWidget(self.cookies_check, 1)
        c_row.addWidget(self.browser_combo)
        opts_grid.addLayout(c_row)

        layout.addWidget(opts)

        # Downloads table
        downloads = QGroupBox("Downloads")
        downloads_layout = QVBoxLayout(downloads)
        downloads_layout.setSpacing(10)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Video", "Quality", "Progress", "Speed / ETA", "Status", ""]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(46)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(190)
        self.table.setWordWrap(False)

        header = self.table.horizontalHeader()
        header.setHighlightSections(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(2, 160)
        downloads_layout.addWidget(self.table)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        downloads_layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        self.clear_btn = QPushButton("Clear finished")
        self.clear_btn.setObjectName("secondary")
        self.retry_btn = QPushButton("Retry failed")
        self.retry_btn.setObjectName("secondary")
        self.retry_btn.setToolTip("Retry every failed download in the list")
        self.cancel_all_btn = QPushButton("Cancel all")
        self.cancel_all_btn.setObjectName("danger")
        self.clear_btn.setEnabled(False)
        self.retry_btn.setEnabled(False)
        self.cancel_all_btn.setEnabled(False)
        actions.addWidget(self.clear_btn)
        actions.addWidget(self.retry_btn)
        actions.addStretch(1)
        actions.addWidget(self.cancel_all_btn)
        downloads_layout.addLayout(actions)

        layout.addWidget(downloads, 1)

        # Actions
        btn_row = QHBoxLayout()
        self.download_btn = QPushButton("Download")
        btn_row.addStretch(1)
        btn_row.addWidget(self.download_btn)
        layout.addLayout(btn_row)

        note = QLabel(
            "Only download content you have the right to download — "
            "this may violate YouTube's Terms of Service."
        )
        note.setStyleSheet("color: #77787f; font-size: 12px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        self.setCentralWidget(root)

    def _connect(self) -> None:
        self.fetch_btn.clicked.connect(self.on_fetch)
        self.download_btn.clicked.connect(self.on_download)
        self.settings_btn.clicked.connect(self.on_settings)
        self.clear_btn.clicked.connect(self.on_clear_finished)
        self.retry_btn.clicked.connect(self.on_retry_failed)
        self.cancel_all_btn.clicked.connect(self.on_cancel_all)
        self.dir_btn.clicked.connect(self.on_browse)
        self.cookies_check.toggled.connect(self.browser_combo.setEnabled)
        self.url_edit.returnPressed.connect(self.on_fetch)

        self.bridge.info_ok.connect(self._info_ok)
        self.bridge.info_err.connect(self._info_err)
        self.bridge.status.connect(self._status)
        self.bridge.progress.connect(self._progress)
        self.bridge.done.connect(self._done)
        self.bridge.error.connect(self._error)

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon_path = runtime.icon_path()
        icon = QIcon(str(icon_path)) if icon_path else QApplication.windowIcon()
        tray = QSystemTrayIcon(icon, self)
        tray.setToolTip("You-T")
        menu = QMenu(self)
        menu.addAction("Show You-T", self._show_window)
        menu.addAction("Settings", self.on_settings)
        menu.addSeparator()
        menu.addAction("Quit", self.close)
        tray.setContextMenu(menu)
        tray.activated.connect(self._tray_activated)
        tray.show()
        self.tray = tray

    # ---------- helpers ----------

    @staticmethod
    def _setting_int(key: str, default: int, low: int, high: int) -> int:
        try:
            value = int(QSettings().value(key, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(high, value))

    def _set_status(self, text: str, *, error: bool) -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("error", error)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _update_status(self) -> None:
        states = [entry.state for entry in self._entries.values()]
        active = states.count("downloading") + states.count("cancelling")
        queued = states.count("queued")
        finished = states.count("finished")
        failed = states.count("failed")
        cancelled = states.count("cancelled")

        parts = []
        if active:
            parts.append(f"{active} downloading")
        if queued:
            parts.append(f"{queued} queued")
        if finished:
            parts.append(f"{finished} finished")
        if failed:
            parts.append(f"{failed} failed")
        if cancelled:
            parts.append(f"{cancelled} cancelled")
        text = "  ·  ".join(parts) if parts else "Ready."

        has_terminal = any(state in TERMINAL_STATES for state in states)
        self.clear_btn.setEnabled(has_terminal)
        self.retry_btn.setEnabled(bool(failed))
        self.cancel_all_btn.setEnabled(bool(active or queued))

        if failed and self._last_error:
            self._set_status(f"{text}  —  {self._last_error}", error=True)
        else:
            self._set_status(text, error=False)

    def _validated_url(self) -> Optional[str]:
        url = self.url_edit.text().strip()
        if not url:
            self._set_status("Paste a video URL first.", error=True)
            return None
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.url_edit.setText(url)
        return url

    def _cookies(self) -> tuple[bool, Optional[str]]:
        if self.cookies_check.isChecked():
            return True, self.browser_combo.currentText()
        return False, None

    def _active_count(self) -> int:
        return sum(1 for e in self._entries.values() if e.state == "downloading")

    def _find_active_by_url(self, url: str) -> Optional[DownloadEntry]:
        return next(
            (
                e
                for e in self._entries.values()
                if e.url == url
                and e.state in ("queued", "downloading", "cancelling")
            ),
            None,
        )

    def _has_queued(self) -> bool:
        return any(e.state == "queued" for e in self._entries.values())

    def _entry(self, entry_id: int) -> Optional[DownloadEntry]:
        return self._entries.get(entry_id)

    def _set_title(self, entry: DownloadEntry, title: str) -> None:
        if not title or title == entry.title:
            return
        entry.title = title
        if entry.title_item is not None:
            entry.title_item.setText(title)
            entry.title_item.setToolTip(f"{title}\n{entry.url}")

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_window()

    def _notify(self, title: str, message: str) -> None:
        if not self.notify_enabled:
            return
        # On Linux, notify-send is more reliable than a tray balloon, especially
        # on GNOME Wayland where tray support is often absent.
        if sys.platform.startswith("linux") and shutil.which("notify-send"):
            try:
                subprocess.Popen(
                    ["notify-send", "-a", "You-T", title, message],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                pass
            return
        if self.tray is not None and self.tray.isVisible():
            self.tray.showMessage(
                title, message, QSystemTrayIcon.MessageIcon.Information, 6000
            )

    # ---------- actions ----------

    def on_browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Choose download folder", self.dir_edit.text()
        )
        if directory:
            self.dir_edit.setText(directory)

    def on_fetch(self) -> None:
        if self._fetching:
            return
        url = self._validated_url()
        if not url:
            return
        use_cookies, browser = self._cookies()
        self.info_label.setText("Fetching video info…")
        self.fetch_btn.setEnabled(False)
        self._fetching = True

        def worker():
            try:
                info = downloader.fetch_info(
                    url, use_cookies=use_cookies, browser=browser
                )
                self.bridge.info_ok.emit(info)
            except Exception as exc:  # noqa: BLE001
                self.bridge.info_err.emit(
                    downloader.friendly_error(str(exc).replace("ERROR:", "").strip())
                )

        threading.Thread(target=worker, daemon=True).start()

    def _info_ok(self, info: dict) -> None:
        self._fetching = False
        self.fetch_btn.setEnabled(True)
        parts = [info["title"]]
        if info.get("uploader"):
            parts.append(info["uploader"])
        if info.get("duration"):
            parts.append(_fmt_duration(info["duration"]))
        self.info_label.setText("  •  ".join(parts))
        self._set_status("Video loaded. Choose quality and hit Download.", error=False)

    def _info_err(self, message: str) -> None:
        self._fetching = False
        self.fetch_btn.setEnabled(True)
        self.info_label.setText("No video loaded.")
        self._set_status(message, error=True)

    def on_download(self) -> None:
        url = self._validated_url()
        if not url:
            return
        if self._find_active_by_url(url) is not None:
            self._set_status(
                "That video is already queued or downloading.", error=True
            )
            return
        output_dir = Path(self.dir_edit.text().strip() or Path.home() / "Downloads")
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._set_status(f"Cannot create folder: {exc}", error=True)
            return

        use_cookies, browser = self._cookies()
        self._next_id += 1
        entry = DownloadEntry(
            id=self._next_id,
            url=url,
            title=url,
            quality=self.quality_combo.currentText(),
            output_dir=str(output_dir),
            use_cookies=use_cookies,
            browser=browser,
        )
        self._entries[entry.id] = entry
        self._add_row(entry)

        self.url_edit.clear()
        self.info_label.setText("No video loaded.")
        self._last_error = ""
        self._fill_slots()
        self._update_status()

    def _add_row(self, entry: DownloadEntry) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        entry.title_item = QTableWidgetItem(entry.title)
        entry.title_item.setToolTip(entry.url)
        quality_item = QTableWidgetItem(entry.quality)
        quality_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        entry.speed_item = QTableWidgetItem("-")
        entry.speed_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        entry.status_item = QTableWidgetItem("Queued")
        entry.status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        entry.progress = QProgressBar()
        entry.progress.setRange(0, 100)
        entry.progress.setValue(0)
        entry.progress.setFormat("Queued")
        entry.progress.setTextVisible(True)

        progress_cell = QWidget()
        progress_cell.setStyleSheet("background-color: transparent;")
        progress_layout = QHBoxLayout(progress_cell)
        progress_layout.setContentsMargins(6, 4, 6, 4)
        progress_layout.addWidget(entry.progress)

        entry.action_btn = QPushButton("Cancel")
        entry.action_btn.setToolTip("Cancel this download")
        entry.action_btn.setObjectName("secondary")
        entry.action_btn.setMinimumWidth(84)
        entry.action_btn.clicked.connect(
            lambda _checked=False, eid=entry.id: self._entry_action(eid)
        )

        self.table.setItem(row, 0, entry.title_item)
        self.table.setItem(row, 1, quality_item)
        self.table.setCellWidget(row, 2, progress_cell)
        self.table.setItem(row, 3, entry.speed_item)
        self.table.setItem(row, 4, entry.status_item)
        self.table.setCellWidget(row, 5, entry.action_btn)

    def _fill_slots(self) -> None:
        while self._active_count() < self.max_parallel:
            entry = next(
                (e for e in self._entries.values() if e.state == "queued"), None
            )
            if entry is None:
                break
            connections = self._allocate_connections()
            if connections is None:
                # Every connection in the shared budget is in use; this file
                # stays queued until one of the running jobs frees some.
                break
            self._start_job(entry, connections)

    def _allocate_connections(self) -> Optional[int]:
        used = sum(
            e.connections
            for e in self._entries.values()
            if e.state in ("downloading", "cancelling")
        )
        available = TOTAL_CONNECTION_BUDGET - used
        if available < MIN_JOB_CONNECTIONS:
            return None
        return max(
            MIN_JOB_CONNECTIONS,
            min(self.connections, available),
        )

    def _start_job(self, entry: DownloadEntry, connections: int) -> None:
        entry.state = "downloading"
        entry.connections = connections
        if entry.action_btn is not None:
            entry.action_btn.setText("Cancel")
            entry.action_btn.setToolTip("Cancel this download")
        if entry.status_item is not None:
            entry.status_item.setText("Starting…")
        if entry.progress is not None:
            entry.progress.setFormat("%p%")

        entry.job = downloader.DownloadJob(
            entry.url,
            entry.output_dir,
            entry.quality,
            use_cookies=entry.use_cookies,
            browser=entry.browser,
            max_connections=entry.connections,
            on_status=lambda s, i=entry.id: self.bridge.status.emit(i, s),
            on_progress=lambda p, i=entry.id: self.bridge.progress.emit(i, p),
            on_done=lambda p, i=entry.id: self.bridge.done.emit(i, p),
            on_error=lambda e, i=entry.id: self.bridge.error.emit(i, e),
        )
        entry.job.start()

    def _entry_action(self, entry_id: int) -> None:
        entry = self._entry(entry_id)
        if entry is None:
            return
        if entry.state in ("failed", "cancelled"):
            self._retry_entry(entry)
            return
        if entry.state == "finished":
            target = (
                Path(entry.path).parent
                if entry.path
                else Path(entry.output_dir)
            )
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
            return
        self._cancel_entry(entry)

    def _retry_entry(self, entry: DownloadEntry) -> None:
        other = self._find_active_by_url(entry.url)
        if other is not None and other is not entry:
            self._set_status(
                "Another copy of that video is still downloading.", error=True
            )
            return
        entry.state = "queued"
        entry.path = None
        entry.error = ""
        entry.connections = 0
        entry.job = None
        entry.summarized = False
        if entry.progress is not None:
            entry.progress.setRange(0, 100)
            entry.progress.setValue(0)
            entry.progress.setFormat("Queued")
        if entry.speed_item is not None:
            entry.speed_item.setText("-")
        if entry.status_item is not None:
            entry.status_item.setText("Queued")
            entry.status_item.setToolTip(entry.url)
        if entry.action_btn is not None:
            entry.action_btn.setText("Cancel")
            entry.action_btn.setToolTip("Cancel this download")
        self._fill_slots()
        self._update_status()

    def on_retry_failed(self) -> None:
        failed = [e for e in self._entries.values() if e.state == "failed"]
        if not failed:
            return
        self._last_error = ""
        skipped = 0
        for entry in failed:
            other = self._find_active_by_url(entry.url)
            if other is not None and other is not entry:
                skipped += 1
                continue
            self._retry_entry(entry)
        self._update_status()
        if skipped:
            self._set_status(
                f"Retried failed downloads — {skipped} already running.", error=True
            )

    def _cancel_entry(self, entry: DownloadEntry) -> None:
        if entry.state == "queued":
            entry.state = "cancelled"
            if entry.status_item is not None:
                entry.status_item.setText("Cancelled")
            if entry.speed_item is not None:
                entry.speed_item.setText("-")
            if entry.progress is not None:
                entry.progress.setFormat("Cancelled")
            if entry.action_btn is not None:
                entry.action_btn.setText("Retry")
                entry.action_btn.setToolTip("Retry this download")
            self._update_status()
            self._maybe_show_summary()
            return
        if entry.state == "downloading" and entry.job is not None:
            entry.state = "cancelling"
            if entry.status_item is not None:
                entry.status_item.setText("Cancelling…")
            entry.job.cancel()

    def on_cancel_all(self) -> None:
        for entry in list(self._entries.values()):
            if entry.state in ("downloading", "queued", "cancelling"):
                self._cancel_entry(entry)
        self._update_status()

    def on_clear_finished(self) -> None:
        for entry_id, entry in list(self._entries.items()):
            if entry.state not in TERMINAL_STATES:
                continue
            if entry.title_item is not None:
                row = self.table.row(entry.title_item)
                if row >= 0:
                    self.table.removeRow(row)
            del self._entries[entry_id]
        self._update_status()

    def on_settings(self) -> None:
        dialog = SettingsDialog(
            self,
            parallel=self.max_parallel,
            connections=self.connections,
            notify=self.notify_enabled,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.max_parallel = dialog.parallel_spin.value()
        self.connections = int(dialog.connections_combo.currentData())
        self.notify_enabled = dialog.notify_check.isChecked()

        settings = QSettings()
        settings.setValue("downloads/max_parallel", self.max_parallel)
        settings.setValue("downloads/connections", self.connections)
        settings.setValue(
            "downloads/notify", "true" if self.notify_enabled else "false"
        )
        settings.sync()

        self._fill_slots()
        self._update_status()

    # ---------- download callbacks ----------

    def _status(self, entry_id: int, message: str) -> None:
        entry = self._entry(entry_id)
        if entry is None or entry.state in TERMINAL_STATES:
            return
        if entry.status_item is not None:
            entry.status_item.setText(message)
            entry.status_item.setToolTip(message)

    def _progress(self, entry_id: int, payload: dict) -> None:
        entry = self._entry(entry_id)
        if entry is None or entry.state != "downloading":
            return

        title = payload.get("title")
        if title:
            self._set_title(entry, str(title))

        phase = payload.get("phase") or "download"
        percent = payload.get("percent")

        if phase == "processing":
            if entry.progress is not None:
                entry.progress.setValue(100)
                entry.progress.setFormat("Processing")
            if entry.speed_item is not None:
                entry.speed_item.setText("-")
            if entry.status_item is not None:
                entry.status_item.setText("Merging…")
            return

        if entry.progress is not None:
            if percent is not None:
                entry.progress.setValue(int(percent))
                entry.progress.setFormat(f"{int(percent)}%")
            else:
                entry.progress.setFormat("…")

        if entry.status_item is not None:
            labels = {
                "video": "Downloading video",
                "audio": "Downloading audio",
            }
            entry.status_item.setText(labels.get(phase, "Downloading"))

        if entry.speed_item is not None:
            bits = []
            speed = payload.get("speed")
            if speed:
                bits.append(f"{speed / (1024 * 1024):.1f} MB/s")
            eta = payload.get("eta")
            if eta is not None:
                bits.append(f"ETA {_fmt_duration(eta)}")
            entry.speed_item.setText("  ·  ".join(bits) if bits else "-")

    def _done(self, entry_id: int, path: str) -> None:
        entry = self._entry(entry_id)
        if entry is None:
            return
        entry.state = "finished"
        entry.path = path
        entry.error = ""
        if entry.progress is not None:
            entry.progress.setValue(100)
            entry.progress.setFormat("100%")
        if entry.speed_item is not None:
            entry.speed_item.setText("-")
        if entry.status_item is not None:
            entry.status_item.setText("Finished")
            entry.status_item.setToolTip(path)
        if entry.action_btn is not None:
            entry.action_btn.setText("Open")
            entry.action_btn.setToolTip("Open containing folder")

        self._notify("Download finished", entry.title)
        self._after_terminal()

    def _error(self, entry_id: int, message: str) -> None:
        entry = self._entry(entry_id)
        if entry is None:
            return

        cancelled = entry.state == "cancelling" or message.strip().lower().startswith(
            "download cancelled"
        )
        if cancelled:
            entry.state = "cancelled"
            if entry.status_item is not None:
                entry.status_item.setText("Cancelled")
            if entry.speed_item is not None:
                entry.speed_item.setText("-")
            if entry.progress is not None:
                entry.progress.setFormat("Cancelled")
        else:
            entry.state = "failed"
            entry.error = message
            self._last_error = f"{entry.title}: {message}"
            if entry.status_item is not None:
                entry.status_item.setText("Failed")
                entry.status_item.setToolTip(message)
            if entry.speed_item is not None:
                entry.speed_item.setText("-")
            if entry.progress is not None:
                entry.progress.setFormat("Failed")
            self._notify("Download failed", f"{entry.title}: {message}")

        if entry.action_btn is not None:
            entry.action_btn.setText("Retry")
            entry.action_btn.setToolTip("Retry this download")
        self._after_terminal()

    def _after_terminal(self) -> None:
        self._fill_slots()
        self._update_status()
        if not any(
            e.state in ("downloading", "queued", "cancelling")
            for e in self._entries.values()
        ):
            self._maybe_show_summary()

    def _maybe_show_summary(self) -> None:
        if self._summary_open:
            return
        if any(
            e.state in ("downloading", "queued", "cancelling")
            for e in self._entries.values()
        ):
            return

        pending = [
            e
            for e in self._entries.values()
            if e.state in TERMINAL_STATES and not e.summarized
        ]
        if not pending:
            return

        for entry in pending:
            entry.summarized = True

        finished = [e for e in pending if e.state == "finished"]
        failed = [e for e in pending if e.state == "failed"]
        if not finished and not failed:
            return

        self._summary_open = True
        try:
            box = QMessageBox(self)
            box.setWindowTitle("Downloads finished")
            box.setIcon(
                QMessageBox.Icon.Warning if failed else QMessageBox.Icon.Information
            )
            summary = f"{len(finished)} download(s) finished."
            if failed:
                summary += f" {len(failed)} failed."
            box.setText(summary)

            lines = [f"• {Path(e.path).name}" for e in finished[:8]]
            if len(finished) > 8:
                lines.append(f"…and {len(finished) - 8} more")
            if lines:
                box.setInformativeText("\n".join(lines))
            if failed:
                box.setDetailedText(
                    "\n\n".join(f"{e.title}\n{e.error}" for e in failed)
                )

            open_btn = box.addButton(
                "Open folder", QMessageBox.ButtonRole.ActionRole
            )
            retry_btn = None
            if failed:
                retry_btn = box.addButton(
                    "Retry failed", QMessageBox.ButtonRole.ActionRole
                )
            close_btn = box.addButton(QMessageBox.StandardButton.Close)
            box.setDefaultButton(close_btn)
            box.exec()

            clicked = box.clickedButton()
            if clicked == open_btn:
                if finished:
                    target = Path(finished[0].path).parent
                else:
                    target = Path(pending[0].output_dir)
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
            elif retry_btn is not None and clicked == retry_btn:
                QTimer.singleShot(0, self.on_retry_failed)
        finally:
            self._summary_open = False

        if any(
            e.state in TERMINAL_STATES and not e.summarized
            for e in self._entries.values()
        ):
            QTimer.singleShot(0, self._maybe_show_summary)

    # ---------- close ----------

    def closeEvent(self, event) -> None:  # noqa: N802
        running = [
            e
            for e in self._entries.values()
            if e.state in ("downloading", "queued", "cancelling")
        ]
        if running:
            answer = QMessageBox.question(
                self,
                "Downloads in progress",
                f"{len(running)} download(s) are still running or queued. "
                "Quit anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for entry in running:
                if entry.job is not None:
                    entry.job.cancel()
        if self.tray is not None:
            self.tray.hide()
        event.accept()
