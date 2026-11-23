import asyncio
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, Optional, Tuple

from pyrogram import Client, compose, filters
from pyrogram.errors import FloodWait, MessageNotModified, RPCError
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from config import Config
from downloader import (
    download_direct_url,
    download_gdrive_file,
    download_stream_or_zoom,
    is_gdrive_url,
    is_stream_url,
    is_zoom_url,
)
from utils import (
    clean_directory,
    format_bytes,
    format_time,
    generate_progress_bar,
    generate_thumbnail,
    get_video_metadata,
    is_video_file,
    sanitize_filename,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("URLDownloaderBot")

# 1. Primary Bot MTProto Client (handles commands, status, direct downloads <= 2GB)
bot = Client(
    "direct_downloader_bot",
    api_id=Config.API_ID or 123456,
    api_hash=Config.API_HASH or "0123456789abcdef0123456789abcdef",
    bot_token=Config.BOT_TOKEN or "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_1234567",
    workdir=str(Config.DOWNLOAD_DIR.parent),
    workers=16,
)

# 2. Secondary User App MTProto Client (for 4GB Hybrid Uploads via Telegram Premium)
user_app: Optional[Client] = None
if Config.USER_SESSION_STRING:
    user_app = Client(
        "user_premium_uploader",
        api_id=Config.API_ID or 123456,
        api_hash=Config.API_HASH or "0123456789abcdef0123456789abcdef",
        session_string=Config.USER_SESSION_STRING,
        in_memory=True,
        workers=8,
    )

# Concurrency semaphore to prevent CPU, RAM, and bandwidth saturation
DOWNLOAD_SEMAPHORE = asyncio.Semaphore(Config.MAX_CONCURRENT_DOWNLOADS)
ACTIVE_DOWNLOADS_COUNT = 0

# In-memory waiters for interactive user conversations
# PASSCODE_WAITERS: user_id -> asyncio.Future[str]
PASSCODE_WAITERS: Dict[int, asyncio.Future] = {}

# CAPTION_WAITERS: user_id -> (asyncio.Future[str], task_id)
CAPTION_WAITERS: Dict[int, Tuple[asyncio.Future, str]] = {}


class ProgressTracker:
    """
    Manages throttled, real-time Telegram progress bar updates for both download and upload stages.
    Guards against Telegram FloodWait exceptions by enforcing a minimum interval between edits.
    Supports fragment tracking for HLS / DASH stream downloads.
    """

    def __init__(self, status_message: Message, filename: str = "Preparing..."):
        self.status_message = status_message
        self.filename = filename
        self.start_time = time.time()
        self.last_edit_time = 0.0
        self.last_text = ""
        self.mode = "download"  # "download" or "upload"

    def set_filename(self, name: str) -> None:
        self.filename = name

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.start_time = time.time()
        self.last_edit_time = 0.0

    async def update_download(
        self,
        current: int,
        total: int,
        speed: Optional[float] = None,
        eta: Optional[float] = None,
        fragment_info: Optional[Tuple[int, int]] = None,
    ) -> None:
        """Throttled progress update for downloading from URL."""
        await self._render_and_edit(
            action_title="📥 **Downloading File...**",
            current=current,
            total=total,
            speed=speed,
            eta=eta,
            fragment_info=fragment_info,
        )

    async def update_upload(self, current: int, total: int) -> None:
        """Throttled progress update for uploading to Telegram."""
        title = (
            "🚀 **Uploading to Telegram (4GB Premium Relay)...**"
            if total > Config.BOT_MAX_SIZE
            else "📤 **Uploading to Telegram...**"
        )
        await self._render_and_edit(
            action_title=title,
            current=current,
            total=total,
            speed=None,
            eta=None,
            fragment_info=None,
        )

    async def _render_and_edit(
        self,
        action_title: str,
        current: int,
        total: int,
        speed: Optional[float],
        eta: Optional[float],
        fragment_info: Optional[Tuple[int, int]] = None,
    ) -> None:
        now = time.time()
        # Throttle edits to avoid Telegram FloodWait
        if (now - self.last_edit_time) < Config.PROGRESS_UPDATE_INTERVAL and (
            total > 0 and current < total
        ):
            return

        percentage = (current / total * 100.0) if total > 0 else 0.0
        bar = generate_progress_bar(percentage, length=10)

        # Calculate speed if not provided
        elapsed = max(0.001, now - self.start_time)
        if speed is None or speed <= 0:
            speed = current / elapsed

        # Calculate ETA if not provided
        if eta is None or eta <= 0:
            remaining_bytes = max(0, total - current)
            eta = (remaining_bytes / speed) if speed > 0 and total > 0 else 0

        speed_str = f"{format_bytes(speed)}/s"
        processed_str = (
            f"{format_bytes(current)} / {format_bytes(total)}"
            if total > 0
            else format_bytes(current)
        )
        eta_str = format_time(eta)

        fragment_line = ""
        if fragment_info and fragment_info[1] > 0:
            fragment_line = f"\n🧩 **Fragments:** `{fragment_info[0]} / {fragment_info[1]}`"

        text = (
            f"{action_title}\n"
            f"`[{bar}]` **{percentage:.1f}%**\n\n"
            f"⚡ **Speed:** `{speed_str}`\n"
            f"💾 **Processed:** `{processed_str}`\n"
            f"⏳ **ETA:** `{eta_str}`"
            f"{fragment_line}\n"
            f"📁 **File:** `{self.filename}`"
        )

        if text == self.last_text:
            return

        try:
            await self.status_message.edit_text(text)
            self.last_text = text
            self.last_edit_time = now
        except FloodWait as e:
            logger.warning(f"Telegram FloodWait hit for {e.value} seconds.")
            self.last_edit_time = now + e.value
        except MessageNotModified:
            pass
        except RPCError as e:
            logger.debug(f"Non-critical RPCError while editing progress: {e}")


def is_authorized(user_id: int) -> bool:
    """Check if user is authorized to use the bot."""
    if not Config.AUTHORIZED_USERS:
        return True
    return user_id in Config.AUTHORIZED_USERS


# ==============================================================================
# Interactive Inline UI Keyboards & Text Builders
# ==============================================================================

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Main navigation keyboard for /start and /help."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📥 Supported Links", callback_data="help_links"),
            InlineKeyboardButton("🔐 Private Zoom Guide", callback_data="help_zoom"),
        ],
        [
            InlineKeyboardButton("📁 Google Drive Guide", callback_data="help_gdrive"),
            InlineKeyboardButton("⚙️ Caption & Naming", callback_data="help_naming"),
        ],
        [
            InlineKeyboardButton("📊 Server Status", callback_data="help_status"),
        ],
    ])


