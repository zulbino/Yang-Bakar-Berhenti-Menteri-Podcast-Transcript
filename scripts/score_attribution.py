"""Score any speaker labelling against the camera reference, and say WHERE it loses.

WHY A SEPARATE SCORER. DER on its own is misleading on this corpus and ranked the systems
wrongly the first time it was computed. Rafizi holds 95.5% of ep62's speaking time, so a
system can lose both co-hosts entirely and still post an excellent DER. This prints four
things instead of one number:

  DER split into missed / false alarm / confusion, because only confusion is attribution
  JER, which weights every speaker equally instead of by time
  per-speaker recall on the seconds EVERY system labels, so no column has its own denominator
  block mixing: how many transcript blocks hold more than one speaker, and how many
    seconds sit under the wrong name inside them

THREE TRAPS, each of which produced a wrong answer here before being fixed.

  1. GREEDY LABEL MAPPING FABRICATES RESULTS. Assigning each system label to the reference
     speaker it overlaps most lets two labels claim the same speaker, and whoever they
     should have covered then reads 0%. That reported MAI recalling 0% of Haziq when MAI
     had labelled 389 of his 457 seconds correctly. DER uses a maximum-weight matching;
     so does this.

  2. DIFFERENT DENOMINATORS ARE NOT COMPARABLE. Systems label different sets of seconds --
     pyannote leaves gaps, transcript blocks tile continuously. Per-speaker recall is
     computed only on seconds every system labels.

  3. A CONTINUOUSLY TILED TRANSCRIPT SCORES 0% MISSED BY CONSTRUCTION. raw.md's blocks run
     end to end, so it can never be charged for missing speech, and its DER flatters it for
     a reason that has nothing to do with accuracy. This is why the split matters.

  python scripts/score_attribution.py data/camera_ref_ep62.rttm --episode ep62
"""
import argparse
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

ROOT = Path(__file__).resolve().parent.parent


def per_second_rttm(path):
    out = {}
    for line in open(path):
        p = line.split()
        a, d = float(p[3]), float(p[4])
        for s in range(int(a), int(a + d)):
            out[s] = p[7].replace("_", " ")
    return out


def per_second_blocks(path):
    """A transcript block owns every second until the next block starts."""
    body = open(path, encoding="utf-8").read().split("# Raw Transcript", 1)[-1]
    bl = re.findall(r"^\[([\d:]+)\]\s*([^:\n]{0,40}?):\s*(.*)$", body, re.M)

    def sec(x):
        q = [int(i) for i in x.split(":")]
        return sum(v * 60 ** i for i, v in enumerate(reversed(q)))

    out, blocks = {}, []
    for i in range(len(bl) - 1):
        a, b = sec(bl[i][0]), sec(bl[i + 1][0])
        who = bl[i][1].strip().split(" (")[0]
        blocks.append((a, b, who, len(bl[i][2].split())))
        for t in range(a, b):
            out[t] = who
    return out, blocks


def per_second_triples(path):
    out = {}
    for a, b, who in json.loads(Path(path).read_text(encoding="utf-8")):
        for t in range(int(a), int(b)):
            out[t] = str(who)
    return out


