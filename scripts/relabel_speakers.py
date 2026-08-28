"""Rename speaker labels in an episode's raw.md, swaps included.

Renaming labels one at a time with sed corrupts a swap: rewriting A->B first, then
B->A, leaves everything under A. This applies the whole mapping in one pass over the
block headers, so a swap stays a swap.

Only the label inside a block header is touched. Body text is left alone, because a
name spoken inside dialogue is part of the transcript, not a label.

  python scripts/relabel_speakers.py ep36 "Cincong=Rafizi" "Rafizi=Cincong"
  python scripts/relabel_speakers.py ep42 "Haziq=Rafizi" --dry-run
"""
import argparse
import glob
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# [1:23:45] Label: text   -- label capped at 40 chars, same shape qa_check.py uses
HEADER_RE = re.compile(r"^(\[(?:\d+:)?\d+:\d+\]\s*)([^:\n]{1,40})(:)", re.M)


def relabel(text, mapping):
    counts = {}

    def sub(m):
        prefix, label, colon = m.groups()
        key = label.strip()
        if key not in mapping:
            return m.group(0)
        counts[key] = counts.get(key, 0) + 1
        return f"{prefix}{mapping[key]}{colon}"

    return HEADER_RE.sub(sub, text), counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode", help="episode tag, e.g. ep36")
    ap.add_argument("renames", nargs="+", metavar="OLD=NEW")
    ap.add_argument("--file", default="raw.md")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    mapping = {}
    for r in args.renames:
        old, _, new = r.partition("=")
        if not old or not new:
            raise SystemExit(f"bad rename {r!r}, expected OLD=NEW")
        mapping[old] = new

    matches = glob.glob(str(ROOT / "episodes" / "*" / f"*-{args.episode}-*"))
    if len(matches) != 1:
        raise SystemExit(f"{args.episode} matched {len(matches)} episode folders: {matches}")
    path = Path(matches[0]) / args.file

    text = path.read_text(encoding="utf-8")
    new_text, counts = relabel(text, mapping)

    for old, new in mapping.items():
        print(f"  {old!r} -> {new!r}: {counts.get(old, 0)} block(s)")
    missing = [o for o in mapping if not counts.get(o)]
    if missing:
        raise SystemExit(f"label(s) never matched, refusing to write: {missing}")

    if args.dry_run:
        print("dry run, nothing written")
        return
    path.write_text(new_text, encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
