"""Local ASR fallback for the raw transcription stage, used when the Gemini API is
unavailable (e.g. billing blocked). Runs mesolitica/malaysian-whisper-medium-v2
locally with VAD-based chunking.

Validated against mesolitica/malaysian-distil-whisper-large-v3, malaysian-whisper-small-v3,
and plain openai/whisper-large-v3 on this podcast's content -- medium-v2 was the most
reliable of the four, with no repetition-loop hallucinations on a 13-minute clip and
~55 minutes of a real episode.

Speaker diarization is a separate pass via lib_diarization.py (pyannote.audio,
purely acoustic, no LLM). Each VAD chunk is transcribed once as a whole (for
ASR context/quality), then lib_forced_align.py times each word precisely
against the diarized speaker turns -- labeling per word instead of picking one
dominant speaker for the whole chunk, which used to silently swallow short
interjections inside a longer chunk (confirmed on ep30/ep39, see
ARCHITECTURE.md). Output is `[MM:SS] Speaker N: text`, matching Gemini raw.md's
turn format closely enough for the same downstream qa_check.py/rewrite-stage
parsing to work unmodified.

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
import lib_forced_align
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
            # Without pinning language+task, this multilingual checkpoint's language
            # auto-detection occasionally misfires on short/atypical chunks and silently
            # translates to English instead of transcribing Malay -- confirmed directly
            # on a short code-switched clip while building the word-level diarization
            # pass below (see ARCHITECTURE.md).
            generate_kwargs={"language": "ms", "task": "transcribe"},
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


def _speaker_lines(text, segment, sr, chunk_start, diarization):
    """Splits one chunk's transcription into per-speaker lines by forced-aligning
    each word, instead of labeling the whole chunk with one dominant speaker."""
    lines = []
    cur_speaker, cur_start, cur_words = None, None, []
    for word, w_start, w_end in lib_forced_align.align_words(text, segment, sr):
        abs_start, abs_end = chunk_start + w_start, chunk_start + w_end
        speaker = lib_diarization.label_for_range(diarization, abs_start, abs_end) or "Speaker ?"
        if speaker != cur_speaker:
            if cur_words:
                lines.append((cur_start, cur_speaker, " ".join(cur_words)))
            cur_speaker, cur_start, cur_words = speaker, abs_start, []
        cur_words.append(word)
    if cur_words:
        lines.append((cur_start, cur_speaker, " ".join(cur_words)))
    return lines


def transcribe_raw_local(audio_path, duration_seconds):
    wav_path = _decode_to_wav(Path(audio_path))
    try:
        audio_array, sr = sf.read(str(wav_path), dtype="float32")

        print("  diarizing speakers ...", flush=True)
        diarization = lib_diarization.diarize(audio_array, sr)

        chunks = _vad_chunks(audio_array, sr)
        pipe = _get_pipe()
        print(f"  local ASR: {len(chunks)} chunks to transcribe", flush=True)

        turns = []
        t0 = time.time()
        for i, (start, end) in enumerate(chunks):
            i0, i1 = int(start * sr), int(end * sr)
            segment = audio_array[i0:i1]
            out = pipe({"array": segment, "sampling_rate": sr}, return_timestamps=True)
            text = out["text"].strip()
            if text:
                turns.extend(_speaker_lines(text, segment, sr, start, diarization))
            if (i + 1) % 20 == 0 or i + 1 == len(chunks):
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed
                eta = (len(chunks) - i - 1) / rate
                print(f"  local ASR: {i+1}/{len(chunks)} chunks, {elapsed:.0f}s elapsed, ETA {eta:.0f}s", flush=True)

        # Merge consecutive same-speaker turns across chunk boundaries -- VAD chunking
        # splits audio every ~28s regardless of speaker continuity, so one uninterrupted
        # turn otherwise ends up as several separate lines with no new information in
        # the extra timestamps.
        lines = []
        for line_start, speaker, line_text in turns:
            if lines and lines[-1][1] == speaker:
                lines[-1] = (lines[-1][0], speaker, lines[-1][2] + " " + line_text)
            else:
                lines.append((line_start, speaker, line_text))
        return "\n\n".join(f"[{_format_timestamp(s)}] {spk}: {t}" for s, spk, t in lines) + "\n"
    finally:
        wav_path.unlink(missing_ok=True)
