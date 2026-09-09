"""Read the speaker off the camera: who is visible, whose mouth moves, and whose face it is.

WHY THIS EXISTS. Nothing in this repo has ever measured a diarizer. Every DER quoted in
ENGINEERING_LOG.md comes from English, European or Chinese corpora, because no Malay
diarization benchmark exists and nobody has hand-labelled four hours of this podcast. So
the pipeline's largest open defect -- speaker attribution -- has been improved by argument
rather than by measurement.

This builds the missing yardstick from the video. The show cuts to whoever is talking, so
the camera is already an independent observer of the answer. Three models turn that into a
reference:

  LR-ASD          does the visible mouth match the audio?   (MIT, 94.06 mAP on AVA)
  YuNet + SFace   whose face is it?                         (MIT, ship inside OpenCV)
  PySceneDetect   where does the shot change?               (inside LR-ASD)

The output is an RTTM plus a UEM. The UEM is not an afterthought: the camera is certain in
some places and blind in others, and scoring a diarizer where the reference does not know
the answer measures noise. Always report UEM coverage next to any DER computed against it.

FOUR THINGS THAT WILL SILENTLY CORRUPT THE RESULT. Each of these was hit while building it.

  1. '-ss' BEFORE '-i' WITH '-c:v copy' DESYNCS EVERY CHUNK. Stream-copied video starts at
     the nearest keyframe before the requested time and then has its timestamps reset to
     zero, while re-encoded audio starts exactly on time. Measured here: 600.24s of video
     against 600.000s of audio, six frames of lip-sync offset fed to a lip-sync model.
     Coarse-seek early, then seek accurately on the output, and re-encode.

  2. EYEWEAR SPLITS ONE PERSON INTO SEVERAL FACE CLUSTERS. Rafizi puts his glasses on
     partway through ep62 and accounts for five of that episode's eight clusters. Anything
     assuming one cluster is one speaker builds a six-speaker reference for a three-person
     episode. Hence a multi-vector gallery per person, matched on the MAXIMUM similarity to
     any member rather than on a centroid.

  3. NO GLOBAL SIMILARITY THRESHOLD SEPARATES THESE PEOPLE. On ep62 Rafizi's within-person
     minimum is 0.35 and his maximum similarity to Haziq is 0.40 -- they overlap, so any
     single cut-off misclassifies somebody. Nearest-neighbour argmax works because a real
     match lands at 0.86-0.98; the floor here only rejects strangers, and the margin only
     rejects ties.

  4. THE CAMERA CUT LAGS THE SPEECH by roughly two seconds. This costs COVERAGE, not
     accuracy, and only because LR-ASD scores lip-sync rather than the cut: during the lag
     the previous speaker is on screen with their mouth shut, so the second is dropped from
     the UEM instead of being attributed to the wrong person. A method keyed to the cut
     itself would get those seconds wrong rather than skip them.

STAGES, in order. Each writes a file and can be re-run alone.

  census     sample every Nth second, detect and embed every face      -> _face_census.json
  cluster    group the census, then LOOK at the contact sheet          -> _census_sheet.png
  gallery    name the clusters and freeze a multi-vector gallery       -> _face_gallery.json
  run        LR-ASD over the whole video in chunks, embedding tracks   -> _camera_tracks/
  reference  identity + speaking score -> per-second labels            -> .rttm and .uem

'cluster' deliberately stops and makes a human look at a picture. Naming a face is the one
step here with no independent check available, and the standing rule on this corpus is that
a speaker is never inferred from text.
"""
import argparse
import glob
import json
import os
import pickle
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

# Hard rule on this machine: only GPU 0 (RTX 2070) is usable. Columbia_test.py calls .cuda()
# in a subprocess, which inherits this environment, so setting it here covers both.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "data" / "_facemodels"
YUNET = MODELS / "face_detection_yunet_2023mar.onnx"
SFACE = MODELS / "face_recognition_sface_2021dec.onnx"
LRASD = ROOT / "data" / "_lrasd"
ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"

