"""Did the rewrite stage actually finish, or did it quietly stop early?

A clean exit code proves nothing here. Measured silent truncations on this corpus:
Haiku dropped ~50% of a Malay translation, Sailor2-8B 32%, and a Gemini key produced
73-82% completeness with names fragmented -- every one of them exiting 0 (ENGINEERING_LOG,
and the model-pilot notes). So a regeneration has to be measured, not trusted.

The thresholds come from the 67-episode distribution rather than from taste. The
translation ratios are the sharp instrument, because they are tight:

    interview-en / interview   median 1.07   p10 1.04   min 0.98
    interview-ms / interview   median 0.98   p10 0.95   min 0.88
    interview    / raw.md      median 0.96   p10 0.73   min 0.48

interview/raw is too broad to threshold: the 2024-era episodes legitimately sit at
0.48-0.67 because that rewrite pass condensed heavily. So instead of an absolute floor,
this compares interview.md against ITS OWN previous committed size -- a regeneration over
the same raw.md should not shrink. That catches a partial run on any episode, including
the ones whose absolute ratio was always low.

Exit code is 1 if any episode fails, so it can gate a retry loop.

Usage:  python scripts/check_rewrite_complete.py ep21 ep26
        python scripts/check_rewrite_complete.py --all
"""
import glob
import os
import re
import subprocess
import sys

import yaml

MIN_EN_RATIO = 0.90        # observed min 0.98; 0.90 leaves headroom without hiding a drop
MIN_MS_RATIO = 0.80        # observed min 0.88
MIN_VS_PREVIOUS = 0.85     # a regeneration should not shrink the file
FILES = ["interview.md", "interview-en.md", "interview-ms.md"]


def body_words(text):
    return len(text.split("---", 2)[-1].split())


def previous_size(path):
    """Word count of the last committed version, or None if it is new."""
    rel = path.replace("\\", "/")
    out = subprocess.run(["git", "show", f"HEAD:{rel}"],
                         capture_output=True, text=True, encoding="utf-8")
    return body_words(out.stdout) if out.returncode == 0 and out.stdout else None


def check(ep_dir):
    problems = []
    sizes = {}
    for name in FILES + ["raw.md"]:
        p = os.path.join(ep_dir, name)
        if not os.path.exists(p):
            problems.append(f"MISSING {name}")
            continue
        text = open(p, encoding="utf-8").read()
        sizes[name] = body_words(text)
        if name != "raw.md":
            if not text.startswith("---"):
                problems.append(f"{name}: no YAML frontmatter")
            else:
                try:
                    fm = yaml.safe_load(text.split("---", 2)[1])
                    if not (fm or {}).get("hosts"):
                        problems.append(f"{name}: frontmatter has no hosts")
                except Exception as exc:
                    problems.append(f"{name}: YAML broken -- {str(exc)[:60]}")
    if len(sizes) < 4:
        return problems, sizes

    iv = sizes["interview.md"] or 1
    en_ratio, ms_ratio = sizes["interview-en.md"] / iv, sizes["interview-ms.md"] / iv
    if en_ratio < MIN_EN_RATIO:
        problems.append(f"interview-en.md only {en_ratio:.2f} of interview.md "
                        f"(floor {MIN_EN_RATIO}) -- translation stopped early")
    if ms_ratio < MIN_MS_RATIO:
        problems.append(f"interview-ms.md only {ms_ratio:.2f} of interview.md "
                        f"(floor {MIN_MS_RATIO}) -- translation stopped early")
    prev = previous_size(os.path.join(ep_dir, "interview.md"))
    if prev and iv / prev < MIN_VS_PREVIOUS:
        problems.append(f"interview.md shrank to {iv/prev:.2f} of the committed version "
                        f"({iv} vs {prev} words) -- rewrite stopped early")

    # a rewrite that lost every speaker label is worse than no rewrite
    text = open(os.path.join(ep_dir, "interview.md"), encoding="utf-8").read()
    if not re.search(r"^\*\*[^*]{2,40}:?\*\*", text, re.M):
        problems.append("interview.md has no bold speaker labels at all")
    return problems, sizes


def main():
    tags = [a for a in sys.argv[1:] if a.startswith("ep")]
    dirs = sorted(glob.glob("episodes/*/*"))
    if tags:
        dirs = [d for d in dirs
                if any(re.search(r"-" + t + r"-", os.path.basename(d)) for t in tags)
                and "bakar" not in d]
    failed = 0
    for d in dirs:
        if not os.path.exists(os.path.join(d, "interview.md")):
            continue
        tag = re.search(r"-(ep\d+)-", os.path.basename(d))
        tag = tag.group(1) if tag else os.path.basename(d)[:12]
        problems, sizes = check(d)
        if problems:
            failed += 1
            print(f"FAIL {tag}")
            for p in problems:
                print(f"       {p}")
        else:
            iv = sizes["interview.md"]
            print(f"ok   {tag}  raw={sizes['raw.md']}  interview={iv}  "
                  f"en={sizes['interview-en.md']/iv:.2f}  ms={sizes['interview-ms.md']/iv:.2f}")
    print(f"\n{failed} episode(s) failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
