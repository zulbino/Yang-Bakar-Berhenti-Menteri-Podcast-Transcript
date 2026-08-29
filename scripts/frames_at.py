"""Contact sheet of video frames for a time range, to see WHO IS ON CAMERA.

The camera in this podcast cuts to whoever is talking, so a frame is direct evidence of
a speaker where the audio methods run out. Confirmed against the owner's own reading on
ep55: at 16:05 the shot is Rafizi alone, and by 16:11 it has cut to Haziq, matching his
adjudication of those two turns exactly.

TWO THINGS THE FRAMES WILL LIE ABOUT IF YOU FORGET THEM:

  - THE CUT LAGS THE SPEECH, by roughly two seconds, and not by a fixed amount. At
    ep55's 16:08, which the owner identified as Haziq's turn, the shot is still Rafizi;
    it cuts at 16:10. So --at pads every target by PAD seconds on BOTH sides and never
    samples a single second. The owner's instruction, and the reason the default is 2.
  - A two-shot proves nothing. Wide shots holding both hosts are common, and so are
    full-screen graphics; in those frames the speaker is unknowable. Only a single close
    shot of one person, mouth open, is evidence.

Frames are tiled into ONE image with the absolute timestamp burned into each, because
reading twenty separate images costs twenty times the context and loses the ordering.

Only the requested window is fetched, via yt-dlp --download-sections, so a 20-second look
does not pull a 3-hour file.

FETCHING MUST GO THROUGH yt_download's CONFIGURATION, not a bare yt-dlp call. A plain
invocation falls back to the ANDROID_VR client, whose signed URLs 403 the moment anything
but yt-dlp's own negotiated client requests them -- which is exactly what --download-sections
does, since it hands the URL to ffmpeg. Reusing the web_embedded client, the local PO-token
server and the node JS runtime (yt_download.py's docstring explains why that combination)
makes the range fetch work.

Usage:
  python scripts/frames_at.py ep36 --at 03:19 13:33 51:58     # one padded row per turn
  python scripts/frames_at.py ep55 --range 16:05 16:25        # one continuous stretch
"""
import argparse
import glob
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yt_download

ROOT = Path(__file__).resolve().parent.parent
# No drive letter: ffmpeg's filtergraph parser splits options on ":" and no amount of
# backslash escaping stops it swallowing "C:". A drive-relative path avoids the colon
# entirely, and fontconfig-by-name is not an option (this build ships no default config).
FONT = "/Windows/Fonts/arial.ttf"
FORMAT = "bestvideo[height<=480][ext=mp4]/bestvideo[height<=480]"
CACHE = ROOT / "data" / "frames_cache"


