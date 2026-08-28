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
baby umur 20 tahun" is a real baby in a longevity argument. "abi" is excluded
entirely -- its single occurrence (ep51 "Abi datang memang hambat sikit") is
narrative, not vocative, so it is not safe to touch.
"""
import re, sys
from pathlib import Path

GARBLES = ["baby", "WB", "obi", "ovi", "oibi", "ubi", "waibi", "abby", "abie", "bibi", "yobi", "bobby"]

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
    total, touched = 0, 0
    for path in sorted(Path("episodes").glob("*/*/*.md")):
        text = path.read_text(encoding="utf-8")
        new, n = fix(text)
        if not n:
            continue
        total += n
        touched += 1
        print(f"  {n:>4}  {path.parent.name[:52]:<54} {path.name}")
        if write:
            path.write_text(new, encoding="utf-8")
    kept = sum(len(KEEPER.findall(p.read_text(encoding="utf-8")))
               for p in Path("episodes").glob("*/*/*.md"))
    print(f"\n{total} substitutions across {touched} files; {kept} protected spans left intact")
    print("dry run -- pass --write to apply" if not write else "written")


if __name__ == "__main__":
    main()
