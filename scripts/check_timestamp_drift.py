"""Cross-check raw.md timestamps against YouTube's own auto-caption timing.

Complements the duplicate-block check (qa_check.py) and repair tool
(dedupe_raw.py): confirmed on ep30, a passage survived duplicate-block repair
but kept a timestamp ~11 minutes off from the caption-verified real time,
because none of its original duplicate occurrences happened to be close to
the truth -- dedupe_raw.py can only pick the least-wrong candidate among what
exists, not invent a correct one. This script catches that residual drift,
and any other timestamp inaccuracy, whether or not it's tied to a duplicate.

Samples blocks spread evenly across each episode, fuzzy-matches each against
the caption's word-level timing (same approach as dedupe_raw.py -- exact
phrase matching doesn't work since Gemini's cleaned-up transcript smooths out
disfluencies the raw ASR caption still has), and writes results to
data/timestamp_drift.json for qa_check.py to fold into QA_CHECKLIST.md.

Usage:
  python scripts/check_timestamp_drift.py [video_id ...]   # default: all episodes
"""
import json
import re
import sys
from pathlib import Path

from common import episode_path, episode_slug, read_frontmatter_body
from dedupe_raw import MATCH_WINDOW_WORDS, MIN_MATCHING_WORDS, fetch_captions, parse_caption_words

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"
EPISODES_DIR = ROOT / "episodes"
OUT_PATH = ROOT / "data" / "timestamp_drift.json"

SAMPLE_COUNT = 12  # blocks sampled per episode, spread evenly by position
MIN_BLOCK_CHARS = 150  # long enough to extract a distinctive phrase
# Fuzzy phrase matching alone has a noise floor of roughly 100-250s even on
# correctly-timed blocks (confirmed empirically: a known-clean episode showed
# drift up to ~220s from matching imprecision on ordinary samples). Only flag
# drift far beyond that, which is what genuine mistiming looks like -- ep30's
# confirmed real case was ~660s off.
DRIFT_THRESHOLD_SECONDS = 300
# A political talk show revisits the same topics (e.g. "nepotisme") at many
# points across a 2-3hr episode -- an unconstrained search for the best-
# scoring window anywhere in the caption can lock onto a distant but
# topically-similar segment instead of the block's real position (confirmed:
# one block's search matched a passage nearly an hour away purely on a
# recurring theme word). Constrain the search to a window around the block's
# own claimed timestamp -- genuine severe mistiming (whole sections displaced
# by an hour or more) shows up as "not found nearby" instead of a wrong
# distant match, which is actually a clearer signal.
SEARCH_RADIUS_SECONDS = 1200

BLOCK_TS_RE = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]")
# A block's timestamp labels where the block STARTS, so the phrase compared
# against it must come from the block's head. Sampling from the middle instead
# measured the offset from the block's start to its midpoint -- pure block
# length, not mistiming. raw.md blocks run to 5,000+ words (20+ minutes of
# speech), which produced 325-1083s of phantom "drift" on nine episodes, always
# positive and always on the longest block in the sample. See ARCHITECTURE.md 1.23.
BLOCK_PREFIX_RE = re.compile(r"^\[(?:\d+:)?\d+:\d+\]\s*(?:[^:\n]{1,40}:)?\s*")


def ts_to_seconds(ts):
    parts = [int(p) for p in ts.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def find_nearby_timestamp(words, times, phrase_words, claimed_ts, radius=SEARCH_RADIUS_SECONDS):
    """Same distinctive-word window scoring as dedupe_raw.find_phrase_timestamp,
    but restricted to a time window around claimed_ts to avoid locking onto a
    topically-similar but wrong distant match (see module docstring)."""
    distinctive = {w for w in phrase_words if len(w) >= 5}
    if len(distinctive) < MIN_MATCHING_WORDS:
        return None
    lo, hi = claimed_ts - radius, claimed_ts + radius
    best_score, best_pos = 0, None
    for i in range(len(words) - MATCH_WINDOW_WORDS + 1):
        if not (lo <= times[i] <= hi):
            continue
        score = len(distinctive & set(words[i:i + MATCH_WINDOW_WORDS]))
        if score > best_score:
            best_score, best_pos = score, i
    if best_score < MIN_MATCHING_WORDS:
        return None
    return times[best_pos]


def sample_blocks(body):
    candidates = []
    for block in body.split("\n\n"):
        stripped = block.strip()
        m = BLOCK_TS_RE.match(stripped)
        if not m or len(stripped) < MIN_BLOCK_CHARS:
            continue
        candidates.append((ts_to_seconds(m.group(1)), stripped))
    if len(candidates) <= SAMPLE_COUNT:
        return candidates
    step = len(candidates) / SAMPLE_COUNT
    return [candidates[int(i * step)] for i in range(SAMPLE_COUNT)]


def check_episode(video_id, episode):
    ep_dir = EPISODES_DIR / episode_path(episode)
    raw_path = ep_dir / "raw.md"
    if not raw_path.exists():
        return None
    _, body = read_frontmatter_body(raw_path)
    samples = sample_blocks(body)
    if not samples:
        return None

    vtt_path = fetch_captions(video_id, "ms") or fetch_captions(video_id, "en")
    if not vtt_path:
        return {"status": "no_captions"}
    words, times = parse_caption_words(vtt_path.read_text(encoding="utf-8"))

    results = []
    not_found = 0
    for claimed_ts, block in samples:
        head = BLOCK_PREFIX_RE.sub("", block)
        phrase = re.sub(r"[^\w\s]", " ", head.lower()).split()[:20]
        actual_ts = find_nearby_timestamp(words, times, phrase, claimed_ts)
        if actual_ts is None:
            not_found += 1
            continue
        results.append({"claimed": claimed_ts, "actual": actual_ts, "drift": actual_ts - claimed_ts})

    if not results and not not_found:
        return {"status": "no_matches"}
    max_drift = max((abs(r["drift"]) for r in results), default=0)
    # "not found nearby" on its own isn't proof of mistiming -- captions can miss
    # a phrase for mundane reasons (ASR garbled that specific stretch, ambient
    # noise). Only treat it as a mistiming signal when it happens on most
    # samples, which is what genuine large-scale displacement looks like.
    widespread_not_found = len(samples) >= 4 and not_found >= len(samples) * 0.6
    return {
        "status": "ok",
        "samples_matched": len(results),
        "samples_not_found_nearby": not_found,
        "samples_total": len(samples),
        "max_drift_seconds": max_drift,
        "flagged": max_drift > DRIFT_THRESHOLD_SECONDS or widespread_not_found,
        "details": results,
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
        print(f"checking {slug} ({video_id}) ...", flush=True)
        result = check_episode(video_id, episode)
        if result is None:
            continue
        existing[slug] = result
        OUT_PATH.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        status = result.get("status")
        if status == "ok":
            flag = "FLAGGED" if result["flagged"] else "ok"
            print(f"  {flag}: max drift {result['max_drift_seconds']}s "
                  f"({result['samples_matched']}/{result['samples_total']} samples matched)")
        else:
            print(f"  {status}")


if __name__ == "__main__":
    main()
