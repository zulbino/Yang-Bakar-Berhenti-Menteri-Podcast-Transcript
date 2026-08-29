"""Sense who is speaking, turn by turn, without trusting any existing speaker label.

WHAT PROBLEM THIS SOLVES. Attribution is the largest open defect in the repo: 341
published turns of 400+ words across 63 episodes sit under one label, and every checker in
the suite is green while that is true, because no check reads whether a turn holds two
voices. The diarizer fails in BOTH directions -- long monologues collapse into one label,
and short interjections get absorbed by whoever is next to them -- so no blanket correction
works and the labels themselves cannot be used as evidence.

MEASURED AGAINST THE OWNER'S GOLD DATA (data/speaker_ground_truth.json, 18 hand-written
turns of ep61). Full results and every rejected approach are in
data/diarization_bakeoff.json.

                                    stage A            stage B
    raw.md (baseline)                    --      11/18 = 61%   Haziq 9/9, Rafizi 2/9
    interview.md                         --      11/18 = 61%   identical to raw.md
    pyannote clustering.threshold=0.55  50%      12/18 = 67%   ORACLE ceiling, not actual
    this script                        100%      15/18 = 83%   Haziq 8/9, Rafizi 7/9

HOW IT WORKS, in the order the pieces matter.

  1. BOUNDARIES COME FROM CAPTION WORD GAPS, NOT FROM THE DIARIZER. A turn change is a
     pause, and YouTube's caption track timestamps every word, so cutting at every pause
     of >=0.4s finds 16 of the 16 gold speaker changes. pyannote at threshold 0.55 finds 8.
     This over-segments by roughly 3x, which is the right direction: merge_same_speaker.py
     repairs over-segmentation, and nothing recovers words from a merge.

  2. NAMING USES A TWO-ENDED AXIS, NOT A THRESHOLD ON ONE VOICEPRINT. Scored by plain
     cosine against a Rafizi reference, 80 Rafizi blocks span 0.473-0.927 and 66 co-host
     blocks span 0.448-0.919 -- the distributions sit on top of each other, because on
     3-second clips of a single recording the cosine is dominated by room and channel, not
     by identity. Only the DIFFERENCE of two class means cancels that common component. So
     the axis needs both ends, and a single voiceprint plus a threshold cannot work here.

  3. THE CO-HOST END IS SEEDED BY THE YB VOCATIVE. Rafizi's end of the axis is safe: all
     39 of his long blocks in ep61 agree with each other. The co-host's end cannot come
     from the label -- 6 of the 8 blocks ep61's raw.md calls Haziq measure as Rafizi -- and
     it cannot come from clustering either, because Rafizi holds 148 of the episode's 175
     minutes, so the pool mean IS Rafizi and 2-means finds noise. `YB` addresses Rafizi, so
     no YB is ever Rafizi speaking. That is the one cue on this corpus that is structural
     rather than stylistic, and the corpus supplies it: median 50 per episode, and all 68
     episodes have at least 4.

  4. SELF-TRAINING REPLACES THE SEED. The YB clips only get the axis pointing the right
     way. One round of re-estimation from the episode's most confidently scored segments
     rebuilds both class means acoustically, which sharpened ep61's reference cosine from
     0.665 to 0.398. More rounds change nothing.

  WHY THIS DOES NOT BREAK THE STANDING RULE. `feedback_never_infer_speaker_from_text` holds:
  register, sentence-continuation, word-overlap and caption `>>` markers have each been
  measurably wrong on this corpus. Text is used here exactly once, to point a microphone at
  a handful of clips, and it is averaged over many instances and then discarded. No turn's
  label is an inference from its own words -- every turn is decided by voice.

WHERE IT STOPS, and this is a hard floor rather than a tuning problem. The three turns it
misses are the three shortest in the passage: `Mana ada cuti?` (0.36s), `Ya.` (0.0s
matched) and `Kita memang beria.` (0.24s). The embedder needs 0.6s. Sub-second backchannels
are out of reach, and turn 8 is also the one the gold data flags as carrying no textual cue
at all, so neither signal reaches it.

HOW THIN THE EVIDENCE IS. One passage, 18 turns, so one turn is 5.6%. The parameters were
tuned on this passage: untuned defaults scored 78%, tuned 83%. Both beat 61%, but only a
second hand-checked passage separates the method from the tuning. Do not read 83% as a
corpus expectation, and do not rewrite any episode from this until a second passage agrees.

Usage:
  python scripts/sense_speakers.py --score              # reproduce the 83% on ep61's gold
  python scripts/sense_speakers.py --episode ep61 --range 105 195   # sense any window
"""
import argparse
import difflib
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")   # RTX 2070 only, never the GTX 970

