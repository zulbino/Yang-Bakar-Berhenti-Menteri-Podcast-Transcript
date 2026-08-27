"""Map every block of an episode to its true audio start, searching the whole
caption (no radius) since blocks can be displaced by tens of minutes.

Establishes splice boundaries before any audio is cut -- the ep35 lesson:
content-align first, cut once.

Usage: python scripts/_align_blocks.py <epNN>
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
man = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
ep = [e for e in man if "-" + tag + "-" in episode_slug(e)][0]
print(f"{episode_slug(ep)}  ({ep['video_id']})")
vtt = fetch_captions(ep["video_id"], "ms") or fetch_captions(ep["video_id"], "en")
words, times = parse_caption_words(vtt.read_text(encoding="utf-8"))
_, body = read_frontmatter_body(ROOT / "episodes" / episode_path(ep) / "raw.md")

def best_global(phrase):
    dist = {w for w in phrase if len(w) >= 5}
    if len(dist) < MIN_MATCHING_WORDS:
        return None, 0, len(dist)
    best, pos = 0, None
    for i in range(len(words) - MATCH_WINDOW_WORDS + 1):
        s = len(dist & set(words[i:i + MATCH_WINDOW_WORDS]))
        if s > best:
            best, pos = s, i
    return (times[pos] if best >= MIN_MATCHING_WORDS else None), best, len(dist)

rows = []
for ts, blk in timestamped_blocks(body):
    ph = re.sub(r"[^\w\s]", " ", BLOCK_PREFIX_RE.sub("", blk).lower()).split()[:20]
    actual, score, tot = best_global(ph)
    rows.append({"claimed": ts, "chars": len(blk), "actual": actual, "score": score,
                 "distinct": tot, "head": BLOCK_PREFIX_RE.sub("", blk)[:60]})
(ROOT / "data" / f"_{tag}_align.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
print(f"caption_end={times[-1]}s   {len(rows)} blocks")
print(f"{'claimed':>8} {'chars':>6} {'actual':>7} {'delta':>7} {'score':>6}  head")
for r in rows:
    a = r["actual"]
    d = f"{a - r['claimed']:+d}" if a is not None else "--"
    print(f"{r['claimed']:>8} {r['chars']:>6} {str(a if a is not None else '--'):>7} {d:>7} "
          f"{r['score']}/{r['distinct']:<4}  {r['head'][:52]!r}")
