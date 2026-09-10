"""Normalize every ASR garble of the spoken honorific "YB" back to YB.

The ASR mishears the two spoken letters Y-B as a single word. Earlier passes fixed
"Bobby" (ENGINEERING_LOG 1.20) and "Wabi" (318 occurrences, commit b2a8fe1); this
handles the remaining family. Every occurrence sits in a vocative slot -- the
"baik YB" / "okey YB" / "macam mana YB?" construction at a segment transition, or a
title before a name.

Decisive proofs that these are one token, not separate words:
  ep20 [55:04]  "Baik, YB. kritik lah baby cakap ini sama macam kedai satu Malaysia"
  ep12          "anda dipilih WB Rafizi untuk dibakar"
  ep50          "Maksud Amir pun telah tikam WB Ram[li]"
  ep20          "Tahniah, WB Hassan"
all four writing the same spoken token two ways inside one turn or as a name title.

KEEP is not optional. Several of these spellings are also real words, and a blind
substitution corrupts them: "ubi keledek" is sweet potato, "baby sharks" / "baby
formula" / "baby boomer" are genuine English in the rewrites, and ep24's "rasa macam
baby umur 20 tahun" is a real baby in a longevity argument.

"abi" was excluded entirely until 2026-09-10, when the owner found it in the two MAI
transcripts and named it. MAI hears the honorific this way where the local ASR heard
"wabi" or "baby", and both new occurrences sit in the vocative slot: ep62 raw [27:11]
"Okey, okey. Baik, Abi." -- the "Baik, YB" construction that opens a segment -- and ep61
raw [1:42:44] "Kalau Abi tanya apa yang kita nak perlu buat in the future". It is in
GARBLES now, with ep51's occurrence anchored in KEEP instead: "ada sekali tu, Abi datang,
memang hambat sikit" is a person arriving at a night market, not a vocative.
"""
import re, sys
from pathlib import Path

# "wabi" is back in this list. It was cleared corpus-wide in b2a8fe1 (318 occurrences),
# but ep61's raw.md was regenerated from local ASR AFTER that pass, so the garble returned
# there and nowhere else -- a corpus scan finds all 13 remaining "wabi" inside ep61. The
# lesson generalises past this variant: a text fix applied corpus-wide does not survive a
# later re-transcription of one episode, so re-run this after any raw.md regeneration.
GARBLES = ["baby", "WB", "obi", "ovi", "oibi", "ubi", "waibi", "abby", "abie", "bibi",
           "yobi", "bobby", "wabi", "abi", "fabi"]
# "fabi" added 2026-09-10, owner-caught in ep61's "Okey, baik. Habis Fabi, masa untuk pilih."
# All 5 occurrences in the corpus sit in the vocative slot addressed to Rafizi -- ep61 raw x1
# and ep62 x4, where the raw and all three published files read "Yang ni yang first, Fabi."
# No person in this corpus is called Fabi, so no KEEP entry is needed. MAI hears the two
# spoken letters this way; the local ASR heard "wabi" and "baby" for the same sound.

# UNRESOLVED, deliberately neither fixed nor added to KEEP: ep24 interview.md reads
# "Adik-adik ada cuba proksi obi sendiri ke?" where interview-ms.md has "proksi sendiri"
# and raw.md has neither, so the word entered at the rewrite and nothing in the repo
# settles it. A corpus-wide run will offer it; check the audio before accepting.

# Anchored spans that must survive untouched. Checked before any substitution runs.
KEEP = [
    r"\bubi\s+keledek\b",            # sweet potato, ep07
    r"\bbaby\s+Exxon\b",             # ep10, ExxonMobil alumni joke
    r"\bbaby\s+sharks?\b",           # ep16 interview-en
    r"\bbaby\s+formula\b",           # ep29 interview-en
    r"\bbaby\s+boomer\b",            # ep29 interview-ms
    r"\bbaby\s+umur\b",              # ep24, real baby in a longevity argument
    r"\b20-year-old\s+baby\b",       # ep24 interview-en, same passage
    r"\bbaby\s+kawan\b",             # ep40, genuinely ambiguous -- left for a human
    r"\bfriend's\s+baby\b",         # ep40 interview-en, the SAME sentence in English.
                                     # The Malay above is deliberately left alone, so its
                                     # translation has to be as well.
    r"\bAbi\s+datang\b",             # ep51 x3, a person arriving, not the honorific
    r"\bAbi\s+came\b",               # ep51 interview-en, the SAME sentence in English:
                                     # "there was one time, Abi came, it was really
                                     # rushed". The Malay above is held back, so its
                                     # translation has to be too.
    r"\bdeliver\s+our\s+baby\b",    # ep21 interview-en, a real birth: "my wife was
                                     # still in hospital about to deliver our baby"
]

TOKEN = re.compile(r"\b(" + "|".join(GARBLES) + r")\b", re.I)
KEEPER = re.compile("|".join(KEEP), re.I)
SENTINEL = "\x00KEEP%d\x00"


def fix(text):
    held = []

    def hold(m):
        held.append(m.group(0))
        return SENTINEL % (len(held) - 1)

    masked = KEEPER.sub(hold, text)
    out, n = TOKEN.subn("YB", masked)
    for i, original in enumerate(held):
        out = out.replace(SENTINEL % i, original)
    return out, n


def main():
    write = "--write" in sys.argv
    # An episode tag scopes the run. The owner works one episode at a time, and a
    # corpus-wide --write while a single episode is under review would put changes in
    # files nobody is looking at.
    tags = [a for a in sys.argv[1:] if not a.startswith("--")]
    paths = sorted(Path("episodes").glob("*/*/*.md"))
    if tags:
        paths = [p for p in paths if any(f"-{t}-" in p.parent.name for t in tags)]
        if not paths:
            raise SystemExit(f"no episode files matched {tags}")
        print(f"scoped to {tags}: {len(paths)} files")
    total, touched = 0, 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        new, n = fix(text)
        if not n:
            continue
        total += n
        touched += 1
        print(f"  {n:>4}  {path.parent.name[:52]:<54} {path.name}")
        if write:
            path.write_text(new, encoding="utf-8")
    kept = sum(len(KEEPER.findall(p.read_text(encoding="utf-8"))) for p in paths)
    print(f"\n{total} substitutions across {touched} files; {kept} protected spans left intact")
    print("dry run -- pass --write to apply" if not write else "written")


if __name__ == "__main__":
    main()
