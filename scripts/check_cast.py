"""Does the frontmatter cast match who is actually in the episode?

WHY THIS EXISTS. CLAUDE.md rule 9, added 2026-09-13. ep39 waited on a person to name a
face because `guest_gallery.py` runs its one-guest bijection on the `guests:` field, and
ep39 lists Iqbal under `hosts:` while its own text says `kenapa kita jemput Iqbal` and
`dah 3-4 kali dijemput`. He is an invited guest. Nothing compared the frontmatter to the
episode's own words, so the tool never tried and the loop stopped at a human.

The `hosts:`/`guests:` fields are written by the rewrite pipeline from the transcript.
That makes them a DERIVED claim about the cast, and rule 3 treats them as metadata that
has to be right. Three signatures, all report-only:

  missing-from-cast  raw.md labels a turn for someone in neither hosts nor guests. The
                     rewrite dropped a name the transcript already had, and every derived
                     file inherits the gap. 2 episodes after the rule-3 extension test
                     below: ep08's 60 turns under `YB Rafizi` and ep02:bakar's
                     `Prof. Barjoyai` against `Prof. Emeritus Dr. Barjoyai Bardai`.
  guest-as-host      someone under `hosts:` whom the episode's own text introduces as
                     invited. This is ep39's defect, and it is the one that silently
                     disables guest_gallery.py.
  introduced-unheard a person the corpus labels in ANOTHER episode, introduced as present
                     here, with no turn of their own. Cross-episode on purpose: it only
                     fires for people the corpus already knows how to name, which is what
                     keeps it quiet. A bare intro-formula scan flags `bersama Trump`.

SANCTIONED LABELS ARE NOT FINDINGS. `Multiple speakers` is the owner's standing
tie-breaker for unresolvable crosstalk, `Speaker ?` is rule 8's per-turn unknown, and
`Audience` is a real group nobody can name. None belongs in a cast list.

WHAT THIS DELIBERATELY DOES NOT DO: change anything. A cast edit goes through
`common.set_frontmatter_list`, because a read-modify-write of these files dropped the
body's H1 from 147 of them once.

  python scripts/check_cast.py
  python scripts/check_cast.py --episodes ep39 ep10
"""
import argparse
import glob
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"^\[([\d:]+)\]\s*([^:\n]{0,40}?):", re.M)
NOT_A_PERSON = ("Speaker", "Multiple", "Audience", "[")
# `YB Rafizi` is ep08's stray label variant, not a second person. Left un-normalised it
# makes `introduced-unheard` fire on all 70 episodes, because every one of them opens
# with `bersama YB Rafizi`. normalize_speaker_labels.py is what actually fixes the label;
# here the honorific is only stripped for comparison.
HONORIFIC = re.compile(r"^(?:YB|Datuk Seri|Datuk|Dato'|Tan Sri|Puan|Tuan|Prof\.?|Dr\.?)\s+", re.I)

# The show's own way of saying someone is here with us, rather than being talked about.
PRESENT = r"(?:bersama(?:-sama)?(?: kita)?|kita ada|kita jemput|jemput|ditemani|saudara|sdr\.?)"
# ... and of saying they were INVITED, which makes them a guest and not a host.
INVITED = r"(?:jemput|dijemput|tetamu|guest)"
HON = r"(?:YB|Datuk(?: Seri)?|Dato'|Tan Sri|Prof\.?|Dr\.?|saudara|sdr\.?)"
OPENING_LINES = 120     # the welcome, where the cast is named
ABSENT = r"(?:tak ada|tiada|tak dapat|tak sempat|tak join|tak hadir)"
AMBIGUOUS = {"ep01", "ep02", "ep03", "ep04", "ep05", "ep06"}


_EPISODES = None
_KNOWN = None


def episodes():
    """Cached, because qa_check.py calls check_dir() once per episode and the `known` set
    below is corpus-wide. Re-reading all 70 raw.md files for each of 70 episodes made a
    single qa_check run take longer than the whole adoption pipeline."""
    global _EPISODES
    if _EPISODES is None:
        _EPISODES = list(_scan())
    return _EPISODES


def _scan():
    for raw in sorted(glob.glob(str(ROOT / "episodes" / "*" / "*" / "raw.md"))):
        d = Path(raw).parent
        iv = d / "interview.md"
        if not iv.exists():
            continue
        text = iv.read_text(encoding="utf-8")
        fm = yaml.safe_load(text.split("---")[1]) if text.startswith("---") else {}
        body = Path(raw).read_text(encoding="utf-8")
        # BOTH SHOWS HAVE AN ep01 THROUGH ep06 and they are different episodes, so a bare
        # tag is ambiguous for six of them. common.raw_for_tag() refuses one outright; the
        # same suffix convention is used here so a report line names one real episode.
        tag = d.name.split("-")[3]
        if tag in AMBIGUOUS:
            tag += ":" + d.parent.name.split("-")[1]
        yield {
            "tag": tag,
            "dir": d,
            "hosts": list(fm.get("hosts") or []),
            "guests": list(fm.get("guests") or []),
            "speakers": {m.group(2).strip() for m in BLOCK.finditer(body)},
            "body": body,
        }


