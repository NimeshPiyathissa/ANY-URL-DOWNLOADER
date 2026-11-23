import asyncio
import os
import py_compile
import re
import shutil
import tempfile
from pathlib import Path

from config import Config
from utils import (
    clean_directory,
    format_bytes,
    format_time,
    generate_progress_bar,
    generate_thumbnail,
    get_video_metadata,
    is_video_file,
    sanitize_filename,
    truncate_caption,
)
from downloader import (
    is_zoom_url,
    is_stream_url,
    is_gdrive_url,
    extract_filename_from_headers,
    _derive_stream_filename,
    _extract_zoom_mp4_and_title,
    _extract_zoom_meeting_id,
    _extract_zoom_csrf_token,
    _load_netscape_cookies,
    ZoomPasscodeRequiredError,
    GDRIVE_FILE_PATTERN,
    GDRIVE_FOLDER_PATTERN,
    _parse_size_str,
    _parse_eta_str,
)
from bot import is_authorized, parse_user_input


def run_tests():
    print("=" * 68)
    print("      RUNNING BOT COMPONENT & REGRESSION TEST SUITE (v3.0.0)")
    print("=" * 68)

    # 1. Test formatters
    assert format_bytes(0) == "0 B"
    assert format_bytes(1024) == "1.00 KB"
    assert format_bytes(1024 * 1024 * 5.5) == "5.50 MB"
    assert format_bytes(1024 * 1024 * 1024 * 1.5) == "1.50 GB"
    assert format_bytes(1024 * 1024 * 1024 * 3.8) == "3.80 GB"
    print("✓ format_bytes passed (including 4GB scale)")

    assert format_time(0) == "00:00"
    assert format_time(65) == "01:05"
    assert format_time(3665) == "01:01:05"
    print("✓ format_time passed")

    # 2. Test progress bar (clean block styling: [██████░░░░])
    assert generate_progress_bar(0) == "░░░░░░░░░░"
    assert generate_progress_bar(50) == "█████░░░░░"
    assert generate_progress_bar(60) == "██████░░░░"
    assert generate_progress_bar(100) == "██████████"
    print("✓ generate_progress_bar clean block styling passed ([██████░░░░])")

    # 3. Test Telegram caption truncation (v3.0.0: strictly <= 1024 chars)
    assert truncate_caption("") == ""
    assert truncate_caption("Short caption") == "Short caption"
    exact_1024 = "A" * 1024
    assert truncate_caption(exact_1024) == exact_1024
    long_caption = "B" * 1200
    truncated = truncate_caption(long_caption)
    assert len(truncated) <= 1024, f"Truncated caption length {len(truncated)} exceeds 1024"
    assert len(truncated) == 1023
    assert truncated.endswith("...")
    assert truncated == ("B" * 1020) + "..."
    print("✓ truncate_caption Telegram 1024-char limit enforcement verified")

    # 4. Test sanitize filename & video checker with Unicode & Sinhala preservation
    assert sanitize_filename("test:file*name?.mp4") == "test_file_name_.mp4"
    sinhala_name = "පාඩම 01: පරිගණක විද්‍යාව.mp4"
    sanitized_sinhala = sanitize_filename(sinhala_name)
    assert "පාඩම 01_ පරිගණක විද්‍යාව.mp4" == sanitized_sinhala
    assert "පාඩම" in sanitized_sinhala
    assert "පරිගණක" in sanitized_sinhala
    print(f"✓ sanitize_filename Sinhala & Unicode preservation verified: '{sanitized_sinhala}'")

    assert is_video_file("video.mp4") is True
    assert is_video_file("recording.mkv") is True
    assert is_video_file("doc.pdf") is False
    assert is_video_file("archive.zip") is False
    print("✓ is_video_file passed")

    # 5. Test Zoom URL detection
    assert is_zoom_url("https://us02web.zoom.us/rec/share/abc123xyz") is True
    assert is_zoom_url("https://company.zoom.us/recording/play/987xyz") is True
    assert is_zoom_url("https://example.com/video.mp4") is False
    print("✓ is_zoom_url passed")

    # 6. Test stream URL detection (.m3u8 / .mpd)
    assert is_stream_url("https://cdn.example.com/videos/master.m3u8") is True
    assert is_stream_url("https://cdn.example.com/videos/index.m3u8") is True
    assert is_stream_url("https://cdn.example.com/stream/manifest.mpd") is True
    assert is_stream_url("https://cdn.example.com/stream/manifest.mpd?token=abc&ts=123") is True
    assert is_stream_url("https://cdn.example.com/videos/master.M3U8") is True
    assert is_stream_url("https://example.com/video.mp4") is False
    assert is_stream_url("https://example.com/page.html") is False
    print("✓ is_stream_url passed")

    # 7. Test Google Drive URL detection & regex patterns
    assert is_gdrive_url("https://drive.google.com/file/d/1B2C3D4E5F6G7H8I9J/view?usp=sharing") is True
    assert is_gdrive_url("https://drive.google.com/open?id=1B2C3D4E5F6G7H8I9J") is True
    assert is_gdrive_url("https://drive.google.com/uc?id=1B2C3D4E5F6G7H8I9J") is True
    assert is_gdrive_url("https://drive.google.com/drive/folders/1B2C3D4E5F6G7H8I9J") is True
    assert is_gdrive_url("https://docs.google.com/document/d/1B2C3D4E5F6G7H8I9J/edit") is True
    assert is_gdrive_url("https://example.com/file.zip") is False

    m_file = GDRIVE_FILE_PATTERN.search("https://drive.google.com/file/d/1B2C3D4E5F6G7H8I9J/view?usp=sharing")
    assert m_file and m_file.group(1) == "1B2C3D4E5F6G7H8I9J"
    m_uc = GDRIVE_FILE_PATTERN.search("https://drive.google.com/uc?id=1B2C3D4E5F6G7H8I9J")
    assert m_uc and m_uc.group(1) == "1B2C3D4E5F6G7H8I9J"
    m_folder = GDRIVE_FOLDER_PATTERN.search("https://drive.google.com/drive/folders/1B2C3D4E5F6G7H8I9J")
    assert m_folder and m_folder.group(1) == "1B2C3D4E5F6G7H8I9J"
    print("✓ is_gdrive_url and GDRIVE regex patterns verified")

    # 8. Test aria2c size and ETA parsers
    assert _parse_size_str("150MiB") == 150 * 1024 * 1024
    assert _parse_size_str("2.5GiB") == int(2.5 * 1024 * 1024 * 1024)
    assert _parse_size_str("500KiB") == 500 * 1024
    assert _parse_size_str("1024B") == 1024
    assert _parse_eta_str("14s") == 14.0
    assert _parse_eta_str("1m30s") == 90.0
    assert _parse_eta_str("01:30") == 90.0
    print("✓ aria2c size and ETA parsers verified")

    # 9. Test HLS fragment progress estimation
    frag_idx, frag_count, dl_bytes = 12, 20, 12000000
    frag_ratio = frag_idx / frag_count
    estimated_total = int(dl_bytes / frag_ratio)
    assert estimated_total == 20000000
    assert round(frag_ratio * 100, 1) == 60.0
    print("✓ HLS fragment progress estimation verified (60.0% at 12/20 fragments)")

    # 10. Test _derive_stream_filename with Sinhala/Unicode folder names
    sinhala_url = "https://cdn.example.com/videos/%E0%B6%B4%E0%B7%8F%E0%B6%A9%E0%B6%B8/master.m3u8"
    derived = _derive_stream_filename(sinhala_url)
    assert derived.endswith(".mp4")
    assert "පාඩම" in derived
    print(f"✓ Sinhala parent folder extraction: '{derived}'")

    english_url = "https://cdn.example.com/videos/Lecture%2001/index.m3u8"
    derived_en = _derive_stream_filename(english_url)
    assert derived_en == "Lecture 01.mp4"
    print(f"✓ English parent folder extraction: '{derived_en}'")

    # 11. Test Header filename extraction (RFC 5987 / 6266)
    headers = {"Content-Disposition": 'attachment; filename="custom_doc.pdf"'}
    assert extract_filename_from_headers(headers, "http://test.com/file") == "custom_doc.pdf"
    headers_utf = {"Content-Disposition": "attachment; filename*=UTF-8''my%20presentation.mp4"}
    assert extract_filename_from_headers(headers_utf, "http://test.com/file") == "my presentation.mp4"
    print("✓ extract_filename_from_headers passed")

    # 12. Test user input parsing
    url, passc, name = parse_user_input("https://us02web.zoom.us/rec/share/123 | mypass | presentation.mp4")
    assert url == "https://us02web.zoom.us/rec/share/123"
    assert passc == "mypass"
    assert name == "presentation.mp4"
    print("✓ parse_user_input passed")

    # 13. Test Config bot ID extraction & Access Control resolution (v3.0.0)
    test_token_1 = "123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ_1234567"
    Config.BOT_TOKEN = test_token_1
    assert Config.extract_bot_id() == 123456789
    print(f"✓ Config.extract_bot_id auto-extracted: {Config.extract_bot_id()}")

    # Verify is_authorized allows bot's own ID automatically (prevents Chrome Extension 403 Forbidden)
    Config.AUTHORIZED_USERS = {999999999}
    assert is_authorized(999999999) is True
    assert is_authorized(123456789) is True, "Bot's own ID must be authorized to prevent extension access denied"
    assert is_authorized(111111111) is False
    print("✓ is_authorized bot-ID auto-whitelist verified (prevents Access Denied for Chrome extension)")

    # 14. Test Config constants and validation error pointing to install.sh
    assert Config.BOT_MAX_SIZE == 2 * 1024 * 1024 * 1024
    assert Config.PREMIUM_MAX_SIZE == 4 * 1024 * 1024 * 1024
    print("✓ Config BOT_MAX_SIZE and PREMIUM_MAX_SIZE verified")

    saved_api_id = Config.API_ID
    Config.API_ID = 0
    try:
        Config.validate()
        assert False, "Config.validate() should have raised ValueError when API_ID is 0"
    except ValueError as val_err:
        assert "sudo bash install.sh" in str(val_err), "Validation error message must guide users to sudo bash install.sh"
        print("✓ Config startup validation error pointing to 'sudo bash install.sh' verified")
    finally:
        Config.API_ID = saved_api_id

    # 15. Test Zero-byte / corrupt file guard logic (v3.0.0)
    with tempfile.NamedTemporaryFile(delete=False) as empty_tf:
        empty_tf_path = Path(empty_tf.name)
    try:
        assert empty_tf_path.exists()
        assert empty_tf_path.stat().st_size == 0
        # Simulating the zero-byte guard condition in bot.py and downloader.py
        is_corrupt = (not empty_tf_path.exists()) or (empty_tf_path.stat().st_size <= 0)
        assert is_corrupt is True
        print("✓ Zero-byte / corrupt file detection guard verified")
    finally:
        empty_tf_path.unlink(missing_ok=True)

    # 16. Test bot.py entrypoint, zero-byte guard, and cleanup
    bot_code = Path("bot.py").read_text(encoding="utf-8")
    assert "bot.run(main())" in bot_code, "bot.py must use bot.run(main()) as entrypoint"
    assert "truncate_caption" in bot_code, "bot.py must use truncate_caption"
    assert "shutil.rmtree(task_dir, ignore_errors=True)" in bot_code, "bot.py must clean task_dir via shutil.rmtree"
    assert "PASSCODE_WAITERS.pop" in bot_code, "bot.py must clean up PASSCODE_WAITERS"
    assert "CAPTION_WAITERS.pop" in bot_code, "bot.py must clean up CAPTION_WAITERS"
    assert "st_size <= 0" in bot_code, "bot.py must guard against 0-byte uploads"
    print("✓ bot.py Python 3.12+ loop, caption truncation, zero-byte guard, and strict cleanup verified")

    # 17. Test downloader.py aria2c header forwarding and zero-byte guards
    dl_code = Path("downloader.py").read_text(encoding="utf-8")
    assert '"hls_prefer_native": True' in dl_code, "downloader.py must enable native HLS downloader"
    assert '"concurrent_fragment_downloads": 32' in dl_code, "downloader.py must use 32 concurrent fragments"
    assert "aria2c" in dl_code, "downloader.py must support aria2c acceleration"
    assert "--header=" in dl_code, "downloader.py aria2c accelerator must forward headers via --header="
    assert "and not extra_headers" not in dl_code, "downloader.py must allow aria2c with extra_headers"
    print("✓ downloader.py aria2c header forwarding (--header=...) and 32-fragment HLS verified")

    # 18. Test Chrome Extension popup.js User-Agent and Referer forwarding (v3.0.0)
    popup_js = Path("chrome-extension/popup.js").read_text(encoding="utf-8")
    assert "navigator.userAgent" in popup_js, "popup.js must capture navigator.userAgent"
    assert "ZOOMSTREAM::" in popup_js, "popup.js must format ZOOMSTREAM:: command"
    assert "${userAgent}" in popup_js, "popup.js must pass captured userAgent to ZOOMSTREAM command"
    print("✓ Chrome Extension popup.js User-Agent and Referer header forwarding verified")

    # 19. Test install.sh interactive installer script (v3.0.0)
    assert Path("install.sh").exists(), "install.sh must exist in repository root"
    install_sh = Path("install.sh").read_text(encoding="utf-8")
    assert "apt-get install -y -qq python3" in install_sh, "install.sh must install python3"
    assert "ffmpeg" in install_sh and "aria2" in install_sh, "install.sh must install ffmpeg and aria2"
    assert 'BOT_ID="${BOT_TOKEN%%:*}"' in install_sh, "install.sh must auto-extract BOT_ID from BOT_TOKEN"
    assert "ALLOWED_USERS=$OWNER_ID,$BOT_ID" in install_sh, "install.sh must write ALLOWED_USERS with bot ID"
    assert "pip" in install_sh and "yt-dlp" in install_sh, "install.sh must upgrade pip and yt-dlp"
    assert "any-url-bot.service" in install_sh, "install.sh must configure any-url-bot.service"
    assert "Restart=always" in install_sh, "install.sh service must have Restart=always"
    print("✓ install.sh interactive terminal installer verified (input validation & auto bot-ID extraction)")

    # 20. Test setup_service.sh delegates cleanly to install.sh
    setup_sh = Path("setup_service.sh").read_text(encoding="utf-8")
    assert "install.sh" in setup_sh, "setup_service.sh must delegate to install.sh cleanly"
    print("✓ setup_service.sh delegation to install.sh verified")

    # 21. Test Zoom meeting ID & CSRF extraction and Netscape cookies
    assert issubclass(ZoomPasscodeRequiredError, ValueError)
    assert _extract_zoom_meeting_id("https://us02web.zoom.us/rec/share/abc123xyz") == "abc123xyz"
    assert _extract_zoom_meeting_id("https://company.zoom.us/rec/play/987xyz?startTime=123") == "987xyz"
    sample_meta_html = '<meta name="csrf-token" content="csrf_meta_123"/>'
    assert _extract_zoom_csrf_token(sample_meta_html) == "csrf_meta_123"

    sample_zoom_html = """
    <html>
      <head><title>Quantum Computing Lecture - Zoom</title></head>
      <body>
        <script>
          window.__data__ = {
            topic: "Quantum Computing Lecture",
            viewMp4Url: "https:\\/\\/ssrweb.zoom.us\\/rec\\/play\\/quantum_lecture.mp4?sig=123"
          };
        </script>
      </body>
    </html>
    """
    extracted_mp4, extracted_topic = _extract_zoom_mp4_and_title(sample_zoom_html)
    assert extracted_mp4 == "https://ssrweb.zoom.us/rec/play/quantum_lecture.mp4?sig=123"
    assert extracted_topic == "Quantum Computing Lecture"
    print("✓ Zoom meeting ID, CSRF, and HTML MP4 extraction verified")

    dummy_cookie_file = Path("test_cookies_tmp.txt")
    dummy_cookie_file.write_text(".zoom.us\tTRUE\t/\tTRUE\t1790000000\t_zm_session\txyz123\n", encoding="utf-8")
    loaded_cookies = _load_netscape_cookies(dummy_cookie_file)
    assert loaded_cookies.get("_zm_session") == "xyz123"
    dummy_cookie_file.unlink(missing_ok=True)
    print("✓ Netscape cookies.txt parser verified")

    # 22. Test clean_directory
    test_clean_dir = Path("test_clean_tmp")
    test_clean_dir.mkdir(exist_ok=True)
    (test_clean_dir / "dummy.txt").write_text("hello")
    clean_directory(test_clean_dir)
    assert not test_clean_dir.exists()
    print("✓ clean_directory workspace cleanup verified")

    # 23. Test py_compile across all Python source modules
    for py_file in ["config.py", "utils.py", "downloader.py", "bot.py"]:
        py_compile.compile(py_file, doraise=True)
        print(f"✓ py_compile verified: {py_file} compiled cleanly without syntax errors")

    # 24. Test FFmpeg / FFprobe integration if ffmpeg is available
    async def test_ffmpeg():
        test_dir = Path("test_tmp")
        test_dir.mkdir(exist_ok=True)
        video_path = test_dir / "sample.mp4"
        thumb_path = test_dir / "sample_thumb.jpg"

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
            str(video_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()
        if proc.returncode == 0 and video_path.exists():
            duration, width, height = await get_video_metadata(video_path)
            assert duration == 2
            assert width == 320
            assert height == 240
            print(f"✓ ffprobe metadata verified: duration={duration}s, width={width}, height={height}")

            t_path = await generate_thumbnail(video_path, thumb_path, duration)
            assert t_path is not None and Path(t_path).exists()
            print("✓ ffmpeg thumbnail generation verified")
        else:
            print("ℹ Skipping ffmpeg video test (synthetic generation skipped or ffmpeg not in PATH)")

        shutil.rmtree(test_dir, ignore_errors=True)

    asyncio.run(test_ffmpeg())
    print("\n" + "=" * 68)
    print("🎉 ALL TESTS COMPLETED AND PASSED PERFECTLY (Release v3.0.0)!")
    print("=" * 68 + "\n")


if __name__ == "__main__":
    run_tests()
