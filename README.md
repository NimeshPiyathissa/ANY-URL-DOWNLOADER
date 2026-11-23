<p align="center">
  <img src="assets/banner.gif" alt="Any URL, HLS & Zoom Downloader Bot" width="100%"/>
</p>

<h1 align="center">⚡ ANY URL, HLS (.m3u8) & ZOOM DOWNLOADER BOT</h1>

<p align="center">
  <b>Enterprise-Grade Asynchronous Telegram Bot with 4GB Hybrid Upload Architecture, HLS/DASH Stream Segment Merging, and Automated Zoom Cloud Recording Extraction.</b>
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+"/></a>
  <a href="https://github.com/Mayuri-Chan/pyrofork"><img src="https://img.shields.io/badge/Pyrofork-MTProto%20v2-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Pyrofork MTProto"/></a>
  <a href="https://ffmpeg.org/"><img src="https://img.shields.io/badge/FFmpeg-FastStart%20%26%20Thumbs-007808?style=for-the-badge&logo=ffmpeg&logoColor=white" alt="FFmpeg"/></a>
  <a href="https://github.com/yt-dlp/yt-dlp"><img src="https://img.shields.io/badge/yt--dlp-Stream%20Engine-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="yt-dlp"/></a>
  <a href="#-4gb-hybrid-upload-architecture"><img src="https://img.shields.io/badge/Upload%20Capacity-4.0%20GB%20Hybrid-8A2BE2?style=for-the-badge&logo=airplayvideo&logoColor=white" alt="4GB Uploads"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License"/></a>
</p>

---

## 📑 Table of Contents

