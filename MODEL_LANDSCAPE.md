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

## Speaker identity: research update, 2026-10-11 (NOT yet measured on this corpus)

The 2026-09-09 rows above compare pyannote 3.x, MAI stitching and pyannoteAI. Since then several
open models appeared. Every number below is the publisher's own or a competitor's, on English,
Chinese or meeting corpora; none is Malay. They decide what to MEASURE, not what to adopt.

| candidate | what it replaces | published claim | runs here? | licence |
|---|---|---|---|---|
| pyannote `speaker-diarization-community-1` | our pyannote 3.1 pipeline | lower speaker confusion than 3.1; DER 17.0 AMI-IHM, 20.2 DIHARD 3 ([pyannoteAI](https://www.pyannote.ai/blog/community-1)) | yes: pyannote.audio 4.0.7 is installed and the weights are already cached | CC-BY-4.0 |
| DiariZen (WavLM-Large + Conformer) | the diarizer | 9.1 VoxConverse, 13.9 AMI-SDM, against 11.2 and 19.9 for community-1 ([table](https://huggingface.co/rewayai/suplime-large), a competitor's) | probably, untested on 8 GB | weights CC BY-NC 4.0 (third-party mirrors; not checked upstream) |
| NVIDIA streaming Sortformer v2 / v2.1 | the diarizer | 13.24 DIHARD III for up to 4 speakers, 42.56 for 5 or more ([guide](https://kili-technology.com/blog/speaker-diarization-models-guide-benchmarks-and-failure-modes-2026)) | needs its own Python 3.12 venv (see Open) | NVIDIA open model |
| 3D-Speaker ERes2NetV2 / CAM++ | WeSpeaker ResNet34 in voice_witness | EER 0.61% / 0.65% VoxCeleb1-O ([paper](https://arxiv.org/pdf/2403.19971)); ERes2NetV2 is tuned for short segments | yes, small models | see [repo](https://github.com/modelscope/3D-Speaker) |
| ReDimNet2 B6 | same | EER 0.29% VoxCeleb1-O, 12.3M parameters ([paper](https://arxiv.org/abs/2603.11841)) | yes, torch.hub | see repo |
| w2v-BERT 2.0 + layer adapters + LoRA | same | EER 0.12% VoxCeleb1-O with calibration, one group, preprint ([paper](https://arxiv.org/pdf/2510.04213)) | inference yes; fine-tuning tight on 8 GB | see repo |

What the literature says about training on our own data:

- **Fine-tune the segmentation model, keep the embedding.** This is the common recipe for a new
  language or domain: Indonesian conversational audio went from 53.5% to 29.2% DER with 25 hours
  ([paper](https://arxiv.org/pdf/2601.03684)). Segmentation decides WHEN the speaker changes, which
  is the part the camera does worst here (it lags the voice and shows the listener).
- **Do not fully fine-tune an embedding model on a handful of speakers.** With 50 to 100 speakers
  full fine-tuning overfits and adapters win ([SE/BN adapter](https://arxiv.org/pdf/2406.07832)).
  Sessions matter more than speaker count ([Vaessen 2022](https://arxiv.org/pdf/2203.14688)), and
  the corpus has many sessions for the hosts: Rafizi 143 h in 76 episodes, Haziq 8.1 h in 62,
  Farhan 1.7 h in 42 (camera reference), guests 0.2 to 1.2 h each.
- **For known recurring speakers, a closed-set back-end on fixed embeddings** (one centroid or a
  small classifier per person, trained across episodes) is the cheap first step; the cross-episode
  voiceprint failed with a single threshold, and argmax over enrolled people does not need one.
- **Report miss, false alarm and confusion separately**, plus the error on the switch second.

The gold standard for any test is ep65, ep66 and ep67: the only episodes the owner labelled block
by block by ear (owner, 2026-10-11). Train on other episodes, test on these three, never on the
same episode. Camera labels are training material, not truth: they carry the camera's lag.

### First measurement, 2026-10-12: voice against camera on the owner's gold

Scored per second against ep65, ep66 and ep67 (owner-labelled), WeSpeaker ResNet34, 1.6 s
windows, majority over 3. "Voice" learns each person from OTHER episodes' camera seconds
only (30 episodes, 20 clips each; Sum Dek Joe 60 clips from 3), so the test episode is unseen.

| | camera: share labelled / accuracy | voice: share labelled / accuracy | switch within 1 s, camera / voice |
|---|---|---|---|
| ep65 | 89% / 98.5% | 100% / 97.9% | 32.5% / 67.5% |
| ep66 | 67% / 96.0% | 100% / 95.8% | 10.1% / 59.9% |
| ep67 | 90% / 96.1% | 100% / 96.6% | 20.8% / 68.6% |

Recall, camera against voice: Haziq 63/87, 43/80, 56/88; Farhan 53/53, 41/84, 46/78; Sum Dek
Joe 64/90 (ep67). Learning from the same episode's camera is no better than learning from
other episodes. Voice invents more switches: 74-75% of its switches are real, the camera's
69-86%. The gold is block-level (a block owns its pauses), so every accuracy is a lower bound.
The measurement first exposed 22 wrong interjection stamps in these three raw.md files
(`restamp_interjections.py`). Not yet tried: ERes2NetV2, ReDimNet2, a trained classifier, a
calibrated abstain bar, segmentation fine-tuning.

**Second measurement, 2026-10-12: better embeddings and a trained classifier did not help.**
ReDimNet2 B6 (VoxCeleb2) and ReDimNet2 B6 (VoxBlink2 + VoxCeleb2 + CN-Celeb), both MIT, tie
with WeSpeaker ResNet34 within about one point on every column (ep67: accuracy 96.4-96.6%,
switches within 1 s 67.7-69.1%). A logistic-regression classifier on 4,880 clips from up to 40
other episodes finds Farhan 4 to 6 points more often but is 0.7 to 1.1 points less accurate and
invents more switches (54-63% real, against 74-82% for the centroid). A probability bar trades
coverage for accuracy (ep65 99.0% at 84%, ep67 97.7% at 79%) but never reaches 100% on this
gold, because a block owns its pauses and the short `ya` of others inside it. So the voice model
is not the limit; the switch second and short turns are. The next test counts wrong WORDS with
`compare_owner_edit.py`, the measure of the ep65 trials, instead of seconds.

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
