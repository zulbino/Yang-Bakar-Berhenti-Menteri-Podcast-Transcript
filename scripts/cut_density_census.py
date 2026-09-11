"""Rank episodes by how badly raw.md UNDER-CUTS them, using two sources and no clock.

WHY A NEW SIGNAL. The existing candidate list for the turn-collapse defect is "published
turns of 400+ words", 341 of them, and its own notes say a long turn is a candidate rather
than a defect -- on ep34 roughly half the long turns turned out to be Rafizi genuinely
talking for ten minutes. So word count alone cannot separate "one person talking a long
time" from "several people filed under one name".

TWO INDEPENDENT COUNTS, NEITHER OF WHICH TRUSTS raw.md's TIMESTAMPS. That last part is the
point: block stamps in this corpus are unreliable (159 of ep61's 203 were more than 10s out,
ep40's clock is 170s early), so any detector that turns a block stamp into a time window is
measuring drift as much as content. Both counts here are whole-episode totals, so the clock
never enters:

  caption speaker changes   `>>` markers in audio/<vid>.ms.vtt, YouTube's own ASR
  raw.md blocks             how many turns the transcript actually cut

The ratio blocks/changes is length-normalised, because both counts scale with runtime.

HOW TO READ IT, and this is the part that matters. Do NOT read the ratio as an error rate.
`>>` is measurably unreliable as a speaker IDENTITY signal and is not used as one here; it
is only counted, and over 600-1400 markers per episode the noise averages out. Read it
RELATIVE to a known-good episode: ep62, the one cut to the current standard, sits at 0.42,
and the corpus median is 0.21. An episode near 0.11 has roughly a quarter of ep62's turn
density for the same amount of conversation.

VALIDATION, done before trusting it. Of 47 scorable episodes, the four with independently
confirmed collapses rank 1, 3, 6 and 9:

  ep41  0.11  rank 1   its 13,756-char block, which the owner later split by ear
  ep34  0.12  rank 3   opening 12 minutes, camera-confirmed as Haziq under Rafizi's name
  ep45  0.14  rank 6   ~11 minutes of Haziq labelled Rafizi
  ep40  0.16  rank 9   the Bloomberg passage, camera-confirmed as Rafizi under Haziq's name

THE RATIO AND THE LONGEST BLOCK ARE DIFFERENT DEFECTS, and conflating them sent one session
after the wrong episode. The ratio finds episode-wide under-cutting. The longest block finds
one pathological turn. ep33 is the worked example: it ranks 41st of 47 on the ratio (0.38,
near ep62's 0.42) and is therefore one of the BETTER-cut episodes, yet it carries a single
14,090-character block holding 104 caption-marked speaker changes. Conversely ep62, cut to
the standard, still has an 11,823-character block, so a long block on its own is not a
defect. Report both columns and never rank on one.

22 episodes are unscorable and are listed separately rather than scored. 16 have no cached
caption track (ep01-ep14 and two YBkM). Six more HAVE a track that contains not a single
`>>` marker -- ep21, ep00, ep05, and YBkM ep01/ep02/ep03 -- because that caption generation
does not use the convention. Scoring those gave ratios of 77 to 199, which sorted them to
the bottom of the table where they read as the best-cut episodes in the corpus.

  python scripts/cut_density_census.py
  python scripts/cut_density_census.py --json data/cut_density.json
"""
import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CUE = re.compile(r"([\d:.]+) --> ([\d:.]+)[^\n]*\n(.*?)(?=\n\n|\Z)", re.S)
BLOCK = re.compile(r"^\[([\d:]+)\]\s*([^:\n]{1,40}?):\s*(.*)$", re.M)
# ep62 is the episode cut to the current standard; quote every ratio against it.
REFERENCE = "ep62"


def video_id(raw):
    head = raw.read_text(encoding="utf-8")[:2000]
    m = re.search(r"(?:video_id|youtube_id|url|source)\s*:\s*(\S+)", head)
    if not m:
        return None
    m2 = re.search(r"([A-Za-z0-9_-]{11})", m.group(1))
    return m2.group(1) if m2 else None


