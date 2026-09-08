"""Drop turns that are nothing but a vocalisation, and keep every turn that says something.

WHY. MAI-Transcribe-2 transcribes backchannels the local ASR drops, so ep62's MAI raw has
314 turns reading `Hmm.` and 89 reading `Mm.` -- 519 of its 1,613 turns are one grunt each.
They are real sounds and belong in the raw transcript. They are noise in the source a
rewrite reads, where they break a speaker's argument into a dozen pieces for nothing. The
owner asked for them gone after checking three disputed regions by ear and finding the only
thing the other host contributed there was "hmm".

TURN-LEVEL, NOT WORD-LEVEL, AND THAT IS THE WHOLE SAFETY ARGUMENT. A turn is dropped only
when EVERY token in it is in the lexicon below. An inline `Uh,` inside a real sentence is
left alone, because editing inside a sentence is how [[feedback_anchor_filler_collapse_regex_locally]]
got burned -- a pattern that is right for one instance strips a genuine interjection
somewhere else in the file. Here the unit of deletion is a whole turn that carries no words.

THE LEXICON IS CLOSED AND DELIBERATELY SHORT. `Ya`, `Okey`, `Betul`, `Yes` and `Yalah` are
NOT in it. They are one-word turns too, and they are answers -- a person agreeing is content
and a person grunting is not. This corpus has form here: a blanket rule applied to a
plausible-looking class corrupted 185 correct names once already.

THE CHECK THAT MAKES IT SAFE. Every word that is not in the lexicon is counted before and
after, and the two multisets must be identical or nothing is written. A deletion that takes
one real word with it cannot reach disk.

  python scripts/strip_filler_turns.py data/_mai_<id>/raw_merged.md
  python scripts/strip_filler_turns.py data/_mai_<id>/raw_merged.md --write
"""
import argparse
import re
import sys
from collections import Counter
from pathlib import Path

TURN = re.compile(r"^\[([\d:]+)\] ([^:]+): (.*)$")

# Closed. Vocalisations only -- nothing here means anything on its own. Adding a word that
# does mean something is the one way to make this tool destructive, so keep the bar at
# "could this be a transcript of a noise rather than of speech".
FILLERS = {
    "hm", "hmm", "hmmm", "hmmmm",
    "mm", "mmm", "mmmm", "mhm", "mhmm", "mmhmm", "mmhm",
    "ha", "haa", "haaa", "haah", "hah", "haha", "hahaha",
    "ah", "aah", "ahh", "ahh", "aha", "ahaa",
    "oh", "ooh", "ohh",
    "uh", "uhh", "uhm", "um", "umm", "erm", "err", "er",
    "eh", "ehh", "huh", "hu",
}


def tokens(text):
    return re.findall(r"[0-9A-Za-z'À-ɏ-]+", text.lower())


def is_filler_only(text):
    words = tokens(text)
    return bool(words) and all(w.replace("-", "") in FILLERS for w in words)


def content_words(lines):
    """Every token in the file that the lexicon does not cover, as a multiset."""
    counter = Counter()
    for line in lines:
        match = TURN.match(line)
        if match:
            counter.update(w for w in tokens(match.group(3)) if w.replace("-", "") not in FILLERS)
    return counter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="a raw.md-format transcript")
    ap.add_argument("--out", help="defaults to rewriting PATH in place")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    path = Path(args.path)
    lines = path.read_text(encoding="utf-8").split("\n")

    kept, dropped = [], []
    for line in lines:
        match = TURN.match(line)
        if match and is_filler_only(match.group(3)):
            dropped.append((match.group(1), match.group(2), match.group(3)))
        else:
            kept.append(line)

    if not dropped:
        print(f"{path.name}: nothing to drop")
        return

    by_speaker = Counter(who for _, who, _ in dropped)
    by_text = Counter(text.strip() for _, _, text in dropped)
    turns_before = sum(1 for line in lines if TURN.match(line))
    print(f"{path.name}: {turns_before} turns -> {turns_before - len(dropped)}, "
          f"dropping {len(dropped)}")
    print("  by speaker: " + ", ".join(f"{who} {n}" for who, n in by_speaker.most_common()))
    print("  by text:")
    for text, n in by_text.most_common(20):
        print(f"    {n:5}  {text!r}")

    # Near misses, printed so the lexicon can be judged rather than trusted. A one-word turn
    # that is NOT dropped is either a real answer or a filler spelling nobody has seen yet.
    near = Counter()
    for line in kept:
        match = TURN.match(line)
        if match and len(tokens(match.group(3))) == 1 and not is_filler_only(match.group(3)):
            near[match.group(3).strip()] += 1
    print("  one-word turns KEPT (check none of these is a grunt):")
    print("    " + ", ".join(f"{t!r} x{n}" for t, n in near.most_common(12)))

    before, after = content_words(lines), content_words(kept)
    if before != after:
        lost = (before - after) + (after - before)
        sys.exit(f"REFUSING TO WRITE: {sum(lost.values())} non-filler words differ, "
                 f"{dict(lost.most_common(10))}")
    print(f"  verified: all {sum(before.values())} non-filler words unchanged")

    if not args.write:
        print("\n-- dry run, pass --write to apply")
        return
    Path(args.out or path).write_text("\n".join(kept), encoding="utf-8")
    print(f"wrote {args.out or path}")


if __name__ == "__main__":
    main()
