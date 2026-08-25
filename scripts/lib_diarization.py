"""Speaker diarization for local-ASR episodes, via pyannote.audio.

Purely acoustic (voice-embedding clustering) -- no LLM involved, so it's immune to
everything that makes Gemini's built-in diarization unreliable on some episodes:
PROHIBITED_CONTENT blocks forcing a fallback model, degradation under retry stress,
and per-run label inconsistency (the same real speaker getting a different invented
name in different transcription attempts, confirmed directly on ep13/ep39).

Requires a Hugging Face token with access to 3 gated repos -- accept terms for all
three at huggingface.co, then set HF_TOKEN:
  - pyannote/segmentation-3.0
  - pyannote/speaker-diarization-3.1
  - pyannote/speaker-diarization-community-1 (a transitive dependency of the above)

Output is anonymous "Speaker N" labels, numbered by first appearance and consistent
within an episode (since they're real voice clusters, not per-utterance guesses) --
still needs a manual naming pass afterward, same as Gemini's generic labels do.
"""
import os

# Hard rule, not just an optimization: this machine's second GPU (GTX 970) causes
# torch to intermittently deadlock on long-running CUDA/threading work when both
# GPUs are visible (confirmed, see lib_local_asr.py's docstring) and is also too
# old for this project's cuDNN build (SM 5.2, needs SM >= 7.5) -- it must never be
# used. Set independently here (not just in lib_local_asr.py) so this holds even
# when this module is imported standalone, before torch initializes a CUDA context.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

import torch
from pyannote.audio import Pipeline

_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=os.environ["HF_TOKEN"])
        if torch.cuda.is_available():
            _pipeline.to(torch.device("cuda"))
    return _pipeline


def diarize(audio_array, sample_rate):
    """Returns a list of (start_seconds, end_seconds, speaker_label) turns, sorted by
    start time. Takes an already-decoded mono waveform (e.g. from soundfile, matching
    what lib_local_asr already loads for the ASR pass) rather than a file path --
    pyannote's own file-loading path depends on torchcodec, which can't find a
    compatible FFmpeg binding on Windows against this project's ffmpeg install
    (confirmed: fails to load libtorchcodec against every bundled FFmpeg version 4-9).
    Feeding a pre-loaded waveform bypasses that code path entirely."""
    pipeline = _get_pipeline()
    waveform = torch.from_numpy(audio_array).float().unsqueeze(0)  # (1, samples), mono
    output = pipeline({"waveform": waveform, "sample_rate": sample_rate})
    seen = {}
    segments = []
    # exclusive_speaker_diarization has overlapping speech turns resolved to a single
    # speaker each -- exactly what merging onto non-overlapping ASR chunks needs.
    for turn, _, speaker in output.exclusive_speaker_diarization.itertracks(yield_label=True):
        if speaker not in seen:
            seen[speaker] = f"Speaker {len(seen) + 1}"
        segments.append((turn.start, turn.end, seen[speaker]))
    segments.sort(key=lambda s: s[0])
    return segments


def label_for_range(segments, start, end):
    """Speaker label with the most time overlap with [start, end); None if no overlap."""
    best_label, best_overlap = None, 0.0
    for seg_start, seg_end, label in segments:
        overlap = min(end, seg_end) - max(start, seg_start)
        if overlap > best_overlap:
            best_overlap, best_label = overlap, label
    return best_label
