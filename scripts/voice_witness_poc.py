"""Proof of concept: can a better embedding model or a tighter window name the residue?

Compares, on the SAME held-out camera runs and the SAME unnamed targets as voice_witness.py:
  embedders  A) pyannote/wespeaker-voxceleb-resnet34-LM (the current witness)
             B) speechbrain/spkrec-ecapa-voxceleb (ECAPA-TDNN)
             C) speechbrain/spkrec-resnet-voxceleb (ResNet TDNN)   -- if it loads
  windows    stamp   : block stamp to the next block's stamp (what voice_witness.py does)
             wordspan: first MAI word to last MAI word of the block, 0.15 s pad each side

Prints one accuracy table per (embedder, window) on held-out windows of 1.6 / 3 / 8 s, then
scores every leftover `Speaker ?` block and every disputed short turn under every combination
and writes data/_<tag>_poc.md for the owner to check against the video. WRITES NOTHING to
episodes/. CPU only.

  python scripts/voice_witness_poc.py ep63
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""
import numpy as np                                  # noqa: E402
import torch                                        # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import verify_speaker_voiceprint as V               # noqa: E402
from mai_camera_raw import camera_per_second, diar_per_second, mai_turns  # noqa: E402
from voice_witness import camera_runs, MIN_TRAIN_SEG, TRAIN_CLIPS, CLIP, GENERIC  # noqa: E402

PAD = 0.15
RULES = (("any", lambda s, m: True),
         ("s>=.55 m>=.20", lambda s, m: s >= .55 and m >= .20),
         ("s>=.60 m>=.30", lambda s, m: s >= .60 and m >= .30))


class Embedder:
    def __init__(self, name):
        self.name = name
        if name == "wespeaker-resnet34":
            self.inf = V._embedder()
            self.f = lambda w: np.asarray(self.inf({"waveform": w, "sample_rate": V.SR})).reshape(-1)
        else:
            from speechbrain.inference.speaker import EncoderClassifier
            from speechbrain.utils.fetching import LocalStrategy
            src = {"ecapa": "speechbrain/spkrec-ecapa-voxceleb",
                   "resnet-tdnn": "speechbrain/spkrec-resnet-voxceleb"}[name]
            enc = EncoderClassifier.from_hparams(source=src, savedir=str(ROOT / "data" / f"_sb_{name}"),
                                                 run_opts={"device": "cpu"},
                                                 local_strategy=LocalStrategy.COPY)
            self.f = lambda w: enc.encode_batch(w).squeeze().detach().numpy().reshape(-1)

    def __call__(self, audio, a, b):
        a, b = max(0.0, a), min(len(audio) / V.SR, b)
        if b - a < 0.4:
            return None
        w = torch.from_numpy(audio[int(a * V.SR):int(b * V.SR)]).unsqueeze(0)
        v = self.f(w)
        return v / np.linalg.norm(v)


def centroids(emb, audio, runs_by_name):
    cents = {}
    for n, runs in runs_by_name.items():
        vecs = []
        for s, e in sorted(runs, key=lambda r: r[1] - r[0], reverse=True)[:TRAIN_CLIPS]:
            m = (s + e) / 2
            v = emb(audio, m - CLIP / 2, m + CLIP / 2)
            if v is not None:
                vecs.append(v)
        if len(vecs) >= 4:
            c = np.mean(vecs, axis=0)
            cents[n] = c / np.linalg.norm(c)
    return cents


def score(v, cents):
    sc = sorted(((float(v @ c), n) for n, c in cents.items()), reverse=True)
    return sc[0][1], sc[0][0], sc[0][0] - (sc[1][0] if len(sc) > 1 else 0.0)


def main():
    tag = sys.argv[1]
    vid, blocks = V.read_episode(tag)
    audio = V.load_audio(vid)
    runtime = len(audio) / V.SR
    rttm = ROOT / "data" / f"camera_ref_{tag}.rttm"
    camera = camera_per_second(rttm)
    diar = diar_per_second(ROOT / "data" / f"diar_{vid}_t055.json", camera)[0]
    words = sorted((w.t, str(w)) for t in mai_turns(vid) for w in t["w"])
    wtimes = np.array([t for t, _ in words])

    # Same split as voice_witness --validate: every third camera run held out.
    train, held = defaultdict(list), []
    for i, (s, e, n) in enumerate(r for r in camera_runs(rttm) if r[1] - r[0] >= 3.0):
        if i % 3 == 0:
            held.append((s, e, n))
        elif e - s >= MIN_TRAIN_SEG:
            train[n].append((s, e))

    # Targets: leftover generic blocks (both window modes) and disputed short turns.
    targets = []
    for i, (stamp, label, text) in enumerate(blocks):
        if not GENERIC.match(label.strip()):
            continue
        s = V.to_seconds(stamp)
        e = V.to_seconds(blocks[i + 1][0]) if i + 1 < len(blocks) else runtime
        inside = wtimes[(wtimes >= s) & (wtimes < e)]
        ws, we = (float(inside[0]) - PAD, float(inside[-1]) + 0.35 + PAD) if len(inside) else (s, e)
        targets.append({"kind": "generic", "stamp": stamp, "t": s, "text": text.strip()[:60],
                        "win": {"stamp": (s, min(e, s + 20)), "wordspan": (ws, min(we, ws + 20))}})
    for line in open(ROOT / "data" / f"_{tag}_dryrun.txt", encoding="utf-8"):
        m = re.match(r"\s+\[?([\d:]+)\]? voice=(.+?) camera=(.+?): (.*)", line.rstrip())
        if m:
            s = V.to_seconds(m.group(1))
            nw = len(m.group(4).split())
            inside = wtimes[(wtimes >= s) & (wtimes < s + 3)][:nw]
            ws, we = (float(inside[0]) - PAD, float(inside[-1]) + 0.35 + PAD) if len(inside) else (s, s + 1.6)
            targets.append({"kind": "disputed", "stamp": m.group(1), "t": s, "text": m.group(4)[:60],
                            "cluster": m.group(2), "camera": m.group(3),
                            "win": {"stamp": (s, s + 1.6), "wordspan": (ws, we)}})

    results = {}
    held_votes = defaultdict(dict)      # (run index, L) -> {model: (who, sc, mg)}
    for name in ("wespeaker-resnet34", "ecapa", "resnet-tdnn"):
        try:
            emb = Embedder(name)
        except Exception as exc:
            print(f"\n== {name}: could not load ({type(exc).__name__}: {str(exc)[:80]})")
            continue
        cents = centroids(emb, audio, train)
        names = sorted(cents)
        cross = {f"{a[:3]}-{b[:3]}": round(float(cents[a] @ cents[b]), 2) for a in names for b in names if a < b}
        print(f"\n== {name}: centroids {names}, between-speaker cosine {cross}")
        rows = []
        for hi, (s, e, n) in enumerate(held):
            for L in (1.6, 3.0, 8.0):
                if e - s < L:
                    continue
                v = emb(audio, s, s + L)
                if v is not None:
                    who, sc, mg = score(v, cents)
                    rows.append((L, n, who, sc, mg))
                    held_votes[(hi, L, n)][name] = (who, sc, mg)
        print(f"{'window':>7} {'rule':>16} {'n':>4} {'named':>6} {'right':>6} {'acc':>7}")
        acc = {}
        for L in (1.6, 3.0, 8.0):
            for lab, rule in RULES:
                sub = [r for r in rows if r[0] == L]
                named = [r for r in sub if rule(r[3], r[4])]
                right = sum(1 for r in named if r[1] == r[2])
                acc[(L, lab)] = (len(sub), len(named), right)
                print(f"{L:>7} {lab:>16} {len(sub):>4} {len(named):>6} {right:>6} "
                      f"{(right / len(named) if named else 0):>7.1%}")
        conf = Counter((r[1][:3], r[2][:3]) for r in rows if r[0] == 1.6 and r[1] != r[2])
        print("  1.6 s confusions:", dict(conf))
        # Score the targets in both window modes.
        for tg in targets:
            for mode, (a, b) in tg["win"].items():
                v = emb(audio, a, b)
                tg.setdefault("scores", {})[(name, mode)] = score(v, cents) if v is not None else None
        results[name] = acc

    # Ensemble: do three independent models agreeing beat any one of them?
    print("\n== three-model vote on held-out windows")
    print(f"{'window':>7} {'rule':>34} {'n':>4} {'named':>6} {'right':>6} {'acc':>7}")
    ens_rules = (("unanimous", lambda vs: len(set(v[0] for v in vs)) == 1),
                 ("unanimous & every margin>=.10", lambda vs: len(set(v[0] for v in vs)) == 1 and min(v[2] for v in vs) >= .10),
                 ("unanimous & every margin>=.15", lambda vs: len(set(v[0] for v in vs)) == 1 and min(v[2] for v in vs) >= .15))
    for L in (1.6, 3.0, 8.0):
        sub = [(k, vs) for k, vs in held_votes.items() if k[1] == L and len(vs) == len(results)]
        for lab, rule in ens_rules:
            named = [(k, vs) for k, vs in sub if rule(list(vs.values()))]
            right = sum(1 for k, vs in named if next(iter(vs.values()))[0] == k[2])
            print(f"{L:>7} {lab:>34} {len(sub):>4} {len(named):>6} {right:>6} {(right / len(named) if named else 0):>7.1%}")
    for tg in targets:
        for mode in ("stamp", "wordspan"):
            vs = [tg["scores"].get((n, mode)) for n in results]
            vs = [v for v in vs if v]
            tg.setdefault("vote", {})[mode] = (vs[0][0], min(v[2] for v in vs)) if len(vs) == len(results) and len(set(v[0] for v in vs)) == 1 else None
    for mode in ("stamp", "wordspan"):
        for kind in ("generic", "disputed"):
            sub = [t for t in targets if t["kind"] == kind]
            u = [t for t in sub if t["vote"][mode]]
            u10 = [t for t in u if t["vote"][mode][1] >= .10]
            print(f"  targets {kind:9} {mode:9}: unanimous {len(u)} of {len(sub)}, unanimous & margin>=.10 {len(u10)}")

    # Owner-facing comparison file.
    combos = [(n, m) for n in results for m in ("stamp", "wordspan")]
    out = [f"# {tag}: proof of concept, three embedding models x two window cuts", "",
           "Held-out accuracy is in the terminal log (data/_poc_log.txt). Below, every leftover block and",
           "every disputed short turn, scored by each combination. A cell reads `name score/margin`; bold",
           "means it clears the strict bar (score >= .60, margin >= .30) that measured 100% on held-out",
           "1.6 s windows for the current model. Links open 5 s early.", ""]
    hdr = "| link | kind | current label | camera | 3-model vote (stamp) | 3-model vote (wordspan) | " + " | ".join(f"{n} {m}" for n, m in combos) + " | words |"
    out += [hdr, "|" + "---|" * (hdr.count("|") - 1)]
    settled = Counter()
    for tg in sorted(targets, key=lambda t: t["t"]):
        cells = []
        for n, m in combos:
            r = tg.get("scores", {}).get((n, m))
            if r is None:
                cells.append("-")
                continue
            who, sc, mg = r
            strong = sc >= .60 and mg >= .30
            if strong:
                settled[(n, m, tg["kind"])] += 1
            cells.append(f"{'**' if strong else ''}{who} {sc:.2f}/{mg:.2f}{'**' if strong else ''}")
        cur = tg.get("cluster", "Speaker ?")
        cam = tg.get("camera", "-")
        votes = " | ".join((f"**{v[0]} (min margin {v[1]:.2f})**" if v and v[1] >= .10 else f"{v[0]} (min margin {v[1]:.2f})" if v else "split")
                           for v in (tg["vote"]["stamp"], tg["vote"]["wordspan"]))
        out.append(f"| [{tg['stamp']}](https://www.youtube.com/watch?v={vid}&t={max(0, tg['t'] - 5)}s) | {tg['kind']} | {cur} | {cam} | {votes} | "
                   + " | ".join(cells) + f" | {tg['text'].replace('|', '/')} |")
    out += ["", "## How many the strict bar would settle, per combination", "",
            "| model | window | leftover blocks | disputed short turns |", "|---|---|---|---|"]
    n_gen = sum(1 for t in targets if t["kind"] == "generic")
    n_dis = sum(1 for t in targets if t["kind"] == "disputed")
    for n, m in combos:
        out.append(f"| {n} | {m} | {settled[(n, m, 'generic')]} of {n_gen} | {settled[(n, m, 'disputed')]} of {n_dis} |")
    Path(ROOT / "data" / f"_{tag}_poc.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\nsettled at the strict bar:", {f"{n}/{m}/{k}": v for (n, m, k), v in settled.items()})
    print(f"wrote data/_{tag}_poc.md")


if __name__ == "__main__":
    main()
