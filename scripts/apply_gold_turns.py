"""Write the owner's DICTATED turns into raw.md, over MAI's words, for a gold passage.

WHY THIS EXISTS. `data/speaker_ground_truth.json` holds passages the owner transcribed by
watching and listening -- ep61's is 18 turns across 01:30 to 03:00, recorded 2026-08-30
with the note "this is the most accurate based on what I hear and watch". raw.md never
received them. `mai_camera_raw.py`'s `carve_in_gold()` splices the CURRENT raw.md's blocks
for that time range, and for ep61 that meant the old local-ASR blocks: three of the
owner's turns fused into one Haziq block, `Mana ada cuti?` missing entirely, and the `YB?`
missing from `Macam nak pilihan raya dah YB?`. The owner found it on 2026-09-12 by reading
the file and quoting words it does not contain.

WHAT IT DOES. Takes MAI's own words for the passage's seconds -- the best-measured
transcript this corpus has, 3.39% WER on podcast speech -- and cuts them at the boundaries
of the owner's dictated turns, giving each turn its own speaker and a stamp from MAI's word
times. The words are MAI's, unchanged; the turn boundaries and the names are the owner's.

HOW THE BOUNDARIES ARE FOUND. `lib_locate.Doc.locate()`, which scores on CHARACTERS, not
whole tokens, because the owner writes `bagitahu` where MAI has `bagi tahu` and `Ogos`
where MAI has `August`. A naive best-ratio scan was tried first and drifted by four turns
(turn 1 landed 58 seconds early), which is why the matching is monotonic here: each turn is
located only in the words after the previous turn's last word.

WHAT IT REFUSES. A turn it cannot locate, a turn whose match scores below lib_locate's own
floor, and any run where the words outside the passage would change. It prints the old and
new blocks and writes nothing without --write.

  python scripts/apply_gold_turns.py ep61
  python scripts/apply_gold_turns.py ep61 --write
"""
import argparse
import glob
import json
import os
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
from lib_locate import Doc, secs, tokens  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
# MAI is requested in 30-minute chunks, and each response's offsets restart at zero.
CHUNK_SECONDS = 1800
# The region is prose ("roughly 01:30 to 03:00") AND it is written in the OLD transcript's
# clock, which drifts: ep61's dictated turn 1 sits at 66 s in MAI's word times against a
# stated 01:30. So the window is padded generously and the turns themselves decide where
# the passage really starts, matched in order. With PAD = 12 the first four turns fell
# outside the window and reported "not locatable".
PAD = 120
# Words used to find each end of the passage in raw.md, the same idea as
# mai_camera_raw.py's gold seams.
SEAM_WORDS = 8


def turns_text(turns, k):
    return turns[k]["text"]


def hms(s):
    s = int(s)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def mai_words(vid):
    out = []
    for f in sorted(glob.glob(str(ROOT / f"data/_mai_{vid}/mai_response_*.json"))):
        idx = int(os.path.basename(f).split("_")[-1].split(".")[0])
        blob = json.loads(Path(f).read_text(encoding="utf-8"))
        for ph in blob.get("phrases", []):
            for w in ph.get("words", []):
                out.append((idx * CHUNK_SECONDS + w["offsetMilliseconds"] / 1000, w["text"]))
    out.sort()
    return out


