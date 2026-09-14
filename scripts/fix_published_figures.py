"""Correct figures the REWRITE got wrong, in the published interview files only.

WHY THIS EXISTS, AND WHY IT IS NOT fix_proper_nouns.py. `check_figures.py` compares every
digit string in interview.md/-en/-ms against raw.md and reports the ones raw cannot source.
It flagged seven real figures across six episodes on 2026-09-14 and nothing could fix them:
`fix_proper_nouns.py` holds a CORPUS-WIDE map for names, and a bare `200 juta` or `47K` is
not safe to rewrite corpus-wide. A figure correction is inherently episode-scoped, so it
needs its own map, keyed by episode.

THIS SCRIPT NEVER TOUCHES raw.md. raw.md is the source every published file is derived
from, and in all seven cases raw.md was already right. Where the RAW carries the wrong
digit instead, the fix goes in `fix_proper_nouns.py`'s map so that
`mai_camera_raw.py` reapplies it on every rebuild -- ep31's `180.8 million` is the one
entry of that kind. The two directions are different defects and they have different homes.

THIS IS INTERIM WORK AND SAYS SO. Six of the seven figures came from the old local-ASR raw,
which the rewrite copied faithfully; regenerating the published files from the MAI raw fixes
those by itself. The owner chose on 2026-09-14 to correct them now rather than wait for the
regeneration of 33 stale published files, because the repo is public and the errors are
material (a ten-fold error on a tax-refund figure, and 47 court cases printed as `47K`).
A regeneration overwrites everything here, which is expected, not a problem.

EVERY ENTRY NEEDS TWO INDEPENDENT WITNESSES, and the `why` records them. The standard is
the owner's rule of 2026-09-12: settle a disputed digit by witness count, never by ear or
by which engine usually wins. The witnesses available are raw.md (MAI), the Malay caption
track in audio/*.vtt, the pre-adoption local-ASR raw, and the sentence's own arithmetic.

THE GUARD: every rule declares how many occurrences it expects across the three files, and
the script refuses to write if the real count differs. Each `find` was verified unique
before it was added here. A figure is the last thing that should be replaced by a loose
pattern, so there are no regexes in this file at all, only literal strings.

  python scripts/fix_published_figures.py            # dry run, prints every change
  python scripts/fix_published_figures.py --write
  python scripts/fix_published_figures.py --tag ep55 # one episode
"""
import argparse
import glob
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["interview.md", "interview-en.md", "interview-ms.md"]

