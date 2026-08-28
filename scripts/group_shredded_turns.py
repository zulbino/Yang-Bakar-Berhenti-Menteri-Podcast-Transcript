"""Label fully shredded runs "Multiple speakers" instead of guessing who said what.

Near a real speaker change, word-level labelling flickers and chops one sentence into
alternating fragments under different names:

    Haziq:  Ini
    Rafizi: scaling up,
    Haziq:  commercial
    Rafizi: operation.

"Ini scaling up, commercial operation" is one phrase. Four names on it is four claims,
and at most one arrangement is right. Grouping the run under a single "Multiple speakers"
turn, fragments joined by " ... ", keeps every word in order while dropping the false
precision. Suggested by the repo owner.

WHY NOT JUST MERGE THEM INTO A NEIGHBOUR. An earlier version folded each fragment into
the surrounding label and was caught before shipping:

    ep12 [07:58]  Rafizi "...beria beria beria ok" | Haziq "beria ok seterusnya"
    ep13 [03:06]  Haziq "...Ahli politik dia tak boleh. TikTok" | Rafizi "pun tak boleh?"

"beria ok seterusnya" is the run-sheet voice, which is never Rafizi. "TikTok pun tak
boleh?" is a real question. In both, the fragment is a genuine short turn and the
NEIGHBOUR'S TAIL is what sits under the wrong name, so folding inward asserts the
opposite of the truth. Direction is not recoverable from text. "Multiple speakers" makes
no claim at all, which is why it is safe where merging is not.

THE SCOPE HAS TO BE NARROW, and two earlier drafts were too wide:

  - Treating Malay particles as mid-sentence markers matched 2,181 spans, most of them
    legitimate ("Tak kelakar.", "Okey.") -- Tak and Okey are ordinary sentence openers.
  - Grouping any mid-sentence alternating run matched 482, including runs containing long
    substantive paragraphs. ep01's "Dari mana?" / "Daripada Johor Bahru." is real rapid
    dialogue, correctly attributed, and blobbing it would destroy good information.

All three conditions are required, and together they match 61 runs / 564 words:

  1. Three or more consecutive turns, so at least two seams are untrustworthy.
  2. EVERY turn at most MAX_FRAGMENT_WORDS words -- a fragment, not a real turn.
  3. EVERY seam mid-sentence: the next fragment starts lowercase and the previous one
     does not end in . ? or !

Runs that fail these are reported, not touched: isolated single tears (one fragment
between two substantial turns) still need audio to place, and the acoustic pass in
reattribute_blocks.py is where that belongs.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

GROUP_LABEL = "Multiple speakers"
JOIN = " ... "
MAX_FRAGMENT_WORDS = 8
MIN_RUN_TURNS = 3

TURN = re.compile(r"^\[([0-9:]+)\]\s*([^:]{1,40}?):\s*(.*)$")


def parse(body):
    return [[m.group(1), m.group(2).strip(), m.group(3).strip()]
            for m in (TURN.match(line.strip()) for line in body.splitlines()) if m]


def _fragment(turn):
    return 0 < len(turn[2].split()) <= MAX_FRAGMENT_WORDS


def _mid_sentence_seam(a, b):
    return bool(b[2]) and b[2][0].islower() and not (a[2] and a[2][-1] in ".?!")


def find_runs(turns):
    """Maximal index ranges [i, j] that satisfy all three conditions."""
    runs, i = [], 0
    while i < len(turns) - 1:
        if not _fragment(turns[i]):
            i += 1
            continue
        j = i
        while (j + 1 < len(turns)
               and turns[j + 1][1] != turns[j][1]
               and _fragment(turns[j + 1])
               and _mid_sentence_seam(turns[j], turns[j + 1])):
            j += 1
        if j - i + 1 >= MIN_RUN_TURNS and len({turns[k][1] for k in range(i, j + 1)}) >= 2:
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    return runs


def apply_runs(turns, runs):
    grouped, out, cut = [], [], {}
    for i, j in runs:
        cut[i] = j
    k = 0
    while k < len(turns):
        if k in cut:
            j = cut[k]
            span = turns[k:j + 1]
            text = JOIN.join(t[2] for t in span)
            out.append([span[0][0], GROUP_LABEL, text])
            grouped.append((span[0][0], [(t[1], t[2]) for t in span]))
            k = j + 1
        else:
            out.append(turns[k])
            k += 1
    return out, grouped


def main():
    write = "--write" in sys.argv
    only = [a for a in sys.argv[1:] if a.startswith("ep")]
    total, files = 0, 0
    for path in sorted(ROOT.glob("episodes/*/*/raw.md")):
        tag = re.search(r"ep\d+", path.parent.name).group(0)
        if only and tag not in only:
            continue
        text = path.read_text(encoding="utf-8")
        head, body = text.split("# Raw Transcript", 1)
        turns = parse(body)
        runs = find_runs(turns)
        if not runs:
            continue
        new_turns, grouped = apply_runs(turns, runs)
        files += 1
        total += len(grouped)
        label = f"{tag}{'(24)' if 'bakar' in str(path) else ''}"
        print(f"\n{label}: {len(grouped)} shredded run(s)")
        for ts, span in grouped:
            print(f"   [{ts:>8}] " + "  |  ".join(f"{lab}: {txt}" for lab, txt in span))
            print(f"             => {GROUP_LABEL}: {JOIN.join(t[1] for t in span)}")
        if write:
            new_body = ("\n\n" + "\n\n".join(f"[{t[0]}] {t[1]}: {t[2]}" for t in new_turns)
                        + "\n")
            path.write_text(head + "# Raw Transcript" + new_body, encoding="utf-8")
    print("")
    print(f"{total} shredded runs across {files} files")
    print("dry run -- pass --write to apply" if not write else "written")


if __name__ == "__main__":
    main()
