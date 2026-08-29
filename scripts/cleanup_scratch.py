"""Delete derived scratch files. Never deletes a source, never deletes a tracked file.

The repo reached 14 GB and 8.2 of those were decoded WAVs that ffmpeg rebuilds on demand.
Everything listed below is either regenerated automatically on next use or reproducible
from a tracked input, so losing it costs seconds.

WHAT IS A SOURCE AND WHAT IS DERIVED, because the distinction is the whole safety argument:

  audio/*.wav        DERIVED. `verify_speaker_voiceprint.load_audio()` runs ffmpeg on the
                     .m4a whenever the WAV is missing, so deleting one is invisible.
                     29 files, 8.2 GB.
  audio/*.m4a        SOURCE, and NOT deleted even with --all. Rebuilding means yt-dlp plus
                     the PO-token server plus YouTube agreeing to serve it, which is the
                     fragile part of this whole pipeline (see ARCHITECTURE's setup notes).
                     Deleting the WAVs is only free BECAUSE these stay.
  audio/*.vtt        SOURCE, and load-bearing far beyond its 63 MB: the captions are the
                     ground truth behind check_caption_coverage, check_timestamp_drift,
                     cohost_candidates and every split timestamp in
                     data/speaker_adjudications.json. Never deleted.

  data/_*_incumbent  gate_rewrite.py's pre-promotion backups. Once a verdict is in and the
                     episode is committed, git holds the history these existed to protect.
  data/_gatelogs/    Batch logs, already summarised into ENGINEERING_LOG.
  data/frames_cache/ Video clips behind frames_at.py. Also video data with no licence to
                     keep around, which is the same reason audio/ is gitignored.
  frames_*.png       Contact sheets, regenerated in seconds.
  scripts/__pycache__
  unresolved_speakers.html   adjudicate_speakers.py rebuilds it from raw.md.

THE GUARD THAT MATTERS: nothing git tracks is ever deleted, checked per path rather than
assumed from the pattern. `data/diar_*.json` sits right beside `data/_*_incumbent` and IS
tracked -- 38 files of diarization output that cost GPU time to rebuild.

  python scripts/cleanup_scratch.py            # report only
  python scripts/cleanup_scratch.py --write
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (label, [paths]) -- globbed here so the report shows real sizes, not patterns.
def targets():
    return [
        ("decoded WAVs (ffmpeg rebuilds on demand)", sorted(ROOT.glob("audio/*.wav"))),
        ("gate pre-promotion backups", sorted(ROOT.glob("data/_*_incumbent"))),
        ("gate batch logs", [ROOT / "data" / "_gatelogs"]),
        ("video frame cache", [ROOT / "data" / "frames_cache"]),
        ("frame contact sheets", sorted(ROOT.glob("frames_*.png"))),
        ("python bytecode", sorted(ROOT.glob("**/__pycache__"))),
        ("regenerable review page", [ROOT / "unresolved_speakers.html"]),
    ]


def tracked_paths():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    return {(ROOT / line).resolve() for line in out.stdout.splitlines() if line}


def size_of(p):
    if p.is_dir():
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    return p.stat().st_size if p.exists() else 0


def human(n):
    for unit in ["B", "K", "M", "G"]:
        if n < 1024 or unit == "G":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024


def gate_in_progress():
    """A gate run whose verdict has not landed yet.

    `data/_<slug>_incumbent` is not a leftover while gate_rewrite.py is running -- it is
    the ONLY copy of the published files it will restore if the candidate loses. Deleting
    it mid-run turns a rejected candidate into a permanent overwrite, which is the exact
    failure the gate exists to prevent. A log with no verdict line means still running.
    """
    logs = sorted((ROOT / "data" / "_gatelogs").glob("*.log"))
    running = []
    for log in logs:
        text = log.read_text(encoding="utf-8", errors="replace")
        if "KEPT candidate" not in text and "RESTORED incumbent" not in text:
            running.append(log.stem)
    return running


def main():
    write = "--write" in sys.argv
    if write and (running := gate_in_progress()):
        raise SystemExit(
            f"REFUSING: gate_rewrite still running on {', '.join(running)} -- its "
            f"data/_*_incumbent backup is the only copy of the published files it would "
            f"restore on a losing candidate. Wait for the verdict, then re-run.")
    tracked = tracked_paths()
    total, skipped = 0, []

    for label, paths in targets():
        paths = [p for p in paths if p.exists()]
        safe = []
        for p in paths:
            # Per-path, not per-pattern: data/diar_*.json is tracked and sits beside the
            # backups this deletes.
            if p.resolve() in tracked:
                skipped.append(p)
                continue
            safe.append(p)
        if not safe:
            continue
        n = sum(size_of(p) for p in safe)
        total += n
        print(f"  {human(n):>7}  {len(safe):>3} item(s)  {label}")
        if write:
            for p in safe:
                shutil.rmtree(p) if p.is_dir() else p.unlink()

    print()
    for pat, why in [("audio/*.m4a", "SOURCE -- yt-dlp + PO tokens + YouTube to rebuild"),
                     ("audio/*.vtt", "SOURCE -- ground truth for every timing check")]:
        files = sorted(ROOT.glob(pat))
        if files:
            print(f"  KEPT {human(sum(size_of(f) for f in files)):>7}  "
                  f"{len(files):>3} {pat:<12} {why}")
    if skipped:
        print(f"\n  refused {len(skipped)} tracked file(s), e.g. {skipped[0].name}")
    print(f"\n{human(total)} " + ("freed" if write else "would be freed -- pass --write"))


if __name__ == "__main__":
    main()
