"""Take an episode from a local-ASR raw all the way to an adopted one, unattended, in a loop.

WHY THIS EXISTS, and why it is a departure. `nightly_recut.py` says at the top that it
"Writes NOTHING to episodes/", and that adopting is "a morning decision, taken after
reading the diff, never by this script". That was right when it was written. The owner
changed it on 2026-09-16: *"can we get the leftover episode by today? dont wait for me, do
one episode then move on to the next. Anything that need my clarification after all else
fails, bring it after the corpus is done so I can verify"*.

So this script does what the chain deliberately would not: it adopts. Three things had to
be true first, and all three are true as of today.

  1. `adopt_mai_camera_raw.py` refuses rather than half-applies. The cast gate stops a
     blind reference at step 0, the owner-decision gate stops a broken ruling at step 2,
     and `must()` now reads every write step's exit code. That last one landed today, after
     ep61 shipped 704 filler words because a refusal was printed and ignored.
  2. Every write tool conserves words under its own guard, and says so in its output.
  3. The owner asked for the diffs in one batch at the end rather than one at a time.

WHAT IT WILL NOT DO. It never passes `--force-blind-reference`, never uses
`git commit --no-verify`, and never retries a refusal with a looser flag. A refusal ends
that episode and the loop moves to the next one, which is exactly what the owner asked
for. Everything refused is collected in the report for one conversation at the end.

ONE GPU JOB AT A TIME is still the rule, and this script honours it by construction: it
runs `nightly_recut.py` for ONE tag and waits. That script's own `claim_the_gpu()` writes
`data/_nightly/chain.pid` and refuses to start while a live pid holds it. Two chains do not
merely compete, they name the same LR-ASD scratch directory and delete each other's work.

THE REFUSED-CAST-GATE RECIPE is built in, because three refusals in three days were all
closed by it and none needed a photograph. When `check_camera_reference.py` refuses, this
runs `guest_gallery.py`, rebuilds the reference against the per-episode gallery it wrote,
and re-checks. Only if that still refuses does the episode go to the owner under rule 9.

  python scripts/overnight_corpus.py                       # every unadopted episode
  python scripts/overnight_corpus.py ep14 ep13 --hours 12   # a subset, with a deadline
  python scripts/overnight_corpus.py --no-commit            # leave the files staged-less

Read `data/_overnight_report.md` afterwards. Never trust a count in it over
`python scripts/corpus_status.py`.
"""
import argparse
import io
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
PY = sys.executable
REPORT = ROOT / "data" / "_overnight_report.md"
STATE = ROOT / "data" / "_overnight_state.json"


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def run(cmd, tail=4000):
    """Run a subprocess. `tail=0` returns the WHOLE output; any other value keeps the end."""
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0, (out if tail == 0 else out[-tail:])


def remaining():
    """Unadopted episodes, newest first, from check_raw_engine's own verdict.

    Derived rather than hardcoded: `check_raw_engine.py` is the mechanism CLAUDE.md names
    for "best engine for raw.md", so it is the authority on which raws are still local.
    """
    # tail=0 means DO NOT TRUNCATE, and it is load-bearing. The default 4000-character tail
    # silently cut the top of the listing, where the six yang-bakar-menteri episodes are, so
    # a first run reported 13 unambiguous tags when 9 is the right answer -- it had simply
    # never seen the duplicates it was meant to exclude.
    _, out = run([PY, "scripts/check_raw_engine.py"], tail=0)
    seen, order = {}, []
    for line in out.splitlines():
        m = re.match(r"^(ep\d+)\s+(\S+)", line.strip())
        if not m:
            continue
        tag, folder = m.group(1), m.group(2)
        seen.setdefault(tag, []).append(folder)
        if tag not in order:
            order.append(tag)
    # AN AMBIGUOUS TAG IS EXCLUDED, and the reason is a silent Windows trap rather than
    # tidiness. ep01 to ep06 exist in BOTH shows, so common.raw_for_tag refuses the bare
    # tag and wants `ep05:bakar`. Every artifact name in this pipeline is built as
    # `camera_ref_<tag>.rttm`, and a colon in an NTFS path creates an ALTERNATE DATA
    # STREAM: measured 2026-09-16, `data/camera_ref_ep05:bakar.rttm` wrote its content into
    # a hidden stream and left a 0-byte `camera_ref_ep05` in the listing. Path.exists()
    # returned True the whole time, so nothing would have reported a problem. Those 12
    # episodes need a filesystem-safe tag first; run them with an explicit qualified tag
    # only after that is fixed.
    return [t for t in order if len(seen[t]) == 1]


