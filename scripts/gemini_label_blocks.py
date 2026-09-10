"""Ask Gemini WHO speaks in blocks we already have, never WHEN a turn starts.

WHY THIS SHAPE AND NOT THE OTHER ONE. `gemini_speaker_timeline.py` asks the same model to
watch a stretch and write down every turn itself. On ep62 that returned 22 turns covering
1,000 seconds of a 600-second clip and gave Rafizi 956 of them: a video model does not know
when things happen. This file asks only the question it answers well. MAI already timed
every word, so the boundaries are known; each block goes to the model as a clip-relative
start time plus its first words, and the model returns one name per block.

MEASURED, AND IT DOES NOT REPLACE THE CAMERA PASS. 182 blocks, five episodes with a camera
reference, three 10-minute windows each: 86% agreement with raw.md and 80% with the camera.
The split by block length is the whole story, and it is the wrong way round for us:

    20+ words   96%        7-19 words  93%
    4-6 words   68%        <=3 words   54%

Long turns never needed help -- MAI and the camera already agree on them. Short turns are
where the camera is weakest and where every open speaker question in this repo lives, and
there the model is a coin flip. When it disagrees with raw.md, the camera backs raw.md 12
times and the model 6. An earlier guess that the disagreements were really BAD BLOCK CUTS
did not survive the split either: blocks the camera says hold one speaker throughout score
88%, mixed blocks 84%. It is length, not purity.

So use this the way `verify_speakers_video.py` is used -- one named window, one disputed
label, with a human or the camera holding the other end. Do not label a corpus with it.
Numbers and method in `data/gemini_label_blocks_measured.txt`.

WHAT THE NUMBERS ARE SCORED AGAINST. Agreement is not truth. Every block is compared twice:
against the label raw.md carries, and against the camera reference's own majority over the
block's span.

THE CAST DESCRIPTIONS ARE THE WHOLE GAME. The model gets no cast list and no voiceprints,
only `verify_speakers_video.CAST`: who wears what, and where they sit. Write those by looking
at a frame of each person in THAT episode, never from another episode's clothes.

THREE THINGS THAT DO NOT WORK, all paid for once already. The Files API answers "the file
failed to be processed" for these clips even at 9 MB of clean H.264/AAC, so the clip goes
inline and a chunk must stay under 20 MB. A clip built by `verify_speakers_video.clip()` has
no audio stream, and the audio is what tells one voice from another. And do not mine the
model's prose about what it saw: on ep62 its "the mouth is closed" reading was wrong.

  python scripts/gemini_label_blocks.py ep62 --start 3600 --minutes 10
  python scripts/gemini_label_blocks.py ep61 --start 600 --minutes 10 --json out.json
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
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import gemini_speaker_timeline as timeline  # noqa: E402
import verify_speakers_video as single  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
API = "https://generativelanguage.googleapis.com"
FALLBACK = "gemini-3.5-flash"          # 3.8-flash hangs; 3.5 answers a window in 12-34 s
INLINE_CAP = 20_000_000                # the documented inline request limit

PROMPT = """You are watching a clip of a Malaysian political podcast recorded in one studio.
The vision mixer cuts to whoever is speaking, but often about two seconds late, and it also
cuts to the person who is ABOUT TO answer. Trust what you hear over what you see.

The people you can see and hear:
{cast}

Below are {n} numbered stretches of speech from this clip, each with the second it begins at
(counted from the start of the clip) and the words spoken in it. For each one, say which
person speaks it. Listen to the voice in that second of the clip. If two people speak inside
one stretch, name the one who speaks most of it.

{blocks}

