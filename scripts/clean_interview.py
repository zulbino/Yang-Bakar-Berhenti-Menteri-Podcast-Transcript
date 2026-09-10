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


SLIP_WORDS = 3


def drop_slips(paras):
    """Remove a short interjection that splits another speaker's sentence.

    "Rafizi: ... Balik kepada cerita." / "Haziq: Perumahan." / "Rafizi: Cerita perumahan lah."
    The owner's rule: a slip-in of a few words from another speaker that adds nothing to the
    story goes, and the sentence around it is rejoined. A turn of SLIP_WORDS words or fewer,
    sandwiched between two turns of one other speaker, is dropped when either the speaker it
    interrupts was mid-sentence (no terminal punctuation) or its words all occur in the
    surrounding turns (an echo). A short QUESTION after a finished sentence stays -- it is
    answered by what follows. Repeats until nothing changes, since a drop can create a new
    sandwich. Returns the kept paragraphs and the dropped interjection texts.
    """
    dropped = []
    changed = True
    while changed:
        changed = False
        parsed = [TURN.match(p) for p in paras]
        for i in range(1, len(paras) - 1):
            a, b, c = parsed[i - 1], parsed[i], parsed[i + 1]
            if not (a and b and c) or a.group(1) != c.group(1) or b.group(1) == a.group(1):
                continue
            words = tokens(b.group(2))
            if not words or len(words) > SLIP_WORDS:
                continue
            around = set(tokens(a.group(2)) + tokens(c.group(2)))
            mid_sentence = not re.search(r"[.?!]\s*$", a.group(2).strip())
            # A slip-in carrying a figure ("Iqbal: -35.", "46, awak 46.") is content unless the
            # surrounding speaker repeats it; mid-sentence alone does not justify dropping it.
            if (mid_sentence and not re.search(r"\d", b.group(2))) or all(w in around for w in words):
                dropped.append(b.group(2).strip())
                del paras[i]
                changed = True
                break
    return paras, dropped


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
    # To a fixpoint: joining two turns can expose a new sandwich, and dropping a slip-in
    # can make two more turns adjacent. One run must be the final state, so a second run
    # on the output changes nothing.
    slips, joined = [], 0
    while True:
        kept, new_slips = drop_slips(kept)
        merged, new_joins = merge_body("\n\n".join(kept))
        slips += new_slips
        joined += new_joins
        if not new_slips and not new_joins:
            return merged, dropped, joined, slips
        kept = merged.strip().split("\n\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--show-slips", action="store_true", help="print every dropped interjection")
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
        new_body, dropped, joined, slips = clean_body(body)
        strip_labels = lambda t: re.sub(r"\*\*[^*\n]{1,40}:\*\*", "", t)
        before, after = Counter(tokens(strip_labels(body))), Counter(tokens(strip_labels(new_body)))
        removed = before - after
        added = after - before
        slip_tokens = {w for s in slips for w in tokens(s)}
        illegal = {w for w in removed if w not in ACKS | INLINE | slip_tokens}
        assert not illegal, f"{Path(path).name}: removed non-filler words {sorted(illegal)[:10]}"
        assert not added, f"{Path(path).name}: words appeared {sorted(added)[:10]}"
        n_before, n_after = len(body.strip().split("\n\n")), len(new_body.strip().split("\n\n"))
        print(f"  {Path(path).name:17} {n_before} -> {n_after} turns; {dropped} retort turns dropped, "
              f"{sum(removed.values())} words removed, {len(slips)} slip-ins dropped, {joined} joins")
        if a.show_slips and slips:
            print("     slip-ins: " + " | ".join(slips))
        if a.write:
            Path(path).write_text(head + "\n" + h1 + "\n\n" + new_body, encoding="utf-8")
    print("written" if a.write else "dry run, pass --write to apply")


if __name__ == "__main__":
    main()
