"""Local ASR fallback for the raw transcription stage, used when the Gemini API is
unavailable (e.g. billing blocked). Runs mesolitica/malaysian-whisper-medium-v2
locally with VAD-based chunking.

Validated against mesolitica/malaysian-distil-whisper-large-v3, malaysian-whisper-small-v3,
and plain openai/whisper-large-v3 on this podcast's content -- medium-v2 was the most
reliable of the four, with no repetition-loop hallucinations on a 13-minute clip and
~55 minutes of a real episode.

Speaker diarization is a separate pass via lib_diarization.py (pyannote.audio,
purely acoustic, no LLM) -- each VAD chunk gets labeled with whichever diarized
speaker has the most time overlap with it. Output is `[MM:SS] Speaker N: text`,
matching Gemini raw.md's turn format closely enough for the same downstream
qa_check.py/rewrite-stage parsing to work unmodified.

Debugging history worth knowing before changing this file's call pattern:
  - On a machine with a second, CUDA-incompatible GPU present (here: an old GTX 970
    alongside the RTX 2070 actually used), torch intermittently deadlocks on
    long-running CUDA/threading work with both GPUs visible -- hangs silently at
    ~0% CPU, no error, reproducing at different, seemingly arbitrary points across
    separate runs (mid-VAD, mid-transcription at different chunk indices). Confirmed
    fixed by hiding every GPU but the first via CUDA_VISIBLE_DEVICES before torch
    initializes. Set unconditionally here since it's harmless on single-GPU machines.
  - This was initially misdiagnosed as a resource leak from calling pipe() once per
    chunk in a plain loop, "fixed" by switching to the pipeline's generator/dataset
    invocation (`pipe(generator(), ...)`) instead. That switch was wrong: it does
    avoid the hang, but only because it happens to sidestep the actual GPU-enumeration
    bug above, at the cost of a ~6x slowdown (each chunk went from ~2s to ~12s,
    turning an ~11 minute transcription into over an hour), most likely from
    per-item DataLoader/worker overhead on Windows. Now that the real cause is fixed
    via CUDA_VISIBLE_DEVICES, plain per-chunk pipe() calls are both fast and stable --
    don't reintroduce the generator pattern without re-confirming it's still needed.
  - Whisper's default multi-temperature fallback decoding is left enabled (no
    `temperature` override) since it's what detects and escapes repetition-loop
    hallucinations (e.g. a chunk degenerating into "that, that, that...").
"""
import os

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

import shutil
import subprocess
import time
from pathlib import Path

import soundfile as sf
import torch
from transformers import pipeline

import lib_diarization
from yt_download import _FFMPEG_FALLBACK

MODEL = "mesolitica/malaysian-whisper-medium-v2"
MAX_CHUNK_S = 28.0
MERGE_GAP_S = 0.4

_pipe = None


def _get_pipe():
    global _pipe
    if _pipe is None:
        _pipe = pipeline(
            "automatic-speech-recognition",
            model=MODEL,
            device=0 if torch.cuda.is_available() else -1,
            dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
        )
    return _pipe


def _ffmpeg_exe():
    return shutil.which("ffmpeg") or str(_FFMPEG_FALLBACK)


def _decode_to_wav(audio_path):
    wav_path = audio_path.with_suffix(".vad16k.wav")
    subprocess.run(
        [
            _ffmpeg_exe(), "-y", "-i", str(audio_path),
            "-ar", "16000", "-ac", "1", "-f", "wav", str(wav_path),
        ],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return wav_path


def _vad_chunks(audio_array, sr):
    from silero_vad import get_speech_timestamps, load_silero_vad

    vad_model = load_silero_vad()
    speech_ts = get_speech_timestamps(
        torch.from_numpy(audio_array), vad_model, sampling_rate=sr,
        return_seconds=True, min_silence_duration_ms=300, speech_pad_ms=100,
    )

    chunks = []
    cur_start, cur_end = None, None
    for seg in speech_ts:
        s, e = seg["start"], seg["end"]
        if cur_start is None:
            cur_start, cur_end = s, e
        elif s - cur_end <= MERGE_GAP_S and (e - cur_start) <= MAX_CHUNK_S:
            cur_end = e
        else:
            chunks.append((cur_start, cur_end))
            cur_start, cur_end = s, e
    if cur_start is not None:
        chunks.append((cur_start, cur_end))
    return chunks


def _format_timestamp(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def transcribe_raw_local(audio_path, duration_seconds):
    wav_path = _decode_to_wav(Path(audio_path))
    try:
        audio_array, sr = sf.read(str(wav_path), dtype="float32")

        print("  diarizing speakers ...", flush=True)
        diarization = lib_diarization.diarize(audio_array, sr)

        chunks = _vad_chunks(audio_array, sr)
        pipe = _get_pipe()
        print(f"  local ASR: {len(chunks)} chunks to transcribe", flush=True)

        lines = []
        t0 = time.time()
        for i, (start, end) in enumerate(chunks):
            i0, i1 = int(start * sr), int(end * sr)
            segment = audio_array[i0:i1]
            out = pipe({"array": segment, "sampling_rate": sr}, return_timestamps=True)
            text = out["text"].strip()
            if text:
                speaker = lib_diarization.label_for_range(diarization, start, end) or "Speaker ?"
                lines.append(f"[{_format_timestamp(start)}] {speaker}: {text}")
            if (i + 1) % 20 == 0 or i + 1 == len(chunks):
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                eta = (len(chunks) - i - 1) / rate
                print(f"  local ASR: {i+1}/{len(chunks)} chunks, {elapsed:.0f}s elapsed, ETA {eta:.0f}s", flush=True)
        return "\n\n".join(lines) + "\n"
    finally:
        wav_path.unlink(missing_ok=True)
