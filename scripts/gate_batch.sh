#!/bin/bash
# Regenerate several episodes' rewrites, each behind gate_rewrite.py's promote-or-restore
# check. Unlike regenerate_rewrites.sh this cannot leave an episode worse than it started:
# a candidate that loses content is discarded and the incumbent is copied back.
#
# Separate OS PROCESSES, not threads, for the same reason as regenerate_rewrites.sh:
# lib_claude_rewrite keeps the current model in module-level state and threads race on it.
# Six at a time is that script's measured sweet spot -- 33 min for six in parallel against
# 26 min each in series.
#
# Tags for ep01-ep06 MUST be disambiguated (ep03:bakar / ep03:berhenti); both shows have
# those numbers and they are different episodes. gate_rewrite.py refuses an ambiguous tag
# rather than guessing, so a missing suffix fails fast instead of rewriting the wrong file.
#
# MANDATORY afterwards, once, because the metadata stage rewrites hosts/guests and reverts
# labels to "Rafizi Ramli" on every run:
#   python scripts/rebuild_roster.py --write
#   python scripts/normalize_speaker_labels.py --write
#   python scripts/build_episode_index.py
#   python scripts/qa_check.py
#
# Usage:  bash scripts/gate_batch.sh ep14 ep02:berhenti ep04:bakar
set -u
PAR=${PAR:-6}
mkdir -p data/_gatelogs

run_one() {
  ep="$1"
  safe=$(echo "$ep" | tr ':' '-')
  echo "[$ep] start $(date +%H:%M:%S)"
  python scripts/gate_rewrite.py "$ep" --engine claude > "data/_gatelogs/${safe}.log" 2>&1
  rc=$?
  verdict=$(grep -E "KEPT candidate|RESTORED incumbent" "data/_gatelogs/${safe}.log" | tail -1)
  echo "[$ep] done $(date +%H:%M:%S) rc=$rc ${verdict:-NO VERDICT LINE}"
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
echo "verdicts:"
grep -hE "KEPT candidate|RESTORED incumbent" data/_gatelogs/*.log | sort | uniq -c
