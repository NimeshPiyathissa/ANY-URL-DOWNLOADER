<p align="center">
  <img src="assets/banner.gif" alt="Any URL, HLS, Zoom & Google Drive Downloader Bot" width="100%"/>
</p>

<h1 align="center">⚡ ANY URL, HLS (.m3u8), ZOOM & GOOGLE DRIVE DOWNLOADER BOT</h1>

<p align="center">
  <b>Production-Grade Asynchronous Telegram Bot with 4GB Hybrid Upload Architecture, 1-Command Interactive Terminal Installer, 16-Connection aria2c Multi-Range Engine, 32-Fragment HLS/DASH Concurrency, Resilient Zoom Web-Fallback Extractor, Telegram cookies.txt Upload, and Zero-Byte Hardening.</b>
</p>

<p align="center">
  <a href="https://github.com/NimeshPiyathissa/ANY-URL-DOWNLOADER/releases/tag/v3.0.0"><img src="https://img.shields.io/badge/Release-v3.0.0-blueviolet?style=for-the-badge&logo=github&logoColor=white" alt="Release v3.0.0"/></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.11%20%7C%203.12-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.11+"/></a>
  <a href="https://github.com/Mayuri-Chan/pyrofork"><img src="https://img.shields.io/badge/Pyrofork-MTProto%20v2-26A5E4?style=for-the-badge&logo=telegram&logoColor=white" alt="Pyrofork MTProto"/></a>
  <a href="https://github.com/yt-dlp/yt-dlp"><img src="https://img.shields.io/badge/yt--dlp-32x%20Fragments%20%2B%20aria2c-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="yt-dlp & aria2c"/></a>
  <a href="https://github.com/wkentaro/gdown"><img src="https://img.shields.io/badge/Google%20Drive-gdown%20Engine-4285F4?style=for-the-badge&logo=googledrive&logoColor=white" alt="Google Drive"/></a>
  <a href="#-4gb-hybrid-upload-architecture"><img src="https://img.shields.io/badge/Upload%20Capacity-4.0%20GB%20Hybrid-8A2BE2?style=for-the-badge&logo=airplayvideo&logoColor=white" alt="4GB Uploads"/></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License"/></a>
</p>

---

## 📑 Table of Contents

