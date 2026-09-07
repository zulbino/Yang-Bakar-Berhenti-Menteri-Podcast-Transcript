"""Map every block of an episode to its true audio start, searching the whole
word track (no radius) since blocks can be displaced by tens of minutes.

Establishes splice boundaries before any audio is cut -- the ep35 lesson:
content-align first, cut once.

TWO WORD SOURCES, AND THE CAPTION ONE IS 15 SECONDS EARLY. A match returns the start of the
best-matching WINDOW, and a window is MATCH_WINDOW_WORDS=40 words, so on a block whose head
words sit late in the window the answer lands before the words were spoken. Measured on ep62
against MAI's per-word offsets, the caption anchors carry a median bias of -16.0s with sd
6.6s. That is irrelevant next to a 500s displacement and it is not irrelevant next to a
correctly stamped block, so retiming a whole file from caption anchors moves the good blocks
15s the wrong way to fix the bad ones.

`--from-mai` swaps the caption track for MAI-Transcribe-2's word offsets from
`data/_mai_<video_id>/mai_response_*.json`, which carry no window bias because every word has
its own timestamp. Same matching algorithm, same output shape, different file
(`_<tag>_align_mai.json`) so the two alignments can be compared rather than overwriting each
other. The captions then stay what they have always been: the independent check, run
afterwards with `check_timestamp_drift.py`.

Usage:
  python scripts/align_blocks.py <epNN>
  python scripts/align_blocks.py <epNN> --from-mai
"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import episode_path, episode_slug, read_frontmatter_body
from dedupe_raw import fetch_captions, parse_caption_words, MATCH_WINDOW_WORDS, MIN_MATCHING_WORDS
from check_timestamp_drift import BLOCK_PREFIX_RE
from qa_check import timestamped_blocks

ROOT = Path(__file__).resolve().parent.parent
tag = sys.argv[1]
from_mai = "--from-mai" in sys.argv[2:]
man = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
ep = [e for e in man if "-" + tag + "-" in episode_slug(e)][0]
print(f"{episode_slug(ep)}  ({ep['video_id']})")


def mai_words(video_id):
    """Every MAI word with its absolute second. The chunk start lives in the response."""
    sandbox = ROOT / "data" / f"_mai_{video_id}"
    files = sorted(sandbox.glob("mai_response*.json"))
    if not files:
        raise SystemExit(f"no MAI responses in {sandbox} -- run transcribe_mai.py first")
    words, times = [], []
    for f in files:
        payload = json.loads(f.read_text(encoding="utf-8"))
        shift = payload.get("_chunk_start_s", 0)
        for phrase in payload.get("phrases", []):
            for w in phrase.get("words", []):
                token = re.sub(r"[^\w\s]", "", w["text"]).strip().lower()
                if token:
                    words.append(token)
                    times.append(int(w["offsetMilliseconds"] / 1000 + shift))
    return words, times


if from_mai:
    words, times = mai_words(ep["video_id"])
    print(f"anchoring on {len(words)} MAI words")
else:
    vtt = fetch_captions(ep["video_id"], "ms") or fetch_captions(ep["video_id"], "en")
    words, times = parse_caption_words(vtt.read_text(encoding="utf-8"))
_, body = read_frontmatter_body(ROOT / "episodes" / episode_path(ep) / "raw.md")

def best_global(phrase):
    """Where a block's opening words are, by best 40-word window, timed at the FIRST
    MATCHED WORD rather than at the window's start.

    The window start is up to 40 words -- 12 to 25 seconds -- before the words being looked
    for, and it used to be the answer. Measured on ep62 against MAI's per-word offsets that
    was a median -16.0s with sd 6.6s on every block, which is nothing beside a 500s
    displacement and is worse than doing nothing on a block that was already right. Timing
    the answer at the first distinctive word inside the winning window removes it.
    """
    dist = {w for w in phrase if len(w) >= 5}
    if len(dist) < MIN_MATCHING_WORDS:
        return None, 0, len(dist)
    best, pos = 0, None
    for i in range(len(words) - MATCH_WINDOW_WORDS + 1):
        s = len(dist & set(words[i:i + MATCH_WINDOW_WORDS]))
        if s > best:
            best, pos = s, i
    if best < MIN_MATCHING_WORDS:
        return None, best, len(dist)
    at = next((times[j] for j in range(pos, min(pos + MATCH_WINDOW_WORDS, len(words)))
               if words[j] in dist), times[pos])
    return at, best, len(dist)

rows = []
for ts, blk in timestamped_blocks(body):
    ph = re.sub(r"[^\w\s]", " ", BLOCK_PREFIX_RE.sub("", blk).lower()).split()[:20]
    actual, score, tot = best_global(ph)
    rows.append({"claimed": ts, "chars": len(blk), "actual": actual, "score": score,
                 "distinct": tot, "head": BLOCK_PREFIX_RE.sub("", blk)[:60]})
out = ROOT / "data" / (f"_{tag}_align_mai.json" if from_mai else f"_{tag}_align.json")
out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
print(f"wrote {out.name}   track_end={times[-1]}s   {len(rows)} blocks")
print(f"{'claimed':>8} {'chars':>6} {'actual':>7} {'delta':>7} {'score':>6}  head")
for r in rows:
    a = r["actual"]
    d = f"{a - r['claimed']:+d}" if a is not None else "--"
    print(f"{r['claimed']:>8} {r['chars']:>6} {str(a if a is not None else '--'):>7} {d:>7} "
          f"{r['score']}/{r['distinct']:<4}  {r['head'][:52]!r}")
