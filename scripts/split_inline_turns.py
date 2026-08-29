"""Give every inline turn marker in raw.md its own block, and drop wordless turns.

`check_published.inline-turn-marker` flags a raw.md block that carries a second
`[mm:ss] Label:` marker mid-paragraph. Nothing fixed it, so the defect survived every
rewrite: the block is attributed to whoever opens it, and the words after the inline
marker are published under that wrong name. ep53 [11:15] put four sentences of a
co-host's speech inside a Rafizi block.

The second failure the same split exposes is a leading label with NO words at all:

    [2:05:27] Speaker 3: [2:05:29] Speaker 1: Baik Dah meletup pun ...
    [2:15:25] Rafizi: [2:15:26] Speaker 2: RM35,000. [2:15:28] Speaker 1: Okeylah ...

`Speaker 3` and `Rafizi` there hold zero transcribed words -- the diarizer opened a
segment on a cluster that the ASR returned nothing for. A turn with no words is not a
turn, and keeping it costs twice: it invents a speaker who says nothing, and the
rewrite reads the empty label as the owner of the text that follows. So a segment whose
text is empty after the split is dropped, not kept.

WHY THIS IS NOT A GUESS. Splitting asserts only what the markers already say -- each
marker names its own speaker and timestamp. It moves no words between labels and
renames nothing. That is the whole reason to prefer it to any inference about who
"really" spoke: the fix needs no ear. Deciding whether ep53's `Speaker 2` at [11:41] is
Haziq or Farhan is a separate question this tool deliberately does not touch.

  python scripts/split_inline_turns.py            # dry run, per-episode counts
  python scripts/split_inline_turns.py --write
  python scripts/split_inline_turns.py ep53 --write
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import episode_path, resolve_tag

# A turn marker: timestamp, then a label that stops at the colon. A label never contains
# a colon or an opening bracket, which is what keeps the scan from running past the next
# marker and swallowing it.
MARKER = re.compile(r"\[(?:\d+:)?\d{1,2}:\d{2}\]\s+[^:\n\[]{1,40}:")


def split_block(line):
    """Return the blocks `line` should become, plus the count of wordless turns dropped."""
    marks = list(MARKER.finditer(line))
    if len(marks) < 2 or marks[0].start() != 0:
        return [line], 0
    bounds = [m.start() for m in marks] + [len(line)]
    blocks, dropped = [], 0
    for i, m in enumerate(marks):
        text = line[m.end():bounds[i + 1]].strip()
        if not text:
            dropped += 1
            continue
        blocks.append(f"{m.group(0)} {text}")
    return blocks, dropped


def fix(body):
    out, splits, dropped = [], 0, 0
    for line in body.splitlines():
        blocks, d = split_block(line)
        if len(blocks) > 1 or d:
            splits += len(blocks) + d - 1
            dropped += d
        out.append("\n\n".join(blocks) if blocks else "")
    tail = "\n" if body.endswith("\n") else ""
    return "\n".join(out) + tail, splits, dropped


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    write = "--write" in sys.argv
    paths = ([episode_path(resolve_tag(t)) / "raw.md" for t in args] if args
             else sorted(Path("episodes").glob("*/*/raw.md")))

    total_s = total_d = touched = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        new, splits, dropped = fix(text)
        if not splits:
            continue
        touched += 1
        total_s += splits
        total_d += dropped
        print(f"  {splits:>3} split  {dropped:>3} wordless  {path.parent.name[:52]}")
        if write:
            path.write_text(new, encoding="utf-8")

    print(f"\n{total_s} inline marker(s) given their own block across {touched} episode(s); "
          f"{total_d} wordless turn(s) dropped")
    print("written -- regenerate the published files, they still hold the merged text"
          if write else "dry run -- pass --write to apply")


if __name__ == "__main__":
    main()
