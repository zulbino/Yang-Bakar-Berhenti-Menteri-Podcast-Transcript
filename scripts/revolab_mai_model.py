"""Azure MAI-Transcribe-2 backend for the Revolab Malaysian ASR benchmark.

WHY THIS EXISTS. MAI-Transcribe-2 is the engine this pipeline transcribes with, and it
appears on no Malay benchmark anywhere -- Microsoft publishes a FLEURS figure and nothing
else, and FLEURS is read news prose that overstates real Malaysian speech by roughly 2.5x.
The Revolab benchmark is the only public one with a `podcast` category, so this plugs MAI
into their harness and gets a number on the same yardstick as the fourteen models already
listed there.

HOW TO USE IT. The harness is a separate MIT-licensed checkout, so this file is copied in
rather than imported:

    git clone https://github.com/Revolab-Sdn-Bhd/revolab-asr-benchmark data/_revolab
    cp scripts/revolab_mai_model.py data/_revolab/asr_benchmark/models/mai_model.py
    # register it: add MaiModel to MODEL_REGISTRY in asr_benchmark/models/__init__.py
    cd data/_revolab && python run_eval.py --model-type mai --model-id MAI-Transcribe-2 \
        --dataset Revolab/ASR-Benchmark-Public --splits train --text-column text \
        --normalized-text-column normalized_text --metadata-columns category \
        --language ms --no-streaming

TWO SETTINGS DELIBERATELY MATCH PRODUCTION RATHER THAN MAXIMISING THE SCORE.

`transcribeStyle` is exposed as an option because it changes the answer and the honest
number depends on the question. This pipeline runs `verbatim`, which keeps fillers, because
raw.md is meant to be close to what was said; a benchmark reference that omits fillers will
charge those as insertions. Run both and report both -- the gap between them is the cost of
the production setting, and hiding it by only running `clean` would flatter the engine
relative to how it is actually used.

`locales` stays unset, as in production. The docs call it a very strong hint, and this
corpus code-switches Malay and English mid-sentence, so forcing a single locale is the
failure mode being measured rather than a tuning knob.

Diarization is OFF here and ON in production. It does not change the transcript text, which
is all WER scores, and leaving it on would spend latency on every ten-second clip for
nothing.
"""

from __future__ import annotations

import io
import json
import os
import time

import numpy as np
import requests

from .base import BaseASRModel, TranscriptionResult

API_VERSION = "2025-10-15"
RETRY_STATUS = (429, 500, 502, 503, 504)


class MaiModel(BaseASRModel):
    """Azure Speech fast-transcription with the MAI-Transcribe-2 enhanced model.

    Requires AZURE_SPEECH_KEY, and AZURE_SPEECH_ENDPOINT or AZURE_SPEECH_REGION.

    kwargs:
        transcribe_style: "verbatim" (default, matches production) or "clean"
        max_retries: default 4
    """

    def _load_model(self) -> None:
        self._key = self.kwargs.get("api_key") or os.environ.get("AZURE_SPEECH_KEY")
        if not self._key:
            raise ValueError("set AZURE_SPEECH_KEY")
        host = os.environ.get("AZURE_SPEECH_ENDPOINT")
        if not host:
            region = os.environ.get("AZURE_SPEECH_REGION")
            if not region:
                raise ValueError("set AZURE_SPEECH_ENDPOINT or AZURE_SPEECH_REGION")
            host = f"https://{region}.api.cognitive.microsoft.com"
        self._url = (f"{host.rstrip('/')}/speechtotext/transcriptions:transcribe"
                     f"?api-version={API_VERSION}")
        self._style = self.kwargs.get("transcribe_style", "verbatim")
        self._retries = int(self.kwargs.get("max_retries", 4))
        self._definition = {
            "enhancedMode": {
                "enabled": True,
                "model": self.model_id,
                "modelOptions": {"transcribeStyle": self._style},
            },
            "diarization": {"enabled": False},
        }

    def transcribe_batch(
        self,
        audio_arrays: list[np.ndarray],
        sample_rates: list[int],
        audio_lengths_s: list[float],
    ) -> list[TranscriptionResult]:
        results = []
        for audio, sr, dur in zip(audio_arrays, sample_rates, audio_lengths_s):
            wav = self._to_wav_bytes(audio, sr)
            began = time.perf_counter()
            try:
                payload = self._post(wav)
            except Exception as exc:
                # One clip failing must not lose the other 819. A skipped row is visible
                # in the manifest; a crashed run three hours in is not.
                results.append(TranscriptionResult(
                    prediction="", audio_length_s=dur,
                    transcription_time_s=time.perf_counter() - began,
                    metadata={"error": str(exc)[:200]}, skipped=True))
                continue
            results.append(TranscriptionResult(
                prediction=self._text_of(payload),
                audio_length_s=dur,
                transcription_time_s=time.perf_counter() - began,
                metadata={"transcribe_style": self._style},
            ))
        return results

    def _post(self, wav: bytes):
        last = None
        for attempt in range(self._retries):
            response = requests.post(
                self._url,
                headers={"Ocp-Apim-Subscription-Key": self._key},
                files={"audio": ("clip.wav", io.BytesIO(wav), "audio/wav")},
                data={"definition": json.dumps(self._definition)},
                timeout=600,
            )
            if response.status_code < 300:
                return response.json()
            last = f"HTTP {response.status_code} {response.text[:160]}"
            if response.status_code not in RETRY_STATUS or attempt == self._retries - 1:
                break
            time.sleep(5 * (attempt + 1))
        raise RuntimeError(last)

    @staticmethod
    def _text_of(payload) -> str:
        """Whole-clip text, tolerant of which key the response uses.

        The response shape is not pinned down in the docs, so accept the documented layout
        and the plausible variants rather than returning an empty string and silently
        scoring 100% error on every row.
        """
        combined = payload.get("combinedPhrases")
        if isinstance(combined, list) and combined:
            text = " ".join(c.get("text", "") for c in combined).strip()
            if text:
                return text
        for key in ("phrases", "segments", "results"):
            items = payload.get(key)
            if isinstance(items, list) and items:
                return " ".join(i.get("text", "") for i in items).strip()
        return str(payload.get("text", "")).strip()

    @staticmethod
    def _to_wav_bytes(audio: np.ndarray, sr: int) -> bytes:
        import soundfile as sf
        buf = io.BytesIO()
        sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
        return buf.getvalue()
