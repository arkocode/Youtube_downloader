import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import main


class TelegramUploadTests(unittest.TestCase):
    def test_413_reports_actual_size_and_recovery_steps(self):
        error = main.ApiTelegramException(
            "sendVideo",
            "413 Request Entity Too Large",
            {"error_code": 413, "description": "Request Entity Too Large"},
        )
        bot = SimpleNamespace(send_message=Mock())
        send_method = Mock(side_effect=error)

        with tempfile.TemporaryDirectory() as folder:
            file_path = os.path.join(folder, "video.mp4")
            with open(file_path, "wb") as file:
                file.write(b"\0" * (int(1.5 * 1024 * 1024)))
            with open(file_path, "rb") as media:
                main.send_media(
                    bot, send_method, 42, media, file_path, "video"
                )

        message = bot.send_message.call_args.args[1]
        self.assertIn("1.5 MiB", message)
        self.assertIn("choose a lower quality", message)
        self.assertIn("Local Bot API server", message)
        self.assertIn("send the link again", message)

    def test_non_413_telegram_errors_are_not_hidden(self):
        error = main.ApiTelegramException(
            "sendVideo",
            "500 Internal Server Error",
            {"error_code": 500, "description": "Internal Server Error"},
        )
        bot = SimpleNamespace(send_message=Mock())
        with self.assertRaises(main.ApiTelegramException):
            main.send_media(bot, Mock(side_effect=error), 42, None, "video.mp4", "video")
        bot.send_message.assert_not_called()


class FakeStream:
    def __init__(
        self,
        itag,
        abr=None,
        resolution=None,
        fps=30,
        filesize_mb=1.0,
    ):
        self.itag = itag
        self.abr = abr
        self.resolution = resolution
        self.fps = fps
        self.filesize_mb = filesize_mb


class DownloaderHelpersTests(unittest.TestCase):
    def test_extract_video_url_from_message_text(self):
        self.assertEqual(
            main.extract_video_url("Please download https://youtu.be/abc123?feature=share."),
            "https://youtu.be/abc123?feature=share",
        )
        self.assertIsNone(main.extract_video_url("No link here"))

    def test_selects_best_available_audio_without_fixed_itags(self):
        streams = [
            FakeStream(999, abr="48kbps"),
            FakeStream(777, abr="160kbps"),
            FakeStream(888, abr="128kbps"),
        ]
        self.assertEqual(main.select_audio_stream(streams).itag, 777)
        with self.assertRaisesRegex(ValueError, "No audio streams"):
            main.select_audio_stream([])

    def test_video_options_are_sorted_and_choose_best_duplicate(self):
        streams = [
            FakeStream(1, resolution="720p", fps=30, filesize_mb=5),
            FakeStream(2, resolution="1080p", fps=30, filesize_mb=8),
            FakeStream(3, resolution="720p", fps=60, filesize_mb=6),
        ]
        result = main.available_video_streams(streams)
        self.assertEqual([stream.itag for stream in result], [2, 3])

    def test_ffmpeg_explicitly_maps_separate_streams_and_copies_video(self):
        command = main.build_ffmpeg_command(
            "ffmpeg.exe", "video.mp4", "audio.webm", "combined.mp4"
        )
        self.assertEqual(command[0], "ffmpeg.exe")
        self.assertIn("0:v:0", command)
        self.assertIn("1:a:0", command)
        self.assertEqual(command[command.index("-c:v") + 1], "copy")
        self.assertEqual(command[command.index("-c:a") + 1], "aac")

    def test_system_ffmpeg_is_preferred(self):
        with patch.object(main.shutil, "which", return_value="C:\\ffmpeg.exe"):
            with patch.dict("sys.modules", {"imageio_ffmpeg": None}):
                self.assertEqual(main.require_ffmpeg(), "C:\\ffmpeg.exe")

    def test_bundled_ffmpeg_is_used_when_path_has_no_ffmpeg(self):
        bundled = "C:\\venv\\ffmpeg-versioned.exe"
        imageio_module = SimpleNamespace(get_ffmpeg_exe=lambda: bundled)
        with patch.object(main.shutil, "which", return_value=None):
            with patch.dict("sys.modules", {"imageio_ffmpeg": imageio_module}):
                with patch.object(main.os.path, "isfile", return_value=True):
                    self.assertEqual(main.require_ffmpeg(), bundled)

    def test_missing_ffmpeg_is_reported_when_no_provider_is_available(self):
        with patch.object(main.shutil, "which", return_value=None):
            with patch.dict("sys.modules", {"imageio_ffmpeg": None}):
                with self.assertRaisesRegex(
                    RuntimeError, "FFmpeg was not found.*imageio-ffmpeg"
                ):
                    main.require_ffmpeg()

    def test_callback_payload_stays_within_telegram_limit(self):
        main.CALLBACK_ACTIONS.clear()
        payload = main.register_action(
            main.CallbackAction("video", "https://www.youtube.com/watch?v=abc", 123)
        )
        self.assertLessEqual(len(payload.encode("utf-8")), 64)
        self.assertIsNone(main.get_action(payload, 456))
        self.assertEqual(main.get_action(payload, 123).owner_id, 123)


if __name__ == "__main__":
    unittest.main()
