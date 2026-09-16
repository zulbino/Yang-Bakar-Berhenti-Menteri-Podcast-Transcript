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
  3. `strip_filler_turns.py` then `strip_inline_fillers.py` -- a turn that is only a noise
     goes, then the noises inside real sentences go too ("Yalah. Uh, I mean" -> "Yalah. I
     mean"). The owner asked for the second one twice. `ha`, `eh`, `aa` and `oh` are kept:
     they carry meaning in Malay. Must precede the fold: before it, a
     fragment's neighbour is a grunt, and the fold's "same speaker either side" test cannot
     fire.
  4. `fold_hanging_fragments.py` -- a mid-sentence fragment the camera cannot see at all
     falls to the speaker around it. Camera-attested fragments are never touched.
  5. `move_hanging_words.py` -- a sentence is never split between two speakers. The tail
     after a block's last full stop moves into the next block when that block continues the
     sentence in lower case. The camera does NOT get a veto here: it attests the wrong
     speaker on exactly these boundaries, because the show cuts to the person about to
     answer. The owner has raised this defect three times.
  6. `merge_same_speaker.py` -- adjacent same-name blocks join. The fold creates new
     adjacency, so it runs after.
  6b. `voice_witness.py --validate` then `--write` -- the episode's own voices, learned from
     the camera's seconds, name what is still generic. Runs ONLY if the strict bar measures
     100% on this episode's held-out 1.6 s windows (owner's rule: a probabilistic vote is not
     identification; 97.6% stays `Speaker ?`). Then the merge runs again.
  6c. `move_hanging_words.py --camera-veto` then `merge_same_speaker.py` AGAIN. The merge at
     step 6 joins blocks, which puts a tail next to a block that was not adjacent when step 5
     looked. Added 2026-09-16 after ep18, ep19 and ep22 each turned out to hold one such tail
     AFTER a clean adoption. The veto is on here and off at step 5: see the comment at the
     call for why the owner's 11-of-11 measurement does not cover this shape.
  6d. `drop_orphan_backchannels.py` then `merge_same_speaker.py` again. A turn of three words
     or fewer, made only of pure acknowledgement tokens, sitting between two blocks of the
     same OTHER speaker, is removed. Owner's decision 2026-09-16. It cannot be attributed by
     any evidence this repo has: the camera is lip-sync, so it credits the one visible
     talking face, and 10 of the owner's 19 blind-sample rows were the other person speaking
     off frame. The lexicon is CLOSED and deliberately excludes `Betul.`, `Setuju.`,
     `Kan?` and `Alhamdulillah.`, which carry a position rather than a signal.
  7. `fix_proper_nouns.py` and `fix_yb_honorific.py` -- corpus-wide reviewed maps. MAI
     spells the honorific `Abi` where the local ASR wrote `wabi`, so a fresh MAI raw always
     needs the second one.
  8. Verification, printed: decisions, gold, adjacency, grunts, garbles, hanging fragments,
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

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
        for line in ((p.stdout or "") + (p.stderr or "")).strip().splitlines():
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
    ap.add_argument("--force-blind-reference", action="store_true",
                    help="adopt even though the camera reference cannot see a "
                         "speaker raw.md credits with real word volume")
    ap.add_argument("--current", help="the raw.md the owner decisions were recorded against; "
                                      "defaults to the episode's committed raw.md")
    a = ap.parse_args()

    raw_path = common.raw_for_tag(a.tag)
    raw = Path(raw_path)
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

    # THE CAST GATE RUNS BEFORE ANYTHING IS BUILT, and 2026-09-13 is why. It was wired
    # only into step 4b, where fold_hanging_fragments.py refused correctly and said so --
    # and this script carried on and wrote the candidate anyway. The overnight queue
    # adopted ep42 and ep39 on references blind to a guest who really speaks (Zikri
    # Kamarulzaman 14.2% of raw's words at 0.0% of camera time; Iqbal 5.3% at 0.0%), and 16
    # of ep42's 74 Zikri blocks came back under a host -- including his own introduction,
    # `bagi yang tak kenal saya, saya Zikri`, as Rafizi. Both had to be reverted by hand.
    # A reference that cannot see a speaker must stop the adoption, not one step of it.
    sys.path.insert(0, str(ROOT / "scripts"))
    import check_camera_reference as ccr  # noqa: E402
    if not ccr.check(a.tag, reference) and not a.force_blind_reference:
        sys.exit(f"{a.tag}: REFUSING to adopt. The camera reference is blind to a speaker "
                 f"raw.md says holds real word volume, so that person's words get handed to "
                 f"the nearest gallery member. Enrol them first (the face-census / "
                 f"label-census / gallery subcommands of camera_speakers.py), or pass "
                 f"--force-blind-reference if you have read data/camera_reference_limits.json "
                 f"and know why this one is safe.")

    candidate = ROOT / "data" / f"_{a.tag}_candidate_raw.md"
    print(f"[1/8] build from MAI words + the camera, fallback and gold from {current.name}")
    code, _ = run([PY, "scripts/mai_camera_raw.py", a.tag, "--current", str(current),
                   "--out", str(candidate)])
    if code:
        sys.exit("build failed")

    print("[2/8] gate: every recorded owner decision survives the candidate")
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
    print("[3/8] drop turns that are only a vocalisation")
    run([PY, "scripts/strip_filler_turns.py", str(raw), "--write"])
    print("[4/8] remove the meaningless filler sounds from inside sentences")
    run([PY, "scripts/strip_inline_fillers.py", a.tag, "--write", "--samples", "0"])
    print("[4b/8] fold hanging fragments the camera cannot see")
    code, _ = run([PY, "scripts/fold_hanging_fragments.py", a.tag, "--write"])
    fold_refused = bool(code)
    print("[5/8] move hanging half-sentences to the speaker who finishes them")
    run([PY, "scripts/move_hanging_words.py", a.tag, "--write"])
    print("[6/8] join adjacent same-speaker blocks")
    run([PY, "scripts/merge_same_speaker.py", f"--episode={a.tag}", "--raw-only", "--write"])
    print("[6b/8] voice witness: name what the camera and the clusters left generic, but only "
          "if it measures 100% on this episode's held-out short windows first")
    code, out = run([PY, "scripts/voice_witness.py", a.tag, "--validate"], quiet=True)
    # The line for the strict bar on 1.6 s windows: "    1.6     score>=.60 & margin>=.30  n named right acc"
    m = re.search(r"^\s*1\.6\s+score>=\.60 & margin>=\.30\s+\d+\s+(\d+)\s+(\d+)\s+([\d.]+)%", out or "", re.M)
    if code or not m:
        print("   voice witness skipped: validation did not run (" + (out or "").strip()[-160:] + ")")
    elif int(m.group(1)) < 10 or int(m.group(2)) != int(m.group(1)):
        print(f"   voice witness skipped: strict bar on 1.6 s held-out windows is {m.group(2)}/{m.group(1)}, "
              f"not 100% over at least 10 -- the owner's rule is that only a witness measured at "
              f"100% on its class writes a label (CLAUDE.md rule 8)")
    else:
        print(f"   validated: strict bar {m.group(2)}/{m.group(1)} on 1.6 s held-out windows")
        run([PY, "scripts/voice_witness.py", a.tag, "--write"])
        run([PY, "scripts/merge_same_speaker.py", f"--episode={a.tag}", "--raw-only", "--write"], quiet=True)
    # THE MERGE CREATES TAILS THE MOVE ALREADY WALKED PAST, so step 5 has to run again.
    # CLAUDE.md rule 6 states the mirror of this (re-run the merge after the move) and rule 8
    # states the general form (re-run a tool when a later pass changes its input); neither was
    # wired into this sequence. Measured 2026-09-16, right after ep20, ep19 and ep18 adopted
    # clean: a second pass found one real tail in each of ep18, ep19 and ep22, and
    # check_overlap_boundaries.py had gone from 0 contested to 1 because of it.
    #
    # --camera-veto IS ON HERE and off in step 5, deliberately. Step 5's default was measured
    # against the owner's ear 11 of 11 on boundaries where the camera shows the NEXT speaker
    # during the previous block. A tail the camera attests to the CURRENT speaker is the other
    # shape, that measurement does not cover it, and ep18's 1:32:59 is the case. Leaving it
    # for an ear is rule 8; moving it would be a guess dressed as a tool.
    print("[6c/8] the merge created new adjacency, so move and merge again")
    run([PY, "scripts/move_hanging_words.py", a.tag, "--camera-veto", "--write"])
    run([PY, "scripts/merge_same_speaker.py", f"--episode={a.tag}", "--raw-only", "--write"], quiet=True)
    # OWNER'S DECISION 2026-09-16: a contentless backchannel inside one speaker's run is
    # removed rather than attributed. Their words: "actually anything offscreen, and the
    # word is just not adding in to anything, we can just safely omit?" The reason it cannot
    # be attributed instead is measured: a 19-row blind sample scored the one-face lip-sync
    # test at 12 of 19, and all 7 misses were the other person speaking OFF FRAME, which no
    # camera can see. Runs AFTER the merge because before it a backchannel's neighbour is
    # often another fragment rather than the speaker's own block.
    print("[6d/8] drop contentless backchannels that sit inside one speaker's run")
    run([PY, "scripts/drop_orphan_backchannels.py", a.tag, "--write"])
    run([PY, "scripts/merge_same_speaker.py", f"--episode={a.tag}", "--raw-only", "--write"], quiet=True)
    print("[7/8] reviewed name maps, corpus-wide")
    run([PY, "scripts/fix_proper_nouns.py", "--write"], quiet=True)
    run([PY, "scripts/fix_yb_honorific.py", "--write"], quiet=True)
    print("[8/8] rewrite the navigation header (a rebuild wipes it) and verify")
    run([PY, "scripts/write_navigation.py", "--write"], quiet=True)
    run([PY, "scripts/check_owner_decisions.py", a.tag, str(raw), "--current", str(current)])
    report(a.tag, raw, reference)
    if fold_refused:
        print(f"\n{a.tag}: fold_hanging_fragments REFUSED (camera blind to a real speaker) and "
              f"was skipped, not overridden -- hanging fragments were left as-is rather than "
              f"folded on a reference that cannot be trusted for them.")
    print(f"\nadopted {rel}. Read the diff before committing, then the four checkers.")


if __name__ == "__main__":
    main()