def _known_speakers():
    """Everyone the corpus labels as a speaker anywhere, honorifics stripped. Corpus-wide
    even when --episodes narrows the report, because that set is the whole point."""
    global _KNOWN
    if _KNOWN is None:
        _KNOWN = set()
        for e in episodes():
            _KNOWN |= {HONORIFIC.sub("", s) for s in e["speakers"]
                       if s and not s.startswith(NOT_A_PERSON)}
    return _KNOWN


def check(only=None):
    eps = [e for e in episodes() if not only or e["tag"] in only]
    if not eps:
        return []
    known = _known_speakers()
    issues = []
    for e in eps:
        cast = set(e["hosts"]) | set(e["guests"])
        bare = {HONORIFIC.sub("", c) for c in cast} | {HONORIFIC.sub("", s) for s in e["speakers"]}
        for who in sorted(e["speakers"]):
            if not who or who.startswith(NOT_A_PERSON) or who in cast:
                continue
            # rule 3: the frontmatter carries the FULL name and the body stays verbatim,
            # so ep09's label `Rodziah Ismail` against cast `Rodziah Ismail (Kak Oji)` is
            # the rule working. Same extension test check_agencies.py uses.
            if any(c.startswith(who) or who.startswith(c) for c in cast):
                continue
            issues.append((e["tag"], "missing-from-cast",
                           f"raw.md labels turns for {who!r}, who is in neither hosts "
                           f"{e['hosts']} nor guests {e['guests']}"))
        for who in e["hosts"]:
            # Match on the first word: the label is `Iqbal`, the text says `saudara Iqbal`.
            first = re.escape(who.split()[0])
            if re.search(rf"{INVITED}\s+(?:\w+\s+){{0,2}}?{first}\b", e["body"], re.I):
                quote = re.search(rf".{{0,30}}{INVITED}\s+(?:\w+\s+){{0,2}}?{first}\b.{{0,30}}",
                                  e["body"], re.I).group(0).replace("\n", " ")
                issues.append((e["tag"], "guest-as-host",
                               f"{who!r} is listed under hosts, but the episode says they "
                               f"were invited: ...{quote.strip()}... -- this disables "
                               f"guest_gallery.py's bijection for them"))
        # INTRODUCTIONS HAPPEN AT THE TOP, and the name follows the formula directly.
        # Two filler words of slack, over the whole episode, flagged ep48's `kalau tengok
        # Nik lah kan ... Nik Nazmi` and ep04's `Faiz` -- people being DISCUSSED, which is
        # the opposite of present. ABSENT is the other half: ep35 opens `saudara Farhan
        # tak ada pada hari ini`, which says outright that he is not here.
        head = "\n".join(e["body"].splitlines()[:OPENING_LINES])
        for who in sorted(known - bare):
            # TWO PEOPLE CAN SHARE A GIVEN NAME, and the match below is on the first word
            # only, because the text says `saudara Faiz` where the label says `Faiz Ahmad`.
            # Without this test, ep03's `Faiz (Financial Faiz)` and ep04's `Faiz Ahmad`
            # each flagged the other's episode. Same extension test as above.
            if any(b.startswith(who) or who.startswith(b) for b in bare):
                continue
            first = re.escape(who.split()[0])
            hit = re.search(rf"{PRESENT}\s+(?:{HON}\s+)?{first}\b(.{{0,25}})", head)
            if hit and not re.match(rf"\s*{ABSENT}", hit.group(1)):
                issues.append((e["tag"], "introduced-unheard",
                               f"{who!r} is introduced as present and the corpus labels "
                               f"them in other episodes, but no turn here is theirs"))
    return issues


def check_dir(ep_dir):
    """qa_check.py's signature: one episode directory in, its issue strings out."""
    ep_dir = Path(ep_dir)
    tag = ep_dir.name.split("-")[3]
    if tag in AMBIGUOUS:
        tag += ":" + ep_dir.parent.name.split("-")[1]
    return [(kind, why) for _, kind, why in check({tag})]


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--episodes", nargs="*")
    a = p.parse_args()

    issues = check(set(a.episodes) if a.episodes else None)
    last = None
    for tag, kind, why in issues:
        if tag != last:
            print(f"\n{tag}")
            last = tag
        print(f"   [{kind}] {why}")
    print(f"\n{len(issues)} cast issue(s) in "
          f"{len({t for t, _, _ in issues})} episode(s)")


if __name__ == "__main__":
    main()