import numpy as np
import soundfile as sf
import torch

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "audio"
SR = 16000
BLOCK = re.compile(r"\[([\d:]+)\]\s*\*{0,2}([^:\n*]{1,40})\*{0,2}:\s*([^\n]*)")
WORD_TAG = re.compile(r"<(\d\d):(\d\d):(\d\d)\.(\d\d\d)><c>\s*([^<]*)</c>")
CUE = re.compile(r"^(\d\d):(\d\d):(\d\d)\.(\d\d\d) --> (\d\d):(\d\d):(\d\d)\.(\d\d\d)")

DEFAULTS = dict(gap=0.4, floor=0.7, keep=30, rounds=1, clip=3.0, n_clips=16, seed_clip=3.0)
EMBED_MIN = 0.6          # the model's own minimum window, and the residual's cause
_inference = None


# --------------------------------------------------------------------------- captions

def _secs(h, m, s, ms):
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def caption_words(vtt_text):
    """[(word_lower, start_seconds)] per spoken word.

    YouTube cues are a rolling window: each repeats the previous line as plain text and
    adds the new line with per-word tags, so reading cue text counts words two or three
    times. The tagged runs are unique -- plus the FIRST word of each new line, which
    carries no tag and inherits the cue start. That leading word matters: a two-character
    turn like `Ya.` can BE it.
    """
    out, cue_start = [], None
    for line in vtt_text.splitlines():
        m = CUE.match(line)
        if m:
            cue_start = _secs(*m.groups()[:4])
            continue
        if "<c>" not in line:
            continue
        lead = line.split("<", 1)[0].strip()
        if lead and lead != "&gt;&gt;":
            for w in lead.replace("&gt;&gt;", " ").split():
                out.append((w.lower(), cue_start))
        for h, mm, s, ms, w in WORD_TAG.findall(line):
            if w.strip():
                out.append((w.strip().lower(), _secs(h, mm, s, ms)))
    return out


def norm(w):
    return re.sub(r"[^\w']", "", w.lower())


def episode_dir(tag):
    hits = [p for p in (ROOT / "episodes").glob(f"*/*-{tag}-*") if p.is_dir()]
    if len(hits) != 1:
        raise SystemExit(f"{tag} matched {len(hits)} episode folders")
    return hits[0]


def video_id_of(folder):
    raw = (folder / "raw.md").read_text(encoding="utf-8")
    return re.search(r"video_id:\s*(\S+)", raw.split("---")[1]).group(1)


# --------------------------------------------------------------------------- audio

def load_audio(video_id):
    wav = AUDIO / f"_{video_id}.16k.wav"
    if not wav.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(AUDIO / f"{video_id}.m4a"),
                        "-ac", "1", "-ar", str(SR), str(wav)], check=True)
    a, sr = sf.read(wav, dtype="float32")
    assert sr == SR, sr
    return a


def embedder():
    global _inference
    if _inference is None:
        from pyannote.audio import Inference, Model
        m = Model.from_pretrained("pyannote/wespeaker-voxceleb-resnet34-LM",
                                  token=os.environ["HF_TOKEN"])
        _inference = Inference(m, window="whole",
                               device=torch.device("cuda" if torch.cuda.is_available()
                                                   else "cpu"))
    return _inference


def embed_span(audio, t0, t1):
    a, b = int(t0 * SR), int(min(t1, len(audio) / SR) * SR)
    if b - a < int(EMBED_MIN * SR):
        return None
    v = np.asarray(embedder()({"waveform": torch.from_numpy(audio[a:b]).unsqueeze(0),
                               "sample_rate": SR})).reshape(-1)
    return v / np.linalg.norm(v)


def nz(v):
    return v / np.linalg.norm(v)


# --------------------------------------------------------------------------- stage A

def word_gap_segments(caps, gap, tail=0.35):
    out, start, words = [], caps[0][1], [caps[0][0]]
    for i in range(len(caps) - 1):
        if caps[i + 1][1] - caps[i][1] >= gap:
            out.append([start, caps[i][1] + tail, words])
            start, words = caps[i + 1][1], [caps[i + 1][0]]
        else:
            words.append(caps[i + 1][0])
    out.append([start, caps[-1][1] + tail, words])
    return out