Reply with JSON only, no prose, one entry per stretch:
{{"labels": [{{"n": 1, "speaker": "<one of the names above>"}}]}}"""


def secs(stamp):
    """[02:43] and [3:29:27] both appear in these files."""
    parts = [int(x) for x in stamp.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def blocks_of(tag):
    raw = common.raw_for_tag(tag)
    text = raw.read_text(encoding="utf-8")
    vid = re.search(r"video_id:\s*(\S+)", text).group(1)
    out = []
    for m in re.finditer(r"^\[([\d:]+)\] ([^:\n]+): (.*)$", text, re.M):
        out.append({"t": secs(m.group(1)), "stamp": m.group(1),
                    "speaker": m.group(2).strip(), "text": m.group(3)})
    return vid, out


def camera_majority(tag, start, end):
    """Which name holds most of [start, end) in the camera reference, and how much of it."""
    ref = ROOT / "data" / f"camera_ref_{tag}.rttm"
    if not ref.exists():
        return None
    held = Counter()
    for line in ref.read_text(encoding="utf-8").splitlines():
        p = line.split()
        if len(p) < 8 or p[0] != "SPEAKER":
            continue
        s, d, who = float(p[3]), float(p[4]), p[7].replace("_", " ")
        overlap = min(end, s + d) - max(start, s)
        if overlap > 0:
            held[who] += overlap
    if not held:
        return None
    who, secs_held = held.most_common(1)[0]
    return who, secs_held / max(end - start, 0.01)


def ask(clip, cast, listing, key, model, timeout):
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "video/mp4",
                         "data": base64.b64encode(clip.read_bytes()).decode()}},
        {"text": PROMPT.format(cast="\n".join(f"- {k}: {v}" for k, v in cast.items()),
                               n=len(listing), blocks="\n".join(listing))}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 65536}}
    req = urllib.request.Request(
        f"{API}/v1beta/models/{model}:generateContent?key={key}",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:300]}") from None
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        # 3.8-flash stopped answering at all on 2026-09-10 -- a one-word text prompt timed
        # out at 90 s while 3.5-flash replied in 22 s. It hangs, it does not return 503, so
        # a 503-only fallback waits out the whole timeout on every window.
        raise RuntimeError(f"no answer in {timeout}s ({type(e).__name__})") from None
    text = "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])
    return text, out.get("usageMetadata", {})


def parse_labels(text):
    """Same defence as timeline.parse_turns: fences, preambles and several objects in a row."""
    text = re.sub(r"```[a-z]*", "", text).strip()
    decoder = json.JSONDecoder()
    at = text.find("{")
    while at != -1:
        try:
            obj, _ = decoder.raw_decode(text[at:])
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and isinstance(obj.get("labels"), list):
            return obj["labels"]
        at = text.find("{", at + 1)
    return None


def one_window(tag, vid, cast, window, start, end, key, model, words, timeout):
    listing = [f"{i + 1}. at {b['t'] - start}s: {' '.join(b['text'].split()[:words])}"
               for i, b in enumerate(window)]
    clip = timeline.clip_with_sound(vid, start, end)
    size = clip.stat().st_size
    if size > INLINE_CAP:
        raise RuntimeError(f"clip is {size / 1e6:.0f} MB, over the {INLINE_CAP / 1e6:.0f} MB "
                           "inline cap -- use a shorter --minutes")
    t0 = time.time()
    try:
        text, usage = ask(clip, cast, listing, key, model, timeout)
        used = model
    except RuntimeError as exc:
        if ("503" not in str(exc) and "no answer" not in str(exc)) or model == FALLBACK:
            raise
        print(f"      {model}: {exc}; falling back to {FALLBACK}")
        text, usage = ask(clip, cast, listing, key, FALLBACK, timeout)
        used = FALLBACK
    labels = parse_labels(text)
    if not labels:
        raise RuntimeError(f"no label list in the reply. First 300 chars:\n{text[:300]}")
    by_n = {int(x["n"]): str(x["speaker"]).strip() for x in labels if "n" in x}
    print(f"      {used}, {time.time() - t0:.0f}s, tokens in "
          f"{usage.get('promptTokenCount')}, {len(by_n)}/{len(window)} answered")
    return by_n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--start", type=int, default=0, help="seconds into the episode")
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--chunks", type=int, default=1, help="consecutive windows to label")
    ap.add_argument("--model", default="gemini-3.8-flash")
    ap.add_argument("--words", type=int, default=14, help="words of each block to quote")
    ap.add_argument("--timeout", type=int, default=420, help="seconds to wait per window")
    ap.add_argument("--json", help="write the per-block verdicts here")
    a = ap.parse_args()

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY is not set")
    vid, blocks = blocks_of(a.tag)
    cast = single.CAST.get(vid)
    if not cast:
        sys.exit(f"no cast description for {vid} ({a.tag}); add one to "
                 "verify_speakers_video.CAST by LOOKING at a frame of each person in this "
                 "episode, or every label is a guess")

    span = int(a.minutes * 60)
    rows, missing = [], 0
    for c in range(a.chunks):
        start = a.start + c * span
        end = start + span
        window = [b for b in blocks if start <= b["t"] < end]
        if not window:
            print(f"[{c + 1}/{a.chunks}] {start}-{end}s: no blocks, skipped")
            continue
        print(f"[{c + 1}/{a.chunks}] {start}-{end}s: {len(window)} blocks")
        try:
            by_n = one_window(a.tag, vid, cast, window, start, end, key, a.model,
                              a.words, a.timeout)
        except RuntimeError as exc:
            print(f"      FAILED {exc}")
            continue
        for i, b in enumerate(window):
            got = by_n.get(i + 1)
            if got is None:
                missing += 1
                continue
            nxt = window[i + 1]["t"] if i + 1 < len(window) else end
            cam = camera_majority(a.tag, b["t"], min(nxt, end))
            rows.append({"stamp": b["stamp"], "t": b["t"], "file": b["speaker"],
                         "gemini": got, "camera": cam[0] if cam else None,
                         "camera_share": round(cam[1], 2) if cam else None,
                         "words": len(b["text"].split()), "text": b["text"][:120]})

    if not rows:
        sys.exit("nothing labelled")
    same = lambda x, y: x is not None and y is not None and x.split(" (")[0] == y.split(" (")[0]
    vs_file = [r for r in rows if same(r["gemini"], r["file"])]
    withcam = [r for r in rows if r["camera"]]
    vs_cam = [r for r in withcam if same(r["gemini"], r["camera"])]
    print(f"\n{len(rows)} blocks labelled, {missing} left unanswered by the model")
    print(f"  agrees with raw.md          {len(vs_file)}/{len(rows)} "
          f"({100 * len(vs_file) / len(rows):.0f}%)")
    if withcam:
        print(f"  agrees with the camera      {len(vs_cam)}/{len(withcam)} "
              f"({100 * len(vs_cam) / len(withcam):.0f}%)")
    short = [r for r in rows if r["words"] <= 6]
    if short:
        ok = [r for r in short if same(r["gemini"], r["file"])]
        print(f"  of those, blocks <=6 words  {len(ok)}/{len(short)} agree with raw.md "
              "-- the class the camera is weakest on")
    conf = defaultdict(Counter)
    for r in rows:
        conf[r["file"]][r["gemini"]] += 1
    print("  raw.md label -> what the model said:")
    for who, got in sorted(conf.items()):
        print(f"    {who:18} {dict(got)}")
    print("\n  every block the model reads differently from raw.md:")
    for r in rows:
        if not same(r["gemini"], r["file"]):
            print(f"    [{r['stamp']}] raw={r['file']:16} gemini={r['gemini']:16} "
                  f"camera={r['camera']} {r['camera_share']} ({r['words']}w) {r['text'][:70]}")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"\nwrote {a.json}")


if __name__ == "__main__":
    main()
