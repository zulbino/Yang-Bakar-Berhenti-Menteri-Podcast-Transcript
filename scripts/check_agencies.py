"""Check GOVERNMENT AGENCY names, the checker CLAUDE.md rule 2 was missing.

`check_names.py` cross-checks a PERSON against the corpus's own roster of people. Rule 2
asks the same question about an agency, and until now nothing asked it. The two defects it
looks for are both attested in this corpus:

  1. A GARBLED agency name in any file. Measured on the pristine corpus: `Kementerian
     Keuangan` / `Menteri Keuangan` x12 across 8 episodes -- `keuangan` is the INDONESIAN
     word, Malaysia's ministry is `Kementerian Kewangan`. ep15's line 69 writes both forms
     in one sentence (`kepada kementerian kewangan Asalnya Tetapi Kementerian Keuangan
     kata`), which is what proves it is the ASR and not the speaker.
  2. An agency named in interview.md that raw.md does not support -- the rewrite swapping
     one real ministry for another, the agency-shaped version of ep48's invented
     `Fahmi Fadzil`.

WHERE THE TRUTH COMES FROM. `data/agency_roster.json`, web-verified entry by entry with a
source URL on each. Never the corpus's own majority spelling: that is the rule J-KOM
settled, where `JKOM` outnumbered the agency's own `J-KOM` and was still wrong. An agency
missing from the roster is flagged nowhere, which is a safe false negative; a wrong roster
entry would flag a correct name, which is not. So entries need a source, not a memory.

WHAT IT IS NOT. A review list, like `check_names.py`, not a gate. It reports; a human
web-verifies the hit and, if it is real, the fix goes in `fix_proper_nouns.py`'s reviewed
map so it applies corpus-wide instead of once.

The extension rule is why `Kementerian Pendidikan Tinggi` is silent against the roster's
`Kementerian Pendidikan`: a candidate that merely extends or truncates a roster name is a
different real body or a short mention, never a garble.

  python scripts/check_agencies.py                      # whole corpus, raw + interview
  python scripts/check_agencies.py --episodes ep15 ep12
"""
import argparse
import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_language_drift import strip_frontmatter

ROOT = Path(__file__).resolve().parent.parent
ROSTER = ROOT / "data" / "agency_roster.json"

# Calibrated on the pristine corpus: `Kementerian Keuangan` vs `Kementerian Kewangan`
# scores 0.95 and must fire; the nearest thing to a false positive below this is
# `Suruhanjaya Diraja` (a Royal Commission, a real body not in the roster) against
# `Suruhanjaya Pilihan Raya` at 0.79, which must stay silent.
GARBLE = 0.88
# Same cutoff and the same reason as check_names.SIMILARITY: an ASR garble still counts as
# the source of a published spelling.
SOURCED = 0.72
HEAD = (r"Kementerian|Menteri|Jabatan|Suruhanjaya|Lembaga|Majlis|Perbadanan|"
        r"Kumpulan Wang|Pihak Berkuasa|Polis Diraja")
PHRASE = re.compile(r"\b(" + HEAD + r")((?:\s+[A-Za-z'-]{2,}){1,4})", re.I)


def squash(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s.lower()))


def load_roster():
    entries = json.loads(ROSTER.read_text(encoding="utf-8"))["agencies"]
    # `Menteri X` is how the corpus usually says the ministry, so a roster name gets its
    # `Kementerian` form matched under either head word.
    names = {}
    for e in entries:
        names[e["name"]] = e
        if e["name"].startswith("Kementerian "):
            names["Menteri " + e["name"][len("Kementerian "):]] = e
    return entries, names


def titled(word):
    """Written as part of a proper noun: capitalised, or the connector `dan`."""
    return word[:1].isupper() or word.lower() == "dan"


