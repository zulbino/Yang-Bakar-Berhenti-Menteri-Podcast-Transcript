"""Check that every Dato'/Datuk and Seri/Sri honorific is written the way the person's own
official page writes it, in raw.md, the interview files and the forum transcript.

WHY. The corpus wrote `Datuk Seri Anwar` 1,210 times while the PMO and Parliament write
`Dato' Seri Anwar`, and `Datuk Seri Najib` 189 times against Parliament's `Dato' Sri`. Both
spellings are said the same way, so the video cannot decide them; the person's own official
page does (data/honorific_roster.json, each entry with its source).

THE GRADE IS NEVER CHANGED. Whether the speaker said Tan Sri, Datuk Seri or Datuk is audible,
and raw.md and the interview files stay true to what was said (owner, 2026-10-04): the YouTube
caption track agrees with raw.md's grade in 2,311 of 2,315 located mentions, so a title that
differs from the person's real one (Hadi Awang is a Tan Sri, Rafizi says `Datuk Seri Hadi`) is the
speaker's own and stays. Where the roster's `held` grade differs from the written one, this
prints it as INFO, for the owner to read.

Only the text after the navigation block (or `# Raw Transcript`) is read, so a YouTube title in
the front matter is never touched.

  python scripts/check_honorifics.py            # report; exit 1 if a spelling is not canonical
  python scripts/check_honorifics.py --write    # rewrite spelling only
"""
import argparse
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

TITLE = r"(?P<title>(?:Datuk|Dato['’]?)(?:\s+(?:Seri|Sri)(?P<utama>\s+Utama)?)?)"
MID = r"(?P<mid>\s+(?:(?:Dr|Haji|Hj)\.?\s+)*)"
HELD_NAMES = {"DSERI": "Datuk Seri / Dato' Seri", "DATUK": "Datuk / Dato'", "TANSRI": "Tan Sri", "TUN": "Tun"}


def files():
    out = []
    for pat in ("raw.md", "interview.md", "interview-en.md", "interview-ms.md", "transcript.md"):
        out += sorted(ROOT.glob(f"episodes/*/*/{pat}"))
    return out


def split_body(text):
    for marker in ("<!-- /nav -->", "# Raw Transcript"):
        i = text.find(marker)
        if i != -1:
            return text[:i + len(marker)], text[i + len(marker):]
    m = re.match(r"---\n.*?\n---\n", text, re.S)
    return (text[:m.end()], text[m.end():]) if m else ("", text)


def compile_entries():
    entries = json.loads((ROOT / "data" / "honorific_roster.json").read_text(encoding="utf-8"))["entries"]
    return [(e, re.compile(rf"(?<![\w'’]){TITLE}{MID}(?P<name>{e['match']})(?![\w'’])")) for e in entries]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    entries = compile_entries()
    changes, info, written = Counter(), Counter(), 0
    for path in files():
        text = path.read_text(encoding="utf-8")
        head, body = split_body(text)
        new = body
        for entry, rx in entries:
            def fix(m, entry=entry, path=path):
                grade = "DSERI" if re.search(r"\b(?:Seri|Sri)\b", m.group("title")) else "DATUK"
                want = entry["forms"].get(grade)
                held = entry["held"]
                if held != grade:
                    info[(entry["name"], grade, held)] += 1
                if not want:
                    return m.group(0)
                canon = want + (" Utama" if m.group("utama") else "")
                if canon != m.group("title"):
                    changes[(entry["name"], m.group("title"), canon, path.parent.parent.name)] += 1
                    return canon + m.group("mid") + m.group("name")
                return m.group(0)
            new = rx.sub(fix, new)
        if new != body and a.write:
            io.open(path, "w", encoding="utf-8", newline="").write(head + new)
            written += 1
    per = Counter()
    for (name, found, canon, series), n in changes.items():
        per[(name, found, canon)] += n
    for (name, found, canon), n in sorted(per.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"{n:5}  {name:<24} {found!r} -> {canon!r}")
    print(f"\n{sum(per.values())} non-canonical spelling(s) across {len({k[3] for k in changes})} series;"
          + (f" {written} file(s) written" if a.write else " nothing written (dry run)"))
    held = Counter()
    for (name, grade, h), n in info.items():
        held[(name, grade, h)] += n
    if held:
        print("\nINFO, not changed: the written grade is not the grade the person held in 2026-10 "
              "(the speaker's own words stay):")
        for (name, grade, h), n in sorted(held.items(), key=lambda kv: -kv[1]):
            print(f"{n:5}  {name:<24} written {HELD_NAMES.get(grade, grade)}, holds {HELD_NAMES.get(h, h)}")
    bad = Counter()
    for path in files():
        body = split_body(path.read_text(encoding="utf-8"))[1]
        for m in re.finditer(r"\bDatuk Sri\b[^\n]{0,40}", body):
            bad[(path.parent.parent.name, " ".join(m.group(0).split()[:5]))] += 1
    if bad:
        print("\nNO SUCH TITLE, not changed (a person is needed to pick Datuk Seri or Dato' Sri):")
        for (series, ctx), n in sorted(bad.items(), key=lambda kv: -kv[1]):
            print(f"{n:5}  {series}  {ctx!r}")
    return 0 if (not per and not bad) or a.write else 1


if __name__ == "__main__":
    sys.exit(main())