CHUNK_S = 600
CENSUS_STEP_S = 10
MIN_FACE_PX = 40
FLOOR = 0.55        # rejects a stranger (the one b-roll face in ep62 scored 0.22)
MARGIN = 0.10       # rejects a tie between two people the gallery cannot separate
SPEAK = 0.0         # LR-ASD's own sign convention for "this mouth produced this audio"


def _models():
    if not YUNET.exists() or not SFACE.exists():
        sys.exit(f"face models missing under {MODELS}\n"
                 f"  curl -L -o {YUNET} {ZOO}/face_detection_yunet/{YUNET.name}\n"
                 f"  curl -L -o {SFACE} {ZOO}/face_recognition_sface/{SFACE.name}")
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320),
                                    score_threshold=0.6, nms_threshold=0.3, top_k=50)
    return det, cv2.FaceRecognizerSF.create(str(SFACE), "")


def _unit(v):
    return v / (np.linalg.norm(v) + 1e-9)


def hms(s):
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def cmd_census(a):
    det, rec = _models()
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    out = []
    for fno in range(0, total, int(fps * a.step)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, fno)
        ok, frame = cap.read()
        if not ok:
            continue
        h, w = frame.shape[:2]
        det.setInputSize((w, h))
        _, faces = det.detect(frame)
        for f in (faces if faces is not None else []):
            if f[2] * f[3] < MIN_FACE_PX ** 2:
                continue
            out.append({"t": round(fno / fps, 2),
                        "x": int(f[0]), "y": int(f[1]), "w": int(f[2]), "h": int(f[3]),
                        "vec": _unit(rec.feature(rec.alignCrop(frame, f)).flatten()).tolist()})
    cap.release()
    Path(a.out).write_text(json.dumps(out))
    print(f"{len(out)} faces sampled every {a.step}s from {total / fps / 60:.1f} min -> {a.out}")