def garbles(body, names):
    """Agency-shaped phrases that nearly, but not exactly, match a roster name.

    Both sides must be written as a TITLE -- capitalised head word, capitalised portfolio
    words -- and that condition is what makes the output readable. Without it the first
    corpus-wide run returned 52 hits, and 30 of them were an ordinary Malay word sitting
    after the head: `kementerian dengan`, `kementerian kerana`, `menteri kanan`,
    `Menteri mempertahankan`. `dengan` occurs 7,220 times in raw; it is not a garbled
    portfolio name, and no similarity cutoff can tell the difference.

    The measured cost of that condition: two real lowercase garbles go unreported, ep35's
    `Menteri yang kewangan` and ep42's `Menteri kelihatan` (for Kesihatan). A lowercase
    garble is exactly what this cannot see, the same way check_names.py cannot see a
    near-miss surname.
    """
    squashed = {squash(n): n for n in names}
    hits = {}
    for m in PHRASE.finditer(body):
        if not m.group(1)[:1].isupper():
            continue
        best = None
        for n in range(1, 5):
            words = m.group(2).split()[:n]
            if len(words) < n or not all(titled(w) for w in words):
                break
            phrase = " ".join([m.group(1)] + words)
            key = squash(phrase)
            if key in squashed:          # exact roster name, nothing to report
                best = None
                break
            close = difflib.get_close_matches(key, squashed, n=1, cutoff=GARBLE)
            if close and (best is None or len(phrase) > len(best[0])):
                best = (phrase, squashed[close[0]], key, close[0])
        if not best:
            continue
        phrase, official, key, official_key = best
        # An extension (`Kementerian Pendidikan Tinggi`) or a truncation
        # (`Kementerian Perdagangan`) of a roster name is a different real body or a short
        # mention of the same one, not a misspelling of it. Tested against EVERY roster
        # name, not just the closest one: ep28's `Menteri Pertanian dan` truncates KPKM,
        # but scores closer to `Menteri Pertahanan`, and checking only the closest match
        # reported Aziz Ishak as Defence Minister when he ran Agriculture.
        if any(key.startswith(k) or k.startswith(key) for k in squashed):
            continue
        quote = " ".join(body[max(0, m.start() - 60):m.end() + 40].split())
        hits.setdefault((phrase, official), quote)
    return hits


def unsourced(pub_body, raw_body, entries):
    """Roster agencies interview.md names that raw.md cannot source."""
    words = re.findall(r"[A-Za-z'-]{2,}", raw_body)
    sources = set()
    for i in range(len(words)):
        for n in range(1, 6):
            if i + n <= len(words):
                sources.add(squash(" ".join(words[i:i + n])))
    sources = {s for s in sources if len(s) >= 4}
    out = []
    for e in entries:
        for form in [f for f in (e["acronym"], e["name"]) if f and len(f) >= 4]:
            m = re.search(r"\b" + re.escape(form) + r"\b", pub_body)
            if not m:
                continue
            if difflib.get_close_matches(squash(form), sources, n=1, cutoff=SOURCED):
                continue
            quote = " ".join(pub_body[max(0, m.start() - 70):m.end() + 70].split())
            out.append((form, quote))
    return out


def check(ep_dir):
    entries, names = load_roster()
    raw_path = ep_dir / "raw.md"
    if not raw_path.exists():
        return []
    issues = []
    raw_body = strip_frontmatter(raw_path.read_text(encoding="utf-8"))
    for name in ("raw.md", "interview.md", "interview-ms.md"):
        path = ep_dir / name
        if not path.exists():
            continue
        hits = garbles(strip_frontmatter(path.read_text(encoding="utf-8")), names)
        for (phrase, official), quote in sorted(hits.items()):
            issues.append((
                "garbled-agency",
                f"{name} writes {phrase!r} where the verified name is {official!r} "
                f"(data/agency_roster.json) -- web-verify, then fix corpus-wide in "
                f"fix_proper_nouns.py. Quote: ...{quote}...",
            ))
    pub_path = ep_dir / "interview.md"
    if pub_path.exists():
        pub_body = strip_frontmatter(pub_path.read_text(encoding="utf-8"))
        miss = unsourced(pub_body, raw_body, entries)
        if miss:
            listed = ", ".join(repr(f) for f, _ in miss)
            issues.append((
                "unsourced-agency",
                f"interview.md names {len(miss)} agency/agencies raw.md does not support "
                f"({listed}) -- read the quote before assuming it is a legitimate "
                f"expansion. Quote: ...{miss[0][1]}...",
            ))
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", nargs="*", default=None)
    args = ap.parse_args()
    total = 0
    for ep_dir in sorted(ROOT.glob("episodes/*/*")):
        if not ep_dir.is_dir():
            continue
        tag = re.search(r"-(ep\d+)-", ep_dir.name + "-")
        label = tag.group(1) if tag else ep_dir.name
        if args.episodes and label not in args.episodes:
            continue
        for sig, msg in check(ep_dir):
            total += 1
            print(f"{label}  {sig}: {msg}")
    print(f"\n{total} agency issue(s)")


if __name__ == "__main__":
    main()
