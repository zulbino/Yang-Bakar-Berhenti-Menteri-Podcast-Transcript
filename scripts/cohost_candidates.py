"""Find candidate co-host moments INSIDE collapsed blocks, to aim the camera at.

The oversized-block episodes cannot be checked on video the way the anonymous-label ones
can: a 62-minute block carries exactly ONE timestamp, at its start, so there is no second
to screenshot. This finds seconds worth looking at.

Two signals, both text-only and both independent of the speaker labels under suspicion:

  YB VOCATIVE. Every "YB" is someone addressing Rafizi, so it is never Rafizi speaking.
  Inside a block labelled Rafizi, each one marks a co-host turn the block swallowed. This
  is the detector the honorific normalisation opened up (ENGINEERING_LOG 1.32): before
  944 garbles were fixed, most of these read as "baby", "WB" or "Oibi" and were invisible.

  RUN-SHEET PHRASE. "okey baik", "seterusnya", "next", "kita ke segmen" -- the voice that
  drives the running order, which belongs to whoever is hosting the desk.

Timestamps come from the YouTube caption track's WORD-LEVEL timings, used purely as an
index to locate a second. The captions are not treated as a text source and nothing from
them is written into the transcript -- the repo owner's instruction, and the right call
anyway, since raw.md is the reviewed artefact.

The caption cue format repeats the previous line in every cue as a rolling window, so
reading cue text naively counts everything two or three times. Only the word-timed
segments (<TIME><c> word</c>) are unique, which is what this parses.

A block does not have to be oversized to swallow a co-host. ep21 and ep27 have no block
over 20 minutes and still hold no Haziq label at all, so --min-block lowers the bar and
scans ordinary blocks too. Only blocks whose label is a HOST are scanned: a YB vocative
inside a guest's block says nothing about the host attribution.

Usage:  python scripts/cohost_candidates.py ep58 ep41 ep47
        python scripts/cohost_candidates.py ep21 ep27 --min-block=120
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_BLOCK_S = 1200          # matches qa_check.py's oversized-block threshold
WORD_TIME = re.compile(r"<(\d\d):(\d\d):(\d\d)\.(\d\d\d)><c>\s*([^<]+)</c>")
TURN = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]\s*([^:]{1,40}?):\s*(.*)$")
RUN_SHEET = ["okey baik", "ok baik", "seterusnya", "kita ke segmen", "next kita",
             "kita pergi ke", "soalan seterusnya"]


def secs(stamp):
    parts = [int(p) for p in stamp.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def hms(t):
    return f"{int(t)//3600}:{int(t)//60%60:02d}:{int(t)%60:02d}" if t >= 3600 \
        else f"{int(t)//60}:{int(t)%60:02d}"


def episode_dir(tag):
    for d in sorted(ROOT.glob("episodes/*/*")):
        if re.search(r"-" + tag + r"-", d.name) and "bakar" not in str(d):
            return d
    sys.exit(f"no episode matched {tag}")


def words_with_times(vtt_path):
    """[(seconds, word)] from the caption track's word-level timings, deduplicated."""
    out, seen = [], set()
    for h, m, s, ms, word in WORD_TIME.findall(vtt_path.read_text(encoding="utf-8")):
        t = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
        key = (round(t, 2), word.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((t, word.strip()))
    return out


PRINCIPAL = "Rafizi"


def oversized_blocks(raw_path, min_block_s=MIN_BLOCK_S):
    turns = []
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        m = TURN.match(line.strip())
        if m:
            turns.append((secs(m.group(1)), m.group(2).strip()))
    blocks = []
    for i, (start, label) in enumerate(turns):
        end = turns[i + 1][0] if i + 1 < len(turns) else start
        if end - start >= min_block_s and PRINCIPAL.lower() in label.lower():
            blocks.append((start, end, label))
    return blocks


def main():
    min_block = next((int(a.split("=", 1)[1]) for a in sys.argv
                      if a.startswith("--min-block=")), MIN_BLOCK_S)
    for tag in [a for a in sys.argv[1:] if not a.startswith("--")]:
        d = episode_dir(tag)
        vid = re.search(r"video_id:\s*(\S+)",
                        (d / "interview.md").read_text(encoding="utf-8")).group(1)
        vtt = ROOT / "audio" / f"{vid}.ms.vtt"
        blocks = oversized_blocks(d / "raw.md", min_block)
        print(f"\n=== {tag}  ({vid})  {len(blocks)} block(s) ===")
        if not vtt.exists():
            print("  NO CAPTION TRACK -- no way to locate a second inside the block")
            continue
        words = words_with_times(vtt)
        for start, end, label in blocks:
            inside = [(t, w) for t, w in words if start <= t < end]
            hits = []
            for i, (t, w) in enumerate(inside):
                low = w.lower().strip(".,?!")
                phrase = " ".join(x[1].lower() for x in inside[i:i + 3])
                if low == "yb":
                    hits.append((t, "YB vocative", " ".join(
                        x[1] for x in inside[max(0, i - 4):i + 4])))
                elif any(phrase.startswith(p) for p in RUN_SHEET):
                    hits.append((t, "run-sheet", " ".join(
                        x[1] for x in inside[i:i + 6])))
            print(f"  block [{hms(start)}]-[{hms(end)}] {(end-start)/60:.0f} min "
                  f"as '{label}': {len(hits)} candidate(s) from {len(inside)} words")
            # cluster hits within 20s: one look covers them
            shown, last = 0, -99
            for t, kind, ctx in hits:
                if t - last < 20:
                    continue
                last = t
                shown += 1
                if shown > 12:
                    print(f"      ... {len(hits)} hits total, first 12 shown")
                    break
                print(f"      {hms(t):>9}  {kind:<12} {ctx[:70]}")


if __name__ == "__main__":
    main()
