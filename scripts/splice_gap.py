"""Splice a newly-transcribed stretch into an episode's raw.md.

Keeps the verified head and tail verbatim and replaces only the damaged middle.
Cluster names come from the episode's own existing labels: the clip starts before
the loss, so its opening turns overlap audio whose speaker is already known, and
matching them by trigram overlap (not by timestamp, which can be offset by tens
of seconds) yields the mapping.

  python scripts/_splice_gap.py ep00 --clip-start 3600 --keep-until 3677 \
      --gap-from 4046 --gap-to 7844 --tail-from 7860
"""
import argparse, json, re, sys
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import episode_path, episode_slug, read_frontmatter_body, frontmatter_md
from qa_check import timestamped_blocks

ROOT = Path(__file__).resolve().parent.parent
LABEL_RE = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]\s*([^:\n]{1,40}):\s*(.*)", re.S)

ap = argparse.ArgumentParser()
ap.add_argument("tag")
ap.add_argument("--clip-start", type=int, required=True)
ap.add_argument("--keep-until", type=int, required=True, help="last CLAIMED ts kept from the head")
ap.add_argument("--gap-from", type=int, required=True, help="first TRUE audio second to take from the new ASR")
ap.add_argument("--gap-to", type=int, required=True, help="last TRUE audio second to take from the new ASR")
ap.add_argument("--tail-from", type=int, default=None, help="first CLAIMED ts kept from the tail")
ap.add_argument("--model-note", default="mesolitica/malaysian-whisper-medium-v2")
ap.add_argument("--match-all", action="store_true",
                help="match new turns against every old turn, not just the overlap "
                     "window -- for episodes whose old timestamps are wrong throughout "
                     "but whose text and labels are still good")
ap.add_argument("--map", action="append", default=[],
                help="override a cluster name, e.g. --map 'Speaker 3=Audience'")
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()

man = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
ep = [e for e in man if "-" + a.tag + "-" in episode_slug(e)][0]
raw_path = ROOT / "episodes" / episode_path(ep) / "raw.md"
fm, body = read_frontmatter_body(raw_path)
blocks = timestamped_blocks(body)
gap_md = (ROOT / "data" / f"_{a.tag}_gap_raw.md").read_text(encoding="utf-8")

def toks(t):
    return re.sub(r"[^\w\s]", " ", t.lower()).split()

def grams(t, n=3):
    w = toks(t)
    return set(tuple(w[i:i+n]) for i in range(len(w)-n+1))

def secs(ts):
    p = [int(x) for x in ts.split(":")]
    while len(p) < 3:
        p.insert(0, 0)
    return p[0]*3600 + p[1]*60 + p[2]

def fmt(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"[{h}:{m:02d}:{s:02d}]" if h else f"[{m:02d}:{s:02d}]"

gap_turns = []
for line in gap_md.splitlines():
    m = LABEL_RE.match(line.strip())
    if m and m.group(3).strip():
        gap_turns.append((a.clip_start + secs(m.group(1)), m.group(2).strip(), m.group(3).strip()))

# --- name the clusters from the overlap with already-verified labels ---
known = [(ts, m.group(2).strip(), grams(m.group(3)))
         for ts, blk in blocks
         if (m := LABEL_RE.match(blk.strip())) and (a.match_all or a.clip_start - 300 <= ts <= a.gap_from + 300)]
votes = defaultdict(Counter)
for t, cluster, text in gap_turns:
    if t >= a.gap_from:
        continue
    g = grams(text)
    if len(g) < 4:
        continue
    best, name = 0, None
    for _, nm, kg in known:
        if kg:
            sc = len(g & kg) / len(g)
            if sc > best:
                best, name = sc, nm
    if best >= 0.30:
        votes[cluster][name] += 1

mapping = {}
print(f"overlap {a.clip_start}-{a.gap_from}s, {len(known)} verified turns to match against")
for cluster, c in sorted(votes.items()):
    win, n = c.most_common(1)[0]
    mapping[cluster] = win
    print(f"  {cluster:12s} -> {win:18s} {n/sum(c.values()):.0%} ({dict(c)})")
for _ov in a.map:
    _c, _n = _ov.split("=", 1)
    mapping[_c.strip()] = _n.strip()
    print(f"  {_c.strip():12s} -> {_n.strip():18s} (manual override)")
present = sorted({c for _, c, _ in gap_turns})
missing = [c for c in present if c not in mapping]
print(f"  clusters present: {present}")
if missing:
    print(f"  UNMAPPED (left as-is, need audio): {missing}")

# --- assemble ---
out = [(ts, blk.strip()) for ts, blk in blocks if ts <= a.keep_until]
kept_head = len(out)
added = 0
for t, cluster, text in gap_turns:
    if not (a.gap_from < t < a.gap_to):
        continue
    out.append((t, f"{fmt(t)} {mapping.get(cluster, cluster)}: {text}"))
    added += 1
kept_tail = 0
if a.tail_from is not None:
    for ts, blk in blocks:
        if ts >= a.tail_from:
            out.append((ts, blk.strip()))
            kept_tail += 1
dropped = len(blocks) - kept_head - kept_tail

out.sort(key=lambda x: x[0])
prev = -1
for i, (t, b) in enumerate(out):
    if t < prev:
        raise SystemExit(f"backward jump at {i}: {t} after {prev}\n  {b[:80]}")
    prev = t

print(f"\nhead {kept_head} blocks (<= {a.keep_until}s) | new {added} turns "
      f"({a.gap_from}-{a.gap_to}s) | tail {kept_tail} blocks (>= {a.tail_from}) | dropped {dropped}")
new_body = "# Raw Transcript" + chr(10)*2 + (chr(10)*2).join(b for _, b in out)
print(f"total {len(out)} blocks, {len(new_body)} chars (was {len(body)})")
if a.dry_run:
    print("\n-- dry run, not written --")
else:
    old = fm.get("model", "")
    fm["model"] = f"{old} + {a.model_note} ({a.gap_from}-{a.gap_to}s)" if old else a.model_note
    raw_path.write_text(frontmatter_md(fm, new_body), encoding="utf-8")
    print(f"wrote {raw_path}")