def video_and_duration(tag):
    import common
    head = io.open(common.raw_for_tag(tag), encoding="utf-8").read()[:2000]
    vid = re.search(r"video_id:\s*([\w-]+)", head)
    dur = re.search(r"duration_seconds:\s*(\d+)", head)
    return (vid.group(1) if vid else None), (int(dur.group(1)) if dur else None)


def ensure_reference(tag, hours_left):
    """Return (ok, note). Builds the camera reference if it is missing, then gates it."""
    ref = ROOT / "data" / f"camera_ref_{tag}.rttm"
    if not ref.exists():
        if hours_left is not None and hours_left <= 0:
            return False, "deadline reached before a camera run could start"
        log(f"{tag}: no reference, running the camera chain (about 1.6 h)")
        ok, out = run([PY, "scripts/nightly_recut.py", tag])
        if not ref.exists():
            return False, f"camera chain produced no reference. tail: {out[-600:]}"

    ok, out = run([PY, "scripts/check_camera_reference.py", tag])
    if ok:
        return True, "reference usable"

    # The refused-cast-gate recipe. The guest is usually already enrolled somewhere, or
    # guest_gallery can name the one unnamed face from the tracks under its bijection.
    log(f"{tag}: reference REFUSED, trying guest_gallery.py before escalating")
    g_ok, g_out = run([PY, "scripts/guest_gallery.py", tag])
    vid, dur = video_and_duration(tag)
    gallery = ROOT / "data" / f"_face_gallery_{vid}.json"
    if not (g_ok and gallery.exists() and vid and dur):
        return False, ("cast gate refused and guest_gallery could not name the face, so "
                       "rule 9 needs a photograph. tail: " + g_out[-500:])
    log(f"{tag}: gallery written, rebuilding the reference (no GPU)")
    run([PY, "scripts/camera_speakers.py", "reference",
         "--tracks", f"data/_camera_tracks_{vid}", "--out", f"data/camera_ref_{tag}",
         "--runtime", str(dur), "--gallery", str(gallery.relative_to(ROOT)), "--", vid])
    ok, out = run([PY, "scripts/check_camera_reference.py", tag])
    if ok:
        return True, "reference usable after guest_gallery named the guest"
    return False, ("cast gate still refuses after guest_gallery, so rule 9 needs a "
                   "photograph. tail: " + out[-500:])


def gates(tag):
    """Every per-episode gate. Returns a list of (name, ok, one-line verdict)."""
    import common
    raw = str(common.raw_for_tag(tag))
    out = []
    for name, cmd in [
        ("owner decisions", [PY, "scripts/check_owner_decisions.py", tag, raw]),
        ("owner text", [PY, "scripts/check_owner_text.py", tag]),
        ("rule 7 boundaries", [PY, "scripts/check_overlap_boundaries.py", tag]),
        ("slurs", [PY, "scripts/check_slurs.py"]),
        ("cast", [PY, "scripts/check_cast.py", tag]),
    ]:
        ok, text = run(cmd, tail=1500)
        last = [l.strip() for l in text.splitlines() if l.strip()]
        out.append((name, ok, last[-1][:200] if last else "(no output)"))
    return out


