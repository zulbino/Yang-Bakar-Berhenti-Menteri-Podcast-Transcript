"""Process a single episode from data/manifest.json into episodes/<slug>/*.md.

Split into two phases so a failure in the rewrite/translate/metadata stage never
loses the (slow, audio-dependent) raw transcription:
  - raw phase:     download audio -> upload -> transcribe -> write raw.md
  - rewrite phase: read raw.md -> clean/EN/MS rewrite + metadata -> write interview*.md

Usage: python scripts/transcribe_episode.py <video_id> [--force] [--stage raw|rewrite|all]
       [--engine gemini|local] [--rewrite-engine gemini|claude]

--engine local runs the raw stage on-device (mesolitica/malaysian-whisper-medium-v2 +
VAD chunking, see lib_local_asr.py) instead of the Gemini API -- a fallback for when
Gemini access is unavailable (e.g. billing blocked). No speaker diarization. Only
affects the raw stage.

--rewrite-engine claude runs the rewrite stage (clean/EN/MS rewrite + metadata) via
the Claude API (see lib_claude_rewrite.py) instead of Gemini, same fallback reason.
Only affects the rewrite stage.
"""
import json
import sys
from pathlib import Path

from common import episode_path, episode_slug, frontmatter_md, human_duration, read_frontmatter_body
import lib_gemini
import yt_download

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"
EPISODES_DIR = ROOT / "episodes"
AUDIO_DIR = ROOT / "audio"


def load_episode(video_id):
    episodes = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for ep in episodes:
        if ep["video_id"] == video_id:
            return ep
    raise SystemExit(f"video_id {video_id} not found in manifest")


def episode_common_fields(episode):
    duration_seconds = episode["duration_seconds"]
    return {
        "title": episode["title"],
        "video_id": episode["video_id"],
        "youtube_url": episode["youtube_url"],
        "channel": episode["channel"],
        "publish_date": f"{episode['upload_date'][0:4]}-{episode['upload_date'][4:6]}-{episode['upload_date'][6:8]}",
        "duration_seconds": duration_seconds,
        "duration": human_duration(duration_seconds),
        "view_count": episode["view_count"],
    }


def process_raw(video_id, force=False, engine="gemini"):
    episode = load_episode(video_id)
    slug = episode_slug(episode)
    out_dir = EPISODES_DIR / episode_path(episode)
    raw_path = out_dir / "raw.md"

    if raw_path.exists() and not force:
        print(f"skip raw {slug} (already exists, use --force to redo)")
        return out_dir

    print(f"=== raw: {slug} ({engine}) ===")
    duration_human = human_duration(episode["duration_seconds"])

    AUDIO_DIR.mkdir(exist_ok=True)
    print("downloading audio ...")
    audio_path = yt_download.download_audio(video_id, AUDIO_DIR)

    if engine == "local":
        print("transcribing raw locally (mesolitica/malaysian-whisper-medium-v2) ...")
        import lib_local_asr
        full_raw = lib_local_asr.transcribe_raw_local(audio_path, episode["duration_seconds"])
        audio_path.unlink()
        note = ("Raw transcript from the local ASR fallback (no Gemini access), "
                "mesolitica/malaysian-whisper-medium-v2 with VAD chunking. No speaker "
                "diarization -- turns are not labeled by speaker. See interview.md for "
                "the polished newspaper-style rewrite.")
    else:
        client = lib_gemini.get_client()
        print("uploading audio to Gemini ...")
        audio_file = lib_gemini.upload_audio(client, audio_path)
        audio_path.unlink()
        print("transcribing raw ...")
        full_raw = lib_gemini.transcribe_raw(client, audio_file, duration_human, episode["duration_seconds"])
        note = "Raw, lightly-cleaned transcript straight from audio. See interview.md for the polished newspaper-style rewrite."

    out_dir.mkdir(parents=True, exist_ok=True)
    raw_fields = episode_common_fields(episode)
    raw_fields["note"] = note
    raw_path.write_text(frontmatter_md(raw_fields, "# Raw Transcript\n\n" + full_raw), encoding="utf-8")
    print(f"wrote {raw_path}")
    return out_dir


