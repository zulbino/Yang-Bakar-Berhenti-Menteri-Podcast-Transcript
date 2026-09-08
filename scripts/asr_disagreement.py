"""Score two transcripts of the same audio against an independent third transcript.

WHAT THIS MEASURES, AND WHAT IT DOES NOT. There is no ground-truth transcript for any
episode in this corpus, so this cannot report a word error rate. What it reports is a
DISAGREEMENT RATE against YouTube's own caption track -- a transcription this pipeline did
not produce. The captions carry their own errors, so the absolute number is not accuracy.
What is meaningful is the COMPARISON: two engines scored against the same independent third
party, with the same normalizer, are being judged on equal terms.

WHY THE NORMALIZER MATTERS MORE THAN THE METRIC. Malaysian Malay has several accepted
spellings for common words -- `okay`/`okey`/`oke`, `jugak`/`juga`, `tu`/`itu`. Scored raw,
a transcript is punished for spelling convention rather than for hearing the wrong word. The
vendored Revolab normalizer folds those to one canonical form first. On this corpus that is
the difference between measuring transcription and measuring orthography.

READ THE DELETION COLUMN FIRST. Published benchmarks on Malaysian audio show deletion is
where engines differ most and where the damage is worst -- one commercial model deletes 15%
of words, producing fluent output with content silently missing. Substitutions are visible
to a reader; deletions are not.

  python scripts/asr_disagreement.py ep62 \
      --hyp local=episodes/.../raw.md --hyp mai=data/_mai_<id>/raw.md
"""
import argparse
import glob
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rapidfuzz.distance import Levenshtein  # noqa: E402

from vendor.revolab_normalizer import MalayTextNormalizer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TURN = re.compile(r"^\[[\d:]+\]\s*[^:\n]{1,40}:\s*(.*)$", re.M)


def vtt_text(path):
    """Caption text, with the rolling-window duplication auto-captions carry stripped."""
    words, tail = [], []
    for line in path.read_text(encoding="utf-8", errors="replace").split("\n"):
        line = line.strip()
        if (not line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE"))
                or "-->" in line or line.isdigit()):
            continue
        # `&gt;&gt;` is YouTube's speaker-change marker, not speech. Counting it as a
        # word inflated ep62's caption total by 1,483 tokens, about 5%.
        line = re.sub(r"<[^>]+>", "", line)
        cue = re.sub(r"&gt;&gt;|>>", " ", line).split()
        if not cue:
            continue
        overlap = 0
        for size in range(min(len(cue), len(tail)), 0, -1):
            if tail[-size:] == cue[:size]:
                overlap = size
                break
        words.extend(cue[overlap:])
        tail = words[-40:]
    return " ".join(words)


def transcript_text(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    turns = TURN.findall(text)
    if not turns:
        raise SystemExit(f"{path} has no [stamp] Speaker: lines")
    return " ".join(turns)


def score(ref_tokens, hyp_tokens):
    """Substitutions, insertions and deletions from one global alignment.

    Tokens are interned to ints first: the aligner compares by equality, and integers make
    a 26k x 30k alignment finish in seconds where string comparison does not.
    """
    vocab = {}
    def ids(seq):
        return [vocab.setdefault(t, len(vocab)) for t in seq]
    ref_ids, hyp_ids = ids(ref_tokens), ids(hyp_tokens)
    counts = {"replace": 0, "insert": 0, "delete": 0}
    for op in Levenshtein.editops(ref_ids, hyp_ids):
        counts[op.tag] += 1
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", help="episode tag, e.g. ep62")
    ap.add_argument("--hyp", action="append", required=True, metavar="LABEL=PATH",
                    help="repeatable; the transcripts being compared")
    ap.add_argument("--ref", help="caption vtt; defaults to the episode's ms-orig track")
    ap.add_argument("--raw", action="store_true", help="skip the Malay normalizer")
    args = ap.parse_args()

    matches = glob.glob(str(ROOT / "episodes" / "*" / f"*-{args.tag}-*"))
    if len(matches) != 1:
        sys.exit(f"{args.tag} matched {len(matches)} episodes")
    import common
    fields, _ = common.read_frontmatter_body(Path(matches[0]) / "raw.md")
    video_id = fields["video_id"]

    ref_path = Path(args.ref) if args.ref else ROOT / "audio" / f"{video_id}.ms-orig.vtt"
    if not ref_path.exists():
        sys.exit(f"{ref_path} not found -- the caption track is the independent reference")

    normalize = (lambda s: s.lower()) if args.raw else MalayTextNormalizer()
    ref_tokens = normalize(vtt_text(ref_path)).split()
    print(f"{args.tag}  reference: {ref_path.name}, {len(ref_tokens):,} tokens "
          f"({'raw' if args.raw else 'Malay-normalized'})")
    print("  NOT a word error rate -- the captions are themselves ASR output. The "
          "comparison between rows is what carries meaning.\n")
    print(f"  {'engine':10} {'tokens':>8} {'disagree':>9} {'sub':>8} {'ins':>8} {'del':>8}")

    rows = []
    for spec in args.hyp:
        label, _, path = spec.partition("=")
        hyp_tokens = normalize(transcript_text(Path(path))).split()
        c = score(ref_tokens, hyp_tokens)
        total = sum(c.values())
        rows.append((label, len(hyp_tokens), total, c))
        n = len(ref_tokens)
        print(f"  {label:10} {len(hyp_tokens):>8,} {total / n:>8.1%} "
              f"{c['replace'] / n:>7.1%} {c['insert'] / n:>7.1%} {c['delete'] / n:>7.1%}")

    if len(rows) == 2:
        (a, _, ta, ca), (b, _, tb, cb) = rows
        better = a if ta < tb else b
        print(f"\n  {better} disagrees less with the captions, by "
              f"{abs(ta - tb) / len(ref_tokens):.1%} of reference tokens.")
        print(f"  deletions: {a} {ca['delete']:,} vs {b} {cb['delete']:,}")


if __name__ == "__main__":
    main()
