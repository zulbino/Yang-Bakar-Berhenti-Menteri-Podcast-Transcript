"""Label every word of a new episode's raw.md by its voice, then rejoin the words into turns.

OWNER'S DECISION 2026-10-16, which replaces rule 8's 100% bar for NEW episodes: voice writes
the labels, every word gets the voice's best speaker even when it is unsure, and the camera
is used only to say who is in the episode and to learn a voice no other episode has.

Measured on the owner's hand-labelled ep65, ep66 and ep67 (MODEL_LANDSCAPE.md, ENGINEERING_LOG
2.26): this method left 337, 740 and 415 wrong-label words, against 489, 1,590 and 1,453 for the
camera and 388, 1,505 and 2,948 for the pipeline. Labelling WORDS matters: relabelling the
pipeline's turns by a voice vote scored 360, 1,139 and 788.

  1. Cast: every name the camera reference holds for at least --min-seconds.
  2. A voice profile per cast member: the mean WeSpeaker ResNet34 embedding of 1.6 s clips cut
     from OTHER episodes' camera seconds. A member with fewer than --min-clips such clips (a new
     guest) gets a profile from THIS episode's camera seconds instead.
  3. This episode's audio in 1.6 s windows every 1 s, each named by the nearest profile, then a
     3-window majority.
  4. Each raw.md word takes the label at its ASR time; adjacent same-label words join.

The words, their order and the filler and name passes already run are untouched; only labels
and turn stamps change. It refuses an episode with recorded owner rulings, because those
outrank the voice and this would overwrite them.

  python scripts/voice_label_raw.py ep68            # dry run: report only
  python scripts/voice_label_raw.py ep68 --write
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
import numpy as np  # noqa: E402
import torch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
import mai_camera_raw  # noqa: E402
import verify_speaker_voiceprint as V  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "_voice"
WIN, HOP = 1.6, 1.0
FRAME = 0.01                                     # Nemotron's output step
NEMO_PY = os.environ.get("NEMO_PYTHON", r"D:\venvs\nemo312\Scripts\python.exe")
TURN = re.compile(r"^\[[\d:]+\]\s*([^:\n\[\]]{1,40}?):\s*(.*)$")
WORD = re.compile(r"[\w']+")
NOTE = re.compile(r"Speaker labels come from the show(?:''|')s own camera cuts.*?fall back to it\.")
NOTE_NOW = ("Speaker labels come from NVIDIA Nemotron 3 Diarization at each word's own time "
            "(scripts/voice_label_raw.py, owner's decisions 2026-10-16 and 2026-10-18); its speakers are "
            "named by WeSpeaker ResNet34 voice profiles learned from the camera seconds of other episodes, "
            "or of this episode for a speaker no other episode has, and a word Nemotron leaves silent takes "
            "the voice profile's label.")


def name(s):
    return re.sub(r"\s*\(.*?\)\s*$", "", s.replace("_", " ").strip())


def rttm_segments(path):
    segs = []
    for line in open(path, encoding="utf-8"):
        p = line.split()
        if len(p) > 8 and p[0] == "SPEAKER":
            segs.append((p[1], float(p[3]), float(p[3]) + float(p[4]), name(p[7])))
    return segs


def embed(inf, w):
    x = torch.from_numpy(np.ascontiguousarray(w, dtype=np.float32)).unsqueeze(0)
    e = np.asarray(inf({"waveform": x, "sample_rate": V.SR})).reshape(-1)
    return e / (np.linalg.norm(e) + 1e-9)


def clip(vid, t0, dur):
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t0:.2f}", "-t", f"{dur:.2f}", "-i",
           str(ROOT / "audio" / f"{vid}.m4a"), "-ac", "1", "-ar", str(V.SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, dtype=np.float32)


def other_episode_profiles(inf, cast, vid, per_ep=20, max_eps=30):
    """Profiles from OTHER episodes' camera seconds, cut straight from each m4a (as voice_test did)."""
    random.seed(7)
    pools = defaultdict(list)
    for f in sorted((ROOT / "data").glob("camera_ref_*.rttm")):
        for v, a, b, who in rttm_segments(f):
            if v != vid and who in cast and b - a >= WIN + 0.4 and (ROOT / "audio" / f"{v}.m4a").exists():
                pools[(who, v)].append((a, b))
    out = {}
    for who in sorted(cast):
        vids = sorted({v for (w, v) in pools if w == who})
        random.shuffle(vids)
        embs = []
        for v in vids[:max_eps]:
            for a, b in random.sample(pools[(who, v)], min(per_ep, len(pools[(who, v)]))):
                w = clip(v, random.uniform(a + 0.2, b - WIN - 0.2), WIN)
                if len(w) >= int(WIN * V.SR * 0.9):
                    embs.append(embed(inf, w))
        out[who] = (embs, min(len(vids), max_eps))
    return out


