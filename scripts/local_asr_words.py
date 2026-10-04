"""Transcribe an episode with a LOCAL engine and save the words in MAI's response format.

WHY. The Azure credit that pays for MAI-Transcribe-2 ends around 2026-10-07, and the owner
wants a free engine. mai_camera_raw.py and move_hanging_words.py read
data/_mai_<vid>/mai_response_*.json. This writes the same shape into another directory, so
the whole adoption pipeline (camera, pyannote, voice witness) can run on local words when
ASR_WORDS_DIR points at it, and compare_owner_edit.py can score the result against the
owner's hand-corrected raw.md.

Each VAD chunk becomes one phrase with speaker None, the shape MAI has with
--no-diarization. Word times come from lib_forced_align.py (torchaudio MMS) for every
engine, so the engines differ only in their words.

  python scripts/local_asr_words.py <video_id> --engine medium-v2|turbo|polyglot

Per-chunk results are cached in <out>/chunks.jsonl, so an interrupted run resumes.
"""
import os

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")

import argparse
import io
import json
import sys
import time
from pathlib import Path

import soundfile as sf
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lib_forced_align  # noqa: E402
import lib_local_asr  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ENGINES = {
    "medium-v2": "mesolitica/malaysian-whisper-medium-v2",
    "turbo": "openai/whisper-large-v3-turbo",
    "polyglot": "knoveleng/polyglot-lion-1.7b",
}


def load(engine):
    model_id = ENGINES[engine]
    if engine == "polyglot":
        from qwen_asr import Qwen3ASRModel
        # The RTX 2070 (Turing) has no native bfloat16, so float16 rather than the card's bf16.
        model = Qwen3ASRModel.from_pretrained(model_id, dtype=torch.float16,
                                              device_map="cuda:0", max_new_tokens=256)
        return lambda seg, sr: model.transcribe(audio=(seg, sr), language=None)[0].text
    from transformers import pipeline
    pipe = pipeline("automatic-speech-recognition", model=model_id, device=0,
                    dtype=torch.float16,
                    # Pinned for the same reason as lib_local_asr.py: auto-detect sometimes
                    # translates a Malay chunk into English.
                    generate_kwargs={"language": "ms", "task": "transcribe"})
    return lambda seg, sr: pipe({"array": seg, "sampling_rate": sr}, return_timestamps=True)["text"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--engine", default="turbo", choices=ENGINES)
    ap.add_argument("--out", help="default data/_asr_<engine>_<video_id>/")
    ap.add_argument("--gap", type=float, default=0.2, help="split a chunk at a pause this long (0.2 scored best on ep65)")
    a = ap.parse_args()

    out = Path(a.out or ROOT / "data" / f"_asr_{a.engine}_{a.video_id}")
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "chunks.jsonl"
    done = {}
    if cache.exists():
        for line in cache.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            done[row["start"]] = row

    audio = ROOT / "audio" / f"{a.video_id}.m4a"
    wav = audio.with_suffix(".vad16k.wav")
    if not wav.exists():
        wav = lib_local_asr._decode_to_wav(audio)
    arr, sr = sf.read(str(wav), dtype="float32")
    chunks = lib_local_asr._vad_chunks(arr, sr)
    print(f"{a.engine}: {len(chunks)} chunks, {len(done)} cached", flush=True)

    transcribe = None
    t0 = time.time()
    with io.open(cache, "a", encoding="utf-8", newline="\n") as fh:
        for i, (s, e) in enumerate(chunks):
            key = round(s, 3)
            if key in done:
                continue
            if transcribe is None:
                transcribe = load(a.engine)
            seg = arr[int(s * sr):int(e * sr)]
            text = (transcribe(seg, sr) or "").strip()
            words = [[w, ws, we] for w, ws, we in lib_forced_align.align_words(text, seg, sr)] if text else []
            row = {"start": key, "end": round(e, 3), "text": text, "words": words}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            done[key] = row
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(chunks)} chunks, {time.time() - t0:.0f}s", flush=True)

    # A VAD chunk runs up to 28 s and often holds two speakers, while a MAI phrase is about a
    # sentence. The pipeline labels a phrase as a whole, so split a chunk at every pause of
    # --gap seconds or more.
    phrases = []
    for row in sorted(done.values(), key=lambda r: r["start"]):
        base, runs = row["start"], []
        for w, ws, we in row["words"]:
            if not runs or ws - runs[-1][-1][2] >= a.gap:
                runs.append([])
            runs[-1].append((w, ws, we))
        for run in runs:
            phrases.append({
                "offsetMilliseconds": int((base + run[0][1]) * 1000),
                "durationMilliseconds": int((run[-1][2] - run[0][1]) * 1000),
                "text": " ".join(w for w, _, _ in run),
                "speaker": None,
                "words": [{"text": w, "offsetMilliseconds": int((base + ws) * 1000),
                           "durationMilliseconds": int((we - ws) * 1000)} for w, ws, we in run],
            })
    (out / "mai_response_00.json").write_text(json.dumps(
        {"_chunk_start_s": 0.0, "_engine": ENGINES[a.engine], "phrases": phrases},
        ensure_ascii=False), encoding="utf-8")
    (out / "engine.json").write_text(json.dumps(
        {"model": ENGINES[a.engine], "gap": a.gap}), encoding="utf-8")
    print(f"finished: {a.engine}, {len(phrases)} phrases, "
          f"{sum(len(p['words']) for p in phrases)} words -> {out}", flush=True)


if __name__ == "__main__":
    main()
