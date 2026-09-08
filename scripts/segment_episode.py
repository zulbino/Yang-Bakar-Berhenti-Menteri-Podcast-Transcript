"""Cut an episode into rewrite-sized segments, on the publisher's own chapter marks.

WHY. The rewrite stage has failed the same way on every cheap model tried: Haiku dropped
about half the translation, a local Sailor2 truncated 32% and invented a claim, Gemini
finished 73-82% and split one name into three. None of them misunderstood the material;
they ran out of road on a three-hour transcript. A segment of one or two thousand words is
a length a small model can actually finish, and it can be gated and retried on its own
instead of re-running three hours of audio's worth of text.

WHERE THE BOUNDARIES COME FROM. The YouTube description carries the chapter marks the show
itself wrote, so the topic boundaries are the publisher's rather than ours -- ep62 has eight.
That is not enough on its own: ep62's FELDA chapter is 26,730 words of the episode's 30,000,
because the show marks one chapter and then talks for three hours. So a chapter longer than
MAX_WORDS is cut again at turn boundaries, never mid-turn, preferring a point where the
speaker changes so a segment does not open in the middle of somebody's answer.

An episode with no chapter marks in its description falls back to size-only splitting.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]\s*([^:\n]{1,40}):(.*)$", re.M)
CHAPTER = re.compile(r"^\s*((?:\d+:)?\d+:\d+)\s+(.{3,80})$", re.M)
MAX_WORDS = 1200
MIN_WORDS = 200      # below this a tail is folded back into the segment before it


def seconds(stamp):
    parts = [int(p) for p in stamp.split(":")]
    return parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]


def hhmmss(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def chapters_of(video_id):
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    entry = next((e for e in manifest if e["video_id"] == video_id), None)
    text = (entry or {}).get("description") or ""
    return [(seconds(s), title.strip()) for s, title in CHAPTER.findall(text)]


def split_turns(turns, title, max_words):
    """Cut one chapter's turns into pieces of at most max_words, at turn boundaries."""
    pieces, current, count = [], [], 0
    for i, turn in enumerate(turns):
        words = len(turn[2].split())
        speaker_changes = i + 1 < len(turns) and turns[i + 1][1] != turn[1]
        current.append(turn)
        count += words
        # cut once the piece is full AND the next turn starts a new speaker, so a segment
        # never opens mid-answer; force a cut at 1.5x rather than run away
        if (count >= max_words and speaker_changes) or count >= max_words * 1.5:
            pieces.append(current)
            current, count = [], 0
    if current:
        if pieces and count < MIN_WORDS:
            pieces[-1].extend(current)
        else:
            pieces.append(current)
    return [(f"{title} ({n + 1}/{len(pieces)})" if len(pieces) > 1 else title, p)
            for n, p in enumerate(pieces)]


def segment(raw_path, video_id, runtime, max_words=MAX_WORDS):
    turns = [(seconds(s), label.strip(), text.strip())
             for s, label, text in BLOCK.findall(raw_path.read_text(encoding="utf-8"))]
    marks = chapters_of(video_id)
    if not marks:
        marks = [(0, "Full episode")]
    out = []
    for i, (start, title) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else runtime
        inside = [t for t in turns if start <= t[0] < end]
        if not inside:
            continue
        for piece_title, piece in split_turns(inside, title, max_words):
            out.append({
                "index": len(out),
                "title": piece_title,
                "start": piece[0][0],
                "end": piece[-1][0],
                "turns": len(piece),
                "words": sum(len(t[2].split()) for t in piece),
                "speakers": sorted({t[1] for t in piece}),
                "text": "\n\n".join(f"[{hhmmss(t[0])}] {t[1]}: {t[2]}" for t in piece),
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--raw", help="transcript to segment; defaults to the episode's raw.md")
    ap.add_argument("--max-words", type=int, default=MAX_WORDS)
    ap.add_argument("--out", help="write the segments as json")
    args = ap.parse_args()

    import glob
    matches = glob.glob(str(ROOT / "episodes" / "*" / f"*-{args.tag}-*"))
    if len(matches) != 1:
        sys.exit(f"{args.tag} matched {len(matches)} episodes")
    fields, _ = common.read_frontmatter_body(Path(matches[0]) / "raw.md")
    raw_path = Path(args.raw) if args.raw else Path(matches[0]) / "raw.md"

    segments = segment(raw_path, fields["video_id"], fields["duration_seconds"], args.max_words)
    total = sum(s["words"] for s in segments)
    print(f"{args.tag}: {len(segments)} segments, {total:,} words, from {raw_path.name}")
    for s in segments:
        print(f"  {s['index']:3}  {hhmmss(s['start'])}-{hhmmss(s['end'])}  {s['turns']:4} turns "
              f"{s['words']:5} words  {'+'.join(x.split()[0] for x in s['speakers']):22} "
              f"{s['title'][:46]}")
    if args.out:
        Path(args.out).write_text(json.dumps(segments, indent=1, ensure_ascii=False),
                                  encoding="utf-8")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
