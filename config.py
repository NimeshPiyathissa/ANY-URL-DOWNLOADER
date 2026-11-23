import os
from pathlib import Path
from typing import Optional, Set
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Application configuration and environment variable loader for Release v3.0.0."""

    # Telegram API Credentials
    API_ID: int = int(os.getenv("API_ID", "0")) if os.getenv("API_ID", "0").isdigit() else 0
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

    # Parse comma-separated authorized user IDs (support both ALLOWED_USERS and AUTHORIZED_USERS)
    _auth_users_raw = os.getenv("ALLOWED_USERS", os.getenv("AUTHORIZED_USERS", "")).strip()
    AUTHORIZED_USERS: Set[int] = {
        int(uid.strip())
        for uid in _auth_users_raw.split(",")
        if uid.strip().lstrip("-").isdigit()
    }
    ALLOWED_USERS = AUTHORIZED_USERS  # Direct alias for compatibility

    # Automatically extract bot ID from BOT_TOKEN and ensure it is included in AUTHORIZED_USERS
    _bot_id_str = BOT_TOKEN.split(":")[0] if ":" in BOT_TOKEN else ""
    if _bot_id_str.isdigit() and AUTHORIZED_USERS:
        AUTHORIZED_USERS.add(int(_bot_id_str))

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
    def extract_bot_id(cls) -> Optional[int]:
        """Extract numeric Telegram Bot ID from BOT_TOKEN."""
        if cls.BOT_TOKEN and ":" in cls.BOT_TOKEN:
            prefix = cls.BOT_TOKEN.split(":")[0].strip()
            if prefix.isdigit():
                return int(prefix)
        return None

    @classmethod
    def is_premium_enabled(cls) -> bool:
        """Returns True if a 4GB Premium user session string is configured."""
        return bool(cls.USER_SESSION_STRING)

    @classmethod
    def validate(cls) -> None:
        """
        Validate required configuration settings at startup.
        Provides clear, human-readable error messages pointing users to 'sudo bash install.sh'.
        """
        env_file = Path(__file__).resolve().parent / ".env"
        errors = []

        if not cls.API_ID or cls.API_ID <= 0:
            errors.append("• API_ID is missing or not a positive integer (obtain from https://my.telegram.org)")
        if not cls.API_HASH or len(cls.API_HASH) < 16:
            errors.append("• API_HASH is missing or too short (obtain from https://my.telegram.org)")
        if not cls.BOT_TOKEN or ":" not in cls.BOT_TOKEN:
            errors.append("• BOT_TOKEN is missing or not in format <bot_id>:<secret> (obtain from @BotFather)")

        if errors:
            env_status = f"Found at {env_file}" if env_file.exists() else "NOT FOUND (.env is missing!)"
            error_banner = (
                f"\n{'=' * 72}\n"
                f"❌ CONFIGURATION VALIDATION FAILED (Release v3.0.0)\n"
                f"   Environment file status: {env_status}\n"
                f"{'=' * 72}\n"
                + "\n".join(errors) + "\n\n"
                f"👉 To configure credentials interactively in 1 step, run:\n"
                f"   sudo bash install.sh\n"
                f"{'=' * 72}\n"
            )
            raise ValueError(error_banner)

        # Ensure download workspace directory exists
        cls.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
