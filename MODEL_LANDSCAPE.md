# Model landscape

Which speech models are worth using on this corpus, what they measure, and how to add a row
when a new one ships. [ARCHITECTURE.md](ARCHITECTURE.md) describes the pipeline;
[ENGINEERING_LOG.md](ENGINEERING_LOG.md) records defects in order. This file is a dated
comparison: add a row, date it, name the yardstick.

## What can be measured

No episode has a hand-made reference transcript, so this repo cannot compute its own word
error rate (WER). Two weaker measures exist, and they must never share a column:

- **Disagreement with YouTube's caption track.** The captions are ASR output too, so the
  number is not accuracy. Two engines scored against the same captions can still be ranked.
- **Revolab's Malaysian ASR benchmark.** Its `podcast` category has real references,
  code-switching and several speakers, so it gives a real WER.

## Malaysian ASR benchmark, re-scored 2026-09-08

Revolab benchmark, **public split, 820 clips**, harness at
`github.com/Revolab-Sdn-Bhd/revolab-asr-benchmark` (MIT). Every row was re-scored with their
aligner and dual-reference rule from their committed predictions, so all rows share one
yardstick. **The MAI-Transcribe-2 rows are our runs**; the others are theirs.

| Model | Overall | Podcast | Parliament | Telephony | Street interview |
|---|---|---|---|---|---|
| **MAI-Transcribe-2 (verbatim)** | **3.96%** | **3.39%** | 3.44% | 9.05% | 9.74% |
| ElevenLabs Scribe v2 | 4.83% | 4.77% | 4.09% | 9.41% | 12.96% |
| Revolab Aisyah 1.0 Pro | 4.89% | 4.41% | 3.71% | 6.11% | 14.56% |
| MAI-Transcribe-2 (clean) | 5.21% | 4.60% | 4.21% | 10.43% | 13.54% |
| Gemini 2.5 Pro | 5.32% | 4.60% | 3.93% | 21.05% | 11.26% |
| Qwen audio 3.0 ASR flash | 7.22% | 7.24% | 5.37% | 11.45% | 20.59% |
| ILMU ASR v4.2 | 7.66% | 4.03% | 4.09% | 17.11% | 16.92% |
| Revolab Aisyah 1.0 Flash | 8.01% | 4.65% | 2.85% | 13.65% | 14.66% |
| Gemini 2.5 Flash | 9.07% | 13.09% | 9.53% | 26.15% | 19.27% |
| AssemblyAI Universal-3.5 Pro | 14.88% | 14.38% | 10.93% | 56.18% | 24.54% |
| Gemini 3.6 Flash | 15.01% | 9.21% | 6.58% | 72.84% | 20.49% |
| Whisper large-v3 | 15.61% | 20.52% | 11.52% | 113.05% | 20.69% |
| Deepgram Nova-3 | 24.61% | 37.82% | 42.95% | 68.34% | 48.55% |

MAI-Transcribe-2, the engine this pipeline uses, scores best in the table: 3.39% on podcast
audio, against 4.03% for ILMU, 4.77% for Scribe v2 and 20.52% for Whisper large-v3.

**Verbatim mode beats clean mode.** The benchmark's references are verbatim, so `clean`
mode deletes real words: deletions rise from 1.45% to 3.04%, and overall WER from 3.96% to
5.21%. Production uses verbatim.

**FLEURS overstates real Malay.** Whisper large-v3 scores 7.9% on FLEURS and 20.52% on
podcast audio here. Treat a FLEURS figure as a lower bound.

### How far to trust it

The scorer was checked first against models with published figures:

| Model | Re-scored here | Published | Delta |
|---|---|---|---|
| Gemini 2.5 Pro | 5.32% | 5.30% | +0.02 |
| ElevenLabs Scribe v2 | 4.83% | 4.79% | +0.04 |
| Whisper large-v3 | 15.61% | 15.62% | -0.01 |
| ILMU v4.2 | 7.66% | 7.78% | -0.12 |
| Deepgram Nova-3 | 24.61% | 25.63% | -1.02 |

The podcast column matches published values exactly for every model. Nova-3's gap comes
from pairing rows by reference text, where identical texts can pair to the wrong clip; the
MAI rows are paired by row id and are not affected.

Caveats, none in MAI's favour: this is the public split, not the private 1,079-clip
leaderboard split; Revolab has not verified it; MAI ran with no language hint while the
others used `--language ms`; four requests ran in parallel, so no speed figure is
comparable.

    python scripts/revolab_run_mai.py --style verbatim
    python scripts/revolab_run_mai.py --style clean

## ep62: disagreement with the caption track, 2026-09-08

Reference: the `ms-orig` caption track, 28,510 words, all texts through Revolab's Malay
normalizer. **Not a WER.**

| Engine | tokens | disagree | sub | ins | del |
|---|---|---|---|---|---|
| Whisper large-v3 (local) | 27,074 | 20.2% | 8.2% | 2.3% | **9.8%** |
| MAI-Transcribe-2 | 30,574 | **14.4%** | 7.4% | 5.8% | **1.3%** |

