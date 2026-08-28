"""Build data/manifest.json: full metadata for YBM podcast episodes >= 1 hour.

Snippets, teasers, and short-form clips in the playlist are excluded by
duration -- only full-length episodes are archived.
Re-run this to refresh metadata or pick up newly published episodes.
"""
import json
import subprocess
import sys
from pathlib import Path

PLAYLIST_URL = "https://www.youtube.com/playlist?list=PLqJKhYZQ8r9Uz3IPEh0lXpF17w3LQK62N"
MIN_DURATION_SECONDS = 3600
ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"


def flat_playlist_entries():
    proc = subprocess.run(
        ["python", "-m", "yt_dlp", "--flat-playlist", "--print", "%(duration)s\t%(id)s", PLAYLIST_URL],
        capture_output=True, text=True, check=True,
    )
    for line in proc.stdout.strip().splitlines():
        duration_str, video_id = line.split("\t")
        yield video_id, float(duration_str) if duration_str != "NA" else 0


def fetch_full_metadata_batch(video_ids):
    urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]
    proc = subprocess.run(
        ["python", "-m", "yt_dlp", "--dump-json", "--no-warnings", *urls],
        capture_output=True, text=True, check=True,
    )
    return [json.loads(line) for line in proc.stdout.strip().splitlines()]


def main():
    long_ids = [vid for vid, dur in flat_playlist_entries() if dur >= MIN_DURATION_SECONDS]
    print(f"{len(long_ids)} episodes >= {MIN_DURATION_SECONDS}s found in playlist", file=sys.stderr)

    episodes = []
    for meta in fetch_full_metadata_batch(long_ids):
        video_id = meta.get("id")
        episodes.append({
            "video_id": video_id,
            "title": meta.get("title"),
            "youtube_url": f"https://www.youtube.com/watch?v={video_id}",
            "upload_date": meta.get("upload_date"),  # YYYYMMDD
            "duration_seconds": meta.get("duration"),
            "view_count": meta.get("view_count"),
            "channel": meta.get("channel"),
            "description": meta.get("description"),
        })

    # MERGE, never overwrite. The playlist is not an archive: an episode can be unlisted,
    # made private, or simply not returned by a flaky fetch, and this script used to just
    # write whatever it got. Re-running it on 2026-08-29 returned 66 instead of 67 and
    # silently dropped ep14 (uboskXAZBfs), whose transcript is published in this repo --
    # the manifest is what every other tool resolves a tag against, so losing a row here
    # orphans a whole episode with a clean exit code.
    existing = []
    if MANIFEST_PATH.exists():
        existing = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    fetched = {e["video_id"]: e for e in episodes}
    merged, seen = [], set()
    for old in existing:
        vid = old["video_id"]
        seen.add(vid)
        merged.append(fetched.get(vid, old))
    dropped = [e["video_id"] for e in existing if e["video_id"] not in fetched]
    added = [vid for vid in fetched if vid not in seen]
    merged.extend(fetched[vid] for vid in added)

    MANIFEST_PATH.parent.mkdir(exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(merged)} episodes to {MANIFEST_PATH} "
          f"({len(added)} new, {len(dropped)} kept from the previous manifest)",
          file=sys.stderr)
    for vid in dropped:
        print(f"  WARNING: {vid} is in the manifest but no longer in the playlist -- "
              f"kept. Check whether it was unlisted or the fetch was incomplete.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
