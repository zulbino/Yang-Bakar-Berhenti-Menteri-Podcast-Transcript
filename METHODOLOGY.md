# Methodology

What produced the files in this archive, how they can be wrong, and how to report an error.
Read it before you cite anything here.

Machines transcribed 190 hours of speech and rewrote it as interviews. I reviewed the
output, but not line by line. Before I caught them, the files had put words in the mouths
of the wrong real people, and insults in the mouths of people who never said them.

## Why a machine made these

Using AI for this project may look like a contradiction. I have seen people use it to make
atrocious work: ugly generated images, robotic sentences, and thinking handed over to a
machine that a person should have done. I also hold to a line from a 1979 IBM training
manual: "A computer can never be held accountable, therefore a computer must never make a
management decision."

To me, AI is a tool. If it makes a better product and a better experience, that is enough.
If it produces low-quality work, that is unacceptable.

AI is here to stay. I use it to automate work that would take me years by hand. With
agentic AI it takes a fraction of the time, and the quality is good enough to check and
correct. That is the premise this project starts from.

The corpus is 72 podcast episodes and 2 public forums, 190 hours in all. The speakers switch between Malay and English
inside one sentence, and often three people talk at once. Transcribing that by hand is
about a year of full-time work, and I am one person doing this outside a job. A machine
transcript that can be checked against the video is better than a human one that never
gets made.

## What produced each file

Each file names the model that produced it in its `model:` frontmatter field.

`raw.md`
: Speech-to-text by Microsoft's MAI-Transcribe-2, for the 73 episodes and both forums built so far. From 2026-10-04 a new episode uses OpenAI Whisper-large-v3-turbo run locally, and raw.md's `model:` line names the engine used. Filler sounds are
  removed; nothing is paraphrased. Speaker names come from the show's camera cuts, which
  show who is talking, then from voice comparison. A turn that no evidence can name is
  labelled `Speaker ?`, as Hansard writes "An Hon. Member". Earlier versions came from
  Gemini and from a local Whisper model; none remain.

`interview.md`
: An edited newspaper-style Q&A built from `raw.md`, in the original mix of Malay and
  English. It is not a transcript: fillers and false starts are gone. Most were written by
  Claude Sonnet 5; some by Gemini Flash Lite, Claude Haiku or GLM. From ep65 on, the edit
  is condensed to roughly half the spoken length.

`transcript.md` (Siri Forum BERSAMA only)
: A cleaned record of each forum, edited the way Hansard edits a debate, in the original
  mix of Malay and English. It keeps every point at close to full length and removes
  filler sounds, stammers and false starts. Written by GLM-5.3. The forums have no
  interview files.

`interview-en.md` and `interview-ms.md`
: Translations of `interview.md`, so two steps from the audio.

The `topics:`, `hosts:` and `guests:` fields are also written by a model.

## What a human decided

- **Speaker names**, from the camera, the YouTube caption track and voice comparison.
  Where tools could not decide, I listened.
- **Name and agency spellings**, from a reviewed correction map with one entry per
  decision, each checked against a public source. Not by majority vote: the majority
  spelling here is wrong for Fuziah Salleh and right for Akmal Saleh.
- **Disputed passages**, by listening to the recording.

**I have not verified any episode line by line, except ep65**, which I corrected by hand
against the video in September 2026. Automated checks cover the whole archive. Human review
covers the places a check pointed at.

## How these files have been wrong

Every class below was measured, and every instance found is corrected.

### Insults nobody said

The honorific `YB` was transcribed as `Babi` (Malay for pig) in 39 places. Five published
passages carried an insult that `raw.md` does not contain, because the rewrite changed a
harmless word: `bangsa` (race, nation) became `bangsat` (bastard) in ep15 and ep51,
`Salawat`, an Islamic blessing, became `celaka` (cursed) in ep16, and a spoken `damn`
became `sial` in ep42. `scripts/check_slurs.py` now fails on any such word that a
published file holds and `raw.md` does not.

