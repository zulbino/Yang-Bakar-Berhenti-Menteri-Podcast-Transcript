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

THE 30-MINUTE CHUNK. It is DIARIZATION, not transcription, that fails on long input: 10
and 30 minutes return 200, 60 minutes returns HTTP 503 `diarization_unavailable`, and the
full 3h55m file returned an opaque 500 that was the same failure surfacing worse. Every
published ceiling (under 5 hours, 300-500 MB) said that file was fine, so the docs are no
guide here. Anything longer than one chunk is therefore cut with ffmpeg and stitched, each
chunk's start added back onto its phrase and word offsets. Two costs come with that: MAI
numbers speakers per REQUEST, so chunk 2's speaker 0 need not be chunk 1's, and a boundary
can land mid-word. Cost in money is unchanged, since billing is per hour of audio.

LEADING SILENCE KILLS A LONG REQUEST. ep62 opens with 43 seconds of digital silence
(exact zeros; the first word is at 00:44), and every request whose audio started there came
back HTTP 500 InternalServerError -- 0-1200s, 0-1790s, 0-1800s, 0-1810s, all of them, both
stream-copied and re-encoded, deterministically. The same ranges starting 15 or 30 seconds
in returned 200, and 0-600s returned 200. Proof rather than correlation: prepending 45
seconds of silence to a clip that returns 200 makes that same clip return 500. So the
opaque 500 the last session saw on the full 3h55m file was this, not the 503
`diarization_unavailable` that a 60-minute chunk gives -- two different undocumented limits
with two different errors. Each chunk therefore starts at its first sound, minus one second
of run-up, and the trimmed lead is added back onto the offsets.

Because of the first cost, a chunked run REFUSES to write raw.md. It writes
`mai_phrases.json` instead, and `reconcile_mai_speakers.py` embeds each chunk's clusters,
scores them against the cast voiceprints, and writes raw.md with the labels joined up.

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

if sys.platform == "win32":
    # A fresh shell does not inherit User-scope environment variables, and this script is
    # usually run from one, so the credentials read as unset. Same fallback as
    # verify_speaker_voiceprint.py: read them where setx actually put them.
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as _key:
            for _name in ("AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION", "AZURE_SPEECH_ENDPOINT"):
                if _name not in os.environ:
                    try:
                        os.environ[_name], _ = winreg.QueryValueEx(_key, _name)
                    except FileNotFoundError:
                        pass
    except FileNotFoundError:
        pass

ROOT = Path(__file__).resolve().parent.parent
API_VERSION = "2025-10-15"
MODEL = "MAI-Transcribe-2"          # 1.5 does NOT support Malay. Do not downgrade.
MAX_UPLOAD_BYTES = 300 * 1024 * 1024
# Above this the diarization sub-service 503s. 30 min is measured-good, 60 min is
# measured-bad, and the true ceiling is somewhere between; do not raise it on a doc page.
CHUNK_SECONDS = 30 * 60
# A long request whose audio opens with more silence than this returns HTTP 500. 28s of
# lead passed and 38s failed on a 30-minute chunk, so keep well under both.
MAX_LEAD_SILENCE = 5.0
LEAD_RUN_UP = 1.0          # keep this much silence, so a soft word onset is not clipped
SILENCE_SCAN_SECONDS = 180.0
SANDBOX = ROOT / "data"

# Below these, refuse to write. Both thresholds encode a real incident rather than taste:
# a single-speaker return is the Speechmatics silent-diarization failure, and a high
# duplicate share is the Gemini loop that emitted 35 distinct texts as 430 blocks.
MIN_SPEAKERS = 2
# Duplicates are counted only over turns of real length. MAI's granularity is one phrase
# per few seconds, so a healthy four-hour episode repeats short backchannels constantly:
# ep62 came back with 322 turns of "Hmm.", 93 of "Mm." and 29 of "Ha.", which is 34% of all
# turns and 0.0% of turns over 20 characters. Not one repeated text ran over 80 characters.
# ep61's Gemini loop, which this guard exists for, was long text: 35 distinct as 430 blocks.
MIN_DUPLICATE_CHARS = 20
MAX_DUPLICATE_SHARE = 0.25
# A loop also shows up as the same text over and over in a ROW, which a length floor would
# miss for a filler like ep56's "mmm...". Healthy output does not do this: the longest run
# of identical adjacent turns is 2 in MAI's ep62 and 1 in every current raw.md.
MAX_IDENTICAL_RUN = 4


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


