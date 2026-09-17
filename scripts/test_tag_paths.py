"""Every artifact filename built from an episode tag must pass through artifact_tag().

WHY THIS IS A TEST AND NOT A CONVENTION. Six tags name two different episodes, because
both shows have an ep01 through ep06, so the rest of the repo disambiguates them as
`ep05:bakar`. A colon in an NTFS path does not name a file. It names an ALTERNATE DATA
STREAM. Measured 2026-09-16: writing `data/camera_ref_ep05:bakar.rttm` put the bytes in
a hidden stream and left a 0-byte `camera_ref_ep05` in the listing, and exists()
returned True throughout. Nothing reported a problem, and git would have committed the
empty file.

The fix was `common.artifact_tag()`, applied at 30 sites on 2026-09-17. A fix applied by
hand at 30 sites is a fix the 31st site will miss, which is what CLAUDE.md means by a
rule with no mechanism. This test is that mechanism.

  python scripts/test_tag_paths.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import common  # noqa: E402

# A tag placeholder, then a filename or a path separator, with no space between them.
# The space rule is what keeps a sentence out of this: `f"{tag} {vid}: ... raw.md"` is a
# message, and `f"_{tag}_align.json"` is a filename.
EXT = r"rttm|uem|json|md|txt|out|wav|png|rrtm"
PLACEHOLDER = r"\{(?:a\.)?(?:tag|t|ep)\}"
UNSAFE = re.compile(PLACEHOLDER + r"[^\s\"'{}]*(?:\.(?:" + EXT + r")|/)")

# These build a GLOB against episodes/, where the show suffix is partitioned off first.
# A glob is not a filename, so artifact_tag would be wrong here.
ALLOWED = ("episodes/*/*-{tag}-*/", "episodes/*/*/{tag}", "_camera_tracks_{vid}")


def offenders():
    out = []
    for path in sorted((ROOT / "scripts").glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):        # a comment quoting the old shape
                continue
            if "artifact_tag" in line or not UNSAFE.search(line):
                continue
            if any(a in line for a in ALLOWED):
                continue
            out.append((path.name, n, line.strip()))
    return out


def main():
    problems = []
    for tag in ("ep05", "ep05:bakar", "ep05:berhenti", "ep63"):
        safe = common.artifact_tag(tag)
        if ":" in safe:
            problems.append(f"artifact_tag({tag!r}) kept the colon: {safe!r}")
        if common.tag_from_artifact(safe) != tag:
            problems.append(f"{tag!r} does not round-trip: {safe!r} -> "
                            f"{common.tag_from_artifact(safe)!r}")

    for name, n, text in offenders():
        problems.append(f"{name}:{n} builds a filename from a raw tag -- wrap it in "
                        f"common.artifact_tag(): {text[:90]}")

    for p in problems:
        print(f"   [tag-path] {p}")
    print(f"\n{len(problems)} unsafe tag path(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
