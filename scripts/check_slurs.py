"""Find an offensive word the corpus attributes to someone who did not say it.

WHY THIS EXISTS. On 2026-09-16 a sweep found `Babi` standing in for the honorific `YB` in
36 places, including the show's own transition line `Okey, baik YB` in ten of them. `babi`
is Malay for pig. Nothing in the repo had ever looked for it: `fix_yb_honorific.py` knew
twelve spellings of the garble and not that one, and the adoption report counted "YB
garbles" with a regex that did not list it either.

The same sweep then found the more serious class. FOUR published passages carried an insult
that raw.md does not contain, because the rewrite stage changed a benign word:

  ep15  raw `budak bangsa enam angka`   -> published `budak bangsat enam angka`
  ep51  raw `Bangsa final kot`          -> published `Bangsat final kot`   (x3)
  ep16  raw `Salawat teruk`             -> published `celaka teruk`
  ep42  raw `Fadina mesti cakap, damn`  -> published `"sial, aku dah...`

`bangsa` is race or nation and `bangsat` is bastard. `Salawat` is an Islamic blessing and
`celaka` means cursed. So the corpus quoted real, named people saying things they did not
say, in the direction that does the most damage. All four are corrected in
`fix_proper_nouns.py` so the fix survives a regeneration of the published files.

TWO CHECKS, because the two failures look nothing alike:

  1. UNSOURCED. An offensive term in interview.md, interview-en.md or interview-ms.md that
     raw.md does not support. This is the ep15/ep16/ep42/ep51 class, and the same shape as
     `check_names.py`, which does this for person names. Only a term in GATE fails the run.
     A term in MILD is printed and does not, because a translation reaches for those words
     honestly. Gating on both gave 34 findings of which 30 were correct translation, and a
     checker that is mostly wrong gets ignored.
  2. NEAR MISS. A term in raw.md that is one edit away from a common benign word, listed
     with that word so the pair can be read rather than guessed. `beruk` and `buruk` differ
     by one letter, and `beruk` is a slur while `buruk` just means bad. Both of the corpus's
     `beruk` were read and both are genuine Malay idiom: ep21 `terperanjat beruk` and ep34
     `nak suruh beruk tengok ke?`. Reported, never rewritten.

WHAT IS NOT A DEFECT. Most hits are real speech, and this is a political podcast that
discusses race, religion and corruption. `bodoh`, `gila` and `bangang` are everyday Malay.
`lembu` and `kerbau` appear because the NFC cattle scandal is a recurring subject. `kafir`,
`syaitan` and `setan` appear in religious argument. ep55 says `babi` eleven times about an
actual pork issue in a Johor seat, and ep33 about pork as food. So a raw.md hit is printed
for a reader and never changed: rule 5 of CLAUDE.md keeps any word that carries meaning,
and deleting a word a person really said would be the worse error.

ADDING A TERM. Put it in TERMS. If it is one edit from an innocent word, put that pair in
NEAR_MISS too, with the benign word second. Do not add a fix here -- an anchored, reviewed
entry in `fix_proper_nouns.py` is where a correction belongs, so it survives a rebuild.

  python scripts/check_slurs.py             # the unsourced check, which is the gate
  python scripts/check_slurs.py --all       # also list every raw.md hit, for a read
"""
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DERIVED = ("interview.md", "interview-en.md", "interview-ms.md")

# GATE: a word that cannot arrive in a published file by honest translation. If one of
# these appears with no support in raw.md, the corpus has invented an insult, and the run
# exits 1.
GATE = {
    "babi", "bangsat", "keparat", "celaka", "sial", "haramjadah",
    "pukimak", "puki", "kimak", "cibai", "butoh", "butuh", "pantat", "sundal", "sundel",
    "lonte", "jalang", "keling", "sepet", "pariah",
    "cunt", "nigger", "nigga", "faggot", "retard", "retarded", "whore", "slut", "fuck",
    "fucking", "bitch",
}

