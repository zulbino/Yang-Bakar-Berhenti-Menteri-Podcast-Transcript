"""Ask Gemini to watch a stretch of the show and write down who speaks when.

WHY THIS EXISTS, AND WHAT IT IS COMPETING WITH. The camera reference
(`scripts/camera_speakers.py`) is the most accurate speaker evidence in this repo, but it
costs about four hours of GPU per episode -- measured on ep57 -- and 64 episodes still need
one, which is roughly nine days of the machine running non-stop. A model that watches AND
hears the video could produce the same timeline in minutes. `verify_speakers_video.py`
already proves the idea works for a single disputed window: it settled 11 of ep62's labels.
This asks for a whole stretch instead of one moment.

IT IS AN EXPERIMENT UNTIL IT IS MEASURED, and ep62 is what makes measuring possible: it has
a camera reference validated against the owner's own read of the file. So the output is
written as an RTTM and scored with `score_attribution.py` against that reference, over the
same window. If it lands near the camera, the remaining episodes cost hours instead of days.
If it does not, this file records that it did not.

THE CAST DESCRIPTIONS ARE THE WHOLE GAME. The model has no voiceprints and no cast list, so
it gets what a viewer gets: who wears what and where they sit, reused from
verify_speakers_video.CAST. Get those wrong and every answer is wrong.

TWO CAUTIONS THAT CARRY OVER FROM THE SINGLE-WINDOW VERSION. The camera cut lags the speech
by about two seconds, so the boundaries a model reports from vision alone are late. And do
not mine the model's own account of what it saw -- on ep62 its "the mouth is closed" reading
was wrong at 0:05:58. The timeline is evidence to score, not an answer to trust.

  python scripts/gemini_speaker_timeline.py ep62 --start 3600 --minutes 10
  python scripts/score_attribution.py data/camera_ref_ep62.rttm --episode ep62 \
      --blocks gemini=data/_gemini_timeline_ep62.rttm
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import verify_speakers_video as single  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
API = "https://generativelanguage.googleapis.com"
FALLBACK = "gemini-3.5-flash"      # 3.8-flash returned 503 "high demand" on the first run
PROMPT = """You are watching a Malaysian political podcast. Several people sit in one studio
and the vision mixer cuts to whoever is speaking, usually about two seconds late.

The people you can see:
{cast}

Watch and listen to the whole clip. Write down every stretch of speech and who speaks it.
Use the AUDIO to decide when one person stops and the next starts, and the PICTURE to decide
who it is. A stretch may be as short as one word. Do not merge two people into one stretch.
The clip starts at {offset} seconds into the episode; report times in seconds from the START
OF THE CLIP, not from the start of the episode.

