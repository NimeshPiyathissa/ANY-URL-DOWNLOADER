# Asynchronous Telegram Direct URL, HLS/DASH & Zoom Downloader Bot (4GB Hybrid Edition)

A high-performance, production-ready Telegram Bot built with **Python 3.12+**, **Pyrofork MTProto**, **aiohttp**, **yt-dlp**, and **FFmpeg**.

It features an intelligent **4GB Hybrid Upload Architecture**:
- **<= 2.0 GB:** Handled directly by the Bot via Pyrogram MTProto.
- **2.0 GB – 4.0 GB:** Relayed via a secondary **Telegram Premium** user session client through a private dump channel and copied directly to the user.

---

## 🚀 Key Features

1. **4GB Hybrid Upload Engine:**
   - Standard bot uploads are restricted by Telegram to 2GB.
   - By attaching an optional `USER_SESSION_STRING` (from a Telegram Premium account) and a `DUMP_CHAT_ID`, the bot dynamically scales up its max upload limit from **2.0 GB** to **4.0 GB**.
   - Seamlessly uses `compose([bot, user_app])` to run both clients asynchronously in the same process.

2. **Direct URL Streaming Downloader:**
   - Asynchronous streaming downloads via `aiohttp` and `aiofiles`.
   - Custom filename override support: `URL | custom_name.ext`.
   - Automatic RFC 5987 / RFC 6266 `Content-Disposition` header decoding.
   - Dynamic size-capping check (rejects files exceeding 2GB/4GB before consuming server bandwidth).

3. **HLS / DASH Stream Downloader (.m3u8 / .mpd):**
   - Automatically detects `.m3u8` and `.mpd` streaming manifest URLs (ignoring query parameters).
   - Downloads all segments concurrently (`concurrent_fragment_downloads: 4`) and merges into a single `.mp4` file.
   - Smart filename derivation: for `master.m3u8` / `index.m3u8`, the URL-decoded parent folder name becomes the filename (supports Sinhala/Unicode folder names).
   - Custom filename override: `URL | custom_name.mp4`.

4. **Zoom Cloud Recording Downloader:**
   - Supports `zoom.us/rec/...` and `zoom.us/recording/...` links.
   - Passcode protection support via `URL | passcode` or `URL | passcode | filename.mp4`.
   - Merges video and audio streams to MP4 using `yt-dlp` in worker threads (`asyncio.to_thread`).
   - Browser headers and optional Netscape-format `cookies.txt` support to bypass HTTP 403 Forbidden restrictions.

5. **Real-time Throttled Progress Bar:**
   - Non-blocking visual progress bar with percentage, speed (`MB/s`), processed/total bytes, ETA, and filename.
   - Built-in throttling (`PROGRESS_UPDATE_INTERVAL=3.5s`) to prevent Telegram `FloodWait` penalties.

6. **FFmpeg Video Metadata & Native Streaming:**
   - Asynchronous `ffprobe` metadata extraction (duration, width, height, handling 90°/270° orientation tags).
   - Asynchronous `ffmpeg` thumbnail generator (max width 320px).
   - Fast video streaming enabled with `supports_streaming=True`.
   - Automatic fallback to `send_document` for non-video files or incompatible codecs.

7. **Concurrency & Workspace Cleanup:**
   - Concurrency managed via `asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)`.
   - Isolated temporary workspaces (`downloads/{task_id}/`).
   - Workspace cleanup in `finally:` blocks guarantees zero orphaned files even on crash or cancellation.

8. **Access Control:**
   - Restrict access to specific Telegram users via `AUTHORIZED_USERS`.

---

## 📁 Project Architecture

```
├── bot.py                # Main application: dual client MTProto engine & hybrid upload logic
├── downloader.py         # Async direct HTTP stream, HLS/DASH & yt-dlp Zoom downloader
├── utils.py              # FFmpeg/FFprobe async metadata, thumbnails, formatters, cleanup
├── config.py             # Environment configuration & dynamic 2GB/4GB limit resolver
├── test_suite.py         # Test suite covering utilities, formatters, stream detection & limits
├── requirements.txt      # Python dependencies (pyrofork, tgcrypto, aiohttp, yt-dlp, etc.)
├── .env.example          # Environment variables template
├── .gitignore            # Git ignore rules for secrets, downloads, and cache
└── README.md             # Complete documentation
```

---

## 🛠️ Step-by-Step Setup Guide

### 1. Prerequisites (Ubuntu / Debian Server)

