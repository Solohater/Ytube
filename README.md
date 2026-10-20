# You-T

A simple desktop video downloader for Linux — paste a URL, pick a quality, save to disk.
Built with Python + PySide6, powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp) and ffmpeg.

## Features

- Paste any URL, fetch title/duration first ("Fetch info")
- Quality picker: Best / 1080p / 720p / 480p / 360p (merged to MP4)
- Progress bar with speed + ETA, cancel button (cleans up partial files)
- Saves to a folder of your choice (default `~/Downloads`)
- "Use cookies from browser" option — fixes YouTube's bot-check / 403 errors
- One automatic retry on transient errors (e.g. stale resume → HTTP 403)
- Dark UI

## Requirements

- Linux
- Python 3.11+ (tested on 3.14)
- ffmpeg on PATH (for merging video+audio streams)
  - Debian/Ubuntu: `sudo apt install ffmpeg`

## Run from source

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python main.py
```

## Package a standalone binary (optional)

```bash
./venv/bin/pip install pyinstaller
./venv/bin/pyinstaller --onefile --windowed --name You-T --collect-all yt_dlp main.py
# result: dist/You-T
```

Note: the packaged app still needs `ffmpeg` installed on the target machine.

## Troubleshooting

**"Sign in to confirm you're not a bot" / HTTP 403 / only low quality downloads**

YouTube gates many requests behind proof-of-origin checks. In the app:

1. Open YouTube in Chrome or Firefox (ideally logged in) and leave it closed afterwards.
2. Tick **"Use cookies from browser"** and pick that browser.
3. Retry. Also keep yt-dlp current: `./venv/bin/pip install -U yt-dlp`.

**"The page needs to be reloaded" / "Requested format is not available"**

A known yt-dlp/YouTube issue ([#17389](https://github.com/yt-dlp/yt-dlp/issues/17389))
triggered by **account cookies** — all cookie-using player clients either error or
return zero formats on current YouTube. The app detects this and automatically
retries without cookies. If you still see it, leave "Use cookies" unticked.

**Downloads fail after weeks of working**

YouTube changes frequently; update yt-dlp first — it's the actual engine.

**GUI crashes on startup with a GLib/GSettings error**

Some shells (e.g. launched from VS Code's snap) inject a stale GSettings schema
directory that makes GTK abort. `main.py` repairs this automatically at launch;
if you run `ui.py` directly you won't get that fix.

## Legal note

Downloading videos may violate YouTube's Terms of Service and/or copyright law.
Only download content you own or have permission to download (e.g. your own
uploads, Creative Commons videos, public-domain content). This tool is provided
for educational/personal-use purposes.
