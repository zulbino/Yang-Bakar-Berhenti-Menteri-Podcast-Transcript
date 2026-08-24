"""Cross-check raw.md speaker labels against the real audio via Gemini's
independent audio understanding, instead of relying purely on manual
eyeballing.

Blind spot-check, same method validated on ep60 (see
project_speaker_attribution_risk_confirmed memory): a short audio clip is cut
around each sampled turn and sent to Gemini with NO transcript given, then the
model is asked how many distinct voices it hears and whether anyone is named
or addressed by name -- that independent read is reported next to the label
raw.md actually claims, for manual comparison. This flags disagreements for
review, it does not auto-correct raw.md.

Usage:
  python scripts/verify_speakers.py <video_id> [--label "Farhan Iqbal"] [--samples N]

Without --label, samples N turns spread evenly across the whole episode. With
--label, samples up to N occurrences of that exact speaker label, spread
evenly across its occurrences -- useful for auditing one suspect name across a
long episode instead of eyeballing every line it appears on.
"""
import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

from google.genai import types

from common import episode_path, episode_slug, read_frontmatter_body, retry
import lib_gemini
import yt_download
from yt_download import _FFMPEG_FALLBACK

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"
EPISODES_DIR = ROOT / "episodes"
AUDIO_DIR = ROOT / "audio"
OUT_PATH = ROOT / "data" / "speaker_verification.json"

BLOCK_RE = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]\s*([^:\n]+):\s*(.*)", re.S)
# Long enough to hear the boundary between the previous speaker, the sampled
# turn, and whatever follows -- useful signal for whether this really is a
# brief interjection or a sustained exchange. Short enough to keep audio-call
# cost trivial (~a few hundred tokens per clip).
CLIP_PADDING_BEFORE_SECONDS = 3
CLIP_DURATION_SECONDS = 25

VERIFY_PROMPT = """Listen to this short audio clip from a Malaysian political podcast/interview. Without being told who is speaking, answer only from what you hear:
1. How many distinct voices/speakers talk in this clip?
2. Roughly transcribe or summarize what is said (English or Bahasa Melayu, mixed is fine).
3. Is anyone in the clip named, addressed by name, or does anyone refer to themselves by name? Quote the exact phrase if so.
4. For each distinct speaker, briefly describe voice pitch, tone, and speaking style, specific enough that the same voice could be recognized from this description alone on a different clip.

Output as JSON."""

VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "speaker_count": {"type": "integer"},
        "transcript_guess": {"type": "string"},
        "named_mentions": {"type": "array", "items": {"type": "string"}},
        "voice_descriptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["speaker_count", "transcript_guess", "named_mentions", "voice_descriptions"],
}


def _ffmpeg_exe():
    return shutil.which("ffmpeg") or str(_FFMPEG_FALLBACK)


def ts_to_seconds(ts):
    parts = [int(p) for p in ts.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return h * 3600 + m * 60 + s


def load_episode(video_id):
    episodes = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for ep in episodes:
        if ep["video_id"] == video_id:
            return ep
    raise SystemExit(f"video_id {video_id} not found in manifest")


def parse_turns(body):
    turns = []
    for block in body.split("\n\n"):
        block = block.strip()
        m = BLOCK_RE.match(block)
        if not m:
            continue
        turns.append({"ts": ts_to_seconds(m.group(1)), "speaker": m.group(2).strip(), "text": m.group(3).strip()})
    return turns


def pick_samples(turns, label, count):
    candidates = [t for t in turns if t["speaker"] == label] if label else turns
    if len(candidates) <= count:
        return candidates
    step = len(candidates) / count
    return [candidates[int(i * step)] for i in range(count)]


def extract_clip(audio_path, start_seconds, out_path):
    clip_start = max(0, start_seconds - CLIP_PADDING_BEFORE_SECONDS)
    subprocess.run(
        [
            _ffmpeg_exe(), "-y", "-ss", str(clip_start), "-t", str(CLIP_DURATION_SECONDS),
            "-i", str(audio_path), "-ar", "16000", "-ac", "1", "-f", "wav", str(out_path),
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def verify_clip(client, clip_path):
    audio_file = lib_gemini.upload_audio(client, clip_path, mime_type="audio/wav")
    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=VERIFY_SCHEMA, safety_settings=lib_gemini.SAFETY_SETTINGS)

    def call():
        resp = lib_gemini.generate_content(client, [audio_file, VERIFY_PROMPT], config)
        return json.loads(lib_gemini._text(resp))

    return retry(call, max_attempts=5, base_delay=15, what="speaker verification")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video_id")
    parser.add_argument("--label", default=None, help="only sample turns with this exact speaker label")
    parser.add_argument("--samples", type=int, default=8)
    args = parser.parse_args()

    episode = load_episode(args.video_id)
    slug = episode_slug(episode)
    raw_path = EPISODES_DIR / episode_path(episode) / "raw.md"
    _, body = read_frontmatter_body(raw_path)
    turns = parse_turns(body)
    samples = pick_samples(turns, args.label, args.samples)
    if not samples:
        raise SystemExit(f"no turns found for label={args.label!r} in {raw_path}")

    print(f"{slug}: sampling {len(samples)} turn(s)" + (f" labeled {args.label!r}" if args.label else ""))

    AUDIO_DIR.mkdir(exist_ok=True)
    audio_path = AUDIO_DIR / f"{args.video_id}.m4a"
    print("downloading audio ...")
    yt_download.download_audio(args.video_id, AUDIO_DIR)

    client = lib_gemini.get_client()
    existing = json.loads(OUT_PATH.read_text(encoding="utf-8")) if OUT_PATH.exists() else {}
    episode_results = existing.setdefault(slug, [])

    clip_path = AUDIO_DIR / f"_verify_clip_{args.video_id}.wav"
    for turn in samples:
        print(f"  [{turn['ts']}s] claimed={turn['speaker']!r} ...", flush=True)
        extract_clip(audio_path, turn["ts"], clip_path)
        try:
            verdict = verify_clip(client, clip_path)
        except Exception as e:
            print(f"    FAILED: {e}")
            continue
        print(f"    heard {verdict['speaker_count']} speaker(s); named: {verdict['named_mentions']}")
        episode_results.append({
            "claimed_ts": turn["ts"],
            "claimed_speaker": turn["speaker"],
            "claimed_text": turn["text"][:200],
            "verdict": verdict,
        })
        OUT_PATH.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")

    clip_path.unlink(missing_ok=True)
    audio_path.unlink(missing_ok=True)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
