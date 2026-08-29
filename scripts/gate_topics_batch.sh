#!/bin/bash
# Re-extract `topics:` for many episodes, each behind gate_topics.py's promote-or-restore
# check. Nothing is overwritten unless it covers more of the episode's own chapter markers.
#
# Separate OS PROCESSES, same reason as gate_batch.sh: lib_claude_rewrite keeps the current
# model in module-level state and threads race on it.
#
# One metadata call reads the whole transcript, so this is minutes per episode, not seconds.
#
# AFTERWARDS:
#   python scripts/build_topic_index.py     # TOPICS.md + the README pointer
#   python scripts/qa_check.py
#
# Usage:  bash scripts/gate_topics_batch.sh ep35 ep29 ep37
#         bash scripts/gate_topics_batch.sh --all
set -u
PAR=${PAR:-6}
mkdir -p data/_topiclogs

if [ "${1:-}" = "--all" ]; then
  set -- $(python - <<'PY'
import re, sys
from pathlib import Path
sys.path.insert(0, "scripts")
from build_topic_index import episodes
# Worst coverage first, so the episodes that need it most land even if the run is cut short.
from gate_topics import coverage
from build_topic_index import segments_by_video
segs = segments_by_video()
rows = []
for _, tag, _, vid, d, topics in episodes():
    cov, total = coverage(topics, segs.get(vid, []))
    rows.append(((cov / total) if total else 9, len(topics), tag.split()[-1]))
rows.sort()
print(" ".join(t for _, _, t in rows))
PY
)
fi

run_one() {
  ep="$1"
  echo "[$ep] start $(date +%H:%M:%S)"
  python scripts/gate_topics.py "$ep" --write > "data/_topiclogs/${ep}.log" 2>&1
  rc=$?
  v=$(grep -E "PROMOTE|REJECT" "data/_topiclogs/${ep}.log" | tail -1)
  echo "[$ep] done $(date +%H:%M:%S) rc=$rc ${v:-NO VERDICT}"
}

n=0
for ep in "$@"; do
  run_one "$ep" &
  n=$((n + 1))
  if [ "$n" -ge "$PAR" ]; then wait; n=0; fi
done
wait
echo "==== all done $(date +%H:%M:%S) ===="
echo
grep -hoE "PROMOTE: chapters [0-9]+/[0-9]+ -> [0-9]+/[0-9]+, lines [0-9]+ -> [0-9]+|REJECT: [a-z ]+" data/_topiclogs/*.log | sort | uniq -c | sort -rn | head -20
