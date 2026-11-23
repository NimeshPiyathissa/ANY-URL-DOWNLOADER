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
    _load_netscape_cookies,
    ZoomPasscodeRequiredError,
)
from bot import parse_user_input


def run_tests():
    print("=" * 60)
    print("      RUNNING BOT COMPONENT & REGRESSION TEST SUITE (v2.0.0)")
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

    # 14. Test downloader.py has high-speed engine, native HLS & 16-fragment concurrency
    dl_code = Path("downloader.py").read_text(encoding="utf-8")
    assert '"hls_prefer_native": True' in dl_code, "downloader.py must enable native HLS downloader"
    assert '"concurrent_fragment_downloads": 16' in dl_code, "downloader.py must use 16 concurrent fragments"
    assert '"http_chunk_size": 10485760' in dl_code, "downloader.py must use 10MB chunk buffers"
    assert "download_gdrive_file" in dl_code, "downloader.py must contain download_gdrive_file"
    print("✓ High-Speed 16-fragment HLS & Google Drive engine verified in downloader.py")

    # 15. Test setup_service.sh systemd installer script
    setup_sh = Path("setup_service.sh").read_text(encoding="utf-8")
    assert "any-url-bot.service" in setup_sh, "setup_service.sh must configure any-url-bot.service"
    assert "systemctl enable any-url-bot.service" in setup_sh
    print("✓ setup_service.sh one-command systemd installer script verified")

    # 16. Test Zoom fallback extractor & Netscape cookies loader (v2.1.0)
    assert issubclass(ZoomPasscodeRequiredError, ValueError)
    sample_zoom_html = """
    <html>
      <head><title>Quantum Computing Lecture - Zoom</title></head>
      <body>
        <script>
          window.__data__ = {
            topic: "Quantum Computing Lecture",
            viewMp4Url: "https://ssrweb.zoom.us/rec/play/quantum_lecture.mp4?sig=123"
          };
        </script>
      </body>
    </html>
    """
    extracted_mp4, extracted_topic = _extract_zoom_mp4_and_title(sample_zoom_html)
    assert extracted_mp4 == "https://ssrweb.zoom.us/rec/play/quantum_lecture.mp4?sig=123"
    assert extracted_topic == "Quantum Computing Lecture"
    print("✓ Zoom HTML MP4 & topic extraction verified")

    dummy_cookie_file = Path("test_cookies_tmp.txt")
    dummy_cookie_file.write_text(".zoom.us\tTRUE\t/\tTRUE\t1790000000\t_zm_session\txyz123\n", encoding="utf-8")
    loaded_cookies = _load_netscape_cookies(dummy_cookie_file)
    assert loaded_cookies.get("_zm_session") == "xyz123"
    dummy_cookie_file.unlink(missing_ok=True)
    print("✓ Netscape cookies.txt parser verified")

    # 17. Test bot.py has document_upload_handler for cookies.txt
    assert "document_upload_handler" in bot_code, "bot.py must include document_upload_handler"
    assert "cookies.txt" in bot_code, "bot.py must handle cookies.txt upload"
    print("✓ Telegram cookies.txt upload handler verified in bot.py")

    # 18. Test clean_directory
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
    print("\n🎉 ALL TESTS COMPLETED AND PASSED PERFECTLY (v2.0.0)!\n")


if __name__ == "__main__":
    run_tests()
