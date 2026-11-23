import asyncio
import logging
import os
import re
import urllib.parse
from pathlib import Path
from typing import Optional

import aiofiles
import aiohttp
import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

from config import Config
from utils import format_bytes, sanitize_filename

logger = logging.getLogger(__name__)

# Zoom URL pattern matcher for both rec and recording paths
ZOOM_PATTERN = re.compile(
    r"https?://(?:[a-zA-Z0-9-]+\.)?zoom\.us/(?:rec|recording)/(?:play|share)/[^\s?#]+",
    re.IGNORECASE
)


def is_zoom_url(url: str) -> bool:
    """Check if the provided URL is a Zoom cloud recording link."""
    return bool(
        ZOOM_PATTERN.search(url)
        or ("zoom.us/" in url and ("/rec/" in url or "/recording/" in url))
    )


def is_stream_url(url: str) -> bool:
    """Check if the URL points to an HLS (.m3u8) or DASH (.mpd) streaming manifest."""
    parsed = urllib.parse.urlparse(url)
    path_lower = parsed.path.lower()
    return path_lower.endswith(".m3u8") or path_lower.endswith(".mpd")


def _derive_stream_filename(url: str) -> str:
    """
    Derive a human-readable filename from a streaming manifest URL.

    For URLs ending with /master.m3u8 or /index.m3u8, use the URL-decoded
    parent folder name as the video title (handles Sinhala/Unicode folder names).
    Otherwise, use the manifest filename stem.
    """
    parsed = urllib.parse.urlparse(url)
    decoded_path = urllib.parse.unquote(parsed.path)
    path_obj = Path(decoded_path)

    basename_lower = path_obj.name.lower()
    if basename_lower in ("master.m3u8", "index.m3u8"):
        parent_name = path_obj.parent.name
        if parent_name:
            return sanitize_filename(f"{parent_name}.mp4")

    # Fallback: use the manifest's own stem
    stem = path_obj.stem
    if stem:
        return sanitize_filename(f"{stem}.mp4")

    return "stream_video.mp4"


def extract_filename_from_headers(headers: aiohttp.typedefs.LooseHeaders, url: str) -> str:
    """
    Extract filename from HTTP headers (Content-Disposition) or fallback to URL path.
    Complies with RFC 5987 / RFC 6266 without using the deprecated cgi module.
    """
    content_disp = headers.get("Content-Disposition") or headers.get("content-disposition", "")
    filename: Optional[str] = None

    if content_disp:
        # 1. Try RFC 5987/6266 format: filename*=UTF-8''filename.ext
        match_utf8 = re.search(
            r"filename\*\s*=\s*(?:UTF-8|iso-8859-1)''([^;\s]+)",
            content_disp,
            re.IGNORECASE
        )
        if match_utf8:
            filename = urllib.parse.unquote(match_utf8.group(1))

        # 2. Standard format: filename="filename.ext" or filename=filename.ext
        if not filename:
            match_std = re.search(r'filename\s*=\s*(?:"([^"]+)"|([^;\s]+))', content_disp, re.IGNORECASE)
            if match_std:
                filename = match_std.group(1) or match_std.group(2)

    # 3. Fallback to URL path
    if not filename:
        parsed_path = urllib.parse.urlparse(url).path
        base = os.path.basename(parsed_path)
        if base:
            filename = urllib.parse.unquote(base)

    # 4. Final fallback if still empty or generic
    if not filename or filename.strip() == "":
        content_type = headers.get("Content-Type", "").lower()
        if "video/mp4" in content_type:
            filename = "video.mp4"
        elif "application/pdf" in content_type:
            filename = "document.pdf"
        elif "application/zip" in content_type:
            filename = "archive.zip"
        else:
            filename = "downloaded_file.bin"

    return sanitize_filename(filename)