def secs(stamp):
    parts = [int(p) for p in stamp.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def video_id(tag):
    """Resolve an `epNN` tag, or `epNN:bakar` / `epNN:berhenti` where both shows have it.

    This used to hardcode `"bakar" not in d`, which made all six yang-bakar-menteri
    episodes unreachable rather than merely ambiguous -- and YBkM-ep02 is exactly where
    the video is needed, since its raw.md leaves 78 turns on `Moderator` and the YBkM
    moderator rotates between people rather than being one fixed MC.
    """
    tag, _, show = tag.partition(":")
    hits = [d for d in sorted(glob.glob(str(ROOT / "episodes/*/*")))
            if re.search(r"-" + tag + r"-", os.path.basename(d))
            and (not show or show in d)]
    if not hits:
        sys.exit(f"no episode matched {tag}")
    if len(hits) > 1:
        opts = ", ".join(f"{tag}:{'bakar' if 'bakar' in h else 'berhenti'}" for h in hits)
        sys.exit(f"{tag} matches {len(hits)} episodes; disambiguate: {opts}")
    text = (Path(hits[0]) / "interview.md").read_text(encoding="utf-8")
    return re.search(r"video_id:\s*(\S+)", text).group(1)


def fetch(vid, t0, t1):
    """Download just [t0, t1) of the video-only stream, cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    clip = CACHE / f"{vid}_{t0}_{t1}.mp4"
    if clip.exists():
        return clip
    yt_download.ensure_pot_server()
    dl = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "-f", FORMAT, "--quiet", "--no-warnings",
         "--js-runtimes", f"node:{yt_download._node_path()}",
         "--extractor-args", "youtube:player_client=web_embedded",
         "--ffmpeg-location", yt_download._ffmpeg_location(),
         "--download-sections", f"*{t0}-{t1}", "--force-keyframes-at-cuts",
         "-o", str(clip), f"https://www.youtube.com/watch?v={vid}"],
        capture_output=True, text=True)
    if not clip.exists():
        sys.exit((dl.stderr or dl.stdout).strip()[:2000] or "yt-dlp fetched nothing")
    return clip


def extract(clip, t0, fps, width, dest_dir, first_index):
    """Write labelled frames as dest_dir/seq_NNN.png; returns how many were written."""
    # the clip's timestamps start at 0, so drawtext adds t0 back to label absolute time
    label = (rf"drawtext=fontfile={FONT}:text='%{{pts\:hms\:{t0}}}'"
             ":fontcolor=yellow:fontsize=26:box=1:boxcolor=black@0.7:boxborderw=5:x=8:y=8")
    pattern = str(dest_dir / f"seq_%03d.png")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(clip),
         "-vf", f"fps={fps},scale={width}:-1,{label}",
         "-start_number", str(first_index), pattern],
        capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(proc.stderr.strip()[:2000])
    return len(list(dest_dir.glob("seq_*.png"))) - first_index + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode")
    ap.add_argument("--at", nargs="+", default=[], metavar="STAMP",
                    help="target timestamps; each gets its own padded row")
    ap.add_argument("--range", nargs=2, default=None, metavar=("START", "END"))
    ap.add_argument("--pad", type=int, default=2,
                    help="seconds sampled before and after each --at target")
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--cols", type=int, default=5)
    ap.add_argument("--width", type=int, default=400, help="per-tile width in pixels")
    ap.add_argument("--out")
    args = ap.parse_args()
    if not args.at and not args.range:
        sys.exit("pass --at STAMP [STAMP ...] or --range START END")

    vid = video_id(args.episode)
    # A disambiguated tag carries a colon ("ep02:bakar"), which Windows rejects in a path.
    safe = args.episode.replace(":", "-")
    work = CACHE / f"_frames_{safe}"
    if work.exists():
        for f in work.glob("seq_*.png"):
            f.unlink()
    work.mkdir(parents=True, exist_ok=True)

    if args.range:
        t0, t1 = secs(args.range[0]), secs(args.range[1])
        if t1 <= t0:
            sys.exit("end must be after start")
        extract(fetch(vid, t0, t1), t0, args.fps, args.width, work, 1)
        cols, label = args.cols, f"{args.range[0]}-{args.range[1]}"
    else:
        # one row per target, so a row reads as "where did the cut land for this turn"
        cols = 2 * args.pad + 1
        n = 1
        for stamp in args.at:
            t = secs(stamp)
            a, b = max(0, t - args.pad), t + args.pad + 1
            extract(fetch(vid, a, b), a, 1.0, args.width, work, n)
            n += cols
        label = f"{len(args.at)} target(s), pad {args.pad}s"

    frames = sorted(work.glob("seq_*.png"))
    rows = -(-len(frames) // cols)
    out = args.out or str(ROOT / f"frames_{safe}.png")
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(work / "seq_%03d.png"),
         "-vf", f"tile={cols}x{rows}:margin=4:padding=4", "-frames:v", "1", out],
        capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(proc.stderr.strip()[:2000])
    print(f"{out}  ({len(frames)} frames, {cols}x{rows}, {label})")
    if args.at:
        for i, stamp in enumerate(args.at):
            print(f"  row {i + 1}: {stamp}")


if __name__ == "__main__":
    main()
