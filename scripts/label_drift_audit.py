"""Corpus-wide audit of speaker labels that differ between raw.md and interview*.md.

The requested wrong-name audit. raw.md is ground truth (it comes from audio);
interview*.md is a downstream rewrite, so a name appearing only downstream was
introduced there.

A first version flagged 63/67 episodes, which is useless. Two causes, both fixed
here:
  - Format: some raw.md files use "[10:00] [Faiz Ahmad] text" with NO colon after
    the bracketed name, so a colon-requiring regex matched nothing and made every
    downstream label look invented (this is what happened on ep04).
  - It conflated legitimate variants with fabrications. "Rafizi" -> "Rafizi Ramli"
    is the rewrite choosing a fuller form, not an error.

So labels are bucketed:
  VARIANT   - token subset either way ("Rafizi" / "Rafizi Ramli"). Ignored.
  SPELLING  - close but not identical ("Eric See-To" / "Eric Sito",
              "Iswardy Morni" / "Iswardi Murni"). Real defects, low severity,
              and exactly what the planned proper-noun pass is for.
  INVENTED  - no relation to any raw.md speaker ("Bobby", "Abie", "Zak").
              Highest severity: a confident name attached to a real person.
  GENERIC   - "Host", "Interviewer" etc. replacing a named speaker. A different
              known issue (unresolved diarization), reported for completeness.

Nothing is edited -- this only reports.
"""
import difflib
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "episodes"
# Handles "[10:00] Name:", "[10:00] [Name]:" and "[10:00] [Name]" (no colon).
# Parentheses are part of the name class on purpose. Without them this pattern could not
# see "Farhan (Pa'an)", the show's regular co-host, in any of the 35 episodes whose raw.md
# labels him that way -- so he counted as a cast member with no speaker label, and every
# consumer of raw_names (this audit's classifier, check_published's generic-label count)
# was working from a roster missing one of the three people usually in the room.
RAW_LABEL = re.compile(
    r"^\[[\d:]+\]\s*(?:\[([^\]]{1,30})\]|([A-Za-z][\w '.()-]{1,28})\s*:)", re.M)
MD_LABEL = re.compile(r"\*\*([A-Za-z][\w '.-]{1,28})\s*:?\*\*")
# Includes the Malay equivalents the rewrite emits when translating a generic
# label -- Pewawancara/Penemuduga/Penemubual all mean "interviewer", Ko-hos is
# "co-host", Klip petikan is the "Quoted clip" label used for read-aloud audio.
# Without these, translated placeholders show up as invented person-names.
GENERIC = re.compile(r"^(Host|Hos|Host lain|Other host|Co-host|Ko-hos|Speaker|Speaker \d+|"
                     r"Interviewer|Pewawancara|Penemuduga|Penemubual|Pengacara|Penyampai|"
                     r"Moderator|Quoted clip|Klip petikan|Audience|Hadirin|Guest|Tetamu|"
                     r"Questioner|Penyoal|Professor|Prof|Unidentified Speaker|"
                     r"Penutur tidak dikenali)$", re.I)
MIN_TURNS = 3
SIMILAR = 0.72


def norm(s):
    return re.sub(r"[^a-z]", "", s.lower())


def tokens(s):
    return {t for t in re.split(r"[^A-Za-z]+", s.lower()) if len(t) > 2}


def classify(label, raw_names):
    lt = tokens(label)
    for rn in raw_names:
        rt = tokens(rn)
        if not lt or not rt:
            continue
        if lt <= rt or rt <= lt:
            return "VARIANT", rn
    best, score = None, 0.0
    for rn in raw_names:
        s = difflib.SequenceMatcher(None, norm(label), norm(rn)).ratio()
        if s > score:
            best, score = rn, s
    if score >= SIMILAR:
        return "SPELLING", f"{best} ({score:.2f})"
    return "INVENTED", None


def main():
    """Print the audit. Kept behind a guard so importing GENERIC/classify from here
    does not trigger a full 67-episode scan -- qa_check.py now imports this module via
    check_published.py, and an import with side effects made it print this whole report
    in the middle of the QA summary."""
    buckets = {"INVENTED": [], "SPELLING": [], "GENERIC": []}
    no_labels = []
    for ep in sorted(ROOT.glob("*/*")):
        if not ep.is_dir() or not (ep / "raw.md").exists():
            continue
        found = RAW_LABEL.findall((ep / "raw.md").read_text(encoding="utf-8"))
        raw_labels = Counter(a or b for a, b in found)
        raw_named = {n for n in raw_labels if not GENERIC.match(n)}
        if not raw_named:
            no_labels.append(ep.name)
            continue

        seen = Counter()
        for name in ("interview.md", "interview-en.md", "interview-ms.md"):
            p = ep / name
            if p.exists():
                seen.update(MD_LABEL.findall(p.read_text(encoding="utf-8")))

        for label, n in seen.items():
            if n < MIN_TURNS:
                continue
            if GENERIC.match(label):
                buckets["GENERIC"].append((ep.name, label, n, ""))
                continue
            kind, ref = classify(label, raw_named)
            if kind != "VARIANT":
                buckets[kind].append((ep.name, label, n, ref or ""))

    for kind in ("INVENTED", "SPELLING"):
        rows = buckets[kind]
        eps = sorted({r[0] for r in rows})
        print(f"\n{'=' * 70}\n{kind}: {len(rows)} label(s) across {len(eps)} episode(s)\n")
        for ep in eps:
            for _, label, n, ref in sorted((r for r in rows if r[0] == ep), key=lambda r: -r[2]):
                suffix = f"  ~ raw.md '{ref}'" if ref else ""
                print(f"  {ep[:52]:52} {label:24} x{n:<4}{suffix}")

    print(f"\n{'=' * 70}\nGENERIC placeholders replacing named speakers: "
          f"{len({r[0] for r in buckets['GENERIC']})} episode(s)")
    top = Counter()
    for ep, label, n, _ in buckets["GENERIC"]:
        top[label] += n
    print(f"  {dict(top.most_common(8))}")
    if no_labels:
        print(f"\nraw.md with no parseable speaker labels ({len(no_labels)}): "
              f"{', '.join(e[:34] for e in no_labels[:6])}")


if __name__ == "__main__":
    main()
