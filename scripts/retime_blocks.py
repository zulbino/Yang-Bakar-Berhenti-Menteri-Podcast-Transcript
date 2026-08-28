"""Rewrite an episode's raw.md timestamps to where the caption says the text really is.

For an episode whose TEXT is sound but whose CLOCK is not -- local ASR's VAD chunking can
hand a chunk the wrong absolute offset, leaving blocks minutes from where they were spoken.
ep61 had its whole middle displaced by up to 472s, which `qa_check.py` read as 1393s of
missing content because a gap in the claimed timeline is indistinguishable from absent
speech unless you go and measure the audio (1.42).

This does not touch a single character of the transcript. Only the `[h:mm:ss]` prefixes
move, so it is safe on a file carrying hand-edits, which a re-transcribe is not.

Run `align_blocks.py <tag>` first; this reads the `data/_<tag>_align.json` it writes.

  python scripts/align_blocks.py ep61
  python scripts/retime_blocks.py ep61            # dry run, prints what would move
  python scripts/retime_blocks.py ep61 --write

Anchors are the blocks the caption matched, minus the ones that disagree with the rest.
Speech runs forward, so true anchors form an increasing sequence and a false phrase-lock
usually does not fit it; keeping the longest increasing subsequence drops the liars without
needing to know in advance which ones they are. That matters because a lock can look strong
-- see the ep17 and ep21 verdicts in `data/qa_reviewed.json`, both isolated locks on blocks
whose head words scored equally badly at the claimed and the matched position.

**A match-score floor was tried and dropped.** Filtering on `align_blocks.py`'s score
before the ordering filter costs far more than it buys: on ep61, scores 4-11 across 132
matched blocks, the ordering filter alone rejects 6 and keeps 80% of the body's characters
anchored, while a floor of 6 leaves 57% and a floor of 7 leaves 42% -- below the point where
interpolation carries the result. So `--min-score` defaults to align_blocks' own
MIN_MATCHING_WORDS, which accepts everything it matched, and exists only as a knob for an
episode where the ordering filter proves insufficient.

Unanchored blocks in between are placed by character length, on the same
SPEECH_CHARS_PER_SECOND that `qa_check.py` uses to judge a gap, then squeezed to fit the
span its two anchors leave. Nothing extrapolates past the outermost anchor: those blocks
keep their claimed offset relative to it, since there is no evidence to place them better.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import episode_path, episode_slug, frontmatter_md, read_frontmatter_body
from dedupe_raw import MIN_MATCHING_WORDS
from qa_check import SPEECH_CHARS_PER_SECOND, timestamped_blocks

ROOT = Path(__file__).resolve().parent.parent
LEADING_TS_RE = re.compile(r"^\[(?:\d+:)?\d+:\d+\]\s*")

# align_blocks.py's own floor: it never reports a match on fewer distinctive words than
# this, so the default accepts every match it found and leaves the filtering to the
# ordering check. Raising it is measurably counterproductive -- see the module docstring.
MIN_ANCHOR_SCORE = MIN_MATCHING_WORDS
# Below this share of the body anchored, interpolation is carrying more of the result than
# the evidence is, and the output would be a guess wearing a measurement's clothes.
MIN_ANCHORED_CHAR_FRACTION = 0.60


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--write", action="store_true", help="apply; otherwise dry run")
    ap.add_argument("--min-score", type=int, default=MIN_ANCHOR_SCORE)
    return ap.parse_args()


def longest_increasing(anchors):
    """The largest subset of (index, seconds) anchors whose seconds increase."""
    if not anchors:
        return []
    best = [1] * len(anchors)
    prev = [-1] * len(anchors)
    for i in range(len(anchors)):
        for j in range(i):
            if anchors[j][1] < anchors[i][1] and best[j] + 1 > best[i]:
                best[i], prev[i] = best[j] + 1, j
    i = max(range(len(anchors)), key=lambda k: best[k])
    chain = []
    while i != -1:
        chain.append(anchors[i])
        i = prev[i]
    return chain[::-1]


def retime(blocks, anchors):
    """New second for every block, from the anchored ones outward."""
    chars = [len(LEADING_TS_RE.sub("", blk, count=1)) for _, blk in blocks]
    fixed = dict(anchors)
    out = [None] * len(blocks)
    for i, sec in anchors:
        out[i] = sec

    ordered = [i for i, _ in anchors]
    for left, right in zip(ordered, ordered[1:]):
        span = fixed[right] - fixed[left]
        # What the text between them would take to say, used only as a shape to
        # distribute the span by -- never to set a duration of its own.
        weights = [chars[i] / SPEECH_CHARS_PER_SECOND for i in range(left, right)]
        total = sum(weights) or 1
        at = fixed[left]
        for offset, i in enumerate(range(left + 1, right)):
            at += span * weights[offset] / total
            out[i] = int(at)

    # Outside the anchored range there is nothing to interpolate against, so hold the
    # claimed spacing and let the nearest anchor supply the offset.
    first, last = ordered[0], ordered[-1]
    for i in range(first - 1, -1, -1):
        out[i] = out[i + 1] - max(1, blocks[i + 1][0] - blocks[i][0])
    for i in range(last + 1, len(blocks)):
        out[i] = out[i - 1] + max(1, blocks[i][0] - blocks[i - 1][0])
    return [max(0, s) for s in out]


def fmt(sec):
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    return f"[{h}:{m:02d}:{s:02d}]" if h else f"[{m:02d}:{s:02d}]"


def main():
    a = parse_args()
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    ep = [e for e in manifest if "-" + a.tag + "-" in episode_slug(e)][0]
    raw_path = ROOT / "episodes" / episode_path(ep) / "raw.md"
    align_path = ROOT / "data" / f"_{a.tag}_align.json"
    if not align_path.exists():
        raise SystemExit(f"no alignment for {a.tag}: run "
                         f"`python scripts/align_blocks.py {a.tag}` first")

    fm, body = read_frontmatter_body(raw_path)
    blocks = timestamped_blocks(body)
    rows = json.loads(align_path.read_text(encoding="utf-8"))
    if len(rows) != len(blocks):
        raise SystemExit(f"alignment describes {len(rows)} blocks, raw.md has "
                         f"{len(blocks)} -- raw.md changed since; re-run align_blocks.py")

    matched = [(i, r["actual"]) for i, r in enumerate(rows)
               if r["actual"] is not None and r["score"] >= a.min_score]
    anchors = longest_increasing(matched)
    rejected = len(matched) - len(anchors)
    chars = [len(LEADING_TS_RE.sub("", blk, count=1)) for _, blk in blocks]
    anchored_chars = sum(chars[i] for i, _ in anchors)
    fraction = anchored_chars / max(1, sum(chars))

    print(f"{episode_slug(ep)}")
    print(f"  {len(blocks)} blocks, {len(rows) - sum(1 for r in rows if r['actual'] is None)}"
          f" caption-matched, {len(matched)} above score {a.min_score}, "
          f"{len(anchors)} kept as anchors ({rejected} rejected as out of order)")
    print(f"  anchors hold {fraction:.0%} of the body's characters")

    if not anchors:
        raise SystemExit("no usable anchors -- nothing to retime against")
    if fraction < MIN_ANCHORED_CHAR_FRACTION:
        raise SystemExit(f"refusing: anchors cover {fraction:.0%} of the text, under the "
                         f"{MIN_ANCHORED_CHAR_FRACTION:.0%} floor. Interpolation would be "
                         f"carrying the result. Improve the captions or the match first.")

    new = retime(blocks, anchors)
    if any(b <= x for x, b in zip(new, new[1:])):
        raise SystemExit("refusing: output timestamps are not strictly increasing")
    duration = ep.get("duration_seconds")
    if duration and new[-1] > duration + 60:
        raise SystemExit(f"refusing: last timestamp {new[-1]}s overruns the "
                         f"{duration}s runtime")

    moves = sorted(((abs(new[i] - blocks[i][0]), blocks[i][0], new[i]) for i in range(len(blocks))),
                   reverse=True)
    print(f"  worst move {moves[0][0]}s ({moves[0][1]}s -> {moves[0][2]}s); "
          f"{sum(1 for m in moves if m[0] >= 60)} blocks move a minute or more")
    print(f"\n{'claimed':>9} {'new':>9} {'move':>7}  head")
    for d, old_s, new_s in moves[:12]:
        i = next(k for k in range(len(blocks)) if blocks[k][0] == old_s and new[k] == new_s)
        head = LEADING_TS_RE.sub("", blocks[i][1], count=1).replace("\n", " ")[:52]
        print(f"{old_s:9d} {new_s:9d} {d:+7d}  {head!r}")

    lines = []
    for (old_s, blk), new_s in zip(blocks, new):
        lines.append(LEADING_TS_RE.sub(fmt(new_s) + " ", blk.strip(), count=1))
    new_body = "# Raw Transcript\n\n" + "\n\n".join(lines)

    if not a.write:
        print("\n-- dry run, not written; pass --write to apply --")
        return
    note = fm.get("note", "")
    stamp = (f"Timestamps retimed against YouTube caption timing by retime_blocks.py "
             f"({len(anchors)} anchors, worst move {moves[0][0]}s); transcript text "
             f"unchanged.")
    fm["note"] = f"{note} {stamp}".strip() if note else stamp
    raw_path.write_text(frontmatter_md(fm, new_body), encoding="utf-8")
    print(f"\nwrote {raw_path}")
    print("Re-run: check_timestamp_drift.py, check_caption_coverage.py, qa_check.py")


if __name__ == "__main__":
    main()
