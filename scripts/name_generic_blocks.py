"""Replace a placeholder speaker label with a name, where the evidence supports one.

WHY. A rebuilt raw can still carry a placeholder. `Speaker ?` comes from the old transcript
through the short-turn rule -- a turn of three words or fewer keeps the label it had -- and
`Overlapping Speaker` is MAI's own cluster name leaking into the file. ep62 shipped with 9
placeholders and ep60 with 1, all of them one or two words. A placeholder is not a decision
by anyone, and the QA rule the owner set on ep61 is zero of them.

TWO SOURCES, IN THIS ORDER, and nothing else:

  1. The camera. If it names one speaker for the block's seconds, that is the answer.
  2. Failing that, the blocks either side. If both carry the same real name and the block is
     at most MAX_WORDS long, it belongs to that person. A one-word "Kertas." between two
     Rafizi blocks is Rafizi finishing his own sentence.

Anything else is printed and left alone. The text is never used as evidence: register,
sentence continuation and word overlap have each been measurably wrong on this corpus.

`Multiple speakers` is NEVER touched. That label is a real finding -- the owner's own
tie-breaker for crosstalk nobody can split -- not a placeholder.

Labels only. The word sequence is asserted identical before anything is written, and a block
named by a recorded owner decision is skipped and printed.

  python scripts/name_generic_blocks.py ep62
  python scripts/name_generic_blocks.py ep62 --write
"""
import argparse
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"^\[([\d:]+)\]\s*([^:\n]{0,40}?):\s*(.*)$", re.M)
PLACEHOLDER = re.compile(r"^(speaker\s*\??\s*\d*|overlapping speaker|unknown|spk_?\d+|"
                         r"speaker_\d+)$", re.I)
MAX_WORDS = 6
DECISION_FILES = ["speaker_adjudications.json", "speaker_video_confirmed.json",
                  "speaker_video_confirmed_ep61_round2.json", "speaker_q_video_confirmed.json",
                  "speaker_from_gold.json", "forced_labels.json"]


def secs(t):
    q = [int(x) for x in t.split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(q)))


def camera_seconds(path):
    out = {}
    for line in io.open(path, encoding="utf-8"):
        f = line.split()
        if f[0] != "SPEAKER":
            continue
        a, dur = float(f[3]), float(f[4])
        for t in range(int(a), int(a + dur) + 1):
            out[t] = f[7].replace("_", " ")
    return out


def decision_texts(tag):
    out = []
    for name in DECISION_FILES:
        path = ROOT / "data" / name
        if not path.exists():
            continue
        for section, rules in json.load(io.open(path, encoding="utf-8")).items():
            if section.startswith("_") or tag not in section.lower():
                continue
            for r in (rules.values() if isinstance(rules, dict) else rules):
                if isinstance(r, dict):
                    for key in ("text", "text_now", "text_was", "text_was_startswith"):
                        if r.get(key):
                            out.append(r[key].lower())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--reference", help="default data/camera_ref_<tag>.rttm")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    path = common.raw_for_tag(a.tag)
    text = path.read_text(encoding="utf-8")
    reference = Path(a.reference or ROOT / "data" / f"camera_ref_{a.tag}.rttm")
    camera = camera_seconds(reference) if reference.exists() else {}
    blocks = BLOCK.findall(text)
    decided = decision_texts(a.tag)

    named, left = [], []
    for i, (st, who, said) in enumerate(blocks):
        if not PLACEHOLDER.match(who.strip()):
            continue
        end = secs(blocks[i + 1][0]) if i + 1 < len(blocks) else secs(st) + 5
        vote = Counter(x for x in (camera.get(t) for t in range(secs(st), max(secs(st) + 1, end)))
                       if x)
        why, pick = None, None
        if vote and len(vote) == 1:
            pick, why = next(iter(vote)), f"camera {dict(vote)}"
        elif vote:
            pick, why = vote.most_common(1)[0][0], f"camera majority {dict(vote)}"
        elif (0 < i < len(blocks) - 1 and blocks[i - 1][1] == blocks[i + 1][1]
                and not PLACEHOLDER.match(blocks[i - 1][1].strip())
                and len(said.split()) <= MAX_WORDS):
            pick, why = blocks[i - 1][1], "camera blind, same speaker either side"
        if not pick:
            left.append((st, who, said, "no camera and the neighbours differ"))
            continue
        if any(d[:40] in said.lower() or said.lower()[:40] in d for d in decided):
            left.append((st, who, said, "an owner decision names this text"))
            continue
        named.append((st, who, pick, said, why))

    for st, who, pick, said, why in named:
        print(f"  [{st}] {who} -> {pick} ({why}): {said[:70]}")
    for st, who, said, why in left:
        print(f"  LEFT as {who} at [{st}], {why}: {said[:70]}")
    print(f"{a.tag}: {len(named)} placeholder(s) named, {len(left)} left")

    if not named or not a.write:
        if named:
            print("\n-- dry run, pass --write to apply")
        return

    out = text
    for st, who, pick, said, _ in named:
        old = f"[{st}] {who}: {said}"
        if out.count(old) != 1:
            sys.exit(f"REFUSING: {old[:60]!r} is not unique")
        out = out.replace(old, f"[{st}] {pick}: {said}")
    strip = re.compile(r"^\[[\d:]+\]\s*[^:\n]{0,40}?:\s*", re.M)
    if strip.sub(" ", text).split() != strip.sub(" ", out).split():
        sys.exit("REFUSING TO WRITE: the word sequence changed")
    path.write_text(out, encoding="utf-8")
    print(f"wrote {path} -- labels only")


if __name__ == "__main__":
    main()
