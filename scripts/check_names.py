"""Check PERSON NAMES in the published files against raw.md.

`check_figures.py` catches an invented NUMBER. Nothing caught an invented NAME, and four
turned up by hand on 2026-08-29, each naming a different real person than the transcript
does:

  ep48  raw `Farha Hashma Ramana`      -> published `Fahmi Fadzil dan kroni-kroninya`
  ep58  raw `Lim Siansi`               -> published `Lim Guan Eng`
  ep60  raw `Ismail Saleh` / `Abid Abdullah` -> published `Ismail Sabri` / `Ahmad Zahid`
  ep13  raw `YB Lee Chean Chung`       -> published `YB Lim Guan Eng... eh, YB Lee Chean Chung`

The last one is the shape to fear: the rewrite INSERTED a politician's name and a fake
self-correction around a name that was already right.

HOW IT DECIDES. The name vocabulary is the corpus's own: every name the transcripts write
after an honorific (YB, Datuk, Dato', Tan Sri, Menteri...), seen at least twice, which is
`check_proper_nouns.collect()`. For each episode, any of those people named in
interview.md must have a plausible source in that episode's raw.md, compared on a
space-and-punctuation-stripped form so an ASR garble still counts as a source.

WHAT IT IS NOT. This is a REVIEW LIST, not a gate, and the reason is measured. At cutoff
0.72 the eleven hits corpus-wide were ten legitimate full-name expansions -- raw says
`Rafizi`, published says `Dato' Sri Rafizi Ramli`, and the added surname drags the
similarity below any threshold that still catches `Fahmi Fadzil` -- and one real defect.
Tightening the cutoff to remove the expansions also removes the defect. So the output is
small enough to read, and reading it is the point.

Three limits worth knowing before trusting a clean run:

  1. A fabrication survives if raw contains a name close enough to the invented one.
     Measured against the five confirmed cases, this check flags four and MISSES ep60's
     `Ismail Sabri`, because raw's `Ismail Saleh` scores above the cutoff. A near-miss
     surname is exactly what it cannot see.
  2. Only interview.md is read. interview-en.md translates Malay institutions into
     English, which raw can never source, and that noise buried the real hits.
  3. Two ASRs agreeing that a name SOUNDS a certain way is not evidence the name is
     right, only that the published text changed it (ENGINEERING_LOG 1.28).

Returns [(signature, message)] so qa_check.py can fold these in beside its own.
"""
import difflib
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_language_drift import strip_frontmatter
import check_proper_nouns as cpn

ROOT = Path(__file__).resolve().parent.parent
# Below this, an ASR garble stops looking like the source of the published spelling.
# Calibrated on the confirmed cases: raw `Zafro` -> published `Zafrul` scores 0.73 and must
# pass; raw `Farha Hashma` -> `Fahmi Fadzil` scores 0.46 and must fail.
SIMILARITY = 0.72
# Ministry and portfolio words. `Menteri Dalam Negeri` makes the honorific extractor emit
# `Dalam Negeri` as if it were a person, and those fragments were 20 of the first 32 hits.
PORTFOLIO = {
    "dalam", "negeri", "kewangan", "pendidikan", "tinggi", "sumber", "manusia", "besar",
    "johor", "next", "kita", "dan", "ekonomi", "perdagangan", "wilayah", "pertahanan",
    "kesihatan", "pengangkutan", "komunikasi", "digital", "belia", "sukan", "luar",
    "perumahan", "tempatan", "pelancongan", "kerja", "raya", "persekutuan", "antarabangsa",
}


def squash(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s.lower()))


def known_people():
    corpus, _ = cpn.collect()
    return {n for n, count in corpus.items()
            if count >= 2 and len(n.split()) >= 2
            and not all(w in PORTFOLIO for w in n.split())}


def raw_sources(raw_body):
    """Every 1-4 word run in raw, squashed, as candidate sources.

    NOT restricted to capitalised runs. The ASR lower-cases names often enough to matter:
    ep41's raw writes `azam baki`, and a capitals-only extractor called the published
    `Azam Baki` unsourced. Dropping the case requirement removes that whole class of false
    positive and costs nothing in recall -- ep48's `Fahmi` and ep13's `Guan`/`Eng` are
    absent from their raw in ANY case.
    """
    words = re.findall(r"[A-Za-z'-]{2,}", raw_body)
    out = set()
    for i in range(len(words)):
        for n in range(1, 5):
            if i + n <= len(words):
                out.add(squash(" ".join(words[i:i + n])))
    return {w for w in out if len(w) >= 5}


def check(ep_dir, people=None):
    raw_path, pub_path = ep_dir / "raw.md", ep_dir / "interview.md"
    if not raw_path.exists() or not pub_path.exists():
        return []
    people = people if people is not None else known_people()
    sources = raw_sources(strip_frontmatter(raw_path.read_text(encoding="utf-8")))
    pub = strip_frontmatter(pub_path.read_text(encoding="utf-8"))
    unsupported = []
    for person in sorted(people):
        m = re.search(r"\b" + re.escape(person) + r"\b", pub, re.I)
        if not m:
            continue
        if difflib.get_close_matches(squash(person), sources, n=1, cutoff=SIMILARITY):
            continue
        quote = " ".join(pub[max(0, m.start() - 70):m.end() + 70].split())
        unsupported.append((person, quote))
    if not unsupported:
        return []
    names = ", ".join(f"{p!r}" for p, _ in unsupported)
    return [(
        "unsourced-name",
        f"interview.md names {len(unsupported)} person(s) raw.md does not support "
        f"({names}) -- usually a legitimate full-name expansion, but this is how ep13's "
        f"invented 'Lim Guan Eng' and ep48's 'Fahmi Fadzil' read too. Quote: "
        f"...{unsupported[0][1]}...",
    )]


def main():
    people = known_people()
    print(f"{len(people)} person names known to the corpus\n")
    flagged = 0
    for ep_dir in sorted((ROOT / "episodes").glob("*/*")):
        if not ep_dir.is_dir() or ep_dir.name.startswith("_"):
            continue
        for _, message in check(ep_dir, people):
            flagged += 1
            print(f"{ep_dir.name[:44]}\n   {message}\n")
    print(f"{flagged} episode(s) with at least one unsourced person name")


if __name__ == "__main__":
    main()
