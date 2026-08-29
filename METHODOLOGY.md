# Methodology

This page covers what produced the files in this archive, how they can be wrong, and how
to report an error. Read it before you cite anything here.

A machine transcribed 168 hours of speech and a second machine rewrote the result into
readable interviews. I reviewed the output, but not line by line. Five passages had put
words in the mouth of the wrong real person before I caught them.

## Why a machine made these

I do not like generative AI, and I used it anyway, because the alternative was that this
archive would not exist.

The corpus is 68 episodes and 168 hours. The speech switches between Bahasa Melayu and
English inside single sentences, and often three people talk at once. Hand-transcribing
that is roughly a year of full-time work for one person, and I am one person doing this
outside a job. A machine transcript that exists and can be checked against the video beats
a human transcript that never gets made. That is the trade, and I would rather state it
than hide it.

## What produced each file

Every episode folder holds four files. Each one records the model that produced it in its
own `model:` frontmatter field, so you never have to guess.

`raw.md`
: The closest thing here to a source. Speech-to-text over the episode audio, lightly
  cleaned, with timestamps. Google Gemini did most of these directly from audio. Where
  Gemini was unavailable, a local model did it instead: `mesolitica/malaysian-whisper-medium-v2`,
  a Malay-specific Whisper variant, with Silero voice-activity detection for chunking. On
  those episodes the speaker turns come from a separate acoustic pass with
  `pyannote.audio`, which groups voices without knowing any names.

`interview.md`
: An editorial rewrite of `raw.md` by Anthropic's Claude, in the style of a newspaper
  interview. It keeps the original mixed Malay and English, so it stays close to how people
  actually spoke. It is not a transcript. Filler and false starts are gone and sentences
  are tidied.

`interview-en.md` and `interview-ms.md`
: Single-language versions, translated from `interview.md` by Claude. These are a
  translation of a rewrite, which puts them two steps from the audio.

The `topics:`, `hosts:`, and `guests:` lists in the frontmatter are also model-extracted.
The topic lists are scored against the show's own YouTube chapter markers, where the
episode has them, so 39 of the 68 have an external check on that field and 29 do not.

## What a human decided

Machines did the transcription, the rewriting, and the translation. I made these calls
myself:

- **Speaker names.** Diarization gives anonymous voices, not identities. I mapped them
  using three kinds of evidence: video frames, because the show cuts to whoever is talking,
  so a single close shot names the speaker; the YouTube caption track, which carries real
  turn boundaries; and voiceprint comparison against clips I had already confirmed.
- **Name spellings.** Corrected from a reviewed map with one entry per decision, checked
  against press reporting. Not a majority-vote normaliser. The majority spelling in this
  corpus is wrong for Fuziah Salleh and right for Akmal Saleh, so a blanket rule would have
  corrupted 185 correct names.
- **Disputed passages.** I listened to the original recording wherever a passage needed a
  human decision.

**I have not verified any episode line by line.** At 168 hours, I am not going to pretend
otherwise. Automated checks cover the whole archive. Human review covers the places a check
pointed at.

## How these files can be wrong

Every failure class below is measured, and the counts come from checks that now run over
all 68 episodes.

### The rewrite has named the wrong real person

Five times, the rewrite put a famous name into a sentence where the source has a different
name or no name at all, and named a real politician as a result. All five are corrected.
All five were invisible in the published text, because the invented version reads better
than the truth.

| Episode | The published text said | `raw.md` says | Wrongly named | Corrected to |
|---|---|---|---|---|
| ep48 | `kau ingat Fahmi Fadzil dan kroni-kroninya` | `Farha Hashma Ramana` | a sitting minister, plus invented "cronies" | `kau ingat Farhash, Ramanan` |
| ep58 | `baik Lim Guan Eng ke ni` | `Lim Siansi` | a former finance minister | `baik Lim Sian See ke ni`, the pro-Najib commentator Eric See-To |
| ep60 | `Ismail Sabri dapat LOD, Ahmad Zahid dapat LOD` | `Ismail Saleh` and `Abid Abdullah` | a former prime minister and the sitting deputy prime minister | `Ismail Salleh dapat LOD, Abied Abdullah dapat LOD`, an Amanah leadership-council member and a social-media account owner |
| ep39 | `Ismail Sabri -- eh, Wisma Putra is foreign` | `Ismail Putra is foreign` | a former prime minister | `Wisma Putra is foreign`, and no person belongs in the sentence |
| ep13 | `ada YB Lim Guan Eng... eh, YB Lee Chean Chung` | `ada YB Lee Chean Chung` | a former finance minister | `ada YB Lee Chean Chung` |

In ep13, `raw.md` already had the name right, and the rewrite put `Lim Guan Eng... eh,` in
front of it, inventing both a wrong name and a spoken self-correction to excuse the switch.
ep39 has the same shape, and there the source named no person at all. In ep60, the YouTube
captions independently heard the same sounds the local model did, which makes the published
names a substitution rather than a repair of a garble.

ep60 took two passes to fix, and the second needed a source outside this archive. The first
pass restored what the two speech-to-text systems heard. Both of those names then appeared
exactly once each in 168 hours, so nothing in the corpus could identify the men. The press
could. Datuk Dr Ismail Salleh, of Amanah's national leadership council, and Abied Abdullah,
a social-media account owner, were each served a RM5 million letter of demand over the RCI
Tabung Haji report. The episode agrees on the names, on their order, and on the `LOD 5
juta` figure Haziq gives half a minute later. `scripts/fix_proper_nouns.py` carries the
source.

