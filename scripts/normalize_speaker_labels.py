"""Normalise speaker labels in interview*.md to the short-name convention.

Run this after ANY rewrite regeneration, alongside scripts/rebuild_roster.py: the rewrite
stage reverts to "Rafizi Ramli" and "Pa'an" every time, and the archive uses one form for
each person in every file (see ARCHITECTURE.md, speaker naming convention).

Only the label position is touched. '**Rafizi Ramli:**' at the start of a turn becomes
'**Rafizi:**', while "Rafizi Ramli" spoken inside dialogue stays exactly as said -- that
is transcript, not a label.

  python scripts/normalize_speaker_labels.py            # dry run
  python scripts/normalize_speaker_labels.py --write    # apply
"""
import re, glob, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WRITE = "--write" in sys.argv
RENAME = {"Rafizi Ramli": "Rafizi", "Pa'an": "Farhan (Pa'an)", "Haziq Azfar": "Haziq"}
LABEL = re.compile(r"^\*\*([^*:\n]{1,45}):\*\*", re.M)

counts, files = {}, 0
for f in sorted(glob.glob(str(ROOT / "episodes" / "*" / "*" / "interview*.md"))):
    text = Path(f).read_text(encoding="utf-8")
    hit = {}

    def sub(m):
        name = m.group(1).strip()
        if name not in RENAME:
            return m.group(0)
        hit[name] = hit.get(name, 0) + 1
        return f"**{RENAME[name]}:**"

    new = LABEL.sub(sub, text)
    if hit:
        files += 1
        for k, v in hit.items():
            counts[k] = counts.get(k, 0) + v
        if WRITE:
            Path(f).write_text(new, encoding="utf-8")
for k, v in sorted(counts.items(), key=lambda x: -x[1]):
    print(f"  {k!r} -> {RENAME[k]!r}: {v} labels")
print(f"\n{files} files " + ("written" if WRITE else "would change (dry run)"))
