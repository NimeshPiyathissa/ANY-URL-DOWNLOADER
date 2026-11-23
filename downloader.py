import asyncio
import html
import logging
import math
import os
import re
import shutil
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple

import aiofiles
import aiohttp
import gdown
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

# Google Drive URL pattern matchers (file, folder, open?id=, uc?id=)
GDRIVE_PATTERN = re.compile(
    r"https?://(?:drive|docs)\.google\.com/(?:(?:file/d/|open\?id=|uc\?id=|drive/folders/)|(?:document|spreadsheets|presentation)/d/)([a-zA-Z0-9_-]+)",
    re.IGNORECASE
)
GDRIVE_FILE_PATTERN = re.compile(
    r"(?:/d/|[?&]id=)([a-zA-Z0-9_-]+)",
    re.IGNORECASE
)
GDRIVE_FOLDER_PATTERN = re.compile(
    r"/folders/([a-zA-Z0-9_-]+)",
    re.IGNORECASE
)


class ZoomPasscodeRequiredError(ValueError):
    """Raised when a Zoom cloud recording requires a passcode or authentication."""
    pass


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


def is_gdrive_url(url: str) -> bool:
    """Check if the provided URL is a Google Drive file or folder link."""
    return bool(
        GDRIVE_PATTERN.search(url)
        or ("drive.google.com" in url)
        or ("docs.google.com" in url and "/d/" in url)
    )


def _parse_size_str(s: str) -> int:
    """Parse size strings (e.g. '150MiB', '2.5GiB', '500KiB', '1024B') into integer bytes."""
    s = s.strip()
    units = {
        "b": 1,
        "k": 1024, "kb": 1000, "kib": 1024,
        "m": 1024**2, "mb": 1000**2, "mib": 1024**2,
        "g": 1024**3, "gb": 1000**3, "gib": 1024**3,
        "t": 1024**4, "tb": 1000**4, "tib": 1024**4,
    }
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([a-zA-Z]*)$", s)
    if not m:
        return 0
    val, unit = float(m.group(1)), m.group(2).lower()
    return int(val * units.get(unit, 1))


