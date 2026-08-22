"""Run transcribe_episode over episodes in data/manifest.json, skipping ones already done.
Commits each episode locally as it completes (no push).

Usage:
  python scripts/batch_process.py                       # all episodes, both phases
  python scripts/batch_process.py --stage raw            # raw transcription only
  python scripts/batch_process.py --stage rewrite         # rewrite/translate/metadata only (raw.md must already exist)
  python scripts/batch_process.py --force                # redo existing files
  python scripts/batch_process.py --engine local          # raw stage via local ASR fallback (see lib_local_asr.py)
  python scripts/batch_process.py --rewrite-engine claude  # rewrite stage via Claude fallback (see lib_claude_rewrite.py)
  python scripts/batch_process.py ID1 ID2 ID3            # only these video IDs
"""
import json
import subprocess
import sys
import traceback
from pathlib import Path

from transcribe_episode import process

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"


def commit_episode(out_dir, title, stage):
    subprocess.run(["git", "add", str(out_dir), str(MANIFEST_PATH)], cwd=ROOT, check=True)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if staged.returncode == 0:
        return  # nothing new to commit (e.g. was skipped, already committed)
    label = {"raw": "raw transcript", "rewrite": "interview rewrite", "all": "transcript"}[stage]
    subprocess.run(["git", "commit", "-m", f"Add {label}: {title}"], cwd=ROOT, check=True)


if __name__ == "__main__":
    argv = sys.argv[1:]
    # Flag values (e.g. "local" in "--engine local") don't start with "--", so
    # they must be explicitly excluded below -- otherwise they leak into the
    # positional video-id filter and silently match zero episodes.
    skip_indices = set()
    force = "--force" in argv
    if force:
        skip_indices.add(argv.index("--force"))
    stage = "all"
    if "--stage" in argv:
        idx = argv.index("--stage")
        stage = argv[idx + 1]
        skip_indices.update({idx, idx + 1})
    engine = "gemini"
    if "--engine" in argv:
        idx = argv.index("--engine")
        engine = argv[idx + 1]
        skip_indices.update({idx, idx + 1})
    rewrite_engine = "gemini"
    if "--rewrite-engine" in argv:
        idx = argv.index("--rewrite-engine")
        rewrite_engine = argv[idx + 1]
        skip_indices.update({idx, idx + 1})
    args = [a for i, a in enumerate(argv) if i not in skip_indices]

    episodes = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    episodes.sort(key=lambda ep: ep["upload_date"])  # oldest (Ep 1) first
    if args:
        wanted = set(args)
        episodes = [ep for ep in episodes if ep["video_id"] in wanted]

    for i, ep in enumerate(episodes, 1):
        print(f"\n### episode {i}/{len(episodes)}: {ep['title']} ###")
        try:
            out_dir = process(ep["video_id"], force=force, stage=stage, engine=engine, rewrite_engine=rewrite_engine)
            if out_dir:
                commit_episode(out_dir, ep["title"], stage)
        except Exception as e:
            print(f"FAILED {ep['video_id']}: {e}", file=sys.stderr)
            traceback.print_exc()
