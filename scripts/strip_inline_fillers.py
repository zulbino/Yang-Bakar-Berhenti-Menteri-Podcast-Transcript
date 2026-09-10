"""Remove the meaningless filler sounds from inside a sentence in raw.md.

WHY. `strip_filler_turns.py` deletes a turn that is nothing but a noise. It cannot touch
"Yalah. Uh, I mean, mungkin tak tahu", where the noise sits inside real speech. The owner
asked for those too, twice on 2026-09-10: *"Heem, hmm -- just remove this, make things more
cleaner"* and *"i still see uhm, hhm, um in the text"*. MAI transcribes them where the local
ASR dropped them, so a fresh MAI raw has hundreds: 704 in ep61, 951 in ep62.

WHICH SOUNDS. Only ones that mean nothing on their own: uh, uhh, uhm, um, umm, er, erm, hm,
hmm, mm, mhm and their longer spellings. **`ha`, `eh`, `aa`, `oh` and `ah` are deliberately
NOT in the list.** In Malay conversation those carry meaning -- `Ha, betul` is agreement,
`eh` is a real tag, `Oh` is recognition -- and this corpus has already been burned once by a
rule that looked obviously safe: a blanket surname fix would have corrupted 185 correct
names. If the owner wants those too they are one list away, and the count is printed so the
decision is informed.

WHAT IT PROTECTS.
  * The gold passage never changes -- the owner dictated that text from ear.
  * Every non-filler word must be identical, in the same order, before anything is written.
    The comparison is case-insensitive, because removing a filler at the start of a sentence
    promotes the next word to a capital.
  * A block is never emptied. If a block is only fillers it is left for
    `strip_filler_turns.py`, whose whole-turn test is the safe way to drop it.

  python scripts/strip_inline_fillers.py ep61
  python scripts/strip_inline_fillers.py ep61 --write
"""
import argparse
import glob
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"^(\[[\d:]+\]\s*[^:\n]{0,40}?:\s*)(.*)$", re.M)
WORD = re.compile(r"[0-9A-Za-zÀ-ɏ']+")
GOLD_PAD = 60

# Longest spellings first: the alternation is ordered, so `hm` must not win over `hmm`.
FILLERS = ["uhmm", "uhm", "uhh", "umm", "erm", "err", "mhmm", "mmhm", "hmmmm", "hmmm",
           "heem", "hmm", "mmm", "uh", "um", "er", "hm", "mm", "mhm"]
INLINE = re.compile(r"(?<![A-Za-z])(?:" + "|".join(FILLERS) + r")(?![A-Za-z])", re.I)


def secs(t):
    q = [int(x) for x in t.split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(q)))


def words_of(text):
    return [w.lower() for w in WORD.findall(text)]


# A filler that is a whole sentence of its own -- "Sewakan, sewakan. Hmm. Bijak-bijak." --
# has to take its own full stop with it, or the removal leaves "sewakan.. Bijak-bijak".
SENTENCE = re.compile(r"(?:(?<=[.?!])|^)\s*(?:" + "|".join(FILLERS) + r")\s*[.?!]+", re.I)


def clean(said):
    """Drop the fillers, then repair the punctuation and spacing they leave behind."""
    out = SENTENCE.sub(" ", said)
    out = INLINE.sub("\x00", out)
    out = re.sub(r"\s*\x00\s*[,]?\s*", " ", out)        # the filler and any comma after it
    out = re.sub(r"\s*([,.?!])", r"\1", out)            # no space before punctuation
    # The lookbehind is the whole point: without it this puts a space inside a number.
    # It turned ep59's "11.6 sajalah" into "11. 6 sajalah" and ep60's "52,000 orang" into
    # "52, 000 orang", and check_figures caught both -- 1 flagged episode became 2.
    out = re.sub(r"(?<![0-9])([,.?!])(?=[A-Za-zÀ-ɏ0-9])", r"\1 ", out)
    out = re.sub(r",\s*(?=[,.?!])", "", out)            # a comma left against a full stop
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"^[,]\s*", "", out)
    # A sentence that now starts lower-case because its filler was the first word.
    def upper(m):
        return m.group(1) + m.group(2).upper()
    out = re.sub(r"(^|[.?!]\s+)([a-zà-ɏ])", upper, out)
    return out


def gold_window(text):
    path = ROOT / "data" / "speaker_ground_truth.json"
    vid = re.search(r"video_id:\s*(\S+)", text)
    if not path.exists() or not vid:
        return None
    for g in json.load(io.open(path, encoding="utf-8")).values():
        if isinstance(g, dict) and g.get("video_id") == vid.group(1):
            found = re.findall(r"(\d{1,2}:\d{2}(?::\d{2})?)", g.get("region", ""))
            if len(found) >= 2:
                return secs(found[0]) - GOLD_PAD, secs(found[1]) + GOLD_PAD
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--samples", type=int, default=4)
    a = ap.parse_args()

    hits = glob.glob(str(ROOT / f"episodes/*/*-{a.tag}-*/raw.md"))
    if len(hits) != 1:
        sys.exit(f"{len(hits)} episodes match {a.tag}")
    path = Path(hits[0])
    text = path.read_text(encoding="utf-8")
    gold = gold_window(text)

    removed, shown, in_gold, emptied = Counter(), 0, 0, 0
    out_parts, last = [], 0
    for m in BLOCK.finditer(text):
        head, said = m.group(1), m.group(2)
        stamp = secs(re.match(r"\[([\d:]+)\]", head).group(1))
        found = INLINE.findall(said)
        if not found:
            continue
        if gold and gold[0] <= stamp <= gold[1]:
            in_gold += len(found)
            continue
        fixed = clean(said)
        if not WORD.search(fixed or ""):
            emptied += 1
            continue
        for f in found:
            removed[f.lower()] += 1
        if shown < a.samples:
            shown += 1
            print(f"  {head.strip()}\n    before: {said[:150]}\n    after:  {fixed[:150]}")
        out_parts.append(text[last:m.start(2)] + fixed)
        last = m.end(2)
    out = "".join(out_parts) + text[last:]

    total = sum(removed.values())
    print(f"{a.tag}: {total} filler word(s) to remove {dict(removed.most_common(8))}"
          + (f", {in_gold} left inside the gold passage" if in_gold else "")
          + (f", {emptied} block(s) left for strip_filler_turns" if emptied else ""))
    if not total:
        return

    before = [w for w in words_of(text) if w not in {f.lower() for f in FILLERS}]
    after = words_of(out)
    if before != after:
        bad = next((i for i, (x, y) in enumerate(zip(before, after)) if x != y), 0)
        sys.exit("REFUSING TO WRITE: the surviving words changed near "
                 f"{' '.join(after[max(0, bad - 6):bad + 6])!r}")
    print(f"  verified: all {len(after)} non-filler words unchanged and in order")
    # A figure must read the same after the repair as before it. This is a separate assert
    # from the word check, because "52,000" and "52, 000" hold the same words.
    numbers = re.compile(r"\d[\d.,]*\d|\d")
    # Compared WITHOUT stripping spaces: stripping them joins "2 uh 3" into "23" and the
    # comparison then fails on its own arithmetic rather than on any damage.
    if numbers.findall(text) != numbers.findall(out):
        sys.exit("REFUSING TO WRITE: a number changed shape")
    print(f"  verified: {len(numbers.findall(out))} figures unchanged")
    if not a.write:
        print("\n-- dry run, pass --write to apply")
        return
    path.write_text(out, encoding="utf-8")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
