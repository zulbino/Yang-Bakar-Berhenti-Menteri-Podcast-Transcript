"""Assert an episode's spoken words are unchanged against a git ref.

Step 3 of ATTRIBUTION_PASS.md. Run it after every write in an attribution pass.

An attribution pass is allowed to move boundaries and change labels. It is never allowed
to change what was said. apply_split_map.py asserts this per touched block; this asserts it
for the whole file against git, which also catches anything a second tool did in between.
"""
import difflib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sense_speakers import BLOCK, episode_dir

WORD = re.compile(r"[\w']+")


def body(text):
    parts = text.split("---", 2)
    return parts[2] if len(parts) > 2 else text


def spoken(text):
    return WORD.findall(" ".join(m.group(3) for m in BLOCK.finditer(body(text))))


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "ep61"
    ref = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
    folder = episode_dir(tag)
    bad = 0
    for name in ("raw.md", "interview.md", "interview-ms.md", "interview-en.md"):
        f = folder / name
        if not f.exists():
            continue
        rel = f.relative_to(Path.cwd()).as_posix()
        old = subprocess.run(["git", "show", f"{ref}:{rel}"], capture_output=True,
                             text=True, encoding="utf-8").stdout
        if not old:
            print(f"  {name:18} not at {ref}, skipped")
            continue
        new = f.read_text(encoding="utf-8")
        a, b = spoken(old), spoken(new)
        if name != "raw.md":
            a, b = WORD.findall(body(old)), WORD.findall(body(new))
        same = a == b
        print(f"  {name:18} {ref} {len(a):>6}w -> now {len(b):>6}w   "
              f"{'IDENTICAL' if same else 'CHANGED'}")
        if not same:
            bad += 1
            for t, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b).get_opcodes():
                if t != "equal":
                    print(f"      {t:8} {a[i1:i2][:10]} -> {b[j1:j2][:10]}")
    raise SystemExit(bad)


if __name__ == "__main__":
    main()
