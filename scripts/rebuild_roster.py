"""Rebuild every episode's hosts/guests frontmatter.

Run this after ANY rewrite regeneration. The metadata stage rewrites those fields from
scratch every time and gets them wrong the same ways each time: it files recurring
co-hosts as guests, prefers "Rafizi Ramli" over the short-name convention, welds
diarization placeholders onto real names ("Amin Sahmat (Speaker 4)"), invents people
outright, and once listed the in-house cat as a co-host.

Two sources, and they answer different questions. `raw.md`'s speaker labels come from the
audio, so they decide WHO spoke and whether each person is cast or guest. They do not
decide the NAME FORM, because by convention they use short names -- deriving from them
alone downgraded "Najib Bakar" to "Najib". So the fullest form seen for the same person
wins, with a guard against placeholder text masquerading as a fuller name.

`PRESENT_UNLABELLED` below carries the one thing neither source can supply: people who
are plainly in the episode and never labelled, because a coarse block swallowed their
interjections. Each entry cites the line that justifies it (see ENGINEERING_LOG.md 1.31).

  python scripts/rebuild_roster.py            # diff only
  python scripts/rebuild_roster.py --write    # apply
"""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from common import episode_slug, episode_path, read_frontmatter_body, frontmatter_md

NL = chr(10)
WRITE = "--write" in sys.argv

# Confirmed by the repo owner.
# Wan Afiq and Amir Sahmat stood in for Haziq: Wan Afiq in ep46 and ep50, Amir Sahmat
# in ep46. Both are captioned as hosts in the episodes' own on-screen graphics.
#
# Syed Munawar, Ibrahim Sani and Najib Bakar moderated the 2024 run, when the show was
# a debate: each episode paired a moderator with a "PEMBAKAR MENTERI" who did the
# grilling. The episode descriptions name the pembakar, so the other participant is the
# moderator -- ep01 pembakar Nazri Hamdan so Najib Bakar moderated, ep03 pembakar Faiz
# Azmi so Syed Munawar, ep05 guest Azlan Awang so Ibrahim Sani, ep06 pembakar Eric
# See-To so Syed Munawar. The metadata LLM had filed all four moderators as guests.
HOSTS = ["Rafizi", "Haziq", "Farhan (Pa'an)", "Iqbal", "Wan Afiq", "Amir Sahmat",
         "Syed Munawar", "Ibrahim Sani", "Najib Bakar"]
MERGE = {
    # "Wan Afiq" is right, confirmed by the show's own on-screen name graphic in ep50.
    # Dialogue only ever says "Afiq", so absence from speech proves nothing about a name.
    "Afiq": "Wan Afiq",
    "Farhan": "Farhan (Pa'an)",
    "YB Rafizi": "Rafizi",
    "Rafizi Ramli": "Rafizi",
    "Pa'an": "Farhan (Pa'an)",
    "Farhan Paan": "Farhan (Pa'an)",
    "Dr. Rais Hussein": "Dr. Rais Hussin",
    # the metadata LLM built this from a single ungrounded 'Ruzai' token in ep52
    "Syuk (Ruzai)": "Syuk",
    "Amin Sahmat": "Amir Sahmat",
    "Speaker 2 (Pa'an/Aan)": "Farhan (Pa'an)",
    "Haziq (moderator/interviewer)": "Haziq",
    "Haziq Azfar": "Haziq",
    "Sum Dek Jo": "Sum Dek Joe",
    "Samdek Joe": "Sum Dek Joe",
    "Joe (Samdek Joe)": "Sum Dek Joe",
    "Eric Sito": "Eric See-To",
    "Cincong": "Lee Chean Chung",      # confirmed: MP for Petaling Jaya, ex-MLA Semambu
    "Chean Chung": "Lee Chean Chung",
}
# not people: diarization placeholders, roles, and the cat
DROP = re.compile(
    r"^(speaker\s*[\d?]+|speaker\s*\?|overlapping speaker|multiple speakers|"
    r"quoted clip|audience|"
    r"host|co-host|moderator|interviewer|host \(unnamed presenter\)|"
    r"chopper.*|unnamed.*|unknown.*)$", re.I)

