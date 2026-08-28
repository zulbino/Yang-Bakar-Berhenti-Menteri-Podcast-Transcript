#!/bin/bash
# Re-cut a list of episodes with clustering.threshold, then score every resulting cluster
# against the host voiceprints. Sequential, because both stages want the whole GPU.
#
# Leaves raw.md carrying ANONYMOUS "SPEAKER_N" labels on purpose: naming is a judgement
# call on the voiceprint scores, and anything the voiceprint rates UNRESOLVABLE needs
# video frames (scripts/frames_at.py). Name them with scripts/relabel_speakers.py before
# committing -- an episode left anonymous is worse than one left alone.
#
# threshold=0.55 and NOT a speaker count: a count hint makes pyannote ignore the
# threshold entirely (ENGINEERING_LOG 1.36). 0.45 scores a lower collapse share and is
# worse, because it shatters a quiet speaker across clusters and makes him unnameable.
#
# DO NOT add ep26: its labels came from Gemini, not pyannote, and are already better than
# a re-cut would produce. Guard 2 caught that once already.
#
# Usage:  bash scripts/recut_sweep.sh ep21 ep27 ep31
set -u
export CUDA_VISIBLE_DEVICES=0
NOISE='warn|torch|re-enabled|>>>|See http|std =|^ *re-cutting|^$'
for ep in "$@"; do
  echo ""
  echo "################ $ep  $(date +%H:%M:%S) ################"
  python scripts/reattribute_blocks.py "$ep" --threshold=0.55 --write 2>&1 \
    | grep -viE "$NOISE" | tail -8
  echo "---- voiceprint $ep ----"
  python scripts/verify_speaker_voiceprint.py --episodes "$ep" 2>&1 \
    | grep -viE "$NOISE" | tail -12
done
echo ""
echo "################ all done $(date +%H:%M:%S) ################"
echo "raw.md files now hold SPEAKER_N labels -- name them before committing"