- [What's New in v3.0.0](#-whats-new-in-v300)
- [What's New in v2.3.0](#-whats-new-in-v230)
- [What's New in v2.2.1](#-whats-new-in-v221)
- [Architecture & Upload Modes](#-architecture--upload-modes)
- [Key Features](#-key-features)
- [Interactive UI & User Experience](#-interactive-ui--user-experience)
- [Command & Input Syntax Reference](#-command--input-syntax-reference)
- [Chrome / Edge Extension (1-Click cookies.txt)](#-chrome--edge-extension-1-click-cookiestxt-exporter)
- [Project Structure](#-project-structure)
- [1-Command Quick Deployment (`install.sh`)](#-1-command-quick-deployment-installsh---recommended)
- [Step-by-Step Ubuntu VPS Setup](#-step-by-step-ubuntu-vps-setup)
- [Live Monitoring & Management](#-live-monitoring--management)
- [Troubleshooting & FAQ](#-troubleshooting--faq)
- [License & Contributions](#-license--contributions)

---

## 🚀 What's New in v3.0.0

* **⚡ 1-Command Interactive Terminal Installer (`install.sh`):** Zero manual `.env` file editing. Runs with color-coded prompts, input validation (`API_ID`, `API_HASH`, `BOT_TOKEN`, `OWNER_ID`, `USER_SESSION_STRING`), automatically extracts `<bot_id>` and adds it to `ALLOWED_USERS` (preventing `Access Denied` on Chrome extension Bot API calls), provisions `python3-venv`, `pip`, `ffmpeg`, `aria2`, `git`, upgrades `yt-dlp --pre`, configures systemd with `Restart=always`, and prints a clean status table.
* **🛡️ Hardened Zoom & CDN Header Forwarding:** Browser extension `popup.js` captures `navigator.userAgent` and passes exact `User-Agent`, `Referer`, and `Cookie` headers into both `aria2c` (`--header=...`) and all `aiohttp` parallel Range sessions in `downloader.py`, completely eliminating `403 Forbidden` mismatches on protected CDN/Zoom video chunks.
* **🛑 Zero-Byte / Corrupt File Guard:** Checks `file_path.exists()` and `file_path.stat().st_size > 0` before uploading in `bot.py` and `downloader.py`, cleanly aborting with a descriptive error instead of crashing Pyrogram's `send_video` / `send_document`.
* **📝 Telegram Caption & Filename Sanitization:** Strictly enforces Telegram's 1024-character caption limit (`caption[:1020] + "..."`) and replaces forbidden filesystem characters (`\ / * ? : " < > | \x00-\x1f`) while preserving Sinhala and all Unicode characters.
* **🧹 Guaranteed Disk & State Cleanup:** Every download job is wrapped in strict `try ... finally` blocks removing temporary workspace directories (`shutil.rmtree(task_dir, ignore_errors=True)`) and purging stale `PASSCODE_WAITERS` / `CAPTION_WAITERS` so VPS storage never fills up on failed tasks.
* **🚨 Startup Config Validation:** Validates `API_ID`, `API_HASH`, and `BOT_TOKEN` at startup with human-readable guidance pointing directly to `sudo bash install.sh` if credentials are missing or malformed.
* **🔄 Unified `setup_service.sh`:** Delegates cleanly to `install.sh` without any code duplication.

---

## 🚀 What's New in v2.3.0

* **🎬 1-Click Zoom Video Stream Capture in Browser Extension:** Added a dedicated **`🎬 Send Zoom Video to Bot`** button in the Chrome/Edge extension. When viewing any protected or CAPTCHA-locked Zoom recording in your browser, one click extracts the active playing `<video>` stream URL (`.mp4` / `.m3u8`), auto-syncs your browser session cookies, and commands the bot to download the video directly—completely bypassing all server-side bot/CAPTCHA blocks!
* **⚡ New Telegram `/zoomstream` Command:** Introduced `/zoomstream <stream_url> | <filename.mp4>` in `bot.py` with automatic `Referer: https://us06web.zoom.us/` and `cookies.txt` header injection for instantaneous stream processing.
* **🍪 Robust Cookie Filename Matching:** `document_upload_handler` now accepts any text file starting with `cookies` (e.g. `cookies.txt`, `cookies (1).txt`, `cookies (2).txt`), saving directly to the resolved absolute path.
* **📍 Absolute `cookies.txt` Path Resolution:** Updated `Config.COOKIES_FILE` in `config.py` and `downloader.py` to resolve via `Path(__file__).resolve().parent / "cookies.txt"` for 100% reliable systemd VPS daemon operation.
* **📦 Upgraded Manifest V3 Extension:** Added `"scripting"` and `"webRequest"` permissions to `chrome-extension/manifest.json` for in-tab media inspection.

---

## 🚀 What's New in v2.2.1

* **🔑 Bulletproof Zoom Passcode & CSRF Token Validation:** Completely resolved false passcode rejection. The bot extracts `meeting_id` from the URL path (`/rec/share/...`, `/rec/play/...`) and dynamically pulls the Zoom CSRF token (`ZOOM-CSRFTOKEN`, `_zm_ctaid`, `cred`) from response cookies and HTML/JS meta.
* **📡 Correct Zoom Payload & Redirect Following:** Submits validation requests to `/rec/validate_meet_passwd` with `action: "viewdetailpage"`, `Origin`, `Referer`, and `X-Requested-With: XMLHttpRequest` headers, and automatically follows `result.redirectUrl` to retrieve the direct stream.
* **🛡️ Bot/CAPTCHA Protection Detection:** When Zoom triggers anti-bot CAPTCHA challenges, the bot immediately detects it and provides clear instructions on exporting `cookies.txt` from the browser to unlock the video.

---

## ⚡ Architecture & Upload Modes

Standard Telegram Bot API accounts are strictly limited to uploading files $\le$ **2.0 GB**. This project solves that limitation with an intelligent **dual-client hybrid architecture**:

```
                                  ┌────────────────────────┐
                                  │   Incoming URL Task    │
                                  └───────────┬────────────┘
                                              │
                         [Download via 16x aria2c / 32x HLS / gdown]
                                              │
                             [Interactive Caption Prompt (30s)]
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
| **Direct HTTP Engine** | 16-Connection aria2c + 8-Worker Parallel Range | 16-Connection aria2c + 8-Worker Parallel Range |
| **HLS / DASH Streams** | 32-Fragment Concurrency (yt-dlp Native) | 32-Fragment Concurrency (yt-dlp Native) |
| **Google Drive Engine** | Yes (`gdown` integration) | Yes (`gdown` integration) |
| **Zoom Cloud Recordings** | Interactive Passcode & Cookies | Interactive Passcode & Cookies |

---

## 🌟 Key Features

* **📥 Multi-Connection Direct HTTP Engine:**
  * Probes server capabilities using `Range: bytes=0-0` requests.
  * Launches `aria2c` with 16 connections (`-x 16 -s 16 -k 1M`) forwarding exact headers.
  * Seamless fallback to an 8-worker asynchronous `aiohttp` parallel range downloader.
  * In-memory part concatenation without corrupting multi-gigabyte archives.

* **📡 32-Fragment Concurrent HLS & DASH Ingestion (`.m3u8` / `.mpd`):**
  * Auto-detects manifest URLs, bypassing complex query tokens.
  * Native Python downloader streams 32 fragments concurrently with 10MB chunk buffers.
  * **Intelligent Unicode/Sinhala Directory Extraction:** Automatically URL-decodes parent folder names for generic `/master.m3u8` or `/index.m3u8` links (e.g., `%E0%B6%B4%E0%B7%8F%E0%B6%A9%E0%B6%B8` $\rightarrow$ `පාඩම.mp4`).

* **📁 High-Speed Google Drive Downloader:**
  * Handles standard `drive.google.com/file/d/...`, `open?id=...`, `uc?id=...`, and shared folder links.
  * Automatically creates `.zip` archives of Google Drive shared folders.
  * Bypasses Google Drive's viral download confirmation screens for large files.

* **🔐 Interactive In-Chat Zoom Passcode Prompt:**
  * Sends a probe to the recording URL. If locked, prompts the user:
    `"🔐 This Zoom recording requires a Passcode. Please reply with the Zoom Passcode now:"`
  * Captures the reply with an in-memory `asyncio.Future` and resumes download automatically.
  * Supports Netscape-formatted `cookies.txt` for passwordless organizational SSO meetings.

* **📝 Interactive Custom Caption Prompt:**
  * Once downloaded, users have 30 seconds to send any custom text message with Markdown formatting to use as the Telegram media caption.
  * Enforces Telegram's 1024-character caption limit (`caption[:1020] + "..."`).
  * Includes `⏭️ Use Default Filename` and `❌ Cancel Upload` inline action buttons.

* **🎬 FFmpeg Video Metadata & Streaming Optimization:**
  * Runs `ffprobe` asynchronously to extract duration, dimensions, and smartphone 90°/270° orientation tags.
  * Generates high-definition Telegram thumbnails (max width 320px).
  * Sets `supports_streaming=True` for immediate in-app video playback.

---

## 📱 Interactive UI & User Experience

<table align="center">
  <tr>
    <td align="center"><b>Interactive Main Menu</b></td>
    <td align="center"><b>Live Progress Reporting</b></td>
  </tr>
  <tr>
    <td>
      <pre>
👋 Hello Alex!
Welcome to Any URL Downloader v3.0.0

[📥 Supported Links]  [🔐 Private Zoom]
[📁 Google Drive   ]  [⚙️ Caption & Naming]
[       📊 Server Status        ]
      </pre>
    </td>
    <td>
      <pre>
📥 Downloading File...
[██████░░░░] 60.0%

⚡ Speed: 24.50 MB/s
💾 Processed: 300.00 MB / 500.00 MB
⏳ ETA: 00:08
🧩 Fragments: 12 / 20
📁 File: Lecture_01.mp4
      </pre>
    </td>
  </tr>
</table>

---

## 💡 Command & Input Syntax Reference

### Telegram Bot Commands

| Command | Description |
| :--- | :--- |
| `/start` | Open the interactive main menu with navigation buttons and system status. |
| `/help` | Detailed guide with copy-ready examples for all supported links. |
| `/status` | Real-time server health: concurrency, upload mode (2GB vs 4GB), and engine metrics. |
| `/zoomstream` | Directly download an extracted Zoom MP4/M3U8 stream with authenticated headers (`/zoomstream <url> \| <name>`). |

### Download Input Formats

| Media Type | Syntax Pattern | Example Input |
| :--- | :--- | :--- |
| **Direct URL** (Auto Name) | `URL` | `https://releases.ubuntu.com/24.04/ubuntu-24.04-desktop-amd64.iso` |
| **Direct URL** (Custom Name) | `URL \| custom_name.ext` | `https://example.com/files/archive.zip \| Backup_May.zip` |
| **HLS Stream** (Auto Name) | `URL` | `https://cdn.site.com/%E0%B6%B4%E0%B7%8F%E0%B6%A9%E0%B6%B8/master.m3u8` |
| **HLS / DASH Stream** (Custom Name) | `URL \| custom_name.mp4` | `https://cdn.site.com/hls/index.m3u8 \| Physics_Rev.mp4` |
| **Google Drive File** | `URL` | `https://drive.google.com/file/d/1A2B3C4D5E6F/view` |
| **Google Drive** (Custom Name) | `URL \| custom_name.ext` | `https://drive.google.com/file/d/1A2B3C4D5E6F/view \| Book.pdf` |
| **Zoom Recording** (Interactive) | `Zoom_URL` | `https://us02web.zoom.us/rec/share/abc123xyz` *(Prompts in chat)* |
| **Zoom Recording** (Inline Passcode) | `Zoom_URL \| passcode` | `https://us02web.zoom.us/rec/share/abc123xyz \| Pass@123` |
| **Zoom Recording** (Pass + Name) | `Zoom_URL \| pass \| name.mp4` | `https://us02web.zoom.us/rec/share/abc123xyz \| Pass@123 \| Class.mp4` |
| **Zoom Direct Stream** (Browser Capture) | `/zoomstream URL \| name.mp4` | `/zoomstream https://ssrweb.zoom.us/rec/play/123.mp4?sig=abc \| Lecture.mp4` |

---

## 🍪 Chrome / Edge Extension (1-Click cookies.txt Exporter)

A dedicated **Manifest V3** browser extension is included inside the [`chrome-extension/`](file:///C:/direct%20url%20downloader%20bot/chrome-extension/) directory. It enables 1-click Netscape `cookies.txt` extraction and 1-click Zoom stream capture directly to your Telegram Downloader Bot!

### 🌟 Key Extension Features:
* **🎬 1-Click Send Zoom Video to Bot:** When viewing any unlocked or CAPTCHA-solved Zoom recording in your browser, one click captures the active stream, User-Agent, Referer, syncs cookies, and commands the bot to start downloading immediately!
* **🍪 Custom Cookie Toolbar Icon:** Crisp golden-brown cookie with chocolate chips (`16px`, `48px`, `128px`).
* **🌐 Active Domain Auto-Detection:** Automatically identifies the active domain and counts available session/authentication cookies.
* **⬇️ 1-Click Netscape cookies.txt Download:** Instantly exports in standard Netscape HTTP Cookie File format compatible with `yt-dlp`, `curl`, and `wget`.
* **📋 Clipboard Copy:** Copies formatted cookie text directly for quick manual pasting.
* **🚀 Direct Telegram Bot Sync:** Send `cookies.txt` straight to your Telegram Downloader Bot chat using Telegram Bot API (`sendDocument`).

### 📥 How to Install:
1. Open your browser extension manager:
   - **Chrome / Brave:** Navigate to `chrome://extensions`
   - **Microsoft Edge:** Navigate to `edge://extensions`
2. Enable **Developer mode** (toggle switch in the top-right corner).
3. Click the **Load unpacked** button.
4. Select the `chrome-extension/` directory from this repository.
5. Pin the **Cookie Exporter (`🍪`)** to your browser extensions toolbar!

---

## 📁 Project Structure

```ascii
ANY-URL-DOWNLOADER/
├── assets/
│   └── banner.gif            # Animated GitHub hero banner
├── chrome-extension/         # Manifest V3 1-click cookies.txt exporter & Bot sync
│   ├── icons/                # High-res cookie toolbar icons (16px, 48px, 128px)
│   ├── manifest.json         # Manifest V3 extension configuration
│   ├── popup.html            # Dark glassmorphism popup UI
│   ├── popup.css             # Glassmorphism styling & animations
│   └── popup.js              # Netscape cookie parser, stream exporter & Telegram sender
├── bot.py                    # Dual-client MTProto bot, interactive buttons & caption prompt
├── downloader.py             # 16x aria2c, 8x HTTP parallel range, 32x HLS/DASH & gdown engines
├── utils.py                  # FFmpeg/ffprobe async wrappers, thumbnails, caption truncation
├── config.py                 # Configuration parser, auto bot-ID whitelist, 2GB/4GB limit resolver
├── install.sh                # 1-Command interactive terminal installer (Release v3.0.0)
├── setup_service.sh          # Systemd installer wrapper (delegates cleanly to install.sh)
├── test_suite.py             # Full regression & component test suite (v3.0.0)
├── requirements.txt          # Production dependencies (Pyrofork, yt-dlp, gdown, etc.)
├── .env.example              # Environment variables template
├── .gitignore                # Git ignore rules for secrets, downloads, and sessions
└── README.md                 # Complete documentation & deployment guide
```

---

## ⚡ 1-Command Quick Deployment (`install.sh` - Recommended)

On any fresh **Ubuntu 20.04 / 22.04 / 24.04 / Debian VPS**:

```bash
git clone https://github.com/NimeshPiyathissa/ANY-URL-DOWNLOADER.git /opt/any-url-downloader
cd /opt/any-url-downloader
sudo bash install.sh
```

### What `install.sh` Does Automatically:
1. Installs all required system packages (`python3`, `python3-venv`, `python3-pip`, `ffmpeg`, `aria2`, `git`) via `apt-get`.
2. Interactively prompts for credentials with validation (or preserves existing `.env`):
   - `API_ID` (numeric digits)
   - `API_HASH` (alphanumeric string)
   - `BOT_TOKEN` (automatically extracts `BOT_ID` and adds it to `ALLOWED_USERS`!)
   - `OWNER_ID` (your numeric Telegram User ID)
   - `USER_SESSION_STRING` (optional for 4GB uploads)
3. Creates the Python virtual environment and installs/upgrades dependencies (`pip`, `yt-dlp --pre`, `requirements.txt`).
4. Generates and starts `/etc/systemd/system/any-url-bot.service` with `Restart=always`.
5. Prints a clean status table with live logs and restart commands!

---

## 🛠️ Step-by-Step Ubuntu VPS Setup

<details>
<summary><b>Click to expand manual setup instructions</b></summary>

### 1. Install System Dependencies

```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv ffmpeg aria2 git
```

### 2. Setup Virtual Environment

```bash
cd /opt/any-url-downloader
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install --upgrade --pre yt-dlp
pip install -r requirements.txt
```

### 3. Configure `.env`

```ini
API_ID=12345678
API_HASH=0123456789abcdef0123456789abcdef
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_1234567

# Optional: Unlocks 4GB Uploads with Telegram Premium
USER_SESSION_STRING=
DUMP_CHAT_ID=

# Access Control (Your Owner ID + Bot ID automatically)
ALLOWED_USERS=123456789,987654321
AUTHORIZED_USERS=123456789,987654321

# Concurrency & Performance
MAX_CONCURRENT_DOWNLOADS=3
PROGRESS_UPDATE_INTERVAL=3.5
DOWNLOAD_DIR=downloads
```

### 4. Run Test Suite

```bash
python test_suite.py
```

### 5. Launch Service

```bash
sudo bash setup_service.sh
```
</details>

---

## 📊 Live Monitoring & Management

```bash
# View live real-time logs
sudo journalctl -u any-url-bot.service -f

# Restart bot after changing .env
sudo systemctl restart any-url-bot.service

# Check service status
sudo systemctl status any-url-bot.service

# Stop bot
sudo systemctl stop any-url-bot.service

# Pull latest updates from GitHub
cd /opt/any-url-downloader
git pull origin main
sudo systemctl restart any-url-bot.service
```

---

## ❓ Troubleshooting & FAQ

<details>
<summary><b>1. How do I enable 4GB uploads?</b></summary>
<br>
Generate a Pyrofork/Pyrogram session string from an account with Telegram Premium. Paste it into <code>USER_SESSION_STRING</code> in your <code>.env</code> file, set <code>DUMP_CHAT_ID</code> to a private channel where both your bot and user account are admins, and run <code>sudo systemctl restart any-url-bot.service</code>.
</details>

<details>
<summary><b>2. Zoom links fail with 403 Forbidden</b></summary>
<br>
Some universities or enterprises require login authentication. Export your browser cookies in Netscape format using the included <i>Any URL Downloader</i> browser extension, send them as <code>cookies.txt</code> directly into the bot chat, or click <b>🎬 Send Zoom Video to Bot</b> directly from the video playback page.
</details>

<details>
<summary><b>3. Why did the bot say "Access Denied" when the Chrome extension sent a command?</b></summary>
<br>
In Release v3.0.0, <code>install.sh</code> and <code>config.py</code> automatically extract your Bot ID from <code>BOT_TOKEN</code> and include it in <code>ALLOWED_USERS</code>. This ensures messages triggered via the Bot API are always authorized.
</details>

<details>
<summary><b>4. Large Google Drive files show quota exceeded</b></summary>
<br>
Google limits high-traffic public files. If a file cannot be downloaded publicly, copy it to your personal Google Drive or download directly using the shared link.
</details>

---

## 📄 License & Contributions

Distributed under the **MIT License**. PRs, issues, and feature suggestions are always welcome!

<p align="center">
  <b>Built with ❤️ for ultra-fast, unrestricted downloading on Telegram.</b>
</p>
