"""Join a speaker's consecutive turns in the published interview files into one paragraph.

WHY. MAI-Transcribe-2 writes one block per phrase, so ep62's raw.md has 1,689 blocks and the
segment rewrite kept that structure one to one: interview.md came out as 1,100 turns, 621 of
them the same speaker continuing after a paragraph break -- "**Rafizi:** Kalaupun benda tu tak
boleh berlaku, paling kurang Ketua Setiausaha" / "**Rafizi:** pergi duduk dan mesyuarat". The
owner asked why. Every earlier episode came from the local ASR's long blocks and never showed
it. raw.md keeps the phrase-level blocks on purpose (it is the verbatim record, and its stamps
locate words); the published files read as prose and get the join.

WHAT IT DOES. In each interview*.md body, two adjacent paragraphs that both open with the same
bold label become one paragraph: the second's text is appended after a space. Nothing else
moves; the word sequence of the body is asserted identical before and after. `Multiple
speakers` and `Speaker ?` are labels like any other and join only with themselves.

  python scripts/merge_adjacent_turns.py ep62            # dry run, counts only
  python scripts/merge_adjacent_turns.py ep62 --write
"""
import argparse
import glob
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
TURN = re.compile(r"^\*\*([^*\n]{1,40}):\*\*[ \t]?(.*)$", re.S)


def merge_body(body):
    paras = body.strip().split("\n\n")
    out, joined = [], 0
    for p in paras:
        m, prev = TURN.match(p), (TURN.match(out[-1]) if out else None)
        if m and prev and m.group(1) == prev.group(1):
            out[-1] = out[-1].rstrip() + " " + m.group(2).strip()
            joined += 1
        else:
            out.append(p)
    return "\n\n".join(out) + "\n", joined


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    tag, _, show = a.tag.partition(":")        # ep05:berhenti -- both shows have an ep05
    hits = [p for p in glob.glob(str(ROOT / f"episodes/*/*-{tag}-*/interview*.md"))
            if not show or show in Path(p).parts[-3]]
    if not hits:
        sys.exit(f"no interview files match {a.tag}")
    for path in sorted(hits):
        text = Path(path).read_text(encoding="utf-8")
        fm_end = text.index("\n---\n", 4) + 5
        head, rest = text[:fm_end], text[fm_end:]
        h1, body = rest.lstrip("\n").split("\n\n", 1)
        new_body, joined = merge_body(body)
        words = lambda t: re.sub(r"\*\*[^*\n]{1,40}:\*\*", "", t).split()
        assert words(body) == words(new_body), f"word sequence changed in {path}"
        before, after = len(body.strip().split("\n\n")), len(new_body.strip().split("\n\n"))
        print(f"  {Path(path).name:17} {before} -> {after} turns ({joined} joins)")
        if a.write:
            Path(path).write_text(head + "\n" + h1 + "\n\n" + new_body, encoding="utf-8")
    print("written" if a.write else "dry run, pass --write to apply")


if __name__ == "__main__":
    main()
