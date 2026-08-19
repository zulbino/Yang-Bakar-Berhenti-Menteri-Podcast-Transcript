"""Process a single episode from data/manifest.json into episodes/<slug>/raw.md and interview.md.

Usage: python scripts/transcribe_episode.py <video_id> [--force]
"""
import json
import sys
from pathlib import Path

from common import chunk_windows, episode_slug, frontmatter_md, human_duration
import lib_gemini

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"
EPISODES_DIR = ROOT / "episodes"
CHUNK_SECONDS = 1200  # 20 min per chunk, safely under Gemini's ~8k output token cap


def load_episode(video_id):
    episodes = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for ep in episodes:
        if ep["video_id"] == video_id:
            return ep
    raise SystemExit(f"video_id {video_id} not found in manifest")


def process(video_id, force=False):
    episode = load_episode(video_id)
    slug = episode_slug(episode)
    out_dir = EPISODES_DIR / slug
    raw_path = out_dir / "raw.md"
    interview_path = out_dir / "interview.md"
    interview_en_path = out_dir / "interview-en.md"
    interview_ms_path = out_dir / "interview-ms.md"

    if not force and all(p.exists() for p in (raw_path, interview_path, interview_en_path, interview_ms_path)):
        print(f"skip {slug} (already processed, use --force to redo)")
        return out_dir

    print(f"=== {slug} ===")
    client = lib_gemini.get_client()

    duration = episode["duration_seconds"]
    windows = list(chunk_windows(duration, CHUNK_SECONDS))
    raw_chunks = []
    clean_chunks = []
    en_chunks = []
    ms_chunks = []
    for i, (start, end) in enumerate(windows, 1):
        print(f"[{i}/{len(windows)}] transcribing {start}s-{end}s ...")
        raw_text = lib_gemini.transcribe_raw_chunk(client, episode["youtube_url"], start, end)
        raw_chunks.append(raw_text)
        print(f"[{i}/{len(windows)}] rewriting to newspaper style (mixed) ...")
        clean_text = lib_gemini.rewrite_clean_chunk(client, raw_text)
        clean_chunks.append(clean_text)
        print(f"[{i}/{len(windows)}] translating to English ...")
        en_chunks.append(lib_gemini.translate_chunk(client, clean_text, "English"))
        print(f"[{i}/{len(windows)}] translating to Bahasa Melayu ...")
        ms_chunks.append(lib_gemini.translate_chunk(client, clean_text, "Bahasa Melayu"))

    full_raw = "\n\n".join(raw_chunks)
    full_clean = "\n\n".join(clean_chunks)
    full_en = "\n\n".join(en_chunks)
    full_ms = "\n\n".join(ms_chunks)

    print("extracting metadata (hosts/guests/summary/topics) ...")
    meta = lib_gemini.extract_metadata(client, full_clean)

    out_dir.mkdir(parents=True, exist_ok=True)

    common_fields = {
        "title": episode["title"],
        "video_id": episode["video_id"],
        "youtube_url": episode["youtube_url"],
        "channel": episode["channel"],
        "publish_date": f"{episode['upload_date'][0:4]}-{episode['upload_date'][4:6]}-{episode['upload_date'][6:8]}",
        "duration_seconds": episode["duration_seconds"],
        "duration": human_duration(episode["duration_seconds"]),
        "view_count": episode["view_count"],
        "hosts": meta["hosts"],
        "guests": meta["guests"],
    }

    raw_fields = dict(common_fields)
    raw_fields["note"] = "Raw, lightly-cleaned transcript straight from audio. See interview.md for the polished newspaper-style rewrite."
    raw_path.write_text(frontmatter_md(raw_fields, "# Raw Transcript\n\n" + full_raw), encoding="utf-8")

    interview_common = dict(common_fields)
    interview_common["topics"] = meta["topics"]
    interview_common["summary"] = meta["summary"]

    interview_fields = dict(interview_common)
    interview_fields["language"] = "mixed"
    interview_fields["note"] = "Polished newspaper-style Q&A rewrite, kept in the original mixed English/Bahasa Melayu (closest to how it was actually spoken). See raw.md for the unedited transcript, or interview-en.md / interview-ms.md for single-language versions."
    interview_path.write_text(frontmatter_md(interview_fields, "# Interview\n\n" + full_clean), encoding="utf-8")

    en_fields = dict(interview_common)
    en_fields["language"] = "en"
    en_fields["note"] = "Full English translation of interview.md (the mixed-language newspaper-style rewrite)."
    interview_en_path.write_text(frontmatter_md(en_fields, "# Interview (English)\n\n" + full_en), encoding="utf-8")

    ms_fields = dict(interview_common)
    ms_fields["language"] = "ms"
    ms_fields["note"] = "Terjemahan penuh Bahasa Melayu bagi interview.md (versi gaya akhbar dwibahasa)."
    interview_ms_path.write_text(frontmatter_md(ms_fields, "# Interview (Bahasa Melayu)\n\n" + full_ms), encoding="utf-8")

    print(f"wrote {raw_path}")
    print(f"wrote {interview_path}")
    print(f"wrote {interview_en_path}")
    print(f"wrote {interview_ms_path}")
    return out_dir


if __name__ == "__main__":
    video_id = sys.argv[1]
    force = "--force" in sys.argv
    process(video_id, force=force)