def assign(ref, sysmap, keys):
    """Maximum-weight one-to-one map from system labels to reference speakers."""
    conf = defaultdict(Counter)
    for t in keys:
        conf[ref[t]][sysmap[t]] += 1
    refs = sorted(conf)
    syss = sorted({s for c in conf.values() for s in c})
    W = np.array([[conf[r].get(s, 0) for s in syss] for r in refs])
    ri, ci = linear_sum_assignment(-W)
    return conf, {syss[j]: refs[i] for i, j in zip(ri, ci)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reference", help="camera RTTM")
    ap.add_argument("--episode", help="episode tag, to score its raw.md")
    ap.add_argument("--rttm", action="append", default=[], metavar="NAME=PATH")
    ap.add_argument("--blocks", action="append", default=[], metavar="NAME=PATH")
    ap.add_argument("--triples", action="append", default=[], metavar="NAME=PATH")
    a = ap.parse_args()

    ref = per_second_rttm(a.reference)
    systems, blocks_of = {}, {}
    if a.episode:
        hits = glob.glob(str(ROOT / f"episodes/*/*{a.episode}*/raw.md"))
        if not hits:
            sys.exit(f"no raw.md for {a.episode}")
        systems["raw.md as shipped"], blocks_of["raw.md as shipped"] = per_second_blocks(hits[0])
    # rsplit, not split: system names legitimately contain "=" ("pyannote thr=0.55"),
    # and splitting on the first one turns the name into half a path.
    for spec, fn in ((a.rttm, per_second_rttm), (a.triples, per_second_triples)):
        for s in spec:
            n, p = s.rsplit("=", 1)
            systems[n] = fn(p)
    for s in a.blocks:
        n, p = s.rsplit("=", 1)
        systems[n], blocks_of[n] = per_second_blocks(p)
    if not systems:
        sys.exit("give at least one system: --episode, --rttm, --blocks or --triples")

    common = set(ref) & set.intersection(*(set(m) for m in systems.values()))
    names = sorted({v for v in ref.values()},
                   key=lambda n: -sum(1 for t in common if ref[t] == n))
    print(f"reference {Path(a.reference).name}: {len(ref)}s over {len(names)} speakers")
    print(f"scored on {len(common)}s labelled by every system   "
          + "  ".join(f"{n} {sum(1 for t in common if ref[t]==n)}s" for n in names))

    print(f"\n{'system':34}" + "".join(f"{n:>10}" for n in names) + f"{'confusion':>11}")
    for label, m in systems.items():
        conf, amap = assign(ref, m, common)
        cells = []
        for n in names:
            tot = sum(conf[n].values())
            hit = sum(v for s, v in conf[n].items() if amap.get(s) == n)
            cells.append(f"{hit/max(tot,1):.0%}")
        wrong = sum(v for r in conf for s, v in conf[r].items() if amap.get(s) != r)
        print(f"{label:34}" + "".join(f"{c:>10}" for c in cells)
              + f"{wrong/max(len(common),1):>10.1%}")

    # DER SPLIT INTO ITS THREE PARTS. One DER cannot tell a system that puts the wrong
    # name on speech from one that did not think there was speech there, and on this corpus
    # those rank differently: raw.md's blocks tile continuously so it scores 0% missed BY
    # CONSTRUCTION, which gives it the best DER in the table and the worst confusion.
    try:
        from pyannote.core import Annotation, Segment, Timeline
        from pyannote.metrics.diarization import DiarizationErrorRate, JaccardErrorRate
    except ImportError:
        print("\n(install pyannote.metrics for the DER split)")
        pass
    else:
        def to_ann(m):
            ann = Annotation(uri="x")
            run = None
            for t in sorted(m):
                if run and m[t] == run[2] and t == run[1] + 1:
                    run[1] = t
                else:
                    if run:
                        ann[Segment(run[0], run[1] + 1)] = run[2]
                    run = [t, t, m[t]]
            if run:
                ann[Segment(run[0], run[1] + 1)] = run[2]
            return ann

        # SCORED OVER THE WHOLE REFERENCE, not the intersection. Restricting to seconds
        # every system labels forces missed and false-alarm to zero by construction and
        # makes the split say nothing -- which is the exact failure the split exists to
        # expose. Each system is measured against everything the camera is sure about,
        # so a system that declines to label a second is charged for it.
        uem = Timeline(uri="x")
        for t in sorted(ref):
            uem.add(Segment(t, t + 1))
        uem = uem.support()
        ref_ann = to_ann(ref)
        print(f"\nover the full reference ({len(ref)}s), so silence counts against a system")
        print(f"{'system':34}{'DER':>8}{'JER':>8}{'missed':>9}{'falarm':>9}{'confus':>9}")
        for label, m in systems.items():
            hyp = to_ann(m)
            metric = DiarizationErrorRate(collar=0.0, skip_overlap=False)
            der = metric(ref_ann, hyp, uem=uem)
            c = metric[:]
            tot = c["total"] or 1
            jer = JaccardErrorRate(collar=0.0, skip_overlap=False)(ref_ann, hyp, uem=uem)
            print(f"{label:34}{der:>7.1%}{jer:>8.1%}{c['missed detection']/tot:>9.1%}"
                  f"{c['false alarm']/tot:>9.1%}{c['confusion']/tot:>9.1%}")

    for label, blocks in blocks_of.items():
        mixed = [b for b in blocks
                 if len({ref[t] for t in range(b[0], b[1]) if t in ref}) > 1]
        misplaced = Counter()
        for a0, b0, who, _ in mixed:
            for t in range(a0, b0):
                if t in ref and ref[t] != who:
                    misplaced[ref[t]] += 1
        durs = sorted(b[1] - b[0] for b in blocks)
        print(f"\n{label}: {len(blocks)} blocks, median {durs[len(durs)//2]}s, "
              f"longest {durs[-1]}s")
        print(f"  {len(mixed)} blocks ({len(mixed)/max(len(blocks),1):.0%}) hold more than "
              f"one speaker; {sum(misplaced.values())}s sit under the wrong name")
        for n, v in misplaced.most_common():
            print(f"    {n:10} {v:>5}s misplaced")


if __name__ == "__main__":
    main()
