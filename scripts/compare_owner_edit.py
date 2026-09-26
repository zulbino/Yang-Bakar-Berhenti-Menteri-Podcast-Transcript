"""Score the pipeline's raw.md against the owner's hand-corrected copy of it.

WHY. From ep65 on (owner, 2026-09-25) every new episode's raw stage ends with two files: the
untouched pipeline output and a copy the owner corrects while watching the video. The owner's
copy is the reference. This measures the pipeline against it, per word and per speaker label,
so an old pipeline assumption can be retested with a number instead of an argument.

The owner's copy is free-form: a new turn may carry no timestamp ("Rafizi: ...") and may use a
short label ("Pa'an:"). Both are read. Words are compared lower-case without punctuation.
Each word's second comes from MAI's own word times, so every region gets a working ?t= link.

  python scripts/compare_owner_edit.py ep65 data/_ep65_review/raw_pipeline.md data/_ep65_review/raw_owner_edit.md
"""
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TURN = re.compile(r"^(?:\[[\d:]+\]\s*)?([A-Z][^:\n\[\]]{0,40}?):\s*(.*)$")
WORD = re.compile(r"[\w']+")


def turns(path, aliases):
    body = Path(path).read_text(encoding="utf-8").split("# Raw Transcript", 1)[-1]
    out = []
    for line in body.splitlines():
        m = TURN.match(line.strip())
        if m:
            who = m.group(1).strip()
            out.append([aliases.get(who, who), m.group(2)])
        elif line.strip() and out:
            out[-1][1] += " " + line.strip()
    return out


def tokens(ts):
    return [(w.lower(), who, k) for k, (who, text) in enumerate(ts) for w in WORD.findall(text)]


def stamp(s):
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def main():
    tag, pipe_path, owner_path = sys.argv[1:4]
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    vid = common.resolve_tag(manifest, tag)["video_id"]
    pipe_turns = turns(pipe_path, {})
    names = {w for w, _ in pipe_turns}
    aliases = {}
    for n in names:
        m = re.search(r"\(([^)]+)\)", n)
        if m:
            aliases[m.group(1)] = n
    owner_turns = turns(owner_path, aliases)
    P, O = tokens(pipe_turns), tokens(owner_turns)

    # every pipeline word gets MAI's second
    mai = [(w.lower(), x["t"] / 1000)  # MAI word times are absolute
           for t in json.loads((ROOT / "data" / f"_mai_{vid}" / "mai_words.json").read_text(encoding="utf-8"))["turns"]
           for x in t["words"] for w in WORD.findall(x["w"])]
    at = [None] * len(P)
    sm = SequenceMatcher(None, [w for w, _, _ in P], [w for w, _ in mai], autojunk=False)
    for a, b, n in sm.get_matching_blocks():
        for i in range(n):
            at[a + i] = mai[b + i][1]
    last = 0.0
    for i in range(len(at)):
        at[i] = last = at[i] if at[i] is not None else last

    sm = SequenceMatcher(None, [w for w, _, _ in P], [w for w, _, _ in O], autojunk=False)
    ops = Counter()
    word_regions = []
    label_ok, label_bad, confusion = 0, 0, Counter()
    regions = []  # contiguous runs of matched words whose label differs
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2)):
                if P[i][1] == O[j][1]:
                    label_ok += 1
                    continue
                label_bad += 1
                confusion[(P[i][1], O[j][1])] += 1
                r = regions[-1] if regions else None
                if r and r["i2"] == i and r["pipe"] == P[i][1] and r["owner"] == O[j][1]:
                    r["i2"] = i + 1
                else:
                    regions.append({"i1": i, "i2": i + 1, "pipe": P[i][1], "owner": O[j][1]})
        else:
            ops[op] += max(i2 - i1, j2 - j1) if op == "replace" else (i2 - i1 or j2 - j1)
            word_regions.append((op, i1, i2, j1, j2))

    ref = len(O)
    lines = [f"# {tag}: pipeline raw.md against the owner's corrected copy", "",
             f"Reference (owner): {ref} words, {len(owner_turns)} turns. "
             f"Pipeline: {len(P)} words, {len(pipe_turns)} turns.", "",
             "## Words", "",
             f"Word error rate {sum(ops.values()) / ref:.1%}: {ops['replace']} substituted, "
             f"{ops['delete']} only in the pipeline, {ops['insert']} only in the owner's copy.", "",
             "## Speaker labels, on the words both files share", "",
             f"{label_ok / (label_ok + label_bad):.1%} right: {label_bad} of {label_ok + label_bad} words "
             f"carry a different label, in {len(regions)} regions.", "",
             "| pipeline said | owner says | words |", "|---|---|---|"]
    lines += [f"| {p} | {o} | {n} |" for (p, o), n in confusion.most_common()]
    lines += ["", "## Every label region", "",
              "| at | pipeline | owner | words | text |", "|---|---|---|---|---|"]
    for r in regions:
        s = at[r["i1"]]
        text = " ".join(w for w, _, _ in P[r["i1"]:r["i2"]])
        lines.append(f"| [{stamp(s)}](https://youtu.be/{vid}?t={max(0, int(s) - 3)}) | {r['pipe']} | "
                     f"{r['owner']} | {r['i2'] - r['i1']} | {text[:90]} |")
    lines += ["", "## Every word change", "",
              "| at | pipeline | owner |", "|---|---|---|"]
    for op, i1, i2, j1, j2 in word_regions:
        s = at[min(i1, len(at) - 1)]
        lines.append(f"| [{stamp(s)}](https://youtu.be/{vid}?t={max(0, int(s) - 3)}) | "
                     f"{' '.join(w for w, _, _ in P[i1:i2]) or '-'} | {' '.join(w for w, _, _ in O[j1:j2]) or '-'} |")
    out = Path(owner_path).with_name("comparison.md")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:12 + len(confusion) + 3]))
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
