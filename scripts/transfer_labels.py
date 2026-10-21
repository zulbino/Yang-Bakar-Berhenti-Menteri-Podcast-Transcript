"""Copy raw.md's speaker labels onto the interview files' turns, without rewriting any text.

Owner, 2026-10-21: after the Nemotron relabel (ENGINEERING_LOG 2.34) only the labels changed, and a
full rewrite of 71 episodes would cost about 5,000 checker calls. Each interview.md turn is matched
to raw.md's words; it takes the label most of its matched words now carry, when that label holds at
least SHARE of them. interview-en.md and interview-ms.md hold the same turns in the same order, so
the same turn takes the same label there, but only when all three files have the same turn count
and the same old label at that position. Anything else is reported and left alone.

    python scripts/transfer_labels.py [tags...] [--write]
"""
import argparse
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

ROOT = Path(__file__).resolve().parent.parent
RAW_TURN = re.compile(r"^\[[\d:]+\]\s*([^:\n\[\]]{1,40}?):\s*(.*)$")
INT_TURN = re.compile(r"^\*\*([^*\n]{1,40}?):\*\*\s?(.*)$")
WORD = re.compile(r"[\w']+")
SHARE, MIN_WORDS = 0.7, 3


def raw_words(path):
    out = []
    for line in path.read_text(encoding="utf-8").split("# Raw Transcript", 1)[1].splitlines():
        m = RAW_TURN.match(line.strip())
        if m:
            out += [(m.group(1).strip(), w.lower()) for w in WORD.findall(m.group(2))]
    return out


def turns(text):
    """[(line index of the label, label, text)] for every **Label:** turn."""
    lines = text.split("\n")
    out = []
    for i, line in enumerate(lines):
        m = INT_TURN.match(line)
        if m:
            out.append([i, m.group(1).strip(), m.group(2)])
        elif out and line.strip() and not line.startswith(("---", "<!--", "#")):
            out[-1][2] += " " + line
    return lines, out


def relabel(lines, t, new):
    i, old = t[0], t[1]
    lines[i] = lines[i].replace(f"**{old}:**", f"**{new}:**", 1)


def episode(d, write):
    raw = raw_words(d / "raw.md")
    files = {k: d / f"interview{k}.md" for k in ("", "-en", "-ms")}
    if not files[""].exists():
        return None
    parsed = {k: turns(p.read_text(encoding="utf-8")) for k, p in files.items() if p.exists()}
    lines, mix = parsed[""]
    iw = [(n, w.lower()) for n, t in enumerate(mix) for w in WORD.findall(t[2])]
    sm = SequenceMatcher(None, [w for _, w in iw], [w for _, w in raw], autojunk=False)
    votes = [Counter() for _ in mix]
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            votes[iw[a + k][0]][raw[b + k][0]] += 1
    # A translation can hold one extra or merged turn; align the label sequences and map a
    # mixed turn only where it sits inside a run of identical labels.
    maps = {}
    for key, (_, ts) in parsed.items():
        s2 = SequenceMatcher(None, [x[1] for x in mix], [x[1] for x in ts], autojunk=False)
        maps[key] = {a_ + k: b_ + k for a_, b_, n in s2.get_matching_blocks() for k in range(n)}
    change, mixed, thin = [], 0, 0
    for n, (t, v) in enumerate(zip(mix, votes)):
        total = sum(v.values())
        if total < MIN_WORDS:
            thin += 1
            continue
        who, k = v.most_common(1)[0]
        if k / total < SHARE:
            mixed += 1
            continue
        if who != t[1]:
            change.append((n, t[1], who, t[2][:80]))
    missed = sum(1 for key in parsed for n, *_ in change if n not in maps[key])
    if write and change:
        for key, (ls, ts) in parsed.items():
            for n, old, new, _ in change:
                if n in maps[key]:
                    relabel(ls, ts[maps[key][n]], new)
            files[key].write_text("\n".join(ls), encoding="utf-8", newline="")
    return len(mix), change, mixed, thin, missed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="*")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    dirs = [common.raw_for_tag(t).parent for t in a.tags] or sorted(p.parent for p in ROOT.glob("episodes/*/*/raw.md"))
    tot = [0, 0, 0, 0]
    for d in dirs:
        r = episode(d, a.write)
        if r is None:
            continue
        n, change, mixed, thin, missed = r
        tot = [tot[0] + n, tot[1] + len(change), tot[2] + mixed, tot[3] + thin]
        flag = f"  {missed} not placed in a translation" if missed else ""
        print(f"{d.name[:40]:40s} turns {n:4d} | relabel {len(change):3d} | mixed {mixed:3d} | unmatched {thin:3d}{flag}")
    print(f"total: {tot[0]} turns, {tot[1]} relabelled, {tot[2]} left (two speakers), {tot[3]} left (unmatched)"
          + ("" if a.write else " -- dry run"))


if __name__ == "__main__":
    main()