def window_embeddings(inf, vid):
    path = CACHE / f"{vid}_windows.npz"
    if path.exists():
        z = np.load(path)
        return list(zip(z["t"].tolist(), list(z["e"])))
    audio = V.load_audio(vid)
    embs, t = [], 0.0
    while t + WIN <= len(audio) / V.SR:
        embs.append((t, embed(inf, audio[int(t * V.SR):int((t + WIN) * V.SR)])))
        t += HOP
    np.savez(path, t=np.array([x[0] for x in embs]), e=np.stack([x[1] for x in embs]))
    wav = ROOT / "audio" / f"_{vid}.16k.wav"
    if wav.exists():
        wav.unlink()
    return embs


def nemotron_frames(vid):
    """Per-speaker activity every 10 ms from Nemotron 3, run in its own Python 3.12 env (cached)."""
    path = CACHE / f"{vid}_nemotron.npz"
    if not path.exists():
        V.load_audio(vid)                        # writes audio/_<vid>.16k.wav
        subprocess.run([NEMO_PY, str(ROOT / "scripts" / "nemotron_diarize.py"),
                        str(ROOT / "audio" / f"_{vid}.16k.wav"), str(path)], check=True, cwd=ROOT)
    return np.load(path)["probs"]


def name_nemotron(P, embs, profiles):
    """Name each Nemotron speaker by the voice profile nearest to the windows it alone holds."""
    names = sorted(profiles)
    C = np.stack([profiles[n] for n in names])
    out = {}
    for k in range(P.shape[1]):
        pool = []
        for t0, e in embs:
            a = P[int(t0 / FRAME):int((t0 + WIN) / FRAME)].mean(axis=0)
            if a[k] > 0.5 and (np.delete(a, k) < 0.5).all():
                pool.append(e)
        if len(pool) >= 20:
            c = np.mean(pool, axis=0)
            sims = C @ (c / np.linalg.norm(c))
            out[k] = names[int(np.argmax(sims))]
            print(f"  nemotron speaker {k}: {len(pool)} windows -> {out[k]} "
                  + ", ".join(f"{n} {s:+.2f}" for n, s in zip(names, sims)))
    return out


