"""Find where an episode's raw.md blocks disagree with what the audio says, and rank the
disagreements by how much speech is at stake.

WHY RANK BY SPEECH RATHER THAN BY CONFIDENCE. The obvious design is to trust the sensing
score and rewrite whatever it disputes. Two measurements say not to:

  - Per-segment `|score|` does NOT predict correctness. Binned over the 39 segments of the
    gold passage it goes 89% / 80% / 67% / 100% / 50% / 50% from the most confident band
    down. Non-monotonic, so there is no threshold to abstain at. (An earlier block-level
    check looked like it did -- 5 of 6 confirmed, the one miss scoring +0.0008 -- but that
    is six points, and the segment-level curve does not support generalising it.)
  - The method is 83% on the gold passage, so roughly one turn in six is wrong. Writing
    that straight into raw.md trades a known defect for a new and less visible one.

So this tool does not decide anything. It aims the camera. The show cuts to whoever is
talking, which is proven evidence on LONG stretches (ENGINEERING_LOG 1.35-1.38, and 5 of 6
ep61 blocks confirmed that way), and long stretches are exactly where a block absorbing
someone else's speech does the most damage. Ranking by seconds-at-stake therefore puts the
regions that are both most harmful AND most checkable at the top.

Output is a report plus a ready-to-paste `frames_at.py --at` line. Nothing is written to any
episode file.

Usage:
  python scripts/audit_block_attribution.py --episode ep61
  python scripts/audit_block_attribution.py --episode ep61 --min-region 20 --out data/_audit_ep61.json
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sense_speakers import (AUDIO, BLOCK, DEFAULTS, ROOT, build_axis, caption_words,
                            embed_span, episode_dir, load_audio, merged_segments, norm,
                            video_id_of)


def stamp_seconds(ts):
    p = [int(x) for x in ts.split(":")]
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]


def block_spans(folder, caps):
    """A block's audio window, taken from WHERE ITS WORDS ARE, not from its timestamp.

    THIS USED TO USE STAMP-TO-NEXT-STAMP AND IT DESTROYED A VERIFIED TURN. ep61's Farhan
    interjection was stamped [2:51:15] while its words sit at 2:51:41-2:51:59 in the caption
    timings -- the episode has known stamp drift. The stamp-derived window therefore covered
    26 seconds of the PREVIOUS speaker, this tool reported "Farhan -> Rafizi" correctly for
    that window, and the label the owner had established by ear and on video was deleted.

    The words carry real times, so use them. Stamps are only a fallback for a block whose
    text does not align at all, and every such block is reported rather than silently
    trusted.
    """
    from build_region_split_map import block_tokens

    toks = block_tokens(folder, caps)
    out, drifted, unaligned = [], [], []
    for i, b in enumerate(toks):
        stamp_t0 = stamp_seconds(b["stamp"])
        if b["timed"]:
            t0 = min(t[3] for t in b["timed"])
            t1 = max(t[3] for t in b["timed"])
            drift = t0 - stamp_t0
            if abs(drift) > 10:
                drifted.append((b["stamp"], b["label"], drift))
        else:
            nxt = stamp_seconds(toks[i + 1]["stamp"]) if i + 1 < len(toks) else stamp_t0 + 30
            t0, t1, drift = stamp_t0, nxt, 0.0
            unaligned.append((b["stamp"], b["label"]))
        out.append({"i": i, "ts": b["stamp"], "t0": t0, "t1": max(t1, t0 + 0.5),
                    "label": b["label"], "text": b["text"], "drift": drift})

    if drifted:
        print(f"  STAMP DRIFT: {len(drifted)} of {len(out)} blocks sit more than 10s from "
              f"their own timestamp. Windows come from the words, so this is reported, not "
              f"corrected.")
        for stamp, lab, d in sorted(drifted, key=lambda x: -abs(x[2]))[:6]:
            print(f"    [{stamp}] {lab:16} words are {d:+.0f}s from the stamp")
    if unaligned:
        print(f"  {len(unaligned)} block(s) had no word align to the captions; their windows "
              f"fall back to stamps and CANNOT be trusted: "
              f"{', '.join(f'[{t}]' for t, _ in unaligned[:6])}")
    return out


def stamp(t):
    t = int(t)
    return f"{t // 3600}:{(t % 3600) // 60:02d}:{t % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default="ep61")
    ap.add_argument("--anchor", default="Rafizi")
    ap.add_argument("--cohost", default="Haziq")
    ap.add_argument("--min-region", type=float, default=15.0,
                    help="report contiguous disagreeing speech at least this long")
    ap.add_argument("--out", default=None)
    for k, v in DEFAULTS.items():
        ap.add_argument(f"--{k.replace('_', '-')}", type=type(v), default=v)
    a = ap.parse_args()
    cfg = {k: getattr(a, k) for k in DEFAULTS}

    folder = episode_dir(a.episode)
    vid = video_id_of(folder)
    caps = [(norm(w), t) for w, t in
            caption_words((AUDIO / f"{vid}.ms.vtt").read_text(encoding="utf-8"))]
    caps = [c for c in caps if c[0]]
    audio = load_audio(vid)

    print(f"{a.episode}  video {vid}")
    # nothing to hold back here: this is a production run, not a scored one
    ax, mid = build_axis(audio, folder, caps, cfg, a.anchor, (-1, -1))

    segs = []
    for t0, t1, words in merged_segments(caps, cfg["gap"], cfg["floor"]):
        v = embed_span(audio, t0, t1)
        if v is None:
            continue
        sc = float(v @ ax) - mid
        segs.append({"t0": t0, "t1": t1, "words": words, "score": sc,
                     "name": a.anchor if sc > 0 else a.cohost})
    print(f"sensed     : {len(segs)} segments, "
          f"{sum(s['t1'] - s['t0'] for s in segs) / 60:.1f} min of speech")

    blocks = block_spans(folder, caps)
    # per block, how many seconds the audio assigns to each name
    for b in blocks:
        b["sensed"] = defaultdict(float)
        for s in segs:
            o = max(0.0, min(b["t1"], s["t1"]) - max(b["t0"], s["t0"]))
            if o > 0:
                b["sensed"][s["name"]] += o
        b["speech"] = sum(b["sensed"].values())
        b["agree"] = b["sensed"].get(b["label"], 0.0)
        b["disagree"] = b["speech"] - b["agree"]

    total = sum(b["speech"] for b in blocks)
    dis = sum(b["disagree"] for b in blocks)
    print(f"\nblocks     : {len(blocks)}, holding {total / 60:.1f} min of sensed speech")
    print(f"disagrees  : {dis / 60:.1f} min = {dis / total:.0%} of speech sits under a "
          f"label the audio disputes")
    by = defaultdict(lambda: [0.0, 0.0])
    for b in blocks:
        by[b["label"]][0] += b["disagree"]
        by[b["label"]][1] += b["speech"]
    print("\n  per current label:")
    for lab, (d, t) in sorted(by.items(), key=lambda x: -x[1][0]):
        if t > 0:
            print(f"    {lab:18} {d / 60:>6.1f} / {t / 60:>6.1f} min disputed = {d / t:>4.0%}")

    # contiguous runs of disagreeing speech, which is what the camera can check
    regions = []
    for b in blocks:
        run = None
        for s in segs:
            if s["t1"] <= b["t0"] or s["t0"] >= b["t1"]:
                continue
            if s["name"] != b["label"]:
                if run is None:
                    run = {"t0": s["t0"], "t1": s["t1"], "name": s["name"],
                           "block": b["i"], "label": b["label"], "secs": 0.0,
                           "words": [], "scores": []}
                if s["name"] != run["name"]:
                    if run["secs"] >= a.min_region:
                        regions.append(run)
                    run = {"t0": s["t0"], "t1": s["t1"], "name": s["name"],
                           "block": b["i"], "label": b["label"], "secs": 0.0,
                           "words": [], "scores": []}
                run["t1"] = s["t1"]
                run["secs"] += s["t1"] - s["t0"]
                run["words"] += s["words"]
                run["scores"].append(s["score"])
            else:
                if run and run["secs"] >= a.min_region:
                    regions.append(run)
                run = None
        if run and run["secs"] >= a.min_region:
            regions.append(run)

    regions.sort(key=lambda r: -r["secs"])
    print(f"\ncontiguous disagreeing regions of >= {a.min_region:.0f}s: {len(regions)}")
    print(f"  they hold {sum(r['secs'] for r in regions) / 60:.1f} min, "
          f"{sum(r['secs'] for r in regions) / dis:.0%} of all disputed speech\n")
    print(f"{'#':>3} {'span':>17} {'secs':>6} {'label':>8} -> {'sensed':<8} {'mean':>7}  text")
    for n, r in enumerate(regions[:40], 1):
        mean = sum(r["scores"]) / len(r["scores"])
        print(f"{n:>3} {stamp(r['t0']) + '-' + stamp(r['t1']):>17} {r['secs']:>6.1f} "
              f"{r['label']:>8} -> {r['name']:<8} {mean:>+7.3f}  "
              f"{' '.join(r['words'])[:52]}")

    top = regions[:12]
    if top:
        print("\ncheck these on video first (mid-region, where the camera has settled):")
        print("  python scripts/frames_at.py " + a.episode + ":berhenti --pad 3 --at " +
              " ".join(stamp((r["t0"] + r["t1"]) / 2) for r in top))

    if a.out:
        Path(a.out).write_text(json.dumps({
            "episode": a.episode, "video_id": vid, "config": cfg,
            "totals": {"speech_min": total / 60, "disputed_min": dis / 60,
                       "disputed_share": dis / total},
            "regions": [{k: (round(v, 2) if isinstance(v, float) else v)
                         for k, v in r.items() if k != "scores"} |
                        {"mean_score": round(sum(r["scores"]) / len(r["scores"]), 4),
                         "text": " ".join(r["words"])}
                        for r in regions],
        }, indent=1), encoding="utf-8")
        print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
