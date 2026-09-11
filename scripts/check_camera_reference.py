"""Refuse a camera reference that is missing someone raw.md says talks. No GPU, no network.

WHY THIS EXISTS. On 2026-09-11 a full 152-minute camera pass on ep33 produced a reference
that looked entirely normal -- 71% coverage, 400 segments, a well-formed RTTM -- and was
wrong for a fifth of the episode:

    raw.md      Rafizi 70.9% of time   Wong Chen 18.3%   Haziq 10.0%   Farhan 0.8%
    reference   Rafizi 93.8%           Wong Chen  0.0%   Haziq  4.7%   Farhan 1.5%

Wong Chen is a GUEST. The face gallery holds the three regulars, so his face matched nobody
and the pass handed his segments to the nearest gallery member. Adopting that reference
would have relabelled a named politician's words -- 172 blocks, 20.1% of the episode -- as
Rafizi, and every other check in the repo would have read the result as fine.

WHY DER DOES NOT CATCH IT, which is the whole point. ep33 scored DER 11.9% against that
reference, the sort of number that passes. JER was 48.1%, against ep52's 16.3%. DER is
dominated by whoever speaks most, and in this corpus that is always Rafizi -- losing a
speaker who holds a fifth of the episode barely moves it. That is the same trap already
recorded for the diarizer: read JER, not DER.

THE CHECK IS NOT A SCORE. It compares the CAST, not the timing. A person raw.md gives a
real share of the words must appear in the reference with a real share of the time. It says
nothing about whether the reference's boundaries are right, so it is a gate before scoring,
never a substitute for it.

WHY IT KEYS ON CHARACTERS AND NOT SECONDS. A block's duration comes from its own stamp and
the next block's, and stamps in this corpus drift -- ep40's clock is 170s early, and ep33's
are non-monotonic enough that retime_blocks.py is required before its split can run. Word
volume needs no clock at all.

  python scripts/check_camera_reference.py            # every reference on disk
  python scripts/check_camera_reference.py ep33
"""
import argparse
import glob
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import common  # noqa: E402

BLOCK = re.compile(r"^\[([\d:]+)\]\s*([^:\n]{1,40}?):\s*(.*)$", re.M)
# A raw speaker below this share of the words is not worth asserting anything about: Farhan
# legitimately holds 0.7% of ep33 and appears in short bursts the camera may never cover.
MIN_RAW_SHARE = 0.05
# How much of their raw share a speaker must retain in the reference. Deliberately loose:
# the camera covers only the seconds it is sure about, so a real speaker can lose most of
# their time to low coverage and still be present. Wong Chen retained 0.0%.
MIN_RETAINED = 0.20
GENERIC = re.compile(r"^(speaker|penutur)\s*[\d?]*$|^multiple speakers$|^audience$", re.I)


def raw_share(tag):
    """{name: share of characters} over raw.md's named blocks. No timestamps involved."""
    text = common.raw_for_tag(tag).read_text(encoding="utf-8")
    chars = Counter()
    for _, who, said in BLOCK.findall(text):
        who = who.strip()
        if GENERIC.match(who):
            continue
        chars[who] += len(said)
    total = sum(chars.values()) or 1
    return {k: v / total for k, v in chars.items()}


def ref_share(path):
    secs = Counter()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        f = line.split()
        if len(f) > 7 and f[0] == "SPEAKER":
            secs[f[7].replace("_", " ")] += float(f[4])
    total = sum(secs.values()) or 1
    return {k: v / total for k, v in secs.items()}, total


def short(name):
    return name.split(" (")[0].strip().lower()


def check(tag, path):
    raw = raw_share(tag)
    ref, covered = ref_share(path)
    ref_by_short = {short(k): v for k, v in ref.items()}
    problems = []
    for name, share in sorted(raw.items(), key=lambda x: -x[1]):
        if share < MIN_RAW_SHARE:
            continue
        got = ref_by_short.get(short(name), 0.0)
        if got < share * MIN_RETAINED:
            problems.append((name, share, got))
    print(f"\n{tag}: reference covers {covered:.0f}s over {len(ref)} speaker(s)")
    for name, share in sorted(raw.items(), key=lambda x: -x[1]):
        got = ref_by_short.get(short(name), 0.0)
        flag = ""
        if share >= MIN_RAW_SHARE and got < share * MIN_RETAINED:
            flag = "  <-- MISSING from the reference"
        print(f"    {name:<20} raw {share:6.1%} of words   reference {got:6.1%} of time{flag}")
    if problems:
        names = ", ".join(p[0] for p in problems)
        print(f"  REFUSE: {names} held a real share of raw.md and the reference does not "
              f"have them. A guest not in the face gallery gets handed to the nearest "
              f"gallery member; rebuild the gallery before using this.")
    return not problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="*")
    a = ap.parse_args()
    if a.tags:
        pairs = [(t, ROOT / "data" / f"camera_ref_{t}.rttm") for t in a.tags]
    else:
        pairs = []
        for p in sorted(glob.glob(str(ROOT / "data" / "camera_ref_*.rttm"))):
            m = re.search(r"camera_ref_(ep\d+)\.rttm$", p)
            if m:
                pairs.append((m.group(1), Path(p)))
    ok = bad = 0
    for tag, path in pairs:
        if not Path(path).exists():
            print(f"\n{tag}: no reference at {path}")
            continue
        if check(tag, path):
            ok += 1
        else:
            bad += 1
    print(f"\n{ok} reference(s) usable, {bad} refused")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
