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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

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
        # Staleness cannot be read from mtime: writing the navigation header touched every
        # published file and made all five look fresh while their text still came from the
        # local-ASR raw. So it is content-based -- a published file is stale until its
        # frontmatter records the sha of the raw.md it was generated from, which
        # rewrite_segments.py stamps. Nothing carries that yet, so every MAI raw counts as
        # having stale published files, which is exactly true today.
        stale = adopted and any(
            "raw_sha:" not in io.open(os.path.join(folder, n), encoding="utf-8").read(1500)
            for n in published)
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
        queue_readiness([r for r in rows if r[0] in set(waiting)])


LABEL = re.compile(r"^\[[\d:]+\]\s*([^:\n]{1,40}?):", re.M)
GENERIC_LABEL = re.compile(
    r"^(speaker\b|multiple speakers|overlapping|audience|hadirin|unknown|\[)", re.I)


def queue_readiness(rows):
    """Which waiting episodes will produce a USABLE reference, and which need a photo first.

    A camera pass costs about 2.5 hours of GPU and its reference is then REFUSED if a
    speaker holding real word volume is in no face gallery. That is the ep33 class, and on
    2026-09-15 fifteen of the thirty-three waiting episodes were in it.

    The refusal is cheap to predict and expensive to discover. The split that matters is
    one-versus-many, not guest-versus-no-guest: `guest_gallery.py` names a guest with NO
    photograph when exactly one unnamed label is left, because one guest and one cluster
    holding the unidentified talking time is a bijection it can assert. Two unnamed labels
    defeat it, and then CLAUDE.md rule 9 needs a public photograph for all but the last.

    The gallery only matters at the `reference` step, which is cheap, needs no GPU and can
    be re-run any time. So an episode listed below is never blocked from its camera pass.
    It just cannot finish unattended.
    """
    enrolled = set()
    for f in glob.glob(str(ROOT / "data" / "_face_gallery*.json")):
        enrolled |= set(json.load(io.open(f, encoding="utf-8"))["gallery"])
    # KEYED ON VIDEO ID, not on the tag. Both shows have an ep01 through ep06, so
    # common.raw_for_tag raises on a bare tag for twelve of the thirty-three episodes
    # waiting here -- and the first version of this function swallowed that and reported
    # on 21, silently omitting the whole yang-bakar-menteri run plus six berhenti
    # episodes. A video id is unique across both shows.
    by_vid = {}
    for path in glob.glob(str(ROOT / "episodes" / "*" / "*" / "raw.md")):
        head = io.open(path, encoding="utf-8").read(4000)
        m = re.search(r"video_id:\s*(\S+)", head)
        if m:
            by_vid[m.group(1)] = path
    auto, photo, missing = [], [], []
    for row in rows:
        tag, vid = row[0], row[1]
        path = by_vid.get(vid)
        if not path:
            missing.append(tag)
            continue
        series = Path(path).parent.parent.name.split("-")[1]
        tag = f"{tag}:{series}" if sum(1 for r in rows if r[0] == row[0]) > 1 else tag
        body = io.open(path, encoding="utf-8").read()
        labels = {m.group(1).strip() for m in LABEL.finditer(body)}
        cand = sorted(l for l in labels
                      if l.split(" (")[0] not in enrolled and not GENERIC_LABEL.search(l))
        (auto if len(cand) <= 1 else photo).append((tag, cand))
    assert len(auto) + len(photo) + len(missing) == len(rows), "queue readiness dropped rows"
    if missing:
        print(f"   NO raw.md found for {len(missing)}: {' '.join(missing)}")
    print(f"   {len(auto)} of those need NO photograph: the cast gate passes, or "
          f"guest_gallery.py names the one unnamed guest from the tracks")
    if photo:
        print(f"   {len(photo)} name more than one unenrolled person. Rule 9 needs a "
              f"photograph for all but the last, before the reference step:")
        for tag, cand in photo:
            print(f"     {tag:<6} {cand}")


if __name__ == "__main__":
    main()