# tag -> list of (find, replace, expected_total_occurrences, why)
FIGURES = {
    "ep31": [
        ("dilaporkan lah, 75 juta kan", "dilaporkan lah, 7.5 juta kan", 2,
         "raw.md says `7.5 juta` and the Malay caption track says `7.5 juta` in the same "
         "sentence. `75 juta` survives only in the pre-adoption local-ASR raw, which the "
         "rewrite copied. The passage is Rafizi allowing for the share price being 39.978 "
         "sen rather than a round 40, so the figure is a small adjustment, not a total."),
        ("what was reported, 75 million", "what was reported, 7.5 million", 1,
         "The English translation of the same sentence. Same two witnesses."),
    ],
    "ep34": [
        ("RM75 bilion dibuat", "RM7.5 bilion dibuat", 2,
         "A TEN-FOLD ERROR, and the worst of this set. raw.md says `7.5 bilion` and the "
         "Malay caption track says `7.5 bilion` FOUR times and `75 bilion` never. The "
         "sentence's own arithmetic agrees: it calls this repayment higher than the PM's "
         "initial commitment of 4 bilion, which 7.5 exceeds narrowly and 75 overshoots "
         "absurdly. The pre-adoption local-ASR raw said `RM75 bilion`."),
        ("RM75 billion was made", "RM7.5 billion was made", 1,
         "The English translation of the same sentence. Same three witnesses."),
    ],
    "ep49": [
        ('"scuba 677" tu?', '"scuba" tu?', 2,
         "The caption track reads `kenapa tak buat scuba? [ketawa]` with no number "
         "attached, and raw.md puts the `6 7` meme in a SEPARATE later exchange (`Dia 6 7, "
         "6 7 lah kan?` then `Ha, 6 7. Wartawan.`). The pre-adoption raw fused the two into "
         "`677`. Deleting the number restores what was said; it does not remove a figure "
         "anyone uttered here."),
        ('"scuba 677" means?', '"scuba" means?', 1,
         "The English translation of the same line. Same two witnesses."),
        ("dia kata, 1B di Pandan", "dia kata, di Pandan", 2,
         "raw.md says only `Di Pandan lah` and the caption track carries no `1B` anywhere. "
         "The pre-adoption local-ASR raw had `1B di Pandan`, so the rewrite inherited it. "
         "Nothing in the episode explains a `1B`, and the passage is about Anwar's "
         "confidence on election night, not a seat number."),
        ("seat 1B in Pandan", "Pandan", 1,
         "The English rewrite went further than the Malay and turned the artefact into "
         "`seat 1B`, inventing a meaning for it. Same two witnesses deny it."),
        ("Facebook 3.3 juta", "Facebook 3 juta", 2,
         "raw.md says `Facebook 3 point. Ha, 3 juta` and the caption track matches it word "
         "for word: `Facebook 3 ... ah 3 juta lebih dekat 4 jutalah kan`. The speaker starts "
         "a decimal and then says `3 juta`. There is no 3.3. The pre-adoption raw wrote `3 "
         "point 3 juta` and the rewrite compressed that to `3.3`. The later `Facebook dekat "
         "3.1` in the same sentence is CORRECT and is left alone."),
        ("Facebook 3.3 million", "Facebook 3 million", 1,
         "The English translation of the same sentence. Same two witnesses."),
    ],
    "ep52": [
        ("DNAA, 47K marah", "DNAA 47 kes, marah", 2,
         "THE ONLY ONE THE REWRITE INVENTED FROM A CORRECT SOURCE, which is why it matters "
         "more than its size suggests. BOTH raws agree: the MAI raw and the pre-adoption "
         "local-ASR raw each say `DNAA 47 kes`, and the Malay captions say `47 kes` twice. "
         "`47K` appears in no witness at all. So 47 court cases became 47 thousand "
         "somethings at the rewrite stage with a correct raw on both sides of it. "
         "Regeneration can repeat this, so re-check ep52 after any rewrite."),
        ("the 47K case here and there", "the 47 cases here and there", 1,
         "The English rewrite kept `47K` and added a singular `case`, which compounds the "
         "error. Same three witnesses."),
    ],
    "ep55": [
        ("200 juta", "700 juta", 2,
         "raw.md says `700 juta` and the caption track settles it outright: `itu pun dah "
         "saya ingat 700 juta`. The pre-adoption local-ASR raw said `200 juta`. The figure "
         "is the cost of widening the PLUS highway from Senai to Yong Peng, which Rafizi "
         "raises as a fairness complaint about federal spending in Johor."),
        ("200 million", "700 million", 1,
         "The English translation of the same sentence. Same two witnesses."),
    ],
    "ep59": [
        ("rugi 120 juta", "rugi 102 juta", 2,
         "raw.md says `rugi 102 juta` and the caption track settles it: `pasaran saham "
         "jatuh balik ah rugi 102 juta okey`. The pre-adoption local-ASR raw said `120 "
         "juta`. The figure is Tabung Haji's 2025 share-price loss, discussed against its "
         "1.4 bilion holding, so the scale is right either way and only the digits differ."),
        ("loss of RM120 million", "loss of RM102 million", 1,
         "The English translation of the same sentence. Same two witnesses."),
    ],
}


def episode_dir(tag):
    hits = glob.glob(str(ROOT / f"episodes/*/*-{tag}-*"))
    if len(hits) != 1:
        sys.exit(f"{tag}: {len(hits)} episode folders match, need exactly 1")
    return Path(hits[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--tag", help="one episode tag, e.g. ep55")
    a = ap.parse_args()

    tags = [a.tag] if a.tag else list(FIGURES)
    changed_files = applied = refusals = 0

    for tag in tags:
        d = episode_dir(tag)
        texts = {}
        for fn in FILES:
            p = d / fn
            if p.exists():
                texts[fn] = io.open(p, encoding="utf-8").read()

        print(f"=== {tag}  {d.name}")
        for find, repl, expect, _why in FIGURES[tag]:
            seen = {fn: t.count(find) for fn, t in texts.items() if t.count(find)}
            total = sum(seen.values())
            if total != expect:
                # Refuse rather than write. A count that has moved means the file was
                # regenerated or already corrected, and either way this rule no longer
                # describes the text it was reviewed against.
                print(f"  REFUSING {find!r}: found {total}, expected {expect} "
                      f"({seen or 'nowhere'}) -- re-review this rule against the file")
                refusals += 1
                continue
            for fn in seen:
                texts[fn] = texts[fn].replace(find, repl)
                applied += 1
            print(f"  {find!r} -> {repl!r}  in {', '.join(seen)}")

        if a.write and not refusals:
            for fn, t in texts.items():
                p = d / fn
                if t != io.open(p, encoding="utf-8").read():
                    io.open(p, "w", encoding="utf-8", newline="").write(t)
                    changed_files += 1

    verb = "applied to" if a.write else "would change"
    print(f"\n{applied} replacement(s) {verb} {changed_files if a.write else '?'} file(s)"
          f"{f', {refusals} rule(s) REFUSED' if refusals else ''}")
    if refusals and a.write:
        sys.exit("nothing written: fix or re-review the refused rule(s) first")
    if not a.write:
        print("dry run -- pass --write to apply, then run scripts/check_figures.py")


if __name__ == "__main__":
    main()
