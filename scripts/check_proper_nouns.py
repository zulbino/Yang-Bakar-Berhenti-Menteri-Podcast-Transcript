"""Find people's names the ASR mangled, by comparing each name against the corpus.

Why not a dictionary. The obvious idea is to check the transcripts against Dewan Bahasa
dan Pustaka's Malay dictionary. That does not work here, for two reasons. The speech is
colloquial and code-switched, so a standard-Malay check flags over 100,000 legitimate
tokens (`kan` appears 19,493 times, `tak` 18,961, `lah` 14,042). And it fails on exactly
the case that matters: `Cincong`, which hid a sitting MP's name for months, IS a real
Malay word meaning fuss. A dictionary confirms a word exists. It cannot tell you the
speaker was saying a name (see ENGINEERING_LOG.md 1.28).

What works instead is comparison, in two directions:

  1. Against the episode's own YouTube captions. An independently generated transcript
     of the same audio. Caveat from 1.28: two ASR systems agreeing means only that both
     heard the same sound the same way, so agreement is weak evidence of correctness --
     disagreement is the useful signal, not agreement.
  2. Against the rest of the corpus. A name spelled one way once, when a very similar
     name is spelled another way fifty times, is almost certainly the same person. This
     is the strongest signal available and needs no external data at all.

Names are found by their honorific (YB, Datuk, Dato', Tan Sri, Saudara, Prof, Dr...),
which is what narrows the output from thousands of capitalised tokens to something
reviewable, and it targets the names whose misspelling would actually harm someone.

This tool reports. It never edits. Every hit needs a human who knows the audio -- and
before any substitution runs, print every occurrence: the two name fixes in this
session would each have corrupted unrelated real people's names without that step.

  python scripts/check_proper_nouns.py
  python scripts/check_proper_nouns.py --episodes ep24 ep36 --min-similarity 0.75
"""
import argparse
import difflib
import glob
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "audio"

HONORIFIC = (r"(?:YB|Datuk|Dato'|Datin|Tan Sri|Tun|Saudara|Saudari|Prof(?:esor)?|Dr\.?|"
             r"Puan|Tuan|Ustaz|Menteri|Ahli Parlimen)")
NAME = r"((?:[A-Z][A-Za-z'-]{2,}\s?){1,3})"
BLOCK_PREFIX = re.compile(r"^\[[^\]]+\][^:\n]{0,40}:", re.M)
VTT_TIME = re.compile(r"\d\d:\d\d:\d\d\.\d\d\d\s*-->")
# honorifics and titles that get swept into the captured name
STOPWORDS = {"seri", "sri", "yang", "juga", "dia", "ini", "itu", "kan", "lah", "baik",
             "cuma", "jadi", "kemudian", "menteri", "satu", "dua", "also", "and"}
RARE_MAX = 4          # a name seen more than this is treated as established
FREQUENT_MIN = 8      # a name seen at least this often is a reference spelling


def caption_tokens(video_id):
    for lang in ("ms", "en"):
        path = AUDIO_DIR / f"{video_id}.{lang}.vtt"
        if path.exists():
            text = path.read_text(encoding="utf-8", errors="replace")
            lines = [l for l in text.splitlines() if not VTT_TIME.search(l)]
            return set(re.findall(r"[\w']+", re.sub(r"<[^>]+>", "", " ".join(lines)).lower()))
    return None


def collect():
    """{episode: (video_id, [names])} plus a corpus-wide Counter of those names."""
    corpus, per_episode = Counter(), {}
    for f in sorted(glob.glob(str(ROOT / "episodes" / "*" / "*" / "raw.md"))):
        text = Path(f).read_text(encoding="utf-8")
        video_id = re.search(r"video_id:\s*(\S+)", text.split("---")[1]).group(1)
        body = BLOCK_PREFIX.sub(" ", text.split("---", 2)[2])
        names = []
        for m in re.finditer(HONORIFIC + r"\s+" + NAME, body):
            parts = [p for p in m.group(1).split() if p.lower() not in STOPWORDS]
            if parts:
                names.append(" ".join(parts))
        corpus.update(n.lower() for n in names)
        per_episode[re.search(r"-(ep\d+)-", f).group(1)] = (video_id, names)
    return corpus, per_episode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", nargs="*", default=[], metavar="TAG")
    ap.add_argument("--min-similarity", type=float, default=0.80,
                    help="how close a rare name must be to a frequent one to be reported")
    args = ap.parse_args()

    corpus, per_episode = collect()
    frequent = sorted({n for n, c in corpus.items() if c >= FREQUENT_MIN})
    print(f"{sum(corpus.values())} honorific-anchored name mentions, "
          f"{len(corpus)} distinct, {len(frequent)} established spellings\n")

    near, unheard, no_caption = [], [], []
    for ep, (video_id, names) in sorted(per_episode.items()):
        if args.episodes and ep not in args.episodes:
            continue
        tokens = caption_tokens(video_id)
        if tokens is None:
            no_caption.append(ep)
        for name in sorted(set(names)):
            count = corpus[name.lower()]
            if count > RARE_MAX:
                continue
            match = difflib.get_close_matches(name.lower(), frequent, n=1,
                                              cutoff=args.min_similarity)
            if match and match[0] != name.lower():
                ratio = difflib.SequenceMatcher(None, name.lower(), match[0]).ratio()
                near.append((-ratio, ep, name, match[0], count))
            elif tokens is not None:
                missing = [p for p in name.lower().split() if len(p) > 2 and p not in tokens]
                if missing:
                    unheard.append((count, ep, name, missing))

    print("=" * 78)
    print("LIKELY GARBLES -- a rare spelling close to an established one")
    print("=" * 78)
    if near:
        print(f"{'sim':>5} {'ep':6} {'as transcribed':30} {'probably':28} seen")
        for negative_ratio, ep, name, match, count in sorted(near):
            print(f"{-negative_ratio:5.2f} {ep:6} {name[:30]:30} {match[:28]:28} x{count}")
    else:
        print("none")

    print()
    print("=" * 78)
    print("UNCONFIRMED -- the episode's own captions never heard these tokens")
    print("=" * 78)
    for count, ep, name, missing in sorted(unheard)[:60]:
        print(f"  {ep:6} {name[:34]:34} caption lacks {missing}")
    if len(unheard) > 60:
        print(f"  ... and {len(unheard) - 60} more")
    if no_caption:
        print(f"\nno cached captions for: {', '.join(no_caption)} "
              f"(only the corpus check ran for these)")


if __name__ == "__main__":
    main()
