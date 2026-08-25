"""Precise word-level timestamps for diarization, via torchaudio's official MMS
forced aligner (pure Python, no native extension -- the ctc-forced-aligner PyPI
package needs a C++ extension that fails to build on this Windows/Python 3.14
setup: `error LNK2001: unresolved external symbol PyInit_align_ops`, no
prebuilt wheel exists for this platform). Used to split each ASR chunk's
already-good transcription into per-word timestamps for per-word speaker
labeling, instead of labeling the whole chunk with one dominant speaker (the
confirmed cause of silently swallowing short interjections -- see
ARCHITECTURE.md).

Numbers and punctuation-only tokens (e.g. "RM11,000") have no alignable
letters in the MMS label set (a-z plus apostrophe), so their timestamps are
interpolated from neighboring aligned words rather than computed directly.
"""
import os
import re

# Hard rule, not just an optimization: this machine's second GPU (GTX 970) causes
# torch to intermittently deadlock on long-running CUDA/threading work when both
# GPUs are visible (confirmed, see lib_local_asr.py's docstring) and is also too
# old for this project's cuDNN build (SM 5.2, needs SM >= 7.5) -- it must never be
# used. Set independently here (not just in lib_local_asr.py) so this holds even
# when this module is imported standalone, before torch initializes a CUDA context.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

import torch
import torchaudio
from torchaudio.pipelines import MMS_FA

_model = None
_tokenizer = None
_aligner = None


def _get_aligner():
    global _model, _tokenizer, _aligner
    if _model is None:
        _model = MMS_FA.get_model()
        _model.eval()
        # Needs torchaudio's CUDA build (matching torch's own cu130 build) installed
        # via `pip install torchaudio==<ver>+cu130 --index-url
        # https://download.pytorch.org/whl/cu130` -- the default PyPI torchaudio wheel
        # is CPU-only and only registers a CPU kernel for the forced_align op, so
        # moving this model to CUDA against that wheel fails outright ("no kernel
        # found"), not just runs slower. Confirmed ~10x slower per chunk on CPU during
        # the ep13 redo before this was fixed.
        if torch.cuda.is_available():
            _model.to(torch.device("cuda"))
        _tokenizer = MMS_FA.get_tokenizer()
        _aligner = MMS_FA.get_aligner()
    return _model, _tokenizer, _aligner


def _normalize(token):
    return re.sub(r"[^a-z']", "", token.lower())


def align_words(text, audio_array, sr):
    """Returns [(original_token, start_seconds, end_seconds), ...] for every
    whitespace-separated token in `text`, in order, timed against
    `audio_array` (mono, sample rate `sr`). Tokens with no alignable letters
    get timestamps interpolated from their nearest aligned neighbors."""
    tokens = text.split()
    if not tokens:
        return []

    model, tokenizer, aligner = _get_aligner()
    device = next(model.parameters()).device

    norm = [_normalize(t) for t in tokens]
    alignable_idx = [i for i, n in enumerate(norm) if n]
    if not alignable_idx:
        return [(t, 0.0, 0.0) for t in tokens]

    waveform = torch.from_numpy(audio_array).float().unsqueeze(0)
    if sr != MMS_FA.sample_rate:
        waveform = torchaudio.functional.resample(waveform, sr, MMS_FA.sample_rate)
    waveform = waveform.to(device)
    duration = audio_array.shape[-1] / sr

    with torch.inference_mode():
        emission, _ = model(waveform)
        try:
            token_spans = aligner(emission[0], tokenizer([norm[i] for i in alignable_idx]))
        except RuntimeError as e:
            if "targets length is too long for CTC" not in str(e):
                raise
            # CTC forced alignment requires the (expanded, blank-separated) target
            # sequence to be no longer than the emission's frame count -- violated when
            # the ASR chunk itself degenerated into a repetition-loop hallucination
            # (confirmed directly: a ~140k-char repeat produced an 889-token target
            # against a 114-frame emission). Not alignable at all in that case; fall
            # back to one span covering the whole chunk, same as the old chunk-level
            # behavior, so the transcription still comes through and qa_check.py's
            # repetition-loop detector can flag it same as ever.
            return [(t, 0.0, duration) for t in tokens]
    ratio = waveform.size(1) / emission.size(1) / MMS_FA.sample_rate

    aligned = {}
    for i, spans in zip(alignable_idx, token_spans):
        aligned[i] = (spans[0].start * ratio, spans[-1].end * ratio)

    results = [None] * len(tokens)
    for i, span in aligned.items():
        results[i] = span
    prev_end = 0.0
    for i in range(len(tokens)):
        if results[i] is not None:
            prev_end = results[i][1]
            continue
        j = i + 1
        while j < len(tokens) and results[j] is None:
            j += 1
        next_start = results[j][0] if j < len(tokens) else prev_end
        results[i] = (prev_end, next_start)

    return [(tokens[i], results[i][0], results[i][1]) for i in range(len(tokens))]
