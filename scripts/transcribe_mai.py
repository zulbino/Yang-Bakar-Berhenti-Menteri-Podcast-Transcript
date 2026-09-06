"""Transcribe an episode with Microsoft MAI-Transcribe-2 via the Azure Speech REST API.

WHY THIS EXISTS. The pipeline's own ASR (mesolitica/malaysian-whisper-medium-v2 plus
pyannote) has three standing weaknesses that MAI-Transcribe-2 addresses in one pass:

1. **Proper nouns.** `fix_proper_nouns.py` now carries 48 patterns repairing names AFTER
   transcription. MAI takes a `phraseList`, so the owner-confirmed spellings go in as bias
   terms and the names come out right at source. The list is BUILT FROM that same reviewed
   map -- see `bias_phrases()`, and note the terms are hints, not forced output.
2. **Timestamp drift.** 159 of ep61's 203 block stamps sat more than 10s from their own
   words, which is how an owner-confirmed Farhan turn got destroyed. MAI returns
   `offsetMilliseconds` per WORD, so a block's stamp is derived from its first word rather
   than from a chunk boundary.
3. **Diarization.** Malay is supported on MAI-Transcribe-2 and NOT on 1.5, so the model
   string below is load-bearing.

WHAT THIS DOES NOT DO. It writes into a sandbox directory, never over `episodes/`. A
re-transcribe in place wipes hand edits and resets speaker labels to `Speaker N` -- that
already cost ep25 its speaker review, and ep61 now carries ten owner decisions that exist
nowhere else in the corpus.

THE GUARD THAT MATTERS. Speechmatics' diarization died silently in August 2026: every
submission came back with all items under one speaker while the API reported
`status: done, errors: None` and echoed the accepted diarization config back. A perfectly
good transcript with no speaker separation in it. So this script reads the DISTINCT SPEAKER
COUNT and the duplicate-text share, and refuses to write raw.md when either looks wrong.
Never judge a fresh transcript by its job status or its last timestamp.

Setup:

    # Create a Microsoft Foundry resource for Speech in the Azure portal, then:
    export AZURE_SPEECH_KEY=<resource key>
    export AZURE_SPEECH_REGION=<region>          # or AZURE_SPEECH_ENDPOINT=<full host>

    python scripts/transcribe_mai.py 0M5hweswMpE --dry-run   # print the request, send nothing
    python scripts/transcribe_mai.py 0M5hweswMpE
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
API_VERSION = "2025-10-15"
MODEL = "MAI-Transcribe-2"          # 1.5 does NOT support Malay. Do not downgrade.
MAX_UPLOAD_BYTES = 300 * 1024 * 1024
SANDBOX = ROOT / "data"

# Below these, refuse to write. Both thresholds encode a real incident rather than taste:
# a single-speaker return is the Speechmatics silent-diarization failure, and a high
# duplicate share is the Gemini loop that emitted 35 distinct texts as 430 blocks.
MIN_SPEAKERS = 2
MAX_DUPLICATE_SHARE = 0.25


def bias_phrases(extra=()):
    """Owner-confirmed spellings from the reviewed correction map, plus the cast.

    Takes the REPLACEMENTS, not the patterns: those are the strings the owner confirmed.
    """
    import fix_proper_nouns as F

    phrases = ["Rafizi Ramli", "Rafizi", "Haziq", "Farhan",
               "Yang Bakar Menteri", "Yang Berhenti Menteri", "YBM"]
    for _, replacement, _ in F.CORRECTIONS:
        # A bias term has to be a NAME. The map also holds whole-phrase repairs -- "Water
        # assets through WASIA", "Kan keychain ada pakai" -- and biasing recognition toward
        # a full sentence would push the model to hear that sentence. So require every word
        # to be capitalised, which is what separates a proper noun from a fragment.
        words = replacement.split()
        if words and all(w[:1].isupper() for w in words):
            phrases.append(replacement)
    for term in extra:
        phrases.append(term)

    seen, out = set(), []
    for p in phrases:
        if p.lower() not in seen:
            seen.add(p.lower())
            out.append(p)
    return out


def definition(phrases):
    return {
        "enhancedMode": {
            "enabled": True,
            "model": MODEL,
            "modelOptions": {
                # raw.md keeps the fillers -- "clean" is for the published rewrite, which
                # is a separate stage with its own gate.
                "transcribeStyle": "verbatim",
                "timestamps": "word",
            },
        },
        "diarization": {"enabled": True},
        "phraseList": {"phrases": phrases},
        # `locales` is deliberately UNSET. The docs call it a very strong hint and warn
        # against it unless you are certain of a single language; these episodes
        # code-switch Malay and English mid-sentence, so auto-detection is the point.
    }


def endpoint():
    host = os.environ.get("AZURE_SPEECH_ENDPOINT")
    if not host:
        region = os.environ.get("AZURE_SPEECH_REGION")
        if not region:
            sys.exit("set AZURE_SPEECH_ENDPOINT, or AZURE_SPEECH_REGION")
        host = f"https://{region}.api.cognitive.microsoft.com"
    host = host.rstrip("/")
    return f"{host}/speechtotext/transcriptions:transcribe?api-version={API_VERSION}"


def submit(audio_path, defn):
    import requests

    key = os.environ.get("AZURE_SPEECH_KEY")
    if not key:
        sys.exit("set AZURE_SPEECH_KEY")
    size = audio_path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        sys.exit(f"{audio_path.name} is {size/1e6:.0f} MB, over the {MAX_UPLOAD_BYTES/1e6:.0f} MB "
                 f"cap -- transcode to 64kbps mono mp3 first")

    with audio_path.open("rb") as fh:
        response = requests.post(
            endpoint(),
            headers={"Ocp-Apim-Subscription-Key": key},
            files={"audio": (audio_path.name, fh, "audio/mpeg")},
            data={"definition": json.dumps(defn)},
            timeout=60 * 60,
        )
    if response.status_code >= 300:
        sys.exit(f"HTTP {response.status_code}: {response.text[:2000]}")
    return response.json()


def phrases_of(payload):
    """Pull speaker-attributed phrases out of the response, tolerantly.

    The exact shape is not pinned down in the docs, so accept the documented Fast
    Transcription layout and a couple of plausible variants rather than crashing on a
    key name. The full payload is always saved, so a shape surprise costs no second call.
    """
    for key in ("phrases", "segments", "results"):
        items = payload.get(key)
        if isinstance(items, list) and items:
            break
    else:
        return []

    out = []
    for item in items:
        text = (item.get("text") or item.get("display") or "").strip()
        if not text:
            continue
        offset = item.get("offsetMilliseconds")
        if offset is None:
            words = item.get("words") or []
            offset = words[0].get("offsetMilliseconds") if words else None
        speaker = item.get("speaker", item.get("speakerId"))
        out.append({
            "speaker": speaker,
            "offset_ms": offset,
            "text": text,
            "words": item.get("words") or [],
        })
    return out


def merge_turns(items):
    """One block per speaker turn, stamped from its own FIRST WORD.

    Consecutive phrases from one speaker are one turn. The stamp comes from word timings
    rather than a chunk boundary, which is the drift this whole exercise is meant to remove.
    """
    turns = []
    for item in items:
        if turns and turns[-1]["speaker"] == item["speaker"]:
            turns[-1]["text"] += " " + item["text"]
            continue
        turns.append({"speaker": item["speaker"],
                      "offset_ms": item["offset_ms"],
                      "text": item["text"]})
    return turns


def stamp(ms):
    if ms is None:
        return "[00:00]"
    total = int(ms // 1000)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"[{h}:{m:02d}:{s:02d}]" if h else f"[{m:02d}:{s:02d}]"


def health(turns, runtime_s):
    """What to check before believing any of it."""
    speakers = {t["speaker"] for t in turns if t["speaker"] is not None}
    texts = [t["text"] for t in turns]
    distinct = len(set(texts))
    duplicate_share = 1 - (distinct / len(texts)) if texts else 1.0
    last_s = max((t["offset_ms"] or 0) for t in turns) / 1000 if turns else 0
    return {
        "turns": len(turns),
        "speakers": sorted(str(s) for s in speakers),
        "distinct_texts": distinct,
        "duplicate_share": duplicate_share,
        "last_stamp_s": last_s,
        "runtime_s": runtime_s,
        "stamp_coverage": (last_s / runtime_s) if runtime_s else None,
        "chars": sum(len(t) for t in texts),
    }


def verdict(h):
    problems = []
    if len(h["speakers"]) < MIN_SPEAKERS:
        problems.append(
            f"only {len(h['speakers'])} distinct speaker(s) ({h['speakers']}) -- this is the "
            f"Speechmatics silent-diarization failure. The transcript may still be good; the "
            f"speaker separation is not there.")
    if h["duplicate_share"] > MAX_DUPLICATE_SHARE:
        problems.append(
            f"{h['duplicate_share']:.0%} of turns repeat text ({h['distinct_texts']} distinct "
            f"of {h['turns']}) -- degeneration loop, same shape as ep61's Gemini raw.")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--audio", help="defaults to the transcoded mp3 in the sandbox")
    ap.add_argument("--out", help="sandbox dir, defaults to data/_mai_<video_id>")
    ap.add_argument("--extra-phrase", action="append", default=[],
                    help="episode-specific bias term, repeatable")
    ap.add_argument("--dry-run", action="store_true", help="print the request, send nothing")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else SANDBOX / f"_mai_{args.video_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    audio = Path(args.audio) if args.audio else out_dir / f"{args.video_id}.64k.mono.mp3"

    phrases = bias_phrases(args.extra_phrase)
    defn = definition(phrases)

    if args.dry_run:
        print(f"POST {endpoint()}")
        print(f"audio {audio}  ({audio.stat().st_size/1e6:.0f} MB)" if audio.exists()
              else f"audio {audio}  MISSING")
        print(json.dumps(defn, ensure_ascii=False, indent=2)[:1200])
        print(f"\n{len(phrases)} bias phrases")
        return

    if not audio.exists():
        sys.exit(f"{audio} not found")

    payload = submit(audio, defn)
    raw_json = out_dir / "mai_response.json"
    raw_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {raw_json}")

    items = phrases_of(payload)
    if not items:
        sys.exit(f"no phrases parsed -- inspect {raw_json} and widen phrases_of()")
    turns = merge_turns(items)

    import transcribe_episode as T

    episode = T.load_episode(args.video_id)
    h = health(turns, episode["duration_seconds"])
    (out_dir / "health.json").write_text(json.dumps(h, indent=2), encoding="utf-8")

    print(f"\n  turns {h['turns']}  speakers {h['speakers']}  chars {h['chars']:,}")
    print(f"  distinct texts {h['distinct_texts']}  duplicate share {h['duplicate_share']:.1%}")
    if h["stamp_coverage"] is not None:
        print(f"  last stamp {h['last_stamp_s']:.0f}s of {h['runtime_s']}s "
              f"({h['stamp_coverage']:.1%})")

    problems = verdict(h)
    if problems:
        print("\nREFUSING to write raw.md:")
        for p in problems:
            print(f"  - {p}")
        print(f"\nThe response is kept at {raw_json}, so nothing needs re-paying.")
        sys.exit(1)

    body = ["# Raw Transcript", ""]
    for t in turns:
        label = t["speaker"] if t["speaker"] is not None else "Speaker ?"
        if str(label).isdigit():
            label = f"Speaker {label}"
        body.append(f"{stamp(t['offset_ms'])} {label}: {t['text']}")
        body.append("")

    fields = {
        **T.episode_common_fields(episode),
        "model": f"microsoft/{MODEL}",
        "note": (f"Raw transcript from {MODEL} via the Azure Speech API, verbatim style, with "
                 f"speaker diarization and word-level timestamps from the model itself rather "
                 f"than from chunk boundaries. Block stamps are taken from each turn's first "
                 f"word. {len(phrases)} keyword-bias phrases were supplied from the "
                 f"owner-reviewed proper-noun map. Speaker labels are the model's own and are "
                 f"NOT yet mapped to real names."),
    }
    raw_md = out_dir / "raw.md"
    raw_md.write_text(common.frontmatter_md(fields, "\n".join(body)), encoding="utf-8")
    print(f"\nwrote {raw_md}")
    print("SANDBOX ONLY. Compare it against the current pipeline before it goes near episodes/.")


if __name__ == "__main__":
    main()
