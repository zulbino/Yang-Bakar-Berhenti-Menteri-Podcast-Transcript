"""Download episode audio from YouTube.

YouTube blocks most yt-dlp client/format combinations behind PO tokens, SABR-only
streaming, or DRM. The working combination found by trial: the `web_embedded`
client, a locally-run bgutil PO-token HTTP server, and node.js for JS challenge
solving (via the yt-dlp-ejs package). Requires `pip install yt-dlp yt-dlp-ejs
bgutil-ytdlp-pot-provider` and the bgutil server repo built once:

    git clone https://github.com/Brainicism/bgutil-ytdlp-pot-provider ~/bgutil-ytdlp-pot-provider
    cd ~/bgutil-ytdlp-pot-provider/server && npm ci && npx tsc
"""
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

POT_SERVER_HOME = Path.home() / "bgutil-ytdlp-pot-provider" / "server"
POT_SERVER_URL = "http://127.0.0.1:4416/ping"
_pot_server_process = None


def _pot_server_up():
    try:
        urllib.request.urlopen(POT_SERVER_URL, timeout=2)
        return True
    except Exception:
        return False


def ensure_pot_server():
    global _pot_server_process
    if _pot_server_up():
        return
    _pot_server_process = subprocess.Popen(
        ["node", "build/main.js"], cwd=POT_SERVER_HOME,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(20):
        if _pot_server_up():
            return
        time.sleep(1)
    raise RuntimeError("bgutil PO token server did not start in time")


def _node_path():
    path = shutil.which("node")
    if not path:
        raise RuntimeError("node.js not found in PATH")
    return path


# yt-dlp downloads raw DASH audio fragments; without ffmpeg to remux them into a
# proper container, Gemini's Files API rejects the upload (state=FAILED).
_FFMPEG_FALLBACK = Path.home() / "AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-9.0-full_build/bin/ffmpeg.exe"


def _ffmpeg_location():
    path = shutil.which("ffmpeg")
    if path:
        return path
    if _FFMPEG_FALLBACK.exists():
        return str(_FFMPEG_FALLBACK.parent)
    raise RuntimeError("ffmpeg not found -- install it (e.g. `winget install Gyan.FFmpeg`)")


def download_audio(video_id, out_dir):
    ensure_pot_server()
    out_path = Path(out_dir) / f"{video_id}.m4a"
    subprocess.run(
        [
            "python", "-m", "yt_dlp",
            "-f", "bestaudio[ext=m4a]/bestaudio",
            "--js-runtimes", f"node:{_node_path()}",
            "--extractor-args", "youtube:player_client=web_embedded",
            "--ffmpeg-location", _ffmpeg_location(),
            "-o", str(out_path),
            f"https://www.youtube.com/watch?v={video_id}",
        ],
        check=True,
    )
    return out_path
