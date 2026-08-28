#!/bin/bash
for ep in ep21 ep24 ep25 ep29 ep39 ep42 ep52 ep60 ep46 ep23 ep55; do
  echo "############ $ep $(date +%H:%M:%S) ############"
  python scripts/reattribute_blocks.py "$ep" --write 2>&1 \
    | grep -vE "Warning|warn|TensorFloat|torch|>>>|See http|std = |re-cutting"
done
echo "############ BATCH2 DONE $(date +%H:%M:%S) ############"
