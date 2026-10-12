"""Re-stamp the short turns whose stamp points at the wrong moment.

WHY. install_owner_edit.py gave an unstamped turn the time of its first word found in the
ASR words, and when the words were not found it fell back to the PREVIOUS turn's start
time. A short interjection the ASR missed (`Bond holders?`, ep65) therefore carried the start
stamp of the long block before it, two minutes early, and a short phrase that also occurs
earlier (`Tapi pinjaman.`, ep67) matched that earlier copy. The voice test of 2026-10-11 found
it: voice and camera both said Rafizi over 129 s that raw.md gave to Farhan.

THE RULE. A turn is SUSPECT when it shares its stamp with the turn before, or when it is
short (6 words or fewer), the speaker before it speaks again after it, and it owns more than
20 s. A suspect turn is located only inside its own window, between the previous turn's
stamp and the next turn's stamp:
  1. its own words, matched against the ASR words in that window, give its time;
  2. if they are not there, it goes where the previous turn's last words end.
The new stamp must lie between its neighbours, and nothing else changes: no word, no label.

  python scripts/restamp_interjections.py ep67           # report
  python scripts/restamp_interjections.py ep67 --write
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
TURN = re.compile(r"^\[(\d+(?::\d+){1,2})\] ([^:\n]+): (.*)$")
WORD = re.compile(r"[\w']+")
SHORT_WORDS = 6
OWNS_TOO_LONG = 20


def fmt(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def secs(stamp):
    parts = [int(p) for p in stamp.split(":")]
    return sum(p * 60 ** i for i, p in enumerate(reversed(parts)))


def asr_words(vid):
    """[(word, start_s, end_s)] from data/_mai_<vid>/mai_words.json, in time order."""
    turns = json.loads((ROOT / "data" / f"_mai_{vid}" / "mai_words.json").read_text(encoding="utf-8"))["turns"]
    out = []
    for t in turns:
        for x in t["words"]:
            for w in WORD.findall(x["w"] or ""):
                a = x["t"] / 1000
                out.append((w.lower(), a, a + (x.get("d") or 0) / 1000))
    return sorted(out, key=lambda w: w[1])


def window(words, t0, t1):
    return [w for w in words if t0 - 1 <= w[1] <= t1 + 1]


def find(text_words, words, last=False):
    """Time of the first (or last) matched word of `text_words` inside `words`, or None.

    Needs half the turn's words matched in order, so one common word (`ya`) cannot place it.
    """
    if not text_words or not words:
        return None
    sm = SequenceMatcher(None, text_words, [w for w, _, _ in words], autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size]
    if sum(b.size for b in blocks) < max(1, (len(text_words) + 1) // 2):
        return None
    if last:
        b = blocks[-1]
        return words[b.b + b.size - 1][2]
    return words[blocks[0].b][1]


def locate(turn_words, prev_words, words, prev_t, next_t):
    """Where a turn starts, searched only between its neighbours' stamps."""
    w = window(words, prev_t, next_t)
    own = find(turn_words, w)
    if own is not None:
        return own, "own words"
    end = find(prev_words[-8:], w, last=True)
    if end is not None:
        return end, "end of the previous turn"
    return None, "not found"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    raw = Path(common.raw_for_tag(a.tag))
    text = raw.read_text(encoding="utf-8")
    head, body = text.split("# Raw Transcript", 1)
    vid = re.search(r"video_id:\s*(\S+)", head).group(1)
    lines = body.split("\n")
    idx = [i for i, l in enumerate(lines) if TURN.match(l)]
    turns = [list(TURN.match(lines[i]).groups()) for i in idx]
    words = asr_words(vid)

    changed = []
    for k in range(1, len(turns)):
        t, who, said = secs(turns[k][0]), turns[k][1], turns[k][2]
        prev_t = secs(turns[k - 1][0])
        next_t = secs(turns[k + 1][0]) if k + 1 < len(turns) else t + 60
        short = len(WORD.findall(said)) <= SHORT_WORDS
        sandwiched = k + 1 < len(turns) and turns[k + 1][1] == turns[k - 1][1] != who
        suspect = t == prev_t or (short and sandwiched and next_t - t > OWNS_TOO_LONG)
        if not suspect:
            continue
        new, how = locate([w.lower() for w in WORD.findall(said)],
                          [w.lower() for w in WORD.findall(turns[k - 1][2])], words, prev_t, next_t)
        if new is None or not (prev_t <= int(new) <= next_t) or int(new) == t:
            continue
        changed.append((k, t, int(new), how, who, said))
        turns[k][0] = fmt(new)

    for k, old, new, how, who, said in changed:
        print(f"  [{fmt(old)}] -> [{fmt(new)}]  {how:26s} {who}: {said[:60]}   https://youtu.be/{vid}?t={max(0, new - 5)}")
    print(f"{a.tag}: {len(changed)} stamp(s) moved, words and labels unchanged")
    if a.write and changed:
        for (stamp, who, said), i in zip(turns, idx):
            lines[i] = f"[{stamp}] {who}: {said}"
        io.open(raw, "w", encoding="utf-8", newline="\n").write(head + "# Raw Transcript" + "\n".join(lines))
        print(f"wrote {raw}")


if __name__ == "__main__":
    main()
