"""Repair raw.md files where the continuation loop duplicated a long block
verbatim at a fabricated timestamp (see qa_check.py's duplicate_blocks check and
ARCHITECTURE.md's "duplicate-block hallucination" section).

Cross-checks each duplicate group against YouTube's own auto-generated captions --
inaccurate on diarization and punctuation, but the word-level timing is generated
directly against the real audio, so it reliably tells which of N occurrences is the
one that actually happened at that time. Confirmed on a real case: a passage
duplicated at three fabricated timestamps in a raw.md had its real occurrence
pinned by the caption to within seconds of one of the three. This avoids re-burning
a full Gemini raw-transcription call just to fix a duplicated section.

Usage:
  python scripts/dedupe_raw.py <video_id> [--apply]   # default is a dry run
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from common import episode_path, frontmatter_md, read_frontmatter_body

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"
EPISODES_DIR = ROOT / "episodes"
CAPTION_DIR = ROOT / "audio"

DUPLICATE_BLOCK_MIN_CHARS = 300  # matches qa_check.py's threshold
SPEAKER_PREFIX_RE = re.compile(r"^\[(?:\d+:)?\d+:\d+\]\s*[^:]*:\s*")
BLOCK_TS_RE = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]")

# Only words YouTube tagged with their own timing are captured -- the rolling
# caption redraw repeats already-settled words as bare untagged text on later
# cues, so this naturally skips those without extra bookkeeping.
TIMESTAMP_TAG_RE = re.compile(r"<(\d\d):(\d\d):(\d\d)\.\d\d\d><c>([^<]*)</c>")


def _load_episode(video_id):
    episodes = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for ep in episodes:
        if ep["video_id"] == video_id:
            return ep
    raise SystemExit(f"video_id {video_id} not found in manifest")


def ts_to_seconds(ts):
    parts = [int(p) for p in ts.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def fetch_captions(video_id, lang):
    CAPTION_DIR.mkdir(exist_ok=True)
    out_tmpl = str(CAPTION_DIR / f"{video_id}.%(ext)s")
    subprocess.run(
        ["python", "-m", "yt_dlp", "--write-auto-subs", "--sub-langs", lang,
         "--skip-download", "--sleep-requests", "2", "-o", out_tmpl,
         f"https://www.youtube.com/watch?v={video_id}"],
        check=True, capture_output=True, text=True,
    )
    path = CAPTION_DIR / f"{video_id}.{lang}.vtt"
    return path if path.exists() else None


def parse_caption_words(vtt_text):
    words, times = [], []
    for h, m, s, word in TIMESTAMP_TAG_RE.findall(vtt_text):
        word = word.strip()
        if not word:
            continue
        words.append(word.lower())
        times.append(int(h) * 3600 + int(m) * 60 + int(s))
    return words, times


MATCH_WINDOW_WORDS = 40  # ~15-25s of speech at typical talking pace
MIN_MATCHING_WORDS = 4  # of the phrase's distinctive words, found within one window


def find_phrase_timestamp(words, times, phrase_words):
    """Fuzzy match: Gemini's "lightly cleaned" transcript smooths out the
    disfluencies YouTube's raw ASR caption still has, so exact consecutive-word
    matches rarely line up. Instead, score each window of the caption by how many
    of the phrase's distinctive (5+ char) words it contains, and return the
    earliest position of the best-scoring window above a minimum threshold."""
    distinctive = {w for w in phrase_words if len(w) >= 5}
    if len(distinctive) < MIN_MATCHING_WORDS:
        return None
    best_score, best_pos = 0, None
    for i in range(0, len(words) - MATCH_WINDOW_WORDS + 1):
        window = words[i:i + MATCH_WINDOW_WORDS]
        score = len(distinctive & set(window))
        if score > best_score:
            best_score, best_pos = score, i
    if best_score < MIN_MATCHING_WORDS:
        return None
    return times[best_pos]


def find_duplicate_groups(blocks):
    groups = {}
    for idx, block in enumerate(blocks):
        stripped = block.strip()
        if len(stripped) < DUPLICATE_BLOCK_MIN_CHARS:
            continue
        m = BLOCK_TS_RE.match(stripped)
        if not m:
            continue
        key = SPEAKER_PREFIX_RE.sub("", stripped, count=1)
        groups.setdefault(key, []).append((idx, ts_to_seconds(m.group(1)), stripped))
    return {k: v for k, v in groups.items() if len(v) > 1}


def dedupe(video_id, apply_changes=False):
    episode = _load_episode(video_id)
    ep_dir = EPISODES_DIR / episode_path(episode)
    raw_path = ep_dir / "raw.md"
    fields, body = read_frontmatter_body(raw_path)
    blocks = body.split("\n\n")

    dup_groups = find_duplicate_groups(blocks)
    if not dup_groups:
        print(f"{video_id}: no duplicate blocks found")
        return

    print(f"{video_id}: {len(dup_groups)} duplicate group(s), fetching captions...")
    vtt_path = fetch_captions(video_id, "ms") or fetch_captions(video_id, "en")
    if not vtt_path:
        print(f"{video_id}: no captions available, cannot cross-check -- skipping")
        return
    words, times = parse_caption_words(vtt_path.read_text(encoding="utf-8"))

    to_remove = set()
    for key, occurrences in dup_groups.items():
        content_words = re.sub(r"[^\w\s]", " ", key.lower()).split()
        mid = len(content_words) // 2
        phrase = content_words[mid:mid + 20]
        true_ts = find_phrase_timestamp(words, times, phrase)
        if true_ts is None:
            print(f"  phrase not found in captions, leaving {len(occurrences)} occurrences as-is")
            continue
        best_idx = min(occurrences, key=lambda o: abs(o[1] - true_ts))[0]
        kept_ts = next(o[1] for o in occurrences if o[0] == best_idx)
        removed_ts = [o[1] for o in occurrences if o[0] != best_idx]
        for idx, ts, _ in occurrences:
            if idx != best_idx:
                to_remove.add(idx)
        print(f"  caption confirms real timestamp ~{true_ts}s -- keeping block at {kept_ts}s, "
              f"removing fabricated copies at {removed_ts}")

    if not to_remove:
        print(f"{video_id}: nothing to remove")
        return

    removed_chars = sum(len(blocks[i]) for i in to_remove)
    new_body = "\n\n".join(b for i, b in enumerate(blocks) if i not in to_remove)
    print(f"{video_id}: removing {len(to_remove)} block(s), {removed_chars} chars")
    if apply_changes:
        raw_path.write_text(frontmatter_md(fields, "# Raw Transcript\n\n" + new_body), encoding="utf-8")
        print(f"{video_id}: wrote {raw_path}")
    else:
        print(f"{video_id}: dry run, not writing (pass --apply to write)")


if __name__ == "__main__":
    dedupe(sys.argv[1], apply_changes="--apply" in sys.argv)
