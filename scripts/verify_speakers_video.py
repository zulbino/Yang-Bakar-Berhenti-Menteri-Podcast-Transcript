"""Ask Gemini who is speaking, from the VIDEO AND AUDIO of a short clip.

HOW THIS DIFFERS FROM THE TWO CHECKS ALREADY HERE. `verify_speakers.py` sends audio only, so
it can hear a voice change but cannot see who is on screen. `frames_at.py` renders frames, so
it can see the cut but hears nothing, and a human has to read the contact sheet. This muxes
the downloaded video with the local audio and asks a model to watch and listen, which is the
same evidence a person uses and is cheap enough to run over a list of disputed turns.

WHY IT WORKS ON THIS SHOW. The camera cuts to whoever is talking, so the shot is direct
evidence (ENGINEERING_LOG 1.35). Two cautions carry over unchanged: the cut LAGS the speech
by about two seconds, so a clip must start before the turn does, and a two-shot or a
full-screen graphic proves nothing.

WHY THE PEOPLE ARE DESCRIBED BY CLOTHING. The model has no voiceprints and no cast list. It
is given what a viewer would use -- who is wearing what, and where they sit -- taken from
frames already confirmed against turns both transcripts agree on. Get those descriptions
wrong and every answer is wrong, so they are per episode and written down here rather than
guessed at call time.

READ THE ANSWER, NOT THE LABEL. The model returns its reasoning and a confidence; a
low-confidence answer on a two-second interjection means the camera never cut, which is a
real outcome and not a failure. This is evidence for a human decision, the same as the
contact sheets.
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform == "win32":
    import winreg
    if "GEMINI_API_KEY" not in os.environ:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as _k:
                os.environ["GEMINI_API_KEY"] = winreg.QueryValueEx(_k, "GEMINI_API_KEY")[0]
        except FileNotFoundError:
            pass

import requests  # noqa: E402

import frames_at  # noqa: E402
from yt_download import _ffmpeg_location  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "_speaker_video"
MODEL = "gemini-3.8-flash"
LEAD_SECONDS = 4       # the cut lags the speech; start before the turn
TAIL_SECONDS = 10

# Per episode, from frames already confirmed against turns both transcripts agree on.
CAST = {
    "0M5hweswMpE": {
        "Rafizi": "an older man in a black shirt with glasses, sitting in a high-backed "
                  "chair with a leafy plant behind him, a white mug and a tablet on the desk",
        "Haziq": "a man in a light blue shirt with glasses and a laptop in front of him, a "
                 "framed picture on the wall behind",
        "Farhan (Pa'an)": "a younger man with short spiky hair in a black hoodie with a "
                          "white '97' logo on the chest, against a plain dark wall, no laptop",
    },
}


def clip(video_id, start, end):
    """Downloaded video for [start, end) with the local audio muxed in."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{video_id}_{start}_{end}.mp4"
    if out.exists():
        return out
    video = frames_at.fetch(video_id, start, end)
    audio = ROOT / "audio" / f"{video_id}.m4a"
    if not audio.exists():
        raise SystemExit(f"{audio} not found -- yt_download.py puts it there")
    subprocess.run([str(_ffmpeg_location()), "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(video), "-ss", str(start), "-t", str(end - start),
                    "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-shortest", str(out)], check=True)
    return out


def ask(path, cast, said):
    people = "\n".join(f"- {name}: {look}" for name, look in cast.items())
    prompt = f"""This is a clip from a Malaysian podcast. Three people are in the room and the
camera cuts to whoever is speaking, about two seconds after they start.

The people:
{people}

In this clip somebody says, roughly: "{said}"

Watch and listen, then answer as JSON only:
{{"speaker": "<one of: {', '.join(cast)}, or unclear>",
  "confidence": "<high|medium|low>",
  "seen": "<who is on camera, and whether their mouth is moving>",
  "why": "<one sentence>"}}

Answer "unclear" if the camera never cuts to the person speaking, if the shot holds two
people, or if a graphic covers the screen. Do not guess from the content of what is said --
judge from who is on camera speaking and from the voice."""
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "video/mp4",
                         "data": base64.b64encode(path.read_bytes()).decode()}},
        {"text": prompt}]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 8192}}
    # 503 "high demand" is common on the free tier and clears on its own; a clip already
    # downloaded is wasted if one transient refusal ends the run.
    import time as _time
    for attempt in range(4):
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, json=body, timeout=600)
        if r.status_code < 300:
            break
        if r.status_code not in (429, 500, 503) or attempt == 3:
            raise RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")
        _time.sleep(15 * (attempt + 1))
    candidate = r.json()["candidates"][0]
    parts = candidate.get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError(f"no parts, finishReason={candidate.get('finishReason')}")
    text = "".join(p.get("text", "") for p in parts)
    match = re.search(r"\{.*\}", text, re.S)
    return json.loads(match.group(0)) if match else {"speaker": "unparsed", "why": text[:200]}


def seconds(stamp):
    parts = [int(p) for p in stamp.split(":")]
    return parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--candidates", required=True,
                    help="json list with at least: at, local, mai, head")
    ap.add_argument("--out", default="data/_speaker_video_verdicts.json")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    cast = CAST.get(args.video_id)
    if not cast:
        sys.exit(f"no cast description for {args.video_id} -- add one to CAST first, or every "
                 f"answer is a guess")
    rows = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
    if args.limit:
        rows = rows[:args.limit]

    verdicts = []
    for row in rows:
        start = max(0, seconds(row["at"]) - LEAD_SECONDS)
        end = start + LEAD_SECONDS + TAIL_SECONDS
        try:
            path = clip(args.video_id, start, end)
            answer = ask(path, cast, row.get("head", "")[:120])
        except Exception as exc:
            print(f"  {row['at']:9} FAILED {str(exc)[:110]}")
            continue
        agrees = ("local" if answer["speaker"] == row.get("local")
                  else "MAI" if answer["speaker"] == row.get("mai") else "neither")
        verdicts.append({**row, "gemini": answer, "agrees_with": agrees})
        print(f"  {row['at']:9} local={row.get('local','?'):16} mai={row.get('mai','?'):16} "
              f"-> {answer['speaker']:16} ({answer.get('confidence','?')}) agrees with {agrees}")
        print(f"            seen: {answer.get('seen','')[:100]}")
    Path(args.out).write_text(json.dumps(verdicts, indent=1, ensure_ascii=False),
                              encoding="utf-8")
    print(f"\nwrote {args.out}")
    tally = {}
    for v in verdicts:
        tally[v["agrees_with"]] = tally.get(v["agrees_with"], 0) + 1
    print(f"agreement: {tally}")


if __name__ == "__main__":
    main()
