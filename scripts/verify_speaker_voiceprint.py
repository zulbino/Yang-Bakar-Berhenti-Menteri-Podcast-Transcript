"""Check raw.md speaker labels against voiceprints, without asking any LLM.

Why this exists. Every earlier speaker check was either textual (does this line read
like something Rafizi would say) or asked a model to listen and guess. Both share a
blind spot: they judge one episode in isolation, so an episode where the diarizer
merged everyone into one cluster and the review pass then named that cluster after
whoever it saw first looks perfectly self-consistent. Seven episodes sat like that for
months, with Rafizi's words filed under a co-host's name (see ENGINEERING_LOG.md 1.27).

The fix is comparison across episodes. Rafizi appears in all 67, so his voice can be
averaged from episodes whose labels are already trusted, and any cluster in any episode
can then be scored against that average. Cosine similarity on speaker embeddings, no
transcript involved, so it is independent of every text heuristic in this repo.

Reading the numbers. Build each reference from at least two episodes and look at the
printed self-agreement first: that is the same person scored against himself across
different recordings, so it is the ceiling this method can reach. On this corpus Rafizi
scores ~0.93 against himself, correct labels land 0.94-0.97, and different people land
0.30-0.50. A reference whose self-agreement is low is not usable, and no score below it
means much.

Two traps worth knowing:

  - Short spans lie, and they lie further than you would guess. A span is measured from
    a block's timestamp to the next block's, and raw.md blocks are coarse, so a brief
    interjection's window bleeds into the neighbouring speaker's audio. Anything under
    about a minute of total speech scores toward whoever surrounds it; the report marks
    those. But the effect does not stop there: ep51's Haziq label covers 10.4 minutes
    across 54 short interjections and scores only 0.635 and 0.616 against the two Haziq
    references, which agree with each other at 0.921 -- and the owner confirmed by ear
    that every sampled turn really is Haziq.

    So a mid-range score on a cluster made of interjections is not evidence of anything.
    Treat roughly 0.60-0.80 as unresolvable by this method whenever the cluster's turns
    are short, no matter how many minutes they add up to, and go to the video or ask
    someone who knows the audio. Only a cluster with long continuous turns earns a
    verdict from a number in that range.
  - A co-host reference built only from brief interjections inherits that same bleed,
    which is why the co-host references here read high against Rafizi. Compare which
    reference wins by how much, not a score against one threshold.

Usage:
  python scripts/verify_speaker_voiceprint.py --episodes ep24 ep36
  python scripts/verify_speaker_voiceprint.py --episodes ep42 --per-block "Zikri Kamarulzaman"
  python scripts/verify_speaker_voiceprint.py --all-suspect

Audio is expected in audio/<video_id>.m4a (scripts/yt_download.py puts it there) and is
decoded to a cached 16 kHz mono wav beside it.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")  # RTX 2070 only, never the GTX 970

if "HF_TOKEN" not in os.environ and sys.platform == "win32":
    # A fresh shell does not inherit User-scope environment variables, and this script
    # is usually run from one. Read the token where setx actually put it.
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            os.environ["HF_TOKEN"], _ = winreg.QueryValueEx(k, "HF_TOKEN")
    except FileNotFoundError:
        pass

import numpy as np
import soundfile as sf
import torch
from pyannote.audio import Inference, Model

sys.path.insert(0, str(Path(__file__).resolve().parent))
from yt_download import _ffmpeg_location

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "audio"
SR = 16000
BLOCK_RE = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]\s*([^:\n]{1,40}):(.*)$", re.M)

# Episodes whose labels are trusted, used to average each person's voice. Rafizi's come
# from episodes where his label already holds 97%+ of the text, so long stretches there
# are him with near-certainty. The co-hosts have no such episode -- they only ever
# interject -- so treat their references as indicative, per the docstring.
DEFAULT_REFERENCES = {
    "Rafizi": [("ep41", "Rafizi"), ("ep58", "Rafizi")],
    "Haziq": [("ep48", "Haziq"), ("ep33", "Haziq"), ("ep19", "Haziq")],
    "Farhan (Pa'an)": [("ep29", "Farhan (Pa'an)"), ("ep50", "Farhan (Pa'an)"),
                       ("ep32", "Farhan (Pa'an)")],
}
SHORT_SPAN_MINUTES = 1.0
CLIP_SECONDS = 8.0
# A cluster whose individual turns average shorter than this cannot be scored reliably,
# however many minutes it totals: every sampling window catches the neighbouring speaker.
# ep51's Haziq is 10.4 minutes of 11-second turns and reads 0.635 against a reference that
# agrees with itself at 0.921, yet the label is correct (confirmed by ear).
MIN_MEAN_TURN_SECONDS = 20.0

_inference = None


def _embedder():
    global _inference
    if _inference is None:
        model = Model.from_pretrained("pyannote/wespeaker-voxceleb-resnet34-LM",
                                      token=os.environ["HF_TOKEN"])
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        _inference = Inference(model, window="whole", device=device)
    return _inference


def episode_dir(tag):
    matches = glob.glob(str(ROOT / "episodes" / "*" / f"*-{tag}-*"))
    if len(matches) != 1:
        raise SystemExit(f"{tag} matched {len(matches)} episode folders: {matches}")
    return Path(matches[0])


def read_episode(tag):
    raw = (episode_dir(tag) / "raw.md").read_text(encoding="utf-8")
    video_id = re.search(r"video_id:\s*(\S+)", raw.split("---")[1]).group(1)
    return video_id, BLOCK_RE.findall(raw)


def load_audio(video_id):
    wav = AUDIO_DIR / f"_{video_id}.16k.wav"
    if not wav.exists():
        src = AUDIO_DIR / f"{video_id}.m4a"
        if not src.exists():
            raise FileNotFoundError(src)
        subprocess.run([str(_ffmpeg_location()), "-v", "error", "-y", "-i", str(src),
                        "-ac", "1", "-ar", str(SR), str(wav)], check=True)
    audio, sr = sf.read(wav, dtype="float32")
    assert sr == SR, sr
    return audio


def to_seconds(stamp):
    parts = [int(p) for p in stamp.split(":")]
    return parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]


def label_spans(blocks, audio_seconds):
    """Wall-clock spans per label. A block's timestamp marks where it starts, so it runs
    until the next block starts."""
    spans = {}
    for i, (stamp, label, _) in enumerate(blocks):
        start = to_seconds(stamp)
        end = to_seconds(blocks[i + 1][0]) if i + 1 < len(blocks) else audio_seconds
        if end - start < 2:
            continue
        spans.setdefault(label.strip(), []).append((start, min(end, audio_seconds)))
    return spans


def embed(audio, spans, max_clips=12):
    """Mean unit embedding over the longest spans, each sampled at its midpoint."""
    inference = _embedder()
    vectors = []
    for start, end in sorted(spans, key=lambda s: s[1] - s[0], reverse=True)[:max_clips]:
        middle = (start + end) / 2
        a = int(max(0, middle - CLIP_SECONDS / 2) * SR)
        b = int(min(len(audio) / SR, middle + CLIP_SECONDS / 2) * SR)
        if b - a < CLIP_SECONDS * SR * 0.6:
            continue
        vector = np.asarray(inference({"waveform": torch.from_numpy(audio[a:b]).unsqueeze(0),
                                       "sample_rate": SR})).reshape(-1)
        vectors.append(vector / np.linalg.norm(vector))
    if not vectors:
        return None
    mean = np.mean(vectors, axis=0)
    return mean / np.linalg.norm(mean)


def build_references(references):
    built = {}
    for who, sources in references.items():
        vectors, tags = [], []
        for tag, label in sources:
            try:
                video_id, blocks = read_episode(tag)
                audio = load_audio(video_id)
            except (FileNotFoundError, SystemExit) as exc:
                print(f"[ref {who}] {tag} unavailable ({exc.__class__.__name__}), skipped")
                continue
            spans = label_spans(blocks, len(audio) / SR).get(label, [])
            if not spans:
                print(f"[ref {who}] {tag} has no {label!r} blocks, skipped")
                continue
            vector = embed(audio, spans, max_clips=14)
            if vector is not None:
                vectors.append(vector)
                tags.append(tag)
        if not vectors:
            print(f"[ref {who}] NO REFERENCE BUILT")
            continue
        agreement = [f"{tags[i]}~{tags[j]}={float(np.dot(vectors[i], vectors[j])):.3f}"
                     for i in range(len(vectors)) for j in range(i + 1, len(vectors))]
        mean = np.mean(vectors, axis=0)
        built[who] = mean / np.linalg.norm(mean)
        print(f"[ref {who:16}] {tags}  self-agreement: {' '.join(agreement) or 'n/a (single episode)'}")
    if not built:
        raise SystemExit("no references could be built -- check audio/ and HF_TOKEN")
    return built


def score_episode(tag, references, per_block=None):
    video_id, blocks = read_episode(tag)
    audio = load_audio(video_id)
    spans = label_spans(blocks, len(audio) / SR)
    print(f"\n=== {tag} ({video_id})")
    result = {}
    for label, label_spans_ in sorted(spans.items(), key=lambda kv: -sum(e - s for s, e in kv[1])):
        minutes = sum(e - s for s, e in label_spans_) / 60
        mean_turn = (minutes * 60) / len(label_spans_)
        vector = embed(audio, label_spans_)
        if vector is None:
            continue
        scores = {who: float(np.dot(vector, ref)) for who, ref in references.items()}
        best = max(scores, key=scores.get)
        runner_up = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0
        if scores[best] > 0.55 and scores[best] - runner_up > 0.10:
            verdict = f"-> {best}"
        elif max(scores.values()) < 0.50:
            verdict = "-> not a known speaker (guest)"
        else:
            verdict = "-> inconclusive"
        if minutes < SHORT_SPAN_MINUTES:
            verdict += "  [span too short to trust]"
        elif (mean_turn < MIN_MEAN_TURN_SECONDS and not verdict.startswith("-> not")
              and not (scores[best] >= 0.85 and scores[best] - runner_up >= 0.15)):
            # An interjection-shaped cluster has its score dragged toward its neighbours,
            # so a mid-range number here means nothing. A high score with a clear margin
            # still stands: bleed can pull a score down or muddle it, but it cannot
            # manufacture 0.87 against the right reference and 0.65 against the next one.
            verdict = (f"-> UNRESOLVABLE, turns average {mean_turn:.0f}s "
                       f"(check the video or ask; do not relabel on this score)")
        rendered = "  ".join(f"{who.split()[0]}={score:+.3f}" for who, score in scores.items())
        print(f"   {label:26} {minutes:6.1f} min   {rendered}   {verdict}")
        result[label] = {"minutes": round(minutes, 1),
                         **{who: round(score, 3) for who, score in scores.items()}}

    for label in per_block or []:
        chosen = [s for s in spans.get(label, []) if s[1] - s[0] >= 6]
        chosen = sorted(chosen, key=lambda s: -(s[1] - s[0]))[:26]
        rows = []
        for span in chosen:
            vector = embed(audio, [span], max_clips=1)
            if vector is not None:
                rows.append((span[0], {w: float(np.dot(vector, r)) for w, r in references.items()}))
        if not rows:
            print(f"   [per-block] {label}: no usable blocks")
            continue
        print(f"   [per-block] {label}  ({len(rows)} blocks)")
        for who in references:
            values = np.array([r[1][who] for r in rows])
            print(f"        vs {who:16} mean={values.mean():+.3f} sd={values.std():.3f} max={values.max():+.3f}")
        print("        a low spread means one voice; a high one means the label merges speakers")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--episodes", nargs="*", default=[], metavar="TAG")
    ap.add_argument("--all-suspect", action="store_true",
                    help="scan every episode whose dominant label is not Rafizi")
    ap.add_argument("--per-block", nargs="*", default=[], metavar="LABEL",
                    help="also report block-by-block scores for these labels")
    ap.add_argument("--json", metavar="PATH")
    args = ap.parse_args()

    episodes = list(args.episodes)
    if args.all_suspect:
        for d in sorted(glob.glob(str(ROOT / "episodes" / "*" / "*"))):
            raw_path = Path(d) / "raw.md"
            if not raw_path.exists():
                continue
            blocks = BLOCK_RE.findall(raw_path.read_text(encoding="utf-8"))
            if not blocks:
                continue
            totals = {}
            for _, label, text in blocks:
                totals[label.strip()] = totals.get(label.strip(), 0) + len(text)
            if max(totals, key=totals.get) != "Rafizi":
                episodes.append(re.search(r"-(ep\d+)-", d).group(1))
    if not episodes:
        ap.error("nothing to check -- pass --episodes or --all-suspect")

    references = build_references(DEFAULT_REFERENCES)
    out = {tag: score_episode(tag, references, args.per_block) for tag in dict.fromkeys(episodes)}
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1), encoding="utf-8")
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