def _parse_eta_str(s: str) -> float:
    """Parse ETA strings (e.g. '14s', '1m30s', '1h', '01:30', '01:15:30') into seconds."""
    s = s.strip().lower()
    if ":" in s:
        parts = s.split(":")
        try:
            if len(parts) == 2:
                return float(int(parts[0]) * 60 + int(parts[1]))
            elif len(parts) == 3:
                return float(int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
        except ValueError:
            pass
    total = 0.0
    matches = re.findall(r"(\d+)([hms])", s)
    if matches:
        for val, unit in matches:
            if unit == "h":
                total += int(val) * 3600
            elif unit == "m":
                total += int(val) * 60
            elif unit == "s":
                total += int(val)
        return total
    try:
        return float(s)
    except ValueError:
        return 0.0


def _load_netscape_cookies(cookies_path: Path) -> dict:
    """Load standard Netscape cookies.txt file into a cookie dictionary."""
    cookies = {}
    if not cookies_path or not cookies_path.is_file():
        return cookies

    try:
        with open(cookies_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) >= 7:
                    # parts: domain, flag, path, secure, expiration, name, value
                    cookies[parts[5]] = parts[6]
    except Exception as e:
        logger.warning(f"Error reading cookies from {cookies_path}: {e}")

    return cookies


def _extract_zoom_mp4_and_title(page_html: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract direct MP4 streaming URL and meeting title from Zoom recording web page HTML."""
    mp4_url: Optional[str] = None
    title: Optional[str] = None

    # Title extraction
    title_match = (
        re.search(r'topic["\']?\s*[:=]\s*["\']([^"\']+)["\']', page_html, re.IGNORECASE)
        or re.search(r'<title>([^<]+)</title>', page_html, re.IGNORECASE)
    )
    if title_match:
        raw_title = title_match.group(1).strip()
        raw_title = re.sub(r"\s*-\s*Zoom(?:\s*Cloud\s*Recording)?.*$", "", raw_title, flags=re.IGNORECASE)
        if raw_title:
            title = sanitize_filename(raw_title)

    # Search for streaming MP4 URL across Zoom Javascript state & DOM
    patterns = [
        r'viewMp4Url["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'mp4Url["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        r'playUrl["\']?\s*[:=]\s*["\']([^"\']+\.mp4[^"\']*)["\']',
        r'fileUrl["\']?\s*[:=]\s*["\']([^"\']+\.mp4[^"\']*)["\']',
        r'<video[^>]+src=["\']([^"\']+)["\']',
        r'<source[^>]+src=["\']([^"\']+)["\']',
        r'["\'](https?://[^"\']+\.mp4(?:\?[^"\']*)?)["\']',
    ]
    for pat in patterns:
        m = re.search(pat, page_html, re.IGNORECASE)
        if m:
            candidate = m.group(1).replace("\\u0026", "&").replace("&amp;", "&")
            candidate = html.unescape(candidate)
            if candidate.startswith("http") and ".mp4" in candidate:
                mp4_url = candidate
                break

    return mp4_url, title


async def _fallback_zoom_mp4_url(
    url: str,
    passcode: Optional[str] = None,
    cookies_path: Optional[Path] = None,
) -> Tuple[str, Optional[str], dict]:
    """
    Resilient async aiohttp Zoom web-page fallback extractor.
    Loads cookies from cookies.txt if present, submits passcode to /rec/validate_meet_passwd if needed,
    and extracts the direct MP4 streaming URL from HTML/JSON state.
    Returns: (mp4_url, extracted_title, headers)
    """
    parsed_url = urllib.parse.urlparse(url)
    base_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"

    cookie_dict = {}
    if cookies_path and cookies_path.is_file():
        cookie_dict = _load_netscape_cookies(cookies_path)

    headers = {
        "User-Agent": Config.DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": base_origin + "/",
    }

    jar = aiohttp.CookieJar(unsafe=True)
    timeout = aiohttp.ClientTimeout(total=45, connect=15, sock_read=30)

    async with aiohttp.ClientSession(cookie_jar=jar, headers=headers, timeout=timeout, cookies=cookie_dict) as session:
        async with session.get(url, allow_redirects=True) as resp:
            page_text = await resp.text(errors="ignore")

        # Check if passcode submission is required
        needs_passcode = bool(
            "validate_meet_passwd" in page_text
            or "meet_passwd" in page_text
            or "password_input" in page_text
            or (re.search(r'passcode|password', page_text, re.IGNORECASE) and "viewMp4Url" not in page_text and ".mp4" not in page_text)
        )

        if needs_passcode:
            if not passcode:
                raise ZoomPasscodeRequiredError(
                    "🔐 This Zoom recording requires a passcode (or valid cookies.txt)."
                )

            # Extract meeting ID or form fields
            meet_id_match = re.search(r'id["\']?\s*[:=]\s*["\']([a-zA-Z0-9_-]+)["\']', page_text)
            meeting_id = meet_id_match.group(1) if meet_id_match else ""

            validate_url = f"{base_origin}/rec/validate_meet_passwd"
            post_data = {
                "id": meeting_id,
                "passwd": passcode.strip(),
                "action": "view",
            }

            async with session.post(validate_url, data=post_data, allow_redirects=True) as post_resp:
                post_text = await post_resp.text(errors="ignore")
                # Also fetch original URL with updated cookies
                async with session.get(url, allow_redirects=True) as follow_resp:
                    follow_text = await follow_resp.text(errors="ignore")
                page_text = post_text + "\n" + follow_text

        mp4_url, title = _extract_zoom_mp4_and_title(page_text)
        if not mp4_url:
            if needs_passcode and passcode:
                raise ValueError(
                    "🔒 **Zoom Passcode Incorrect:** The meeting server rejected the provided passcode."
                )
            raise ValueError(
                "⚠️ **Zoom Extraction Failed:** Could not locate direct MP4 stream on recording page. "
                "If this is an institutional meeting, please upload your `cookies.txt` to the bot."
            )

        request_headers = {
            "User-Agent": Config.DEFAULT_USER_AGENT,
            "Referer": base_origin + "/",
        }
        return mp4_url, title, request_headers


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
        match_utf8 = re.search(
            r"filename\*\s*=\s*(?:UTF-8|iso-8859-1)''([^;\s]+)",
            content_disp,
            re.IGNORECASE
        )
        if match_utf8:
            filename = urllib.parse.unquote(match_utf8.group(1))

        if not filename:
            match_std = re.search(r'filename\s*=\s*(?:"([^"]+)"|([^;\s]+))', content_disp, re.IGNORECASE)
            if match_std:
                filename = match_std.group(1) or match_std.group(2)

    if not filename:
        parsed_path = urllib.parse.urlparse(url).path
        base = os.path.basename(parsed_path)
        if base:
            filename = urllib.parse.unquote(base)

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
    progress_tracker,
    extra_headers: Optional[dict] = None
) -> Path:
    """
    High-Speed Direct File Downloader.
    1. First attempts aria2c accelerator with 16 connections if available on system.
    2. Falls back to multi-connection parallel Range downloader (8 concurrent aiohttp workers with 1MB chunks).
    3. Seamlessly falls back to sequential chunked stream for non-range endpoints.
    Enforces Config.MAX_FILE_SIZE dynamically.
    """
    headers = {
        "User-Agent": Config.DEFAULT_USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }
    if extra_headers:
        headers.update(extra_headers)

    timeout = aiohttp.ClientTimeout(total=None, connect=60, sock_read=180)

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        # Check server support for Range requests and retrieve metadata
        test_headers = dict(headers)
        test_headers["Range"] = "bytes=0-0"

        async with session.get(url, headers=test_headers, allow_redirects=True) as probe_resp:
            if probe_resp.status >= 400:
                raise ValueError(f"HTTP Server returned error {probe_resp.status}: {probe_resp.reason}")

            content_length = 0
            accepts_ranges = False

            content_range = probe_resp.headers.get("Content-Range", "")
            if probe_resp.status == 206 and "/" in content_range:
                try:
                    content_length = int(content_range.rsplit("/", 1)[-1])
                    accepts_ranges = True
                except ValueError:
                    content_length = probe_resp.content_length or 0
            else:
                content_length = probe_resp.content_length or 0
                if probe_resp.headers.get("Accept-Ranges", "").lower() == "bytes":
                    accepts_ranges = True

            if content_length > Config.MAX_FILE_SIZE:
                limit_str = format_bytes(Config.MAX_FILE_SIZE)
                raise ValueError(
                    f"File size ({format_bytes(content_length)}) exceeds the maximum allowed limit of {limit_str}."
                )

            # Determine final output filename
            if custom_filename:
                final_name = sanitize_filename(custom_filename)
                if not Path(final_name).suffix:
                    inferred_name = extract_filename_from_headers(probe_resp.headers, str(probe_resp.url))
                    inferred_ext = Path(inferred_name).suffix
                    if inferred_ext:
                        final_name = f"{final_name}{inferred_ext}"
            else:
                final_name = extract_filename_from_headers(probe_resp.headers, str(probe_resp.url))

            progress_tracker.set_filename(final_name)
            output_filepath = output_dir / final_name

        # --- Ultra-Fast Accelerator 1: aria2c (16 connections) ---
        aria2c_bin = shutil.which("aria2c")
        if aria2c_bin and not extra_headers:
            logger.info(f"⚡ Launching aria2c accelerator with 16 connections for {final_name}...")
            cmd = [
                aria2c_bin,
                "-x", "16",
                "-s", "16",
                "-k", "1M",
                "--file-allocation=none",
                "--summary-interval=1",
                "--auto-file-renaming=false",
                "--allow-overwrite=true",
                "-d", str(output_dir),
                "-o", final_name,
                url,
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                async def read_aria_stdout():
                    while True:
                        line_bytes = await proc.stdout.readline()
                        if not line_bytes:
                            break
                        line_str = line_bytes.decode("utf-8", errors="ignore").strip()
                        m_progress = re.search(
                            r"(\d+(?:\.\d+)?[a-zA-Z]+)/(\d+(?:\.\d+)?[a-zA-Z]+)\s*\(\s*(\d+)%\s*\)",
                            line_str
                        )
                        m_speed = re.search(r"DL:(\d+(?:\.\d+)?[a-zA-Z]+)", line_str)
                        m_eta = re.search(r"ETA:(\w+)", line_str)

                        if m_progress:
                            cur_b = _parse_size_str(m_progress.group(1))
                            tot_b = _parse_size_str(m_progress.group(2))
                            spd_b = float(_parse_size_str(m_speed.group(1))) if m_speed else 0.0
                            eta_s = _parse_eta_str(m_eta.group(1)) if m_eta else 0.0
                            if hasattr(progress_tracker, "update"):
                                progress_tracker.update(current=cur_b, total=tot_b, speed=spd_b, eta=eta_s)
                            else:
                                await progress_tracker.update_download(current=cur_b, total=tot_b, speed=spd_b, eta=eta_s)

                await read_aria_stdout()
                await proc.wait()

                if proc.returncode == 0 and output_filepath.exists() and output_filepath.stat().st_size > 0:
                    f_size = output_filepath.stat().st_size
                    await progress_tracker.update_download(current=f_size, total=f_size)
                    return output_filepath
                else:
                    logger.warning(f"aria2c non-zero exit ({proc.returncode}). Falling back to aiohttp range downloader.")
            except Exception as aria_err:
                logger.warning(f"aria2c execution error ({aria_err}). Falling back to aiohttp range downloader.")

        # --- Ultra-Fast Accelerator 2: Multi-Connection Parallel Range Downloader (8 connections) ---
        num_connections = 8
        min_parallel_size = 4 * 1024 * 1024  # 4 MB threshold

        if accepts_ranges and content_length >= min_parallel_size:
            logger.info(
                f"Multi-connection range download enabled for {final_name} "
                f"({format_bytes(content_length)}) using {num_connections} workers."
            )
            part_size = math.ceil(content_length / num_connections)
            part_files: list[Path] = []
            downloaded_per_worker = [0] * num_connections
            is_downloading = True

            async def progress_reporter():
                while is_downloading:
                    current_total = sum(downloaded_per_worker)
                    if hasattr(progress_tracker, "update"):
                        progress_tracker.update(current=current_total, total=content_length)
                    else:
                        await progress_tracker.update_download(current=current_total, total=content_length)
                    await asyncio.sleep(Config.PROGRESS_UPDATE_INTERVAL)

            reporter_task = asyncio.create_task(progress_reporter())

            async def download_part(worker_id: int, start: int, end: int):
                part_path = output_dir / f"{final_name}.part_{worker_id}"
                part_files.append(part_path)
                part_headers = dict(headers)
                part_headers["Range"] = f"bytes={start}-{end}"

                async with aiohttp.ClientSession(headers=headers, timeout=timeout) as worker_session:
                    async with worker_session.get(url, headers=part_headers, allow_redirects=True) as resp:
                        if resp.status not in (200, 206):
                            raise ValueError(f"Worker {worker_id} range request failed: status {resp.status}")

                        async with aiofiles.open(part_path, "wb") as f_part:
                            async for chunk in resp.content.iter_chunked(1024 * 1024):  # 1MB buffer
                                await f_part.write(chunk)
                                downloaded_per_worker[worker_id] += len(chunk)

            try:
                tasks = []
                for i in range(num_connections):
                    start = i * part_size
                    end = min(start + part_size - 1, content_length - 1)
                    if start <= end:
                        tasks.append(download_part(i, start, end))

                await asyncio.gather(*tasks)

            finally:
                is_downloading = False
                reporter_task.cancel()
                try:
                    await reporter_task
                except asyncio.CancelledError:
                    pass

            # Fast chunked concatenation of parts
            async with aiofiles.open(output_filepath, "wb") as f_out:
                for i in range(num_connections):
                    part_p = output_dir / f"{final_name}.part_{i}"
                    if part_p.exists():
                        async with aiofiles.open(part_p, "rb") as f_part:
                            while True:
                                data = await f_part.read(4 * 1024 * 1024)  # 4MB chunks
                                if not data:
                                    break
                                await f_out.write(data)
                        part_p.unlink(missing_ok=True)

            await progress_tracker.update_download(current=content_length, total=content_length)
            return output_filepath

        # --- Fallback Branch: Standard Chunked Stream Downloader ---
        logger.info(f"Using standard stream downloader for {final_name} (Range not supported or small file).")
        async with session.get(url, allow_redirects=True) as response:
            if response.status >= 400:
                raise ValueError(f"HTTP Server returned error {response.status}: {response.reason}")

            downloaded_bytes = 0
            chunk_size = 1024 * 1024  # 1 MB chunk buffer

            async with aiofiles.open(output_filepath, mode="wb") as f:
                async for chunk in response.content.iter_chunked(chunk_size):
                    await f.write(chunk)
                    downloaded_bytes += len(chunk)

                    if downloaded_bytes > Config.MAX_FILE_SIZE:
                        limit_str = format_bytes(Config.MAX_FILE_SIZE)
                        raise ValueError(f"Download aborted: Stream exceeded the maximum limit of {limit_str}.")

                    if hasattr(progress_tracker, "update"):
                        progress_tracker.update(current=downloaded_bytes, total=content_length)
                    else:
                        await progress_tracker.update_download(current=downloaded_bytes, total=content_length)

            await progress_tracker.update_download(
                current=downloaded_bytes,
                total=downloaded_bytes if content_length <= 0 else content_length
            )
            return output_filepath


# Alias download_direct_file to download_direct_url for consistency
download_direct_file = download_direct_url


async def download_gdrive_file(
    url: str,
    output_dir: Path,
    custom_filename: Optional[str],
    progress_tracker
) -> Path:
    """
    High-Speed Google Drive Downloader using gdown.
    Supports clean file ID downloads and shared folders (compressed to .zip).
    Enforces Config.MAX_FILE_SIZE and reports real-time file size growth.
    """
    logger.info(f"Starting Google Drive download for URL: {url}")
    is_downloading = True

    async def monitor_gdrive_progress():
        while is_downloading:
            files = [f for f in output_dir.glob("*") if f.is_file() and not f.name.endswith(".tmp")]
            if files:
                current_size = sum(f.stat().st_size for f in files)
                if current_size > 0:
                    if hasattr(progress_tracker, "update"):
                        progress_tracker.update(current=current_size, total=0)
                    else:
                        await progress_tracker.update_download(current=current_size, total=0)
            await asyncio.sleep(Config.PROGRESS_UPDATE_INTERVAL)

    monitor_task = asyncio.create_task(monitor_gdrive_progress())

    folder_match = GDRIVE_FOLDER_PATTERN.search(url)
    try:
        if folder_match:
            folder_id = folder_match.group(1)
            folder_out = output_dir / (Path(custom_filename).stem if custom_filename else "gdrive_folder")
            folder_out.mkdir(parents=True, exist_ok=True)

            def run_folder_sync():
                return gdown.download_folder(id=folder_id, output=str(folder_out), quiet=True)

            await asyncio.to_thread(run_folder_sync)

            # Zip the downloaded folder
            zip_stem = sanitize_filename(Path(custom_filename).stem if custom_filename else "gdrive_folder")
            zip_base = output_dir / zip_stem
            zip_path_str = await asyncio.to_thread(shutil.make_archive, str(zip_base), "zip", str(folder_out))
            downloaded_file = Path(zip_path_str)
        else:
            file_match = GDRIVE_FILE_PATTERN.search(url)
            file_id = file_match.group(1) if file_match else None
            target_dest = output_dir / (custom_filename or "gdrive_download")

            def run_file_sync() -> Optional[str]:
                output_arg = str(target_dest) if custom_filename else str(output_dir)
                if file_id:
                    return gdown.download(id=file_id, output=output_arg, quiet=True)
                return gdown.download(url=url, output=output_arg, quiet=True)

            await asyncio.to_thread(run_file_sync)

            candidates = [
                f for f in output_dir.glob("*")
                if f.is_file() and not f.name.endswith(".tmp")
            ]
            if not candidates:
                raise FileNotFoundError("Google Drive download finished, but no file was created.")

            candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            downloaded_file = candidates[0]

            if custom_filename:
                safe_custom = sanitize_filename(custom_filename)
                if not Path(safe_custom).suffix and downloaded_file.suffix:
                    safe_custom = f"{safe_custom}{downloaded_file.suffix}"
                target_path = output_dir / safe_custom
                if target_path != downloaded_file:
                    downloaded_file.rename(target_path)
                    downloaded_file = target_path

    except Exception as e:
        raise ValueError(f"⚠️ **Google Drive Download Failed:** {e}") from e
    finally:
        is_downloading = False
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass

    file_size = downloaded_file.stat().st_size
    if file_size > Config.MAX_FILE_SIZE:
        limit_str = format_bytes(Config.MAX_FILE_SIZE)
        raise ValueError(f"Downloaded file ({format_bytes(file_size)}) exceeds active upload limit of {limit_str}.")

    await progress_tracker.update_download(current=file_size, total=file_size)
    progress_tracker.set_filename(downloaded_file.name)
    return downloaded_file


class _StreamDownloadState:
    """Thread-safe state object for tracking yt-dlp progress."""
    def __init__(self):
        self.downloaded_bytes: int = 0
        self.total_bytes: int = 0
        self.speed: float = 0.0
        self.eta: float = 0.0
        self.fragment_index: int = 0
        self.fragment_count: int = 0
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
    High-Speed Unified yt-dlp downloader for Zoom recordings and HLS/DASH streams.
    Downloads 32 fragments concurrently with native HLS segment downloader and 10MB chunk buffers.
    Features real-time progress callbacks on every fragment/byte update.
    Enforces Config.MAX_FILE_SIZE.
    """
    state = _StreamDownloadState()

    def ydl_progress_hook(d: dict) -> None:
        """Callback invoked by yt-dlp in the worker thread."""
        status = d.get("status")
        if status == "downloading":
            state.downloaded_bytes = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate", 0)

            frag_idx = d.get("fragment_index")
            frag_count = d.get("fragment_count")
            if frag_idx and frag_count and frag_count > 0:
                state.fragment_index = frag_idx
                state.fragment_count = frag_count
                if not total or total <= 0:
                    frag_ratio = frag_idx / frag_count
                    total = int(state.downloaded_bytes / frag_ratio) if frag_ratio > 0 else 0

            state.total_bytes = total
            state.speed = float(d.get("speed") or 0.0)
            state.eta = float(d.get("eta") or 0.0)

            # Thread-safe direct progress update on every fragment/byte update
            frag_info = (state.fragment_index, state.fragment_count) if state.fragment_count > 0 else None
            if hasattr(progress_tracker, "update"):
                progress_tracker.update(
                    current=state.downloaded_bytes,
                    total=state.total_bytes,
                    speed=state.speed,
                    eta=state.eta,
                    fragment_info=frag_info,
                )
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
        "concurrent_fragment_downloads": 32,
        "buffersize": 1024 * 1024,
        "retries": 10,
        "fragment_retries": 10,
        "http_chunk_size": 10485760,  # 10 MB chunk size
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

    if passcode:
        ydl_opts["videopassword"] = passcode.strip()

    if Config.COOKIES_FILE.is_file():
        ydl_opts["cookiefile"] = str(Config.COOKIES_FILE)
        logger.info(f"Using cookies file: {Config.COOKIES_FILE}")

    # Async monitor task to periodically update Telegram progress
    async def monitor_progress():
        while not state.is_done and state.error is None:
            if state.downloaded_bytes > 0 or state.fragment_index > 0:
                frag_info = (state.fragment_index, state.fragment_count) if state.fragment_count > 0 else None
                if hasattr(progress_tracker, "update"):
                    progress_tracker.update(
                        current=state.downloaded_bytes,
                        total=state.total_bytes,
                        speed=state.speed,
                        eta=state.eta,
                        fragment_info=frag_info,
                    )
                else:
                    await progress_tracker.update_download(
                        current=state.downloaded_bytes,
                        total=state.total_bytes,
                        speed=state.speed,
                        eta=state.eta,
                        fragment_info=frag_info,
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

        # Check for Zoom-specific failures to invoke resilient web fallback
        if is_zoom_url(url):
            is_passcode_issue = (
                "passcode" in err_msg or "password" in err_msg or "wrong passcode" in err_msg
            )
            is_extract_issue = "unable to extract" in err_msg or "extractor" in err_msg or "403" in err_msg

            if (is_passcode_issue or is_extract_issue) and not passcode:
                raise ZoomPasscodeRequiredError(
                    f"Zoom recording requires a passcode or session verification."
                ) from e

            logger.warning(f"yt-dlp failed on Zoom link ({e}). Attempting resilient aiohttp web fallback...")
            try:
                mp4_url, zoom_title, fallback_hdrs = await _fallback_zoom_mp4_url(
                    url=url,
                    passcode=passcode,
                    cookies_path=Config.COOKIES_FILE if Config.COOKIES_FILE.is_file() else None,
                )
                final_name = custom_filename or (f"{zoom_title}.mp4" if zoom_title else None)
                return await download_direct_url(
                    url=mp4_url,
                    output_dir=output_dir,
                    custom_filename=final_name,
                    progress_tracker=progress_tracker,
                    extra_headers=fallback_hdrs,
                )
            except ZoomPasscodeRequiredError:
                raise
            except Exception as fb_err:
                raise ValueError(
                    f"⚠️ **Zoom Download Failed:** Both yt-dlp and fallback web extractor failed ({fb_err})"
                ) from fb_err

        # General error formatting
        if "larger than max-filesize" in err_msg:
            limit_str = format_bytes(Config.MAX_FILE_SIZE)
            raise ValueError(f"⚠️ **File Size Limit Exceeded:** The recording exceeds the maximum limit of {limit_str}.") from e
        elif "403" in err_msg or "forbidden" in err_msg:
            raise ValueError(
                "🚫 **Access Denied (403 Forbidden):** The server restricted access to this content.\n"
                "💡 Tip: Send your `cookies.txt` file directly to this bot in chat to authenticate."
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
        if not Path(safe_custom).suffix and primary_file.suffix:
            safe_custom = f"{safe_custom}{primary_file.suffix}"
        target_path = output_dir / safe_custom
        if target_path != primary_file:
            primary_file.rename(target_path)
            primary_file = target_path
    elif is_stream_url(url):
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
