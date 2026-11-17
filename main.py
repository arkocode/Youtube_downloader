import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Optional

import telebot
from dotenv import load_dotenv
from pytubefix import YouTube
from telebot import types
from telebot.apihelper import ApiTelegramException


LOGGER = logging.getLogger(__name__)
ACTION_TTL_SECONDS = 60 * 60
CALLBACK_ACTIONS = {}


@dataclass(frozen=True)
class CallbackAction:
    kind: str
    url: str
    owner_id: int
    itag: Optional[int] = None
    resolution: Optional[str] = None


def extract_video_url(text):
    for token in text.split():
        if token.startswith(("https://", "http://")):
            return token.rstrip(".,;!?)]}")
    return None


def stream_bitrate(stream):
    match = re.search(r"\d+(?:\.\d+)?", getattr(stream, "abr", "") or "")
    return float(match.group()) if match else 0


def select_audio_stream(streams):
    audio_streams = list(streams)
    if not audio_streams:
        raise ValueError("No audio streams are available for this video.")
    return max(audio_streams, key=stream_bitrate)


def stream_size_mb(stream):
    size = getattr(stream, "filesize_mb", None)
    return float(size) if size is not None else None


def format_size(*streams):
    sizes = [stream_size_mb(stream) for stream in streams]
    if any(size is None for size in sizes):
        return "size unavailable"
    return f"~{sum(sizes):.1f} MB"


def resolution_height(resolution):
    match = re.search(r"(\d+)", resolution or "")
    return int(match.group(1)) if match else 0


def available_video_streams(streams):
    selected = {}
    for stream in streams:
        resolution = getattr(stream, "resolution", None)
        if not resolution:
            continue
        current = selected.get(resolution)
        score = (getattr(stream, "fps", 0) or 0, stream_size_mb(stream) or 0)
        current_score = (
            (getattr(current, "fps", 0) or 0, stream_size_mb(current) or 0)
            if current
            else None
        )
        if current is None or score > current_score:
            selected[resolution] = stream
    return sorted(
        selected.values(),
        key=lambda stream: resolution_height(stream.resolution),
        reverse=True,
    )


def register_action(action):
    now = time.monotonic()
    expired = [
        token
        for token, (created_at, _) in CALLBACK_ACTIONS.items()
        if now - created_at > ACTION_TTL_SECONDS
    ]
    for token in expired:
        del CALLBACK_ACTIONS[token]

    token = uuid.uuid4().hex
    CALLBACK_ACTIONS[token] = (now, action)
    return f"act:{token}"


def get_action(callback_data, owner_id):
    token = callback_data.removeprefix("act:")
    entry = CALLBACK_ACTIONS.get(token)
    if entry is None or time.monotonic() - entry[0] > ACTION_TTL_SECONDS:
        CALLBACK_ACTIONS.pop(token, None)
        return None
    action = entry[1]
    if action.owner_id != owner_id:
        return None
    del CALLBACK_ACTIONS[token]
    return action


def build_ffmpeg_command(ffmpeg, video_file, audio_file, output_file):
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        video_file,
        "-i",
        audio_file,
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        output_file,
    ]


def require_ffmpeg():
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, FileNotFoundError, RuntimeError):
        ffmpeg = None

    if ffmpeg and os.path.isfile(ffmpeg):
        return ffmpeg
    raise RuntimeError(
        "FFmpeg was not found. Install the project dependencies (including "
        "imageio-ffmpeg) or install FFmpeg and add it to PATH."
    )


def send_media(bot, send_method, user_id, media, file_path, media_type, **kwargs):
    try:
        send_method(user_id, media, **kwargs)
    except ApiTelegramException as error:
        if error.error_code != 413:
            raise

        size_mib = os.path.getsize(file_path) / (1024 * 1024)
        bot.send_message(
            user_id,
            f"Telegram rejected this {media_type} upload as too large. "
            f"The finished file is {size_mib:.1f} MiB. Try the link again and "
            "choose a lower quality. Larger uploads need a separately configured "
            "Local Bot API server. This temporary file will be removed when this "
            "request ends, so send the link again to download it.",
        )


def combine_streams(video_file, audio_file, output_file, ffmpeg=None):
    ffmpeg = ffmpeg or require_ffmpeg()
    command = build_ffmpeg_command(ffmpeg, video_file, audio_file, output_file)
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=900)
    except subprocess.CalledProcessError as error:
        LOGGER.error("FFmpeg failed: %s", error.stderr[-2000:])
        raise RuntimeError("FFmpeg could not combine the downloaded audio and video.") from error
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("FFmpeg took too long to combine the downloaded streams.") from error


def get_video(link):
    video = YouTube(link)
    video_streams = available_video_streams(
        video.streams.filter(progressive=False, file_extension="mp4", only_video=True)
    )
    audio_stream = select_audio_stream(video.streams.filter(only_audio=True))
    if not video_streams:
        raise ValueError("No separate MP4 video streams are available for this link.")
    return video, video_streams, audio_stream


def build_keyboard(video, video_streams, audio_stream, owner_id):
    buttons = []
    for stream in video_streams:
        action = CallbackAction(
            "video", video.watch_url, owner_id, stream.itag, stream.resolution
        )
        buttons.append(
            types.InlineKeyboardButton(
                f"🎬 {stream.resolution} · {format_size(stream, audio_stream)}",
                callback_data=register_action(action),
            )
        )

    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append(
        [
            types.InlineKeyboardButton(
                "🎵 MP3",
                callback_data=register_action(
                    CallbackAction("mp3", video.watch_url, owner_id)
                ),
            ),
            types.InlineKeyboardButton(
                "🖼 Thumbnail",
                callback_data=register_action(
                    CallbackAction("thumbnail", video.watch_url, owner_id)
                ),
            ),
        ]
    )
    return types.InlineKeyboardMarkup(rows)


