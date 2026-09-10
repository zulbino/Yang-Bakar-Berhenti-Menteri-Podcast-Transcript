"""Make the published interview read like newspaper copy: no grunts, no one-word retorts, no
filler words, and a speaker's consecutive turns joined into one paragraph.

OWNER'S RULE (2026-09-10): "the interview has to be really clean from all that human retort
and short reply, like standard newspaper journalism ... simplification but accurate story is
the key." raw.md is the verbatim record and is handled by strip_filler_turns.py; this is the
published layer, and it goes further than the raw does.

THREE EDITS, each a closed lexicon so nothing with meaning can be touched:

  1. A turn is DROPPED when every token in it is an acknowledgement or a vocalisation:
     "Ya.", "Okey.", "Ya, betul.", "Hmm.", "Haha." A turn with one content word stays --
     "2.3 billion.", "Koperasi?", "Tak." are answers and questions, not retorts.
  2. Filler TOKENS are removed inside a turn: "Uh,", "Um.", "Aaa", "Hmm," "Eh," -- the set
     below and nothing else. The word after a removed filler is capitalised when the filler
     opened the sentence, so "Uh, yang ini saya" becomes "Yang ini saya".
  3. Consecutive turns of one speaker are joined (merge_adjacent_turns.merge_body), because
     dropping a "Ya." between two Rafizi turns leaves them adjacent.

THE GUARD: every word removed must be in one of the two lexicons; the multiset of all other
words is asserted identical before and after. check_figures.py still runs on the result.

  python scripts/clean_interview.py ep62            # dry run, counts
  python scripts/clean_interview.py ep62 --write
"""
import argparse
import glob
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from merge_adjacent_turns import merge_body  # noqa: E402
from strip_filler_turns import FILLERS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TURN = re.compile(r"^\*\*([^*\n]{1,40}):\*\*[ \t]?(.*)$", re.S)
# Whole-turn acknowledgements, on top of the raw's vocalisation lexicon. "Tak" (no) and
# "Betul" alone could be answers, but "Betul." as a lone turn in this show is assent.
ACKS = FILLERS | {"ya", "yaa", "yah", "yalah", "yes", "yep", "yap", "yup", "iya", "ok", "okay",
                  "okey", "okeylah", "okaylah", "betul", "betullah", "faham", "hehe", "hehehe",
                  "hihi", "yeah", "right", "correct", "kan", "lah", "la", "yelah", "haah"}
# Inline fillers: only pure vocalisations, never an acknowledgement ("Ya" mid-sentence is content).
INLINE = {"uh", "uhh", "um", "umm", "erm", "err", "aa", "aaa", "aaaa", "hmm", "hm", "mm",
          "mhm", "mm-hmm", "mmhmm", "haah", "eh", "ehh"}
INLINE_RE = re.compile(r"(?<![\w-])(" + "|".join(sorted(map(re.escape, INLINE), key=len, reverse=True))
                       + r")(?![\w-])[,.]?\s*", re.I)


def tokens(text):
    return [t for t in re.findall(r"[\w'-]+", text.lower())]


def ack_only(text):
    toks = tokens(text)
    return bool(toks) and all(t in ACKS for t in toks)


def strip_inline(text):
    out = []
    pos = 0
    for m in INLINE_RE.finditer(text):
        before = text[pos:m.start()]
        out.append(before)
        # Capitalise the next word when the filler began the text or followed a sentence end.
        lead = "".join(out).rstrip()
        rest = text[m.end():]
        if (not lead or lead[-1] in ".?!") and rest[:1].islower():
            rest = rest[0].upper() + rest[1:]
            text = text[:m.end()] + rest
        pos = m.end()
    out.append(text[pos:])
    s = "".join(out)
    s = re.sub(r"\s+([,.?!])", r"\1", s)        # "kan ,"  -> "kan,"
    s = re.sub(r"([,.?!])\1+", r"\1", s)        # ",,"    -> ","
    s = re.sub(r"\s{2,}", " ", s).strip()
    s = re.sub(r"^[,.]\s*", "", s)              # a turn that began with a removed filler
    return s


def clean_body(body):
    paras = body.strip().split("\n\n")
    kept, dropped = [], 0
    for p in paras:
        m = TURN.match(p)
        if m and ack_only(m.group(2)):
            dropped += 1
            continue
        if m:
            text = strip_inline(m.group(2))
            if not tokens(text):
                dropped += 1
                continue
            p = f"**{m.group(1)}:** {text}"
        kept.append(p)
    merged, joined = merge_body("\n\n".join(kept))
    return merged, dropped, joined


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    tag, _, show = a.tag.partition(":")
    hits = [p for p in glob.glob(str(ROOT / f"episodes/*/*-{tag}-*/interview*.md"))
            if not show or show in Path(p).parts[-3]]
    if not hits:
        sys.exit(f"no interview files match {a.tag}")
    for path in sorted(hits):
        text = Path(path).read_text(encoding="utf-8")
        fm_end = text.index("\n---\n", 4) + 5
        head, rest = text[:fm_end], text[fm_end:]
        h1, body = rest.lstrip("\n").split("\n\n", 1)
        new_body, dropped, joined = clean_body(body)
        strip_labels = lambda t: re.sub(r"\*\*[^*\n]{1,40}:\*\*", "", t)
        before, after = Counter(tokens(strip_labels(body))), Counter(tokens(strip_labels(new_body)))
        removed = before - after
        added = after - before
        illegal = {w for w in removed if w not in ACKS | INLINE}
        assert not illegal, f"{Path(path).name}: removed non-filler words {sorted(illegal)[:10]}"
        assert not added, f"{Path(path).name}: words appeared {sorted(added)[:10]}"
        n_before, n_after = len(body.strip().split("\n\n")), len(new_body.strip().split("\n\n"))
        print(f"  {Path(path).name:17} {n_before} -> {n_after} turns; {dropped} retort turns dropped, "
              f"{sum(removed.values())} filler words removed, {joined} joins")
        if a.write:
            Path(path).write_text(head + "\n" + h1 + "\n\n" + new_body, encoding="utf-8")
    print("written" if a.write else "dry run, pass --write to apply")


if __name__ == "__main__":
    main()