def merged_segments(caps, gap, floor, lo=None, hi=None):
    """Word-gap cuts, then absorb anything under `floor` into the neighbour it is closest
    to IN TIME, so every scored unit is real audio and none has to inherit a name.

    The floor is the dominant parameter and it trades the two stages against each other:
    at 0.7 boundary recall is 16/16 and the score 83%; at 1.0 it is 13/16 and 78%; at 1.4
    it is 12/16. Merging to get longer, better-scored segments destroys exactly the
    short-turn boundaries this exists to recover, so keep it as low as the embedder allows.
    """
    segs = word_gap_segments(caps, gap)
    if lo is not None:
        segs = [s for s in segs if lo <= s[0] <= hi]
    changed = True
    while changed:
        changed = False
        for i, s in enumerate(segs):
            if s[1] - s[0] >= floor or len(segs) == 1:
                continue
            g_prev = s[0] - segs[i - 1][1] if i > 0 else float("inf")
            g_next = segs[i + 1][0] - s[1] if i + 1 < len(segs) else float("inf")
            j = i - 1 if g_prev <= g_next else i + 1
            a, b = min(i, j), max(i, j)
            segs[a] = [segs[a][0], segs[b][1], segs[a][2] + segs[b][2]]
            del segs[b]
            changed = True
            break
    return [tuple(s) for s in segs]


# --------------------------------------------------------------------------- stage B

def anchor_spans(folder, anchor, min_dur, exclude):
    """Long blocks under the trusted anchor label. Long is the part of raw.md that IS
    reliable; the defect being chased is short turns."""
    blocks = BLOCK.findall((folder / "raw.md").read_text(encoding="utf-8"))
    out = []
    for i, (ts, lab, _) in enumerate(blocks):
        if lab.strip() != anchor:
            continue
        p = [int(x) for x in ts.split(":")]
        a = p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]
        q = blocks[i + 1][0].split(":") if i + 1 < len(blocks) else None
        if q:
            q = [int(x) for x in q]
            b = q[0] * 3600 + q[1] * 60 + q[2] if len(q) == 3 else q[0] * 60 + q[1]
        else:
            b = a + 30
        if b - a >= min_dur and not (exclude[0] <= a <= exclude[1]):
            out.append((a, b))
    return out


