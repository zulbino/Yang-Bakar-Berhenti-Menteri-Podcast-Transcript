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

## Published Malay podcast WER

Source: Revolab Malaysian ASR benchmark, public split, 820 clips, read 2026-09-08. Harness is
MIT at `github.com/Revolab-Sdn-Bhd/revolab-asr-benchmark`; the leaderboard API needs no auth.

| Model | Podcast WER | Overall WER | Notes |
|---|---|---|---|
| ILMU ASR v4.2 (YTL AI Labs) | **4.03** | 7.78 | Malaysian sovereign model, OpenAI-compatible API, needs a key |
| Revolab Aisyah 1.0 Pro | 4.41 | 4.89 | staging endpoint, pricing unpublished |
| Gemini 2.5 Pro | 4.60 | 5.30 | 9.5h audio per prompt, diarization prompted not native |
| ElevenLabs Scribe v2 | 4.77 | 4.79 | 10h files, 32-speaker diarization, lowest deletion rate |
| Qwen3-ASR-1.7B | 16.24 | 15.26 | |
| **Whisper large-v3** | **20.52** | 15.62 | what this pipeline's local fallback runs |
| Deepgram Nova-3 | 38.78 | 25.63 | deletes 15.5% of words |
| **MAI-Transcribe-2** | **no number exists** | -- | the engine ep62 was transcribed with |

**FLEURS overstates real Malay by roughly 2.5x.** Whisper large-v3 scores 7.9% there and
20.52% here, because FLEURS is read news prose with no code-switching. Treat any FLEURS figure
as a floor, never a forecast.

**Noise reorders the table.** Clean to noisy, Gemini 2.5 Pro moves 6.43 to 11.13 while one
flash-class model moves 6.81 to 34.05.

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

## Open

- **MAI-Transcribe-2 has no leaderboard-comparable number.** Getting one needs the Revolab
  public split, which is gated to an authorized list -- request access at
  `huggingface.co/datasets/Revolab/ASR-Benchmark-Public`. Adding MAI as a backend is a
  subclass of `BaseASRModel` implementing `transcribe_batch`, roughly 40 lines.
- **Untested and worth testing:** ElevenLabs Scribe v2 (best available combination of podcast
  accuracy, a 10-hour file limit and real diarization), and Speechmatics `en_ms`, the only
  purpose-built Malay-English bilingual pack any vendor ships and completely unmeasured by
  anyone.
- **Diarization has no Malay number anywhere**, from any vendor or paper. Every DER quoted in
  `ENGINEERING_LOG.md` 1.51 comes from English, European or Chinese corpora.

## Adding a row when something launches

1. If it is on the Revolab leaderboard, take the podcast column and note the read date.
2. If not, run `scripts/asr_disagreement.py` against an episode with a caption track and add
   it to the measured table. State that it is a disagreement rate.
3. Record what you could not verify. An empty cell that says "no number exists" is worth more
   than a number from a different yardstick.