def cmd_cluster(a):
    from sklearn.cluster import AgglomerativeClustering
    rows = json.loads(Path(a.census).read_text())
    M = np.array([r["vec"] for r in rows])
    lab = AgglomerativeClustering(n_clusters=None, distance_threshold=a.threshold,
                                  metric="cosine", linkage="average").fit_predict(M)
    Path(a.out).write_text(json.dumps({"labels": lab.tolist(), "threshold": a.threshold}))

    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    counts = np.bincount(lab)
    grid = []
    for c in [c for c in np.argsort(-counts) if counts[c] >= a.min_size]:
        idx = np.where(lab == c)[0]
        row = []
        for i in idx[np.linspace(0, len(idx) - 1, 6).astype(int)]:
            r = rows[i]
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(r["t"] * fps))
            ok, fr = cap.read()
            if not ok:
                continue
            pad = int(r["w"] * 0.35)
            crop = cv2.resize(fr[max(0, r["y"] - pad):r["y"] + r["h"] + pad,
                                 max(0, r["x"] - pad):r["x"] + r["w"] + pad], (170, 170))
            bar = np.zeros((26, 170, 3), np.uint8)
            cv2.putText(bar, f"c{c} {hms(r['t'])}", (3, 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
            row.append(np.vstack([bar, crop]))
        while len(row) < 6:
            row.append(np.zeros_like(row[0]))
        grid.append(np.hstack(row))
        print(f"  cluster {c:>3}  n={len(idx):>5}  "
              f"{hms(min(rows[i]['t'] for i in idx))}-{hms(max(rows[i]['t'] for i in idx))}")
    cap.release()
    cv2.imwrite(a.sheet, np.vstack(grid))
    print(f"\n{a.sheet} written -- LOOK AT IT before naming anything. Expect one person to "
          f"own several clusters: glasses, profile and lighting each split them.")


def cmd_gallery(a):
    rows = json.loads(Path(a.census).read_text())
    lab = json.loads(Path(a.labels).read_text())["labels"]
    gallery, prov = defaultdict(list), defaultdict(list)
    for pair in a.name:
        cid, name = pair.split("=", 1)
        idx = [i for i, l in enumerate(lab) if l == int(cid)]
        if not idx:
            print(f"  cluster {cid} is empty -- skipped")
            continue
        take = [idx[j] for j in
                np.linspace(0, len(idx) - 1, min(len(idx), a.per_cluster)).astype(int)]
        gallery[name] += [rows[i]["vec"] for i in take]
        prov[name].append({"cluster": int(cid), "n_total": len(idx), "n_taken": len(take)})
    Path(a.out).write_text(json.dumps({"gallery": dict(gallery), "provenance": dict(prov)}))

    print(a.out)
    for n, v in gallery.items():
        print(f"  {n:10} {len(v):>3} vectors from clusters {[p['cluster'] for p in prov[n]]}")
    names = list(gallery)
    print("\n  within-person MIN against cross-person MAX. If the first is lower than the")
    print("  second, no global threshold can separate them and only argmax will do:")
    for n in names:
        G = np.array(gallery[n])
        print(f"    {n:10} within min {(G @ G.T).min():.2f}")
    for i, x in enumerate(names):
        for y in names[i + 1:]:
            S = np.array(gallery[x]) @ np.array(gallery[y]).T
            print(f"    {x} vs {y}: cross max {S.max():.2f}")


def _embed_crop(avi, det, rec, stride=5, upscale=2):
    """Mean SFace vector over a track's cropped face video.

    The crops are 224px, which is small for a detector tuned on full frames, so they are
    doubled before detection. Without that the hit rate on profile shots drops sharply.
    """
    cap, feats, n = cv2.VideoCapture(avi), [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        n += 1
        if n % stride:
            continue
        big = cv2.resize(frame, None, fx=upscale, fy=upscale)
        det.setInputSize((big.shape[1], big.shape[0]))
        _, faces = det.detect(big)
        if faces is None or len(faces) == 0:
            continue
        f = max(faces, key=lambda x: x[2] * x[3])
        feats.append(_unit(rec.feature(rec.alignCrop(big, f)).flatten()))
    cap.release()
    if not feats:
        return None, 0
    return _unit(np.mean(feats, axis=0)).tolist(), len(feats)


def cmd_run(a):
    if not (LRASD / "Columbia_test.py").exists():
        sys.exit(f"LR-ASD not found at {LRASD}\n"
                 f"  git clone https://github.com/Junhua-Liao/LR-ASD {LRASD}")
    det, rec = _models()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # Chunk files are named by offset only, and an existing chunk is skipped. Before this
    # guard, running a second episode into the same --out silently reused the first
    # episode's chunks and reported full progress having processed nothing.
    meta = out / "meta.json"
    stem = Path(a.video).name
    if meta.exists():
        prior = json.loads(meta.read_text())["video"]
        if prior != stem:
            sys.exit(f"{out} already holds tracks for {prior}, not {stem}; use another --out")
    else:
        meta.write_text(json.dumps({"video": stem}))
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    cap.release()

    # A stride partition parallelises without a lock: no two workers pick the same chunk,
    # so they never collide on a work directory. Three is right here because LR-ASD reads
    # one JPG per frame and leaves the GPU at 37% -- the win is overlapped I/O, not compute.
    every = list(range(0, int(total), CHUNK_S))
    began = time.time()
    for t0 in every[a.offset::a.stride]:
        dest = out / f"chunk_{t0:06d}.json"
        if dest.exists():
            continue
        name = f"k{t0}"
        work, chunk = LRASD / "work" / name, LRASD / "work" / f"{name}.mp4"
        shutil.rmtree(work, ignore_errors=True)
        work.parent.mkdir(parents=True, exist_ok=True)
        dur = min(CHUNK_S, total - t0)
        pre = min(20, t0)          # see note 1 in the module docstring
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-ss", str(t0 - pre), "-i", a.video,
                        "-ss", str(t0 - pre), "-i", a.audio,
                        "-map", "0:v", "-map", "1:a", "-ss", str(pre), "-t", str(dur),
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                        "-c:a", "aac", str(chunk)], check=True)
        r = subprocess.run([sys.executable, "Columbia_test.py", "--videoName", name,
                            "--videoFolder", "work", "--pretrainModel",
                            "weight/finetuning_TalkSet.model"],
                           cwd=LRASD, capture_output=True, text=True)
        tp, sp = work / "pywork" / "tracks.pckl", work / "pywork" / "scores.pckl"
        if not tp.exists():
            print(f"{t0}s FAILED: {(r.stderr or '')[-300:]}", flush=True)
            shutil.rmtree(work, ignore_errors=True)
            chunk.unlink(missing_ok=True)
            continue
        tracks, scores = pickle.load(open(tp, "rb")), pickle.load(open(sp, "rb"))
        cfps = cv2.VideoCapture(str(work / "pyavi" / "video.avi")).get(cv2.CAP_PROP_FPS) or 25
        rows = []
        for ii, (tr, sc) in enumerate(zip(tracks, scores)):
            f, s = tr["track"]["frame"], np.asarray(sc, dtype=float)
            box = tr["track"]["bbox"].mean(axis=0)
            crop = work / "pycrop" / f"{ii:05d}.avi"
            vec, nv = _embed_crop(str(crop), det, rec) if crop.exists() else (None, 0)
            per = defaultdict(list)
            for ff, vv in zip(f, s):
                per[int(t0 + ff / cfps)].append(float(vv))
            rows.append({"t0": round(t0 + f[0] / cfps, 2), "t1": round(t0 + f[-1] / cfps, 2),
                         "mean": round(float(s.mean()), 3),
                         "talk_frac": round(float((s > SPEAK).mean()), 3),
                         "cx": int((box[0] + box[2]) / 2), "w": int(box[2] - box[0]),
                         "per_sec": {k: round(float(np.mean(v)), 2) for k, v in per.items()},
                         "vec": vec, "vec_frames": nv})
        dest.write_text(json.dumps({"t0": t0, "tracks": rows}))
        shutil.rmtree(work, ignore_errors=True)
        chunk.unlink(missing_ok=True)
        n = len(list(out.glob("chunk_*.json")))
        print(f"{t0 // 60:>4}-{int(min(t0 + CHUNK_S, total)) // 60:>4} min  "
              f"{len(rows):>4} tracks  {n}/{len(every)} chunks  "
              f"elapsed {(time.time() - began) / 60:.0f}m", flush=True)


def cmd_reference(a):
    G = {k: np.array(v) for k, v in
         json.loads(Path(a.gallery).read_text())["gallery"].items()}

    def identify(vec):
        if not vec:
            return None
        v = np.array(vec)
        ranked = sorted(((float((M @ v).max()), n) for n, M in G.items()), reverse=True)
        best, name = ranked[0]
        second = ranked[1][0] if len(ranked) > 1 else 0.0
        return name if best >= a.floor and best - second >= a.margin else None

    meta = Path(a.tracks) / "meta.json"
    if meta.exists() and a.uri not in json.loads(meta.read_text())["video"]:
        sys.exit(f"{a.tracks} holds tracks for {json.loads(meta.read_text())['video']}, "
                 f"not {a.uri}")

    # A face the gallery cannot name is still a face whose mouth LR-ASD scored. It cannot
    # be labelled, but it must still count toward the overlap test: dropping it credited a
    # guest's crosstalk to whichever host was identified, and dropped the guest's own solo
    # speech from the UEM as if nobody had spoken. On ep62, where all three people are in
    # the gallery, this changes 2 seconds; on a guest episode it is the whole guest.
    UNKNOWN = "?"
    per_sec, ntr, nid = defaultdict(dict), 0, 0
    for p in sorted(glob.glob(str(Path(a.tracks) / "chunk_*.json"))):
        for tr in json.loads(Path(p).read_text()).get("tracks", []):
            ntr += 1
            name = identify(tr.get("vec"))
            if name:
                nid += 1
            else:
                name = UNKNOWN
            for s, v in tr["per_sec"].items():
                s = int(s)
                per_sec[s][name] = max(per_sec[s].get(name, -9.0), v)

    ref, overlap, quiet, unknown = {}, 0, 0, 0
    for s, who in per_sec.items():
        talking = [n for n, v in who.items() if v > a.speak]
        if len(talking) == 1 and talking[0] != UNKNOWN:
            ref[s] = talking[0]
        elif len(talking) > 1:
            overlap += 1
        elif talking:
            unknown += 1
        else:
            quiet += 1

    turns, cur = [], None
    for s in sorted(ref):
        if cur and ref[s] == cur[2] and s == cur[1] + 1:
            cur[1] = s
        else:
            if cur:
                turns.append(cur)
            cur = [s, s, ref[s]]
    if cur:
        turns.append(cur)

    with open(a.out + ".rttm", "w") as f:
        for x, y, n in turns:
            # RTTM is whitespace-delimited: a name with a space would split into fields.
            f.write(f"SPEAKER {a.uri} 1 {x:.2f} {y - x + 1:.2f} <NA> <NA> "
                    f"{n.replace(' ', '_')} <NA> <NA>\n")
    with open(a.out + ".uem", "w") as f:
        for x, y, _ in turns:
            f.write(f"{a.uri} 1 {x:.2f} {y + 1:.2f}\n")

    # Coverage over the episode's runtime, not over the last second a face was seen: a tail
    # with no gallery face (a guest's sign-off, credits) otherwise inflates the figure.
    span = a.runtime or int(max(per_sec) if per_sec else 0) + 1
    print(f"tracks {ntr}, identified {nid} ({nid / max(ntr, 1):.0%})")
    print(f"{span}s runtime   CONFIDENT {len(ref)}s = {len(ref) / max(span, 1):.0%} UEM coverage")
    print(f"  excluded: overlap {overlap}s, unknown face talking {unknown}s, "
          f"on-screen-but-silent {quiet}s, no face {span - len(per_sec)}s")
    print(f"  {len(turns)} turns -> {a.out}.rttm / {a.out}.uem")
    for n, v in Counter(ref.values()).most_common():
        print(f"    {n:10} {v:>6}s  {v / max(len(ref), 1):>5.1%}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("census", help="detect and embed every face at a fixed interval")
    c.add_argument("video")
    c.add_argument("--step", type=float, default=CENSUS_STEP_S)
    c.add_argument("--out", default="data/_face_census.json")
    c.set_defaults(fn=cmd_census)

    c = sub.add_parser("cluster", help="group the census and write a contact sheet to READ")
    c.add_argument("video")
    c.add_argument("--census", default="data/_face_census.json")
    c.add_argument("--threshold", type=float, default=0.30)
    c.add_argument("--min-size", type=int, default=10)
    c.add_argument("--out", default="data/_census_labels.json")
    c.add_argument("--sheet", default="data/_census_sheet.png")
    c.set_defaults(fn=cmd_cluster)

    c = sub.add_parser("gallery", help="name clusters: --name 5=Rafizi --name 50=Haziq")
    c.add_argument("--census", default="data/_face_census.json")
    c.add_argument("--labels", default="data/_census_labels.json")
    c.add_argument("--name", action="append", required=True, metavar="CLUSTER=NAME")
    c.add_argument("--per-cluster", type=int, default=30)
    c.add_argument("--out", default="data/_face_gallery.json")
    c.set_defaults(fn=cmd_gallery)

    c = sub.add_parser("run", help="LR-ASD over the video in chunks, embedding every track")
    c.add_argument("video")
    c.add_argument("audio")
    c.add_argument("--out", default="data/_camera_tracks")
    c.add_argument("--offset", type=int, default=0)
    c.add_argument("--stride", type=int, default=1)
    c.set_defaults(fn=cmd_run)

    c = sub.add_parser("reference", help="per-second speaker labels as RTTM + UEM")
    c.add_argument("uri")
    c.add_argument("--tracks", default="data/_camera_tracks")
    c.add_argument("--gallery", default="data/_face_gallery.json")
    c.add_argument("--floor", type=float, default=FLOOR)
    c.add_argument("--margin", type=float, default=MARGIN)
    c.add_argument("--speak", type=float, default=SPEAK)
    c.add_argument("--out", default="data/camera_reference")
    c.add_argument("--runtime", type=int, help="episode length in seconds, for the coverage denominator")
    c.set_defaults(fn=cmd_reference)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
