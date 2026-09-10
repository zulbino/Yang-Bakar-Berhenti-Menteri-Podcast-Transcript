"""One table: where every episode stands in the MAI+camera pass, and what is missing.

WHY. The pass has four stages per episode -- MAI words, a camera reference, the raw adopted,
the published files rebuilt -- and 69 episodes. Answering "what is left?" by running greps
costs a page of output every time and invites a wrong answer. This prints one row per
episode and one summary line.

IT ALSO CHECKS THE ONE THING THAT FAILS SILENTLY. A MAI transcript can come back short: the
API returns 503 above about 30 minutes of audio, an opaque 500 when a long request opens on
silence, and a stale chunk file once cost ep61 fifteen minutes of speech. None of that raises
an error. So the MAI column is not "present", it is the share of the episode's own duration
that MAI's last word reaches. Anything below 97% is flagged and needs its chunks re-cut, not
its transcript read.

  python scripts/corpus_status.py             # the table
  python scripts/corpus_status.py --short      # the summary line and the flags only
"""
import argparse
import glob
import io
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COVERAGE_FLOOR = 0.97


def mai_coverage(vid, seconds):
    files = sorted(glob.glob(str(ROOT / f"data/_mai_{vid}/mai_response_*.json")))
    if not files or not seconds:
        return None, 0
    last, words = 0.0, 0
    for path in files:
        blob = json.load(io.open(path, encoding="utf-8"))
        base = blob.get("_chunk_start_s", 0)
        for phrase in blob.get("phrases", []):
            spoken = phrase.get("words") or []
            words += len(spoken)
            if spoken:
                last = max(last, base + spoken[-1]["offsetMilliseconds"] / 1000)
    return last / seconds, words


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--short", action="store_true")
    a = ap.parse_args()

    rows = []
    for folder in sorted(glob.glob(str(ROOT / "episodes/*/*/"))):
        raw_path = os.path.join(folder, "raw.md")
        if not os.path.exists(raw_path):
            continue
        head = io.open(raw_path, encoding="utf-8").read(1200)
        vid = re.search(r"video_id:\s*(\S+)", head)
        seconds = re.search(r"duration_seconds:\s*(\d+)", head)
        tag = re.search(r"-(ep\d+)-", folder)
        if not (vid and tag):
            continue
        vid, tag = vid.group(1), tag.group(1)
        seconds = int(seconds.group(1)) if seconds else 0
        adopted = "MAI-Transcribe-2" in head
        reference = (ROOT / "data" / f"camera_ref_{tag}.rttm").exists()
        coverage, words = mai_coverage(vid, seconds)
        published = [n for n in ("interview.md", "interview-ms.md", "interview-en.md")
                     if os.path.exists(os.path.join(folder, n))]
        # A published file older than the raw it came from is stale by definition.
        stale = adopted and any(os.path.getmtime(os.path.join(folder, n))
                                < os.path.getmtime(raw_path) for n in published)
        rows.append((tag, vid, coverage, words, reference, adopted, len(published), stale))

    rows.sort(key=lambda r: int(r[0][2:]), reverse=True)
    if not a.short:
        print(f"{'ep':>6} {'MAI':>7} {'words':>7} {'camera':>7} {'raw':>5} {'published':>10}")
        for tag, _, cov, words, ref, adopted, n, stale in rows:
            mai = "-" if cov is None else f"{cov:.0%}" + ("!" if cov < COVERAGE_FLOOR else "")
            print(f"{tag:>6} {mai:>7} {words or '':>7} {'yes' if ref else '-':>7} "
                  f"{'MAI' if adopted else 'local':>5} "
                  f"{(str(n) + ' stale' if stale else str(n)) if n else 'none':>10}")

    have_mai = [r for r in rows if r[2] is not None]
    short = [r for r in have_mai if r[2] < COVERAGE_FLOOR]
    print(f"\n{len(rows)} episodes | MAI words {len(have_mai)} | camera reference "
          f"{sum(1 for r in rows if r[4])} | raw adopted {sum(1 for r in rows if r[5])} | "
          f"published stale {sum(1 for r in rows if r[7])}")
    if short:
        print("MAI transcripts that do not reach the end of their episode -- re-cut these:")
        for tag, vid, cov, words, *_ in short:
            print(f"   {tag} {vid}: {cov:.0%} of the episode, {words} words")
    ready = [r[0] for r in rows if r[2] and r[2] >= COVERAGE_FLOOR and r[4] and not r[5]]
    if ready:
        print("ready to adopt now (MAI words + camera reference, raw still local):",
              " ".join(ready))
    waiting = [r[0] for r in rows if r[2] and r[2] >= COVERAGE_FLOOR and not r[4]]
    if waiting:
        print(f"waiting on a camera reference ({len(waiting)}):", " ".join(waiting[:12]),
              "..." if len(waiting) > 12 else "")


if __name__ == "__main__":
    main()