def _ffprobe():
    from yt_download import _ffmpeg_location
    return Path(_ffmpeg_location()).with_name("ffprobe.exe")


def duration_of(audio_path):
    """Seconds of the FILE, not of the YouTube metadata.

    The two disagree -- ep62 is 14121 in its frontmatter and 14120.6 on disk -- and a
    chunk plan built from the smaller number silently drops the tail.
    """
    import subprocess

    out = subprocess.run([str(_ffprobe()), "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", str(audio_path)],
                         capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def leading_silence(audio_path, start):
    """Seconds of silence at `start`, measured, capped at SILENCE_SCAN_SECONDS.

    ffmpeg's silencedetect rather than a threshold of my own, and only the first window is
    decoded because that is all that matters.
    """
    import re
    import subprocess

    from yt_download import _ffmpeg_location

    proc = subprocess.run(
        [str(_ffmpeg_location()), "-hide_banner", "-ss", f"{start:.3f}",
         "-t", f"{SILENCE_SCAN_SECONDS}", "-i", str(audio_path),
         "-af", "silencedetect=noise=-50dB:d=1", "-f", "null", "-"],
        capture_output=True, text=True)
    events = re.findall(r"silence_(start|end): ([\d.]+)", proc.stderr)
    if not events or events[0][0] != "start" or float(events[0][1]) > 0.5:
        return 0.0
    for kind, value in events:
        if kind == "end":
            return float(value)
    return SILENCE_SCAN_SECONDS


def cut_chunks(audio_path, out_dir, chunk_seconds):
    """Chunks of at most `chunk_seconds`, each starting at its first sound.

    Returns [(index, start_seconds, path)] where start_seconds is where the FILE actually
    begins, which is what gets added back onto the offsets. Coverage stays contiguous: a
    chunk trimmed at the front keeps its original end, it does not slide.

    Stream copy, so no re-encode and no quality loss; mp3 frames are 26 ms, so a cut lands
    within a frame of where it was asked for. Cuts are NOT aligned to silence, which is why
    a boundary can split a word -- the alternative is a silence scan over four hours of
    audio to save a word every half hour.
    """
    import subprocess

    from yt_download import _ffmpeg_location

    total = duration_of(audio_path)
    plan = [(i, i * chunk_seconds, min(chunk_seconds, total - i * chunk_seconds))
            for i in range(max(1, -(-int(total) // chunk_seconds)))]

    chunk_dir = out_dir / "chunks"
    chunks = []
    for index, start, length in plan:
        lead = leading_silence(audio_path, start)
        trim = max(0.0, lead - LEAD_RUN_UP) if lead > MAX_LEAD_SILENCE else 0.0
        if trim >= length:
            print(f"  chunk {index} at {stamp(start * 1000)} is silent throughout, skipped")
            continue
        if trim == 0.0 and len(plan) == 1:
            chunks.append((index, 0.0, audio_path))
            continue
        if trim:
            print(f"  chunk {index}: trimming {trim:.1f}s of leading silence, which is what "
                  f"the opaque HTTP 500 is")
        chunk_dir.mkdir(parents=True, exist_ok=True)
        path = chunk_dir / f"chunk{index:02d}_{int(round(start + trim))}.mp3"
        if not path.exists():
            subprocess.run([str(_ffmpeg_location()), "-v", "error", "-y",
                            "-ss", f"{start + trim:.3f}", "-t", f"{length - trim:.3f}",
                            "-i", str(audio_path), "-c", "copy", str(path)], check=True)
        chunks.append((index, start + trim, path))
    return chunks


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
            "duration_ms": item.get("durationMilliseconds"),
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
        # Chunk is part of the identity. MAI assigns speaker numbers per request, so
        # chunk 1 speaker 0 and chunk 2 speaker 0 are two different clusters until
        # reconcile_mai_speakers.py says otherwise, and merging them here would weld two
        # people into one turn at every boundary.
        key = (item.get("chunk", 0), item["speaker"])
        end = None
        if item["offset_ms"] is not None and item.get("duration_ms") is not None:
            end = item["offset_ms"] + item["duration_ms"]
        if turns and (turns[-1]["chunk"], turns[-1]["speaker"]) == key:
            turns[-1]["text"] += " " + item["text"]
            turns[-1]["end_ms"] = end or turns[-1]["end_ms"]
            continue
        turns.append({"chunk": item.get("chunk", 0),
                      "speaker": item["speaker"],
                      "offset_ms": item["offset_ms"],
                      "end_ms": end,
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
    """What to check before believing any of it.

    Speaker counts are PER CHUNK. A chunked run that returns one speaker in one chunk has
    the Speechmatics failure in that chunk, and counting the union across chunks would
    hide it behind the other chunks' speakers.
    """
    per_chunk = {}
    for t in turns:
        if t["speaker"] is not None:
            per_chunk.setdefault(t.get("chunk", 0), set()).add(str(t["speaker"]))
    texts = [t["text"] for t in turns]
    long_texts = [t for t in texts if len(t) >= MIN_DUPLICATE_CHARS]
    distinct = len(set(long_texts))
    duplicate_share = 1 - (distinct / len(long_texts)) if long_texts else 1.0
    longest_run, run, previous = 0, 0, None
    for text in texts:
        run = run + 1 if text == previous else 1
        previous = text
        longest_run = max(longest_run, run)
    last_s = max((t["offset_ms"] or 0) for t in turns) / 1000 if turns else 0
    return {
        "turns": len(turns),
        "chunks": len(per_chunk),
        "speakers_per_chunk": {str(c): sorted(v) for c, v in sorted(per_chunk.items())},
        "speakers": sorted(set().union(*per_chunk.values())) if per_chunk else [],
        "turns_over_floor": len(long_texts),
        "distinct_texts": distinct,
        "duplicate_share": duplicate_share,
        "longest_identical_run": longest_run,
        "last_stamp_s": last_s,
        "runtime_s": runtime_s,
        "stamp_coverage": (last_s / runtime_s) if runtime_s else None,
        "chars": sum(len(t) for t in texts),
    }


def verdict(h):
    problems = []
    for chunk, speakers in h["speakers_per_chunk"].items():
        if len(speakers) < MIN_SPEAKERS:
            problems.append(
                f"chunk {chunk} has only {len(speakers)} distinct speaker(s) ({speakers}) -- "
                f"this is the Speechmatics silent-diarization failure. The transcript may "
                f"still be good; the speaker separation is not there.")
    if h["duplicate_share"] > MAX_DUPLICATE_SHARE:
        problems.append(
            f"{h['duplicate_share']:.0%} of the {h['turns_over_floor']} turns over "
            f"{MIN_DUPLICATE_CHARS} characters repeat text ({h['distinct_texts']} distinct) "
            f"-- degeneration loop, same shape as ep61's Gemini raw.")
    if h["longest_identical_run"] > MAX_IDENTICAL_RUN:
        problems.append(
            f"one text repeats {h['longest_identical_run']} times in a row -- filler loop, "
            f"same shape as ep56's 'mmm...' run.")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--audio", help="defaults to the transcoded mp3 in the sandbox")
    ap.add_argument("--out", help="sandbox dir, defaults to data/_mai_<video_id>")
    ap.add_argument("--extra-phrase", action="append", default=[],
                    help="episode-specific bias term, repeatable")
    ap.add_argument("--chunk-minutes", type=float, default=CHUNK_SECONDS / 60,
                    help="length of each request's audio; above ~30 diarization 503s")
    ap.add_argument("--dry-run", action="store_true", help="print the request, send nothing")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else SANDBOX / f"_mai_{args.video_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    audio = Path(args.audio) if args.audio else out_dir / f"{args.video_id}.64k.mono.mp3"

    phrases = bias_phrases(args.extra_phrase)
    defn = definition(phrases)

    chunk_seconds = int(args.chunk_minutes * 60)

    if args.dry_run:
        print(f"POST {endpoint()}")
        if audio.exists():
            total = duration_of(audio)
            count = max(1, -(-int(total) // chunk_seconds))
            print(f"audio {audio}  ({audio.stat().st_size/1e6:.0f} MB, {total/60:.0f} min)")
            print(f"{count} chunk(s) of {chunk_seconds/60:g} min, "
                  f"about ${total/3600*0.10:.2f} at $0.10 per hour of audio")
        else:
            print(f"audio {audio}  MISSING")
        print(json.dumps(defn, ensure_ascii=False, indent=2)[:1200])
        print(f"\n{len(phrases)} bias phrases")
        return

    if not audio.exists():
        sys.exit(f"{audio} not found")

    chunks = cut_chunks(audio, out_dir, chunk_seconds)
    print(f"{len(chunks)} chunk(s) of {chunk_seconds/60:g} min")

    items, responses = [], []
    for index, start, path in chunks:
        name = "mai_response.json" if len(chunks) == 1 else f"mai_response_{index:02d}.json"
        raw_json = out_dir / name
        if raw_json.exists():
            # Already paid for. A run that dies on chunk 6 must not re-buy chunks 0 to 5.
            payload = json.loads(raw_json.read_text(encoding="utf-8"))
            start = payload.get("_chunk_start_s", start)
            print(f"  chunk {index}: reusing {raw_json.name}")
        else:
            payload = submit(path, defn)
            payload["_chunk_start_s"] = start
            raw_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        responses.append(raw_json)

        got = phrases_of(payload)
        if not got:
            sys.exit(f"chunk {index}: no phrases parsed -- inspect {raw_json} and widen "
                     f"phrases_of()")
        shift = int(round(start * 1000))
        for item in got:
            item["chunk"] = index
            if item["duration_ms"] is None and item["words"]:
                last = item["words"][-1]
                if (last.get("offsetMilliseconds") is not None
                        and item["offset_ms"] is not None):
                    item["duration_ms"] = (last["offsetMilliseconds"]
                                           + (last.get("durationMilliseconds") or 0)
                                           - item["offset_ms"])
            if item["offset_ms"] is not None:
                item["offset_ms"] += shift
            for word in item["words"]:
                if word.get("offsetMilliseconds") is not None:
                    word["offsetMilliseconds"] += shift
            items.append(item)
        speakers = sorted({str(i["speaker"]) for i in got})
        print(f"  chunk {index} at {stamp(shift)}: {len(got)} phrases, speakers {speakers}")

    turns = merge_turns(items)

    import transcribe_episode as T

    episode = T.load_episode(args.video_id)
    h = health(turns, episode["duration_seconds"])
    (out_dir / "health.json").write_text(json.dumps(h, indent=2), encoding="utf-8")

    print(f"\n  turns {h['turns']}  chunks {h['chunks']}  chars {h['chars']:,}")
    for chunk, speakers in h["speakers_per_chunk"].items():
        print(f"  chunk {chunk} speakers {speakers}")
    print(f"  turns over {MIN_DUPLICATE_CHARS} chars {h['turns_over_floor']}  distinct "
          f"{h['distinct_texts']}  duplicate share {h['duplicate_share']:.1%}  longest "
          f"identical run {h['longest_identical_run']}")
    if h["stamp_coverage"] is not None:
        print(f"  last stamp {h['last_stamp_s']:.0f}s of {h['runtime_s']}s "
              f"({h['stamp_coverage']:.1%})")

    problems = verdict(h)
    if problems:
        print("\nREFUSING to write raw.md:")
        for p in problems:
            print(f"  - {p}")
        kept = ", ".join(str(r) for r in responses)
        print(f"\nThe response(s) are kept at {kept}, so nothing needs re-paying.")
        sys.exit(1)

    phrases_path = out_dir / "mai_phrases.json"
    phrases_path.write_text(json.dumps({
        "video_id": args.video_id,
        "audio": str(audio),
        "chunk_seconds": chunk_seconds,
        "chunks": [{"index": i, "start_s": start, "path": str(path)}
                   for i, start, path in chunks],
        "turns": turns,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {phrases_path}")

    if len(chunks) > 1:
        # Speaker numbers are per request, so "Speaker 1" would mean a different person in
        # every chunk. Writing that file would file eight people's words under two labels,
        # and every checker in the repo would read it as fine.
        print(f"\n{len(chunks)} chunks, so the speaker numbers are NOT comparable across "
              f"them and raw.md is not written here. Next:")
        print(f"  python scripts/reconcile_mai_speakers.py {args.video_id} --out {out_dir}")
        return

    body = ["# Raw Transcript", ""]
    for t in turns:
        label = t["speaker"] if t["speaker"] is not None else "Speaker ?"
        # MAI numbers speakers from 0; this corpus numbers from 1, and every checker and
        # relabel command in the repo is written against "Speaker 1" upward.
        if str(label).isdigit():
            label = f"Speaker {int(label) + 1}"
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
