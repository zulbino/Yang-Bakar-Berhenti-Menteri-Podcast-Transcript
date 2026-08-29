"""Correct ASR-garbled proper nouns across raw.md and the published files.

The local ASR and every rewrite engine garble Malaysian names, and the garble sometimes
outnumbers the correct spelling, so `check_proper_nouns.py` cannot infer which form is
right -- its `RARE_MAX = 4` even promotes a frequently-repeated garble to an "established
spelling". This applies corrections the owner has confirmed, one name at a time.

Every entry needs an owner decision behind it. A name is not a typo to be normalised by
majority vote: "Saleh" appears 266 times against "Salleh" 89, and those are not one
person spelled two ways -- which is exactly why this file holds a reviewed map rather
than a similarity heuristic.

  python scripts/fix_proper_nouns.py              # dry run, prints per-file counts
  python scripts/fix_proper_nouns.py --write

Each pattern uses an explicit negative lookahead rather than `\\b`, because a `\\b`
written into a file through a nested heredoc becomes a literal backspace and then
silently matches nothing (ENGINEERING_LOG 1.42).
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (regex, replacement, why). Longest/most-specific first, so a broader pattern cannot
# eat a more specific one's match.
CORRECTIONS = [
    (r"Fuzi Asaleh",
     "Fuziah Salleh",
     "Fuziah Salleh, PKR secretary-general. Garbled once, in ep37, inside a list of "
     "PKR figures -- 'orang macam Fuzi Asaleh, orang macam Izzah, orang macam Ramanan' "
     "-- which is what identifies it."),
    (r"Fusyah Saleh(?![A-Za-z])",
     "Fuziah Salleh",
     "Third garble of the same name, once."),
    (r"Fuziah Saleh(?![A-Za-z])",
     "Fuziah Salleh",
     "Her SURNAME, correctable only as a two-word pattern. A blanket Saleh -> Salleh "
     "would be wrong: the corpus's 266 `Saleh` and 89 `Salleh` cover at least four "
     "referents, and 35 of them are Akmal Saleh, whose name really does take one L. "
     "Fuziah 13x `Saleh` / 3x `Salleh`, Mat 11/7, Tun Salleh Abas 0/1."),
    (r"Fuzia(?![A-Za-z])",
     "Fuziah",
     "Same person, first name only. 24 occurrences against 244 already correct, and all "
     "24 are unambiguously her: 'setiausaha agung, Fuzia', 'Fuzia Saleh boleh "
     "dipertimbangkan untuk kur[angkan]'. Owner-confirmed 2026-08-29."),
    # Ceplos, the online political persona. Verified to exist before any substitution:
    # the label began as netizen shorthand for a social-media figure known for political
    # video content. ep07 makes the referent certain from inside the corpus -- "kemunculan
    # yang kalau di media sosial orang panggil 'cheplos' kan? Aku pun kena pergi Google
    # cheplos ni apa". Established spelling is overwhelming and not a bare majority
    # argument: 478 correct in the published files against these 16, and every one of the
    # 16 was read in context first.
    (r"Cepulau(?![A-Za-z])",
     "Ceplos",
     "ep34 x6 across all three published files: 'Cepulau masih lagi macam biasa ... dia "
     "dalam bubble dia'. Gemini's audio read of the same seconds heard 'Che Pblos', so "
     "two independent ASRs mangled one name two ways."),
    (r"Cephlos(?![A-Za-z])",
     "Ceplos",
     "raw x7, ep26/ep27/ep41: 'Walaupun Cephlos tak puas hati', 'ada ayat-ayat Cephlos "
     "ni', 'mungkin Cephlos yang repost'."),
    (r"cephlos(?![A-Za-z])",
     "ceplos",
     "One lowercase instance, ep41 interview.md: 'ini mungkin cephlos yang repost'. "
     "Missed by the capitalised entry above -- which is the argument for verifying a "
     "substitution by re-grepping rather than by reading the tool's own count."),
    (r"Cheplos(?![A-Za-z])",
     "Ceplos",
     "Capitalised form of the ep07 garble; kept separate from the lowercase entry so "
     "running-text case is preserved -- the corpus uses `ceplos` lowercase 222 times."),
    (r"cheplos(?![A-Za-z])",
     "ceplos",
     "ep07 x10 across the three published files, inside the quoted phrase where Rafizi "
     "says he had to look the term up."),
]

# DELIBERATELY NOT CORRECTED, verified against sources 2026-08-29. Recorded so the
# analysis is not redone, and because each of these looks like an obvious sweep until
# you check who the name belongs to.
#
#   Akmal Saleh -- ONE L IS CORRECT. 185 occurrences. Muhamad Akmal bin Saleh, UMNO
#     Youth chief; Wikipedia and every news source spell it Saleh. A blanket
#     `Saleh` -> `Salleh` would have corrupted all 185, which is the reason the Fuziah
#     surname fix above is a two-word pattern.
#     https://en.wikipedia.org/wiki/Muhamad_Akmal_Saleh
#   Mat Saleh / Mat Salleh -- BOTH ARE LEGITIMATE. The colloquialism for a Westerner is
#     attested either way; the OED's own etymology entry lists "Malay mat saleh". Not a
#     garble, so 11 `Saleh` and 7 `Salleh` are both left as spoken.
#     https://www.oed.com/dictionary/mat-salleh_n
#   Tun Salleh Abas -- already correct in its single occurrence.
#   mak Saleh / Mak Salleh -- 6 occurrences, referent not established. Left alone.
#
# The general rule this corpus keeps proving: a name is not a spelling to normalise by
# majority vote. The majority form was WRONG for Fuziah and RIGHT for Akmal.


def targets():
    return (sorted(ROOT.glob("episodes/*/*/raw.md"))
            + sorted(ROOT.glob("episodes/*/*/interview.md"))
            + sorted(ROOT.glob("episodes/*/*/interview-en.md"))
            + sorted(ROOT.glob("episodes/*/*/interview-ms.md")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    compiled = [(re.compile(rx), rep, why) for rx, rep, why in CORRECTIONS]
    for rx, rep, _ in compiled:
        # A pattern that lost its escapes matches nothing and reports a clean zero, so
        # prove it is intact before trusting any count below.
        print(f"pattern {rx.pattern!r} -> {rep!r}")

    totals = {rep: 0 for _, rep, _ in compiled}
    touched = 0
    for path in targets():
        text = original = path.read_text(encoding="utf-8")
        hits = {}
        for rx, rep, _ in compiled:
            text, n = rx.subn(rep, text)
            if n:
                hits[rep] = hits.get(rep, 0) + n
                totals[rep] += n
        if text != original:
            touched += 1
            rel = path.relative_to(ROOT / "episodes")
            print(f"  {str(rel):78s} {hits}")
            if args.write:
                path.write_text(text, encoding="utf-8")

    print(f"\n{touched} file(s) {'written' if args.write else 'would change'}")
    for rep, n in totals.items():
        print(f"  -> {rep}: {n}")
    if not args.write:
        print("\n-- dry run, pass --write to apply --")


if __name__ == "__main__":
    main()
