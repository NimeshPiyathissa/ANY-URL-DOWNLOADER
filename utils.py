import asyncio
import json
import logging
import math
import os
import re
import shutil
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# List of common video file extensions
VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm",
    ".flv", ".wmv", ".m4v", ".ts", ".3gp"
}


def format_bytes(size_bytes: int | float) -> str:
    """Format bytes into a human-readable string (e.g. 12.34 MB, 1.50 GB)."""
    if size_bytes <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = min(int(math.log(size_bytes, 1024)), len(units) - 1)
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s:.2f} {units[i]}"


def format_time(seconds: int | float) -> str:
    """Format seconds into HH:MM:SS or MM:SS."""
    if seconds <= 0 or math.isnan(seconds) or math.isinf(seconds):
        return "00:00"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def generate_progress_bar(percentage: float, length: int = 10) -> str:
    """Generate a visual text-based progress bar."""
    percentage = max(0.0, min(100.0, percentage))
    filled_length = int(round(length * (percentage / 100.0)))
    filled_length = max(0, min(length, filled_length))
    return "■" * filled_length + "□" * (length - filled_length)


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Sanitize a filename by removing or replacing invalid filesystem characters."""
    if not name:
        return "downloaded_file.bin"

    # Replace forbidden filesystem characters with underscore
    clean = re.sub(r'[\\/*?:"<>|]', "_", name)
    # Strip leading/trailing whitespaces and periods
    clean = clean.strip(" .")

    if not clean:
        return "downloaded_file.bin"

    # Retain extension while truncating long stem
    p = Path(clean)
    stem, ext = p.stem, p.suffix
    if len(clean) > max_length:
        max_stem_len = max_length - len(ext)
        clean = f"{stem[:max_stem_len]}{ext}"

    return clean


def is_video_file(file_path: str | Path) -> bool:
    """Check if the given file path has a video extension."""
    return Path(file_path).suffix.lower() in VIDEO_EXTENSIONS


async def get_video_metadata(video_path: str | Path) -> Tuple[int, int, int]:
    """
    Extract video duration (seconds), width, and height using ffprobe asynchronously.
    Correctly handles video rotation metadata (e.g. mobile 90° or 270° recordings).
    Returns: (duration, width, height)
    """
    video_path = str(video_path)
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "stream=width,height,duration,codec_type,side_data_list:stream_tags=rotate",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning(f"ffprobe returned non-zero code {proc.returncode}: {stderr.decode(errors='ignore')}")
            return 0, 0, 0

        data = json.loads(stdout.decode(errors="ignore"))

        duration = 0.0
        width = 0
        height = 0
        rotation = 0

        # Try getting duration from format container first
        if "format" in data and "duration" in data["format"]:
            try:
                duration = float(data["format"]["duration"])
            except (ValueError, TypeError):
                duration = 0.0

        # Iterate streams to find primary video stream
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                width = int(stream.get("width") or 0)
                height = int(stream.get("height") or 0)

                # Fallback duration from stream if format container did not have it
                if duration <= 0 and stream.get("duration"):
                    try:
                        duration = float(stream["duration"])
                    except (ValueError, TypeError):
                        pass

                # Check rotation in tags
                tags = stream.get("tags") or {}
                if "rotate" in tags:
                    try:
                        rotation = int(tags["rotate"])
                    except (ValueError, TypeError):
                        pass

                # Check rotation in side_data_list
                for side_data in stream.get("side_data_list", []):
                    if "rotation" in side_data:
                        try:
                            rotation = int(side_data["rotation"])
                        except (ValueError, TypeError):
                            pass
                break

        # Swap width and height if rotated 90 or 270 degrees
        if abs(rotation) in (90, 270):
            width, height = height, width

        return int(duration), width, height

    except Exception as e:
        logger.error(f"Error extracting metadata from {video_path}: {e}")
        return 0, 0, 0


async def generate_thumbnail(
    video_path: str | Path,
    thumb_path: str | Path,
    duration: int = 0
) -> Optional[str]:
    """
    Generate a thumbnail frame from the video using ffmpeg asynchronously.
    Scales thumbnail to max width 320 maintaining aspect ratio for optimal Telegram rendering.
    Returns the path to the thumbnail file if successful, else None.
    """
    video_path = str(video_path)
    thumb_path = str(thumb_path)

    # Pick a seek point: at 10% of duration, capped between 1s and 10s
    seek_time = max(1.0, min(duration * 0.1, 10.0)) if duration > 0 else 1.0

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(seek_time),
        "-i", video_path,
        "-vframes", "1",
        "-vf", "scale='min(320,iw)':-1",
        "-q:v", "2",
        thumb_path
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode == 0 and os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
            return thumb_path
        else:
            logger.warning(f"ffmpeg thumbnail generation failed: {stderr.decode(errors='ignore')}")
            return None

    except Exception as e:
        logger.error(f"Exception generating thumbnail for {video_path}: {e}")
        return None


def clean_directory(dir_path: str | Path) -> None:
    """Safely delete a directory and all its contents."""
    try:
        path = Path(dir_path)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
            logger.info(f"Cleaned up workspace directory: {path}")
    except Exception as e:
        logger.error(f"Error cleaning directory {dir_path}: {e}")
