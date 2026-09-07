"""Offline check of reconcile_mai_speakers grouping: no audio, no network, synthetic vectors.

Run it after touching group(), name_groups() or relabelled_turns(). The cases are the three
things that actually went wrong on ep62: a speaker whose number changes between chunks, one
person MAI split into two clusters inside a single chunk, and a chunk boundary cutting a turn
in half.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reconcile_mai_speakers as R

rng = np.random.default_rng(0)


def person(base, jitter=0.05):
    v = base + rng.normal(0, jitter, base.shape)
    return v / np.linalg.norm(v)


dim = 32
A = rng.normal(0, 1, dim); A /= np.linalg.norm(A)
B = rng.normal(0, 1, dim); B /= np.linalg.norm(B)
C = rng.normal(0, 1, dim); C /= np.linalg.norm(C)

# 3 chunks. A is speaker 0 in chunks 0 and 2 but speaker 1 in chunk 1; B swaps with him.
# C only shows up in chunk 2, as a guest.
truth = {(0, 0): A, (0, 1): B, (1, 0): B, (1, 1): A, (2, 0): A, (2, 1): C}
vectors = {k: person(v) for k, v in truth.items()}
keys = sorted(vectors)
minutes = {(0, 0): 20, (0, 1): 8, (1, 0): 7, (1, 1): 21, (2, 0): 18, (2, 1): 9}

groups, pairs = R.group(keys, vectors, 0.70)
print("groups:", [[f"c{c}s{s}" for c, s in g] for g in groups])
assert len(groups) == 3, groups
by_size = sorted(groups, key=lambda g: -sum(minutes[k] for k in g))
assert by_size[0] == [(0, 0), (1, 1), (2, 0)], by_size[0]      # A joined across chunks
assert sorted(by_size[1]) == [(0, 1), (1, 0)], by_size[1]      # B joined
assert by_size[2] == [(2, 1)], by_size[2]                      # C alone

# Same-chunk clusters must never merge even if the vectors are near-identical.
same = {(0, 0): A, (0, 1): person(A, 0.001), (1, 0): person(A, 0.001)}
g2, _ = R.group(sorted(same), same, 0.70)
assert all(len({m[0] for m in members}) == len(members) for members in g2), g2
print("same-chunk constraint holds:", [[f"c{c}s{s}" for c, s in g] for g in g2])

# Naming: reference A is the cast, C is not.
refs = {"Rafizi": A, "Haziq": B}
named, report = R.name_groups(groups, vectors, minutes, refs)
for row in report:
    print(f"  {row['label']:10} {row['minutes']:5.1f} min  {row['scores']}  {row['verdict']}")
assert named[(0, 0)] == "Rafizi" and named[(1, 1)] == "Rafizi"
assert named[(0, 1)] == "Haziq"
assert named[(2, 1)].startswith("Speaker"), named[(2, 1)]

# Turn relabelling: a chunk boundary splitting one person's turn must weld back together.
turns = [
    {"chunk": 0, "speaker": 0, "offset_ms": 0, "end_ms": 5000, "text": "satu"},
    {"chunk": 0, "speaker": 1, "offset_ms": 5000, "end_ms": 9000, "text": "dua"},
    {"chunk": 0, "speaker": 0, "offset_ms": 9000, "end_ms": 1800000, "text": "tiga"},
    {"chunk": 1, "speaker": 1, "offset_ms": 1800000, "end_ms": 1805000, "text": "empat"},
    {"chunk": 1, "speaker": 0, "offset_ms": 1805000, "end_ms": 1809000, "text": "lima"},
    {"chunk": 2, "speaker": 1, "offset_ms": 3600000, "end_ms": 3605000, "text": "enam"},
    {"chunk": 9, "speaker": 4, "offset_ms": 3605000, "end_ms": 3609000, "text": "hantu"},
]
final = R.relabelled_turns(turns, named)
rendered = [(t["label"], t["text"]) for t in final]
print("turns:", rendered)
assert rendered[0] == ("Rafizi", "satu")
assert rendered[1] == ("Haziq", "dua")
assert rendered[2] == ("Rafizi", "tiga empat")     # welded across the chunk boundary
assert rendered[3] == ("Haziq", "lima")
assert rendered[4][0] == "Speaker 1"
assert rendered[5][0] == "Speaker ?"

# Spans: sub-2s turns and missing offsets drop out.
spans = R.clusters_of([
    {"chunk": 0, "speaker": 0, "offset_ms": 0, "end_ms": 5000, "text": "x"},
    {"chunk": 0, "speaker": 0, "offset_ms": 5000, "end_ms": 6000, "text": "y"},
    {"chunk": 0, "speaker": 1, "offset_ms": None, "end_ms": None, "text": "z"},
])
assert spans == {(0, 0): [(0.0, 5.0)]}, spans
print("clusters_of drops short and unstamped turns")
print("\nALL PASS")
