"""Reverse-map each raw.md block to where its text actually occurs in the audio.

The ep35 fabrication recipe: for each block, find where
in the caption its text actually occurs, using 4-gram matching unconstrained by
the claimed timestamp. Reveals whether late blocks are displaced, duplicated
from earlier audio, or absent from the audio entirely."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import episode_path, episode_slug, read_frontmatter_body
from dedupe_raw import fetch_captions, parse_caption_words
from qa_check import timestamped_blocks

ROOT = Path(__file__).resolve().parent.parent
manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
WANT = sys.argv[1:]
if not WANT:
    raise SystemExit("usage: python scripts/block_origin_map.py <epNN> [epNN ...]")
N = 4

def norm(t):
    return [w for w in re.sub(r"[^\w\s]", " ", t.lower()).split()]

for ep in manifest:
    slug = episode_slug(ep)
    tag = [t for t in WANT if "-" + t + "-" in slug]
    if not tag:
        continue
    _, body = read_frontmatter_body(ROOT / "episodes" / episode_path(ep) / "raw.md")
    vtt = fetch_captions(ep["video_id"], "ms") or fetch_captions(ep["video_id"], "en")
    words, times = parse_caption_words(vtt.read_text(encoding="utf-8"))
    cw = [re.sub(r"[^\w]", "", w.lower()) for w in words]
    gram_at = {}
    for i in range(len(cw) - N + 1):
        gram_at.setdefault(tuple(cw[i:i+N]), []).append(times[i])
    print(f"\n===== {tag[0]}  {slug}   caption_end={times[-1]}s")
    print(f"  {'claimed':>8} {'chars':>6} {'hits':>5} {'median_actual':>14} {'p10':>6} {'p90':>6}")
    for ts, blk in timestamped_blocks(body):
        bw = norm(blk)
        hits = []
        for i in range(len(bw) - N + 1):
            g = tuple(bw[i:i+N])
            if g in gram_at and len(gram_at[g]) <= 3:   # rare grams only
                hits.extend(gram_at[g])
        if not hits:
            print(f"  {ts:>8} {len(blk):>6} {0:>5} {'NO MATCH IN AUDIO':>14}")
            continue
        hits.sort()
        med = hits[len(hits)//2]
        p10, p90 = hits[int(len(hits)*.1)], hits[int(len(hits)*.9)]
        mark = "" if abs(med - ts) < 300 else "   <== DISPLACED"
        print(f"  {ts:>8} {len(blk):>6} {len(hits):>5} {med:>14} {p10:>6} {p90:>6}{mark}")
