"""Do the corrected regions actually read the right host in the file a READER opens?

This is the only check that measures the thing an attribution pass is for. gate_rewrite's
attribution metric scores the whole episode and is the right promotion gate; this answers
the narrower question region by region, which is what tells you whether the pass landed.

On ep61 it is what showed the regeneration took: the Malay renderings went from 5 of 15
regions correct to 12 of 15, and named the three that did not (the shortest, each merged
back into a neighbouring turn by the rewrite's own re-segmentation).

LIMITATION, and it is not small: matching is by Malay word overlap against the region's
raw.md text, so it CANNOT read interview-en.md. Every English row comes back "no match" by
construction. That is a gap in this tool, not a finding about the file.

Matching has to be fuzzy at all because the published files are a rewrite -- lightly
cleaned, punctuated, sometimes reordered within a turn -- so an exact search finds nothing.

  python scripts/check_region_labels.py ep61 data/_audit_ep61_postfix.json
"""
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sense_speakers import episode_dir

PUB = re.compile(r"^\*\*([^*\n]{1,40}?):\*\*\s*(.*)$", re.M)


def words(s):
    return [w for w in re.findall(r"[\w']+", s.lower()) if len(w) > 3]


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "ep61"
    audit = json.loads(Path(sys.argv[2] if len(sys.argv) > 2
                            else "data/_audit_ep61_postfix.json").read_text(encoding="utf-8"))
    # region numbers that were applied; everything else in the audit was skipped
    conf = os.environ.get("REGIONS")
    confirmed = ({int(x) for x in conf.split(",")} if conf
                 else set(range(1, len(audit["regions"]) + 1)))
    folder = episode_dir(tag)

    for name in ("interview.md", "interview-ms.md", "interview-en.md"):
        f = folder / name
        if not f.exists():
            continue
        turns = [(m.group(1).strip(), set(words(m.group(2))), m.group(2))
                 for m in PUB.finditer(f.read_text(encoding="utf-8"))]
        print(f"\n=== {name}: {len(turns)} published turns ===")
        print(f"{'reg':>4} {'sensed':>8} {'published label':>16} {'ovl':>5}  verdict")
        agree = wrong = weak = 0
        for n, r in enumerate(audit["regions"], 1):
            if n not in confirmed:
                continue
            rw = set(words(r["text"]))
            if not rw:
                continue
            best, score = None, 0.0
            for lab, tw, _ in turns:
                ov = len(rw & tw) / len(rw)
                if ov > score:
                    best, score = lab, ov
            if score < 0.15:
                verdict, weak = "no match", weak + 1
            elif best == r["name"]:
                verdict, agree = "already correct", agree + 1
            else:
                verdict, wrong = "STILL OLD LABEL", wrong + 1
            print(f"{n:>4} {r['name']:>8} {str(best):>16} {score:>5.0%}  {verdict}")
        print(f"  already correct {agree}   still wrong {wrong}   unmatched {weak}")


if __name__ == "__main__":
    main()
