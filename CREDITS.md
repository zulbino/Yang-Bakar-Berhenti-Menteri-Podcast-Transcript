# Credits and third-party terms

This archive is assembled almost entirely out of other people's work. The code in
`scripts/` is glue: it downloads audio, hands it to models other people trained, and
checks the result. Without the projects below there would be no transcripts here at
all, and in particular no Malay-language ones.

Nothing in this file is legal advice. It records what each component is, what its
licence says, and what its authors ask for.

## What this project runs on

| Component | What it does here | Licence |
|---|---|---|
| [mesolitica/malaysian-whisper-medium-v2](https://huggingface.co/mesolitica/malaysian-whisper-medium-v2) | The local ASR fallback. Malay-language speech recognition, the single hardest part of this project | **None declared** -- [see below](#the-licensing-question-on-mesolitica-and-what-the-evidence-says) |
| [OpenAI Whisper](https://github.com/openai/whisper) | The base model the above is fine-tuned from | MIT (code), Apache-2.0 (weights) |
| [pyannote.audio](https://github.com/pyannote/pyannote-audio) + `speaker-diarization-3.1`, `segmentation-3.0` | Works out who is speaking when, on locally-transcribed episodes | MIT, gated -- see below |
| [wespeaker-voxceleb-resnet34-LM](https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM) | Speaker embeddings, pulled in by the diarization pipeline | **CC-BY-4.0** -- attribution required |
| [Meta MMS forced aligner](https://github.com/facebookresearch/fairseq/tree/main/examples/mms) (`torchaudio.pipelines.MMS_FA`) | Word-level alignment, so speaker turns land on the right words | **CC-BY-NC 4.0** -- attribution required, non-commercial only |
| [Silero VAD](https://github.com/snakers4/silero-vad) | Splits long audio into speech chunks | MIT |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Audio download, playlist metadata, and the auto-captions used as ground truth | Unlicense |
| [bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) | PO tokens, without which YouTube serves nothing usable | GPL-3.0 |
| [PyTorch](https://pytorch.org/), [torchaudio](https://github.com/pytorch/audio), [Transformers](https://github.com/huggingface/transformers), [Hugging Face Hub](https://github.com/huggingface/huggingface_hub), [soundfile](https://github.com/bastibe/python-soundfile), [NumPy](https://numpy.org/), [PyYAML](https://pyyaml.org/) | Everything underneath | Apache-2.0 / BSD / MIT |
| Google Gemini / AI Studio, Anthropic Claude, Speechmatics | Hosted APIs for transcription, rewriting and verification | Provider terms -- see below |

Also relied on, though not code: **YouTube's own auto-captions**, which are the
reference this project checks every transcript against, and
[**@mediarakyat**](https://www.youtube.com/@mediarakyat), whose independent
re-uploads of the same episodes provided a second recording to confirm findings
against. Several bugs in this archive were only provable because those existed.

And, obviously, **Rafizi Ramli and his guests**, who made the thing being transcribed.

## Citations the authors ask for

If you use this archive or its pipeline in published work, cite the underlying
research, not this repo:

- **pyannote.audio** -- Hervé Bredin, *pyannote.audio 2.1 speaker diarization
  pipeline: principle, benchmark, and recipe*, INTERSPEECH 2023; and Alexis Plaquet
  & Hervé Bredin, *Powerset multi-class cross entropy loss for neural speaker
  diarization*, INTERSPEECH 2023.
- **MMS / forced alignment** -- Vineel Pratap et al., *Scaling Speech Technology to
  1,000+ Languages*, 2023 ([arXiv:2305.13516](https://arxiv.org/abs/2305.13516)).
- **Whisper** -- Alec Radford et al., *Robust Speech Recognition via Large-Scale Weak
  Supervision*, 2022 ([arXiv:2212.04356](https://arxiv.org/abs/2212.04356)).
- **WeSpeaker** -- Hongji Wang et al., *Wespeaker: A research and production oriented
  speaker embedding learning toolkit*, ICASSP 2023.
- **mesolitica** -- no paper published yet; the model card says a preprint is coming.
  Credit [mesolitica/malaysian-whisper-medium-v2](https://huggingface.co/mesolitica/malaysian-whisper-medium-v2)
  by name and link.

Exact BibTeX for the pyannote models is on their model cards, which are gated and
need a logged-in Hugging Face account to read.

## Hosted APIs, and what their terms actually require

None of the three require attribution. Recorded here because their terms shaped how
this archive was built, and because "no attribution required" is not the same as "no
obligations".

**Google Gemini / Google AI Studio** did most of the transcription and rewriting.
Google [does not claim ownership](https://ai.google.dev/gemini-api/terms) of generated
content, and attribution is required only where applicable law demands it. The term
that matters here is the free tier: on unpaid services *"Google uses the content you
submit to the Services and any generated responses to provide, improve, and develop
Google products and services"*, and human reviewers may read submissions. Everything
sent was already-public broadcast audio from a public YouTube channel, so that was an
acceptable trade for this project -- but it is a real property of the free tier, and
anyone reusing this pipeline on private or sensitive audio should not repeat it. Paid
tier does not train on prompts or responses.

**Anthropic Claude** (via the `claude` CLI) ran the rewrite, translation and metadata
stage on the fallback path. Under the
[commercial terms](https://www.anthropic.com/legal/commercial-terms), *"Customer (a)
retains all rights to its Inputs, and (b) owns its Outputs"*, and *"Anthropic may not
train models on Customer Content from Services"*. No attribution required. The terms
do ask that users be told factual assertions in output should not be relied on without
checking -- which is what this repo's accuracy note does.

**Speechmatics** was used for verification transcription during the ep35 investigation,
under its commercial terms.

## Terms that carry over to anyone reusing this

The [CC0 dedication](LICENSE) covers **this project's own code in `scripts/`**. It
cannot and does not relicense anything above. Two constraints survive:

1. **The MMS forced aligner is CC-BY-NC 4.0: non-commercial use only.** Running this
   pipeline as-is for a commercial purpose would breach that, regardless of what
   `LICENSE` says about our glue code. This archive is free, unfunded and
   non-commercial, so its own use is within the terms. If you need a commercial
   pipeline, replace `scripts/lib_forced_align.py` or obtain separate permission from
   Meta. This constrains the *pipeline*, not the transcripts: reusing the finished
   text does not involve the model.
2. **The WeSpeaker embedding model is CC-BY-4.0: attribution required.** Naming it, as
   this file does, satisfies that.

The pyannote diarization models are **gated**. Access requires a Hugging Face account,
accepting the model conditions, and stating your organisation and what you intend to
use them for. That access was requested for this project's stated purpose: building a
free, public, non-commercial transcript archive of a Malaysian public-affairs podcast.
Anyone re-running this pipeline must request their own access under their own
purpose; a token cannot be shared or inherited.

`bgutil-ytdlp-pot-provider` is GPL-3.0. This project does not redistribute, bundle or
link it -- `requirements.txt` names it and the user installs it themselves, and
`yt_download.py` runs it as a separate process. Vendoring it into this repo would
change that analysis.

## The licensing question on mesolitica, and what the evidence says

`mesolitica/malaysian-whisper-medium-v2` is the most important single component here
-- the reason Malay transcription works at all -- and **its model card declares no
licence**. That is worth stating precisely rather than guessing at, so the Hugging Face
API was queried across both organisations:

| Publisher | Models | No licence declared | Most common declared licence |
|---|---|---|---|
| [mesolitica](https://huggingface.co/mesolitica) | 278 | 274 (99%) | `cc-by-nc-4.0` (3 of the 4) |
| [malaysia-ai](https://huggingface.co/malaysia-ai) | 23 | 22 (96%) | `mit` (1) |
| mesolitica datasets | 206 | 192 (93%) | `mit`, then `cc-by-nc-4.0` |
| malaysia-ai datasets | 107 | 89 (83%) | `cc-by-nc-4.0` (14) |

So the silence is an **organisation-wide pattern, not an oversight on one card**. Three
things point the other way, toward clear open intent:

- Their *code* is openly licensed: [`malaya`](https://github.com/malaysia-ai/malaya)
  (MIT), [`malaya-speech`](https://github.com/malaysia-ai/malaya-speech) (MIT),
  [`malaysian-dataset`](https://github.com/malaysia-ai/malaysian-dataset) (Apache-2.0).
- [malaysia-ai](https://huggingface.co/malaysia-ai) describes itself as a non-profit
  whose purpose is "We build open source".
- The models are published publicly, undocumented but freely downloadable, with a
  preprint promised on the card.

But intent is not a licence, and where these publishers *do* state one, the most
frequent choice is **`cc-by-nc-4.0`: attribution, non-commercial**. That is the best
available evidence of what they expect.

**How this project treats it.** mesolitica is credited by name and link wherever the
model is mentioned, and this archive is free, unfunded and non-commercial, which
already matches the terms they choose when they choose any. The pipeline is separately
locked to non-commercial by the MMS aligner regardless, so nothing is lost by aligning
with that here too.

**If you are building on this**, do not read the missing licence as permission. Form
your own view, and ideally ask [mesolitica](https://huggingface.co/mesolitica) to
declare one -- it would settle the question for everyone using Malaysian speech models,
not just this repo. The same applies to the training corpus,
[`mesolitica/malaysian-stt`](https://huggingface.co/datasets/mesolitica/malaysian-stt),
which aggregates YouTube and other sources and likewise declares no licence.