async def download_direct_url(
    url: str,
    output_dir: Path,
    custom_filename: Optional[str],
    progress_tracker
) -> Path:
    """
    Download a direct file URL asynchronously using streaming chunks with aiohttp.
    Supports throttled progress reporting and dynamically enforces Config.MAX_FILE_SIZE (2GB or 4GB).
    """
    headers = {
        "User-Agent": Config.DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",  # Avoid gzip/chunked encoding issues for accurate size reporting
    }

    timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=180)

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        async with session.get(url, allow_redirects=True) as response:
            if response.status >= 400:
                raise ValueError(f"HTTP Server returned error {response.status}: {response.reason}")

            # Check content length against active maximum size limit
            content_length = response.content_length or 0
            if content_length > Config.MAX_FILE_SIZE:
                limit_str = format_bytes(Config.MAX_FILE_SIZE)
                raise ValueError(
                    f"File size ({format_bytes(content_length)}) exceeds the maximum allowed limit of {limit_str}."
                )

            # Determine filename
            if custom_filename:
                final_name = sanitize_filename(custom_filename)
                # If custom name lacks extension, infer from response headers/url
                if not Path(final_name).suffix:
                    inferred_name = extract_filename_from_headers(response.headers, str(response.url))
                    inferred_ext = Path(inferred_name).suffix
                    if inferred_ext:
                        final_name = f"{final_name}{inferred_ext}"
            else:
                final_name = extract_filename_from_headers(response.headers, str(response.url))

            progress_tracker.set_filename(final_name)
            output_filepath = output_dir / final_name

            # Stream response to file
            downloaded_bytes = 0
            chunk_size = 512 * 1024  # 512 KB chunks

            async with aiofiles.open(output_filepath, mode="wb") as f:
                async for chunk in response.content.iter_chunked(chunk_size):
                    await f.write(chunk)
                    downloaded_bytes += len(chunk)

                    # Guard against runaway downloads exceeding limit when Content-Length is missing/inaccurate
                    if downloaded_bytes > Config.MAX_FILE_SIZE:
                        limit_str = format_bytes(Config.MAX_FILE_SIZE)
                        raise ValueError(f"Download aborted: Stream exceeded the maximum limit of {limit_str}.")

                    await progress_tracker.update_download(
                        current=downloaded_bytes,
                        total=content_length
                    )

            # Ensure final progress update reaches 100%
            await progress_tracker.update_download(
                current=downloaded_bytes,
                total=downloaded_bytes if content_length <= 0 else content_length
            )

            return output_filepath


class _StreamDownloadState:
    """Thread-safe state object for tracking yt-dlp progress."""
    def __init__(self):
        self.downloaded_bytes: int = 0
        self.total_bytes: int = 0
        self.speed: float = 0.0
        self.eta: float = 0.0
        self.is_done: bool = False
        self.error: Optional[Exception] = None


