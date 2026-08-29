"""Put every frontmatter list item back on one line, without touching the body.

`common.frontmatter_md` called yaml.dump with no `width`, so it wrapped at 80 characters
with a two-space continuation. That is valid YAML and reads back correctly through
yaml.safe_load -- but every frontmatter reader in this repo uses a regex of the shape
`^topics:\\n((?:- .*\\n)*)`, which stops dead at the first continuation line. So a wrapped
entry truncated the list and hid every entry after it.

It shipped that way on 24 episodes. ep11's twelve topics read as three; a coverage report
built on those regexes reported a 49% mean when the real figure was 78%. The helper now
passes a large width, so new writes cannot wrap; this repairs what is already on disk.

Surgical on purpose: only the matched list block is rewritten, the rest of the file is
copied through unchanged, and the body is asserted identical before anything is written.
That matters because the round-trip through `read_frontmatter_body` + `frontmatter_md`
DELETES a leading "# Interview" heading from the body -- which is how 49 episodes lost
theirs in the first place.

  python scripts/normalize_frontmatter_lists.py
  python scripts/normalize_frontmatter_lists.py --write
"""
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LIST_KEYS = ("topics", "hosts", "guests")


def block_re(key):
    """The key's line plus its items, including wrapped continuation lines."""
    return re.compile(rf"^{key}:(?:[ ]*\[\][ ]*)?\n?(?:[ ]*-[ ].*\n|[ ]{{2,}}\S.*\n)*", re.M)


def render(key, values):
    if not values:
        return f"{key}: []\n"
    out = [f"{key}:\n"]
    for v in values:
        # Dump one item at a time so yaml still applies its own quoting rules -- a value
        # with a leading indicator or a ": " needs them -- but nothing can wrap.
        out.append(yaml.dump([v], allow_unicode=True, default_flow_style=False,
                             width=10 ** 6).rstrip("\n") + "\n")
    return "".join(out)


def main():
    write = "--write" in sys.argv
    touched = 0
    for path in sorted(ROOT.glob("episodes/*/*/*.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        head, fm, body = text.split("---", 2)
        fields = yaml.safe_load(fm) or {}
        new_fm = fm
        for key in LIST_KEYS:
            if key not in fields or not isinstance(fields[key], list):
                continue
            rx = block_re(key)
            if not rx.search(new_fm):
                continue
            new_fm = rx.sub(render(key, fields[key]), new_fm, count=1)
        if new_fm == fm:
            continue
        # Same values, no wrapped lines left, body byte-identical.
        assert yaml.safe_load(new_fm) == fields, path
        rebuilt = head + "---" + new_fm + "---" + body
        assert rebuilt.split("---", 2)[2] == body, path
        touched += 1
        print(f"  {path.parent.name[:46]}/{path.name}")
        if write:
            path.write_text(rebuilt, encoding="utf-8")
    print(f"\n{touched} file(s) " + ("normalised" if write else "would be normalised"))


if __name__ == "__main__":
    main()
