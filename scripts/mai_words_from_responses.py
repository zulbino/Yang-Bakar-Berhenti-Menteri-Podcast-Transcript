"""Recover MAI's phrase and word timings from the responses already on disk. No network.

WHAT WAS LOST AND WHERE IT STILL IS. `transcribe_mai.py` writes two things per episode: the
raw API responses, `mai_response_NN.json`, and a digest, `mai_phrases.json`. The digest's
`turns` come from MAI's diarization, so on a run made WITHOUT diarization there is one turn
per 30-minute chunk. 68 of the 69 episodes are in that state: 4 to 8 turns each, every
`speaker` null. Only ep62 (0M5hweswMpE) has a granular digest, 1,669 turns, because its run
asked for diarization.

The detail was never actually lost. Each response carries a `phrases` list -- 2,584 of them
for ep33 -- and every phrase carries `offsetMilliseconds`, `durationMilliseconds` and a
`words` list with per-word offsets. Across the corpus that is 121,021 phrases and 1,323,667
word timings sitting unread. This reads them back out.

WHY IT MATTERS. `corpus_status.py` reports "MAI words 69" and that counts runs that EXIST,
not runs that are usable. The ep62 recipe is "MAI words + camera labels": the camera says
who and MAI says exactly when each word was spoken. Believing only ep62 had word times made
the Azure credit expiry (~2026-10-07) look like a deadline for the whole corpus. It is not:
every episode's word times are already paid for and on disk.

WHAT THIS DOES NOT DO. It does not invent speakers. 68 of the 69 responses have no speaker
field at all, so every recovered turn is written with `speaker: null` and naming stays the
camera's job. It also does not touch `mai_phrases.json`, because `reconcile_mai_speakers.py`
reads that file and expects diarized turns; the output goes to `mai_words.json` beside it so
nothing downstream changes until a caller opts in.

Offsets are made ABSOLUTE. A phrase's `offsetMilliseconds` is relative to its own chunk, and
the chunk's own start is in `_chunk_start_s`. Adding them is the whole conversion, and
getting it wrong would shift a whole 30-minute chunk -- the same class of error as ep40's
170-second clock drift, but silent, because the numbers would still look like timestamps.

  python scripts/mai_words_from_responses.py                # every episode, dry run
  python scripts/mai_words_from_responses.py --write
  python scripts/mai_words_from_responses.py ep33 --write
"""
import argparse
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import common  # noqa: E402


def video_id_for(tag):
    raw = common.raw_for_tag(tag)
    head = raw.read_text(encoding="utf-8")[:2000]
    m = re.search(r"(?:video_id|youtube_id|url|source)\s*:\s*(\S+)", head)
    return re.search(r"([A-Za-z0-9_-]{11})", m.group(1)).group(1)


def recover(sandbox):
    """[(offset_ms, end_ms, text, n_words)] over every chunk, absolute and in order."""
    turns, chunks = [], 0
    for path in sorted(glob.glob(str(sandbox / "mai_response_*.json"))):
        r = json.loads(Path(path).read_text(encoding="utf-8"))
        base = int(round(float(r.get("_chunk_start_s") or 0.0) * 1000))
        chunks += 1
        for p in r.get("phrases", []):
            off = p.get("offsetMilliseconds")
            if off is None or not (p.get("text") or "").strip():
                continue
            words = []
            for w in p.get("words") or []:
                wo = w.get("offsetMilliseconds")
                if wo is None:
                    continue
                words.append({"t": base + wo,
                              "d": w.get("durationMilliseconds"),
                              "w": w.get("text")})
            turns.append({"offset_ms": base + off,
                          "end_ms": base + off + int(p.get("durationMilliseconds") or 0),
                          "speaker": p.get("speaker"),
                          "text": p["text"].strip(),
                          "words": words})
    turns.sort(key=lambda t: t["offset_ms"])
    return turns, chunks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="*", help="episode tags; default is every MAI sandbox")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    if a.tags:
        boxes = [(t, ROOT / "data" / f"_mai_{video_id_for(t)}") for t in a.tags]
    else:
        boxes = [(None, Path(p)) for p in sorted(glob.glob(str(ROOT / "data" / "_mai_*")))
                 if Path(p).is_dir()]

    tot_t = tot_w = written = 0
    thin = []
    for tag, box in boxes:
        if not box.exists():
            print(f"  {box.name}: MISSING")
            continue
        turns, chunks = recover(box)
        words = sum(len(t["words"]) for t in turns)
        digest = box / "mai_phrases.json"
        had = len(json.loads(digest.read_text(encoding="utf-8")).get("turns", [])) \
            if digest.exists() else 0
        gain = f"{had} -> {len(turns)}"
        # A phrase with no words list still has its own offset, which is enough to place a
        # turn; flag it rather than drop it, because a chunk that lost its words is a sign
        # the response was truncated.
        nowords = sum(1 for t in turns if not t["words"])
        note = f"  [{nowords} phrase(s) carry no word list]" if nowords else ""
        if len(turns) <= had:
            thin.append(box.name)
        print(f"  {box.name[5:]:<14} chunks {chunks}  turns {gain:<14} words {words:>7}{note}")
        tot_t += len(turns)
        tot_w += words
        if a.write:
            (box / "mai_words.json").write_text(json.dumps({
                "_what": "Phrase and word timings recovered from mai_response_*.json by "
                         "scripts/mai_words_from_responses.py. Offsets are ABSOLUTE ms.",
                "_speakers": "null unless the original run asked MAI to diarize; naming is "
                             "the camera's job, not this file's.",
                "video_id": box.name[5:],
                "chunks": chunks,
                "turns": turns,
            }, ensure_ascii=False), encoding="utf-8")
            written += 1

    print(f"\n{len(boxes)} sandbox(es): {tot_t:,} phrase turns, {tot_w:,} word timings")
    if thin:
        print(f"{len(thin)} already as granular as the digest (nothing gained): {thin}")
    print(f"wrote mai_words.json in {written} sandbox(es)" if a.write else "dry run")


if __name__ == "__main__":
    main()
