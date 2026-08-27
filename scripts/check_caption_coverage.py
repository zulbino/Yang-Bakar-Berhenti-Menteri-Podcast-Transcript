"""Cross-check raw.md against YouTube's captions for content that is simply absent.

The content-loss check in qa_check.py (ENGINEERING_LOG.md 1.17) measures gaps
*between* consecutive timestamps, so it only sees loss that leaves a hole in the
timeline. Loss backfilled by duplicated or displaced blocks -- or, in ep48's
case, papered over with `[silence]` markers -- presents as a populated timeline
and escapes it entirely. That is how ep48's missing 40 minutes was not merely
undetected but affirmatively waived as "genuine dead air".

This check runs the other way round: it starts from the audio and asks what is
missing from the transcript. Sliding a 60s window across the caption, it scores
each bucket by the fraction of its word 4-grams that appear anywhere in raw.md.
4-grams are rare enough that a match means the speech really is present, and
common enough to be robust to ASR wording differences.

Usage:
  python scripts/check_caption_coverage.py [video_id ...]   # default: all
"""
import json
import re
import sys
from pathlib import Path

from common import episode_path, episode_slug, read_frontmatter_body
from dedupe_raw import fetch_captions, parse_caption_words

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"
OUT_PATH = ROOT / "data" / "caption_coverage.json"

BUCKET_SECONDS = 60
NGRAM = 4
MIN_GRAMS_PER_BUCKET = 5  # below this the bucket is music or silence, not evidence

# An absolute coverage floor does not work: how closely raw.md's wording tracks
# the captions varies hugely by episode. Healthy episodes cluster at 22-28%
# baseline, but four sit at 0-3% for mundane reasons that are not content loss
# (ep02 has English captions against a Malay transcript, ep21's YouTube ASR runs
# at half the normal word density, ep03's wording diverges from the captions
# throughout while its blocks still map to the right audio positions, and ep45's
# raw.md is 78% duplicated). Below MIN_MEASURABLE_BASELINE the transcript and the
# captions do not share enough wording for absence to mean anything, so the
# episode is reported unmeasurable rather than flagged.
MIN_MEASURABLE_BASELINE = 0.10
DEAD_BUCKET_FRACTION = 0.20  # of the episode's own median bucket
MIN_DEAD_RUN_SECONDS = 600   # 10 min; the worst false run on a clean episode is 120s


def _words(text):
    return re.sub(r"[^\w\s]", " ", text.lower()).split()


def check_episode(video_id, episode):
    raw_path = ROOT / "episodes" / episode_path(episode) / "raw.md"
    if not raw_path.exists():
        return None
    vtt_path = fetch_captions(video_id, "ms") or fetch_captions(video_id, "en")
    if not vtt_path:
        return {"status": "no_captions"}

    _, body = read_frontmatter_body(raw_path)
    raw = _words(body)
    raw_grams = {tuple(raw[i:i + NGRAM]) for i in range(len(raw) - NGRAM + 1)}

    words, times = parse_caption_words(vtt_path.read_text(encoding="utf-8"))
    if not times:
        return {"status": "no_captions"}
    end = times[-1]

    buckets, scores = [], []
    for start in range(0, end + 1, BUCKET_SECONDS):
        seg = [w for w in (re.sub(r"[^\w]", "", w.lower())
                           for w, t in zip(words, times) if start <= t < start + BUCKET_SECONDS) if w]
        grams = [tuple(seg[i:i + NGRAM]) for i in range(len(seg) - NGRAM + 1)]
        if len(grams) < MIN_GRAMS_PER_BUCKET:
            buckets.append((start, None))
            continue
        score = sum(1 for g in grams if g in raw_grams) / len(grams)
        buckets.append((start, score))
        scores.append(score)

    if not scores:
        return {"status": "no_speech"}
    baseline = sorted(scores)[len(scores) // 2]
    mean = sum(scores) / len(scores)
    if baseline < MIN_MEASURABLE_BASELINE:
        return {"status": "inconclusive", "baseline": round(baseline, 3),
                "mean_coverage": round(mean, 3), "caption_end": end}

    floor = baseline * DEAD_BUCKET_FRACTION
    runs, current = [], None
    for start, score in buckets:
        if score is not None and score < floor:
            current = [start, start + BUCKET_SECONDS] if current is None else [current[0], start + BUCKET_SECONDS]
        elif current:
            runs.append(current)
            current = None
    if current:
        runs.append(current)

    dead = [r for r in runs if r[1] - r[0] >= MIN_DEAD_RUN_SECONDS]
    worst = max((r[1] - r[0] for r in dead), default=0)
    return {
        "status": "ok",
        "baseline": round(baseline, 3),
        "mean_coverage": round(mean, 3),
        "caption_end": end,
        "dead_runs": dead,
        "worst_dead_run_seconds": worst,
        "flagged": bool(dead),
    }


def main():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    wanted = set(sys.argv[1:]) or None
    existing = json.loads(OUT_PATH.read_text(encoding="utf-8")) if OUT_PATH.exists() else {}

    for episode in manifest:
        video_id = episode["video_id"]
        if wanted and video_id not in wanted:
            continue
        slug = episode_slug(episode)
        result = check_episode(video_id, episode)
        if result is None:
            continue
        existing[slug] = result
        OUT_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        if result["status"] != "ok":
            print(f"{slug[:58]:58s} {result['status']}", flush=True)
        else:
            flag = "FLAGGED" if result["flagged"] else "ok"
            print(f"{slug[:58]:58s} {flag}: baseline {result['baseline']:.0%}, "
                  f"worst dead run {result['worst_dead_run_seconds']}s "
                  f"{result['dead_runs'] if result['dead_runs'] else ''}", flush=True)


if __name__ == "__main__":
    main()