- [Overview](#-overview)
- [Architecture & Upload Modes](#-architecture--upload-modes)
- [Key Features](#-key-features)
- [Command & Input Syntax Reference](#-command--input-syntax-reference)
- [Project Structure](#-project-structure)
- [Ubuntu VPS Deployment Guide](#-ubuntu-vps-deployment-guide)
  - [1. Prerequisites](#1-prerequisites)
  - [2. Clone & Environment Setup](#2-clone--environment-setup)
  - [3. Configure Environment Variables](#3-configure-environment-variables)
  - [4. Verification Test Run](#4-verification-test-run)
  - [5. Systemd Background Service](#5-systemd-background-service)
  - [6. Real-time Monitoring & Maintenance](#6-real-time-monitoring--maintenance)
- [Troubleshooting & FAQ](#-troubleshooting--faq)
- [License & Contributions](#-license--contributions)

---

## 🌟 Overview

**ANY-URL-DOWNLOADER** is a robust, production-ready Telegram Bot built to conquer modern file distribution challenges. Whether downloading direct high-speed HTTP binaries, decrypting passcode-gated Zoom cloud meetings, or downloading and merging HLS (`.m3u8`) and DASH (`.mpd`) video streams on the fly, this bot streamlines the entire lifecycle:

$$\text{Remote Source} \xrightarrow[\text{Concurrent HTTP / yt-dlp}]{\text{Stream Download}} \text{Isolated Workspace} \xrightarrow[\text{ffprobe / ffmpeg}]{\text{Metadata \& Thumbs}} \xrightarrow[\text{Pyrogram / Pyrofork}]{\text{Hybrid Upload}} \text{Telegram User}$$

---

## ⚡ Architecture & Upload Modes

Standard Telegram Bot API accounts are strictly limited to uploading files $\le$ **2.0 GB**. This project solves that limitation with an intelligent **dual-client hybrid architecture**:

```
                                  ┌────────────────────────┐
                                  │   Incoming URL Task    │
                                  └───────────┬────────────┘
                                              │
                                     [Download & Merge]
                                              │
                                     [Check Output Size]
                                              │
                      ┌───────────────────────┴───────────────────────┐
                      │                                               │
             File Size <= 2.0 GB                             File Size > 2.0 GB
                      │                                               │
           [Standard Bot Client]                           [Secondary User Client]
                      │                                      (Telegram Premium)
                      │                                               │
        Uploads Directly to Chat                       Uploads to Private Relay Channel
                      │                                               │
                      │                                    [Bot Client Copies Message]
                      │                                               │
                      └───────────────────────┬───────────────────────┘
                                              │
                                     Clean Delivery to User
```

| Capability | Standard Bot Mode | Hybrid Premium Relay Mode |
| :--- | :--- | :--- |
| **Max File Size Limit** | `2.0 GiB` | `4.0 GiB` |
| **Required Telegram Accounts** | 1 Bot Token (via [@BotFather](https://t.me/BotFather)) | 1 Bot Token + 1 Premium User Session |
| **Setup Complexity** | Zero configuration (default) | Paste `USER_SESSION_STRING` & `DUMP_CHAT_ID` |
| **Relay Mechanism** | Direct upload to recipient chat | User Session uploads to Dump Channel $\rightarrow$ Bot copies to User |
| **Direct HTTP Downloads** | Yes (`aiohttp` streaming) | Yes (`aiohttp` streaming) |
| **HLS / DASH Streams** | Yes (`yt-dlp` segment merging) | Yes (`yt-dlp` segment merging) |
| **Zoom Cloud Recordings** | Yes (Passcode & Cookies supported) | Yes (Passcode & Cookies supported) |

---

## 🚀 Key Features

* **📥 Asynchronous Direct HTTP Streaming:**
  * Uses `aiohttp` and `aiofiles` chunk-streaming (512 KB buffers) to download files without loading them into memory.
  * Implements RFC 5987 / RFC 6266 `Content-Disposition` header decoding for internationalized and percent-encoded filenames.
  * Active size-guarding checks `Content-Length` headers beforehand and terminates runaway streams exceeding the active limit.

* **📡 Unified HLS & DASH Stream Ingestion (`.m3u8` / `.mpd`):**
  * Automatically detects `.m3u8` and `.mpd` manifest URLs (ignoring query parameters and tokens).
  * Downloads video fragments concurrently (`concurrent_fragment_downloads: 4`) and merges them cleanly into standard `.mp4` containers.
  * **Intelligent Unicode & Sinhala Path Decoder:** When an HLS stream points to generic endpoints like `/master.m3u8` or `/index.m3u8`, the engine extracts and URL-decodes the parent directory name (e.g., `%E0%B6%B4%E0%B7%8F%E0%B6%A9%E0%B6%B8` $\rightarrow$ `පාඩම.mp4`), preventing generic filenames.

* **🎥 Automated Zoom Cloud Recording Ingestion:**
  * Regex-powered extraction for `zoom.us/rec/play/...` and `zoom.us/rec/share/...` links.
  * Native passcode submission via inline syntax (`URL | passcode`).
  * Full support for Netscape-format `cookies.txt` to bypass HTTP 403 Forbidden barriers on restricted institutional meetings.

* **📊 Anti-FloodThrottled Progress Bars:**
  * Displays a non-blocking visual gauge with percentage, download/upload speed (`MB/s`), processed bytes, ETA countdown, and filename.
  * Throttled using `PROGRESS_UPDATE_INTERVAL` (default: 3.5s) to guarantee zero Telegram `FloodWait` penalties.

* **🎬 FFmpeg Video Metadata & FastStart Optimization:**
  * Asynchronously invokes `ffprobe` to parse video width, height, duration, and 90°/270° smartphone orientation rotation tags.
  * Generates high-definition, Telegram-compliant video thumbnails (max width 320px).
  * Enables in-app streaming with `supports_streaming=True`, allowing users to watch while downloading.

* **🛡️ Sandboxed Workspaces & Strict Concurrency:**
  * Every task executes inside an isolated workspace (`downloads/{user_id}_{uuid}/`).
  * Mandatory execution of `finally:` cleanup blocks guarantees zero leftover files even on task failure or network disconnects.
  * Concurrency semaphore limits simultaneous jobs to prevent CPU, RAM, or bandwidth starvation.

---

## 💡 Command & Input Syntax Reference

### Telegram Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` | Display the welcome banner, system status, and current active upload limit (2GB vs 4GB). |
| `/help` | Detailed guide with copy-ready syntax examples for Direct URLs, HLS streams, and Zoom links. |
| `/status` | Real-time health stats: active download slots, 4GB Premium status, dump channel, and access mode. |

### Download Input Formats

The bot supports flexible syntax using the pipe (`|`) delimiter:

| Media Type | Syntax Pattern | Example Input |
| :--- | :--- | :--- |
| **Direct URL** (Default name) | `URL` | `https://releases.ubuntu.com/24.04/ubuntu-24.04-desktop-amd64.iso` |
| **Direct URL** (Custom name) | `URL \| custom_filename.ext` | `https://example.com/files/archive.zip \| Monthly_Backup.zip` |
| **HLS Stream** (Auto parent name) | `URL` | `https://cdn.site.com/courses/%E0%B6%B4%E0%B7%8F%E0%B6%A9%E0%B6%B8/master.m3u8` |
| **HLS / DASH Stream** (Custom name) | `URL \| custom_filename.mp4` | `https://cdn.site.com/hls/live/index.m3u8 \| Physics_Revision.mp4` |
| **Zoom Recording** (Public) | `Zoom_URL` | `https://us02web.zoom.us/rec/share/abc123xyz` |
| **Zoom Recording** (Passcode) | `Zoom_URL \| passcode` | `https://us02web.zoom.us/rec/share/abc123xyz \| Pass@1234` |
| **Zoom Recording** (Pass + Name) | `Zoom_URL \| passcode \| name.mp4` | `https://us02web.zoom.us/rec/share/abc123xyz \| Pass@1234 \| Lecture_01.mp4` |

---

## 📁 Project Structure

```ascii
ANY-URL-DOWNLOADER/
├── assets/
│   └── banner.gif            # Animated GitHub hero banner
├── bot.py                    # Main MTProto application, dispatcher, progress & relay logic
├── downloader.py             # aiohttp direct downloader & yt-dlp unified stream/Zoom engine
├── utils.py                  # FFmpeg/ffprobe async wrappers, thumbnail generator, formatters
├── config.py                 # Pydantic/dotenv configuration parser & 2GB/4GB dynamic resolver
├── test_suite.py             # 17-point component test suite covering all logic branches
├── requirements.txt          # Production dependencies (Pyrofork, yt-dlp, aiohttp, etc.)
├── .env.example              # Sample environment template
├── .gitignore                # Production ignore rules for secrets, sessions, and downloads
└── README.md                 # Complete documentation & deployment guide
```

---

## 🛠️ Ubuntu VPS Deployment Guide

Follow this guide to deploy the bot on an Ubuntu 20.04/22.04/24.04 VPS.

### 1. Prerequisites

Update system packages and install Python 3, virtual environment tools, Git, build essentials, and FFmpeg:

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv ffmpeg build-essential python3-dev git
```

Verify that Python and FFmpeg are available in your path:

```bash
python3 --version
ffmpeg -version
ffprobe -version
```

---

### 2. Clone & Environment Setup

Clone the repository into `/opt/any-url-downloader` and create an isolated Python virtual environment:

```bash
# Create and set ownership of directory
sudo mkdir -p /opt/any-url-downloader
sudo chown -R $USER:$USER /opt/any-url-downloader

# Clone the repository
git clone https://github.com/NimeshPiyathissa/ANY-URL-DOWNLOADER.git /opt/any-url-downloader
cd /opt/any-url-downloader

# Initialize virtual environment
python3 -m venv venv
source venv/bin/activate

# Upgrade pip and install all dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

---

### 3. Configure Environment Variables

Generate your production `.env` configuration file from the template:

```bash
cp .env.example .env
nano .env
```

Configure your parameters:

```ini
# ==========================================
# Telegram API Credentials (from https://my.telegram.org)
# ==========================================
API_ID=12345678
API_HASH=0123456789abcdef0123456789abcdef

# ==========================================
# Telegram Bot Token (from @BotFather)
# ==========================================
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_1234567

# ==========================================
# (OPTIONAL) Telegram Premium Session for 4GB Uploads
# Leave empty for standard 2GB bot mode.
# Paste a Pyrofork/Pyrogram session string here to enable 4GB uploads.
# ==========================================
USER_SESSION_STRING=

# ==========================================
# (OPTIONAL) Dump Channel ID for 4GB Relay
# Required only if USER_SESSION_STRING is provided.
# Both the bot and the user account must be admins in this channel.
# Example: DUMP_CHAT_ID=-1001234567890
# ==========================================
DUMP_CHAT_ID=

# ==========================================
# Access Control (Leave empty for public bot access)
# Comma-separated list of allowed Telegram user IDs
# ==========================================
AUTHORIZED_USERS=

# ==========================================
# Concurrency & Performance
# ==========================================
MAX_CONCURRENT_DOWNLOADS=3
PROGRESS_UPDATE_INTERVAL=3.5
DOWNLOAD_DIR=downloads
```

> [!TIP]
> **Enabling 4GB Uploads Later:**
> You do not need to rewrite any code. Simply paste a valid session string into `USER_SESSION_STRING=` and set `DUMP_CHAT_ID=`, then restart the service. The bot will automatically switch from 2GB to 4GB mode.

---

### 4. Verification Test Run

Run the automated test suite before launching the daemon:

```bash
cd /opt/any-url-downloader
source venv/bin/activate

# Run the 17-point component test suite
python test_suite.py
```

Expected output:
```
============================================================
      RUNNING BOT COMPONENT & REGRESSION TEST SUITE
============================================================
✓ format_bytes passed (including 4GB scale)
✓ format_time passed
✓ generate_progress_bar passed
✓ sanitize_filename and is_video_file passed
✓ is_zoom_url passed
✓ is_stream_url passed
✓ Sinhala parent folder extraction: 'පාඩම.mp4'
✓ English parent folder extraction: 'Lecture 01.mp4'
✓ Non-master m3u8 stem fallback: 'playlist.mp4'
✓ extract_filename_from_headers passed
✓ parse_user_input passed
✓ Config BOT_MAX_SIZE and PREMIUM_MAX_SIZE constants verified
✓ USER_SESSION_STRING fallback: 2GB bot-only mode confirmed
✓ clean_directory workspace cleanup verified
✓ ffprobe metadata verified: duration=2s, width=320, height=240
✓ ffmpeg thumbnail generation verified

🎉 ALL TESTS COMPLETED AND PASSED PERFECTLY!
```

---

### 5. Systemd Background Service

To ensure the bot runs 24/7 and restarts automatically upon server reboot or crashes, configure a systemd service:

```bash
sudo tee /etc/systemd/system/any-url-downloader.service > /dev/null << 'EOF'
[Unit]
Description=Any URL, HLS and Zoom Telegram Downloader Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/any-url-downloader
ExecStart=/opt/any-url-downloader/venv/bin/python bot.py
Restart=always
RestartSec=10
EnvironmentFile=/opt/any-url-downloader/.env

# Security Hardening
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
```

Reload systemd daemon, enable, and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now any-url-downloader
```

Check the active service status:

```bash
sudo systemctl status any-url-downloader
```

---

### 6. Real-time Monitoring & Maintenance

Inspect live operational logs:

```bash
sudo journalctl -u any-url-downloader -f
```

Restart or stop the bot:

```bash
# Restart bot after updating .env
sudo systemctl restart any-url-downloader

# Stop bot
sudo systemctl stop any-url-downloader
```

Update to the latest version from GitHub:

```bash
cd /opt/any-url-downloader
git pull origin main
sudo systemctl restart any-url-downloader
```

---

## ❓ Troubleshooting & FAQ

<details>
<summary><b>1. Zoom downloads return 403 Forbidden</b></summary>
<br>
Some institutions require user authentication to view cloud recordings. Export your authenticated browser cookies in Netscape format using an extension like <i>Get cookies.txt LOCALLY</i>, save them as <code>cookies.txt</code> in <code>/opt/any-url-downloader/cookies.txt</code>, and the bot will automatically pass them to yt-dlp.
</details>

<details>
<summary><b>2. Why is TgCrypto showing as missing in logs?</b></summary>
<br>
<code>TgCrypto</code> accelerates Telegram MTProto cryptographic operations. If you see a warning, install build-essential and compile it into your venv:
<pre><code>sudo apt install -y build-essential python3-dev
source venv/bin/activate
pip install --force-reinstall tgcrypto</code></pre>
</details>

<details>
<summary><b>3. How do I restrict the bot so only I can use it?</b></summary>
<br>
Find your numeric Telegram User ID (e.g., using <a href="https://t.me/userinfobot">@userinfobot</a>). Add it to your <code>.env</code> file:
<pre><code>AUTHORIZED_USERS=123456789</code></pre>
Then restart the service: <code>sudo systemctl restart any-url-downloader</code>.
</details>

---

## 📄 License & Contributions

Distributed under the **MIT License**. Contributions, issues, and feature requests are welcome!

<p align="center">
  <b>Developed with ❤️ for seamless, unconstrained file downloading on Telegram.</b>
</p>
