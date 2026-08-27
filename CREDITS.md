# Credits and third-party terms

I built this archive almost entirely out of other people's work. The code in `scripts/`
is glue: it downloads audio, hands it to models other people trained, and checks the
result. Without the projects below there would be no transcripts here at all, and no
Malay-language ones in particular.

I'm not a lawyer, and none of this is legal advice. This file records what each
component is, what its licence says, and what its authors ask for.

## What this project runs on

| Component | What it does here | Licence |
|---|---|---|
| [mesolitica/malaysian-whisper-medium-v2](https://huggingface.co/mesolitica/malaysian-whisper-medium-v2) | The local ASR fallback. Malay-language speech recognition, the hardest part of this project | **None declared** -- [see below](#the-licensing-question-on-mesolitica-and-what-the-evidence-says) |
| [OpenAI Whisper](https://github.com/openai/whisper) | The base model the above is fine-tuned from | MIT (code), Apache-2.0 (weights) |
| [pyannote.audio](https://github.com/pyannote/pyannote-audio) + `speaker-diarization-3.1`, `segmentation-3.0` | Works out who is speaking when, on locally-transcribed episodes | MIT, gated -- see below |
| [wespeaker-voxceleb-resnet34-LM](https://huggingface.co/pyannote/wespeaker-voxceleb-resnet34-LM) | Speaker embeddings, pulled in by the diarization pipeline | **CC-BY-4.0** -- attribution required |
| [Meta MMS forced aligner](https://github.com/facebookresearch/fairseq/tree/main/examples/mms) (`torchaudio.pipelines.MMS_FA`) | Word-level alignment, so speaker turns land on the right words | **CC-BY-NC 4.0** -- attribution required, non-commercial only |
| [Silero VAD](https://github.com/snakers4/silero-vad) | Splits long audio into speech chunks | MIT |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Audio download, playlist metadata, and the auto-captions used as ground truth | Unlicense |
| [bgutil-ytdlp-pot-provider](https://github.com/Brainicism/bgutil-ytdlp-pot-provider) | PO tokens, without which YouTube serves nothing usable | GPL-3.0 |
| [PyTorch](https://pytorch.org/), [torchaudio](https://github.com/pytorch/audio), [Transformers](https://github.com/huggingface/transformers), [Hugging Face Hub](https://github.com/huggingface/huggingface_hub), [soundfile](https://github.com/bastibe/python-soundfile), [NumPy](https://numpy.org/), [PyYAML](https://pyyaml.org/) | Everything underneath | Apache-2.0 / BSD / MIT |
| Google Gemini / AI Studio, Anthropic Claude, Speechmatics | Hosted APIs for transcription, rewriting and verification | Provider terms -- see below |

Two things I relied on are not code. **YouTube's own auto-captions** are the reference
every transcript is checked against. [**@mediarakyat**](https://www.youtube.com/@mediarakyat)
re-uploaded the same episodes, which gave me a second recording to confirm findings
against. Several of the bugs in this archive were only provable because those existed.

And of course **Rafizi Ramli and his guests**, who made the thing being transcribed.

## Citations the authors ask for

If you use this archive or its pipeline in published work, please cite the underlying
research rather than this repo:

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
- **mesolitica** -- they have published no paper yet, and the model card says a preprint
  is coming. Please credit
  [mesolitica/malaysian-whisper-medium-v2](https://huggingface.co/mesolitica/malaysian-whisper-medium-v2)
  by name and link.

The exact BibTeX for the pyannote models sits on their model cards, which are gated and
need a logged-in Hugging Face account to read.

## Hosted APIs, and what their terms require

None of the three require attribution. They are recorded here because their terms shaped
how this archive was built, and because requiring no attribution still leaves obligations.

**Google Gemini and Google AI Studio** did most of the transcription and rewriting.
Google [doesn't claim ownership](https://ai.google.dev/gemini-api/terms) of generated
content, and asks for attribution only where the law requires it. The term that matters
here is the free tier: on unpaid services *"Google uses the content you submit to the
Services and any generated responses to provide, improve, and develop Google products
and services"*, and human reviewers may read what you submit. Everything I sent was
already-public broadcast audio from a public YouTube channel, so I accepted that trade.
It is a real property of the unpaid tier, though, so if you point this pipeline at
private or sensitive audio, use the paid tier, which doesn't train on prompts or
responses.

**Anthropic Claude**, through the `claude` CLI, ran the rewrite, translation and metadata
stage on the fallback path. Under the
[commercial terms](https://www.anthropic.com/legal/commercial-terms), *"Customer (a)
retains all rights to its Inputs, and (b) owns its Outputs"*, and *"Anthropic may not
train models on Customer Content from Services"*. They require no attribution. They do
ask that users be told not to rely on factual assertions in the output without checking
them, which is what the accuracy note does.

**Speechmatics** transcribed audio for verification during the ep35 investigation, under
its commercial terms.

## Terms that carry over to anyone reusing this

The [CC0 dedication](LICENSE) covers **my own code in `scripts/`**. It can't relicense
anything above it. Two constraints remain:

1. **The MMS forced aligner is CC-BY-NC 4.0, non-commercial only.** If you run this
   pipeline as it stands for a commercial purpose, you breach that, whatever `LICENSE`
   says about the glue code. This archive is free, unfunded and non-commercial, so its
   own use sits inside the terms. For a commercial pipeline, replace
   `scripts/lib_forced_align.py` or get separate permission from Meta. This constrains
   the pipeline and not the transcripts, because reusing the finished text doesn't
   involve the model.
2. **The WeSpeaker embedding model is CC-BY-4.0 and requires attribution.** Naming it,
   as this file does, satisfies that.

The pyannote diarization models are **gated**. To get access you need a Hugging Face
account, you must accept the model conditions, and you must state your organisation and
what you intend to use the models for. I requested access for this project's stated
purpose: building a free, public, non-commercial transcript archive of a Malaysian
public-affairs podcast. If you re-run this pipeline you need your own access under your
own purpose, because a token can't be shared or inherited.

`bgutil-ytdlp-pot-provider` is GPL-3.0. This repo doesn't redistribute, bundle or link
it. `requirements.txt` names it, you install it yourself, and `yt_download.py` runs it as
a separate process. Vendoring it into the repo would change that.

## The licensing question on mesolitica, and what the evidence says

`mesolitica/malaysian-whisper-medium-v2` is the most important single component here,
and the reason Malay transcription works at all. **Its model card declares no licence.**
I wanted to state that precisely rather than guess, so I queried the Hugging Face API
across both organisations:

| Publisher | Models | No licence declared | Most common declared licence |
|---|---|---|---|
| [mesolitica](https://huggingface.co/mesolitica) | 278 | 274 (99%) | `cc-by-nc-4.0` (3 of the 4) |
| [malaysia-ai](https://huggingface.co/malaysia-ai) | 23 | 22 (96%) | `mit` (1) |
| mesolitica datasets | 206 | 192 (93%) | `mit`, then `cc-by-nc-4.0` |
| malaysia-ai datasets | 107 | 89 (83%) | `cc-by-nc-4.0` (14) |

The silence runs across both organisations, so I can't treat it as one blank card
somebody forgot. Three things point toward clear open intent:

- Their code carries open licences: [`malaya`](https://github.com/malaysia-ai/malaya)
  (MIT), [`malaya-speech`](https://github.com/malaysia-ai/malaya-speech) (MIT), and
  [`malaysian-dataset`](https://github.com/malaysia-ai/malaysian-dataset) (Apache-2.0).
- [malaysia-ai](https://huggingface.co/malaysia-ai) describes itself as a non-profit
  whose purpose is "We build open source".
- They publish the models openly and undocumented, free to download, with a preprint
  promised on the card.

Intent still is not a licence. Where these publishers do state one, they most often
choose **`cc-by-nc-4.0`: attribution, non-commercial**. That is the best evidence I've
of what they expect.

**How I treat it.** I credit mesolitica by name and link wherever I mention the model,
and this archive is free, unfunded and non-commercial, which already matches the terms
they pick when they pick any. The MMS aligner locks my pipeline to non-commercial use
anyway, so aligning with that here costs me nothing.

**If you build on this**, please do not read the missing licence as permission. Form
your own view, and consider asking [mesolitica](https://huggingface.co/mesolitica) to
declare one. That would settle the question for everyone using Malaysian speech models,
not only for this repo. The same applies to the training corpus,
[`mesolitica/malaysian-stt`](https://huggingface.co/datasets/mesolitica/malaysian-stt),
which aggregates YouTube and other sources and also declares no licence.
