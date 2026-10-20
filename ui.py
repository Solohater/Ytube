"""PySide6 main window for the You-T downloader."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import downloader

DARK_QSS = """
QWidget {
    background-color: #1e1f24;
    color: #e6e6e6;
    font-size: 14px;
}
QLineEdit, QComboBox {
    background-color: #2a2b31;
    border: 1px solid #3d3e46;
    border-radius: 6px;
    padding: 7px 9px;
    selection-background-color: #3a6ea5;
}
QLineEdit:focus, QComboBox:focus { border-color: #5b8def; }
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
"""


class Bridge(QObject):
    info_ok = Signal(dict)
    info_err = Signal(str)
    status = Signal(str)
    progress = Signal(dict)
    done = Signal(str)
    error = Signal(str)


def _fmt_duration(seconds) -> str:
    if not seconds:
        return ""
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("You-T — Video Downloader")
        self.setMinimumWidth(640)
        self.bridge = Bridge()
        self.job: downloader.DownloadJob | None = None
        self._build_ui()
        self._connect()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("You-T")
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #5b8def;")
        layout.addWidget(title)

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

        # Progress
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready.")
        self.status_label.setObjectName("status")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        # Actions
        btn_row = QHBoxLayout()
        self.download_btn = QPushButton("Download")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.setEnabled(False)
        btn_row.addStretch(1)
        btn_row.addWidget(self.download_btn)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

        note = QLabel(
            "Only download content you have the right to download — "
            "this may violate YouTube's Terms of Service."
        )
        note.setStyleSheet("color: #77787f; font-size: 12px;")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)

        self.setCentralWidget(root)

    def _connect(self) -> None:
        self.fetch_btn.clicked.connect(self.on_fetch)
        self.download_btn.clicked.connect(self.on_download)
        self.cancel_btn.clicked.connect(self.on_cancel)
        self.dir_btn.clicked.connect(self.on_browse)
        self.cookies_check.toggled.connect(self.browser_combo.setEnabled)
        self.url_edit.returnPressed.connect(self.on_fetch)

        self.bridge.info_ok.connect(self._info_ok)
        self.bridge.info_err.connect(self._info_err)
        self.bridge.status.connect(lambda s: self._set_status(s, error=False))
        self.bridge.progress.connect(self._progress)
        self.bridge.done.connect(self._done)
        self.bridge.error.connect(self._error)

    # ---------- helpers ----------

    def _set_status(self, text: str, *, error: bool) -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("error", error)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _validated_url(self) -> str | None:
        url = self.url_edit.text().strip()
        if not url:
            self._set_status("Paste a video URL first.", error=True)
            return None
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.url_edit.setText(url)
        return url

    def _cookies(self) -> tuple[bool, str | None]:
        if self.cookies_check.isChecked():
            return True, self.browser_combo.currentText()
        return False, None

    def _set_busy(self, busy: bool) -> None:
        self.fetch_btn.setEnabled(not busy)
        self.download_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        self.url_edit.setEnabled(not busy)
        self.quality_combo.setEnabled(not busy)
        self.dir_btn.setEnabled(not busy)
        self.cookies_check.setEnabled(not busy)
        self.browser_combo.setEnabled(not busy and self.cookies_check.isChecked())

    # ---------- actions ----------

    def on_browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Choose download folder", self.dir_edit.text()
        )
        if directory:
            self.dir_edit.setText(directory)

    def on_fetch(self) -> None:
        url = self._validated_url()
        if not url:
            return
        use_cookies, browser = self._cookies()
        self.info_label.setText("Fetching video info…")
        self.fetch_btn.setEnabled(False)

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
        self.fetch_btn.setEnabled(True)
        parts = [info["title"]]
        if info.get("uploader"):
            parts.append(info["uploader"])
        if info.get("duration"):
            parts.append(_fmt_duration(info["duration"]))
        self.info_label.setText("  •  ".join(parts))
        self._set_status("Video loaded. Choose quality and hit Download.", error=False)

    def _info_err(self, message: str) -> None:
        self.fetch_btn.setEnabled(True)
        self.info_label.setText("No video loaded.")
        self._set_status(message, error=True)

    def on_download(self) -> None:
        url = self._validated_url()
        if not url:
            return
        output_dir = Path(self.dir_edit.text().strip() or Path.home() / "Downloads")
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._set_status(f"Cannot create folder: {exc}", error=True)
            return
        if self.job is not None and self.job.active:
            return

        use_cookies, browser = self._cookies()
        self.progress_bar.setValue(0)
        self._set_busy(True)

        self.job = downloader.DownloadJob(
            url,
            str(output_dir),
            self.quality_combo.currentText(),
            use_cookies=use_cookies,
            browser=browser,
            on_status=self.bridge.status.emit,
            on_progress=self.bridge.progress.emit,
            on_done=self.bridge.done.emit,
            on_error=self.bridge.error.emit,
        )
        self.job.start()

    def on_cancel(self) -> None:
        if self.job is not None and self.job.active:
            self.job.cancel()
            self._set_status("Cancelling…", error=False)

    def _progress(self, p: dict) -> None:
        percent = p.get("percent")
        if percent is not None:
            self.progress_bar.setValue(percent)
        phase = p.get("phase") or "download"
        bits = []
        if phase == "video":
            bits.append("Downloading video")
        elif phase == "audio":
            bits.append("Downloading audio")
        elif phase == "processing":
            bits.append("Merging / processing")
            self.progress_bar.setValue(100)
        else:
            bits.append("Downloading")
        if percent is not None and phase != "processing":
            bits.append(f"{percent}%")
        speed = p.get("speed")
        if speed:
            mb = speed / (1024 * 1024)
            bits.append(f"{mb:.1f} MB/s")
        eta = p.get("eta")
        if eta is not None:
            bits.append(f"ETA {_fmt_duration(eta)}")
        self.status_label.setProperty("error", False)
        self._set_status("  •  ".join(bits), error=False)

    def _done(self, path: str) -> None:
        self._set_busy(False)
        self.progress_bar.setValue(100)
        self._set_status(f"Saved: {path}", error=False)

    def _error(self, message: str) -> None:
        self._set_busy(False)
        self._set_status(message, error=True)

    # ---------- close ----------

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.job is not None and self.job.active:
            answer = QMessageBox.question(
                self,
                "Download in progress",
                "A download is still running. Quit anyway?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.job.cancel()
        event.accept()