def voice_by_second(embs, profiles):
    names = sorted(profiles)
    C = np.stack([profiles[n] for n in names])
    raw = [names[int(np.argmax(C @ e))] for _, e in embs]
    out = {}
    for i, (t, _) in enumerate(embs):
        win = raw[max(0, i - 1):i + 2]
        top, n = Counter(win).most_common(1)[0]
        out[int(t + WIN / 2)] = top if n > len(win) / 2 else raw[i]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--min-seconds", type=float, default=30.0,
                    help="camera seconds a name needs to count as in the episode")
    ap.add_argument("--min-clips", type=int, default=50,
                    help="other-episode clips below which this episode's camera seconds are used")
    ap.add_argument("--raw", help="relabel this copy instead of the episode's raw.md, to score it "
                                  "against the owner's gold with compare_owner_edit.py")
    a = ap.parse_args()

    bare = a.tag.partition(":")[0]
    rulings = json.loads((ROOT / "data" / "speaker_adjudications.json").read_text(encoding="utf-8"))
    hit = [k for k in rulings if re.search(rf"(^|[^0-9a-z]){re.escape(bare)}_", k)]
    if hit and not a.raw:
        sys.exit(f"REFUSING: {a.tag} has owner rulings ({', '.join(hit)}), which outrank the voice. "
                 f"This tool is for new episodes (owner, 2026-10-16).")

    raw = Path(a.raw) if a.raw else common.raw_for_tag(a.tag)
    text = raw.read_text(encoding="utf-8")
    head, body = text.split("# Raw Transcript", 1)
    vid = re.search(r"^video_id:\s*(\S+)", head, re.M).group(1)
    reference = ROOT / "data" / f"camera_ref_{common.artifact_tag(a.tag)}.rttm"
    CACHE.mkdir(parents=True, exist_ok=True)

    secs = Counter()
    for _, x, y, who in rttm_segments(reference):
        secs[who] += y - x
    cast = {w for w, s in secs.items() if s >= a.min_seconds}
    print(f"cast from the camera (>= {a.min_seconds:.0f} s): "
          + ", ".join(f"{w} {secs[w]:.0f}s" for w in sorted(cast))
          + (f" | ignored: " + ", ".join(f"{w} {s:.0f}s" for w, s in secs.items() if w not in cast)
             if len(cast) < len(secs) else ""))

    inf = V._embedder()
    P = nemotron_frames(vid)
    embs = window_embeddings(inf, vid)
    wav = ROOT / "audio" / f"_{vid}.16k.wav"
    if wav.exists():
        wav.unlink()
    camera = {}
    for _, x, y, who in rttm_segments(reference):
        for s in range(int(x), int(y)):
            camera[s] = who
    same = defaultdict(list)
    for t0, e in embs:
        seen = {camera.get(s) for s in range(int(t0), int(t0 + WIN) + 1)}
        if len(seen) == 1 and None not in seen and next(iter(seen)) in cast:
            same[next(iter(seen))].append(e)
    profiles = {}
    for who, (clips, eps) in other_episode_profiles(inf, cast, vid).items():
        if len(clips) >= a.min_clips:
            src, pool = f"{len(clips)} clips from {eps} other episodes", clips
        else:
            src, pool = f"{len(same[who])} windows of THIS episode's camera seconds (only {len(clips)} elsewhere)", same[who]
        if not pool:
            sys.exit(f"REFUSING: no voice sample for {who}, so no profile can be built")
        c = np.mean(pool, axis=0)
        profiles[who] = c / np.linalg.norm(c)
        print(f"  profile {who}: {src}")
    voice = voice_by_second(embs, profiles)
    nem_name = name_nemotron(P, embs, profiles)

    turns = []
    for line in body.splitlines():
        m = TURN.match(line.strip())
        if m:
            turns.append((m.group(1).strip(), m.group(2).split()))
    label_for = {**mai_camera_raw.CAMERA_NAME, **{name(l): l for l, _ in turns}}
    asr = [(w.lower(), x["t"] / 1000, x.get("d", 0) / 1000)
           for t in json.loads((ROOT / "data" / f"_mai_{vid}" / "mai_words.json").read_text(encoding="utf-8"))["turns"]
           for x in t["words"] for w in WORD.findall(x["w"] or "")]
    flat = [(lab, tok, (WORD.findall(tok.lower()) or [""])[0]) for lab, toks in turns for tok in toks]
    sm = SequenceMatcher(None, [f[2] for f in flat], [a[0] for a in asr], autojunk=False)
    times, durs = [None] * len(flat), [0.0] * len(flat)
    for x, y, n in sm.get_matching_blocks():
        for k in range(n):
            times[x + k], durs[x + k] = asr[y + k][1], asr[y + k][2]
    last = 0.0
    for k, t in enumerate(times):                # an unmatched word takes the previous word's time
        times[k] = last = t if t is not None else last

    def nemotron_at(t, d):
        """The named Nemotron speaker most active over the word's own span, or None."""
        a = P[int(t / FRAME):max(int(t / FRAME) + 1, int((t + d) / FRAME))]
        if not len(a):
            return None
        a = a.mean(axis=0)
        return nem_name.get(int(a.argmax())) if a.max() > 0.5 else None

    def voice_at(t):
        for d in (0, -1, 1, -2, 2):
            if int(t) + d in voice:
                return voice[int(t) + d]
        return None

    blocks, changed, by, src = [], 0, Counter(), Counter()
    for (lab, tok, _), t, d in zip(flat, times, durs):
        v = nemotron_at(t, d)
        src["nemotron" if v else "voice"] += 1
        v = v or voice_at(t)
        new = label_for.get(v, v) if v else lab
        changed += new != lab
        by[new] += 1
        if blocks and blocks[-1][1] == new:
            blocks[-1][2].append(tok)
        else:
            blocks.append((t, new, [tok]))
    print(f"words {len(flat)} | label changed {changed} ({changed / max(1, len(flat)):.1%}) | "
          f"matched to an ASR time {sum(1 for x in sm.get_matching_blocks() for _ in range(x[2]))} | "
          f"turns {len(turns)} -> {len(blocks)}")
    print("  words per speaker: " + ", ".join(f"{w} {n}" for w, n in by.most_common())
          + f" | label from {dict(src)}")
    if not a.write:
        print("-- dry run, pass --write to relabel raw.md")
        return

    def stamp(s):
        h, r = divmod(int(s), 3600)
        m, x = divmod(r, 60)
        return f"{h}:{m:02d}:{x:02d}" if h else f"{m:02d}:{x:02d}"

    head = NOTE.sub(NOTE_NOW.replace("'", "''"), head)
    lines = [f"[{stamp(t)}] {who}: {' '.join(toks)}" for t, who, toks in blocks]
    raw.write_text(head + "# Raw Transcript\n\n" + "\n\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {raw}")


if __name__ == "__main__":
    main()
