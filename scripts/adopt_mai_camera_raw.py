"""Adopt the MAI+camera raw for one episode, running the whole standard in order.

WHY THIS EXISTS. Every step here was already a rule, and ep61 still shipped without three
of them, because the sequence lived in a person's head. The owner's instruction on
2026-09-10: *"dont skip or forget things we decided in ep62, we want to carry the same high
standard for all other episodes as well"*. So the sequence is one command, it prints every
number it claims, and it refuses rather than half-applies.

ORDER MATTERS, and each step is here for a measured reason:

  1. `mai_camera_raw.py --current <the raw the decisions were recorded against>` -- the
     --current is not optional after a swap: reading its own output back feeds the fallback
     labels and the gold splice their own answer.
  2. `check_owner_decisions.py` on the CANDIDATE, before anything is written. Exit 1 stops
     the run. This is the gate that keeps an owner decision from being overwritten.
  3. `strip_filler_turns.py` -- grunt-only turns go. Must precede the fold: before it, a
     fragment's neighbour is a grunt, and the fold's "same speaker either side" test cannot
     fire.
  4. `fold_hanging_fragments.py` -- a mid-sentence fragment the camera cannot see at all
     falls to the speaker around it. Camera-attested fragments are never touched.
  5. `merge_same_speaker.py` -- adjacent same-name blocks join. The fold creates new
     adjacency, so it runs after.
  6. `fix_proper_nouns.py` and `fix_yb_honorific.py` -- corpus-wide reviewed maps. MAI
     spells the honorific `Abi` where the local ASR wrote `wabi`, so a fresh MAI raw always
     needs the second one.
  7. Verification, printed: decisions, gold, adjacency, grunts, garbles, hanging fragments,
     and the camera score.

  python scripts/adopt_mai_camera_raw.py ep60             # dry run: build, gate, report
  python scripts/adopt_mai_camera_raw.py ep60 --write
"""
import argparse
import glob
import io
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
BLOCK = re.compile(r"^\[([\d:]+)\]\s*([^:\n]{0,40}?):\s*(.*)$", re.M)
GARBLE = re.compile(r"\b(baby|WB|obi|ovi|oibi|ubi|waibi|abby|abie|bibi|yobi|bobby|wabi|abi)\b", re.I)
NAME_GARBLE = re.compile(r"\bPaan\b|Pak An(?![A-Za-z])")
FILLERS = {"hm", "hmm", "hmmm", "hmmmm", "mm", "mmm", "mmmm", "mhm", "mhmm", "mmhmm", "mmhm",
           "ha", "haa", "haaa", "haah", "hah", "haha", "hahaha", "ah", "aah", "ahh", "aha",
           "ahaa", "oh", "ooh", "ohh", "uh", "uhh", "uhm", "um", "umm", "erm", "err", "er",
           "eh", "ehh", "huh", "hu", "heem"}


def run(cmd, quiet=False):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if not quiet:
        for line in (p.stdout or "").strip().splitlines():
            print("   " + line)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def report(tag, path, reference):
    text = io.open(path, encoding="utf-8").read()
    blocks = BLOCK.findall(text)
    same = Counter(y[1] for x, y in zip(blocks, blocks[1:]) if x[1] == y[1])
    grunts = sum(1 for _, _, t in blocks
                 if t and all(w.lower().replace("-", "") in FILLERS
                              for w in re.findall(r"[0-9A-Za-z'-]+", t)))
    hanging = [x[0] for x, y in zip(blocks, blocks[1:])
               if x[1] != y[1] and x[2] and y[2] and x[2].rstrip()[-1] not in '.?!:"'
               and y[2].split()[0][:1].islower()]
    print(f"  blocks {len(blocks)} | adjacent same-speaker {sum(same.values())} "
          f"{dict(same) if same else ''} | grunt-only turns {grunts} | "
          f"YB garbles {len(GARBLE.findall(text))} | Paan/Pak An {len(NAME_GARBLE.findall(text))} | "
          f"blank runs {len(re.findall(chr(10) + '{3,}', text))} | hanging fragments {len(hanging)}")
    if reference.exists():
        _, out = run([PY, "scripts/score_attribution.py", str(reference), "--episode", tag,
                      "--blocks", f"this={path}"], quiet=True)
        keep = [l.strip() for l in out.splitlines()
                if l.strip().startswith("this") or "hold more than one" in l
                or "sit under the wrong name" in l]
        for line in keep[:4]:
            print("   " + line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--current", help="the raw.md the owner decisions were recorded against; "
                                      "defaults to the episode's committed raw.md")
    a = ap.parse_args()

    hits = glob.glob(str(ROOT / f"episodes/*/*-{a.tag}-*/raw.md"))
    if len(hits) != 1:
        sys.exit(f"{len(hits)} episodes match {a.tag}")
    raw = Path(hits[0])
    rel = raw.relative_to(ROOT).as_posix()
    reference = ROOT / "data" / f"camera_ref_{a.tag}.rttm"
    if not reference.exists():
        sys.exit(f"no camera reference at {reference} -- run nightly_recut.py {a.tag} first")

    # The decisions were recorded against the COMMITTED file, which is what --current wants.
    current = Path(a.current) if a.current else ROOT / "data" / f"_old_{a.tag}_raw.md"
    if not a.current:
        code, out = run(["git", "show", f"HEAD:{rel}"], quiet=True)
        if code:
            sys.exit(f"cannot read the committed raw.md: {out.strip()[:200]}")
        io.open(current, "w", encoding="utf-8", newline="\n").write(out)

    candidate = ROOT / "data" / f"_{a.tag}_candidate_raw.md"
    print(f"[1/7] build from MAI words + the camera, fallback and gold from {current.name}")
    code, _ = run([PY, "scripts/mai_camera_raw.py", a.tag, "--current", str(current),
                   "--out", str(candidate)])
    if code:
        sys.exit("build failed")

    print("[2/7] gate: every recorded owner decision survives the candidate")
    code, _ = run([PY, "scripts/check_owner_decisions.py", a.tag, str(candidate),
                   "--current", str(current)])
    if code:
        sys.exit("REFUSING: the gate found a decision the candidate does not keep")

    if not a.write:
        print("\nbefore, as shipped:")
        report(a.tag, raw, reference)
        print("candidate:")
        report(a.tag, candidate, reference)
        print("\n-- dry run, pass --write to adopt it and run the standard")
        return

    raw.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
    print("[3/7] drop turns that are only a vocalisation")
    run([PY, "scripts/strip_filler_turns.py", str(raw), "--write"])
    print("[4/7] fold hanging fragments the camera cannot see")
    run([PY, "scripts/fold_hanging_fragments.py", a.tag, "--write"])
    print("[5/7] join adjacent same-speaker blocks")
    run([PY, "scripts/merge_same_speaker.py", f"--episode={a.tag}", "--raw-only", "--write"])
    print("[6/7] reviewed name maps, corpus-wide")
    run([PY, "scripts/fix_proper_nouns.py", "--write"], quiet=True)
    run([PY, "scripts/fix_yb_honorific.py", "--write"], quiet=True)
    print("[7/7] verify")
    run([PY, "scripts/check_owner_decisions.py", a.tag, str(raw), "--current", str(current)])
    report(a.tag, raw, reference)
    print(f"\nadopted {rel}. Read the diff before committing, then the four checkers.")


if __name__ == "__main__":
    main()