In a passage about who is being sued, the rewrite had named a former prime minister and the
sitting deputy prime minister. The men actually named were an opposition-party council
member and a Facebook page owner.

`scripts/check_names.py` now reads every person name in the published files back against
`raw.md`, and reports any name that nothing in the source could have produced. It catches
four of these five. It misses ep60's, because `Ismail Saleh` and `Ismail Sabri` are too
similar to separate by string distance, and the tool's own docstring records that limit.

### The rewrite has printed its own commentary as speech

Five instances, all corrected. The model reasoned out loud inside text attributed to a
named speaker: `[per classroom actually higher -- wait]` in ep34, `[sic -- should be a
population figure, not currency]` in ep53, `[translator's note: sentence unclear in
source]` in ep16, a note about the speaker turning a question around in ep28, and `Farhash
[FarmaJ?]` in ep36. Two of them were right about a real defect in the surrounding text. The
aside was doing a job a check should have done.

### The speech-to-text has invented sentences nobody said

The sentence `Sila berasa bebas untuk menyukai, melanggan, maju dan memberi ganjaran untuk
menyokong lajur Der Spiegel dan Diandian` appeared 142 times across 98 files, including 29
`raw.md` files. Nobody on this podcast says it. It is a Malay rendering of Chinese
YouTube-subtitle boilerplate that the local Whisper model absorbed from its training data,
where Der Spiegel and Diandian are two unrelated channels. All 142 are now removed by
`scripts/remove_asr_boilerplate.py`.

Deleting it was only safe because the audio said so. For every occurrence, the words either
side were looked up in the episode's YouTube caption track: if both sides sit inside one
window of the captions, the real speech runs straight through the spot and nothing was
displaced. That held for 41 of 41 checkable occurrences, with no counter-example, so the
hallucination was inserted beside real speech rather than over it.

What survives, deliberately: the hosts really do ask viewers to subscribe. `Jangan lupa
untuk melanggan` is in four files, and ep16 has Haziq joking about having to say it
(`melanggan dan melanggan, celaka teruk`). Same words, different speaker, and only the
sentence shape tells them apart.

### Speaker turns are attributed to the wrong person

Diarization cuts at pauses, not at speaker changes, so one labelled block can contain
several people. 341 published turns of 400 words or more sit under a single speaker label.
Two misattributions are confirmed on camera: ep34 opens with 12 minutes of the co-host's
greeting labelled as Rafizi, and ep40 gives Rafizi's `masa saya jadi Menteri Ekonomi` line
to someone who was never a minister. Both are corrected. Treat any label during fast
crosstalk as unverified.

### Numbers and scale words change

Speech-to-text confuses `juta` with `bilion`, and a rewrite can carry the error forward.
ep21 published `8.2 bilion` where the source audio says `8.2 juta`, at three separate
spots. `scripts/check_figures.py` now reads every figure in the published files back
against `raw.md`, and reports 0 unexplained differences across all 68 episodes. Check any
number that matters against the video anyway.

### Translation invents meaning from noise

Where the speech-to-text produced nonsense, the translator sometimes translated the
nonsense into confident English. ep34's `Dan Mahagahan dia wampas` became `And Mahagahan,
he's amazing` in `interview-en.md`. The real line, from the news card visible on screen, is
about a Friday sermon. The English file is the weakest of the four.

## Before you quote this

1. Read the passage in `raw.md`, not only in `interview.md`. The raw file is closer to the
   audio.
2. Open the episode video at that timestamp. Every file carries a `youtube_url`, and
   `raw.md` carries timestamps.
3. Do not quote `interview-en.md` or `interview-ms.md` as anyone's words. They are a
   translation of a rewrite.
4. Treat every proper name as unverified until you hear it.
5. Treat a speaker label during crosstalk as unverified until you watch it.

## Automated checks

`python scripts/qa_check.py` audits every episode for the failure signatures listed above,
and writes the results to `QA_CHECKLIST.md`. A clean row means no *known* signature fired.
It does not mean the episode is verified. Two episodes read as clean for months while
missing 41% and 80% of their content, until I added checks for those signatures.

Current state: 68 of 68 episodes clean, 0 flagged, 11 findings reviewed and judged benign,
with the reasoning for each recorded in `data/qa_reviewed.json`.

For the pipeline itself, see [ARCHITECTURE.md](ARCHITECTURE.md). For every failure I hit
while building it, including the ones above in full detail, see
[ENGINEERING_LOG.md](ENGINEERING_LOG.md).

## How to report an error

Open an issue at
[the repository's issue tracker](https://github.com/zulbino/Yang-Bakar-Berhenti-Menteri-Podcast-Transcript/issues).
Name the episode and quote the passage. If you know what the video says instead, include
that. I will fix it and record what changed.

If you are the person quoted, your request comes first, and I will act on it however it
reaches me. A transcription error introduced by this pipeline is mine to correct. A dispute
about what was actually said on the show is a different thing, and that belongs with the
original creators.

GitHub issues are public and there is no private channel here yet. If that is a problem,
open an issue asking me to contact you and leave the details out of it.
