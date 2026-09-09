"""Before a re-cut is written: does every recorded owner decision on this episode survive it?

WHY. The owner's speaker decisions live in tracked JSON under data/ (adjudications, regions
confirmed on video, `Speaker ?` namings, the gold passage). ep61 lost one such decision once
because a later pass never looked (ATTRIBUTION_PASS.md, "Read the episode's history first").
This makes the look mechanical: for every decision it finds the turn in the CURRENT raw.md by
its stamp, takes that turn's opening words, finds those words in the CANDIDATE file, and
requires the candidate's label to be the owner's. A decision it cannot locate is reported,
never silently passed.

The gold passage is checked differently: the owner dictated it from ear, so its text is not
raw.md's text. Its region is required to be byte-identical between current and candidate.

  python scripts/check_owner_decisions.py ep61 data/_nightly/ep61_preview_raw.md
"""
import glob
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"^\[([\d:]+)\]\s*([^:\n]{0,40}?):\s*(.*)$", re.M)
DECISION_FILES = ["speaker_adjudications.json", "speaker_video_confirmed.json",
                  "speaker_video_confirmed_ep61_round2.json", "speaker_q_video_confirmed.json",
                  "speaker_from_gold.json"]


def secs(t):
    q = [int(x) for x in t.split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(q)))


def short(w):
    return w.split(" (")[0].strip()


def main():
    tag, candidate = sys.argv[1], sys.argv[2]
    hits = glob.glob(str(ROOT / f"episodes/*/*-{tag}-*/raw.md"))
    if len(hits) != 1:
        sys.exit(f"{len(hits)} episodes match {tag}")
    cur_text = io.open(hits[0], encoding="utf-8").read()
    cand_text = io.open(candidate, encoding="utf-8").read()
    vid = re.search(r"video_id:\s*(\S+)", cur_text).group(1)
    cur, cand = BLOCK.findall(cur_text), BLOCK.findall(cand_text)

    def current_block(stamp):
        return [(w, t) for st, w, t in cur if secs(st) == secs(stamp)]

    def candidate_labels(snippet):
        return sorted({short(w) for _, w, t in cand if snippet in t})

    checks = []   # (source, owner's label, snippet of the turn's text)
    for name in DECISION_FILES:
        path = ROOT / "data" / name
        if not path.exists():
            continue
        data = json.load(io.open(path, encoding="utf-8"))
        for section, rules in data.items():
            if section.startswith("_") or not isinstance(rules, dict):
                continue
            blob = json.dumps(rules, ensure_ascii=False)
            if tag not in section.lower() and vid not in blob:
                continue
            for stamp, r in rules.items():
                if not stamp[:1].isdigit() or not isinstance(r, dict):
                    continue
                src = f"{name}:{section}@{stamp}"
                for who, snip, at in r.get("split", []):
                    if snip:
                        checks.append((src, who, snip[:45]))
                if "who" in r:
                    # Locate by the rule's own text when it has one. A stamp is NOT unique
                    # in this corpus (a split re-uses its parent's stamp), so ep61's
                    # 1:22:10 names two blocks and the first one is not the owner's.
                    snip = r.get("text_now") or r.get("text_was_startswith") or r.get("text_was")
                    if not snip:
                        blk = current_block(r.get("at_now", stamp))
                        snip = blk[0][1] if blk else ""
                    checks.append((src, r["who"], snip[:45]))

    ok = bad = missing = 0
    for src, who, snip in checks:
        if len(snip.split()) < 2:
            missing += 1
            print(f"  cannot locate ({src}): no usable text for the turn the owner named {who}")
            continue
        labels = candidate_labels(snip)
        if not labels:
            missing += 1
            print(f"  NOT FOUND in candidate ({src}): {who} | {snip}")
        elif labels == [short(who)]:
            ok += 1
        else:
            bad += 1
            print(f"  MISMATCH ({src}): owner says {who}, candidate has {labels} | {snip}")

    # The gold passage: region byte-identical.
    truth = json.load(io.open(ROOT / "data" / "speaker_ground_truth.json", encoding="utf-8"))
    gold_ok = None
    for key, g in truth.items():
        if not isinstance(g, dict) or g.get("video_id") != vid:
            continue
        m = re.findall(r"(\d{1,2}:\d{2}(?::\d{2})?)", g.get("region", ""))
        if len(m) >= 2:
            lo, hi = secs(m[0]), secs(m[1])
            a = [b for b in cur if lo - 60 <= secs(b[0]) <= hi + 60]
            b = [b for b in cand if lo - 60 <= secs(b[0]) <= hi + 60]
            gold_ok = a == b
            print(f"  gold passage {g['region']!r}: {len(a)} current vs {len(b)} candidate blocks, "
                  f"{'IDENTICAL' if gold_ok else 'CHANGED'}")

    print(f"\n{tag}: {len(checks)} owner decisions -- {ok} preserved, {bad} mismatched, "
          f"{missing} not locatable" + ("" if gold_ok is None else f"; gold passage {'kept' if gold_ok else 'CHANGED'}"))
    sys.exit(1 if bad or gold_ok is False else 0)


if __name__ == "__main__":
    main()
