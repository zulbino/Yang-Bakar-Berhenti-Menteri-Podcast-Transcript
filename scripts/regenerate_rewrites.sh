#!/bin/bash
# Regenerate the rewrite stage (interview.md / -en / -ms + metadata) for named episodes,
# after raw.md's speaker attribution has changed.
#
# Separate OS PROCESSES, not threads: lib_claude_rewrite keeps the current model in
# module-level state, so threads race on it. Measured at 33 min for six in parallel
# against 26 min *each* in series, so six at a time is the sweet spot.
#
# A run is NOT finished when the first output file's mtime changes -- process_rewrite
# writes all three files at the end. Check whether the process is alive, not the
# timestamp. Reading too early once produced a committed conclusion that a run had
# failed when it had not (ENGINEERING_LOG 1.31).
#
# MANDATORY afterwards, because the metadata stage rewrites hosts/guests and reverts
# labels to "Rafizi Ramli" on every run:
#   python scripts/rebuild_roster.py --write
#   python scripts/normalize_speaker_labels.py --write
#   python scripts/build_episode_index.py
#   python scripts/qa_check.py
#
# Usage:  bash scripts/regenerate_rewrites.sh ep45 ep44 ep43
set -u
run_one() {
  ep="$1"
  vid=$(python - "$ep" <<'PY'
import re, sys, glob, os
tag = sys.argv[1]
for d in sorted(glob.glob('episodes/*/*')):
    if re.search(r'-' + tag + r'-', os.path.basename(d)) and 'bakar' not in d:
        t = open(os.path.join(d, 'interview.md'), encoding='utf-8').read()
        print(re.search(r'video_id:\s*(\S+)', t).group(1)); break
PY
)
  echo "[$ep] video_id=$vid start $(date +%H:%M:%S)"
  python - "$vid" <<'PY' > "rewrite_${ep}.log" 2>&1
import sys, os
sys.path.insert(0, "scripts")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
import transcribe_episode as T
T.process_rewrite(sys.argv[1], force=True, rewrite_engine="claude")
PY
  echo "[$ep] done $(date +%H:%M:%S) rc=$? (see rewrite_${ep}.log)"
}
n=0
for ep in "$@"; do
  run_one "$ep" &
  n=$((n + 1))
  if [ "$n" -ge 6 ]; then wait; n=0; fi
done
wait
echo "==== all done $(date +%H:%M:%S) ===="