Reply with JSON only, no prose:
{{"turns": [{{"start": 0.0, "end": 4.2, "speaker": "<one of the names above>"}}]}}"""


def clip_with_sound(vid, start, end):
    """A window of the show with BOTH streams, re-encoded so the API can decode it.

    verify_speakers_video.clip() produced video only here, and the Files API answered "the
    file failed to be processed" -- and a silent clip could not answer the question anyway,
    since the audio is what marks a turn boundary. The audio comes from audio/<vid>.m4a, cut
    with an accurate seek on the INPUT of a re-encode; the ENGINEERING_LOG entry about -ss
    with -c:v copy does not apply because nothing is stream-copied.
    """
    import subprocess
    import frames_at
    from yt_download import _ffmpeg_location
    out = ROOT / "data" / "frames_cache" / f"{vid}_{start}_{end}_av.mp4"
    if out.exists() and out.stat().st_size > 1e6:
        return out
    video = frames_at.fetch(vid, start, end)
    audio = ROOT / "audio" / f"{vid}.m4a"
    if not audio.exists():
        sys.exit(f"no audio at {audio}")
    cmd = [str(_ffmpeg_location()), "-v", "error", "-y",
           "-i", str(video),
           "-ss", str(start), "-t", str(end - start), "-i", str(audio),
           "-map", "0:v:0", "-map", "1:a:0",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
           "-r", "10", "-vf", "scale=640:-2", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "64k", "-ac", "1",
           "-shortest", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)
    return out


def upload(path, key):
    """The Files API, because a ten-minute clip is far past the inline limit."""
    size = path.stat().st_size
    req = urllib.request.Request(
        f"{API}/upload/v1beta/files?key={key}",
        data=json.dumps({"file": {"display_name": path.name}}).encode(),
        headers={"X-Goog-Upload-Protocol": "resumable",
                 "X-Goog-Upload-Command": "start",
                 "X-Goog-Upload-Header-Content-Length": str(size),
                 "X-Goog-Upload-Header-Content-Type": "video/mp4",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        session = r.headers["X-Goog-Upload-URL"]
    req = urllib.request.Request(
        session, data=path.read_bytes(),
        headers={"Content-Length": str(size), "X-Goog-Upload-Offset": "0",
                 "X-Goog-Upload-Command": "upload, finalize"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        info = json.load(r)["file"]
    name = info["name"]
    for _ in range(120):                      # ACTIVE means Google has finished decoding it
        with urllib.request.urlopen(f"{API}/v1beta/{name}?key={key}", timeout=60) as r:
            info = json.load(r)
        if info.get("state") == "ACTIVE":
            return info["uri"]
        if info.get("state") == "FAILED":
            sys.exit(f"upload failed: {info}")
        time.sleep(5)
    sys.exit("upload never became ACTIVE")


def ask(uri, cast, offset, key, model):
    body = {"contents": [{"parts": [
        {"file_data": {"mime_type": "video/mp4", "file_uri": uri}},
        {"text": PROMPT.format(cast="\n".join(f"- {k}: {v}" for k, v in cast.items()),
                               offset=offset)}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 65536}}
    req = urllib.request.Request(
        f"{API}/v1beta/models/{model}:generateContent?key={key}",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=1800) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code}: {e.read().decode()[:400]}")
    usage = out.get("usageMetadata", {})
    text = "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])
    return text, usage


def parse_turns(text):
    """The reply is JSON, but not always ONE object: a fenced block, a preamble, or several
    objects in a row all happen. Decode from each `{` until one yields a turns list."""
    text = re.sub(r"```[a-z]*", "", text).strip()
    decoder = json.JSONDecoder()
    at = text.find("{")
    while at != -1:
        try:
            obj, _ = decoder.raw_decode(text[at:])
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and isinstance(obj.get("turns"), list):
            return obj["turns"]
        at = text.find("{", at + 1)
    at = text.find("[")
    if at != -1:
        try:
            arr, _ = decoder.raw_decode(text[at:])
            if isinstance(arr, list) and arr and isinstance(arr[0], dict):
                return arr
        except json.JSONDecodeError:
            pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--start", type=int, default=0, help="seconds into the episode")
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--model", default="gemini-3.8-flash")
    ap.add_argument("--out")
    a = ap.parse_args()

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY is not set")
    raw = common.raw_for_tag(a.tag)
    vid = re.search(r"video_id:\s*(\S+)", raw.read_text(encoding="utf-8")).group(1)
    cast = single.CAST.get(vid)
    if not cast:
        sys.exit(f"no cast description for {vid}; add one to verify_speakers_video.CAST first, "
                 "or every answer is a guess")

    end = a.start + int(a.minutes * 60)
    print(f"[1/4] clip {a.start}-{end}s of {vid}")
    path = clip_with_sound(vid, a.start, end)
    print(f"      {path.stat().st_size / 1e6:.0f} MB")
    print("[2/4] upload")
    uri = upload(path, key)
    print(f"[3/4] ask {a.model}")
    t0 = time.time()
    try:
        text, usage = ask(uri, cast, a.start, key, a.model)
    except SystemExit as exc:
        if "503" not in str(exc) or a.model == FALLBACK:
            raise
        print(f"      {a.model} is busy; falling back to {FALLBACK}")
        text, usage = ask(uri, cast, a.start, key, FALLBACK)
    print(f"      {time.time() - t0:.0f}s, tokens in {usage.get('promptTokenCount')}, "
          f"out {usage.get('candidatesTokenCount')}")

    turns = parse_turns(text)
    if not turns:
        sys.exit(f"no turn list in the reply. First 400 characters:\n{text[:400]}")
    out = Path(a.out or ROOT / "data" / f"_gemini_timeline_{a.tag}.rttm")
    with out.open("w", encoding="utf-8") as f:
        for t in turns:
            start, dur = a.start + float(t["start"]), float(t["end"]) - float(t["start"])
            if dur <= 0:
                continue
            who = str(t["speaker"]).replace(" ", "_")
            f.write(f"SPEAKER {vid} 1 {start:.2f} {dur:.2f} <NA> <NA> {who} <NA> <NA>\n")
    spoken = {}
    for t in turns:
        spoken[t["speaker"]] = spoken.get(t["speaker"], 0) + float(t["end"]) - float(t["start"])
    print(f"[4/4] {len(turns)} turns over {a.minutes:.0f} min -> {out}")
    print("      seconds per speaker: "
          + ", ".join(f"{k} {v:.0f}s" for k, v in sorted(spoken.items(), key=lambda x: -x[1])))
    print(f"\nscore it:\n  python scripts/score_attribution.py data/camera_ref_{a.tag}.rttm "
          f"--episode {a.tag} --blocks gemini={out}")


if __name__ == "__main__":
    main()