Deletions separate the engines: Whisper drops 2,856 words that the captions contain, MAI
369. Substitutions are close, so both hear words about equally well; they differ on
whether they write them down. Part of MAI's higher insertion rate is real backchannels the
captions omit (527 single-sound turns). Both files carried hand corrections, so neither is
raw engine output.

    python scripts/asr_disagreement.py ep62 \
        --hyp local=episodes/.../raw.md --hyp mai=data/_mai_0M5hweswMpE/raw.md

## Diarization against the camera, ep62, 2026-09-09

Reference: `data/camera_ref_ep62.rttm` from `scripts/camera_speakers.py`. LR-ASD decides
whether the visible mouth matches the audio; YuNet and SFace say whose face it is. A second
is labelled only when exactly one identified person speaks: **12,473 of 14,101 seconds,
88%**. Scored at collar 0 with overlap counted.

| system | DER | JER | confusion | Rafizi | Haziq | Farhan |
|---|---|---|---|---|---|---|
| ep62 raw.md, after block split and owner review | **1.6%** | **21.1%** | **1.6%** | 99% | **92%** | **88%** |
| pyannote 3.x, threshold 0.55 | 5.2% | 25.7% | 2.1% | 99% | 85% | 73% |
| MAI + voiceprint stitching | 5.3% | 51.4% | 5.3% | 96% | 86% | 12% |
| pyannoteAI Precision-2 + voiceprints | 11.0% | 43.4% | 5.7% | 95% | 81% | 67% |
| ep62 raw.md, pipeline output before review | 3.0% | 33.7% | 2.8% | 99% | 67% | 74% |

**Confusion is the column for attribution.** DER also counts missed speech and false alarm.
**Read JER, not DER:** Rafizi holds 95.5% of ep62's speaking time, so a system that loses
both co-hosts can still post a good DER.

The top row was split using this same camera reference, so it is a consistency check, not
independent proof. The owner's ear is the independent check: five confirmed timestamps and
eleven corrections, four of which the metrics had scored as improvements while the output
was wrong.

MAI's own speaker ids, before stitching, score DER 87.3%: the API caps near 30 minutes, so
ep62 went through as eight requests with unrelated ids, 22 clusters for 3 people. Voiceprint
stitching repairs it to 5.3%, except for Farhan at 12%.

Per-speaker recall uses a one-to-one mapping over the 11,755 seconds every system labels;
greedy per-label mapping produces false results (`ENGINEERING_LOG.md` 1.55).

    python scripts/score_attribution.py data/camera_ref_ep62.rttm --episode ep62 \
        --triples "pyannote 3.x thr=0.55=data/diar_0M5hweswMpE_t055.json" \
        --rttm "pyannoteAI=data/_pyannoteai/0M5hweswMpE_identify_exclusive.rttm" \
        --blocks "MAI + voiceprint=data/_mai_0M5hweswMpE/raw.md"

Caveats: one episode; 12% of it unmeasured (graphics, turned faces, two mouths moving); and
at the time, Haziq's and Farhan's faces were named from raw.md's own labels, so only Rafizi
was anchored independently.

To rebuild the reference, fetch the 480p video (618 MB, about ten minutes) at format 135 so
LR-ASD scores stay comparable:

    python -m yt_dlp -f 135 --extractor-args youtube:player_client=web_embedded \
        -o data/_video/0M5hweswMpE_480p.mp4 \
        https://www.youtube.com/watch?v=0M5hweswMpE
    python scripts/camera_speakers.py census    data/_video/0M5hweswMpE_480p.mp4
    python scripts/camera_speakers.py cluster   data/_video/0M5hweswMpE_480p.mp4
    python scripts/camera_speakers.py gallery   --name 5=Rafizi --name 50=Haziq --name 6=Farhan
    python scripts/camera_speakers.py run       data/_video/0M5hweswMpE_480p.mp4 audio/0M5hweswMpE.m4a
    python scripts/camera_speakers.py reference 0M5hweswMpE --out data/camera_ref_ep62

### pyannoteAI Precision-2: rejected, 2026-09-09

Two passes over ep62 used about 8 of the 150 free trial hours. It lost to free local
pyannote 3.x (confusion 5.7% against 2.1%). Voiceprint enrolment named all three hosts
correctly, but it only renames clusters: `diarize` and `identify` returned the same 3,882
segments. The idea worth keeping is enrolment from camera-confirmed audio, which the
pipeline now does locally.

## Open

- **Not measured: NVIDIA Sortformer.** NeMo on Python 3.14 would downgrade numpy and
  pyannote and break `scripts/score_attribution.py`. It needs its own Python 3.12 venv.
- **Worth measuring: Speechmatics `en_ms`**, the only Malay-English bilingual pack any vendor
  ships, with no published number. ElevenLabs Scribe v2 still has two things MAI lacks:
  10-hour files against MAI's 2-hour cap, and 32-speaker diarization.
- **No diarization number for Malay exists** from any vendor or paper. Every DER in
  `ENGINEERING_LOG.md` 1.51 comes from English, European or Chinese corpora.

## Adding a row

1. If the model is on the Revolab leaderboard, take its podcast column and note the date.
2. If not, run `scripts/asr_disagreement.py` on an episode with a caption track, and label
   the result a disagreement rate.
3. Write down what you could not verify. An empty cell marked "no number exists" beats a
   number from a different yardstick.