### The wrong real person named

Five times the rewrite put a famous name where the source had another name or none:

| Episode | Published text said | `raw.md` says | Corrected to |
|---|---|---|---|
| ep48 | `Fahmi Fadzil dan kroni-kroninya` | `Farha Hashma Ramana` | `Farhash, Ramanan` |
| ep58 | `Lim Guan Eng` | `Lim Siansi` | `Lim Sian See` (Eric See-To) |
| ep60 | `Ismail Sabri`, `Ahmad Zahid` | `Ismail Saleh`, `Abid Abdullah` | `Ismail Salleh`, `Abied Abdullah` |
| ep39 | `Ismail Sabri -- eh, Wisma Putra` | `Ismail Putra` | `Wisma Putra`, no person |
| ep13 | `YB Lim Guan Eng... eh, YB Lee Chean Chung` | `YB Lee Chean Chung` | `YB Lee Chean Chung` |

In ep13 and ep39 the rewrite also invented a spoken self-correction to excuse the switch.
In ep60 a former prime minister and the deputy prime minister stood in for an Amanah
council member and a social-media account owner, identified from press reports of a RM5
million letter of demand. `scripts/check_names.py` now checks every person name against
`raw.md`. It catches four of the five; `Ismail Saleh` and `Ismail Sabri` are too close in
spelling for it.

### The model's own notes printed as speech

Five times, for example `[per classroom actually higher -- wait]` in ep34 and
`[translator's note: sentence unclear in source]` in ep16.

### Sentences nobody said

The local Whisper model inserted `Sila berasa bebas untuk menyukai, melanggan...` 142 times,
a Malay version of Chinese subtitle boilerplate from its training data. All were removed,
after the caption track showed that real speech ran straight past each one (41 of 41
checkable cases).

### Numbers and scale words

Speech-to-text confuses `juta` (million) with `bilion`. ep21 published `8.2 bilion` where the
audio says `8.2 juta`. `scripts/check_figures.py` checks every figure against `raw.md`.

### Translation of noise

Where speech-to-text produced nonsense, the translator sometimes turned it into confident
English. ep34's `Dan Mahagahan dia wampas` became `And Mahagahan, he's amazing`; the real
line was about a Friday sermon. The English file is the weakest of the four.

### Speaker labels

The camera shows who is talking, but not who is speaking off frame. Treat any label during
crosstalk as unverified.

## Before you quote this

1. Read the passage in `raw.md`, not only in `interview.md`.
2. Open the video at that timestamp. Every file has a `youtube_url`; `raw.md` has
   timestamps.
3. Do not quote `interview-en.md` or `interview-ms.md` as anyone's words.
4. Treat every proper name, and every speaker label during crosstalk, as unverified until
   you hear it.

## Automated checks

`python scripts/qa_check.py` checks every episode for the failures above and writes
`QA_CHECKLIST.md`. A clean row means no known failure was found, not that the episode is
verified. Two episodes passed as clean for months while missing 41% and 80% of their
content.

Measured 2026-09-28: 18 of 74 recordings carry at least one flag, and 6 findings are reviewed
as harmless, with reasons in `data/qa_reviewed.json`.

[ARCHITECTURE.md](ARCHITECTURE.md) describes the pipeline. [ENGINEERING_LOG.md](ENGINEERING_LOG.md)
records every failure in full.

## How to report an error

Open an issue at
[the repository's issue tracker](https://github.com/zulbino/Yang-Bakar-Berhenti-Menteri-Podcast-Transcript/issues).
Name the episode, quote the passage, and say what the video says if you know. I will fix it
and record what changed.

If you are the person quoted, your request comes first, however it reaches me. An error this
pipeline introduced is mine to correct. A dispute about what was said on the show belongs
with the original creators.

Issues are public and there is no private channel yet. If that is a problem, open an issue
asking me to contact you, and leave the details out.