def process_rewrite(video_id, force=False, rewrite_engine="gemini"):
    episode = load_episode(video_id)
    slug = episode_slug(episode)
    out_dir = EPISODES_DIR / episode_path(episode)
    raw_path = out_dir / "raw.md"
    interview_path = out_dir / "interview.md"
    interview_en_path = out_dir / "interview-en.md"
    interview_ms_path = out_dir / "interview-ms.md"

    if not raw_path.exists():
        raise SystemExit(f"{raw_path} missing -- run the raw phase first")

    if not force and all(p.exists() for p in (interview_path, interview_en_path, interview_ms_path)):
        print(f"skip rewrite {slug} (already exists, use --force to redo)")
        return out_dir

    print(f"=== rewrite: {slug} ({rewrite_engine}) ===")
    if rewrite_engine == "claude":
        import lib_claude_rewrite
        engine = lib_claude_rewrite
    else:
        engine = lib_gemini
    client = engine.get_client()
    _, full_raw = read_frontmatter_body(raw_path)

    print("rewriting to newspaper style (mixed) ...")
    full_clean = engine.rewrite_clean(client, full_raw)
    print("translating to English ...")
    full_en = engine.translate(client, full_clean, "English")
    print("translating to Bahasa Melayu ...")
    full_ms = engine.translate(client, full_clean, "Bahasa Melayu")
    print("extracting metadata (hosts/guests/summary/topics) ...")
    meta = engine.extract_metadata(client, full_clean)

    interview_common = episode_common_fields(episode)
    interview_common["hosts"] = meta["hosts"]
    interview_common["guests"] = meta["guests"]
    interview_common["topics"] = meta["topics"]
    interview_common["summary"] = meta["summary"]

    mixed_fields = dict(interview_common)
    mixed_fields["language"] = "mixed"
    mixed_fields["note"] = "Polished newspaper-style Q&A rewrite, kept in the original mixed English/Bahasa Melayu (closest to how it was actually spoken). See raw.md for the unedited transcript, or interview-en.md / interview-ms.md for single-language versions."
    interview_path.write_text(frontmatter_md(mixed_fields, "# Interview\n\n" + full_clean), encoding="utf-8")

    en_fields = dict(interview_common)
    en_fields["language"] = "en"
    en_fields["note"] = "Full English translation of interview.md (the mixed-language newspaper-style rewrite)."
    interview_en_path.write_text(frontmatter_md(en_fields, "# Interview (English)\n\n" + full_en), encoding="utf-8")

    ms_fields = dict(interview_common)
    ms_fields["language"] = "ms"
    ms_fields["note"] = "Terjemahan penuh Bahasa Melayu bagi interview.md (versi gaya akhbar dwibahasa)."
    interview_ms_path.write_text(frontmatter_md(ms_fields, "# Interview (Bahasa Melayu)\n\n" + full_ms), encoding="utf-8")

    print(f"wrote {interview_path}")
    print(f"wrote {interview_en_path}")
    print(f"wrote {interview_ms_path}")
    return out_dir


def process(video_id, force=False, stage="all", engine="gemini", rewrite_engine="gemini"):
    out_dir = None
    if stage in ("raw", "all"):
        out_dir = process_raw(video_id, force=force, engine=engine)
    if stage in ("rewrite", "all"):
        out_dir = process_rewrite(video_id, force=force, rewrite_engine=rewrite_engine)
    return out_dir


if __name__ == "__main__":
    video_id = sys.argv[1]
    force = "--force" in sys.argv
    stage = "all"
    if "--stage" in sys.argv:
        stage = sys.argv[sys.argv.index("--stage") + 1]
    engine = "gemini"
    if "--engine" in sys.argv:
        engine = sys.argv[sys.argv.index("--engine") + 1]
    rewrite_engine = "gemini"
    if "--rewrite-engine" in sys.argv:
        rewrite_engine = sys.argv[sys.argv.index("--rewrite-engine") + 1]
    process(video_id, force=force, stage=stage, engine=engine, rewrite_engine=rewrite_engine)
