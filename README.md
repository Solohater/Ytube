# You-T

A simple desktop video downloader — paste a URL, pick a quality, save to disk.
Built with Python + PySide6, powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp).
ffmpeg is bundled, so there is nothing else to install.

## Features

- Paste any URL, fetch title/duration first ("Fetch info")
- Quality picker: Best / 1080p / 720p / 480p / 360p (merged to MP4)
- **Download queue**: add links one after another; up to 3 files download at
  once (configurable) with per-file progress, speed/ETA and cancel
- Parallel fragment downloads with a shared connection budget (configurable)
- Desktop notification when a file finishes, plus a summary popup with an
  "Open folder" button when the whole queue is done
- Saves to a folder of your choice (default `~/Downloads`)
- "Use cookies from browser" option — fixes YouTube's bot-check / 403 errors
- Automatic retries with backoff for network/DNS outages, preserving partial
  progress, plus one fresh retry for stale-resume errors (e.g. HTTP 403)
- **Retry failed** button to re-queue every failed download at once
- Dark UI, light app icon

## Install

**Linux** — download `You-T-<version>-x86_64.AppImage` from
[Releases](https://github.com/Solohater/Ytube/releases), then:

```bash
chmod +x You-T-*-x86_64.AppImage
./You-T-*-x86_64.AppImage
```

If your system has no FUSE, run it with
`./You-T-*.AppImage --appimage-extract-and-run`.
A `.tar.gz` with the same app is also published.

On **Wayland** (e.g. Ubuntu/GNOME) the dock only shows the real icon when the app
is registered with the desktop. Run this once after downloading:

```bash
./install.sh /path/to/You-T-*-x86_64.AppImage
```

That copies the AppImage to `~/.local/opt/you-t/`, installs the `.desktop` entry
and icons, and adds **You-T** to your app menu. Remove it later with
`./install.sh --uninstall`.

**Windows** — download `You-T-<version>-win64.zip`, extract it anywhere, and run
`You-T.exe`. The build is unsigned, so SmartScreen may ask for confirmation
("More info" → "Run anyway"). The exe icon is embedded; no install step needed.

## Using the app

1. Paste a URL and press **Fetch info** (optional but shows the title).
2. Pick a quality/folder and press **Download**.
3. The URL box clears immediately — paste the next link and press **Download**
   again. Up to 3 files run at once; the rest wait in the queue.
4. Each row has its own progress, speed/ETA and **Cancel** button.
5. When a file completes you get a notification; when the queue drains you get a
   summary popup with **Open folder**.

**Settings** (top right) controls simultaneous downloads (1–5), connections per
file (8–32) and finish notifications. Connections are shared: while several
files run, each gets a smaller slice of the total budget to avoid YouTube
throttling.

## Run from source

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python main.py
```

Requires Python 3.11+ (tested on 3.14) and a desktop session. For source runs,
`ffmpeg` must be on `PATH`; packaged builds use their bundled copy.

## Build installers

Both scripts fetch a static **LGPL** ffmpeg build into `vendor/ffmpeg/`
(gitignored) and bundle it with the app.

**Linux** — produces an AppImage and a tarball in `dist/`:

```bash
./venv/bin/pip install -r requirements-build.txt
./build.sh
```

**Windows** (PowerShell) — produces `dist/You-T-<version>-win64.zip`:

```powershell
python -m pip install -r requirements-build.txt
./build.ps1
```

CI builds both platforms on every `v*` tag and attaches the artifacts to the
GitHub release. To cut a release:

```bash
# bump VERSION first
git tag v1.1.0
git push origin v1.1.0
```

Regenerate icons after editing `assets/icon.svg`:

```bash
./venv/bin/python tools/make_icon.py
```

## Troubleshooting

**"Sign in to confirm you're not a bot" / HTTP 403 / only low quality downloads**

YouTube gates many requests behind proof-of-origin checks. In the app:

1. Open YouTube in Chrome or Firefox (ideally logged in) and leave it closed afterwards.
2. Tick **"Use cookies from browser"** and pick that browser.
3. Retry. Also keep yt-dlp current — packaged builds ship a fixed version, so
   use a newer release of You-T when YouTube changes.

**"The page needs to be reloaded" / "Requested format is not available"**

A known yt-dlp/YouTube issue ([#17389](https://github.com/yt-dlp/yt-dlp/issues/17389))
triggered by **account cookies** — all cookie-using player clients either error or
return zero formats on current YouTube. The app detects this and automatically
retries without cookies. If you still see it, leave "Use cookies" unticked.

**"Temporary failure in name resolution" / Errno -3 / Errno -2**

The system could not resolve YouTube's servers — a momentary DNS or network
outage, not a cookies/YouTube problem. The app waits and retries automatically
(5 s, 15 s, 30 s) and keeps partial downloads. If it still fails, check your
Wi-Fi/VPN/DNS, then press **Retry** on the row or **Retry failed** to resume.

**Downloads fail after weeks of working**

YouTube changes frequently; update You-T (and therefore yt-dlp) to the latest release.

**GUI crashes on startup with a GLib/GSettings error**

Some shells (e.g. launched from VS Code's snap) inject a stale GSettings schema
directory that makes GTK abort. `main.py` repairs this automatically at launch;
if you run `ui.py` directly you won't get that fix.

## Licensing

You-T is provided for educational/personal use. It bundles an LGPL build of
ffmpeg from [BtbN/FFmpeg-Builds](https://github.com/BtbN/FFmpeg-Builds); see
that project for source and license details. yt-dlp is distributed under the
Unlicense.

Downloading videos may violate YouTube's Terms of Service and/or copyright law.
Only download content you own or have permission to download (e.g. your own
uploads, Creative Commons videos, public-domain content).
