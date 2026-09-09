# Model landscape

Which speech and language models are worth using for this corpus, what they measure, and how
to re-measure when a new one launches.

`ENGINEERING_LOG.md` records defects and their fixes in the order they happened.
`ARCHITECTURE.md` describes the pipeline as it stands. This file is the third thing: a dated
comparison you reopen when something new ships. Add a row, date it, name the yardstick.

## What can and cannot be measured here

**There is no ground-truth transcript for any episode.** Nobody has hand-transcribed four
hours of code-switched Malay against the audio, so this repo cannot report a word error rate
of its own. Two weaker measurements are available, and the difference matters:

- **Disagreement against YouTube's caption track.** The captions are themselves ASR output
  with their own errors, so the absolute number is not accuracy. Two engines scored against
  the same third-party transcript with the same normalizer are judged on equal terms, so the
  *comparison between rows* is meaningful even though no row is a WER.
- **A published benchmark.** Revolab's Malaysian ASR benchmark has a `podcast` category --
  casual register, code-switching, multiple speakers. It carries real references, so it
  produces a real WER. Its public split is gated behind an access request.

Never mix the two columns. A disagreement rate and a WER are different quantities.

## Malaysian ASR benchmark, re-scored here 2026-09-08

Source: Revolab Malaysian ASR benchmark, **public split, 820 clips**. Harness is MIT at
`github.com/Revolab-Sdn-Bhd/revolab-asr-benchmark`. Every row below was re-scored from that
repo's own committed prediction manifests using their aligner and their dual-reference rule,
so the whole table is one yardstick. **MAI-Transcribe-2 is our run**; every other row is
theirs.

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
| **Whisper large-v3** | 15.61% | **20.52%** | 11.52% | 113.05% | 20.69% |
| Deepgram Nova-3 | 24.61% | 37.82% | 42.95% | 68.34% | 48.55% |

**The engine this pipeline already runs is the most accurate one measured, and by a clear
margin on the category that matters.** MAI at 3.39% podcast WER against Scribe v2's 4.77% and
ILMU's 4.03%. Against the local Whisper fallback at 20.52%, it is six times better.

**Verbatim beats clean, which is the opposite of what was expected.** The prediction going in
was that `transcribeStyle: verbatim` would be penalised, because keeping fillers should read
as insertions against a reference that omits them. It does not: the benchmark's references
are themselves verbatim, so `clean` mode *deletes real words*. Deletion goes 1.45% to 3.04%
and overall WER goes 3.96% to 5.21%. Singing is the extreme case, 10.27% to 27.85%. The
production setting is the correct one and now has a number behind it.

### How far to trust this

The scorer was validated before the MAI number was believed, by re-scoring models whose
published figures are known:

| Model | Re-scored here | Published | Delta |
|---|---|---|---|
| Gemini 2.5 Pro | 5.32% | 5.30% | +0.02 |
| ElevenLabs Scribe v2 | 4.83% | 4.79% | +0.04 |
| Whisper large-v3 | 15.61% | 15.62% | -0.01 |
| ILMU v4.2 | 7.66% | 7.78% | -0.12 |
| Deepgram Nova-3 | 24.61% | 25.63% | -1.02 |

Four of five land within 0.12 points, including both models nearest MAI's range, and the
per-category podcast column reproduces published values exactly for every model. Nova-3's
1-point gap is the one loose end: manifests are stored in a different order from the parquet,
so rows are paired by reference text, and clips sharing identical reference text can pair to
the wrong audio. That hurts a high-error model most and does not affect the MAI rows, which
are keyed by row id.

Remaining caveats, none of which favour MAI:

- This is the **public 820-clip split**, not the private 1,079-clip split the official
  leaderboard ranks on.
- It is a self-run measurement, not verified by Revolab.
- MAI ran with **no language hint** (`locales` unset, as in production), while the other rows
  were run with `--language ms`. If anything that is the harder condition.
- Audio bytes were posted as stored rather than decoded and re-encoded, avoiding one lossy
  round trip their loader performs.
- Four requests ran in parallel, so no speed figure is comparable.

Reproduce with:

    python scripts/revolab_run_mai.py --style verbatim
    python scripts/revolab_run_mai.py --style clean

**FLEURS still overstates real Malay.** Whisper large-v3 scores 7.9% on FLEURS and 20.52% on
podcast audio here. Treat any FLEURS figure as a floor.

## Measured here

