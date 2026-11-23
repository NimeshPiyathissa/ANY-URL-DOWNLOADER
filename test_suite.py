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
    extract_filename_from_headers,
    _derive_stream_filename,
)
from bot import parse_user_input


def run_tests():
    print("=" * 60)
    print("      RUNNING BOT COMPONENT & REGRESSION TEST SUITE")
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

    # 2. Test progress bar
    assert generate_progress_bar(0) == "□□□□□□□□□□"
    assert generate_progress_bar(50) == "■■■■■□□□□□"
    assert generate_progress_bar(100) == "■■■■■■■■■■"
    print("✓ generate_progress_bar passed")

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

    # 6. Test _derive_stream_filename with Sinhala/Unicode folder names
    # master.m3u8 with URL-encoded Sinhala parent folder
    sinhala_url = "https://cdn.example.com/videos/%E0%B6%B4%E0%B7%8F%E0%B6%A9%E0%B6%B8/master.m3u8"
    derived = _derive_stream_filename(sinhala_url)
    assert derived.endswith(".mp4"), f"Expected .mp4 extension, got: {derived}"
    assert "පාඩම" in derived, f"Expected decoded Sinhala folder name in filename, got: {derived}"
    print(f"✓ Sinhala parent folder extraction: '{derived}'")

    # index.m3u8 with English parent folder
    english_url = "https://cdn.example.com/videos/Lecture%2001/index.m3u8"
    derived_en = _derive_stream_filename(english_url)
    assert derived_en == "Lecture 01.mp4", f"Expected 'Lecture 01.mp4', got: {derived_en}"
    print(f"✓ English parent folder extraction: '{derived_en}'")

    # Non-master/index .m3u8 falls back to stem
    custom_m3u8 = "https://cdn.example.com/videos/playlist.m3u8"
    derived_custom = _derive_stream_filename(custom_m3u8)
    assert derived_custom == "playlist.mp4", f"Expected 'playlist.mp4', got: {derived_custom}"
    print(f"✓ Non-master m3u8 stem fallback: '{derived_custom}'")

    # 7. Test Header filename extraction (RFC 5987 / 6266)
    headers = {"Content-Disposition": 'attachment; filename="custom_doc.pdf"'}
    assert extract_filename_from_headers(headers, "http://test.com/file") == "custom_doc.pdf"

    headers_utf = {"Content-Disposition": "attachment; filename*=UTF-8''my%20presentation.mp4"}
    assert extract_filename_from_headers(headers_utf, "http://test.com/file") == "my presentation.mp4"
    print("✓ extract_filename_from_headers passed")

    # 8. Test user input parsing
    url, passc, name = parse_user_input("https://us02web.zoom.us/rec/share/123 | mypass | presentation.mp4")
    assert url == "https://us02web.zoom.us/rec/share/123"
    assert passc == "mypass"
    assert name == "presentation.mp4"

    url2, passc2, name2 = parse_user_input("https://example.com/file.zip | myarchive.zip")
    assert url2 == "https://example.com/file.zip"
    assert passc2 is None
    assert name2 == "myarchive.zip"

    # Stream URL with custom filename
    url3, passc3, name3 = parse_user_input("https://cdn.example.com/stream/master.m3u8 | my_lecture.mp4")
    assert url3 == "https://cdn.example.com/stream/master.m3u8"
    assert passc3 is None
    assert name3 == "my_lecture.mp4"
    print("✓ parse_user_input passed")

    # 9. Test Config 2GB vs 4GB limits
    assert Config.BOT_MAX_SIZE == 2 * 1024 * 1024 * 1024
    assert Config.PREMIUM_MAX_SIZE == 4 * 1024 * 1024 * 1024
    print("✓ Config BOT_MAX_SIZE and PREMIUM_MAX_SIZE constants verified")

    # 10. Test optional USER_SESSION_STRING fallback
    # When USER_SESSION_STRING is empty/None, bot should run in 2GB mode without errors
    if not Config.USER_SESSION_STRING:
        assert Config.MAX_FILE_SIZE == Config.BOT_MAX_SIZE, "Without USER_SESSION_STRING, MAX_FILE_SIZE should equal BOT_MAX_SIZE (2GB)"
        assert Config.is_premium_enabled() is False, "Without USER_SESSION_STRING, is_premium_enabled() should be False"
        print("✓ USER_SESSION_STRING fallback: 2GB bot-only mode confirmed (no session configured)")
    else:
        assert Config.MAX_FILE_SIZE == Config.PREMIUM_MAX_SIZE, "With USER_SESSION_STRING, MAX_FILE_SIZE should equal PREMIUM_MAX_SIZE (4GB)"
        assert Config.is_premium_enabled() is True, "With USER_SESSION_STRING, is_premium_enabled() should be True"
        print("✓ USER_SESSION_STRING active: 4GB premium mode confirmed")

    # 13. Test bot.py entrypoint uses bot.run(main()) for Python 3.12+ loop stability
    bot_code = Path("bot.py").read_text(encoding="utf-8")
    assert "bot.run(main())" in bot_code, "bot.py must use bot.run(main()) as entrypoint"
    assert "asyncio.run(main())" not in bot_code, "bot.py must not use asyncio.run(main())"
    print("✓ Python 3.12+ event loop fix verified in bot.py (bot.run(main()) is active)")

    # 14. Test downloader.py has native HLS and safe ASCII template
    dl_code = Path("downloader.py").read_text(encoding="utf-8")
    assert '"hls_prefer_native": True' in dl_code, "downloader.py must enable native HLS downloader"
    assert '"downloader": "native"' in dl_code, "downloader.py must use native downloader"
    assert "stream_output" in dl_code, "downloader.py must use safe ASCII output template for ffmpeg"
    print("✓ Native HLS downloader & safe ASCII remux template verified in downloader.py")

    # 15. Test clean_directory
    test_clean_dir = Path("test_clean_tmp")
    test_clean_dir.mkdir(exist_ok=True)
    (test_clean_dir / "dummy.txt").write_text("hello")
    clean_directory(test_clean_dir)
    assert not test_clean_dir.exists()
    print("✓ clean_directory workspace cleanup verified")

    # 12. Test FFmpeg / FFprobe integration if ffmpeg is available
    async def test_ffmpeg():
        test_dir = Path("test_tmp")
        test_dir.mkdir(exist_ok=True)
        video_path = test_dir / "sample.mp4"
        thumb_path = test_dir / "sample_thumb.jpg"

        # Generate a small 2-second synthetic video test file using ffmpeg
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
    print("\n🎉 ALL TESTS COMPLETED AND PASSED PERFECTLY!\n")


if __name__ == "__main__":
    run_tests()
