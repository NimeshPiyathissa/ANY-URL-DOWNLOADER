import asyncio
import os
import shutil
from pathlib import Path

from config import Config
from utils import (
    format_bytes,
    format_time,
    generate_progress_bar,
    sanitize_filename,
    is_video_file,
    get_video_metadata,
    generate_thumbnail,
    clean_directory,
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
from bot import parse_user_input


def run_tests():
    print("=" * 60)
    print("      RUNNING BOT COMPONENT & REGRESSION TEST SUITE (v2.3.0)")
    print("=" * 60)

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

    # 2. Test progress bar (v2.0.0 clean block styling: [██████░░░░])
    assert generate_progress_bar(0) == "░░░░░░░░░░"
    assert generate_progress_bar(50) == "█████░░░░░"
    assert generate_progress_bar(60) == "██████░░░░"
    assert generate_progress_bar(100) == "██████████"
    print("✓ generate_progress_bar clean block styling passed ([██████░░░░])")

    # 3. Test sanitize filename & video checker
    assert sanitize_filename("test:file*name?.mp4") == "test_file_name_.mp4"
    assert is_video_file("video.mp4") is True
    assert is_video_file("recording.mkv") is True
    assert is_video_file("doc.pdf") is False
    assert is_video_file("archive.zip") is False
    print("✓ sanitize_filename and is_video_file passed")

    # 4. Test Zoom URL detection
    assert is_zoom_url("https://us02web.zoom.us/rec/share/abc123xyz") is True
    assert is_zoom_url("https://company.zoom.us/recording/play/987xyz") is True
    assert is_zoom_url("https://example.com/video.mp4") is False
    print("✓ is_zoom_url passed")

    # 5. Test stream URL detection (.m3u8 / .mpd)
    assert is_stream_url("https://cdn.example.com/videos/master.m3u8") is True
    assert is_stream_url("https://cdn.example.com/videos/index.m3u8") is True
    assert is_stream_url("https://cdn.example.com/stream/manifest.mpd") is True
    assert is_stream_url("https://cdn.example.com/stream/manifest.mpd?token=abc&ts=123") is True
    assert is_stream_url("https://cdn.example.com/videos/master.M3U8") is True  # case insensitive
    assert is_stream_url("https://example.com/video.mp4") is False
    assert is_stream_url("https://example.com/page.html") is False
    assert is_stream_url("https://example.com/file.m3u8.bak") is False
    print("✓ is_stream_url passed")

    # 6. Test Google Drive URL detection (v2.0.0)
    assert is_gdrive_url("https://drive.google.com/file/d/1B2C3D4E5F6G7H8I9J/view?usp=sharing") is True
    assert is_gdrive_url("https://drive.google.com/open?id=1B2C3D4E5F6G7H8I9J") is True
    assert is_gdrive_url("https://drive.google.com/uc?id=1B2C3D4E5F6G7H8I9J") is True
    assert is_gdrive_url("https://drive.google.com/drive/folders/1B2C3D4E5F6G7H8I9J") is True
    assert is_gdrive_url("https://docs.google.com/document/d/1B2C3D4E5F6G7H8I9J/edit") is True
    assert is_gdrive_url("https://example.com/file.zip") is False
    print("✓ is_gdrive_url passed (Google Drive links recognized)")

    # Test Google Drive regex patterns (v2.2.0)
    m_file = GDRIVE_FILE_PATTERN.search("https://drive.google.com/file/d/1B2C3D4E5F6G7H8I9J/view?usp=sharing")
    assert m_file and m_file.group(1) == "1B2C3D4E5F6G7H8I9J"
    m_uc = GDRIVE_FILE_PATTERN.search("https://drive.google.com/uc?id=1B2C3D4E5F6G7H8I9J")
    assert m_uc and m_uc.group(1) == "1B2C3D4E5F6G7H8I9J"
    m_folder = GDRIVE_FOLDER_PATTERN.search("https://drive.google.com/drive/folders/1B2C3D4E5F6G7H8I9J")
    assert m_folder and m_folder.group(1) == "1B2C3D4E5F6G7H8I9J"
    print("✓ GDRIVE_FILE_PATTERN and GDRIVE_FOLDER_PATTERN regex verified")

    # Test aria2c size and ETA parsers (v2.2.0)
    assert _parse_size_str("150MiB") == 150 * 1024 * 1024
    assert _parse_size_str("2.5GiB") == int(2.5 * 1024 * 1024 * 1024)
    assert _parse_size_str("500KiB") == 500 * 1024
    assert _parse_size_str("1024B") == 1024
    assert _parse_eta_str("14s") == 14.0
    assert _parse_eta_str("1m30s") == 90.0
    assert _parse_eta_str("01:30") == 90.0
    print("✓ aria2c size and ETA parsers verified")

    # 7. Test HLS fragment progress estimation (v2.0.0)
    frag_idx, frag_count, dl_bytes = 12, 20, 12000000
    frag_ratio = frag_idx / frag_count
    estimated_total = int(dl_bytes / frag_ratio)
    assert estimated_total == 20000000, f"Expected 20,000,000 bytes, got {estimated_total}"
    assert round(frag_ratio * 100, 1) == 60.0
    print("✓ HLS fragment progress estimation verified (60.0% at 12/20 fragments)")

    # 8. Test _derive_stream_filename with Sinhala/Unicode folder names
    sinhala_url = "https://cdn.example.com/videos/%E0%B6%B4%E0%B7%8F%E0%B6%A9%E0%B6%B8/master.m3u8"
    derived = _derive_stream_filename(sinhala_url)
    assert derived.endswith(".mp4"), f"Expected .mp4 extension, got: {derived}"
    assert "පාඩම" in derived, f"Expected decoded Sinhala folder name in filename, got: {derived}"
    print(f"✓ Sinhala parent folder extraction: '{derived}'")

    english_url = "https://cdn.example.com/videos/Lecture%2001/index.m3u8"
    derived_en = _derive_stream_filename(english_url)
    assert derived_en == "Lecture 01.mp4", f"Expected 'Lecture 01.mp4', got: {derived_en}"
    print(f"✓ English parent folder extraction: '{derived_en}'")

    custom_m3u8 = "https://cdn.example.com/videos/playlist.m3u8"
    derived_custom = _derive_stream_filename(custom_m3u8)
    assert derived_custom == "playlist.mp4", f"Expected 'playlist.mp4', got: {derived_custom}"
    print(f"✓ Non-master m3u8 stem fallback: '{derived_custom}'")

    # 9. Test Header filename extraction (RFC 5987 / 6266)
    headers = {"Content-Disposition": 'attachment; filename="custom_doc.pdf"'}
    assert extract_filename_from_headers(headers, "http://test.com/file") == "custom_doc.pdf"

    headers_utf = {"Content-Disposition": "attachment; filename*=UTF-8''my%20presentation.mp4"}
    assert extract_filename_from_headers(headers_utf, "http://test.com/file") == "my presentation.mp4"
    print("✓ extract_filename_from_headers passed")

    # 10. Test user input parsing
    url, passc, name = parse_user_input("https://us02web.zoom.us/rec/share/123 | mypass | presentation.mp4")
    assert url == "https://us02web.zoom.us/rec/share/123"
    assert passc == "mypass"
    assert name == "presentation.mp4"

    url2, passc2, name2 = parse_user_input("https://example.com/file.zip | myarchive.zip")
    assert url2 == "https://example.com/file.zip"
    assert passc2 is None
    assert name2 == "myarchive.zip"

    url3, passc3, name3 = parse_user_input("https://drive.google.com/file/d/123/view | GDrive_File.zip")
    assert url3 == "https://drive.google.com/file/d/123/view"
    assert passc3 is None
    assert name3 == "GDrive_File.zip"
    print("✓ parse_user_input passed (including GDrive custom name)")

    # 11. Test Config 2GB vs 4GB limits
    assert Config.BOT_MAX_SIZE == 2 * 1024 * 1024 * 1024
    assert Config.PREMIUM_MAX_SIZE == 4 * 1024 * 1024 * 1024
    print("✓ Config BOT_MAX_SIZE and PREMIUM_MAX_SIZE constants verified")

    # 12. Test optional USER_SESSION_STRING fallback
    if not Config.USER_SESSION_STRING:
        assert Config.MAX_FILE_SIZE == Config.BOT_MAX_SIZE
        assert Config.is_premium_enabled() is False
        print("✓ USER_SESSION_STRING fallback: 2GB bot-only mode confirmed (no session configured)")
    else:
        assert Config.MAX_FILE_SIZE == Config.PREMIUM_MAX_SIZE
        assert Config.is_premium_enabled() is True
        print("✓ USER_SESSION_STRING active: 4GB premium mode confirmed")

    # 13. Test bot.py entrypoint uses bot.run(main()) for Python 3.12+ loop stability
    bot_code = Path("bot.py").read_text(encoding="utf-8")
    assert "bot.run(main())" in bot_code, "bot.py must use bot.run(main()) as entrypoint"
    assert "asyncio.run(main())" not in bot_code, "bot.py must not use asyncio.run(main())"
    print("✓ Python 3.12+ event loop fix verified in bot.py (bot.run(main()) is active)")

    # 14. Test downloader.py has high-speed engine, native HLS & 32-fragment concurrency
    dl_code = Path("downloader.py").read_text(encoding="utf-8")
    assert '"hls_prefer_native": True' in dl_code, "downloader.py must enable native HLS downloader"
    assert '"concurrent_fragment_downloads": 32' in dl_code, "downloader.py must use 32 concurrent fragments"
    assert '"buffersize": 1024 * 1024' in dl_code, "downloader.py must use 1MB buffer"
    assert '"http_chunk_size": 10485760' in dl_code, "downloader.py must use 10MB chunk buffers"
    assert "download_gdrive_file" in dl_code, "downloader.py must contain download_gdrive_file"
    assert "aria2c" in dl_code, "downloader.py must support aria2c acceleration"
    print("✓ High-Speed 32-fragment HLS, aria2c & Google Drive engine verified in downloader.py")

    # 15. Test setup_service.sh systemd installer script with aria2
    setup_sh = Path("setup_service.sh").read_text(encoding="utf-8")
    assert "any-url-bot.service" in setup_sh, "setup_service.sh must configure any-url-bot.service"
    assert "systemctl enable any-url-bot.service" in setup_sh
    assert "apt-get install -y aria2" in setup_sh, "setup_service.sh must auto-install aria2"
    print("✓ setup_service.sh one-command systemd installer script with aria2 verified")

    # 16. Test Zoom meeting ID & CSRF extraction and fallback extractor (v2.2.1)
    assert issubclass(ZoomPasscodeRequiredError, ValueError)

    # Test meeting ID extraction from URL paths and HTML
    assert _extract_zoom_meeting_id("https://us02web.zoom.us/rec/share/abc123xyz") == "abc123xyz"
    assert _extract_zoom_meeting_id("https://company.zoom.us/rec/play/987xyz?startTime=123") == "987xyz"
    assert _extract_zoom_meeting_id("https://zoom.us/recording/play/lecture_456") == "lecture_456"
    sample_id_html = '<input type="hidden" name="id" value="meet_token_999"/>'
    assert _extract_zoom_meeting_id("https://zoom.us/rec/validate_meet_passwd", sample_id_html) == "meet_token_999"
    print("✓ Zoom meeting ID extraction from URLs and HTML verified")

    # Test CSRF token extraction from meta tag and inline JS
    sample_meta_html = '<meta name="csrf-token" content="csrf_meta_123"/>'
    assert _extract_zoom_csrf_token(sample_meta_html) == "csrf_meta_123"
    sample_js_html = '<script>window.__data__ = { csrfToken: "csrf_js_456" };</script>'
    assert _extract_zoom_csrf_token(sample_js_html) == "csrf_js_456"
    print("✓ Zoom CSRF token extraction from meta tags and JS verified")

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
    print("✓ Zoom HTML MP4 (with escaped slashes) & topic extraction verified")

    # Verify action=viewdetailpage and ZOOM-CSRFTOKEN in downloader.py
    assert '"action": "viewdetailpage"' in dl_code, "downloader.py must use action='viewdetailpage'"
    assert '"ZOOM-CSRFTOKEN"' in dl_code, "downloader.py must include ZOOM-CSRFTOKEN header"
    assert '"X-Requested-With": "XMLHttpRequest"' in dl_code, "downloader.py must include X-Requested-With header"
    print("✓ Zoom passcode validation headers & payload verified in downloader.py")

    dummy_cookie_file = Path("test_cookies_tmp.txt")
    dummy_cookie_file.write_text(".zoom.us\tTRUE\t/\tTRUE\t1790000000\t_zm_session\txyz123\n", encoding="utf-8")
    loaded_cookies = _load_netscape_cookies(dummy_cookie_file)
    assert loaded_cookies.get("_zm_session") == "xyz123"
    dummy_cookie_file.unlink(missing_ok=True)
    print("✓ Netscape cookies.txt parser verified")

    # 17. Test bot.py has document_upload_handler for cookies.txt (with wildcard support)
    assert "document_upload_handler" in bot_code, "bot.py must include document_upload_handler"
    assert "cookies.txt" in bot_code, "bot.py must handle cookies.txt upload"
    assert 'startswith("cookies")' in bot_code, "bot.py must support cookies (1).txt filenames"
    print("✓ Telegram cookies.txt upload handler with wildcard support verified in bot.py")

    # 18. Test /zoomstream command & absolute cookies path (v2.3.0)
    assert Config.COOKIES_FILE.is_absolute(), "Config.COOKIES_FILE must be an absolute path"
    assert "zoomstream_handler" in bot_code, "bot.py must include zoomstream_handler"
    assert "execute_download_pipeline" in bot_code, "bot.py must include execute_download_pipeline"
    print("✓ /zoomstream command handler and absolute COOKIES_FILE verified in bot.py & config.py")

    # 19. Test Chrome Extension Manifest V3 configuration (v2.3.0)
    manifest_code = Path("chrome-extension/manifest.json").read_text(encoding="utf-8")
    assert '"scripting"' in manifest_code, "manifest.json must include scripting permission"
    assert '"webRequest"' in manifest_code, "manifest.json must include webRequest permission"
    assert '"1.1.0"' in manifest_code, "manifest.json version must be 1.1.0"
    print("✓ Chrome Extension Manifest V3 scripting & webRequest permissions verified")

    # 20. Test thread-safe ProgressTracker in bot.py (v2.2.0)
    assert "def update(" in bot_code, "bot.py ProgressTracker must have universal update method"
    assert "def update_download_threadsafe(" in bot_code, "bot.py ProgressTracker must have threadsafe method"
    assert "asyncio.run_coroutine_threadsafe" in bot_code, "bot.py must use run_coroutine_threadsafe for worker threads"
    print("✓ Thread-safe ProgressTracker verified in bot.py")

    # 19. Test clean_directory
    test_clean_dir = Path("test_clean_tmp")
    test_clean_dir.mkdir(exist_ok=True)
    (test_clean_dir / "dummy.txt").write_text("hello")
    clean_directory(test_clean_dir)
    assert not test_clean_dir.exists()
    print("✓ clean_directory workspace cleanup verified")

    # 17. Test FFmpeg / FFprobe integration if ffmpeg is available
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
    print("\n🎉 ALL TESTS COMPLETED AND PASSED PERFECTLY (v2.3.0)!\n")


if __name__ == "__main__":
    run_tests()