# REPORT ONLY. These are real words with innocent uses, and a translation legitimately
# reaches for them, so an unsourced hit is usually not a defect. The first version of this
# script gated on them too and produced 34 findings of which 30 were correct translation:
# `syaitan itu ada dalam perincian` is the English idiom "the devil is in the details",
# `damn` renders a Malay intensifier in interview-en.md, and `lembu` appears because the
# NFC cattle scandal is a recurring subject. They are still printed, because a cluster of
# them in one episode is worth a look.
MILD = {
    "khinzir", "jahanam", "bahlul", "tolol", "dungu", "bangang", "bodoh", "gila",
    "anjing", "setan", "syaitan", "pelesit", "beruk", "monyet", "kerbau", "lembu",
    "pendatang", "kafir", "murtad", "shit", "bastard", "damn",
}

TERMS = GATE | MILD

# A slur that is one edit from an innocent word, so an ASR slip produces it by accident.
# (slur, the benign word it is probably a garble of, why it matters)
NEAR_MISS = [
    ("beruk", "buruk", "baboon vs bad"),
    ("keling", "keliling", "an ethnic slur for Indians vs `around`"),
    ("jalang", "jalan", "whore vs road, and `jalan` is in every other sentence"),
    ("pantat", "pantai", "vulgar vs coast, and `Lembah Pantai` is a real constituency"),
    ("sial", "sila", "damn vs please"),
    ("bangsat", "bangsa", "bastard vs race or nation -- this one really happened, ep15 and ep51"),
    ("tolol", "tolong", "moron vs help"),
    ("babi", "YB", "pig vs the honorific -- 36 occurrences, found 2026-09-16"),
]

WORD = re.compile(r"[A-Za-zÀ-ɏ']+")


def episodes():
    for folder in sorted((ROOT / "episodes").glob("*/*")):
        if folder.is_dir() and (folder / "raw.md").exists():
            tag = re.search(r"-(ep\d+)-", folder.name)
            yield (tag.group(1) if tag else folder.name), folder


def hits(text):
    found = defaultdict(list)
    for m in WORD.finditer(text):
        w = m.group(0).lower()
        if w in TERMS:
            found[w].append(text[max(0, m.start() - 60):m.end() + 40].replace("\n", " "))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="also print every raw.md occurrence, so a human can read them")
    a = ap.parse_args()

    unsourced, raw_total, near = [], defaultdict(int), []
    for tag, folder in episodes():
        raw = (folder / "raw.md").read_text(encoding="utf-8")
        in_raw = hits(raw)
        for term, spans in in_raw.items():
            raw_total[term] += len(spans)
        for name in DERIVED:
            path = folder / name
            if not path.exists():
                continue
            for term, spans in hits(path.read_text(encoding="utf-8")).items():
                if term not in in_raw:
                    unsourced.append((tag, name, term, spans[0]))
        for slur, benign, why in NEAR_MISS:
            if slur in in_raw:
                near.append((tag, slur, benign, why, len(in_raw[slur])))

    print(f"{sum(raw_total.values())} occurrence(s) of {len(raw_total)} term(s) in raw.md, "
          "every one of them a word somebody said")
    if a.all:
        for term in sorted(raw_total, key=lambda t: -raw_total[term]):
            print(f"   {term:12s} {raw_total[term]:4d}")

    gated = [u for u in unsourced if u[2] in GATE]
    mild = [u for u in unsourced if u[2] not in GATE]

    print(f"\n{len(gated)} SLUR(S) in a published file that raw.md does not support:")
    for tag, name, term, span in gated:
        print(f"   [unsourced-slur] {tag} {name}: {term!r} is absent from raw.md")
        print(f"       ...{span}")
    if gated:
        print("   raw.md is the verbatim source. A derived file holding a slur it does not "
              "contain is quoting someone as saying it. Read raw.md at that point, then add "
              "an anchored entry to fix_proper_nouns.py so a regeneration keeps the fix.")

    print(f"\n{len(mild)} milder term(s) unsourced, almost always honest translation:")
    for tag, name, term, _ in mild:
        print(f"   {tag} {name}: {term!r}")

    if near:
        print(f"\n{len(near)} near-miss term(s) in raw.md, for a READ and not a rewrite:")
        for tag, slur, benign, why, n in near:
            print(f"   {tag} {slur!r} x{n} -- one edit from {benign!r} ({why})")

    return 1 if gated else 0


if __name__ == "__main__":
    sys.exit(main())
