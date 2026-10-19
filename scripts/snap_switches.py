"""Move a speaker switch to the nearest sentence end, without changing who speaks.

Nemotron finds the right speakers but often places the switch a word or two early or late
(owner's ear on the relabel review, 2026-10-19: "Ya. Kita semua kena scam." had "Ya." left with
the previous speaker). A switch within K words of a sentence end (. ? !) moves to it. Only the
words between the switch and the edge move, the move never crosses another switch or a frozen
(owner-ruled) word, so no speaker is invented and no turn disappears.

Measured on the owner's gold, ep65-68 (ENGINEERING_LOG 2.31): K=2 takes the Nemotron labels from
1,044 to 972 wrong-label words and improves every episode; K=3 and treating a comma as an edge
are both worse. voice_label_raw.py calls snap(); the command line is for testing a copy.

    python scripts/snap_switches.py <raw copy> --out <path> [--k 2] [--comma]
"""
import argparse
import re
from pathlib import Path

TURN = re.compile(r"^\[([\d:]+)\]\s*([^:\n\[\]]{1,40}?):\s*(.*)$")
STRONG = re.compile(r"[.?!]['\"”)]*$")
WEAK = re.compile(r"[,;:]['\"”)]*$")


def snap(labels, tokens, k=2, comma=False, frozen=frozenset()):
    """Relabel `labels` in place; returns the number of switches moved."""
    def edge(j):                                     # is there a sentence end before word j?
        if j <= 0 or j >= len(tokens):
            return False
        return bool(STRONG.search(tokens[j - 1]) or (comma and WEAK.search(tokens[j - 1])))

    moved = 0
    for i in range(1, len(labels)):
        if labels[i] == labels[i - 1] or edge(i):
            continue
        A, B = labels[i - 1], labels[i]
        for e in [x for d in range(1, k + 1) for x in (i - d, i + d)]:
            if not (0 < e < len(labels) and edge(e)):
                continue
            span = range(e, i) if e < i else range(i, e)
            keep, side = (A, B) if e < i else (B, A)
            if all(labels[j] == keep and j not in frozen for j in span):
                for j in span:
                    labels[j] = side
                moved += 1
                break
    return moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("raw")
    ap.add_argument("--out", required=True)
    ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--comma", action="store_true", help="a comma also counts as an edge")
    a = ap.parse_args()

    head, body = Path(a.raw).read_text(encoding="utf-8").split("# Raw Transcript", 1)
    words = []
    for line in body.splitlines():
        m = TURN.match(line.strip())
        if m:
            words += [(m.group(2).strip(), w, m.group(1)) for w in m.group(3).split()]
    labels = [w[0] for w in words]
    moved = snap(labels, [w[1] for w in words], a.k, a.comma)
    blocks = []
    for lab, (_, tok, st) in zip(labels, words):
        if blocks and blocks[-1][1] == lab:
            blocks[-1][2].append(tok)
        else:
            blocks.append([st, lab, [tok]])
    Path(a.out).write_text(head + "# Raw Transcript\n\n"
                           + "\n\n".join(f"[{s}] {l}: {' '.join(t)}" for s, l, t in blocks) + "\n",
                           encoding="utf-8", newline="\n")
    print(f"moved {moved} | turns {len(blocks)}")


if __name__ == "__main__":
    main()
