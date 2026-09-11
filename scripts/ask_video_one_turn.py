"""Ask a video model who speaks ONE named turn, over a generous window around it.

WHY THIS AND NOT gemini_label_blocks.py. That one hands the model 22 blocks of a 10-minute
clip at once and asks for a name per block. Measured over 182 blocks it lands at 86%, but at
68% on turns of 4-6 words and 54% on three words or fewer -- and when it dissents from the
file the camera backs the file 2 to 1. Short turns are the only class anyone needs help with,
so that mode cannot arbitrate them.

This mode is the one that worked: `verify_speakers_video.py` settled 11 of ep62's labels by
asking about a single moment. The differences that matter are all about attention -- ONE
question per request, a window wide enough to hear the exchange either side of the turn
(default 40 s), the turn quoted verbatim with its offset inside the clip, and the neighbouring
turns supplied as context so the model knows who was talking before and after. It also has to
commit: a name, a confidence, and what it actually saw and heard.

READ THE CAUTIONS BEFORE TRUSTING AN ANSWER. A camera cut is NOT a speaker change -- the show
cuts to whoever is about to answer, which is what puts these turns on the wrong person in the
first place. And do not treat the model's account of a mouth as evidence: on ep62 at 0:05:58
its "the mouth is closed" reading was simply wrong. The answer is a vote, next to the camera's
vote and a human's ear, never a verdict on its own.

  python scripts/ask_video_one_turn.py ep57 --at 02:43 --window 40
  python scripts/ask_video_one_turn.py ep57 --turns data/_yb_turns.json --json out.json
"""
import argparse
import base64
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
import gemini_speaker_timeline as timeline  # noqa: E402
import verify_speakers_video as single  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
API = "https://generativelanguage.googleapis.com"
MODEL = "gemini-3.5-flash"      # 3.8-flash hangs rather than answering; see ARCHITECTURE.md

PROMPT = """You are watching a clip of a Malaysian political podcast recorded in one studio.

The people who can appear and speak:
{cast}

IMPORTANT: the vision mixer often cuts to the person who is ABOUT TO answer, while someone
else is still talking. So the face on screen is NOT proof of who is speaking. Use the VOICE
to decide, and use the picture only to match a voice to a person.

Here is the run of speech in this clip, in order. The turn in question is marked >>>:

{context}

The marked turn begins {offset:.0f} seconds into this clip and the words are:
  "{text}"

Who speaks those words? Reply with JSON only:
{{"speaker": "<one of the names above>",
  "confidence": "high" | "medium" | "low",
  "heard": "<one sentence on what the voice sounded like and who you matched it to>",
  "saw": "<one sentence on what was on screen while those words were spoken>"}}"""


def secs(stamp):
    parts = [int(x) for x in stamp.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def load(tag):
    raw = common.raw_for_tag(tag)
    text = raw.read_text(encoding="utf-8")
    vid = re.search(r"video_id:\s*(\S+)", text).group(1)
    turns = [{"t": secs(m.group(1)), "stamp": m.group(1), "who": m.group(2).strip(),
              "text": m.group(3)}
             for m in re.finditer(r"^\[([\d:]+)\] ([^:\n]+): (.*)$", text, re.M)]
    return vid, turns


def ask(clip, cast, context, offset, text, key, timeout):
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "video/mp4",
                         "data": base64.b64encode(clip.read_bytes()).decode()}},
        {"text": PROMPT.format(cast="\n".join(f"- {k}: {v}" for k, v in cast.items()),
                               context=context, offset=offset, text=text)}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 2048}}
    req = urllib.request.Request(
        f"{API}/v1beta/models/{MODEL}:generateContent?key={key}",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:200]}") from None
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"no answer in {timeout}s ({type(e).__name__})") from None
    body = "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])
    body = re.sub(r"```[a-z]*", "", body).strip()
    at = body.find("{")
    if at == -1:
        raise RuntimeError(f"no JSON in the reply: {body[:200]}")
    obj, _ = json.JSONDecoder().raw_decode(body[at:])
    return obj, out.get("usageMetadata", {})


def one(tag, vid, turns, cast, stamp, window, key, timeout):
    i = min(range(len(turns)), key=lambda j: abs(turns[j]["t"] - secs(stamp)))
    target = turns[i]
    start = max(0, target["t"] - window // 2)
    end = start + window
    ctx = []
    for t in turns:
        if start <= t["t"] < end:
            mark = ">>> " if t is target else "    "
            ctx.append(f"{mark}at {t['t'] - start:>3}s  {t['text'][:110]}")
    clip = timeline.clip_with_sound(vid, start, end)
    verdict, usage = ask(clip, cast, "\n".join(ctx), target["t"] - start,
                         target["text"], key, timeout)
    return {
        "stamp": target["stamp"], "words": target["text"],
        "file_says": target["who"], "model_says": verdict.get("speaker"),
        "confidence": verdict.get("confidence"), "heard": verdict.get("heard"),
        "saw": verdict.get("saw"), "clip": f"{start}-{end}s",
        "tokens_in": usage.get("promptTokenCount"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--at", action="append", default=[], help="stamp of a turn to ask about")
    ap.add_argument("--turns", help="JSON file: [{\"tag\": \"ep57\", \"at\": \"02:43\"}, ...]")
    ap.add_argument("--window", type=int, default=40, help="seconds of video around the turn")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--json")
    a = ap.parse_args()

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY is not set")
    jobs = [(a.tag, s) for s in a.at]
    if a.turns:
        jobs += [(j.get("tag", a.tag), j["at"])
                 for j in json.loads(Path(a.turns).read_text(encoding="utf-8"))]
    if not jobs:
        sys.exit("give --at or --turns")

    cache, rows = {}, []
    for tag, stamp in jobs:
        if tag not in cache:
            vid, turns = load(tag)
            cast = single.CAST.get(vid)
            if not cast:
                sys.exit(f"no cast description for {vid} ({tag}) -- add one by LOOKING at a "
                         "frame of each person in THIS episode")
            cache[tag] = (vid, turns, cast)
        vid, turns, cast = cache[tag]
        print(f"[{tag} {stamp}] asking...", flush=True)
        try:
            r = one(tag, vid, turns, cast, stamp, a.window, key, a.timeout)
        # frames_at.fetch calls sys.exit when a download fails, and YouTube fails one
        # intermittently. One bad clip must not abandon the remaining turns.
        except (RuntimeError, SystemExit) as exc:
            print(f"   FAILED {exc}")
            rows.append({"stamp": stamp, "tag": tag, "error": str(exc)})
            continue
        r["tag"] = tag
        agree = "same as file" if (r["model_says"] or "").split(" (")[0] == \
            r["file_says"].split(" (")[0] else "DIFFERS from file"
        print(f"   file={r['file_says']}  model={r['model_says']} "
              f"({r['confidence']}) -- {agree}")
        print(f"   heard: {r['heard']}")
        rows.append(r)
        time.sleep(2)

    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1, ensure_ascii=False),
                                encoding="utf-8")
        print(f"\nwrote {a.json}")


if __name__ == "__main__":
    main()
