"""Ask the YouTube caption track which of two transcripts heard a figure correctly.

WHY. `check_figures.py` finds a number in the published text that raw.md does not have, and
until now that always went to the owner's ear. On ep59 the local ASR heard `rugi 120 juta`
and MAI heard `rugi 102 juta`, one digit transposed, and nothing in either file could settle
it. The caption track can: YouTube's own transcription is a THIRD witness, made by neither
engine, and it says `rugi 102 juta okey, loss from discontinued operation`. Two independent
witnesses against one.

The owner's standing goal for this project is to need fewer human checks, so a question a
machine can answer should never reach them. This answers the ones the captions cover and
says plainly when they do not.

HOW IT FINDS THE PLACE. Not by the clock -- the caption clock and the block clock disagree by
tens of seconds in this corpus. It takes the words around the figure in the file that HAS it,
and matches them in the caption text with scripts/lib_locate.py, which scores on characters
and so survives a different spelling. Then it reads whatever number the captions have in the
same spot.

WHAT IT DOES NOT DO. It changes nothing. Two engines and a caption track can all be wrong
together, and a figure in a transcript people cite has to be right, so the output is evidence
for a decision, not the decision.

  python scripts/figure_witness.py ep59
"""
import argparse
import glob
import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from lib_locate import Doc, tokens  # noqa: E402

FIGURE = re.compile(r"\b\d[\d.,]*\s*(?:bilion|billion|juta|million|ribu|peratus|%)?", re.I)
WINDOW = 9          # words either side of the figure, used to find the place


def caption_text(vid):
    """The caption track as one string, cues de-duplicated, tags stripped."""
    out, seen = [], set()
    for path in sorted(glob.glob(str(ROOT / f"audio/{vid}*.vtt"))):
        text = io.open(path, encoding="utf-8", errors="replace").read()
        for block in re.split(r"\n\n+", text):
            if not re.match(r"\d\d:\d\d:\d\d\.\d+ --> ", block):
                continue
            for line in block.splitlines()[1:]:
                line = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", line)).strip()
                line = line.replace("&gt;&gt;", "").replace("&gt;", "").strip()
                if line and line not in seen:
                    seen.add(line)
                    out.append(line)
    return " ".join(out)


def norm(figure):
    """`1,500` and `1500` are the same number; `120 juta` and `120 million` are too."""
    f = figure.lower().replace(",", "").replace(" ", "").rstrip(".")
    for a, b in (("billion", "bilion"), ("million", "juta"), ("thousand", "ribu")):
        f = f.replace(a, b)
    return f


def figures(text):
    return {m.group(0).strip() for m in FIGURE.finditer(text)
            if any(c.isdigit() for c in m.group(0))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--figure", action="append", default=[],
                    help="only these; default is every figure the two files disagree about")
    a = ap.parse_args()

    hits = glob.glob(str(ROOT / f"episodes/*/*-{a.tag}-*/raw.md"))
    if len(hits) != 1:
        sys.exit(f"{len(hits)} episodes match {a.tag}")
    folder = Path(hits[0]).parent
    raw = io.open(folder / "raw.md", encoding="utf-8").read()
    vid = re.search(r"video_id:\s*(\S+)", raw).group(1)
    published = {}
    for name in ("interview.md", "interview-ms.md", "interview-en.md"):
        if (folder / name).exists():
            published[name] = io.open(folder / name, encoding="utf-8").read()

    captions = caption_text(vid)
    if not captions:
        sys.exit(f"no caption track in audio/ for {vid} -- this episode has no third witness")
    witness = Doc("[00:00] captions: " + captions)

    if a.figure:
        wanted = a.figure
    else:
        in_raw = {norm(f) for f in figures(raw)}
        seen, wanted = set(), []
        for text in published.values():
            for f in sorted(figures(text)):
                if norm(f) in in_raw or norm(f) in seen:
                    continue
                seen.add(norm(f))
                wanted.append(f)
    if not wanted:
        print(f"{a.tag}: the published files hold no figure that raw.md lacks")
        return

    print(f"{a.tag}: {len(wanted)} figure(s) to witness, caption track {len(captions.split())} words")
    for fig in wanted:
        source = next((t for t in list(published.values()) + [raw] if fig in t), None)
        if source is None:
            print(f"\n  {fig!r}: not in any file any more")
            continue
        i = source.index(fig)
        before = " ".join(tokens(source[max(0, i - 400):i])[-WINDOW:])
        after = " ".join(tokens(source[i + len(fig):i + len(fig) + 400])[:WINDOW])
        found = witness.locate(before + " " + after) or witness.locate(before) or witness.locate(after)
        print(f"\n  {fig!r}, printed as: ...{before} [{fig}] {after}...")
        if not found:
            print("     the captions do not carry this passage -- this one needs the owner's ear")
            continue
        lo = max(0, found["tok0"] - WINDOW - 4)
        hi = min(len(witness.tok), found["tok1"] + WINDOW + 4)
        heard = " ".join(witness.tok[lo:hi])
        nums = [t for t in witness.tok[lo:hi] if any(c.isdigit() for c in t)]
        print(f"     captions say (match {found['score']:.2f}): ...{heard}...")
        print(f"     numbers the captions have there: {nums or 'none'}")


if __name__ == "__main__":
    main()