Install Python 3.12+, FFmpeg, and build essentials for cryptographic acceleration:

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv ffmpeg build-essential python3-dev
```

Verify FFmpeg installation:
```bash
ffmpeg -version
ffprobe -version
```

---

### 2. Clone and Setup Environment

```bash
# Clone the repository
git clone <your-repository-url>
cd <repository-directory>

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

### 3. Enable 4GB Uploads (Optional)

If you have a Telegram Premium account and want to unlock 4GB uploads:

1. Generate a Pyrofork/Pyrogram session string using any standard method (e.g., [Replit Session Generator](https://replit.com/@AshutoshGoswami24/Pyrogram-Session-Generator), or run `Client.export_session_string()` in a local Python script).
2. Paste the exported session string into `USER_SESSION_STRING` in your `.env` file.
3. Create a private Telegram channel, add **both** the bot and the Premium user account as administrators, and set the channel ID as `DUMP_CHAT_ID`.

> **Without `USER_SESSION_STRING`:** The bot runs cleanly in standard 2GB mode — no errors, no extra configuration needed.

---

### 4. Configure Environment Variables (`.env`)

Copy the template:
```bash
cp .env.example .env
```

Open `.env` in an editor:
```bash
nano .env
```

Fill in the parameters:
```env
# Required Telegram API credentials (from https://my.telegram.org)
API_ID=12345678
API_HASH=0123456789abcdef0123456789abcdef

# Required Telegram Bot Token (from @BotFather)
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_1234567

# Optional: Telegram Premium Session String (Unlocks 4GB uploads)
# Leave empty for standard 2GB bot mode. Paste the string here to enable 4GB.
USER_SESSION_STRING=

# Optional: Dump / Relay Channel ID (Required for 4GB uploads to relay files)
# Create a private Telegram channel, add BOTH your bot and user account as administrators,
# and get its ID (e.g. -1001234567890).
DUMP_CHAT_ID=

# Optional: Comma-separated authorized Telegram User IDs (leave blank for public access)
AUTHORIZED_USERS=123456789,987654321

# Performance and Concurrency
MAX_CONCURRENT_DOWNLOADS=3
PROGRESS_UPDATE_INTERVAL=3.5
DOWNLOAD_DIR=downloads
```

---

### 5. Running the Bot

#### Test Locally:
```bash
python bot.py
```

#### Production Deployment with Systemd (Ubuntu):

Create a systemd service file:
```bash
sudo nano /etc/systemd/system/telegram-downloader.service
```

Paste the following configuration (replace paths and user with your setup):
```ini
[Unit]
Description=Telegram Direct URL and Zoom Downloader Bot (4GB Hybrid)
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/telegram-downloader
ExecStart=/opt/telegram-downloader/venv/bin/python bot.py
Restart=always
RestartSec=10
EnvironmentFile=/opt/telegram-downloader/.env

# Security Hardening
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-downloader
sudo systemctl status telegram-downloader
```

View real-time logs:
```bash
sudo journalctl -u telegram-downloader -f
```

---

## 💡 Telegram Command & Input Syntax

### Commands
- `/start` - Welcome message and upload mode status.
- `/help` - Syntax reference and usage examples.
- `/status` - Live concurrency, 2GB/4GB status, relay health, and access mode.

### 1. Direct URLs
- **Standard download:**
  ```text
  https://releases.ubuntu.com/24.04/ubuntu-24.04-desktop-amd64.iso
  ```
- **Custom filename:**
  ```text
  https://example.com/files/archive.zip | production_backup.zip
  ```

### 2. HLS / DASH Streams
- **Auto-detected filename from URL path:**
  ```text
  https://cdn.example.com/videos/Lecture%2001/master.m3u8
  ```
- **Custom filename:**
  ```text
  https://cdn.example.com/stream/index.m3u8 | my_video.mp4
  ```

### 3. Zoom Cloud Recordings
- **Public recording:**
  ```text
  https://us02web.zoom.us/rec/share/abc123xyz
  ```
- **Passcode-protected recording:**
  ```text
  https://us02web.zoom.us/rec/share/abc123xyz | SecretPass123
  ```
- **Passcode + Custom filename:**
  ```text
  https://us02web.zoom.us/rec/share/abc123xyz | SecretPass123 | Lecture_01.mp4
  ```

---

## 🧪 Running Unit Tests

Run the included verification suite:
```bash
python test_suite.py
```