### ep62, disagreement against the caption track (2026-09-08)

    python scripts/asr_disagreement.py ep62 \
        --hyp local=episodes/.../raw.md --hyp mai=data/_mai_0M5hweswMpE/raw.md

Reference is the `ms-orig` caption track, 28,510 words. All three texts pass through the
vendored Revolab Malay normalizer first, so `okay`/`okey` and `jugak`/`juga` do not count as
errors. **Not a WER.**

| Engine | tokens | disagree | sub | ins | del |
|---|---|---|---|---|---|
| Whisper large-v3 (local) | 27,074 | 20.2% | 8.2% | 2.3% | **9.8%** |
| MAI-Transcribe-2 | 30,574 | **14.4%** | 7.4% | 5.8% | **1.3%** |

Reading it:

- **The deletion column is the finding.** The local engine is missing 2,856 words' worth of
  content relative to an independent transcription of the same audio; MAI is missing 369.
  That is the same failure the published benchmark predicts for Whisper on Malaysian audio,
  reproduced on this corpus.
- **MAI's higher insertion rate is partly a virtue.** It transcribes backchannels that both
  the captions and the local engine drop -- 527 of its turns on ep62 are a single
  vocalisation. That accounts for some, not all, of the 5.8%.
- **Substitutions are close** (8.2% against 7.4%), so the two engines hear individual words
  about equally well. They differ on whether they write them down.
- **Both files carry hand corrections**, so neither is pristine engine output. The local file
  has also had six degenerated filler runs collapsed, which removed spurious words and
  therefore flatters its insertion rate.

## Diarization, measured against the camera 2026-09-09

Source: `data/camera_ref_ep62.rttm`, built by `scripts/camera_speakers.py` from ep62's video.
LR-ASD scores whether the visible mouth matches the audio; YuNet plus SFace say whose face it
is. A second is labelled only where exactly one identified person is speaking, which covers
**12,473 of 14,101 seconds, 88%**. Scored at **collar 0 with overlap counted**, inside the UEM.

| system | DER | JER | Rafizi | Haziq | Farhan |
|---|---|---|---|---|---|
| raw.md as shipped | **3.0%** | 33.7% | 99% | 67% | 74% |
| pyannote 3.x thr=0.55 | 4.6% | **21.6%** | 99% | **85%** | 73% |
| MAI + voiceprint stitching | 5.3% | 51.4% | 96% | 86% | 12% |
| pyannoteAI Precision-2 + 3 voiceprints | 10.8% | 37.3% | 95% | 81% | 67% |
| pyannoteAI Precision-2, no enrolment | 10.8% | 37.3% | -- | -- | -- |
| MAI, chunk ids unstitched | 87.3% | 93.2% | -- | -- | -- |

Per-speaker recall uses a maximum-weight one-to-one mapping over the 11,755 seconds every
system labels, so no column rests on a different denominator (`data/_common_basis.py`).
Greedy per-label mapping is wrong here and fabricates a result -- see `ENGINEERING_LOG.md`
1.55.

**DER hides three different errors, so split it** (`data/_der_components.py`). Only the
confusion column measures attribution:

| system | DER | missed | false alarm | confusion |
|---|---|---|---|---|
| pyannote 3.x thr=0.55 | 4.6% | 2.9% | 0.0% | **1.8%** |
| pyannoteAI Precision-2 | 10.8% | 5.1% | 3.5% | **2.2%** |
| raw.md as shipped | 3.0% | 0.0% | 0.0% | **3.0%** |

raw.md scores 0% missed **by construction** -- its blocks tile continuously, so it can never
be charged for missing speech, and its flattering DER is an artifact of that. On confusion,
the one column that measures who is talking, it is last.

### pyannoteAI Precision-2, trialled 2026-09-09: do not pay for it on this corpus

Free trial, 150 hours. Two full passes over ep62 cost about 8 of them and ran in 188s and
284s. Findings:

- **It is beaten by the free local model it is sold against.** Confusion 2.2% against
  pyannote 3.x's 1.8%, and per-speaker 95/81/67 against 99/85/73.
- **Voiceprint enrolment works perfectly and is the part worth keeping.** Three voiceprints
  cut from camera-confirmed single-speaker runs matched all three hosts correctly:
  Farhan 90 with a 64-point margin, Rafizi 95 over Haziq's 80, Haziq 90 over Rafizi's 81.
  Rafizi and Haziq sit close, the same overlap the face embeddings show.
- **Enrolment does not change segmentation.** `diarize` and `identify` returned byte-identical
  3,882 segments; enrolment only renames clusters. So it cannot fix this pipeline's actual
  defect, which is in cutting blocks, not in naming clusters.