def reference(audio, spans, clip, n_clips, margin=0.15):
    """Mean unit embedding of clips across the interior of the longest spans. The interior
    margin keeps a block boundary that is off by a second out of the reference."""
    vecs = []
    for a, b in sorted(spans, key=lambda s: s[1] - s[0], reverse=True):
        ia, ib = a + (b - a) * margin, b - (b - a) * margin
        room = ib - ia
        if room < clip:
            continue
        k = max(1, min(6, int(room // clip)))
        for j in range(k):
            t0 = ia + j * (room - clip) / max(1, k - 1) if k > 1 else ia
            v = embed_span(audio, t0, t0 + clip)
            if v is not None:
                vecs.append(v)
        if len(vecs) >= n_clips:
            break
    if not vecs:
        return None, 0
    V = np.stack(vecs[:n_clips])
    return nz(V.mean(0)), len(V)


def raw_word_times(folder, caps):
    """Timestamp every word of raw.md by aligning it to the caption word stream.

    raw.md is the reviewed text and carries clean `YB`; the captions carry the clock but
    garble YB into `webb`, `wabi`, `obi`. One global difflib pass pins raw.md's words to
    caption times even across a garble, because the words either side of it still match.
    """
    body = (folder / "raw.md").read_text(encoding="utf-8").split("---", 2)[2]
    toks, yb = [], []
    for m in BLOCK.finditer(body):
        for w in re.findall(r"[\w']+", m.group(3)):
            if norm(w):
                toks.append(norm(w))
                yb.append(w.upper() == "YB")
    sm = difflib.SequenceMatcher(a=toks, b=[w for w, _ in caps], autojunk=False)
    times = [None] * len(toks)
    for i, j, k in sm.get_matching_blocks():
        for d in range(k):
            times[i + d] = caps[j + d][1]
    return [(times[i], yb[i]) for i in range(len(toks)) if times[i] is not None]


def yb_seed_spans(folder, caps, gap, clip, exclude):
    """One clip-long span per YB occurrence, centred on the segment containing it."""
    segs = word_gap_segments(caps, gap)
    spans, seen = [], set()
    for t, is_yb in raw_word_times(folder, caps):
        if not is_yb or exclude[0] <= t <= exclude[1]:
            continue
        hit = next(((a, b) for a, b, _ in segs if a - 0.4 <= t <= b + 0.4), None)
        if hit is None or hit in seen:
            continue
        seen.add(hit)
        a, b = hit
        if b - a < clip:
            mid = (a + b) / 2
            a, b = mid - clip / 2, mid + clip / 2
        spans.append((a, min(b, a + clip)))
    return spans


def axis_of(ref_a, ref_b):
    ax = nz(ref_a - ref_b)
    return ax, float(((ref_a + ref_b) / 2) @ ax)


def build_axis(audio, folder, caps, cfg, anchor, exclude, report=True):
    ref_a, n_a = reference(audio, anchor_spans(folder, anchor, 60, exclude),
                           cfg["clip"], cfg["n_clips"])
    if ref_a is None:
        raise SystemExit(f"no usable {anchor} reference blocks >= 60s")

    seeds = yb_seed_spans(folder, caps, cfg["gap"], cfg["seed_clip"], exclude)
    vecs = [v for v in (embed_span(audio, a, b) for a, b in seeds) if v is not None]
    if len(vecs) < 4:
        raise SystemExit(f"only {len(vecs)} usable YB seeds -- too few to aim an axis")
    ref_b = nz(np.stack(vecs).mean(0))
    ax, mid = axis_of(ref_a, ref_b)

    good = [v for v in vecs if float(v @ ax) - mid < 0]
    if good and len(good) < len(vecs):
        ref_b = nz(np.stack(good).mean(0))
        ax, mid = axis_of(ref_a, ref_b)
    if report:
        print(f"seed axis  : {anchor} {n_a} clips / co-host {len(good)} YB clips "
              f"({len(vecs) - len(good)} dropped as wrong-side)")
        print(f"             reference cosine {float(ref_a @ ref_b):.3f}")

    # self-training: rebuild both class means from the most confident segments
    pool = [s for s in merged_segments(caps, cfg["gap"], cfg["floor"])
            if not (exclude[0] <= s[0] <= exclude[1])]
    pool = pool[::max(1, len(pool) // 500)]
    V = np.stack([v for v in (embed_span(audio, a, min(b, a + 6.0)) for a, b, _ in pool)
                  if v is not None])
    for r in range(cfg["rounds"]):
        sc = V @ ax - mid
        order = np.argsort(sc)
        n_b = min(cfg["keep"], max(4, int((sc < 0).sum())))
        n_r = min(cfg["keep"], max(4, int((sc > 0).sum())))
        ref_b, ref_a = nz(V[order[:n_b]].mean(0)), nz(V[order[-n_r:]].mean(0))
        ax, mid = axis_of(ref_a, ref_b)
        if report:
            print(f"self-train : round {r + 1} over {len(V)} segments -> "
                  f"co-host {n_b} / {anchor} {n_r} clips, "
                  f"reference cosine {float(ref_a @ ref_b):.3f}")
    if float(ref_a @ ref_b) > 0.85:
        raise SystemExit("REFUSED: the two voices did not separate. A collapsed axis "
                         "silently labels everything one name -- see bake-off v2.")
    return ax, mid


def sense(audio, caps, ax, mid, cfg, lo, hi, anchor, cohost):
    out = []
    for t0, t1, words in merged_segments(caps, cfg["gap"], cfg["floor"], lo, hi):
        v = embed_span(audio, t0, t1)
        if v is None:
            continue
        sc = float(v @ ax) - mid
        out.append({"t0": t0, "t1": t1, "words": words, "score": sc,
                    "name": anchor if sc > 0 else cohost})
    return out


# --------------------------------------------------------------------------- scoring

def gold_align(gold, caps):
    """Put the gold turns on the clock. Text matching must be fuzzy: the ASR turned
    `Biarkan saya mengigil` into `Misalkan tak panas ke pelut`, so an exact search would
    silently skip the worst cases. One global pass also cannot reorder turns."""
    cap_words = [w for w, _ in caps]
    toks, owner = [], []
    for t in gold["turns"]:
        for w in re.findall(r"[\w']+", t["text"].lower()):
            if norm(w):
                toks.append(norm(w))
                owner.append(t["n"])
    sm = difflib.SequenceMatcher(a=toks, b=cap_words, autojunk=False)
    hits = defaultdict(list)
    for i, j, k in sm.get_matching_blocks():
        for d in range(k):
            hits[owner[i + d]].append(caps[j + d][1])
    turns = []
    for t in gold["turns"]:
        ts = hits.get(t["n"])
        turns.append({**t, "t0": min(ts) if ts else None, "t1": max(ts) if ts else None})
    for i, t in enumerate(turns):
        if t["t0"] is None:
            prv = next((turns[j]["t1"] for j in range(i - 1, -1, -1) if turns[j]["t1"]), None)
            nxt = next((turns[j]["t0"] for j in range(i + 1, len(turns)) if turns[j]["t0"]), None)
            if prv and nxt and nxt > prv:
                t["t0"], t["t1"] = prv, nxt
    return turns


def score(turns, segs):
    rows, correct = [], 0
    for i, t in enumerate(turns):
        e0 = t["t0"]
        e1 = turns[i + 1]["t0"] if i + 1 < len(turns) else t["t1"] + 1.0
        signed, seen = 0.0, False
        for s in segs:
            o = max(0.0, min(e1, s["t1"]) - max(e0, s["t0"]))
            if o > 0:
                signed += o * s["score"]
                seen = True
        pred = ("Rafizi" if signed > 0 else "Haziq") if seen else "(none)"
        ok = pred == t["speaker"]
        correct += ok
        rows.append((t, pred, ok, signed))
    return rows, correct


def boundary_recall(turns, segs, tol=0.75):
    changes = [(turns[i]["t1"], turns[i + 1]["t0"]) for i in range(len(turns) - 1)
               if turns[i]["speaker"] != turns[i + 1]["speaker"]]
    hit = sum(1 for a, b in changes
              if any(abs(s["t0"] - (a + b) / 2) <= tol or abs(s["t1"] - (a + b) / 2) <= tol
                     for s in segs))
    return hit, len(changes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episode", default="ep61")
    ap.add_argument("--anchor", default="Rafizi", help="the trusted label; he is in all 67")
    ap.add_argument("--cohost", default="Haziq")
    ap.add_argument("--range", nargs=2, type=float, metavar=("LO", "HI"))
    ap.add_argument("--score", action="store_true", help="score against the gold passage")
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

    gold = turns = None
    if a.score:
        gd = json.loads((ROOT / "data" / "speaker_ground_truth.json").read_text(encoding="utf-8"))
        key = next((k for k in gd if not k.startswith("_") and k.endswith(a.episode)), None)
        if key is None:
            raise SystemExit(f"no gold passage for {a.episode}")
        gold = gd[key]
        turns = gold_align(gold, caps)
        lo, hi = min(t["t0"] for t in turns) - 5, max(t["t1"] for t in turns) + 5
    else:
        if not a.range:
            raise SystemExit("give --range LO HI, or --score to use the gold passage")
        lo, hi = a.range

    exclude = (lo - 30, hi + 30)
    print(f"{a.episode}  video {vid}  window {lo:.0f}-{hi:.0f}s   "
          f"(reference material excludes {exclude[0]:.0f}-{exclude[1]:.0f}s)")
    ax, mid = build_axis(audio, folder, caps, cfg, a.anchor, exclude)
    segs = sense(audio, caps, ax, mid, cfg, lo, hi, a.anchor, a.cohost)
    print(f"sensed     : {len(segs)} segments, each scored on its own audio\n")

    if not a.score:
        for s in segs:
            print(f"  [{int(s['t0']) // 60:02d}:{int(s['t0']) % 60:02d}] "
                  f"{s['name']:8} {s['score']:+.3f}  {' '.join(s['words'])[:66]}")
        return

    rows, correct = score(turns, segs)
    hit, tot = boundary_recall(turns, segs)
    print(f"{'#':>3} {'GOLD':7} {'SENSED':7} {'':4} {'signed':>8} text")
    for t, pred, ok, sc in rows:
        print(f"{t['n']:>3} {t['speaker']:7} {pred:7} {'ok ' if ok else 'BAD':4} "
              f"{sc:>+8.3f} {t['text'][:48]}")
    n = len(rows)
    print(f"\n  STAGE A boundary recall: {hit}/{tot} = {hit / tot:.0%}")
    print(f"  STAGE B end-to-end:      {correct}/{n} = {correct / n:.0%}   (raw.md = 61%)")
    by = defaultdict(lambda: [0, 0])
    for t, pred, ok, _ in rows:
        by[t["speaker"]][1] += 1
        by[t["speaker"]][0] += ok
    print("  " + "   ".join(f"{k} {c}/{tot_}" for k, (c, tot_) in sorted(by.items()))
          + "      (raw.md: Haziq 9/9, Rafizi 2/9)")


if __name__ == "__main__":
    main()