def send_video_choices(message, bot):
    link = extract_video_url(message.text or "")
    if not link:
        bot.send_message(
            message.chat.id,
            "Send a YouTube link to see the available video and audio options.",
        )
        return

    try:
        video, video_streams, audio_stream = get_video(link)
        keyboard = build_keyboard(
            video, video_streams, audio_stream, message.from_user.id
        )
        caption = f"⬇️ Choose a format\n\n{video.title}\nby {video.author}"
        caption = caption[:1024]
        try:
            bot.send_photo(
                message.chat.id,
                video.thumbnail_url,
                caption=caption,
                reply_to_message_id=message.message_id,
                reply_markup=keyboard,
            )
        except ApiTelegramException:
            LOGGER.warning("Could not send thumbnail; sending the choices as text.")
            bot.send_message(
                message.chat.id,
                caption,
                reply_to_message_id=message.message_id,
                reply_markup=keyboard,
            )
    except Exception:
        LOGGER.exception("Could not prepare download options.")
        bot.send_message(
            message.chat.id,
            "I couldn't read that video. Check the link and try again.",
        )


def download_video(action, user_id, bot):
    ffmpeg = require_ffmpeg()
    video = YouTube(action.url)
    video_stream = video.streams.get_by_itag(action.itag)
    if video_stream is None:
        raise ValueError("The selected video quality is no longer available.")
    audio_stream = select_audio_stream(video.streams.filter(only_audio=True))

    bot.send_message(user_id, "⬇️ Downloading the selected video and audio…")
    with tempfile.TemporaryDirectory(prefix="youtube-downloader-") as work_dir:
        video_file = video_stream.download(
            output_path=work_dir, filename=f"video.{video_stream.subtype}"
        )
        audio_file = audio_stream.download(
            output_path=work_dir, filename=f"audio.{audio_stream.subtype}"
        )
        output_file = os.path.join(work_dir, "combined.mp4")
        combine_streams(video_file, audio_file, output_file, ffmpeg)

        bot.send_message(user_id, "📤 Sending your video…")
        with open(output_file, "rb") as media:
            send_media(
                bot,
                bot.send_video,
                user_id,
                media,
                output_file,
                "video",
                supports_streaming=True,
                caption=f"{video.title}\nby {video.author}\n{video_stream.resolution}",
            )


def download_mp3(action, user_id, bot):
    video = YouTube(action.url)
    audio_stream = select_audio_stream(video.streams.filter(only_audio=True))
    ffmpeg = require_ffmpeg()

    bot.send_message(user_id, "🎵 Preparing your MP3…")
    with tempfile.TemporaryDirectory(prefix="youtube-downloader-") as work_dir:
        audio_file = audio_stream.download(
            output_path=work_dir, filename=f"audio.{audio_stream.subtype}"
        )
        output_file = os.path.join(work_dir, "audio.mp3")
        try:
            subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    audio_file,
                    "-vn",
                    "-codec:a",
                    "libmp3lame",
                    "-q:a",
                    "2",
                    output_file,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=900,
            )
        except subprocess.CalledProcessError as error:
            LOGGER.error("FFmpeg MP3 conversion failed: %s", error.stderr[-2000:])
            raise RuntimeError("FFmpeg could not convert the audio to MP3.") from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("FFmpeg took too long to convert the audio.") from error

        with open(output_file, "rb") as media:
            send_media(
                bot,
                bot.send_audio,
                user_id,
                media,
                output_file,
                "audio",
                caption=f"{video.title}\nby {video.author}\nMP3",
            )


def handle_callback(callback, bot):
    action = get_action(callback.data or "", callback.from_user.id)
    if action is None:
        bot.answer_callback_query(
            callback.id,
            "This selection is unavailable. Send the link again if it expired.",
            show_alert=True,
        )
        return

    bot.answer_callback_query(callback.id)
    try:
        if action.kind == "video":
            download_video(action, callback.from_user.id, bot)
        elif action.kind == "mp3":
            download_mp3(action, callback.from_user.id, bot)
        elif action.kind == "thumbnail":
            video = YouTube(action.url)
            bot.send_photo(
                callback.from_user.id,
                video.thumbnail_url,
                caption=f"{video.title}\nby {video.author}",
            )
    except Exception as error:
        LOGGER.exception("Download action failed.")
        bot.send_message(
            callback.from_user.id,
            f"Download failed: {error}",
        )


def main():
    load_dotenv(".env")
    token = os.environ.get("API_KEY")
    if not token:
        raise RuntimeError("Set API_KEY in the .env file before starting the bot.")

    logging.basicConfig(level=logging.INFO)
    bot = telebot.TeleBot(token)

    @bot.message_handler(commands=["start"])
    def greeting(message):
        bot.send_message(
            message.chat.id,
            "Hi! Send a YouTube link to choose an available video quality or MP3.",
        )

    @bot.message_handler(content_types=["text"])
    def receive_link(message):
        send_video_choices(message, bot)

    @bot.callback_query_handler(func=lambda callback: bool(callback.data))
    def handle_selection(callback):
        handle_callback(callback, bot)

    bot.infinity_polling(skip_pending=True)


if __name__ == "__main__":
    main()
