import os
from pathlib import Path
from typing import Optional, Set
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Application configuration and environment variable loader."""

    # Telegram API Credentials
    API_ID: int = int(os.getenv("API_ID", "0"))
    API_HASH: str = os.getenv("API_HASH", "").strip()
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()

    # Telegram Premium User Session String for 4GB Hybrid Uploads
    USER_SESSION_STRING: Optional[str] = (
        os.getenv("USER_SESSION_STRING", "").strip() or None
    )

    # Dump Channel / Relay Chat ID for staging 2GB-4GB uploads
    _dump_chat_raw = os.getenv("DUMP_CHAT_ID", "").strip()
    if _dump_chat_raw:
        try:
            DUMP_CHAT_ID: Optional[int | str] = int(_dump_chat_raw)
        except ValueError:
            DUMP_CHAT_ID = _dump_chat_raw
    else:
        DUMP_CHAT_ID = None

    # Parse comma-separated authorized user IDs
    _auth_users_raw = os.getenv("AUTHORIZED_USERS", "").strip()
    AUTHORIZED_USERS: Set[int] = {
        int(uid.strip())
        for uid in _auth_users_raw.split(",")
        if uid.strip().lstrip("-").isdigit()
    }

    # Concurrency and throttling settings
    MAX_CONCURRENT_DOWNLOADS: int = int(os.getenv("MAX_CONCURRENT_DOWNLOADS", "3"))
    PROGRESS_UPDATE_INTERVAL: float = float(os.getenv("PROGRESS_UPDATE_INTERVAL", "3.5"))
    DOWNLOAD_DIR: Path = Path(os.getenv("DOWNLOAD_DIR", "downloads"))

    # Upload size limits
    BOT_MAX_SIZE: int = 2 * 1024 * 1024 * 1024  # 2 GiB (Telegram Bot API limit)
    PREMIUM_MAX_SIZE: int = 4 * 1024 * 1024 * 1024  # 4 GiB (Telegram Premium limit)

    # Dynamic maximum file size based on presence of Premium user session
    MAX_FILE_SIZE: int = PREMIUM_MAX_SIZE if USER_SESSION_STRING else BOT_MAX_SIZE

    # Absolute cookies file path for yt-dlp authenticated sessions & systemd compatibility
    COOKIES_FILE: Path = Path(__file__).resolve().parent / "cookies.txt"

    # Standard browser User-Agent to prevent 403 Forbidden blocks
    DEFAULT_USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    @classmethod
    def is_premium_enabled(cls) -> bool:
        """Returns True if a 4GB Premium user session string is configured."""
        return bool(cls.USER_SESSION_STRING)

    @classmethod
    def validate(cls) -> None:
        """Validate required configuration settings."""
        missing = []
        if not cls.API_ID:
            missing.append("API_ID")
        if not cls.API_HASH:
            missing.append("API_HASH")
        if not cls.BOT_TOKEN:
            missing.append("BOT_TOKEN")

        if missing:
            raise ValueError(
                f"Missing required environment variables in .env: {', '.join(missing)}\n"
                "Please configure them in your .env file."
            )

        # Ensure download workspace directory exists
        cls.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