async def download_stream_or_zoom(
    url: str,
    output_dir: Path,
    passcode: Optional[str],
    custom_filename: Optional[str],
    progress_tracker
) -> Path:
    """
    Unified yt-dlp downloader for Zoom cloud recordings and HLS/DASH streams.
    Downloads all fragments concurrently and merges them into a single .mp4 file.
    Handles passcode authentication, browser headers, optional cookies.txt, and progress tracking.
    Enforces Config.MAX_FILE_SIZE. Runs yt-dlp in a worker thread to avoid blocking asyncio.
    """
    state = _StreamDownloadState()

    def ydl_progress_hook(d: dict) -> None:
        """Callback invoked by yt-dlp in the worker thread."""
        status = d.get("status")
        if status == "downloading":
            state.downloaded_bytes = d.get("downloaded_bytes", 0)
            state.total_bytes = d.get("total_bytes") or d.get("total_bytes_estimate", 0)
            state.speed = float(d.get("speed") or 0.0)
            state.eta = float(d.get("eta") or 0.0)
        elif status == "finished":
            state.is_done = True

    # Safe ASCII template to prevent ffmpeg non-ASCII/Unicode/Sinhala remuxing errors
    out_template = str(output_dir / "stream_output.%(ext)s")

    # HTTP headers: Only include Referer for Zoom recordings (avoids AWS S3 403 Forbidden errors on manifests)
    http_headers = {
        "User-Agent": Config.DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if is_zoom_url(url):
        http_headers["Referer"] = url

    ydl_opts = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "concurrent_fragment_downloads": 4,
        "hls_prefer_native": True,
        "downloader": "native",
        "max_filesize": Config.MAX_FILE_SIZE,
        "outtmpl": out_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [ydl_progress_hook],
        "http_headers": http_headers,
    }

    # Pass passcode to yt-dlp if provided (Zoom recordings)
    if passcode:
        ydl_opts["videopassword"] = passcode.strip()

    # Pass cookiefile if cookies.txt exists on disk
    if Config.COOKIES_FILE.is_file():
        ydl_opts["cookiefile"] = str(Config.COOKIES_FILE)
        logger.info(f"Using cookies file: {Config.COOKIES_FILE}")

    # Async monitor task to periodically update Telegram progress
    async def monitor_progress():
        while not state.is_done and state.error is None:
            if state.downloaded_bytes > 0:
                await progress_tracker.update_download(
                    current=state.downloaded_bytes,
                    total=state.total_bytes,
                    speed=state.speed,
                    eta=state.eta
                )
            await asyncio.sleep(Config.PROGRESS_UPDATE_INTERVAL)

    monitor_task = asyncio.create_task(monitor_progress())

    info_dict = None

    def run_ydl_sync():
        nonlocal info_dict
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=True)
            return info_dict

    try:
        await asyncio.to_thread(run_ydl_sync)
    except (ExtractorError, DownloadError) as e:
        err_msg = str(e).lower()
        if "larger than max-filesize" in err_msg:
            limit_str = format_bytes(Config.MAX_FILE_SIZE)
            raise ValueError(f"⚠️ **File Size Limit Exceeded:** The recording exceeds the maximum limit of {limit_str}.") from e
        elif "passcode" in err_msg or "password" in err_msg or "wrong passcode" in err_msg:
            raise ValueError(
                "🔒 **Zoom Passcode Error:** This recording is protected by a passcode.\n"
                "Please provide it in the format:\n"
                "`<Zoom URL> | <passcode>`"
            ) from e
        elif "403" in err_msg or "forbidden" in err_msg:
            raise ValueError(
                "🚫 **Access Denied (403 Forbidden):**\n"
                "The server has restricted access to this content.\n"
                "💡 Tip: If you have valid browser cookies, save them to `cookies.txt` in the bot directory."
            ) from e
        else:
            raise ValueError(f"⚠️ **Stream/Zoom Download Failed:** {e}") from e
    finally:
        state.is_done = True
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

    # Find the downloaded file in the output directory
    downloaded_files = [
        f for f in output_dir.glob("*")
        if f.is_file() and not f.name.endswith(".part") and not f.name.endswith(".ytdl")
    ]
    if not downloaded_files:
        raise FileNotFoundError("yt-dlp completed, but no downloaded file was found in the workspace.")

    # Sort by modification time to get the primary downloaded video
    downloaded_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    primary_file = downloaded_files[0]

    # Handle custom filename or derive from stream URL / Zoom metadata
    if custom_filename:
        safe_custom = sanitize_filename(custom_filename)
        # Preserve extension if missing
        if not Path(safe_custom).suffix and primary_file.suffix:
            safe_custom = f"{safe_custom}{primary_file.suffix}"
        target_path = output_dir / safe_custom
        if target_path != primary_file:
            primary_file.rename(target_path)
            primary_file = target_path
    elif is_stream_url(url):
        # For stream URLs, derive a meaningful filename from the URL path
        derived_name = _derive_stream_filename(url)
        target_path = output_dir / derived_name
        if target_path != primary_file:
            primary_file.rename(target_path)
            primary_file = target_path
    elif is_zoom_url(url):
        zoom_title = (info_dict or {}).get("title")
        if zoom_title and zoom_title.strip() and zoom_title != "stream_output":
            safe_zoom = sanitize_filename(f"{zoom_title}{primary_file.suffix}")
            target_path = output_dir / safe_zoom
            if target_path != primary_file:
                primary_file.rename(target_path)
                primary_file = target_path

    progress_tracker.set_filename(primary_file.name)
    return primary_file
