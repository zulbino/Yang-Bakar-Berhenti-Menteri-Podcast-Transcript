#!/bin/bash
# Separate OS processes, NOT threads: lib_claude_rewrite holds the current model in
# module-level state, so threads would race on it (ARCHITECTURE.md). Six at a time --
# measured at 33 min for six in parallel against 26 min *each* in series.
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
  echo "[$ep] video_id=$vid starting $(date +%H:%M:%S)"
  python - "$vid" "$ep" <<'PY' > "_rw_${ep}.log" 2>&1
import sys, os
sys.path.insert(0, "scripts")
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
import transcribe_episode as T
T.process_rewrite(sys.argv[1], force=True, rewrite_engine="claude")
PY
  echo "[$ep] finished $(date +%H:%M:%S) rc=$?"
}
BATCH1="$1"; BATCH2="$2"
for ep in $BATCH1; do run_one "$ep" & done
wait
echo "==== batch 1 done $(date +%H:%M:%S) ===="
for ep in $BATCH2; do run_one "$ep" & done
wait
echo "==== batch 2 done $(date +%H:%M:%S) ===="