def commit(tag, note):
    import common
    rel = Path(common.raw_for_tag(tag)).relative_to(ROOT).as_posix()
    run(["git", "add", "--", rel])
    ok, out = run(["git", "commit", "-m", f"{tag} adopted unattended: {note}"])
    return ok, out[-400:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="*", help="default: every episode check_raw_engine flags")
    ap.add_argument("--hours", type=float, default=None,
                    help="do not START a new camera run after this many hours")
    ap.add_argument("--no-commit", action="store_true")
    a = ap.parse_args()

    tags = a.tags or remaining()
    started = time.time()
    log(f"{len(tags)} episode(s) to take through camera + adoption: {' '.join(tags)}")
    results = []

    for n, tag in enumerate(tags, 1):
        hours_left = None if a.hours is None else a.hours - (time.time() - started) / 3600
        log(f"[{n}/{len(tags)}] {tag} starting")
        t0 = time.time()
        ok, note = ensure_reference(tag, hours_left)
        if not ok:
            log(f"{tag}: BLOCKED before adoption -- {note[:160]}")
            results.append(dict(tag=tag, state="blocked", stage="reference", note=note,
                                minutes=round((time.time() - t0) / 60, 1)))
            write_report(results, started, tags)
            continue

        ok, out = run([PY, "scripts/adopt_mai_camera_raw.py", tag, "--write"], tail=8000)
        if not ok:
            refusal = next((l for l in reversed(out.splitlines())
                            if "REFUS" in l or "no camera reference" in l), out[-300:])
            log(f"{tag}: adoption REFUSED -- {refusal[:160]}")
            results.append(dict(tag=tag, state="blocked", stage="adoption",
                                note=refusal.strip()[:600],
                                minutes=round((time.time() - t0) / 60, 1)))
            write_report(results, started, tags)
            continue

        g = gates(tag)
        failed = [name for name, passed, _ in g if not passed]
        committed = ""
        if not a.no_commit:
            c_ok, c_out = commit(tag, note)
            committed = "committed" if c_ok else f"NOT committed: {c_out[:200]}"
        log(f"{tag}: adopted in {(time.time()-t0)/60:.0f} min, "
            f"gates {'all pass' if not failed else 'FAILED: ' + ', '.join(failed)}")
        results.append(dict(tag=tag, state="adopted" if not failed else "adopted-gate-failed",
                            stage="done", note=note, gates=g, failed=failed,
                            commit=committed, minutes=round((time.time() - t0) / 60, 1)))
        write_report(results, started, tags)

    write_report(results, started, tags, final=True)
    done = sum(1 for r in results if r["state"] == "adopted")
    log(f"finished: {done} adopted, {len(results) - done} need attention, "
        f"{(time.time() - started)/3600:.1f} h elapsed")


def write_report(results, started, tags, final=False):
    STATE.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = ["# Overnight corpus run", "",
             f"Started {time.strftime('%Y-%m-%d %H:%M', time.localtime(started))}, "
             f"{(time.time() - started)/3600:.1f} h elapsed, "
             f"{len(results)} of {len(tags)} episode(s) attempted."
             + ("" if final else " STILL RUNNING."), "",
             "Never trust a count here over `python scripts/corpus_status.py`.", "",
             "| ep | state | min | note |", "|---|---|---|---|"]
    for r in results:
        note = r["note"].replace("\n", " ").replace("|", "/")[:150]
        lines.append(f"| {r['tag']} | {r['state']} | {r['minutes']} | {note} |")
    blocked = [r for r in results if r["state"] != "adopted"]
    if blocked:
        lines += ["", "## Needs the owner, per rule 9 and rule 8", ""]
        for r in blocked:
            lines += [f"### {r['tag']} -- blocked at {r['stage']}", "",
                      "```", r["note"][:1200], "```", ""]
    for r in results:
        if r.get("failed"):
            lines += [f"### {r['tag']} adopted but a gate failed: {', '.join(r['failed'])}",
                      ""]
            for name, ok, verdict in r.get("gates", []):
                lines.append(f"- {'pass' if ok else 'FAIL'} {name}: {verdict}")
            lines.append("")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
