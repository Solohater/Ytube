"""GUI-agnostic download engine wrapping yt-dlp."""

from __future__ import annotations

import hashlib
import re
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import yt_dlp

import runtime

QUALITY_CHOICES = ("Best", "1080p", "720p", "480p", "360p")
BROWSER_CHOICES = ("chrome", "firefox", "brave", "edge", "chromium", "vivaldi", "opera")

# DASH/HLS videos are split into fragments. Downloading them in parallel is the
# single biggest speed win; 24 is aggressive but well tolerated by YouTube.
CONCURRENT_FRAGMENTS = 24
MIN_CONNECTIONS = 8
MAX_CONNECTIONS = 32
HTTP_CHUNK_SIZE = 10 * 1024 * 1024
BUFFER_SIZE = 1024 * 1024

# DNS/network outages are often momentary; wait a little before each retry so
# a resolver or VPN can come back instead of hammering it immediately.
NETWORK_RETRY_DELAYS = (5, 15, 30)


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
    if (
        "temporary failure in name resolution" in low
        or "errno -3" in low
        or "name or service not known" in low
        or "nodename nor servname" in low
        or "getaddrinfo failed" in low
    ):
        return (
            "Could not reach YouTube's servers (DNS/network hiccup). Check your "
            "Wi-Fi/VPN/DNS, then hit Retry — partial progress is kept."
        )
    if "network is unreachable" in low or "errno 101" in low:
        return (
            "The network connection dropped mid-download. Check Wi-Fi/VPN, then "
            "hit Retry to restart it."
        )
    if "no such file or directory" in low or "errno 2" in low:
        return (
            "A temporary fragment file disappeared. This usually means the same "
            "video was downloading twice into the same folder. Remove the other "
            "copy, then hit Retry."
        )
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


def _base_opts(
    use_cookies: bool = False,
    browser: Optional[str] = None,
    max_connections: int = CONCURRENT_FRAGMENTS,
    force_ipv4: bool = False,
) -> dict:
    connections = max(MIN_CONNECTIONS, min(MAX_CONNECTIONS, int(max_connections)))
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "retries": 5,
        "fragment_retries": 5,
        "file_access_retries": 5,
        "socket_timeout": 30,
        "concurrent_fragment_downloads": connections,
        "http_chunk_size": HTTP_CHUNK_SIZE,
        "buffersize": BUFFER_SIZE,
        "logger": _QuietLogger(),
    }
    if force_ipv4:
        # Some networks advertise IPv6 without a working route, which surfaces
        # as "[Errno 101] Network is unreachable".
        opts["source_address"] = "0.0.0.0"
    ffmpeg = runtime.ffmpeg_location()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
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


_NETWORK_MARKERS = (
    "temporary failure in name resolution",
    "errno -3",
    "errno -2",
    "name or service not known",
    "nodename nor servname",
    "getaddrinfo failed",
    "network is unreachable",
    "errno 101",
    "connection reset",
    "connection refused",
    "timed out",
    "incomplete read",
    "unable to download video data",
)


