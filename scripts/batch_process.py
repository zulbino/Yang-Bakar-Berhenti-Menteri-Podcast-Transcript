"""Run transcribe_episode over episodes in data/manifest.json, skipping ones already done.
Commits each episode locally as it completes (no push).

Usage:
  python scripts/batch_process.py                       # all episodes
  python scripts/batch_process.py --force                # all episodes, redo existing
  python scripts/batch_process.py ID1 ID2 ID3            # only these video IDs
"""
import json
import subprocess
import sys
from pathlib import Path

from transcribe_episode import process

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"


def commit_episode(out_dir, title):
    subprocess.run(["git", "add", str(out_dir), str(MANIFEST_PATH)], cwd=ROOT, check=True)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if staged.returncode == 0:
        return  # nothing new to commit (e.g. was skipped, already committed)
    subprocess.run(["git", "commit", "-m", f"Add transcript: {title}"], cwd=ROOT, check=True)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    episodes = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if args:
        wanted = set(args)
        episodes = [ep for ep in episodes if ep["video_id"] in wanted]

    for i, ep in enumerate(episodes, 1):
        print(f"\n### episode {i}/{len(episodes)}: {ep['title']} ###")
        try:
            out_dir = process(ep["video_id"], force=force)
            if out_dir:
                commit_episode(out_dir, ep["title"])
        except Exception as e:
            print(f"FAILED {ep['video_id']}: {e}", file=sys.stderr)
