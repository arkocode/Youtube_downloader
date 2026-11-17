# YouTube Downloader Bot

A Telegram bot that lists available MP4 video qualities for a YouTube link and
lets the user download a video, an MP3 audio file, or the video's thumbnail.
Use it only for material you own or are authorized to download, and in
accordance with the platform's terms.

## Requirements

- Python 3.9 or newer
- A Telegram bot token
- Internet access for the Telegram Bot API and the media source

FFmpeg is provided by the `imageio-ffmpeg` Python dependency. The bot first
checks for an `ffmpeg` executable on `PATH`, then falls back to the bundled
executable. A separate system FFmpeg installation is optional.

## Install

The following commands use PowerShell on Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

On macOS or Linux, activate the environment with
`source .venv/bin/activate` instead.

Create a `.env` file beside `main.py` with your Telegram bot token:

```dotenv
API_KEY=YOUR_TELEGRAM_BOT_TOKEN
```

Keep the token private. `.env` is ignored by Git; do not paste your token into
source files, issues, or chat messages.

## Run

```powershell
python main.py
```

Open the bot in Telegram and send `/start`, then send a YouTube video link.
Choose an available video quality, MP3, or thumbnail from the buttons.

## Formats and FFmpeg

- **Video:** The bot offers available separate MP4 video streams, pairs the
  selected video with the highest-bitrate available audio stream, copies the
  video stream, and encodes the audio as AAC for the MP4 output.
- **MP3:** The best available audio stream is converted to MP3 with FFmpeg.
- **Thumbnail:** The video's thumbnail is sent as an image.

Media is processed in a temporary directory and removed after the request
finishes. If FFmpeg cannot be found either on `PATH` or in `imageio-ffmpeg`, the
bot reports the dependency that needs to be installed.

## Telegram upload limits

The hosted Telegram Bot API limits uploaded file sizes. If Telegram rejects a
video or audio upload with HTTP 413, the bot reports the finished file's size
and suggests trying the link again at a lower video quality. The temporary file
is removed after the failed request, so it must be downloaded again.

For larger uploads, a separately configured Local Bot API server may support a
higher limit. This project uses the hosted Bot API by default and does not
configure or start a Local Bot API server.

## Tests

Run the unit tests from the repository root:

```powershell
python -m unittest discover -s tests -v
```