def get_back_button() -> InlineKeyboardMarkup:
    """Standard back button returning to the main menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="help_home")]
    ])


def build_welcome_text(user_first_name: str) -> str:
    mode_label = (
        "🚀 **4.0 GB (Hybrid Premium Enabled)**"
        if Config.is_premium_enabled()
        else "⚡ **2.0 GB (Standard Bot Mode)**"
    )
    return (
        f"👋 Hello **{user_first_name}**!\n\n"
        f"Welcome to **Any URL, HLS, Zoom & Google Drive Downloader Bot v2.0.0**.\n\n"
        f"**System Capabilities:**\n"
        f"• **Active Upload Limit:** {mode_label}\n"
        f"• 📥 **Direct URLs:** 8-connection parallel chunk downloading for max speed.\n"
        f"• 📡 **HLS / DASH Streams:** 16-fragment concurrent `.m3u8` / `.mpd` merging.\n"
        f"• 🎥 **Zoom Cloud:** Automated recording download with interactive passcode prompt.\n"
        f"• 📁 **Google Drive:** Direct downloads for public files & shared folders.\n"
        f"• 📝 **Custom Captions:** Interactive 30-second caption prompt before upload.\n"
        f"• 🎬 **Fast Video Streaming:** Real-time thumbnail & metadata extraction.\n\n"
        f"👇 **Tap the menu buttons below to explore guides and features:**"
    )


# ==============================================================================
# Command Handlers
# ==============================================================================

@bot.on_message(filters.command("start") & filters.private)
async def start_handler(client: Client, message: Message):
    """Handler for /start command."""
    user = message.from_user
    if not is_authorized(user.id):
        await message.reply_text(
            f"⛔ **Access Denied**\n\n"
            f"You are not authorized to use this bot.\n"
            f"Your Telegram User ID: `{user.id}`\n"
            f"Please share this ID with the administrator to request access."
        )
        return

    await message.reply_text(
        build_welcome_text(user.first_name),
        reply_markup=get_main_menu_keyboard(),
    )


@bot.on_message(filters.command("help") & filters.private)
async def help_handler(client: Client, message: Message):
    """Handler for /help command."""
    user = message.from_user
    if not is_authorized(user.id):
        await message.reply_text(f"⛔ Access Denied. Your User ID: `{user.id}`")
        return

    await message.reply_text(
        "📖 **Interactive Help & Documentation**\n\n"
        "Select a topic below to view copy-ready examples and usage tips:",
        reply_markup=get_main_menu_keyboard(),
    )


@bot.on_message(filters.command("status") & filters.private)
async def status_handler(client: Client, message: Message):
    """Handler for /status command."""
    user = message.from_user
    if not is_authorized(user.id):
        return

    premium_status = "🌟 Active (4GB Hybrid Enabled)" if Config.is_premium_enabled() else "⚪ Inactive (2GB Bot Limit)"
    dump_status = f"✅ Configured (`{Config.DUMP_CHAT_ID}`)" if Config.DUMP_CHAT_ID else "⚪ Not Configured (Direct Fallback)"
    cookies_status = "✅ Present (`cookies.txt`)" if Config.COOKIES_FILE.is_file() else "⚪ Not Found"
    max_size_label = "4.0 GB (Hybrid Premium)" if Config.is_premium_enabled() else "2.0 GB (Bot Only)"

    status_text = (
        f"📊 **System Status & Health (v2.0.0)**\n\n"
        f"• **Active Downloads:** `{ACTIVE_DOWNLOADS_COUNT} / {Config.MAX_CONCURRENT_DOWNLOADS}`\n"
        f"• **Max Upload Size:** `{max_size_label}`\n"
        f"• **Direct Engine:** `8-Connection Parallel Range (aiohttp)`\n"
        f"• **Stream Engine:** `16-Fragment Concurrent (yt-dlp Native HLS)`\n"
        f"• **Google Drive:** `Active (gdown engine)`\n"
        f"• **Premium User Session:** {premium_status}\n"
        f"• **Dump Channel Relay:** {dump_status}\n"
        f"• **Zoom Cookies:** {cookies_status}\n"
        f"• **Progress Throttle:** `{Config.PROGRESS_UPDATE_INTERVAL}s`\n"
        f"• **Access Control:** `{'Restricted (' + str(len(Config.AUTHORIZED_USERS)) + ' users)' if Config.AUTHORIZED_USERS else 'Public Mode'}`"
    )
    await message.reply_text(status_text, reply_markup=get_back_button())


# ==============================================================================
# Interactive Callback Query Handlers
# ==============================================================================

@bot.on_callback_query()
async def callback_query_handler(client: Client, query: CallbackQuery):
    """Handles all inline keyboard callback queries."""
    user = query.from_user
    if not is_authorized(user.id):
        await query.answer("⛔ Access Denied.", show_alert=True)
        return

    data = query.data

    # 1. Main Navigation Menu
    if data == "help_home":
        await query.message.edit_text(
            build_welcome_text(user.first_name),
            reply_markup=get_main_menu_keyboard(),
        )
        await query.answer()

    elif data == "help_links":
        text = (
            "📥 **Supported Link Types & Syntax**\n\n"
            "**1. Direct URLs (High-Speed Multi-Connection):**\n"
            "• Standard:\n"
            "`https://example.com/files/archive.zip`\n"
            "• Custom filename:\n"
            "`https://example.com/files/archive.zip | my_backup.zip`\n\n"
            "**2. HLS & DASH Streams (.m3u8 / .mpd):**\n"
            "• Auto-decoded parent folder title (Sinhala / Unicode supported):\n"
            "`https://cdn.site.com/videos/%E0%B6%B4%E0%B7%8F%E0%B6%A9%E0%B6%B8/master.m3u8`\n"
            "• Custom filename:\n"
            "`https://cdn.site.com/stream/index.m3u8 | Physics_Lecture.mp4`\n\n"
            "**3. Google Drive Links:**\n"
            "• File or folder link:\n"
            "`https://drive.google.com/file/d/1A2B3C4D5E6F/view`\n"
            "• Custom filename:\n"
            "`https://drive.google.com/file/d/1A2B3C4D5E6F/view | Dataset.zip`"
        )
        await query.message.edit_text(text, reply_markup=get_back_button())
        await query.answer()

    elif data == "help_zoom":
        text = (
            "🔐 **Zoom Cloud Recording Guide**\n\n"
            "The bot provides two convenient ways to download Zoom recordings:\n\n"
            "**Method A — Interactive Passcode Prompt (New in v2.0):**\n"
            "1. Simply send your Zoom link:\n"
            "   `https://us02web.zoom.us/rec/share/abc123xyz`\n"
            "2. If protected, the bot will prompt: *'Please reply with the Zoom Passcode now'*\n"
            "3. Send your passcode in the chat and download starts immediately!\n\n"
            "**Method B — Inline Pipe Syntax:**\n"
            "• `Zoom_URL | passcode`\n"
            "• `Zoom_URL | passcode | Lecture_01.mp4`\n\n"
            "💡 **Institutional Zoom Links (403 Forbidden):**\n"
            "If your university/work restricts recordings, place an authenticated Netscape `cookies.txt` "
            "file in the bot root directory. The bot will use it automatically."
        )
        await query.message.edit_text(text, reply_markup=get_back_button())
        await query.answer()

    elif data == "help_gdrive":
        text = (
            "📁 **Google Drive Download Guide**\n\n"
            "The bot natively supports high-speed Google Drive downloads powered by `gdown`.\n\n"
            "**Supported URL formats:**\n"
            "• `https://drive.google.com/file/d/FILE_ID/view?usp=sharing`\n"
            "• `https://drive.google.com/open?id=FILE_ID`\n"
            "• `https://drive.google.com/uc?id=FILE_ID`\n"
            "• Public Google Drive shared folders\n\n"
            "**Custom Output Filename:**\n"
            "`https://drive.google.com/file/d/FILE_ID/view | Research_Paper.pdf`\n\n"
            "⚡ Downloads are streamed at full VPS line-speed with automatic confirmation tokens."
        )
        await query.message.edit_text(text, reply_markup=get_back_button())
        await query.answer()

    elif data == "help_naming":
        text = (
            "⚙️ **Caption & Naming Guide**\n\n"
            "**1. Custom Filename Override (Pipe Syntax):**\n"
            "Attach `| filename.ext` to any URL:\n"
            "`https://example.com/stream.m3u8 | My_Video.mp4`\n\n"
            "**2. Interactive Caption Prompt (New in v2.0):**\n"
            "• Once any download completes, the bot presents an interactive prompt:\n"
            "  *'Send a custom Caption for this upload, or tap Use Default Filename'*\n"
            "• Send any custom text (formatting & emojis supported) within 30 seconds!\n"
            "• If no text is sent or if you tap the button, the clean filename is used automatically."
        )
        await query.message.edit_text(text, reply_markup=get_back_button())
        await query.answer()

    elif data == "help_status":
        premium_status = "🌟 Active (4GB Hybrid Enabled)" if Config.is_premium_enabled() else "⚪ Inactive (2GB Bot Limit)"
        dump_status = f"✅ Configured (`{Config.DUMP_CHAT_ID}`)" if Config.DUMP_CHAT_ID else "⚪ Not Configured"
        max_size_label = "4.0 GB (Hybrid Premium)" if Config.is_premium_enabled() else "2.0 GB (Bot Only)"

        status_text = (
            f"📊 **Live Server Health & Status**\n\n"
            f"• **Active Downloads:** `{ACTIVE_DOWNLOADS_COUNT} / {Config.MAX_CONCURRENT_DOWNLOADS}`\n"
            f"• **Max Upload Size:** `{max_size_label}`\n"
            f"• **Direct Downloads:** `Multi-Connection Range (8 workers)`\n"
            f"• **HLS Streams:** `16 Concurrent Fragments`\n"
            f"• **Google Drive:** `Active (gdown)`\n"
            f"• **Premium Session:** {premium_status}\n"
            f"• **Dump Channel:** {dump_status}\n"
            f"• **Progress Interval:** `{Config.PROGRESS_UPDATE_INTERVAL}s`"
        )
        await query.message.edit_text(status_text, reply_markup=get_back_button())
        await query.answer()

    # 2. Cancel Zoom Passcode Waiting
    elif data.startswith("cancel_zoom_"):
        uid = int(data.split("_")[-1])
        if uid == user.id and uid in PASSCODE_WAITERS:
            fut = PASSCODE_WAITERS[uid]
            if not fut.done():
                fut.cancel()
            await query.answer("Zoom download cancelled.")
            try:
                await query.message.edit_text("❌ **Zoom download cancelled.**")
            except RPCError:
                pass

    # 3. Caption Actions
    elif data.startswith("caption_default_"):
        uid = user.id
        if uid in CAPTION_WAITERS:
            fut, _ = CAPTION_WAITERS[uid]
            if not fut.done():
                fut.set_result("DEFAULT")
            await query.answer("Proceeding with default filename caption.")

    elif data.startswith("caption_cancel_"):
        uid = user.id
        if uid in CAPTION_WAITERS:
            fut, _ = CAPTION_WAITERS[uid]
            if not fut.done():
                fut.set_result("CANCEL")
            await query.answer("Upload cancelled.")


# ==============================================================================
# Input Parser
# ==============================================================================

def parse_user_input(text: str) -> Tuple[str, Optional[str], Optional[str]]:
    """
    Parse user message into (url, passcode, custom_filename).
    Supported formats:
    - URL
    - URL | custom_filename.ext
    - Zoom_URL | passcode
    - Zoom_URL | passcode | custom_filename.mp4
    """
    parts = [p.strip() for p in text.split("|") if p.strip()]
    if not parts:
        return "", None, None

    url = parts[0]
    is_zoom = is_zoom_url(url)

    passcode: Optional[str] = None
    custom_filename: Optional[str] = None

    if is_zoom:
        if len(parts) == 2:
            second_part = parts[1]
            if Path(second_part).suffix.lower() in [".mp4", ".mkv", ".mov", ".webm"]:
                custom_filename = second_part
            else:
                passcode = second_part
        elif len(parts) >= 3:
            passcode = parts[1]
            custom_filename = parts[2]
    else:
        if len(parts) >= 2:
            custom_filename = parts[1]

    return url, passcode, custom_filename


# ==============================================================================
# Main Message Handler
# ==============================================================================

@bot.on_message(filters.text & filters.private & ~filters.command(["start", "help", "status"]))
async def download_request_handler(client: Client, message: Message):
    """Main message handler for incoming download requests and interactive responses."""
    global ACTIVE_DOWNLOADS_COUNT
    user = message.from_user

    # Access control
    if not is_authorized(user.id):
        await message.reply_text(
            f"⛔ **Access Denied**\n\n"
            f"You are not authorized to use this bot.\n"
            f"Your Telegram User ID: `{user.id}`\n"
            f"Please share this ID with the administrator to request access."
        )
        return

    raw_text = message.text.strip()

    # --- Check for Active Interactive Waiters ---

    # 1. Check if user is replying to a Zoom Passcode prompt
    if user.id in PASSCODE_WAITERS:
        fut = PASSCODE_WAITERS[user.id]
        if not fut.done():
            fut.set_result(raw_text)
            return

    # 2. Check if user is replying to a Post-Download Caption prompt
    if user.id in CAPTION_WAITERS:
        fut, _ = CAPTION_WAITERS[user.id]
        if not fut.done():
            fut.set_result(raw_text)
            return

    # Parse new download URL request
    url, passcode, custom_filename = parse_user_input(raw_text)

    # Validate URL structure
    if not (url.startswith("http://") or url.startswith("https://")):
        await message.reply_text(
            "⚠️ **Invalid URL:** Please send a valid link starting with `http://` or `https://`.\n"
            "Send `/help` for syntax examples.",
            reply_markup=get_main_menu_keyboard(),
        )
        return

    # --- Interactive Zoom Passcode Detection ---
    if is_zoom_url(url) and not passcode:
        # Check if the Zoom recording requires a passcode before queueing
        requires_passcode = False

        def check_zoom_passcode_sync() -> bool:
            ydl_check_opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "http_headers": {
                    "User-Agent": Config.DEFAULT_USER_AGENT,
                    "Referer": url,
                },
            }
            if Config.COOKIES_FILE.is_file():
                ydl_check_opts["cookiefile"] = str(Config.COOKIES_FILE)

            with yt_dlp.YoutubeDL(ydl_check_opts) as ydl:
                try:
                    ydl.extract_info(url, download=False)
                    return False
                except (ExtractorError, DownloadError) as e:
                    err_str = str(e).lower()
                    if "passcode" in err_str or "password" in err_str or "wrong passcode" in err_str:
                        return True
                    return False
                except Exception:
                    return False

        requires_passcode = await asyncio.to_thread(check_zoom_passcode_sync)

        if requires_passcode:
            passcode_future = asyncio.get_running_loop().create_future()
            PASSCODE_WAITERS[user.id] = passcode_future

            prompt_msg = await message.reply_text(
                "🔐 **This Zoom recording requires a Passcode.**\n\n"
                "Please reply with the Zoom Passcode now to start downloading:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_zoom_{user.id}")]
                ])
            )

            try:
                captured_passcode = await asyncio.wait_for(passcode_future, timeout=120.0)
                passcode = captured_passcode.strip()
            except asyncio.TimeoutError:
                await prompt_msg.edit_text("⏱️ **Passcode entry timed out.** Please resend the Zoom link.")
                return
            except asyncio.CancelledError:
                await prompt_msg.edit_text("❌ **Zoom download cancelled.**")
                return
            finally:
                PASSCODE_WAITERS.pop(user.id, None)
                try:
                    await prompt_msg.delete()
                except Exception:
                    pass

    # Create status message
    status_msg = await message.reply_text("⏳ **Queued:** Waiting for an available download slot...")

    # Unique task ID and isolated workspace directory
    task_id = f"{user.id}_{uuid.uuid4().hex[:8]}"
    task_dir = Config.DOWNLOAD_DIR / task_id

    try:
        # Acquire semaphore to respect concurrency limits
        async with DOWNLOAD_SEMAPHORE:
            ACTIVE_DOWNLOADS_COUNT += 1
            task_dir.mkdir(parents=True, exist_ok=True)

            display_name = sanitize_filename(custom_filename) if custom_filename else "Initializing..."
            progress = ProgressTracker(status_msg, filename=display_name)

            await status_msg.edit_text("🔍 **Connecting and analyzing stream...**")

            # --- 1. Download Stage ---
            is_zoom = is_zoom_url(url)
            is_stream = is_stream_url(url)
            is_gdrive = is_gdrive_url(url)

            if is_zoom:
                dl_type = "Zoom Cloud Recording"
            elif is_stream:
                dl_type = "HLS/DASH Stream"
            elif is_gdrive:
                dl_type = "Google Drive"
            else:
                dl_type = "High-Speed Direct URL"

            logger.info(f"Task {task_id}: Starting {dl_type} for URL: {url}")

            if is_zoom or is_stream:
                downloaded_file = await download_stream_or_zoom(
                    url=url,
                    output_dir=task_dir,
                    passcode=passcode,
                    custom_filename=custom_filename,
                    progress_tracker=progress,
                )
            elif is_gdrive:
                downloaded_file = await download_gdrive_file(
                    url=url,
                    output_dir=task_dir,
                    custom_filename=custom_filename,
                    progress_tracker=progress,
                )
            else:
                downloaded_file = await download_direct_url(
                    url=url,
                    output_dir=task_dir,
                    custom_filename=custom_filename,
                    progress_tracker=progress,
                )

            # Validate file existence and size
            if not downloaded_file.exists():
                raise FileNotFoundError("The file was not found on disk after download.")

            file_size = downloaded_file.stat().st_size
            if file_size > Config.MAX_FILE_SIZE:
                limit_str = format_bytes(Config.MAX_FILE_SIZE)
                raise ValueError(
                    f"Downloaded file size ({format_bytes(file_size)}) exceeds active upload limit of {limit_str}."
                )

            # --- 2. Metadata & Thumbnail Extraction (for Video Files) ---
            progress.set_filename(downloaded_file.name)
            thumb_path: Optional[str] = None
            duration = 0
            width = 0
            height = 0

            if is_video_file(downloaded_file):
                await status_msg.edit_text("🎬 **Extracting video metadata & generating thumbnail...**")
                duration, width, height = await get_video_metadata(downloaded_file)

                thumb_target = task_dir / f"thumb_{task_id}.jpg"
                thumb_path = await generate_thumbnail(downloaded_file, thumb_target, duration=duration)

            # --- 3. Interactive Post-Download Caption Prompt ---
            caption_future = asyncio.get_running_loop().create_future()
            CAPTION_WAITERS[user.id] = (caption_future, task_id)

            caption_prompt_msg = await message.reply_text(
                f"✅ **Download Complete!**\n"
                f"📁 **File:** `{downloaded_file.name}`\n"
                f"💾 **Size:** `{format_bytes(file_size)}`\n\n"
                f"📝 **Send a custom Caption for this upload**, or tap below:\n"
                f"*(Automatically uses default filename after 30 seconds)*",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "⏭️ Use Default Filename",
                            callback_data=f"caption_default_{task_id}"
                        ),
                        InlineKeyboardButton(
                            "❌ Cancel Upload",
                            callback_data=f"caption_cancel_{task_id}"
                        ),
                    ]
                ])
            )

            user_caption_choice = None
            try:
                user_caption_choice = await asyncio.wait_for(caption_future, timeout=30.0)
            except asyncio.TimeoutError:
                user_caption_choice = "DEFAULT"
            finally:
                CAPTION_WAITERS.pop(user.id, None)
                try:
                    await caption_prompt_msg.delete()
                except Exception:
                    pass

            # Abort if user chose cancel
            if user_caption_choice == "CANCEL":
                await status_msg.edit_text("❌ **Upload Cancelled by user.**")
                return

            # Determine final caption
            if user_caption_choice and user_caption_choice != "DEFAULT":
                caption = user_caption_choice.strip()
            else:
                caption = (
                    f"📁 **File:** `{downloaded_file.name}`\n"
                    f"💾 **Size:** `{format_bytes(file_size)}`\n"
                    f"{'⏱ **Duration:** `' + format_time(duration) + '`' if duration > 0 else ''}"
                ).strip()

            # --- 4. Hybrid Upload Stage ---
            progress.set_mode("upload")

            async def upload_progress_callback(current: int, total: int):
                await progress.update_upload(current=current, total=total)

            # --- Hybrid Upload Branching ---
            if file_size > Config.BOT_MAX_SIZE:
                # File is between 2GB and 4GB -> requires Telegram Premium user session
                if not user_app:
                    raise ValueError(
                        f"⚠️ **File Size Exceeds Bot Limit (2.0 GB):**\n"
                        f"Downloaded file size: **{format_bytes(file_size)}**.\n"
                        f"To unlock uploads up to 4.0 GB, configure a Telegram Premium `USER_SESSION_STRING` in `.env`."
                    )

                logger.info(
                    f"Task {task_id}: File size {format_bytes(file_size)} > 2GB. Relaying via Premium user session."
                )
                await status_msg.edit_text(
                    f"🚀 **Relaying 4GB Upload via Telegram Premium Session...**\n"
                    f"📁 **File:** `{downloaded_file.name}`\n"
                    f"💾 **Size:** `{format_bytes(file_size)}`"
                )

                target_chat = Config.DUMP_CHAT_ID if Config.DUMP_CHAT_ID else message.chat.id
                uploaded_msg = None

                if is_video_file(downloaded_file):
                    try:
                        uploaded_msg = await user_app.send_video(
                            chat_id=target_chat,
                            video=str(downloaded_file),
                            caption=caption,
                            duration=duration,
                            width=width,
                            height=height,
                            thumb=thumb_path,
                            supports_streaming=True,
                            progress=upload_progress_callback,
                        )
                    except Exception as upload_err:
                        logger.warning(
                            f"Task {task_id}: user_app send_video failed ({upload_err}). Falling back to send_document."
                        )

                if not uploaded_msg:
                    uploaded_msg = await user_app.send_document(
                        chat_id=target_chat,
                        document=str(downloaded_file),
                        caption=caption,
                        thumb=thumb_path,
                        progress=upload_progress_callback,
                    )

                # If uploaded to DUMP_CHAT_ID, cleanly relay file to user's chat via bot.copy_message
                if Config.DUMP_CHAT_ID and uploaded_msg:
                    try:
                        await bot.copy_message(
                            chat_id=message.chat.id,
                            from_chat_id=Config.DUMP_CHAT_ID,
                            message_id=uploaded_msg.id,
                        )
                    except RPCError as copy_err:
                        logger.error(f"Task {task_id}: Failed to copy message from DUMP_CHAT_ID: {copy_err}")
                        await message.reply_text(
                            f"✅ Upload succeeded to relay channel, but failed to forward to this chat: {copy_err}\n"
                            "Please ensure the bot has administrator permissions in the dump chat."
                        )

            else:
                # File is <= 2GB -> Standard upload directly by bot
                logger.info(f"Task {task_id}: Uploading {downloaded_file.name} ({format_bytes(file_size)}) via bot.")
                uploaded_msg = None

                if is_video_file(downloaded_file):
                    try:
                        uploaded_msg = await bot.send_video(
                            chat_id=message.chat.id,
                            video=str(downloaded_file),
                            caption=caption,
                            duration=duration,
                            width=width,
                            height=height,
                            thumb=thumb_path,
                            supports_streaming=True,
                            progress=upload_progress_callback,
                        )
                    except Exception as upload_err:
                        logger.warning(
                            f"Task {task_id}: bot send_video failed ({upload_err}). Falling back to send_document."
                        )

                if not uploaded_msg:
                    uploaded_msg = await bot.send_document(
                        chat_id=message.chat.id,
                        document=str(downloaded_file),
                        caption=caption,
                        thumb=thumb_path,
                        progress=upload_progress_callback,
                    )

            # Clean up progress status message
            try:
                await status_msg.delete()
            except RPCError:
                pass

            logger.info(f"Task {task_id}: Processing and upload finished successfully.")

    except Exception as exc:
        logger.error(f"Task {task_id} failed: {exc}", exc_info=True)
        error_details = str(exc)
        try:
            await status_msg.edit_text(f"❌ **Task Failed:**\n{error_details}")
        except RPCError:
            pass

    finally:
        ACTIVE_DOWNLOADS_COUNT = max(0, ACTIVE_DOWNLOADS_COUNT - 1)
        # 5. Mandatory Workspace Cleanup (Guarantee temporary files are removed immediately)
        clean_directory(task_dir)


async def main():
    """Start primary bot and optional secondary user app cleanly."""
    apps = [bot]
    if user_app is not None:
        apps.append(user_app)
        logger.info("🚀 4GB Hybrid Upload Support is ENABLED (Premium User Session Active).")
    else:
        logger.info("⚡ Standard 2GB Upload Support is ACTIVE (Bot Only Mode).")

    if Config.USER_SESSION_STRING and not Config.DUMP_CHAT_ID:
        logger.warning(
            "⚠️ DUMP_CHAT_ID is not configured. When uploading files >2GB to other users, "
            "configuring a private Dump Channel where both bot and user account are admins is strongly recommended."
        )

    await compose(apps)


if __name__ == "__main__":
    Config.validate()
    logger.info("Starting Direct URL & Zoom Cloud Downloader Bot...")
    bot.run(main())