def caption_changes(vtt):
    """How many times YouTube's captions mark a new speaker. Dedup first: the cue stream
    repeats each line as it scrolls, so counting raw cues triples the figure."""
    seen, changes = set(), 0
    for m in CUE.finditer(Path(vtt).read_text(encoding="utf-8")):
        text = re.sub(r"<[^>]*>", "", m.group(3)).replace("&gt;&gt;", ">>").strip()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines or lines[-1] in seen:
            continue
        seen.add(lines[-1])
        if lines[-1].lstrip().startswith(">>"):
            changes += 1
    return changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="also write the table here")
    a = ap.parse_args()

    rows, skipped = [], []
    for path in sorted(glob.glob(str(ROOT / "episodes" / "*" / "*" / "raw.md"))):
        raw = Path(path)
        tag = re.search(r"-(ep\d+)-", raw.parent.name).group(1)
        show = raw.parent.parent.name.split("-")[1]
        vid = video_id(raw)
        vtt = ROOT / "audio" / f"{vid}.ms.vtt" if vid else None
        blocks = BLOCK.findall(raw.read_text(encoding="utf-8"))
        longest = max((len(b[2]) for b in blocks), default=0)
        mai = ROOT / "data" / f"_mai_{vid}" / "mai_words.json" if vid else None
        phrases = len(json.loads(mai.read_text(encoding="utf-8"))["turns"]) \
            if mai and mai.exists() else None
        if not (vtt and vtt.exists()):
            skipped.append(f"{tag}:{show}(no vtt)")
            continue
        changes = caption_changes(vtt)
        # A track with ZERO markers does not mean nobody ever changed speaker -- it means
        # this caption generation does not use the convention. ep21, ep00, ep05, ep01,
        # ep02 and YBkM-ep03 have not one `>>` in the whole file, against 3,548 in ep62's.
        # Scoring them gave ratios of 77 to 199 that sorted to the bottom of the table and
        # read like the best-cut episodes in the corpus. Unavailable, not zero.
        if changes == 0:
            skipped.append(f"{tag}:{show}(no >> markers)")
            continue
        rows.append({"episode": tag, "show": show, "blocks": len(blocks),
                     "caption_changes": changes, "mai_phrases": phrases,
                     "ratio": round(len(blocks) / max(changes, 1), 3),
                     "longest_block_chars": longest})

    rows.sort(key=lambda r: r["ratio"])
    ref = next((r["ratio"] for r in rows if r["episode"] == REFERENCE), None)
    med = rows[len(rows) // 2]["ratio"] if rows else 0

    print(f"{'rank':>4}  {'ep':<6}{'blocks':>7}{'changes':>9}{'MAI':>7}{'ratio':>7}"
          f"{'vs ep62':>9}{'longest':>9}")
    for i, r in enumerate(rows, 1):
        rel = f"{r['ratio'] / ref:.0%}" if ref else "-"
        mark = "  <- REFERENCE" if r["episode"] == REFERENCE else ""
        print(f"{i:>4}  {r['episode']:<6}{r['blocks']:>7}{r['caption_changes']:>9}"
              f"{str(r['mai_phrases']):>7}{r['ratio']:>7.2f}{rel:>9}"
              f"{r['longest_block_chars']:>9}{mark}")
    print(f"\n{len(rows)} scored, median ratio {med:.2f}, {REFERENCE} reference {ref}")
    print(f"{len(skipped)} unscorable, absent rather than zero: {' '.join(skipped)}")
    worst = [r["episode"] for r in rows[:6]]
    big = sorted(rows, key=lambda r: -r["longest_block_chars"])[:6]
    print(f"\nunder-cut episode-wide: {' '.join(worst)}")
    print(f"one pathological block:  "
          f"{' '.join(f'{r['episode']}({r['longest_block_chars']})' for r in big)}")

    if a.json:
        Path(a.json).write_text(json.dumps({
            "_what": "Per-episode turn-cut density. See scripts/cut_density_census.py for "
                     "how to read the ratio -- it is NOT an error rate.",
            "_reference": f"{REFERENCE} is cut to the current standard and sits at {ref}; "
                          f"the corpus median is {med}.",
            "_two_defects": "ratio finds episode-wide under-cutting; longest_block_chars "
                            "finds one pathological turn. ep33 is 41st on ratio yet holds a "
                            "14,090-char block, and ep62 is the reference yet holds 11,823.",
            "rows": rows, "no_captions": skipped,
        }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {a.json}")


if __name__ == "__main__":
    main()
