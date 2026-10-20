"""GUI-agnostic download engine wrapping yt-dlp."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

QUALITY_CHOICES = ("Best", "1080p", "720p", "480p", "360p")
BROWSER_CHOICES = ("chrome", "firefox", "brave", "edge", "chromium", "vivaldi", "opera")


class CancelledError(Exception):
    """Raised inside progress hooks when the user cancels."""


def quality_to_height(quality: str) -> Optional[int]:
    return None if quality == "Best" else int(quality.rstrip("p"))


def format_spec(max_height: Optional[int]) -> str:
    if max_height is None:
        return "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b"
    h = max_height
    return (
        f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]"
        f"/bv*[height<={h}]+ba"
        f"/b[height<={h}][ext=mp4]"
        f"/b[height<={h}]"
    )


def friendly_error(message: str) -> str:
    low = message.lower()
    if "page needs to be reloaded" in low:
        return (
            "YouTube rejected the request (known yt-dlp/YouTube issue). "
            "Untick \"Use cookies from browser\" and retry; keep yt-dlp updated."
        )
    if "requested format is not available" in low or "no video formats" in low:
        return (
            "YouTube didn't provide any downloadable formats (usually a cookies/"
            "proof-of-origin gate). Try unticking cookies and retry; "
            "if it persists, update yt-dlp."
        )
    if "sign in to confirm" in low or "not a bot" in low:
        return (
            "YouTube flagged the request as a bot. Enable \"Use cookies from browser\" "
            "in Settings (with YouTube open/logged in in that browser), then retry."
        )
    if "po token" in low:
        return (
            "YouTube needs a proof-of-origin token. Update yt-dlp and enable "
            "\"Use cookies from browser\", then retry."
        )
    if "403" in low or "forbidden" in low:
        return "YouTube refused the request (403). Update yt-dlp, enable cookies, and retry."
    if "unsupported url" in low:
        return "That URL is not supported. Paste a normal video URL."
    if "video is unavailable" in low or "video unavailable" in low:
        return "The video is unavailable (private, deleted, or region-locked)."
    if "secretstorage" in low or "keyring" in low or "dbus" in low:
        return (
            "Couldn't read browser cookies (system keyring unavailable). "
            "Unlock your keyring, choose Firefox instead of Chrome, "
            "or untick \"Use cookies from browser\"."
        )
    if "unable to download video data" in low:
        return "Download failed mid-way. Check your connection and retry."
    return message


class _QuietLogger:
    """Swallows yt-dlp console output; errors still arrive as exceptions."""

    def debug(self, msg: str) -> None:  # noqa: D102
        pass

    def info(self, msg: str) -> None:  # noqa: D102
        pass

    def warning(self, msg: str) -> None:  # noqa: D102
        pass

    def error(self, msg: str) -> None:  # noqa: D102
        pass


def _base_opts(use_cookies: bool = False, browser: Optional[str] = None) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 30,
        "logger": _QuietLogger(),
    }
    if use_cookies and browser:
        opts["cookiesfrombrowser"] = (browser,)
    return opts


def fetch_info(
    url: str,
    *,
    use_cookies: bool = False,
    browser: Optional[str] = None,
) -> dict:
    try:
        return _fetch_info_once(url, use_cookies=use_cookies, browser=browser)
    except Exception:  # noqa: BLE001
        if not use_cookies:
            raise
        # Account cookies often break extraction on current YouTube;
        # fall back to a cookieless request before giving up.
        return _fetch_info_once(url, use_cookies=False, browser=None)


def _fetch_info_once(
    url: str,
    *,
    use_cookies: bool = False,
    browser: Optional[str] = None,
) -> dict:
    opts = _base_opts(use_cookies, browser)
    opts.update({"skip_download": True, "noplaylist": True})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("_type") == "playlist":
        entries = info.get("entries") or []
        if not entries:
            raise RuntimeError("Empty playlist")
        info = entries[0]
    duration = info.get("duration")
    return {
        "title": info.get("title") or "Unknown title",
        "duration": int(duration) if duration else None,
        "uploader": info.get("uploader") or info.get("channel") or "",
        "id": info.get("id") or "",
    }


def _is_transient(message: str) -> bool:
    low = message.lower()
    return any(
        s in low
        for s in (
            "403",
            "forbidden",
            "401",
            "502",
            "503",
            "504",
            "timed out",
            "connection reset",
            "unable to download video data",
            "incomplete read",
            "temporary failure",
        )
    )


class DownloadJob:
    """Runs one download in a background thread with progress callbacks."""

    def __init__(
        self,
        url: str,
        output_dir: str,
        quality: str = "Best",
        *,
        use_cookies: bool = False,
        browser: Optional[str] = None,
        on_status: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[dict], None]] = None,
        on_done: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
    ):
        self.url = url
        self.output_dir = str(output_dir)
        self.quality = quality
        self.use_cookies = use_cookies
        self.browser = browser
        self.on_status = on_status or (lambda s: None)
        self.on_progress = on_progress or (lambda p: None)
        self.on_done = on_done or (lambda p: None)
        self.on_error = on_error or (lambda e: None)
        self._cancelled = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._partial: Optional[str] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _emit_progress(self, percent, speed, eta, phase):
        try:
            self.on_progress(
                {
                    "percent": percent,
                    "speed": speed,
                    "eta": eta,
                    "phase": phase,
                }
            )
        except Exception:
            pass

    def _hook(self, d: dict) -> None:
        filename = d.get("filename")
        if not filename:
            tmp = d.get("tmpfilename")
            if tmp:
                filename = tmp[:-5] if tmp.endswith(".part") else tmp
        if filename:
            self._partial = filename
        if self._cancelled.is_set():
            raise CancelledError()
        status = d.get("status")
        if status == "downloading":
            info = d.get("info_dict") or {}
            vcodec = info.get("vcodec")
            acodec = info.get("acodec")
            if vcodec and vcodec != "none":
                phase = "video"
            elif acodec and acodec != "none":
                phase = "audio"
            else:
                phase = "download"
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            percent = int(done * 100 / total) if total else None
            self._emit_progress(percent, d.get("speed"), d.get("eta"), phase)
        elif status == "finished":
            self._emit_progress(100, None, None, "processing")

    def _cleanup_partial(self) -> None:
        if not self._partial:
            return
        from glob import escape

        path = Path(self._partial)
        parent, name = path.parent, path.name
        if not parent.is_dir():
            return
        for leftover in parent.glob(escape(name) + "*"):
            if leftover.name == name:
                continue
            try:
                leftover.unlink()
            except OSError:
                pass

    def _run(self) -> None:
        self.on_status("Starting download…")
        for attempt in (1, 2):
            try:
                self._attempt(attempt)
                return
            except CancelledError:
                self._cleanup_partial()
                self.on_error("Download cancelled.")
                return
            except Exception as exc:  # noqa: BLE001
                if self._cancelled.is_set():
                    self._cleanup_partial()
                    self.on_error("Download cancelled.")
                    return
                msg = str(exc)
                if "ERROR:" in msg:
                    msg = msg.split("ERROR:", 1)[1].strip()
                if attempt == 1 and self.use_cookies:
                    # Account cookies often break extraction on current
                    # YouTube ("page needs to be reloaded", gated formats).
                    # Fall back to a cookieless attempt before giving up.
                    self.use_cookies = False
                    self._cleanup_partial()
                    self._partial = None
                    self.on_status("Cookies rejected by YouTube — retrying without cookies…")
                    continue
                if attempt == 1 and _is_transient(msg):
                    # A stale .part from an earlier session can trigger
                    # HTTP 403 (expired media URL). Clear it and retry once.
                    self._cleanup_partial()
                    self._partial = None
                    self.on_status("Download hit a snag — retrying fresh…")
                    continue
                self.on_error(friendly_error(msg))
                return

    def _attempt(self, attempt: int) -> None:
        self._partial = None
        opts = _base_opts(self.use_cookies, self.browser)
        opts.update(
            {
                "format": format_spec(quality_to_height(self.quality)),
                "merge_output_format": "mp4",
                "outtmpl": str(
                    Path(self.output_dir) / "%(title).200B [%(id)s].%(ext)s"
                ),
                "progress_hooks": [self._hook],
            }
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(self.url, download=True)

        if info is None:
            raise RuntimeError("Download failed: no video data returned.")

        path = ""
        requested = info.get("requested_downloads") or []
        if requested:
            path = requested[0].get("filepath") or ""
        if not path:
            ext = "mp4"
            path = str(
                Path(self.output_dir)
                / f"{info.get('title', 'video')} [{info.get('id', '')}].{ext}"
            )
        self.on_done(path)