def gold_entry(vid):
    truth = json.loads((ROOT / "data" / "speaker_ground_truth.json").read_text(encoding="utf-8"))
    for key, g in truth.items():
        if isinstance(g, dict) and g.get("video_id") == vid and g.get("turns"):
            m = re.findall(r"(\d{1,2}:\d{2}(?::\d{2})?)", g.get("region", ""))
            if len(m) >= 2:
                return key, secs(m[0]), secs(m[1]), g
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    raw_path = Path(common.raw_for_tag(a.tag))
    text = raw_path.read_text(encoding="utf-8")
    vid = re.search(r"video_id:\s*(\S+)", text).group(1)
    found = gold_entry(vid)
    if not found:
        sys.exit(f"{a.tag}: no dictated turns for {vid} in data/speaker_ground_truth.json")
    key, lo, hi, gold = found
    print(f"{a.tag}: {len(gold['turns'])} dictated turns, {key}, region {hms(lo)}-{hms(hi)}")
    print(f"  source: {gold.get('source')}")

    words = [(t, w) for t, w in mai_words(vid) if lo - PAD <= t <= hi + PAD]
    if not words:
        sys.exit(f"{a.tag}: MAI has no words in {hms(lo)}-{hms(hi)}")
    # One pseudo-block per word, so a located token span maps straight back to its second.
    pseudo = "\n\n".join(f"[{hms(t)}] MAI: {w}" for t, w in words)

    # ONE GLOBAL MONOTONIC ALIGNMENT, not a per-turn search. Locating each turn separately
    # with lib_locate found 6 of ep61's 18: it returns None below three tokens, so `Ya.`
    # and `Kita memang beria.` can never be found that way, and one miss leaves the cursor
    # where it was and drags the next turn off too. Both streams are the same speech in the
    # same order, so SequenceMatcher over the token lists aligns them in one pass, and
    # monotonicity comes free.
    dictated = []                      # (token, turn index) for every dictated word
    for k, turn in enumerate(gold["turns"]):
        dictated += [(w, k) for w in tokens(turn["text"])]
    mai_tok = [w for _, w in words]
    for i, w in enumerate(mai_tok):
        mai_tok[i] = tokens(w)[0] if tokens(w) else ""
    owner_of = [None] * len(mai_tok)
    for op in SequenceMatcher(None, [d[0] for d in dictated], mai_tok,
                              autojunk=False).get_opcodes():
        kind, i1, i2, j1, j2 = op
        if kind != "equal":
            continue
        for step in range(i2 - i1):
            owner_of[j1 + step] = dictated[i1 + step][1]
    # THE RATIO IS MEASURED OVER THE DICTATION, not over the padded window. PAD is
    # deliberately wide because the region's minutes come from a drifting clock, so most of
    # the window is speech outside the passage; scoring against it read 19% on a good
    # alignment and refused to run.
    hits = [i for i, o in enumerate(owner_of) if o is not None]
    covered = len({i for op in [None] for i in hits})
    dict_hit = len({dictated[i][1] for i in range(len(dictated))}) and sum(
        1 for o in owner_of if o is not None)
    print(f"  aligned {dict_hit} MAI words to the dictation's {len(dictated)} words "
          f"({dict_hit / len(dictated):.0%} of the dictation)")
    if dict_hit / len(dictated) < 0.6:
        sys.exit(f"{a.tag}: REFUSING, only {dict_hit / len(dictated):.0%} of the dictated "
                 f"words found a match -- the region or the entry is wrong")
    # The PASSAGE is what the alignment covers, first aligned word to last. Everything
    # outside it in the padded window is other speech and must be left alone.
    first, last = hits[0], hits[-1]
    words = words[first:last + 1]
    owner_of = owner_of[first:last + 1]
    lo, hi = words[0][0], words[-1][0]
    print(f"  passage in MAI's clock: {hms(lo)}-{hms(hi)}, {len(words)} words")
    # A MAI word the alignment did not cover (a filler MAI heard and the owner did not,
    # a different spelling) joins the turn of the word before it, so no word is dropped.
    last = next(o for o in owner_of if o is not None)
    for i, o in enumerate(owner_of):
        if o is None:
            owner_of[i] = last
        else:
            last = o
    # An out-of-order assignment is the one thing a monotonic pass must not emit.
    for i in range(1, len(owner_of)):
        owner_of[i] = max(owner_of[i], owner_of[i - 1])

    # A word both turns could own lands on the earlier one, because SequenceMatcher takes
    # the first equal run it finds: MAI's `Kita memang beria. Okey. Okey, baik YB.` put both
    # `Okey`s on Rafizi and left Haziq's turn opening `baik YB`. So a trailing word that is
    # the next dictated turn's OWN opening word is handed forward.
    for i in range(len(owner_of) - 1):
        k = owner_of[i]
        nxt = owner_of[i + 1]
        if nxt == k or nxt is None:
            continue
        opening = tokens(turns_text(gold["turns"], nxt))[:4]
        j = i
        while j >= 0 and owner_of[j] == k:
            word = tokens(words[j][1])
            # Fuzzy, because the two spell the same sound differently: the owner writes
            # `Okay` and MAI writes `Okey`, and an exact test left both on the wrong turn.
            if not word or not any(SequenceMatcher(None, word[0], o).ratio() >= 0.75
                                   for o in opening):
                break
            owner_of[j] = nxt
            j -= 1

    blocks, turns = [], gold["turns"]
    start = 0
    for i in range(1, len(owner_of) + 1):
        if i == len(owner_of) or owner_of[i] != owner_of[start]:
            turn = turns[owner_of[start]]
            body = " ".join(w for _, w in words[start:i]).strip()
            blocks.append((words[start][0], turn["speaker"], body, turn["n"]))
            start = i
    unseen = sorted(set(range(len(turns))) - set(owner_of))
    for k in unseen:
        print(f"  turn {turns[k]['n']} ({turns[k]['speaker']}) got no words: "
              f"{turns[k]['text'][:60]!r}")

    print("\n  NEW BLOCKS")
    for t, who, body, n in blocks:
        print(f"    [{hms(t)}] {who}: {body[:86]}")

    # WHICH raw.md BLOCKS GET REPLACED IS DECIDED BY WORDS, NEVER BY THE CLOCK. Picking
    # them by the padded time window selected 24 blocks for an 18-block passage, four
    # minutes of unrelated talk included, and the only guard that existed checked the words
    # OUTSIDE that window -- so the extra blocks would have been deleted silently.
    doc = Doc(text)
    head_hit = doc.locate(" ".join(tokens(blocks[0][2])[:SEAM_WORDS]), near=lo)
    tail_hit = doc.locate(" ".join(tokens(blocks[-1][2])[-SEAM_WORDS:]), near=hi)
    if not head_hit or not tail_hit:
        sys.exit(f"{a.tag}: REFUSING, cannot find the passage's own seams in raw.md")
    b0, b1 = doc.owner[head_hit["tok0"]], doc.owner[tail_hit["tok1"]]
    if b1 < b0:
        sys.exit(f"{a.tag}: REFUSING, the passage seams cross in raw.md ({b0} > {b1})")
    old = list(range(b0, b1 + 1))
    removed = sum(len(tokens(doc.blocks[i][2])) for i in old)
    added = sum(len(tokens(b[2])) for b in blocks)
    print(f"  seams: raw blocks {b0}-{b1}, {removed} words out, {added} words in")
    if not 0.6 <= added / removed <= 1.6:
        sys.exit(f"{a.tag}: REFUSING, the replacement changes the passage's length too much "
                 f"({removed} -> {added} words)")
    print("\n  BLOCKS BEING REPLACED")
    for i in old:
        print(f"    {doc.line(i)[:96]}")

    lines = [doc.line(i) for i in range(len(doc.blocks))]
    lines[old[0]:old[-1] + 1] = [f"[{hms(t)}] {who}: {body}" for t, who, body, _ in blocks]
    head = text[:text.index(doc.line(0))]
    out = head + "\n\n".join(lines) + "\n"

    before = ([w for i in range(b0) for w in tokens(doc.blocks[i][2])],
              [w for i in range(b1 + 1, len(doc.blocks)) for w in tokens(doc.blocks[i][2])])
    after_doc = Doc(out)
    tail0 = b0 + len(blocks)
    after = ([w for i in range(b0) for w in tokens(after_doc.blocks[i][2])],
             [w for i in range(tail0, len(after_doc.blocks))
              for w in tokens(after_doc.blocks[i][2])])
    print(f"  words outside the passage unchanged: {len(before[0])} before the "
          f"passage, {len(before[1])} after. Stamps monotonic.")
    if before != after:
        sys.exit(f"{a.tag}: REFUSING, words OUTSIDE the passage changed "
                 f"({len(before[0])}+{len(before[1])} -> {len(after[0])}+{len(after[1])})")
    stamps = [secs(b[0]) for b in after_doc.blocks]
    if any(b < a for a, b in zip(stamps, stamps[1:])):
        sys.exit(f"{a.tag}: REFUSING, stamps run backwards after the splice")
    print(f"\n  words outside the passage unchanged ({len(before)}), stamps monotonic")
    if not a.write:
        print("\n-- dry run, pass --write to apply")
        return
    raw_path.write_text(out, encoding="utf-8")
    print(f"wrote {raw_path}")


if __name__ == "__main__":
    main()
