"""Rule 7 for a Nemotron-labelled raw.md: flag a speaker switch only where Nemotron itself is unsure.

check_overlap_boundaries.py takes the camera as the referee, so on an episode Nemotron labelled
it flags every switch where the two disagree, and on the owner's gold Nemotron is right far more
often than the camera (972 against 4,022 wrong-label words on ep65-68). Owner's decision
2026-10-19: such an episode is checked against Nemotron's own activity instead. A switch is
flagged when, over the last WORDS words before it or the first WORDS after it, the labelled
speaker is not clearly the most active (margin under MARGIN) or the other side's speaker is
also active (above OVERLAP), which is where two people talk at once.

Nemotron's speaker indices are named from the file itself: each index takes the label most of
its own words carry.

    python scripts/check_overlap_nemotron.py <tag> [--raw <copy>] [--links]
    python scripts/check_overlap_nemotron.py <tag> --raw <copy> --gold <owner raw.md>   # measure
"""
import argparse
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

ROOT = Path(__file__).resolve().parent.parent
TURN = re.compile(r"^\[[\d:]+\]\s*([^:\n\[\]]{1,40}?):\s*(.*)$")
WORD = re.compile(r"[\w']+")
FRAME, WORDS, MARGIN, OVERLAP = 0.01, 2, 0.3, 0.5


def words_of(path):
    out = []
    for line in Path(path).read_text(encoding="utf-8").split("# Raw Transcript", 1)[1].splitlines():
        m = TURN.match(line.strip())
        if m:
            out += [(m.group(1).strip(), t) for t in m.group(2).split()]
    return out


def timed(words, vid):
    asr = [(w.lower(), x["t"] / 1000, max(x.get("d", 0), 1) / 1000)
           for t in json.loads((ROOT / "data" / f"_mai_{vid}" / "mai_words.json").read_text(encoding="utf-8"))["turns"]
           for x in t["words"] for w in WORD.findall(x["w"] or "")]
    keys = [(WORD.findall(t.lower()) or [""])[0] for _, t in words]
    sm = SequenceMatcher(None, keys, [a[0] for a in asr], autojunk=False)
    span = [None] * len(words)
    for x, y, n in sm.get_matching_blocks():
        for k in range(n):
            span[x + k] = (asr[y + k][1], asr[y + k][2])
    last = (0.0, 0.0)
    for k, s in enumerate(span):
        span[k] = last = s or (last[0], 0.0)
    return span


def flags(tag, raw):
    head = Path(raw).read_text(encoding="utf-8").split("# Raw Transcript", 1)[0]
    vid = re.search(r"^video_id:\s*(\S+)", head, re.M).group(1)
    P = np.load(ROOT / "data" / "_voice" / f"{vid}_nemotron.npz")["probs"]
    words = words_of(raw)
    span = timed(words, vid)

    def act(i):
        t, d = span[i]
        a = P[int(t / FRAME):max(int(t / FRAME) + 1, int((t + d) / FRAME))]
        return a.mean(axis=0) if len(a) else np.zeros(P.shape[1])

    acts = [act(i) for i in range(len(words))]
    votes = {}
    for (lab, _), a in zip(words, acts):
        if a.max() > 0.5:
            votes.setdefault(int(a.argmax()), Counter())[lab] += 1
    index = {}
    for k, c in votes.items():                     # each label keeps its strongest index
        lab, n = c.most_common(1)[0]
        if n > index.get(lab, (None, 0))[1]:
            index[lab] = (k, n)
    index = {lab: k for lab, (k, _) in index.items()}

    out = []
    for i in range(1, len(words)):
        A, B = words[i - 1][0], words[i][0]
        if A == B or A not in index or B not in index:
            continue
        why = []
        for side, own, other, rng in (("end of", A, B, range(max(0, i - WORDS), i)),
                                      ("start of", B, A, range(i, min(len(words), i + WORDS)))):
            for j in rng:
                a = acts[j]
                if a[index[own]] - a[index[other]] < MARGIN:
                    why.append(f"{side} {own}: '{words[j][1]}' {own} {a[index[own]]:.2f} vs {other} {a[index[other]]:.2f}")
                    break
                if a[index[other]] > OVERLAP:
                    why.append(f"{side} {own}: '{words[j][1]}' both speak ({other} {a[index[other]]:.2f})")
                    break
        if why:
            out.append((i, int(span[i][0]), A, B, why))
    return vid, words, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--raw")
    ap.add_argument("--gold", help="owner's corrected raw.md: report how many real errors the flags cover")
    ap.add_argument("--links", action="store_true")
    a = ap.parse_args()
    raw = a.raw or common.raw_for_tag(a.tag)
    vid, words, out = flags(a.tag, raw)
    switches = sum(1 for i in range(1, len(words)) if words[i][0] != words[i - 1][0])
    print(f"{a.tag}: {len(out)} of {switches} switches flagged")
    if a.links:
        for i, s, A, B, why in out:
            print(f"  https://youtu.be/{vid}?t={max(0, s - 5)}  {A} -> {B}: {'; '.join(why)}")
    if a.gold:
        gold = words_of(a.gold)
        sm = SequenceMatcher(None, [w[1].lower() for w in words], [w[1].lower() for w in gold], autojunk=False)
        right = [None] * len(words)
        for x, y, n in sm.get_matching_blocks():
            for k in range(n):
                g = re.sub(r"\s*\(.*?\)\s*$", "", gold[y + k][0])
                right[x + k] = re.sub(r"\s*\(.*?\)\s*$", "", words[x + k][0]) == g
        bad = {i for i in range(1, len(words)) if words[i][0] != words[i - 1][0]
               and any(right[j] is False for j in range(max(0, i - 3), min(len(words), i + 3)))}
        hit = {i for i, *_ in out}
        print(f"  switches with a wrong word within 3: {len(bad)}; flagged {len(bad & hit)} "
              f"({len(bad & hit) / max(1, len(bad)):.0%}); flags on a clean switch {len(hit - bad)}")


if __name__ == "__main__":
    main()