def _is_network_error(message: str) -> bool:
    low = message.lower()
    return any(marker in low for marker in _NETWORK_MARKERS)


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
            "connection refused",
            "unable to download video data",
            "incomplete read",
            "temporary failure",
            "network is unreachable",
            "errno 101",
            "temporary failure in name resolution",
            "name or service not known",
            "no such file or directory",
            "errno 2",
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
        max_connections: int = CONCURRENT_FRAGMENTS,
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
        self.max_connections = max_connections
        self.on_status = on_status or (lambda s: None)
        self.on_progress = on_progress or (lambda p: None)
        self.on_done = on_done or (lambda p: None)
        self.on_error = on_error or (lambda e: None)
        self._cancelled = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._temp_dir: Optional[str] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _emit_progress(self, percent, speed, eta, phase, title=None):
        try:
            self.on_progress(
                {
                    "percent": percent,
                    "speed": speed,
                    "eta": eta,
                    "phase": phase,
                    "title": title,
                }
            )
        except Exception:
            pass

    def _hook(self, d: dict) -> None:
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
            title = info.get("title")
            self._emit_progress(percent, d.get("speed"), d.get("eta"), phase, title)
        elif status == "finished":
            info = d.get("info_dict") or {}
            self._emit_progress(100, None, None, "processing", info.get("title"))

    def _cleanup_temp(self) -> None:
        if not self._temp_dir:
            return
        temp_dir = Path(self._temp_dir)
        root = temp_dir.parent
        shutil.rmtree(temp_dir, ignore_errors=True)
        self._temp_dir = None
        try:
            root.rmdir()  # only succeeds when no other job is using it
        except OSError:
            pass

    def _cleanup_orphans(self, video_id: Optional[str]) -> None:
        """Remove stream/part files left by older interrupted downloads."""
        if not video_id:
            return
        pattern = re.compile(
            rf"\[{re.escape(video_id)}\]"
            rf"\.f\d+(?:-\d+)?\.[A-Za-z0-9]+"
            rf"(?:\.part)?(?:-Frag\d+(?:\.part)?)?$"
        )
        ytdl = f"[{video_id}].ytdl"
        cutoff = time.time() - 600
        try:
            entries = list(Path(self.output_dir).iterdir())
        except OSError:
            return
        for entry in entries:
            if not entry.is_file():
                continue
            if not (pattern.search(entry.name) or entry.name.endswith(ytdl)):
                continue
            try:
                # Never touch a file another job may still be writing to.
                if entry.stat().st_mtime > cutoff:
                    continue
                entry.unlink()
            except OSError:
                pass

    def _run(self) -> None:
        self.on_status("Starting download…")
        attempt = 1
        network_retry = 0
        reuse_temp = False
        while True:
            try:
                self._attempt(attempt, reuse_temp=reuse_temp)
                return
            except CancelledError:
                self._cleanup_temp()
                self.on_error("Download cancelled.")
                return
            except Exception as exc:  # noqa: BLE001
                if self._cancelled.is_set():
                    self._cleanup_temp()
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
                    self._cleanup_temp()
                    self.on_status("Cookies rejected by YouTube — retrying without cookies…")
                    attempt += 1
                    reuse_temp = False
                    continue
                if _is_network_error(msg):
                    if network_retry < len(NETWORK_RETRY_DELAYS):
                        delay = NETWORK_RETRY_DELAYS[network_retry]
                        network_retry += 1
                        self.on_status(
                            f"Network/DNS problem — retrying in {delay}s…"
                        )
                        if self._cancelled.wait(delay):
                            self._cleanup_temp()
                            self.on_error("Download cancelled.")
                            return
                        # Keep the temp dir so completed fragments survive the
                        # outage and yt-dlp can resume instead of starting over.
                        reuse_temp = True
                        attempt += 1
                        continue
                    # Keep the temp dir so a manual Retry can resume from the
                    # fragments already downloaded before the outage.
                    self.on_error(friendly_error(msg))
                    return
                if _is_transient(msg):
                    # A stale .part from an earlier session can trigger
                    # HTTP 403 (expired media URL). Retry with a fresh temp dir.
                    self._cleanup_temp()
                    self.on_status("Download hit a snag — retrying fresh…")
                    attempt += 1
                    reuse_temp = False
                    continue
                self._cleanup_temp()
                self.on_error(friendly_error(msg))
                return

    def _make_temp_dir(self) -> str:
        """Return a stable per-URL dir so a later Retry can resume fragments."""
        root = Path(self.output_dir) / ".you-t-tmp"
        root.mkdir(parents=True, exist_ok=True)
        self._purge_stale_temp_dirs(root)
        key = hashlib.sha1(self.url.encode("utf-8")).hexdigest()[:16]
        path = root / f"job-{key}"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    @staticmethod
    def _purge_stale_temp_dirs(root: Path) -> None:
        """Drop stream files abandoned by a crash or a hard kill."""
        cutoff = time.time() - 86400
        try:
            entries = list(root.iterdir())
        except OSError:
            return
        for entry in entries:
            try:
                if entry.is_dir() and entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
            except OSError:
                pass

    def _attempt(self, attempt: int, *, reuse_temp: bool = False) -> None:
        # A brand-new job reuses its per-URL temp dir so interrupted downloads
        # resume. Only deliberate fresh retries (cookies/403) wipe it.
        if not reuse_temp and attempt > 1:
            self._cleanup_temp()
        if not self._temp_dir:
            self._temp_dir = self._make_temp_dir()
        if attempt == 1:
            connections = self.max_connections
        else:
            # Retry more gently: fewer sockets makes a flaky link less likely to
            # drop again, and IPv4 avoids IPv6-only routes that don't exist.
            connections = MIN_CONNECTIONS
        opts = _base_opts(
            self.use_cookies,
            self.browser,
            connections,
            force_ipv4=attempt > 1,
        )
        opts.update(
            {
                "format": format_spec(quality_to_height(self.quality)),
                "merge_output_format": "mp4",
                # Keep this template relative: yt-dlp ignores "paths" entirely
                # when outtmpl is absolute, which would put .part/-Frag files
                # in the output folder and let parallel jobs collide.
                "outtmpl": "%(title).200B [%(id)s].%(ext)s",
                "paths": {
                    "home": self.output_dir,
                    "temp": self._temp_dir,
                },
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
        if not Path(path).is_file():
            raise RuntimeError("Download finished but the output file is missing.")

        self._cleanup_temp()
        self._cleanup_orphans(info.get("id"))
        self.on_done(path)
