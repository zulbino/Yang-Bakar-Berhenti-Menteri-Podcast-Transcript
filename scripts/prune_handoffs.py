"""Delete every HANDOFF_*.md except the newest two.

WHY THIS EXISTS. Owner's decision 2026-09-15, after four had piled up: *"why is there
accumulated handoff md files, just delete those after one session ahead perhaps"*. A handoff
is session state and CLAUDE.md already says it goes stale in hours, so an old one is not a
record, it is a decoy. CLAUDE.md's own opening paragraph had named `HANDOFF_2026-09-13.md`
and `HANDOFF_2026-09-12.md` for two days after they stopped being the newest, which is
exactly how a session ends up reading the wrong corpus state.

WHY TWO AND NOT ONE. The newest can be mid-write when a session ends unexpectedly. The one
before it is the fallback. Anything older is superseded twice over.

ORDERED BY THE DATE IN THE FILENAME, not by mtime. A file gets touched when it is read or
copied, and `HANDOFF_2026-09-15.md` is the newest whatever its timestamp says.

They are gitignored, so this deletes untracked local files and never touches history.

  python scripts/prune_handoffs.py            # report only
  python scripts/prune_handoffs.py --write
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP = 2
STAMP = re.compile(r"^HANDOFF_(\d{4}-\d{2}-\d{2})\.md$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", type=int, default=KEEP)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    dated = []
    for p in ROOT.glob("HANDOFF_*.md"):
        m = STAMP.match(p.name)
        if not m:
            print(f"SKIPPING {p.name}: the name carries no HANDOFF_YYYY-MM-DD.md date")
            continue
        dated.append((m.group(1), p))
    dated.sort(reverse=True)

    keep, drop = dated[:a.keep], dated[a.keep:]
    for _, p in keep:
        print(f"keep   {p.name}")
    for _, p in drop:
        print(f"DELETE {p.name}")
        if a.write:
            p.unlink()
    print(f"\n{len(keep)} kept, {len(drop)} {'deleted' if a.write else 'to delete'}"
          + ("" if a.write or not drop else " -- pass --write"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