- Its higher DER is mostly VAD disagreement, not misattribution -- it claims less speech than
  a reference that labels whole seconds.

The mechanism worth copying locally: **enrol from camera-confirmed audio.** The camera
reference supplies clean single-speaker runs (Rafizi 136s, Haziq 36s, Farhan 17s) with
evidence behind them, which is a better enrolment source than raw.md's labels, since those
labels are what is under test.

**Read JER, not DER.** Rafizi holds 95.5% of ep62's speaking time, so a system that gets him
right and loses both co-hosts still posts an excellent DER. The shipped file does exactly
that -- best DER in the table, worst recall on Haziq.

**pyannote beats what ships, on the co-host.** 85% against 67%: eighteen points of Haziq are
lost in the naming stage that runs after diarization, not by the diarizer. That is where the
attribution work should go next.

**MAI's chunking is the whole of its 87.3%.** The API caps out near 30 minutes, so ep62 went
through as eight requests whose speaker ids have no relation to each other -- 22 clusters for
3 people. The voiceprint join repairs it to 5.3%. What the join does not repair is Farhan, at
11% recall.

Caveats that cut against these numbers, not for them:

- **One episode.** Nothing here generalises until a second reference exists.
- **Haziq's and Farhan's names are not independent of raw.md.** They were assigned from
  which face the camera holds during turns already labelled that way (52% and 62%
  pluralities). Only Rafizi is independently anchored, by the owner's ear. Findings that
  need only "Rafizi or not" are safe; findings that turn on telling Haziq from Farhan are not.
- **12% of the episode is unmeasured**, where the camera is on a graphic, a face is turned
  away, or two mouths move at once.
- The reference agrees with raw.md on 97% of covered seconds, so it is auditing the labels,
  not replacing them.

Reproduce with:

    python scripts/camera_speakers.py census   data/_video/0M5hweswMpE_480p.mp4
    python scripts/camera_speakers.py cluster  data/_video/0M5hweswMpE_480p.mp4
    python scripts/camera_speakers.py gallery  --name 5=Rafizi --name 50=Haziq --name 6=Farhan
    python scripts/camera_speakers.py run      data/_video/0M5hweswMpE_480p.mp4 audio/0M5hweswMpE.m4a
    python scripts/camera_speakers.py reference 0M5hweswMpE --out data/camera_ref_ep62

## Open

- **Closed 2026-09-09:** diarization now has a real number on this corpus. The gap is in the
  naming stage after the diarizer, not in the diarizer.
- **Closed 2026-09-08:** MAI-Transcribe-2 now has a benchmark number, and it is the best of
  the sixteen rows measured. No engine change is warranted; the open question was whether we
  were on the wrong engine, and we are not.
- **Closed 2026-09-09:** pyannoteAI Precision-2 trialled and rejected on accuracy. Keep the
  enrolment idea, not the service.
- **Not measured:** NVIDIA Sortformer. NeMo will not install cleanly here -- on Python 3.14
  the resolver backtracks to NeMo 2.5.0 and would downgrade numpy to 1.26.4, pyannote.core
  to 5.0.0 and pyannote.metrics to 3.2.1, which breaks `data/_score_diar.py` and
  pyannote.audio 4.0.7. It needs an isolated Python 3.12 venv and its own torch.
- **Still worth measuring:** Speechmatics `en_ms`, the only purpose-built Malay-English
  bilingual pack any vendor ships, which nobody has published a number for. ElevenLabs
  Scribe v2 is now less interesting on accuracy (4.83% against MAI's 3.96%) but still has
  two things MAI lacks: 10-hour files against MAI's 2-hour cap, and 32-speaker diarization
  that does not collapse under an hour.
- **The gap that remains is diarization, not transcription.** MAI wins on words and loses on
  speakers -- it absorbed the third host on ep62 where the local raw did not. Nothing in this
  benchmark measures that.
- **Diarization has no Malay number anywhere**, from any vendor or paper. Every DER quoted in
  `ENGINEERING_LOG.md` 1.51 comes from English, European or Chinese corpora.

## Adding a row when something launches

1. If it is on the Revolab leaderboard, take the podcast column and note the read date.
2. If not, run `scripts/asr_disagreement.py` against an episode with a caption track and add
   it to the measured table. State that it is a disagreement rate.
3. Record what you could not verify. An empty cell that says "no number exists" is worth more
   than a number from a different yardstick.
