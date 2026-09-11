"""Print a clickable YouTube link and the caption text for any moment in an episode.

WHY THIS EXISTS. The owner asked for it on 2026-09-11: "when you need something for me to
verify visually and listen manually, do give straight up the timestamp link, did not expect
me to scrub through the video timestamp one by one." Anything escalated for their ear ships
as a link, not a block stamp.

WHY NOT JUST BUILD THE LINK FROM raw.md's STAMP. Because the stamp is often wrong by more
than the length of the turn. 159 of ep61's 203 block stamps were more than 10s off, and
ep40's clock is about 170 seconds early -- its `[35:30]` block is at 2296s in the audio,
not 2130s. A link built on the stamp sends the owner to the wrong moment, which is worse
than sending nothing, because they cannot tell it is wrong without already knowing the
answer. So this prints the CAPTION WINDOW around the stamp and leaves the reading to a
person: the caption text is what identifies the right second.

TWO THINGS THAT LOOK LIKE SHORTCUTS AND ARE NOT, both tried and discarded on 2026-09-11:

  - Fuzzy-matching the fragment's own text against the caption track. A fragment like `Hmm`
    or `tu` matches any cue, and this drifted by up to 165 seconds while reporting a
    confident score. Short fragments cannot locate themselves.
  - Literal-matching a NEIGHBOUR block's long tail. Zero unique anchors across 11 blocks:
    raw.md and the YouTube captions come from different ASR engines, so the wording differs
    even where both are correct.

The VTT cue line carries `align:start position:0%` AFTER the timestamps and before the
newline. A regex that expects the text immediately after the arrow matches zero cues in
every file and then reports silence at every timestamp asked about. Hence CUE below, and
hence the cue count printed in the header -- validate the parser before trusting a result.

  python scripts/listen_links.py ep34 1:49:20 2:04:29
  python scripts/listen_links.py ep33 59:17 --window 40
  python scripts/listen_links.py ep53 --unknowns        # every `Speaker ?` block
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

CUE = re.compile(r"([\d:.]+) --> ([\d:.]+)[^\n]*\n(.*?)(?=\n\n|\Z)", re.S)
BLOCK = re.compile(r"^\[([\d:]+)\]\s+([^:\n]{1,40}):\s*(.*)$", re.M)
LEAD_IN = 6


def secs(t):
    p = [float(x) for x in t.split(":")]
    while len(p) < 3:
        p = [0] + p
    return p[0] * 3600 + p[1] * 60 + p[2]


def hms(s):
    s = int(s)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def video_id(raw_path):
    head = raw_path.read_text(encoding="utf-8")[:2000]
    m = re.search(r"(?:video_id|youtube_id|url|source)\s*:\s*(\S+)", head)
    return re.search(r"([A-Za-z0-9_-]{11})", m.group(1)).group(1)


def captions(vid):
    path = Path(__file__).resolve().parent.parent / "audio" / f"{vid}.ms.vtt"
    if not path.exists():
        return None
    out = []
    for m in CUE.finditer(path.read_text(encoding="utf-8")):
        text = re.sub(r"<[^>]*>", "", m.group(3)).replace("&gt;&gt;", ">>").strip()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines:
            out.append((secs(m.group(1)), lines[-1]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("stamps", nargs="*", help="block stamps, e.g. 1:49:20")
    ap.add_argument("--unknowns", action="store_true", help="every `Speaker ?` block")
    ap.add_argument("--window", type=int, default=14, help="seconds of caption either side")
    a = ap.parse_args()

    raw = common.raw_for_tag(a.tag)
    vid = video_id(raw)
    cues = captions(vid)
    body = raw.read_text(encoding="utf-8")
    blocks = BLOCK.findall(body)

    stamps = list(a.stamps)
    if a.unknowns:
        stamps += [st for st, who, _ in blocks if who.strip() == "Speaker ?"]
    if not stamps:
        ap.error("give at least one stamp, or --unknowns")

    if cues is None:
        print(f"{a.tag}: no caption track at audio/{vid}.ms.vtt -- links below are built "
              f"from raw.md's stamp and MAY BE WRONG by minutes")
    else:
        print(f"{a.tag}  video {vid}  {len(cues)} caption cues spanning "
              f"{hms(cues[0][0])}-{hms(cues[-1][0])}")

    for st in stamps:
        at = secs(st)
        said = next((t for s, who, t in blocks if s == st), "")
        print(f"\n### [{st}] {said[:60]!r}")
        print(f"    https://youtu.be/{vid}?t={max(0, int(at) - LEAD_IN)}")
        if cues is None:
            continue
        seen = set()
        for s, c in cues:
            if at - a.window <= s <= at + a.window and c not in seen:
                seen.add(c)
                print(f"      {hms(s)} {s:9.1f}  {c[:90]}")
        if not seen:
            print(f"      no cue within {a.window}s -- the stamp is off, widen --window")


if __name__ == "__main__":
    main()