LAB = re.compile(r"^\[(?:\d+:)?\d+:\d+\]\s*([^:\n]{1,40}):", re.M)
NONSPEECH = re.compile(r"^(music|silence|end of|intro|outro|muzik|ketawa|laugh|applause)", re.I)


def canon(n):
    n = re.sub(r"\s+", " ", n).strip()
    return MERGE.get(n, n)


# A cast member can be plainly present in an episode and still have no speaker label:
# coarse blocks absorb short interjections, so his speech ends up inside someone else's
# turn. The hosts field is metadata about who took part, not a transcript label, so it
# records presence on dialogue evidence -- the owner's call, 2026-08-28.
#
# The bar is direct address ("Haziq, aku cabar kau"), or a reference to what the person
# said earlier in THIS episode ("yang Haziq sebut tadi", "macam Haziq kata tadi"). A
# third-person mention of someone in the abstract is not enough.
#
# This cross-checks cleanly against the stand-in episodes: ep46 and ep50 are exactly where
# Wan Afiq appears, and both say outright why -- "Haziq tak ada so kita cover lain lah"
# and "Haziq mana? Haziq pergi mana? Kita tengah cuti."
PRESENT_UNLABELLED = {
    # Haziq: addressed directly, or quoted as having just spoken
    "ep21": ["Haziq"],   # "Haziq selain daripada dia buat kerja percuma jadi moderator"
    "ep27": ["Haziq"],   # "yang Haziq sebut tadi lah"
    "ep31": ["Haziq"],   # "kalau kau Haziq kan, buat video"; "Saya tanya Haziq. Tak cukup kau."
    "ep47": ["Haziq"],   # "You pun sebut Haziq"; "Pertama kali Haziq jadi host kita"
    # Farhan (Pa'an): same bar
    "ep39": ["Farhan (Pa'an)"],   # "apa nama ni Farhan sebut tadi"
    "ep55": ["Farhan (Pa'an)"],   # "Pa'an yang takut dah"
    # ep43 and ep44 removed 2026-08-28: both were re-cut at turn level, so Farhan holds
    # 26 and 16 labelled turns of his own. ep44's identity was confirmed by the repo owner
    # from the video after the voiceprint returned UNRESOLVABLE on 7-second turns.
    #
    # TEN MORE removed later the same day, each because the person now holds real turns:
    #   ep24 (78), ep25 (38), ep29 (52), ep42 (28), ep52 (102), ep58 (50) for Haziq
    #   ep23 (20), ep46 (19), ep60 (1) for Farhan, and ep36 for both (1 and 5)
    # ep58 is the clearest case: 0 -> 50 turns once clustering.threshold=0.55 broke a
    # collapse that no speaker-count hint could (ENGINEERING_LOG 1.36), and ep36, ep42 and
    # ep60 came from reading the video frames rather than from any acoustic pass (1.35).
    #
    # SIX REMAIN, and they are the honest remainder of this audit: Haziq in ep21, ep27,
    # ep31 and ep47, Farhan in ep39 and ep55. Each is present on dialogue evidence and
    # still has no label, because their speech sits inside a block the diarizer would not
    # split. ep47 is the one where the video already proves it: 11 of 17 sampled seconds
    # inside its two 24-minute "Rafizi" blocks are Haziq.
    # both
    # ep45 removed 2026-08-28: Haziq now holds 55 labelled turns of his own after
    # scripts/reattribute_blocks.py re-cut the collapsed blocks, so he no longer needs
    # a manual override. The justifying quote was "Itu bukan sebab dia malas, Haziq.
    # Kau cara cakap tu". Entries here should be deleted, not kept, as each episode's
    # blocks get re-cut -- an override that outlives its cause hides whether the fix worked.
}
# Deliberately NOT added, and why:
#   ep40  "boleh menggantikan Haziq sebagai moderator" reads as replacing an absent Haziq
#   ep41  "kepada Haziq lah" is Rafizi listing people in the abstract, not addressing him
#   ep25/ep35 for Farhan: "Farhan tidak ada untuk menjawab" and "Farhan tak ada pada hari
#         ini. Raya awal... isteri dia meraikan" -- explicitly absent
#   ep46/ep50 for Haziq: explicitly absent, which is why the stand-ins are there
#   kep06, ep14 for Farhan: third-person narrative only, presence not established
#   ep18 for Farhan: "soalan daripada Saudara Farhan, producer kesayangan kita" is a
#         question he sent in, read out by someone else -- not direct address, and it
#         predates his first speaker label (ep20) by two weeks. He joined as producer
#         behind the camera and only starts appearing on-mic from ep20, which is why
#         ep01-ep17 have no Farhan at all: he was not on the show yet.

man = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
changes, unchanged = [], 0
for ep in man:
    slug, rel = episode_slug(ep), episode_path(ep)
    d = ROOT / "episodes" / rel
    _, body = read_frontmatter_body(d / "raw.md")

    # order of first appearance, so the opener leads
    seen = []
    for m in LAB.finditer(body):
        n = canon(m.group(1))
        if NONSPEECH.match(n) or DROP.match(n) or n.startswith("["):
            continue
        if n not in seen:
            seen.append(n)
    # raw.md decides WHO spoke and whether they are cast or guest, because its
    # labels come from the audio. It does not decide the NAME FORM: by convention
    # raw.md uses short names, so regenerating from it alone downgraded
    # "Najib Bakar" to "Najib" and "Prof. Emeritus Dr. Barjoyai Bardai" to
    # "Prof. Barjoyai". Prefer the fullest form seen for the same person.
    fm_prev, _ = read_frontmatter_body(d / "interview.md")
    known = [canon(x) for x in (fm_prev.get("hosts") or []) + (fm_prev.get("guests") or []) if x]

    PLACEHOLDER = re.compile(r"\((?:speaker|penutur)\s*[\d?]+\)|speaker\s*[\d?]+", re.I)

    def fullest(name):
        toks = set(name.lower().replace(".", "").split())
        best = name
        for cand in known:
            # a longer form is only fuller if the extra words are real. The metadata LLM
            # welds diarization placeholders onto names ("Amin Sahmat (Speaker 4)") and
            # this used to prefer them purely for being longer strings.
            if PLACEHOLDER.search(cand):
                continue
            ct = set(cand.lower().replace(".", "").split())
            # same person if one name's words are contained in the other's
            if toks and (toks <= ct or ct <= toks) and len(cand) > len(best):
                best = cand
        return best

    seen = [fullest(n) for n in seen]
    seen = list(dict.fromkeys(seen))
    # order hosts by the roster, not by who happens to open the episode
    hosts = [n for n in seen if canon(n) in HOSTS or n in HOSTS]
    tag_match = re.search(r"-(ep\d+)-", rel.name if hasattr(rel, "name") else str(rel))
    for extra in PRESENT_UNLABELLED.get(tag_match.group(1) if tag_match else "", []):
        if extra not in hosts:
            hosts.append(extra)
    hosts = sorted(set(hosts),
                   key=lambda n: HOSTS.index(canon(n)) if canon(n) in HOSTS else 99)
    guests = [n for n in seen if n not in hosts]

    old_h = fm_prev.get("hosts") or []
    old_g = fm_prev.get("guests") or []
    if old_h == hosts and old_g == guests:
        unchanged += 1
        continue
    changes.append((slug, old_h, old_g, hosts, guests))

    if WRITE:
        for name in ["interview.md", "interview-en.md", "interview-ms.md"]:
            p = d / name
            fm, b = read_frontmatter_body(p)
            fm["hosts"], fm["guests"] = hosts, guests
            heading = "# " + ("Interview" if name == "interview.md" else "Interview")
            first = p.read_text(encoding="utf-8").split("---", 2)[2].lstrip(NL).split(NL, 1)[0]
            p.write_text(frontmatter_md(fm, first + NL * 2 + b), encoding="utf-8")

print(f"episodes changed: {len(changes)}   already correct: {unchanged}" + NL)
for slug, oh, og, nh, ng in changes:
    print(f"  {slug[:52]}")
    if oh != nh:
        print(f"     hosts   {oh}")
        print(f"          ->  {nh}")
    if og != ng:
        print(f"     guests  {og}")
        print(f"          ->  {ng}")
print(NL + ("WROTE the changes" if WRITE else "diff only, nothing written (pass --write to apply)"))
