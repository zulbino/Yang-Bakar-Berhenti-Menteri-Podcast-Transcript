"""Turn the owner's hand-corrected copy of raw.md into the episode's raw.md.

WHY. The owner edits a copy while watching the video (CLAUDE.md, raw-review workflow). They
add turns without a timestamp and sometimes mistype a label. raw.md needs `[MM:SS] Label:`
on every turn, so this gives each unstamped turn the time of its first word, read from MAI's
own word times, the same way compare_owner_edit.py reads them. A stamped turn keeps its stamp.

The header (front matter and navigation) comes from the current raw.md, not from the copy.
The words and labels come from the copy, byte for byte. Two checks run before anything is
written: every label must be one of the episode's known speakers, and the stamps must not
run backwards.

  python scripts/install_owner_edit.py ep66 data/_ep66_review/raw_owner_edit.md
  python scripts/install_owner_edit.py ep66 data/_ep66_review/raw_owner_edit.md --write
"""
import argparse
import io
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TURN = re.compile(r"^(?:\[([\d:]+)\]\s*)?([A-Z][^:\n\[\]]{0,40}?):\s*(.*)$")
WORD = re.compile(r"[\w']+")
SANCTIONED = {"Speaker ?", "Multiple speakers", "Audience"}


def fmt(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def secs(stamp):
    parts = [int(p) for p in stamp.split(":")]
    return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("copy")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--also-known", action="append", default=[], metavar="NAME",
                    help="a speaker the pipeline raw.md never labelled but the episode's own "
                         "description names (a guest whose face the camera did not know)")
    a = ap.parse_args()

    raw = Path(common.raw_for_tag(a.tag))
    head = raw.read_text(encoding="utf-8").split("# Raw Transcript", 1)[0] + "# Raw Transcript\n"
    vid = re.search(r"video_id:\s*(\S+)", head).group(1)
    body = Path(a.copy).read_text(encoding="utf-8").split("# Raw Transcript", 1)[-1]

    turns = []
    for line in body.splitlines():
        if not line.strip():
            continue
        m = TURN.match(line.strip())
        if not m:
            sys.exit(f"not a turn line, fix it in the copy first: {line[:100]!r}")
        turns.append([m.group(1), m.group(2).strip(), m.group(3).strip()])

    known = {m.group(1) for m in re.finditer(r"^\[[\d:]+\]\s*([^:\n]+):", raw.read_text(encoding="utf-8"), re.M)}
    bad = sorted({t[1] for t in turns} - known - SANCTIONED - set(a.also_known))
    if bad:
        sys.exit(f"labels that no speaker of this episode uses (typo?): {bad}")

    mai = [(w.lower(), x["t"] / 1000)
           for t in json.loads((ROOT / "data" / f"_mai_{vid}" / "mai_words.json").read_text(encoding="utf-8"))["turns"]
           for x in t["words"] for w in WORD.findall(x["w"])]
    owner = [(i, w.lower()) for i, t in enumerate(turns) for w in WORD.findall(t[2])]
    at = {}
    sm = SequenceMatcher(None, [w for _, w in owner], [w for w, _ in mai], autojunk=False)
    for x, y, n in sm.get_matching_blocks():
        for k in range(n):
            at.setdefault(owner[x + k][0], mai[y + k][1])

    prev = 0.0
    out, filled = [], 0
    for i, (stamp, who, text) in enumerate(turns):
        if stamp:
            t = secs(stamp)
        else:
            t = at.get(i, prev)
            filled += 1
        if int(t) < int(prev):
            sys.exit(f"stamps run backwards at turn {i} [{fmt(t)}] after [{fmt(prev)}]: {who}: {text[:60]!r}")
        prev = t
        out.append(f"[{stamp or fmt(t)}] {who}: {text}")

    print(f"{a.tag}: {len(turns)} turns, {filled} stamped from MAI word times, "
          f"{len(known)} speakers in raw.md, labels {sorted({t[1] for t in turns})}")
    if a.write:
        io.open(raw, "w", encoding="utf-8", newline="\n").write(head + "\n" + "\n\n".join(out) + "\n")
        print(f"wrote {raw}")


if __name__ == "__main__":
    main()
