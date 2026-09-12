"""A third witness for a speaker label: the episode's own voices, learned from the camera.

WHY. After MAI's words, the camera reference and the camera-vouched pyannote clusters have
all run, an episode still leaves two classes of turn unnamed (ep63: 61 `Speaker ?` blocks
and 46 short turns where the voice cluster and the camera disagree). The owner's standing
rule is that a digit or a label goes to their ear only when the tools split -- so a third
independent witness is needed, and text is barred from being it.

This one is voice, but not the corpus voiceprint that verify_speaker_voiceprint.py builds
across episodes (whose two cosine distributions overlap, see ENGINEERING_LOG). It is
episode-local: the camera reference already says who is speaking for most of the runtime,
so each named speaker's centroid is built from THIS recording's camera-attested seconds --
same room, same microphone, same day -- and every unnamed window is scored against those
centroids. The camera never sees the windows being scored (that is why they are unnamed), so
the witness is independent of the camera at exactly the seconds that matter.

It WRITES NOTHING. It prints, per target window, the cosine to each speaker and the margin
between the best and the second, plus the leave-one-out self-agreement of each centroid so
the reader knows the ceiling. The decision rule lives with the reader: two of the three
witnesses (camera, named pyannote cluster, this) agreeing is a label; a split stays
`Speaker ?`. Runs on CPU by design -- the GPU is the camera pass's, and this is small.

  python scripts/voice_witness.py ep63
  python scripts/voice_witness.py ep63 --json data/_ep63_voice_witness.json
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""          # CPU only: never a second GPU process
import numpy as np                              # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import verify_speaker_voiceprint as V           # noqa: E402  (embedder, load_audio, SR)
from mai_camera_raw import camera_per_second, diar_per_second  # noqa: E402

MIN_TRAIN_SEG = 6.0        # a camera-attested run must be this long to train on
TRAIN_CLIPS = 24           # per speaker
CLIP = 6.0                 # seconds per training clip
MIN_TARGET = 1.0           # shorter windows are scored but marked weak
WEAK_UNDER = 2.5           # seconds; below this the score is reported as weak
GENERIC = re.compile(r"^Speaker\s*(\d+|\?)$")


def embed_window(inf, audio, a, b):
    a, b = max(0.0, a), min(len(audio) / V.SR, b)
    if b - a < 0.5:
        return None
    import torch
    seg = torch.from_numpy(audio[int(a * V.SR):int(b * V.SR)]).unsqueeze(0)
    v = np.asarray(inf({"waveform": seg, "sample_rate": V.SR})).reshape(-1)
    return v / np.linalg.norm(v)


def camera_runs(rttm):
    runs = []
    for line in open(rttm, encoding="utf-8"):
        f = line.split()
        if f[0] == "SPEAKER":
            runs.append((float(f[3]), float(f[3]) + float(f[4]), f[7].replace("_", " ")))
    return runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--json", help="also write every score here")
    ap.add_argument("--write", action="store_true",
                    help="relabel raw.md where the witness clears the MEASURED thresholds "
                         "(--validate on ep63, 358 held-out windows: >=3 s windows 95-100%% at "
                         "score>=.55 & margin>=.20; 1.6 s windows 100%% at score>=.60 & margin>=.30). "
                         "Label field only; the body is asserted unchanged; every change is printed")
    ap.add_argument("--validate", action="store_true",
                    help="hold out every third camera run, score windows cut from it, and print "
                         "accuracy by window length and margin -- the threshold comes from here")
    a = ap.parse_args()

    vid, blocks = V.read_episode(a.tag)
    audio = V.load_audio(vid)
    runtime = len(audio) / V.SR
    inf = V._embedder()
    rttm = ROOT / "data" / f"camera_ref_{a.tag}.rttm"
    camera = camera_per_second(rttm)
    diar_path = ROOT / "data" / f"diar_{vid}_t055.json"
    diar = diar_per_second(diar_path, camera)[0] if diar_path.exists() else {}

    # 1. Centroids from the camera's own runs, longest first, midpoint clips.
    by_name, held = defaultdict(list), []
    for i, (s, e, n) in enumerate(r for r in camera_runs(rttm) if r[1] - r[0] >= 3.0):
        if a.validate and i % 3 == 0:
            held.append((s, e, n))          # never trained on
        elif e - s >= MIN_TRAIN_SEG:
            by_name[n].append((s, e))
    cents, per_clip = {}, {}
    for n, runs in by_name.items():
        vecs = []
        for s, e in sorted(runs, key=lambda r: r[1] - r[0], reverse=True)[:TRAIN_CLIPS]:
            m = (s + e) / 2
            v = embed_window(inf, audio, m - CLIP / 2, m + CLIP / 2)
            if v is not None:
                vecs.append(v)
        if len(vecs) >= 4:
            per_clip[n] = np.array(vecs)
            c = np.mean(vecs, axis=0)
            cents[n] = c / np.linalg.norm(c)
    names = sorted(cents)
    print(f"{a.tag}: {len(names)} voices learned from the camera: "
          + ", ".join(f"{n} ({len(per_clip[n])} clips)" for n in names))
    # Leave-one-out self-agreement and cross-speaker similarity: the ceiling and the floor.
    for n in names:
        M = per_clip[n]
        loo = []
        for i in range(len(M)):
            rest = np.delete(M, i, axis=0).mean(axis=0)
            loo.append(float(M[i] @ (rest / np.linalg.norm(rest))))
        others = {o: float(cents[n] @ cents[o]) for o in names if o != n}
        print(f"  {n:14} self {np.mean(loo):.2f} (min {min(loo):.2f})   vs "
              + "  ".join(f"{o} {v:.2f}" for o, v in others.items()))

    if a.validate:
        # Windows of three lengths cut from the START of each held-out run (a real block's
        # window starts at its stamp), scored exactly as a target would be.
        rows = []
        for s, e, n in held:
            for L in (1.6, 3.0, 8.0):
                if e - s < L:
                    continue
                v = embed_window(inf, audio, s, s + L)
                if v is None:
                    continue
                sc = sorted(((float(v @ cents[k]), k) for k in names), reverse=True)
                rows.append((L, n, sc[0][1], sc[0][0], sc[0][0] - sc[1][0]))
        print(f"held-out camera runs: {len(held)}, windows scored: {len(rows)}")
        print(f"{'window':>7} {'rule':>28} {'n':>5} {'named':>6} {'right':>6} {'acc':>6}")
        for L in (1.6, 3.0, 8.0):
            for lab, rule in (("any", lambda sc, m: True), ("score>=.55 & margin>=.20", lambda sc, m: sc >= .55 and m >= .20),
                              ("score>=.60 & margin>=.30", lambda sc, m: sc >= .60 and m >= .30)):
                sub = [r for r in rows if r[0] == L]
                named = [r for r in sub if rule(r[3], r[4])]
                right = sum(1 for r in named if r[1] == r[2])
                print(f"{L:>7} {lab:>28} {len(sub):>5} {len(named):>6} {right:>6} {right / len(named) if named else 0:>6.1%}")
        by_pair = Counter((r[1], r[2]) for r in rows if r[0] == 8.0 and r[1] != r[2])
        print("  8 s confusions (truth -> voice):", dict(by_pair))
        return

    # 2. Targets: every generic block in raw.md, window = its stamp to the next stamp.
    targets = []
    for i, (stamp, label, text) in enumerate(blocks):
        if not GENERIC.match(label.strip()):
            continue
        s = V.to_seconds(stamp)
        e = V.to_seconds(blocks[i + 1][0]) if i + 1 < len(blocks) else runtime
        targets.append({"kind": "generic block", "t": s, "end": min(e, s + 20), "label": label.strip(),
                        "text": text.strip()[:70]})
    # ...and every short turn the build reported as voice-vs-camera disputed.
    dry = ROOT / "data" / f"_{a.tag}_dryrun.txt"
    if dry.exists():
        for line in open(dry, encoding="utf-8"):
            m = re.match(r"\s+\[?([\d:]+)\]? voice=(.+?) camera=(.+?): (.*)", line.rstrip())
            if m:
                s = V.to_seconds(m.group(1))
                targets.append({"kind": "disputed short turn", "t": s, "end": s + 1.6,
                                "voice_cluster": m.group(2), "camera": m.group(3),
                                "text": m.group(4)[:70]})

    out = []
    tally = Counter()
    for tg in targets:
        s, e = tg["t"], tg["end"]
        v = embed_window(inf, audio, s, e)
        if v is None:
            continue
        scores = {n: float(v @ cents[n]) for n in names}
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        best, second = ranked[0], ranked[1] if len(ranked) > 1 else (None, 0.0)
        cam = Counter(camera[t] for t in range(int(s), int(e) + 1) if t in camera)
        dia = Counter(diar[t] for t in range(int(s), int(e) + 1) if t in diar)
        tg.update({
            "voice": best[0], "voice_score": round(best[1], 3),
            "margin": round(best[1] - second[1], 3),
            "weak": (e - s) < WEAK_UNDER,
            "camera_here": cam.most_common(1)[0][0] if cam else None,
            "pyannote_here": dia.most_common(1)[0][0] if dia else None,
            "scores": {k: round(x, 3) for k, x in scores.items()},
        })
        witnesses = [w for w in (tg["camera_here"], tg["pyannote_here"], tg["voice"]) if w]
        agree = Counter(witnesses).most_common(1)[0] if witnesses else (None, 0)
        tg["two_of_three"] = agree[0] if agree[1] >= 2 and not tg["weak"] else None
        tally[tg["kind"], "named by 2 of 3" if tg["two_of_three"] else "split or weak"] += 1
        out.append(tg)

    print()
    for tg in out:
        h, r = divmod(tg["t"], 3600)
        m, sec = divmod(r, 60)
        flag = "WEAK " if tg["weak"] else "     "
        print(f"{flag}{h}:{m:02}:{sec:02} {tg['kind'][:9]:9} voice={tg['voice']:12} "
              f"{tg['voice_score']:.2f} margin {tg['margin']:.2f} | camera={tg['camera_here'] or '-':12} "
              f"pyannote={tg['pyannote_here'] or '-':12} | 2of3={tg['two_of_three'] or '-':12} | {tg['text']}")
    print()
    for (kind, verdict), n in sorted(tally.items()):
        print(f"  {kind:20} {verdict:16} {n}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote {a.json}")

    # 3. The decision, with the measured thresholds. A generic block takes the witness alone
    # when it clears the bar (the camera and the cluster are absent there by definition). A
    # disputed short turn is a vote: cluster (its current label), camera, and the witness if
    # it clears the short bar; the majority wins, a tie keeps the current label.
    changes = []
    for tg in out:
        long_ok = (tg["end"] - tg["t"]) >= 3.0 and tg["voice_score"] >= .55 and tg["margin"] >= .20
        short_ok = tg["voice_score"] >= .60 and tg["margin"] >= .30
        if tg["kind"] == "generic block" and (long_ok or short_ok):
            changes.append((tg["t"], tg["label"], tg["voice"], tg["text"], "witness alone"))
        elif tg["kind"] != "generic block" and short_ok:
            votes = Counter([tg["voice_cluster"], tg["camera"], tg["voice"]])
            top, n = votes.most_common(1)[0]
            if n >= 2 and top != tg["voice_cluster"]:
                changes.append((tg["t"], tg["voice_cluster"], top, tg["text"], "2 of 3"))
    print(f"\n{len(changes)} label(s) the witness settles" + ("" if a.write else " (dry run; --write applies)"))
    raw_path = V.episode_dir(a.tag) / "raw.md"
    text = raw_path.read_text(encoding="utf-8")
    strip_labels = lambda t: re.sub(r"^(\[[\d:]+\] )[^:\n]+:", r"\1", t, flags=re.M)
    body_before = strip_labels(text)
    applied = 0
    for t, old_l, new_l, snippet, how in changes:
        h, r = divmod(t, 3600)
        m, sec = divmod(r, 60)
        stamp = f"{h}:{m:02}:{sec:02}" if h else f"{m:02}:{sec:02}"
        head = re.escape(snippet.split(" ")[0]) if snippet else ""
        rx = re.compile(rf"^(\[{re.escape(stamp)}\] ){re.escape(old_l)}:(?=\s*{head})", re.M)
        n = len(rx.findall(text))
        print(f"  {stamp} {old_l} -> {new_l}  [{how}]  {snippet[:60]}" + ("" if n == 1 else f"   !! {n} matches, skipped"))
        if n == 1 and a.write:
            text = rx.sub(lambda mm: mm.group(1) + new_l + ":", text, count=1)
            applied += 1
    if a.write:
        assert body_before == strip_labels(text), "body changed -- refusing to write"
        raw_path.write_text(text, encoding="utf-8")
        print(f"wrote {raw_path.name}: {applied} label(s) changed, body byte-identical")


if __name__ == "__main__":
    main()
