# Engineering log

Every failure this pipeline has produced, what caused it, and what fixed it, in the
order they were found. Sections are numbered `stage.issue`: **1.x** is the raw
transcription stage, **2.x** is the rewrite/translate/metadata stage. Numbers are
stable and referenced from `qa_check.py`, `data/qa_reviewed.json` and commit
messages, so they are never reused or renumbered.

These sections lived in `ARCHITECTURE.md` until 2026-08-28 and kept their numbers
through the move, so a reference in older code or commit messages to
"ARCHITECTURE.md 1.17" means section 1.17 of this file.
[ARCHITECTURE.md](ARCHITECTURE.md) now describes only the stack as it currently stands.

## Symptom index

Start here if something looks wrong. Find the symptom, read the section.

| Symptom | Section |
|---|---|
| Transcript stops early, or a stretch of audio is simply absent | [1.17](#117-content-dropped-from-the-middle-of-an-episode-invisible-to-every-check), [1.24](#124-ep00-and-ep26-are-missing-an-hour-of-audio-each-not-middle-gaps), [1.25](#125-a-check-that-starts-from-the-audio-and-the-wrong-suppression-it-caught) |
| Same passage appears twice under different timestamps | [1.6](#16-duplicate-block-hallucination-in-long-episode-continuations), [1.19](#119-ep26s-two-duplicates-and-why-needs-audio-was-the-wrong-call), [1.22](#122-the-continuation-loop-has-no-re-emission-guard-root-cause-of-ep45) |
| Timestamps drift, jump backward, or exceed the episode length | [1.10](#110-non-canonical-timestamps-past-the-first-hour), [1.11](#111-verifying-timestamps-against-youtubes-own-captions), [1.16](#116-timestamp-corruption-bug-catalog-and-a-free-corpus-wide-detector), [1.23](#123-the-drift-checker-measured-block-length-not-mistiming) |
| A word or phrase repeats hundreds of times | [1.7](#17-token-repetition-degeneration-after-repeated-retries) |
| Transcript reads like a summary, not speech | [1.8](#18-fabricated-fake-episodes-when-the-continuation-loop-runs-out-of-real-audio), [1.18](#118-a-rawmd-that-is-a-fabricated-summary-outline-not-a-transcript) |
| Wrong speaker name, or a name nobody said | [1.30](#130-why-the-obvious-generic-label-rule-is-wrong), [1.29](#129-three-speaker-label-gotchas-that-keep-recurring), [1.12](#112-verifying-speaker-labels-against-real-audio), [1.13](#113-verifying-speaker-labels-via-native-youtube-clip-processing), [1.20](#120-the-rewrite-stage-invents-speakers-out-of-mangled-honorifics), [1.26](#126-restoring-four-episodes-and-when-a-speaker-label-is-worse-than-none), [1.27](#127-seven-episodes-filed-rafizis-words-under-a-co-hosts-name), [1.45](#145-reading-the-camera-on-ep62s-farhan-disagreement-and-what-it-says-about-mai), [1.49](#149-asking-a-model-to-watch-the-video-and-reading-its-unclear-answers) |
| Gemini refuses the audio, or the API goes dark | [1.5](#15-prohibited_content-safety-block-on-politically-sensitive-audio), [1.15](#115-gemini-audio-verification-going-fully-dark-speechmatics-as-a-working-alternative) |
| Rewrite is much shorter than the transcript | [2.1](#21-choosing-a-fallback-provider), [2.2](#22-claude-silently-condensing-heavily-disfluent-chunks-instead-of-fully-rewriting-them) |
| A check keeps flagging something already judged fine | [1.21](#121-the-checklist-could-not-shrink-because-it-had-no-memory) |
| An episode has no speaker labels at all | [1.31](#131-labelling-ep45-by-scoring-blocks-instead-of-clusters), [1.26](#126-restoring-four-episodes-and-when-a-speaker-label-is-worse-than-none) |
| Most of an episode credited to the wrong speaker | [1.27](#127-seven-episodes-filed-rafizis-words-under-a-co-hosts-name) |
| A person's name spelled several different ways | [1.28](#128-one-name-eight-spellings-and-why-a-nickname-was-not-a-nickname) |
| A check reports clean but you do not believe it | [1.14](#114-a-coverage-check-that-checked-the-wrong-timestamp-and-the-content-loss-it-invented), [1.23](#123-the-drift-checker-measured-block-length-not-mistiming), [1.25](#125-a-check-that-starts-from-the-audio-and-the-wrong-suppression-it-caught) |
| Choosing or replacing a model | [1.1](#11-earlier-llm-based-candidates-rejected-before-the-whisper-comparison), [1.2](#12-which-local-asr-model), [1.4](#14-the-gemini-model-chain), [2.1](#21-choosing-a-fallback-provider) |

## Raw transcription stage

### 1.1: Earlier LLM-based candidates (rejected before the Whisper comparison)

- **Found:** before settling on a fine-tuned Whisper model, an earlier round tested
  whether a general-purpose local LLM with native audio input could replace Gemini
  outright. Five models across three architectures were run against the same real
  clip (a segment of episode 9 containing "Ahli Parlimen Ampang"), via LM Studio /
  llama.cpp on the RTX 2070:

  | Model | Result |
  |---|---|
  | `whisper-large-v3-turbo` (hosted on Groq) | Corrupted "Ampang" to "Ambang"; fabricated a plausible-sounding passage not present in the audio |
  | `Qwen3-ASR-1.7B` (`ggml-org/Qwen3-ASR-1.7B-GGUF`) | Same "Ambang" corruption and near-identical fabricated passage |
  | `polyglot-lion-1.7b` (Qwen3-ASR fine-tune for SEA languages, converted to GGUF manually) | Same corruption and fabrication: confirms the problem lives in the shared audio encoder, not the text decoder a fine-tune would touch |
  | `gemma-4-12b-it` (`unsloth/gemma-4-12b-it-GGUF`) | Uncapped: runaway generation, 1488+ tokens for a 70-second clip, never terminated (llama.cpp's Gemma-4 audio path is explicitly experimental). Capped at 154 tokens: got "Ampang" right for the first time, but substituted Tagalog for the opening Malay line and mangled the show's own name |

- **Root cause:** all five models, across three unrelated architectures, hallucinated
  the same fabricated passage at the same point in the clip: most likely a shared
  training-data reaction to an ambiguous moment in the audio (background chatter or
  cross-talk) that Gemini correctly ignored.
- **Fix / decision:** that result, plus the runaway-generation and
  language-substitution failures, closed out this line of investigation: stay on
  Gemini for raw transcription. The later local-ASR fallback (below) used a
  deliberately narrower starting point (Malay-specific Whisper fine-tunes rather than
  general-purpose multimodal LLMs) and got a working result.

### 1.2: Which local ASR model

- **Found:** five candidates were tested directly against real episode audio (a
  13-minute clip, plus two full episodes, a plain interview and a heavy-crosstalk
  debate format):

  | Model | Result |
  |---|---|
  | `mesolitica/malaysian-whisper-medium-v2` | **Selected.** No repetition-loop hallucinations on the original test clips. A real one appeared later in production on ep60 (~19s, "di atas" repeated ~140x on one noisy stretch). See Known Limitations below. |
  | `mesolitica/malaysian-distil-whisper-large-v3` | Repetition-loop hallucinations |
  | `mesolitica/malaysian-whisper-small-v3` | Repetition-loop hallucinations |
  | `openai/whisper-large-v3` (non-fine-tuned) | Repetition-loop hallucinations, plus entity errors at crosstalk moments (for example, hearing "Ampang" as "abang") |
  | A malaysia-ai custom VQ/turbo model | Repetition-loop hallucinations |

- **Context:** the crosstalk entity errors showed up even on the flagship,
  non-fine-tuned `whisper-large-v3` model, not just the smaller fine-tuned ones. That
  points to a generic Whisper-family weakness at overlapping speech, not something
  specific to one model or to Malay/English code-switching.
- **Fix / decision:** `mesolitica/malaysian-whisper-medium-v2` selected, per the table
  above. Speaker diarization for local-ASR episodes is a separate acoustic pass (see
  "speaker diarization for local-ASR episodes" under Known Limitations below):
  `[MM:SS] Speaker N: text` turns, documented in each file's frontmatter `note` field.

### 1.3: Hardware

- **Found:** local ASR runs on a machine with two GPUs: an NVIDIA RTX 2070 (8GB, used
  for inference) and a GTX 970 (4GB, otherwise idle), driver 581.57, PyTorch built for
  CUDA 13.0. With both GPUs visible to CUDA, long transcription runs deadlock
  unpredictably: a silent hang at 0% CPU, no error, at a different point in the run
  each time.
- **Fix:** `lib_local_asr.py` sets `CUDA_VISIBLE_DEVICES=0` unconditionally before
  torch initializes to force single-GPU use. Harmless on a single-GPU machine;
  required on this one.

### 1.4: The Gemini model chain

- **Context:** `lib_gemini.py` tries models in order, best-quality-first, and
  advances to the next one when the current model's free-tier daily quota (20
  requests/day per model) is exhausted, or when it hits sustained `503 UNAVAILABLE`
  (a couple of quick retries first, since a single transient 503 usually
  self-recovers, then advance):

  `gemini-3.7-flash` → `gemini-3.6-flash` → `gemini-3.1-pro-preview` → `gemini-3.5-flash` →
  `gemini-3.5-flash-lite` → `gemini-3-flash-preview` → `gemini-3.1-flash-lite` →
  `gemini-2.5-pro` → `gemini-flash-latest` → `gemini-flash-lite-latest`

- **Found:** a wrong or deprecated model ID in this list 404s identically on every
  retry, which otherwise burns a full 10-attempt backoff before failing the whole
  episode. Caught twice in practice: this list originally had `gemini-3.1-pro`
  (missing the `-preview` suffix the real model ID needs, confirmed against
  `client.models.list()`), and separately `gemini-2.5-flash` /
  `gemini-2.5-flash-lite` turned out to be fully retired (`404 "no longer available
  to new users"`, not a quota issue), so a batch that genuinely exhausted every model
  above them cascaded all the way to the end and dead-ended on two models that could
  never succeed.
- **Fix:** replaced the retired models with the `-latest` rolling aliases
  (`gemini-flash-latest`, `gemini-flash-lite-latest`), which track whatever
  generation Google currently serves instead of a pinned version number that can be
  retired later. `lib_gemini.py` also now advances immediately on a plain `404
  NOT_FOUND` (`_is_model_not_found`) instead of retrying it. Treating any 404 as
  "skip this model" fixes both incidents and the general class of bug: a model
  Google renames or retires again won't need a new special case.
- **Context:** `gemini-3.7-flash` was originally excluded outright: it repeatedly
  returned sustained `503 UNAVAILABLE` (high demand) since its Aug 13 2026 launch, a
  Google-side capacity problem, not a quota problem, so falling back to it used to
  just waste an attempt. Re-added once that congestion reportedly cleared, now with
  real 503 handling (above) instead of exclusion. `gemini-2.5-pro` and the two
  `-latest` aliases are kept at the end as a last resort for quota diversity rather
  than a first choice. Every model in this chain (not just the weakest ones) has
  shown it can silently drop mixed-language code-switching under some conditions
  (see the model-evaluation history above); `qa_check.py`'s language-density check is
  what catches that now, not model selection alone.
- **Found:** this chain handles *daily request-count* exhaustion well. It doesn't
  help with a different quota dimension: *input tokens per minute*. A single
  raw-transcription call sends an episode's entire audio as one context, and for a
  2+ hour episode that's enough volume to burn through the free tier's
  250,000-input-tokens-per-minute-per-model limit across all four chained models
  within a couple of retries, leaving no further fallback to advance to.
- **Fix / decision:** that's the actual reason `--engine local` exists for the raw
  stage: not a transcription-quality problem, a quota-shape problem specific to
  long-form audio in a single call.

### 1.5: PROHIBITED_CONTENT safety block on politically sensitive audio

- **Found:** while redoing the raw stage through Gemini across the archive, two
  episodes discussing corruption allegations against named public officials failed
  every retry with an identical error: `finish_reason=None,
  prompt_feedback=block_reason=PROHIBITED_CONTENT`.
- **Root cause:** Gemini's API has two independent safety layers: the five
  adjustable harm categories (harassment, hate speech, sexual content, dangerous
  content, civic integrity) this pipeline already sets to `BLOCK_NONE`, and a
  separate built-in "prohibited use policy" layer that no safety-setting combination
  can disable. `PROHIBITED_CONTENT` belongs to the second layer, so widening
  `SAFETY_SETTINGS` further would not have helped. Retrying the same model against it
  is also pointless (the classification is deterministic, not a transient failure),
  so the original 10-attempt exponential backoff wasted roughly 15 minutes per
  blocked episode before giving up.
- **Context:** reports on Google's own AI Developer forum note this block triggers
  more readily on the newest model generation (Gemini 3.x) than older ones,
  particularly for audio/video-understanding requests, exactly this pipeline's
  raw-transcription call shape. `gemini-3.7-flash` and `gemini-3.6-flash` had only
  just been promoted to the front of `MODEL_FALLBACK_CHAIN` (1.4 above) when this
  surfaced, which fits.
- **Fix:** `generate_content()` detects `PROHIBITED_CONTENT` immediately after the
  API call returns and advances to the next model in the fallback chain right away,
  the same mechanism already used for quota exhaustion and sustained `503`s
  (`_is_prohibited_content_block` in `lib_gemini.py`). This walks straight to an
  older/different-generation model within the same attempt, instead of exhausting
  ten identical retries against a model that will never produce output for that
  content.

### 1.6: Duplicate-block hallucination in long-episode continuations

- **Found:** found by manually cross-checking a raw.md against YouTube's own
  auto-generated captions (`yt-dlp --write-auto-subs`) after a speaker name only
  appeared in the captions, not the transcript: the surrounding ~1,600-word passage
  turned out to be duplicated verbatim at three different timestamps in the raw.md.
  A repo-wide scan then found the same pattern in 22 of 67 episodes, one with 764
  duplicate blocks (~396,000 characters, 43% of that file).
- **Root cause:** `transcribe_raw`'s continuation loop asks the model to "continue
  from where you left off" across multiple rounds for long episodes, judging
  progress purely by the last `[MM:SS]` timestamp emitted. That heuristic has a
  blind spot: if the model backtracks and re-emits an already-covered passage under
  new, fabricated timestamps instead of truly continuing, timestamps still climb, so
  the coverage check reports success while the content silently repeats. The
  existing runaway-timestamp check (1.10 below) only catches this when the
  fabricated timestamps overshoot the real episode duration; it missed cases where
  the repeated block's fake timestamps stay in a locally plausible range.
- **Context:** several already-flagged "interview.md looks truncated" entries turned
  out to be a side effect of this: the ratio check looked catastrophic partly because
  `raw.md` was artificially bloated with duplicates, not because the rewrite was
  actually that incomplete.
- **Fix (detection):** `qa_check.py` now flags any long block (300+ chars, past the
  length a naturally short recurring reaction like "Ya" or "Baik" would hit) that
  repeats verbatim at a different timestamp.
- **Fix (repair, without re-burning a Gemini call):** `scripts/dedupe_raw.py`
  cross-checks each duplicate group against YouTube's own auto-generated captions
  (`yt-dlp --write-auto-subs`) to find which occurrence's timestamp is real, then
  removes the fabricated copies. The captions are unusable for diarization or
  punctuation (YouTube's auto-captions carry no speaker labels at all, confirmed
  directly: ASR word stream only) but their word-level timing is generated straight
  from the audio, so it reliably locates where a passage actually happened. Exact
  consecutive-word matching against the captions doesn't work: Gemini's "lightly
  cleaned" transcript smooths out disfluencies the raw ASR caption still has, so
  phrasing rarely lines up word-for-word. Instead, the script scores each ~40-word
  window of the caption by how many of the duplicated block's distinctive (5+
  character) words it contains, and keeps whichever occurrence's own timestamp lands
  closest to the best-scoring window. Confirmed on a real case: a ~1,600-word
  passage duplicated at three fabricated timestamps had its true occurrence pinned
  by the caption within seconds of the earliest of the three, consistent with the
  failure mode being the model backtracking to repeat something it already said, not
  fabricating new timestamps out of nowhere. Where a group's captions don't
  confidently resolve (phrase not found, or too generic to be distinctive), the
  script leaves that group untouched and prints a warning rather than guessing; the
  continuation loop itself still doesn't reject repeated content during generation,
  so a small residue of unresolved duplicates may need a full raw-stage redo instead
  of a surgical repair.

### 1.7: Token-repetition degeneration after repeated retries

- **Found:** redoing ep13's raw stage (originally flagged for 7 duplicate blocks)
  hit a new failure mode instead: a single call succeeded on its 6th attempt after 5
  consecutive failures on the same model (`gemini-3.5-flash`): a read timeout, an
  empty response at `finish_reason=MAX_TOKENS`, an empty response at
  `finish_reason=STOP`, and two empty responses at the SDK-unrecognized
  `finish_reason=MALFORMED_RESPONSE`. The 6th attempt returned usable text, so
  `retry()` accepted it as success, but a ~90,000-character stretch of that output
  degenerated into the same short phrase repeated verbatim roughly 40 times ("SMS ke
  apa, SMS ke apa, ...") before trailing off into an unrelated English fragment, all
  inside what should have been one normal speaker turn. No new `[MM:SS]` timestamp
  was ever emitted during the repetition, so the whole degenerate stretch merged
  into a single paragraph-break-less block; `qa_check.py`'s existing wall-of-text
  check (a single block over 20,000 chars) caught it, but only as a side effect; the
  actual defect is token-level repetition, not a missing separator.
- **Root cause:** not confirmed, but the failure sequence (timeout -> MAX_TOKENS ->
  malformed x2 -> finally "succeeds") is consistent with retry-induced model
  degradation rather than a fresh, healthy generation.
- **Context:** a repo-wide check confirmed this isn't a one-off. Every other episode
  whose raw.md frontmatter records `model: gemini-3.5-flash` (5 at the time) was
  scanned for the same pattern: `ep53` had an even larger case (a 140,000-char
  stretch of one sentence repeated dozens of times), already on the flagged list
  but, like ep13, only because the repeat happened to strip paragraph breaks too,
  not because anything detected the repetition itself. The other 3 were clean. One
  near-miss worth recording: `ep48` has a real, non-buggy short repetition ("nyet
  nyet nyet nyet...", a euphemism the hosts were joking about on-air) that a naive
  detector would false-positive on. Distinguishing it from genuine degeneration
  needed a minimum total repeated span (150+ chars), not just "the same phrase
  repeats", since real filler-word repetition is short and genuine degeneration runs
  for thousands of characters.
- **Fix:** `qa_check.py` now has a dedicated `repetition_loops` check
  (`REPETITION_RE` + a minimum span filter) independent of the wall-of-text check,
  so a repetition loop that keeps normal timestamp breaks between repeats (which
  would currently pass every other check silently) gets caught directly instead of
  by coincidence.

### 1.8: Fabricated fake episodes when the continuation loop runs out of real audio

- **Found:** ep60's raw.md transcribed the real 3h18m episode correctly up to a
  genuine sign-off and `[music/outro]` marker at `[1:52:58]`, then kept going: it
  invented a chain of eleven fake mini-episodes (self-labeled episodes 61-71, each
  with its own intro/guest/content/outro) to fill the remaining ~1h25m, including
  fabricated quotes attributed to real government ministers (Fahmi Fadzil, Hannah
  Yeoh, Nik Nazmi, and others) discussing topics they never actually raised.
  Confirmed false against YouTube's real auto-captions at the same claimed
  timestamps: the real audio covers unrelated topics (university funding,
  foreign-worker minimum wage) with no mention of the fabricated ministers or
  subjects.
- **Root cause:** the continuation loop (1.6 and 1.7 above) keeps prompting
  "continue from where you left off" toward the real, correct total duration; once
  there's no real content left to transcribe, Gemini generates plausible-sounding
  fake content instead of stopping. This is a materially different, higher-severity
  risk than the duplicate-block and repetition-loop failures above: those produce
  garbled or repeated *nonsense*, easy to spot; this produces specific,
  internally-consistent false claims attributed to named real people, a
  misinformation/defamation risk if it shipped un-caught.
- **Context:** a related but distinct failure, found in the same sweep, on two other
  episodes (ep05, ep31): instead of fabricating, the model explicitly gave up and
  leaked its own refusal into the transcript (*"I am unable to provide a
  word-for-word transcript..."*), abandoning tens of thousands of characters of real
  content.
- **Fix:** redo the raw stage via `--engine local` for all three. Acoustic ASR
  (Whisper) has no mechanism to invent people or topics that aren't in the audio, so
  this failure class isn't possible with the local fallback, confirmed on ep60's
  redo, which produced a normal, verifiably real sign-off in place of the fabricated
  tail. The local engine produced a different, much smaller-stakes failure of its
  own on the redo: short stretches (typically under 20s) where Whisper gets stuck
  repeating one filler sound or word ("di atas" ~140x, "mmmm..." runs, "Maksudnya"
  ~80x) on a noisy or unclear patch of audio: garbled nonsense, not a fabricated
  claim, hand-collapsed to a short reasonable filler rather than guessed at. One
  instance across the redo batch (ep42) was more severe: a full ~4-minute speaker
  turn came out as "T-T-T-T-..." repeated hundreds of times with no recoverable real
  words: genuine content loss, not just an exaggerated filler sound. Left as an
  explicit removal note in raw.md (real gap disclosed, not invented content) rather
  than collapsed to a guessed phrase, since there's nothing in the surrounding text
  to reconstruct it from.
- **Context (detection gap, not yet closed):** no automated check catches
  invented-content fabrication directly (as opposed to its downstream symptoms).
  ep60 was found by manually scanning for a `[music/outro]`-style marker followed by
  unusually long trailing content, then reading the flagged episodes for context,
  not exhaustive, and a repo-wide re-scan after any future Gemini raw-stage batch is
  still worth doing. The leaked-refusal phrasing on ep05/ep31 ("I am unable to", "I
  cannot generate") also isn't covered by the existing leaked-reasoning check
  (`LEAKED_REASONING_RE`), which was tuned for a different phrasing pattern.

### 1.9: Doubled blank lines between every turn

- **Found:** every raw.md had two blank lines between turns instead of one, across
  every episode regardless of engine or model: confirmed as a formatting artifact,
  not a content bug.
- **Root cause:** `_normalize_turn_breaks`'s regex substitution matches twice at
  every timestamp boundary: once consuming the real preceding whitespace, then again
  as a redundant zero-width match at the resulting position, so every separator got
  inserted twice.
- **Fix:** fixed by collapsing any run of 3+ newlines to exactly one blank line
  after the original substitution, rather than chasing the regex engine's
  match-order behavior. Applied retroactively across all existing raw.md files
  (whitespace-only change, verified via diff).

### 1.10: Non-canonical timestamps past the first hour

- **Found:** 34 of 67 episodes had timestamps like `[96:37]` instead of `[1:36:37]`
  once the minutes component passed 59.
- **Context:** numerically harmless (every consumer here parses the last two
  bracket groups as minutes:seconds unbounded, so `96:37` and `1:36:37` both resolve
  to the same total-seconds value) but inconsistent with how the same episode
  formats timestamps everywhere else.
- **Fix:** fixed with a `_canonicalize_timestamps` pass in `lib_gemini.py` that
  rolls any `[MM:SS]` with MM >= 60 over to `[H:MM:SS]`, applied at generation time
  going forward and retroactively across all 34 files.

### 1.11: Verifying timestamps against YouTube's own captions

- **Context:** two independent tools exist for cross-checking `raw.md` timestamps
  against YouTube's auto-generated captions, unusable for diarization (confirmed:
  zero speaker labels of any kind, pure ASR word stream) but their word-level timing
  is generated straight from the real audio, making them a genuine independent
  accuracy signal Gemini's own self-reported timestamps can't provide.
  - **`dedupe_raw.py`** (see 1.6 above): repairs a known duplicate group by picking
    whichever occurrence's timestamp is closest to the caption-verified real time.
    Limitation confirmed directly: if none of the duplicate's original occurrences
    happen to be close to the truth, the "least wrong" pick still leaves residual
    drift, caught on ep30, where a passage survived dedup but stayed off by roughly
    11 minutes.
  - **`check_timestamp_drift.py`**: a general sweep, independent of any known
    duplicate. Samples ~12 blocks spread across an episode, fuzzy-matches each
    against the caption, and flags episodes where drift exceeds a threshold. Writes
    results to `data/timestamp_drift.json`, folded into `qa_check.py`'s own output
    (`QA_CHECKLIST.md`) as a flagged issue line per episode. A full 67-episode sweep
    found 27 flagged: some are high-confidence real drift (high match rate *and*
    high drift), but a low caption-match count (few of the 12 samples locatable near
    their claimed timestamp) is ambiguous on its own: it can mean genuine
    large-scale displacement, or just that the fuzzy caption match fails broadly for
    that episode (wrong caption language, heavy code-switching) with no real timing
    bug at all. Distinguishing the two needs a manual look at the actual caption
    text around a few "not found nearby" samples before trusting the flag as a real
    bug.
- **Root cause (shared tuning lessons, learned the hard way):** both tools share the
  same fuzzy-matching approach and inherited the same lessons:
  - Exact phrase matching doesn't work. Gemini's "lightly cleaned" transcript
    smooths out the disfluencies the raw ASR caption still has, so consecutive-word
    matches rarely line up. Both tools score a window of caption words by how many
    of a block's distinctive (5+ character) words it contains, rather than
    requiring an exact run.
  - An unconstrained search is unsafe for general drift-checking. A political talk
    show revisits the same topics (e.g. "nepotisme") at many points across a 2-3
    hour episode. `dedupe_raw.py` gets away with searching the whole caption because
    it only ever chooses among a handful of known candidate positions: even a
    slightly-off best-match reference still picks a real occurrence.
    `check_timestamp_drift.py` has no such candidate list; an early version that
    searched the entire caption for every sample produced a "58-minutes-off" false
    positive by locking onto a distant but topically-similar segment.
  - The matching noise floor is real and must be calibrated against actual data,
    not guessed. Even correctly-timed blocks showed up to ~250s of apparent drift
    from matching imprecision alone on a known-clean episode. The flagging
    threshold (300s) sits above that floor; ep30's confirmed real error (~660s) sits
    well above the threshold. A threshold picked without this empirical check would
    have either buried the real signal in noise or missed it entirely.
  - A flagged drift can be a timestamp-resolution artifact, not displaced content.
    ep41's local-ASR redo flagged at 819s max drift (well above the 300s threshold
    and close to ep30's confirmed-real ~660s), but a manual read of the flagged
    region found no missing or reordered content: instead, the VAD chunker had
    merged roughly 28 minutes of genuinely continuous speech (no pause long enough
    to split on) into one `[MM:SS]` block covering the episode's entire final
    stretch. Later caption samples inside that block legitimately occur minutes
    after the block's single claimed timestamp, so the drift is real but harmless:
    the transcript is complete and correctly ordered, just coarser-grained than
    usual for that one stretch.
  - **ep44 (RESOLVED 2026-08-27, same artifact as ep41, not a bug)**: 1.16 had
    provisionally classed ep44 alongside ep32/ep33 as "hard reset + constant
    offset" based on `check_timestamp_drift.py`'s reported +910s/+1354s drift.
    A direct re-check (fetching the cached caption and searching for phrases
    spread across each flagged block, rather than trusting the production
    tool's single mid-block sample) found no gap: this episode's local-ASR
    transcript has only 19 candidate blocks for a 3-hour episode, i.e. very
    coarse VAD merging, same root cause as ep41. The two flagged blocks are
    each one continuous Rafizi monologue (confirmed by tracing multiple
    phrases from across each block, which land at strictly increasing real
    timestamps with no gap) -- one spans a ~15-minute FWCMS/TURAP policy
    rant, the other a ~19-minute closing segment (a "cerita Papa Gomo"
    personal story) that ends with the real episode sign-off and even
    self-referential in-dialogue time-checks ("dah 3 jam") matching the
    file's real `duration_seconds`. No content is missing or displaced;
    reclassified out of 1.16's bug catalog entirely.
  - **ep58 (REVIEWED 2026-08-27, same non-bug shape, different trigger
    check)**: flagged only by `qa_check.py`'s wall-of-text check (a
    43,878-char block), not by `check_timestamp_drift.py` at all --
    `data/timestamp_drift.json` shows 12/12 samples matched with only 230s
    max drift, comfortably clean. Confirmed the giant block contains exactly
    one `[timestamp] Speaker:` label at its start and no others embedded
    inside, i.e. it's one genuinely long uninterrupted Rafizi monologue
    (consistent with the same speaking-style pattern as ep41/ep44), not
    multiple turns merged by a missing paragraph break. No fix needed; the
    wall-of-text check has no way to tell "one long real monologue" from
    "several turns merged" short of this kind of manual read, so expect it
    to keep firing here on every future `qa_check.py` run.
  - **ep43 (REVIEWED 2026-08-27, Type C confirmed via deep-probe, no fix
    needed)**: flagged for both wall-of-text (one 23,596-char block, single
    speaker label throughout, same non-bug shape as ep41/ep44/ep58) and
    `check_timestamp_drift.py` (466s max drift, 11/12 matched). Re-ran
    `_deep_drift_probe.py` directly: drift bounces between +1s and +399s
    with no sustained trend or growth (+384, +66, +17, +399, +282, +1, +220,
    +204, +32, +20 across the episode) -- scattered false-positive matches
    on topically-similar content, not real displacement, matching last
    night's original Type C classification.
- **Fix:** for `check_timestamp_drift.py`, constrained the search to a ±20-minute
  window around each block's own claimed timestamp: genuine large-scale
  displacement (whole sections off by an hour or more) now shows up as "not found
  nearby" instead of a confidently-wrong distant answer, which is a clearer signal,
  not a weaker one. Distinguishing a timestamp-resolution artifact (like ep41) from
  genuine displacement needs the same manual read `check_timestamp_drift.py` already
  calls for on ambiguous flags: check whether the block's content spans an
  implausibly long single turn before assuming the timestamp is wrong.

### 1.12: Verifying speaker labels against real audio

- **Context:** manual speaker-name review (comparing `raw.md` labels against the
  repo owner's own knowledge of who's actually speaking) is Gemini diarization's
  biggest weak point, and doesn't scale to eyeballing every line of dozens of
  multi-hour episodes. `scripts/verify_speakers.py` automates a blind spot-check
  instead: it cuts a short audio clip around a sampled turn (optionally all
  occurrences of one suspect speaker label) and sends it to Gemini with no
  transcript given, asking independently how many voices it hears and whether
  anyone is named, the same method that first confirmed a real misattribution on a
  local-ASR episode's opening exchange (see Known Limitations below). It
  deliberately doesn't auto-correct `raw.md`; a blind audio read is a strong
  disagreement signal, not proof, since it has no reference voice to match against.
- **Found (first real case solved with it):** the label "Farhan Iqbal" appears 615
  times across 11 episodes and was suspected of being one blanket bug (either a
  hallucinated name or a mixup with "Haziq Azfar"). A text-only pattern check first
  split this into two groups: 10 episodes where the label appears as a genuine minor
  third voice (never more than 1-2 turns in a row, alongside a separate Haziq Azfar
  label), consistent with a real, occasional contributor (the show's producer),
  versus ep39, an outlier with no Haziq label at all, where "Farhan Iqbal" (217x)
  and a bare "Iqbal" (84x) run a sustained 3-way exchange with Rafizi covering 43%
  of the episode's turns.
- **Fix / root cause:** audio verification confirmed both halves of that split: the
  blind spot-check found two vocally-consistent, clearly distinct speakers
  throughout ep39's "Farhan Iqbal" turns (not silence or noise), and a direct
  clip-to-clip comparison between a "Farhan Iqbal"-labeled clip and an
  "Iqbal"-labeled clip from elsewhere in the same episode came back same-speaker
  with high confidence, proving ep39's split is ONE real person labeled
  inconsistently by Gemini's diarization, not two people and not the Haziq mixup
  that applies to the other 10 episodes. Lesson: a label that looks like an obvious
  bug from text alone can be two unrelated things at once (a real recurring minor
  speaker in most episodes, a diarization-consistency bug in one outlier): a blanket
  find-and-replace across every occurrence would have been wrong for 10 of the 11
  episodes.
- **Context (related dead end):** 3 separate audio calls (a blind read, a longer
  clip, and an explicit "transcribe verbatim, do not summarize" instruction) all cut
  off at the identical phrase in ep39's spoken intro, right before the co-host's
  name would be stated. Since even an explicit verbatim instruction reproduced the
  same cutoff with no additional content, this looks like a genuine gap in the audio
  (an edit or jingle) or a name introduced via on-screen text rather than spoken
  aloud (this is a video podcast; only audio is extracted here), not the model
  withholding it. Don't keep re-querying the same clip expecting a different result;
  check the source video directly instead.

### 1.13: Verifying speaker labels via native YouTube clip processing

- **Context:** a cheaper, more capable alternative to `verify_speakers.py`'s
  download-and-ffmpeg-cut approach: Gemini's `types.Part(file_data=types.FileData
  (file_uri=<youtube_url>), video_metadata=types.VideoMetadata(start_offset="Ns",
  end_offset="Ms"))` lets Gemini watch a clipped time range directly from a public
  YouTube URL: no download, no upload, no local audio file needed at all. Two
  advantages over the audio-clip method: it's watching actual video, so it can use
  visual cues (who's on screen, lip movement) alongside voice, not just audio; and
  clipping server-side means only the requested window's tokens are billed, not the
  whole file.
- **Found (token limit, not a workaround):** sending a whole multi-hour episode this
  way still hits the model's ~1M-token context ceiling (confirmed directly: a
  3h18m video 400s into it). Clipping isn't optional for anything beyond short
  episodes: always pass `video_metadata` with a bounded range, never the bare URL
  alone on a long episode.
- **Fix (trust the timestamp you send, not the one Gemini reports):** Gemini's
  self-reported in-clip timestamps carry their own imprecision (same class of issue
  as LLM-generated timestamps generally). The reliable pattern: pick the timestamp
  to check from `raw.md` (itself worth cross-checking against YouTube's
  auto-captions first, see 1.11 above), clip a window around it, and ask only "who
  is speaking", letting Gemini supply the identity, not the timing.
- **Fix (lean prompt, matched to the question being asked):** for validating a
  single suspected speaker, `verify_speakers.py`'s descriptive prompt (voice pitch,
  tone, named mentions) is right. For mapping raw diarization clusters to real names
  across many turns at once, a much leaner prompt works better and costs far fewer
  output tokens: give Gemini the episode's known-cast list (from the video
  description, below) and ask for a bare `MM:SS - Name` list, nothing else.
- **Context (confirmed effective on ep60 and ep46):** on ep60, clip sampling
  resolved a 6-cluster diarization down to the real 3 people in the episode (Haziq,
  Rafizi, guest "Sum Dek Jo") plus genuine crosstalk, and caught a real ASR
  mishearing in the same pass ("Nurul Izan" heard aloud is actually Nurul Izzah, a
  real, frequently-discussed politician). On ep46 it resolved 2 of 4 diarized
  clusters cleanly (Speaker 1 -> Afiq, Speaker 2 -> Rafizi, consistent across 6+
  samples each) but proved the other two were genuinely mixed: both "Speaker 3" and
  "Speaker 4" turned out to contain turns from two different real people (Farhan and
  guest co-host Amin Sahmat) depending on sample point, not one person mislabeled
  twice. Not every cluster resolves to a single name: when repeated sampling keeps
  returning different real people for the same label, that's a genuine diarization
  merge, and the fix is to leave it labeled generically rather than force a
  guess.
- **Context (YouTube video descriptions are a high-value, already-available source
  of ground truth):** `data/manifest.json`'s `description` field (fetched once by
  `build_manifest.py`, no extra cost) frequently states the guest's real name
  directly, sometimes with the exact nickname used on-air ("Dato' Syed Azuan ataupun
  lebih dikenali sebagai DSA"). Worth checking before any audio-based verification:
  it's free, and resolves plenty of cases with zero Gemini calls at all.
- **Context (cost note):** the free-tier `GEMINI_API_KEY` caps at roughly 20
  requests/day per model (confirmed by hitting `429 RESOURCE_EXHAUSTED` on
  `gemini-3.6-flash` mid-session). `lib_gemini.py`'s `MODEL_FALLBACK_CHAIN` order is
  the natural fallback when this happens: switching to the next model (e.g.
  `gemini-3.5-flash`) picks up cleanly.

### 1.14: A coverage check that checked the wrong timestamp, and the "content loss" it invented

- **Found:** ep44's `--engine local` raw stage failed repeatedly with an identical
  error, always stopping "1203s before the episode's end (last turn at 9704s of
  10907s)". A first attempt at a fix (periodic `torch.cuda.empty_cache()` every 100
  chunks, on the theory that GPU memory fragmentation across hundreds of sequential
  forward passes was silently dropping chunks past roughly index 524) made no
  difference: a fresh run reproduced the exact same 9704s/1203s numbers, byte-for-byte
  identical to the run before the fix.
- **Root cause:** that exact reproducibility showed this was never a
  content-loss bug at all. Debug logging added directly into
  `transcribe_raw_local()` showed the last **pre-merge** raw chunk actually started at
  10856.9s, essentially the true end of the 10906.8s episode; every one of the final
  586/586 chunks transcribed real content, none empty. The problem was in the
  *merge* step: `transcribe_raw_local` merges consecutive same-speaker turns into one
  line that keeps only the **start** timestamp of the run (see 1.9's doubled-blank-line
  fix and the "VAD chunking splits audio every ~28s" comment for why that merge
  exists at all). ep44's final ~19 minutes were one uninterrupted speaker turn, so all
  of it correctly merged into a single 13,769-character line labeled with its start
  time, 9704s, even though the line's actual content ran all the way to the real end.
  The coverage check I'd just added compared `duration_seconds` against that merged
  line's start timestamp instead of the last chunk actually processed, so it raised a
  loud, perfectly reproducible false alarm on entirely correct output. This is the
  same class of artifact as 1.11's ep41 case (a long uninterrupted block reads as
  "drift" because later content shares one earlier label), just tripping a hard
  failure instead of a soft QA flag.
- **Fix:** check against `turns[-1][0]` (the last **pre-merge** chunk's own start
  time, anchored to real per-chunk VAD/ASR timing) instead of `lines[-1][0]` (the
  last **merged** line's start time, which a long same-speaker run can leave far
  earlier than the content it actually contains).
- **Residual limitation, not fixed:** `qa_check.py`'s own `raw.md timestamp coverage`
  check has the identical flaw, reading the *last* `[MM:SS]` label in the file's text
  rather than any true end-of-content signal, because `raw.md` only ever records a
  turn's **start** timestamp, never its end: merging discards the finer-grained
  timestamps that would be needed to detect this correctly, and that information
  isn't recoverable from the persisted file alone. Fixing this properly would mean
  changing what `raw.md` records (e.g. an end timestamp per merged line), a bigger
  format change not undertaken here. In the meantime, an episode with a genuinely
  long uninterrupted closing turn will keep showing a low coverage percentage and
  drift flag in `QA_CHECKLIST.md` even when, as confirmed directly on ep44, nothing
  is actually missing; treat that combination (low coverage + a single very long
  final block + a real sign-off at the true end of `raw.md`) as this known pattern,
  not a fresh bug, and verify by reading the file's actual ending before assuming
  content is missing.

### 1.15: Gemini audio verification going fully dark; Speechmatics as a working alternative

- **Found, 2026-08-26:** every Gemini call (rewrite, translation, and
  `verify_speakers.py`'s audio spot-check alike) started failing with `429
  RESOURCE_EXHAUSTED: Your prepayment credits are depleted`, on every model
  tier, not just the usual free-tier daily cap from 1.13. Tested across 4
  independently-created API keys, including one on a brand-new Google account
  that had never touched the Gemini API before and whose AI Studio console
  showed "Free tier" with "Set up billing" never clicked. Confirmed via a raw
  HTTP call to `generativelanguage.googleapis.com` (bypassing the `google-genai`
  SDK entirely) that the block is server-side, not a client/SDK bug. This is a
  harder failure than 2.1's original finding (shared Cloud Billing account
  across keys): a project with billing never configured still hit a
  "prepayment" error, suggesting Google's current policy requires an active
  prepay balance for any call at all, even ostensibly free-tier ones. No
  workaround found from this side; needs the account holder to actually
  complete AI Studio's billing setup.
- **Fix (unblocks diarization verification only, not the rewrite pipeline):**
  Speechmatics (`asr.api.speechmatics.com`), a third-party batch
  transcription+diarization API, used as a drop-in alternative to
  `verify_speakers.py` for cross-checking a pyannote diarization split when
  Gemini is unavailable. Recipe: `POST /v2/jobs` (multipart, `data_file` = the
  episode's `.m4a`, `config` = `{"type":"transcription","transcription_config":
  {"language":"ms","diarization":"speaker","operating_point":"enhanced"}}`),
  poll `GET /v2/jobs/<id>` until `status` is `done`, then `GET
  /v2/jobs/<id>/transcript?format=json-v2` and group consecutive same-speaker
  `word`/`punctuation` items into turns. A 3-hour episode takes roughly
  15-45 minutes to process; running 2 jobs concurrently against the same
  account worked without issue.
- **Validated on ep39:** Speechmatics' independent diarization agreed with
  pyannote's existing 3-cluster split (down to which turns land where) and
  resolved a suspected diarization merge as a false alarm: the personal,
  first-person political content ("dia dah saman aku" -- someone is suing me,
  reminiscing about being Economy Minister) that looked like it might be a
  second person mixed into the same "Speaker 1" cluster as the show's opening
  intro was, on both tools' independent read, one continuous speaker: Rafizi
  personally delivers his own third-person-style intro in this episode (see
  the Speaker naming convention section below), not the usual Haziq-does-intro
  pattern. No manual per-turn split was actually needed once that was
  understood.
- **Validated on ep36:** used to break a tie between two plausible readings of
  a fast, overlapping-banter Chinese New Year episode. Both pyannote and
  Speechmatics agreed on the aggregate 2-speaker split; Speechmatics' turn
  boundaries at the disputed points, combined with which speaker used the
  "Wabi" nickname (always addressed at Rafizi, never used by him), confirmed
  which cluster was Rafizi and which was the guest.
- **Not a full replacement:** Speechmatics has no equivalent to 1.13's
  named-identity resolution (Gemini watching video/audio and reporting who's
  speaking by name or visual cue) -- it only gives voice clusters and turn
  boundaries, same as pyannote. It resolves *whether* a diarization split is
  real or a merge/glitch; a human (or Gemini, once billing is fixed) still has
  to supply the actual name.
- **Update, 2026-08-27 afternoon: the Speechmatics diarization recipe above no
  longer diarizes, silently.** Every submission now comes back with all items in
  a single `S1` speaker cluster, while the API reports `status: done`,
  `errors: None`, and echoes the accepted config back as
  `{"diarization": "speaker", ...}`. So it looks like a success and produces a
  perfectly good transcript with no speaker separation in it at all -- read the
  distinct-speaker count, never the job status. Ruled out, one variable at a
  time:
  - **Not audio quality.** A mono 64k downmix and a faithful stereo 44.1kHz/128k
    clip of the same stretch returned all-`S1` and near-identical text (93,192
    vs 93,207 chars).
  - **Not clip length or a hard episode.** A 10-minute clip from a stretch where
    `raw.md` shows the two speakers alternating every few seconds returned
    1,284 items, all `S1`.
  - **Not `speaker_sensitivity`.** Adding
    `speaker_diarization_config: {speaker_sensitivity: 0.6}` changed nothing.
  - **Not Malay-specific.** The same clip with `language: en` returned 756
    items, all `S1`.
  Most likely an account entitlement or API change on Speechmatics' side, which
  can't be diagnosed from here -- same shape as the Gemini billing wall above,
  and it needs the account holder to check the plan. Until then Speechmatics is
  a **transcription** source only, and 1.12/pyannote is the only working
  diarization.
- **What Speechmatics is still good for (new, 2026-08-27):** used as a pure
  transcription source for the first time here, on ep35's fabricated tail
  (1.18), and the text is strong -- 93k chars against YouTube captions' 99.5k
  for the same 8,326 seconds, with the Malay/English code-switching preserved
  ("So orang akan tag aku lah kan? ... Then u know itu troll farm kan") and
  real punctuation and sentence casing, which the captions lack. Its weakness is
  the same proper-noun problem the local engine has: it renders the Mahathir
  nickname "atuk" correctly once and then as "atur", and garbles the same name
  the captions garble. Any spliced output needs the name-correction pass, not a
  spot check.
- **Update, 2026-08-27: Gemini access restored** (but see the further update
  below -- this lapsed the same day). A freshly issued API key
  works end-to-end for full audio transcription, not just text generation --
  confirmed directly via `lib_gemini.upload_audio` + `transcribe_raw` on a
  real clip and then a full ~2-hour episode. The pinned model at the head of
  `MODEL_FALLBACK_CHAIN` had since been retired (404 "no longer available");
  the existing fallback logic (2.1) auto-advanced to `gemini-3.6-flash`
  without any code change needed. A full-episode call succeeded only after
  several automatic retries (one `block_reason=OTHER` content-filter
  false-positive hit three times in a row, one `504 DEADLINE_EXCEEDED`) --
  `lib_gemini.py`'s existing retry loop absorbed all of it silently, just
  took longer than a clean run would. **Lesson for reusing this key**: don't
  hardcode it anywhere in the repo; it's stored as a User-level Windows
  environment variable (`GEMINI_API_KEY`, same convention as `NVIDIA_API_KEY`
  and `HF_TOKEN`), picked up automatically by `genai.Client()`. **Lesson for
  re-transcribing any already-processed episode now that Gemini works
  again**: never blind `--force` redo a file that already has real speaker
  names assigned -- confirmed directly that a fresh Gemini pass on a clip
  used a generic "Host" label for a speaker (Haziq) that the existing,
  already-correct `raw.md` had named correctly, the same regression class as
  the local-ASR-redo-wipes-names bug in the Speaker naming convention
  section below, just via a different engine. Where verification is wanted
  without that risk: transcribe into a scratch file, not the real one, and
  cross-check timestamps/content against the existing `raw.md` (see 1.16).
- **Update, 2026-08-27 afternoon: Gemini went walled, then a new key worked.**
  Within one session the key that had worked hours earlier began returning
  `429 RESOURCE_EXHAUSTED: Your prepayment credits are depleted` on every call,
  and a freshly issued key then worked end-to-end on real audio upload
  (`upload_audio` + `transcribe_raw` on a 133MB clip, model
  `gemini-3.7-flash`). So access is per-key, not per-account-state, and it can
  flip inside a single sitting. Two rules follow:
  - Treat "Gemini access restored" as true only for the key and session that
    verified it. The fresh-test-on-real-audio rule caught the wall before any
    work was committed to a Gemini-dependent splice, which is what it is for.
  - A trivial text call is still not sufficient evidence. The replacement key
    passed a text call and then had to be re-verified on an actual audio upload
    before being trusted.
- **A second silent failure found while hitting that wall:**
  `verify_speakers.py` **exits 0 when every one of its Gemini calls fails.** All
  four samples returned 429, it wrote a `data/speaker_verification.json` full of
  failure entries, printed them, and still reported success to the shell.
  Anything scripting around it reads that as a clean verification run. Not yet
  fixed; it belongs in the "clean exit code isn't enough" list below.
- **A stale fix for `KeyError: 'HF_TOKEN'`.** An earlier session's note said to
  re-persist the variable. That is not the problem -- it is already correctly
  persisted at User scope. It is that a fresh shell here does not inherit it, so
  the fix is per-run injection, and re-persisting an already-persisted variable
  looks like it worked and then fails again next session:
  `$env:HF_TOKEN = [Environment]::GetEnvironmentVariable('HF_TOKEN','User')`.
  Same for `SPEECHMATICS_API_KEY`.

### 1.16: Timestamp corruption bug catalog, and a free corpus-wide detector

- **Context:** 1.11's `check_timestamp_drift.py` sweep flagged roughly a
  fifth of the corpus for drift, but its own search-radius constraint (see
  1.11's Fix) means severe cases beyond ±20 minutes surface only as
  ambiguous "not found nearby" counts, not a quantified drift value --
  undercounting true severity rather than hiding it outright. Manually
  investigating several of these flagged episodes (ep05, ep10, ep26, ep32,
  ep33, ep44, ep45) turned up **four distinct bug shapes**, not one:
  - **Hard reset + constant offset** (ep32, confirmed root cause and fixed):
    the file's own printed timestamp sequence jumps backward at one specific
    line, then runs at a large but *constant* offset (exactly +2400s/40min,
    confirmed via an exact phrase match at the boundary in two unrelated
    captions) for the rest of the file (or until a second reset).
    **Critically, this does NOT necessarily mean missing content** -- ep32's
    initial diagnosis assumed a ~14-minute audio gap purely from comparing
    block-start labels, which was wrong: the mislabeled section's actual text
    picks up with zero gap from the correctly-timed content before it (both
    land at real time 02:04:14 in the caption). The fix that was actually
    needed was pure relabeling (add the measured constant offset to every
    affected timestamp), not re-transcription. Also found, bundled with the
    same bug on ep32: a 3-line literal duplicate of the episode's sign-off,
    once at the mislabeled timestamp and once at the correct one -- removed
    the mislabeled copy. **ep44 was provisionally classed here too but turned
    out to be a false alarm** -- see 1.11's ep44 entry, it's the same
    timestamp-resolution artifact as ep41, no bug at all.
  - **Genuine missing content, not just mislabeled** (ep33, confirmed via
    direct caption dump, NOT yet fixed): unlike ep32, ep33's raw.md has *no*
    backward jump at all in its own printed timestamps (the corpus-wide
    backward-jump scan below returns clean on it) -- the file stays
    monotonic while silently skipping real audio. Found two separate gaps by
    fetching the cached caption directly and searching for phrases from
    specific points within flagged blocks (the production tool's single
    mid-block sample isn't dense enough to catch this): (1) a ~4-minute real
    stretch (FWCMS foreign-worker digital-system procurement, PAC/Ketua Audit
    Negara audit findings, COVID-era contract-legality discussion) dropped
    from the middle of one paragraph, whose opening and closing sentences
    both match the real caption fine but whose middle simply isn't there;
    (2) a ~10-minute real stretch at the very end, where raw.md substitutes a
    plausible-sounding but **fabricated** placeholder --
    `[2:38:20] Music continues...` -> `[2:39:10] Music fades into a
    continuous loop for the remainder of the recording archive` ->
    `[2:48:20] End of Audio]` -- for what the real caption shows is genuine
    substantive dialogue (a Selangor land-sale/governance discussion) followed
    by the actual episode goodbye. A corpus-wide grep for this exact phrase
    (`fades into a continuous loop`) found only one other match, ep00, whose
    own "[Music / Outro]" marker covers a plausible 12-18s and is not this
    bug. Needs real re-transcription of both gaps and re-splicing, not a
    relabel -- a materially bigger fix than the other bug shapes here, left
    unfixed pending that work.
  - **Duplicated content with a fabricated later timestamp** (ep26, ep45,
    confirmed via caption cross-check, NOT yet fixed): the opposite
    direction from the reset case -- a stretch of the file's printed
    timestamps are *larger* than the content's real position, and the
    error grows across the stretch rather than staying constant, consistent
    with a passage that really occurs earlier being re-inserted later in
    the file under invented labels. More complex than ep32's case and
    deliberately left unfixed pending a proper investigation (denser
    caption sampling or a Gemini shadow-transcription of the affected
    range) -- do not assume every near-duplicate passage in a long
    monologue is this bug; real speakers do restate points for emphasis,
    confirmed ambiguous on one of ep26's own late-file passages that looked
    similar but wasn't obviously a verbatim repeat.
  - **Block misordering, correct labels** (ep05, confirmed and fixed): a
    short, internally-coherent exchange had each of its own timestamps
    individually correct (confirmed against the episode's own caption) but
    was physically placed later in the file than chronologically-later
    content. Fix was a pure cut-and-reinsert at the right position, zero
    text changed.
  - **Single mistimed line** (ep10, confirmed and fixed): one isolated line
    sandwiched between two otherwise-correctly-sequenced neighbors, content
    reads as a natural direct reply to what precedes it. Not a sustained
    bug, just one bad timestamp; corrected to a value consistent with its
    neighbors.
  - Separately, a fifth "bug" (ep45) turned out to be a plain formatting
    typo unrelated to the above: `[21:18:55]` for a ~3-hour episode, an
    extra leading digit, corrected to `[2:18:55]` per the very next line's
    `[2:19:15]`. Worth checking for this class of typo specifically (an
    implausible hour count) before assuming any large jump is a real
    content-displacement bug.
- **New detection method, free (no API or caption needed):** scan each
  `raw.md`'s own printed timestamps in file order and flag any point where
  a later line's value drops more than ~30s below the running maximum seen
  so far. This alone found all four fixed bugs above, including two
  (ep45's typo, ep05's reorder) that neither `check_timestamp_drift.py`'s
  caption-based sweep nor a manual caption-based deep-dive had found,
  because both of those bugs preserve locally-correct timestamps and would
  only show up as a hard-to-notice ordering violation, not a drift value.
  Running it across the full 67-episode corpus took seconds and found
  exactly 5 episodes with any jump over 30s -- worth adding as a permanent,
  cheap check in `qa_check.py` rather than a one-off investigation script.
- **Independent verification source discovered:** the YouTube channel
  `@mediarakyat` (channel ID `UCiqdR78bc6Tu7jRpZH7xB5A`) has re-uploaded
  nearly this entire podcast series as separate videos (often both a
  `(LIVE)` raw-stream cut and an edited `(Episod Penuh)` cut per episode),
  usually with their own independent YouTube auto-captions. Matched by
  episode number and duration (within ~1-8%, confirming same recording).
  Used to independently re-confirm ep32/ep33/ep44/ep26's bugs via a
  completely separate recording and caption run, ruling out "one caption's
  fuzzy-match coincidence" as an explanation. Also recovered usable
  captions for 2 otherwise caption-less originals (`yang-berhenti-menteri`
  ep01/ep02) and, as a side effect, confirmed a guest's real name ("Lee
  Chean Chung", ep36) directly from mediarakyat's own video title. **Not
  reliable for every episode**: checked all mediarakyat candidates for
  `yang-berhenti-menteri` ep03-14, and every single one (Live and Penuh
  alike) came back with zero automatic captions at all -- confirmed via
  direct `yt-dlp --list-subs`, not a rate-limit artifact.
- **A separate caption-availability gotcha, unrelated to mediarakyat:**
  YouTube sometimes files a Malay video's own auto-caption under language
  code `id` (Indonesian) rather than `ms`, since the two languages are
  close enough to confuse its language detector. `ms` may also be nominally
  listed but is then a lower-quality machine-translation of the `id`
  original rather than a real independent transcription. Checking `id`
  recovered captions for 3 originally-uncaptioned 2024-era episodes
  (`yang-bakar-menteri` ep01-03). `check_timestamp_drift.py` and
  `dedupe_raw.py`'s `fetch_captions()` currently only try `ms` then `en` --
  should add `id` as a third fallback (not yet done).

### 1.17: Content dropped from the middle of an episode, invisible to every check

- **Found:** `qa_check.py` reported the corpus as 53/67 clean. Two of those
  "clean" episodes were missing most of their content. `ep00`
  (`yang-berhenti-menteri`, 2025-05-10) has 60 timestamped blocks for a
  7,938-second episode, with four unexplained holes -- the largest 1,097s
  between `[1:08:16]` and `[1:27:18]`, plus 982s between `[1:42:11]` and
  `[1:58:38]` -- adding up to roughly **41% of the runtime with no transcript
  at all**. `ep26` is worse at 54%.
- **Why every existing check missed it.** The coverage check only asks whether
  the *last* timestamp reaches the end of the audio (see 1.14 for how that
  check has been wrong before), so a file can drop its entire middle and still
  score 100%. The free backward-jump scan from 1.16 can't see it either: these
  gaps jump *forward*, and the printed timestamps stay perfectly monotonic
  straight through them. This is the same class as `ep33`'s mid-episode gap,
  which only a direct caption-phrase-position check found -- but this
  detector is free and needs no captions.
- **Why the obvious version of this check does not work.** Flagging any large
  gap between consecutive timestamps over-flags **63 of 67 episodes**, because
  `raw.md` merges a long monologue into a single timestamped block (the
  coarse-VAD-merge artifact, 1.11). A genuine 6-minute monologue is
  indistinguishable from a 6-minute hole if you only look at the timestamps.
- **The fix that works:** score each gap against how much text actually sits at
  its start. Malay speech in this corpus runs roughly 13 chars/sec, so a 982s
  gap opening from a 60-char one-liner is missing content, while a 2,568s gap
  opening from a 33,000-char wall of text is not. Two exclusions matter: skip
  lead-in and tail (intro music before the first words is normal, and the tail
  is already covered), and skip blocks holding only a bracketed non-speech
  marker -- `ep48` genuinely ends at `[2:39:48]` and leaves 40 minutes of dead
  air labelled `[silence]`, which is not lost content and would otherwise be a
  false positive.
- **Now permanent in `qa_check.py`.** Flags at 10% of runtime lost. Calibrated
  corpus-wide: catches exactly ep45, ep26, ep00 and ep35, with the next-worst
  episode at 6%.
- **Related fix in the same pass.** The existing duplicate-block check had two
  bugs that hid the corpus's worst case. Its prefix regex required a
  colon-terminated speaker label (`[^:]*:`), but `ep45`'s blocks carry none
  (`[1:31:57] Sufi tahap tinggi...`), so the timestamp stayed in the comparison
  key and every repeat looked distinct -- the identical root cause already
  documented for `short_block_loops`. Its 300-char floor also sat above ep00's
  and ep26's real 60-283 char duplicates. With the timestamp stripped
  unconditionally and the floor at 60, ep45 reports **1,028 duplicate blocks,
  78% of the file**, one passage repeated 19 times. Dropping the floor to 60
  introduced no false positives anywhere in the corpus.

### 1.18: A `raw.md` that is a fabricated summary outline, not a transcript

- **Found:** `ep35` (2026-02-13, `gemini-3.6-flash`) passed every check as
  clean. Most of it is a Gemini-written *summary of the episode* presented as a
  transcript. 46,389 chars for a 3h13m episode where ~151,000 is expected:
  roughly **80% of the episode fabricated or missing**.
- **Locating the boundary needed three attempts, and register heuristics failed
  twice.** This is the most transferable lesson here.
  1. Window-level profiling of round timestamps and written-register marks said
     the transcript went bad at line 258. Wrong -- lines 258-264 are genuine.
  2. Per-*utterance* register scoring said line 278 `[55:03]`. Also wrong. That
     line claims `[55:03]` and reads "Tak pernah. Tak pernah. Setakat ini Datuk
     Seri Anwar Ibrahim tak bagi sentuh pasal kuasa SPRM ni", but the captions
     and Speechmatics independently have "Jadi sebab itu perkara ini. Saya tak
     tahu sejauh mana lagi mereka nak tarik" at that moment. Register looked
     clean because fabricated *dialogue* can be stylistically indistinguishable
     from real dialogue -- only the round-timestamp tell is reliable, and it
     fires late.
  3. **Content alignment against the captions is the actual test.** For each
     block, pull captions over a window sized to the block's own speech duration
     (`chars/13 + 60s`) and measure word overlap. Genuine blocks score 0.69-1.00;
     fabricated ones score <=0.41. Use an adaptive window, not a fixed one: at
     +/-60s the genuine 6,518-char block scored 0.43 and looked fabricated,
     because its words cannot all fall within two minutes of its start.
  **True boundary: the `[40:33]` block is the last genuine one** (0.96);
  everything from `[53:19]` is fabricated. Note also a real 4.4-minute content
  hole between ~48:53 and 53:19 *inside* what the register heuristic called
  genuine.
- **How it reads.** Numbered lists inside "speech" (`1. Rehatkan Azam Baki
  serta-merta. 2. Tubuhkan Suruhanjaya Siasatan Diraja (RCI)...`), agenda labels
  (`Baik, kita masuk segmen terkahir: Soal Jawab & Mak Lampir / PKR`),
  third-person descriptions of what was said rather than the words themselves
  (`Sembang pasal komen-komen orang terhadap podcast YB`), and written-register
  marks real speech never contains -- `/` as a conjunction and parenthetical
  glosses like `(bekas setiausaha politik Anwar)`.
- **This is a new hallucination shape.** Distinct from ep33's fabricated
  `[Music fades into a continuous loop...]` placeholder (which at least admits
  content is absent), from plain truncation (2.2), and from every repetition
  variant in 1.16 -- this one is fluent, plausible, topically accurate, and
  therefore the hardest to notice by reading.
- **Free detector, now permanent in `qa_check.py`:** timing that was invented
  rather than measured lands on round minute boundaries. Real ASR timestamps
  land on arbitrary second values, so ~1.7% should end in `:00` by chance.
  ep35 is at **25%**, and it is the only episode in the corpus above 8% --
  a clean separation, flagged at a 12% threshold.
- **`Fizi` resolved: it is the host, and the correct name is `Haziq`**
  (user-verified against the audio). The mechanism is worth understanding because
  it is the same bug class as ep38's `Nazri`/`Haziq`. The host's line is
  `Macam biasa bersama saya, saudara Rafizi` -- he is introducing the *guest*.
  YouTube's captions garble that to "saudara Fizi Ramlie", dropping the "Ra".
  Gemini took that truncation of the **guest's** name and applied it as the
  **host's** label, so the file has Rafizi's name split across both speakers.
  Supporting evidence: the host calls the other party "YB" throughout (hosts do,
  Rafizi does not call himself that); the captions say Farhan was absent that
  day; and at `[1:23:27]` the audio has "Saya dah bacalah. Haziq pun dah baca",
  a third-person reference placing Haziq in the room.
- **One hallucinated token stood in for three different things**, so a
  replace-all would have introduced new errors -- it would have written "Haziq
  introduces Haziq" and "Haziq is sick, Haziq isn't here":

  | Location | raw.md says | Actually | Count |
  |---|---|---|---|
  | speaker labels | `Fizi:` | Haziq | 91 |
  | intro, L18 | "saudara Fizi" | saudara **Rafizi** | 1 |
  | L132 | "Fizi tak ada" | **Pa'an** tak ada | 1 |

  **Lesson for the corpus-wide wrong-name audit:** a wrong name is not
  necessarily a single substitution, and in-text occurrences answer differently
  from speaker labels. Both confirmed instances of this bug class (ep38, ep35)
  landed on the **host** label, so start there rather than sampling all speakers
  evenly.
- **A caption limitation found while verifying this:** YouTube merges speakers
  within a single cue. At `[22:45]` the captions read "Hazid demam. Pakan tak ada
  hilang", which is actually Rafizi's "Haziq demam! Pa'an tak ada" plus Haziq
  interjecting "Pa'an hilang". Do not treat one caption line as one speaker.
- **Engine bake-off for the re-transcription, measured against the captions as
  reference** (2026-08-27). All three ran on the same clip:

  | | recall | precision | repetition | blocks | speakers |
  |---|---|---|---|---|---|
  | local ASR | .851 | .909 | **1,323ch loop** | 7 (max 56,785ch) | none, 1 cluster |
  | Speechmatics | .864 | .914 | 0 | 1 | none, no-op (1.15) |
  | Gemini | **.917** | **.949** | 0 | 136 (max 10,667ch) | **Rafizi / Host** |

  Local ASR is unusable: 7 blocks for 138 minutes with the largest at 56,785
  chars (the wall-of-text check trips at 20,000), a hallucination loop, and
  pyannote resolving a two-person conversation to a single cluster.
- **Gemini's winning score is partly an artefact of a serious flaw: it
  normalises proper nouns into the generic category it thinks they mean.** The
  spoken name here is "Ceplos" (user-verified against the audio). Gemini rendered
  it **"cybertroopers" 17 times out of 17**, in sentences otherwise word-identical
  to Speechmatics'. A 2-minute liveness clip of the same passage produced a third
  answer, "Chegubard" -- a real Malaysian activist. So two runs, two different
  fabricated-but-entirely-plausible names, on a name the weaker engine got right
  every time.
  - **Word-overlap metrics structurally cannot catch this**, because
    "cybertroopers" genuinely occurs elsewhere in the same episode. Fluent
    normalised text scores *better* against a reference than an unfamiliar proper
    noun does.
  - **A capitalised-token check does not catch it either.** Flagging capitalised
    words unsupported by other sources found 13 candidates and missed all 17 of
    these, because a substitution *into* a common word looks unremarkable. Of
    those 13, only one was a real error; the rest were valid alternates
    (`Dato'`), ordinary Malay words, or names Gemini got *right* that the others
    lost entirely (Lalitha Kunaratnam, Fleximart, Free Anwar Campaign).
  - Assume further entity normalisations remain undetected in any Gemini output.
- **Chosen construction, using each engine only for what it demonstrably does
  well:** Speechmatics for text and timings, Gemini for speaker spans mapped on
  by time. Gemini's timestamps are reliable enough for this -- median drift **0s**,
  range -1s..+2s against Speechmatics' word timings.
  - **Snap speaker changes to sentence ends.** A raw time cut at +/-2s accuracy
    still slices mid-clause in fast speech, which produced turns like
    "hitam? Baju" out of "Baju hitam?". Snapping to the nearest sentence
    terminator within 12 words fixed 73 of 125 boundaries.
  - Rejected: caption `>>` markers as turn boundaries. There are 676 real ones
    (median gap 9s) and they look promising, but alternating speakers across them
    gave mean turn lengths of 142ch vs 138ch -- a ratio of 1.03, i.e. no speaker
    signal at all. Labels derived that way would have been invented structure
    presented as data.
  - Sanity check that passed: Rafizi 89,879 chars vs Haziq 3,217 (29:1), matching
    Rafizi's own on-air remark that he had to do the talking because Haziq was
    ill and Pa'an was absent.
- **Fixed 2026-08-27.** Spliced from `[40:33]` onward and `rewrite`/`translate`
  re-run via Claude. raw.md went 46,389 -> 136,466 chars against ~151,000
  expected for a 3h13m episode, the shortfall being the 2:38 of intro music and
  natural pauses. ep35 now passes all three checks: off the QA flag list, off the
  1.17 content-loss list, and the round-timestamp probe reports **zero** episodes
  above threshold corpus-wide (ep35 was the only one, at 25%).
- **One translation defect the splice exposed, worth knowing about.** "Ceplos" is
  a coined term for a specific team of cybertroopers, so it is a named actor. The
  English translate pass read it as *ceplas-ceplos* (Malay for blurting things
  out) and rendered it four different generic ways across ~8 paragraphs -- "cheap
  shots" x4, "outbursts" x3, "PKR sources", "blabbermouth" -- erasing the actor
  from the English edition while `raw.md`, `interview.md` and `interview-ms.md`
  all kept it correctly. So coined terms are vulnerable at **both** the
  transcribe stage (Gemini normalising it INTO "cybertroopers") and the translate
  stage (normalising it into a different generic category). Fixed with verified
  targeted edits; each replacement had to share anchor words with a Malay
  paragraph that used the term, so a generic phrase standing in for some other
  word could not be swept up.

### 1.19: ep26's two duplicates, and why "needs audio" was the wrong call

- **Prior status:** ep26 was the corpus's most ambiguous open case, deliberately
  left untouched on the grounds that it needed someone to listen to the audio to
  decide whether a repeated passage near the end was a bug or genuine rhetorical
  restatement. It did not. Text alone settles it, and cheaply.
- **The settling argument:** the repeated span is **13,571 characters**. A
  speaker cannot reproduce 13.5k characters of speech a second time, so
  restatement was never a live hypothesis. Anything above roughly a paragraph
  can be decided without audio; reserve the audio budget for genuinely short
  ambiguous spans (ep31's two orphan lines are the real example of that).
- **Which copy to delete, decided by ordering not by content:** the block appears
  at `[01:34:55]`-`[01:35:33]` twice. The first sits in a monotonic position
  (`00:23:14 -> 01:34:55 -> 01:56:00`); the second violates ordering
  (`02:20:25 -> 01:34:55 -> 02:22:25`). The ordering-violating copy is the
  spurious insert, and removing it also cleared the backward-jump flag from 1.16.
- **The copies were not byte-identical**, which matters for how you write the
  guard. In 12,867 chars they differ at exactly one token boundary (`bolehlah`
  vs `boleh lah`), so the second copy came from a *separate transcription pass
  over the same audio*, not a straight copy -- consistent with the
  continuation-loop re-emission in 1.16. A byte-equality assertion fails here
  and a whitespace-collapsing one also fails; compare with whitespace stripped
  out entirely. The retained copy is also the correctly-spelled one, since
  `bolehlah` is right for the Malay `-lah` suffix.
- **A second, different duplicate found in the same pass, and a third duplicate
  shape.** `[02:23:55]` shares its first **2,515 chars** with `[02:13:28]`
  verbatim, then diverges: the first continues in Malay for 11,991 chars while
  the second stops at 2,771 with a 256-char **English** restatement of the
  two-school-types distinction the first already covers in Malay. So the
  language-drift bug can reach `raw.md` itself, not just the rewrite stage. This
  shape -- long shared prefix, then divergence -- evades all three earlier
  detectors: exact matching misses it (they diverge), `difflib` scores it low
  (the tails are unrelated text), and the language-density check passes (the file
  is overwhelmingly Malay overall).
- **Deliberately not made a permanent check.** A corpus-wide prefix-duplicate
  sweep at a 400-char floor found this shape in exactly one other place: ep45,
  where the hits are trivial variants of duplicates the fixed 1.17 check already
  reports. With one real occurrence corpus-wide there's nothing to calibrate a
  threshold against, so this stays a scratch probe rather than a `qa_check.py`
  check that would mostly generate noise.
- **A misplaced duplicate also inflates the 1.17 content-loss figure.** Before
  the fix ep26 reported 4,813s lost across two gaps (54% of the episode); after
  it, 2,990s across one (34%). The second "hole" was never missing content -- it
  was the artifact of the duplicate block sitting at the wrong point in the
  timeline, so the gap measured from its end to the next real timestamp. Order
  matters when triaging: clear duplicates and ordering violations *first*, then
  re-measure content loss, or you will go looking for audio to re-transcribe that
  was never absent.
- **Still open on ep26:** the remaining 2,990s gap between `[00:23:14]` and
  `[01:34:55]` (34% of runtime) is real missing content and needs
  re-transcription.

### 1.20: The rewrite stage invents speakers out of mangled honorifics

- **Found 2026-08-27**, after the user said they had never heard of a "Bobby" in
  the podcast. The rewrite stage had given "Bobby" **246 labelled turns** across
  ep04/ep19/ep22, and the metadata stage listed him as a host or guest in four
  episodes. There is no Bobby. It is the ASR collapsing **"baik YB"** into one
  token -- Haziq addressing Rafizi as YB while moving to the next segment, which
  is why every occurrence sits at a segment transition.
- **The detector: `scripts/label_drift_audit.py`.** Any speaker label present in
  `interview*.md` but absent from `raw.md`. It buckets results, because a first
  version that did not flagged 63 of 67 episodes and was useless:
  - `VARIANT` -- token subset either way ("Rafizi" / "Rafizi Ramli"). Ignored.
  - `SPELLING` -- close but not identical ("Eric See-To" / "Eric Sito"). Real,
    low severity, and what the proper-noun pass is for.
  - `INVENTED` -- no relation to any raw.md speaker. Highest severity.
  - `GENERIC` -- "Host", "Interviewer", and their Malay equivalents
    (`Pewawancara`, `Penemuduga`, `Ko-hos`, `Klip petikan`). Without those in the
    stop-list, translated placeholders read as invented person-names.
- **The confirmed cases all share one root cause: a mangled honorific or a common
  noun promoted to a speaker.** The rewrite appears to treat any unattributed
  name-shaped token as a speaker label:

  | Episode(s) | Invented label | Actually |
  |---|---|---|
  | ep04/19/22 | `Bobby` (246 turns) | "baik **YB**", spoken by Haziq |
  | ep44 | `baby` x25 in text | **YB**; captions render it "babi" (= pig) |
  | ep44 | `Aziz` | Haziq (raw.md `[01:16]` carries the line verbatim) |
  | ep02 | `Abie` | Haziq |
  | ep08 | `Zak` | Rafizi |
  | ep22 | `Razal` | Haziq |
  | ep27 | `Amy` | Farhan |
  | ep00 | `Hakim` | the common noun *hakim* (judge), still unconfirmed |

- **The three-stage propagation matters for how you fix it.** Each stage needs a
  *different* repair, and a blanket rename is wrong:
  - frontmatter `hosts`/`guests` -> **drop** the entry (no such person)
  - frontmatter summary prose -> the real host's name
  - speaker labels -> the real speaker
  - dialogue mentions -> the honorific ("YB")
  Renaming everything to "YB" would have written `hosts: - Rafizi - YB`.
- **Verify each occurrence; the counts lie.** Two near-misses caught this way:
  one ep44 "baby" is genuine English ("umur pertengahan 40 lebih tu kira masih
  baby lah", about a politician's age), and an exclusion regex with a bare
  unanchored `a` alternative matched "Beri**a** baby" as "a baby" and wrongly
  protected it. In Malay, where many words end in 'a', unanchored single-letter
  alternatives are actively dangerous.
- **`raw.md` is not automatically authoritative either.** In ep04 and ep06 the
  ASR was wrong and the rewrite *repaired* the name -- raw.md had "Chegubard"
  where the audio says "ceplos", and "Cikgu Bard" where it says "Chegubard",
  while all three interview files were already correct. So the rewrite stage both
  corrupts names and corrects them depending on the case, and a proper-noun audit
  has to compare all four files per episode rather than trusting either side.
- **Cross-check against `data/manifest.json` before calling a name invented.**
  Every episode's YouTube description is stored there and usually announces
  guests. That check reclassified two of my own findings: `Dato' Syed Azwan` is a
  real declared guest ("Dato' Syed Azuan ataupun lebih dikenali sebagai DSA"), and
  `Dr Irwan Arifin` is declared in ep08's description. Both had been flagged only
  because raw.md leaves those guests unlabelled. **Also watch the duplicate
  episode numbers** -- the corpus has two ep05s across the two series, and I
  initially audited the wrong one.
- **Still open:** 19 invented labels across 16 episodes remain unverified, plus 3
  spelling variants. ep00's `Hakim` and `Rashidi bin Haji Bandar Ahmad` need
  audio; the rest need the same caption cross-check.

### 1.21: The checklist could not shrink, because it had no memory

- **Found 2026-08-27, from a fair challenge:** why does `QA_CHECKLIST.md` never go
  down? At the time it held 15 flagged episodes. Categorising the flags answered it:
  **11 of the 15 were flagged only by `drift` and/or `wall-of-text`** -- and both
  had already been adjudicated as false positives in earlier sessions. The
  2026-08-27 handoff says so explicitly: *"ep44 turned out to be a FALSE alarm...
  same coarse-VAD-merge artifact as ep41... ep58, ep43: also confirmed non-bugs."*
  They were still flagged.
- **Root cause: `qa_check.py` fully overwrites `QA_CHECKLIST.md` on every run**,
  emitting `- [ ]` for flagged and `- [x]` for clean. The checkboxes are therefore
  decorative -- tick one after reviewing an episode and the next run erases it.
  There was nowhere to record "reviewed, benign, because X". So every session
  re-discovered and re-investigated the same resolved episodes, and the count
  stayed pinned at 14-16 no matter how much real work happened. **The checks were
  not too strict; they were amnesiac.** A verdict that lives only in prose is a
  verdict the tool will keep asking about.
- **Fix 1, a review ledger: `data/qa_reviewed.json`.** Episode slug -> signature
  name -> `{verdict, reason, date}`. A `benign` verdict moves that issue out of the
  flagged list into a "Reviewed, judged benign" section of the checklist, struck
  through, with the rationale printed. Every issue now carries a stable signature
  name (`drift`, `wall-of-text`, `content-loss`, `duplicates`, `backward-jump`,
  `truncated`, `coverage`, `round-timestamps`, ...) so the ledger has something to
  key on. Deleting an entry re-flags it; reprocessing an episode should clear its
  entries so the new output is judged fresh. A suppression with no reason recorded
  is worse than no suppression.
- **Fix 2, automate 1.11's test instead of leaving it to prose.** The wall-of-text
  check exists to catch MERGED TURNS -- lost paragraph breaks running several
  speakers together. A block that merged turns still contains their inline
  `[MM:SS] Speaker:` markers, so counting them separates the cases: one marker is a
  genuine long monologue (the coarse-VAD-merge artifact, not a defect), two or more
  means turns really were merged. This cleared ep58 outright and removed the flag
  from ep41/ep43/ep44 with no manual suppression needed, which is strictly better
  than a ledger entry -- the tool now reaches the same verdict a human did.
- **Fix 3, a drift magnitude floor (`MIN_ACTIONABLE_DRIFT_SECONDS = 60`).**
  `check_timestamp_drift.py` is a sampling heuristic with a documented
  search-radius limitation (1.11), so small reported drift is not evidence of a
  defect. The corpus splits cleanly: ep21 at 8s and ep05 at 22s on 1.5-2.7 hour
  recordings -- within caption-alignment noise, not actionable at any effort level
  -- against 325s to 1083s for every other flagged episode.
- **Result: 15 -> 12 flagged, and the remaining 12 are all genuine open questions**
  rather than re-litigation: 3 hard content defects (ep00, ep26, ep45) and 9
  drift-only episodes needing one verification pass each. Because of the ledger,
  each of those passes is now permanent.
- **The wider lesson for this repo.** Adding a check is cheap and satisfying;
  adding a check without a way to record its adjudication converts a one-off
  investigation into a recurring tax. Any new signature should ship with a
  signature name so the ledger can retire it.

### 1.22: The continuation loop has no re-emission guard (root cause of ep45)

- **Found 2026-08-27**, from a fair challenge: why does ep45 need "redoing again"?
  It does not -- **ep45's `raw.md` has never been re-transcribed.** Its only
  commits are corpus-wide sweeps (the folder split, a blank-line fix, timestamp
  canonicalisation, the host short-name convention), and it carries no `model:`
  line, so it is the original transcription. The 2026-08-26 commit "Fix ep44,
  ep45, ep49 (severe truncation)" touched ep45 but **not** `raw.md` -- it repaired
  the interview rewrites only.
- **But the bug that produced it is still live and unguarded.**
  `lib_gemini._generate_with_continuation` accumulates up to 8 continuation
  rounds with no test that a chunk advances past what is already collected:

      full_text = ""
      for _ in range(8):
          resp = generate_content(client, contents, config)
          text = _text(resp)
          full_text += text          # no overlap check
          if _finish_reason_name(resp) != "MAX_TOKENS":
              return full_text

  When the model backtracks and re-emits a covered passage under fresh
  timestamps, the loop appends it, and the "last timestamp keeps climbing"
  progress heuristic still reads as satisfied. That is exactly ep45: 1,028
  duplicate blocks, one passage repeated 19 times, 78% of the file, plus a
  runaway `[21:18:55]` stamp on a 2h58m episode.
- **So a plain `--force` redo can reproduce the same failure.** Three things
  qualify that:
  - **It is intermittent, not deterministic.** ep35's Gemini run went through the
    same loop over a 2h33m clip and produced zero repetition.
  - **It would no longer ship silently.** The duplicate-block check fixed in 1.17
    is precisely what was blind to ep45 before, so a failed redo now gets caught
    by `qa_check.py` rather than sitting in the corpus.
  - **Speechmatics is structurally immune**: a single batch job with no
    continuation loop, so re-emission cannot occur by construction. Measured at
    zero repetition on a comparable-length clip, with the best literal
    proper-noun fidelity of the three engines (1.15).
- **Recommended order, not yet done:** add an overlap guard to the continuation
  loop first -- reject or retry a chunk whose opening duplicates accumulated text
  -- since that protects every future transcription rather than one episode. Then
  transcribe ep45 with Speechmatics for text and timings and Gemini for speaker
  spans only, the combination validated on ep35 in 1.18.
- **General lesson.** This bug was documented in prose (in `qa_check.py`'s
  duplicate-block comment) for weeks while nothing enforced it, and a redo was
  being recommended without anyone checking whether the root cause was fixed.
  Before reprocessing an episode, check whether the failure mode that broke it is
  still reachable.

### 1.23: The drift checker measured block length, not mistiming

- **Found 2026-08-27**, from a fair challenge: nine episodes (ep27, ep31, ep34,
  ep41, ep43, ep44, ep47, ep51, ep56) had sat on the checklist as "drift-only,
  needs one verification pass" across several sessions. All nine came from one bug
  in the checker.
- **The evidence was already in the data I had collected.** Every drift spike in the corpus
  was *positive* -- not one negative outlier in nine episodes -- and every spike
  landed on the longest block in its sample. Drift caused by mistiming has no
  reason to prefer one sign or to correlate with block length.
- **Cause.** `check_episode` extracted its comparison phrase from the *middle* of
  a block and compared the result against the timestamp at the block's *start*:

      content_words = re.sub(r"[^\w\s]", " ", block.lower()).split()
      mid = len(content_words) // 2
      phrase = content_words[mid:mid + 20]
      actual_ts = find_nearby_timestamp(words, times, phrase, claimed_ts)

  A block's timestamp labels where the block begins. `raw.md` blocks routinely run
  to 1,000-5,500 words because of the coarse-VAD merge behaviour described in
  1.11, so a block's midpoint is genuinely 10-20 minutes of audio after its start.
  The check was reporting half the block's duration and calling it mistiming.
- **Fix**: strip the `[MM:SS] Speaker:` prefix and take the phrase from the
  block's head, which is what the timestamp actually labels.
- **Effect, corpus-wide.** Max drift on the nine fell from 325-1083s to 17-29s.
  The corpus median max-drift is now **21s**, and only three episodes exceed 60s.
  The module docstring's claimed "noise floor of roughly 100-250s even on
  correctly-timed blocks" was never a noise floor -- it was this bias, measured
  and then written down as a property of the method. `DRIFT_THRESHOLD_SECONDS`
  (300) was calibrated against it, so the threshold now sits ~10x above the real
  noise floor rather than barely above a phantom one.
- **What survived the fix**: ep00 (446s) and ep45 (845s), both genuinely broken
  and both already flagged by stronger checks, plus ep17 (958s), a single
  false phrase-lock adjudicated benign in `data/qa_reviewed.json`.
- **I tested match confidence as a way to retire ep17 automatically, and
  rejected.** Across all 470 samples the score separates poorly: ep45's *real*
  defect matches at 4/5 distinctive words (0.80) while ep00's *real* defect
  matches at 4/13 (0.31), straddling ep17's false lock at 4/9 (0.44). No honest
  cut exists, so ep17 got a ledger entry instead of an invented rule. Per 1.21,
  prefer an objective test to a ledger entry -- but only when the objective test
  actually separates the cases.

This checker's own output contained the proof it was wrong for as long as it had been
running: every spike positive, and every spike correlated with block length. I had been
reading its residual error as a list of suspects when it was data about the checker
itself. Nine episodes stayed open across several sessions because of a measurement
artifact.

### 1.24: ep00 and ep26 are missing an hour of audio each, not "middle gaps"

- **Found 2026-08-27** while working the two remaining content defects with the
  captions-first method 1.17 recommends.
- The checklist described ep00 as "41% missing across 4 gaps" and ep26 as "34%
  missing, one 2,990s gap". Both understate the damage and misdescribe its shape.
  A first probe looked reassuring -- 70-95% of each gap's distinctive caption
  words were present somewhere in `raw.md` -- but that test is worthless: single
  common Malay words will match somewhere in a 130-minute transcript by chance.
- **4-gram coverage, bucketed by time, settles it.** Word 4-grams are
  rare enough that a match means the speech is genuinely present. Sliding a
  60-second window across the caption and asking what fraction of its 4-grams
  appear anywhere in `raw.md` produces a coverage strip that localises loss
  exactly. Both episodes show normal coverage for their first ~75 minutes and
  then flat zero to the end:
  - **ep00**: zero coverage from 4800s to 7860s (caption runs to 7935s).
  - **ep26**: zero coverage from 4920s to 8880s (caption runs to 8826s).
- **Reverse-mapping each block to its true audio position** (the ep35 fabrication
  recipe, 1.18) explains what filled the space:
  - **ep00** transcribes audio 0-4050s correctly, then blocks `[4088]`, `[4092]`,
    `[4096]`, `[5238]`, `[6127]`, `[6131]` and `[7118]` are verbatim re-emissions
    of blocks `[2612]`, `[2617]`, `[2620]` and `[3652]` under fresh timestamps
    (identical char counts, identical median audio origin). Blocks `[5710]`-`[5763]`
    hold real content displaced from audio 4361-4760s. Then it jumps to the
    genuine outro at `[7860]`. **Roughly 57 of 132 minutes were never transcribed.**
  - **ep26** holds real content in order out to audio ~4880s, but every timestamp
    from block `[1394]` onward is wrong -- `[5733]` is really 3222s, `[6960]` is
    really 3858s, `[8950]` is really 4077s. **Roughly 66 of 147 minutes are absent.**
- **Both are the 1.22 continuation-loop failure**, matching ep45 and ep35: the
  model backtracks, re-emits covered ground under new timestamps, and the loop
  appends it while the "last timestamp keeps climbing" heuristic still reads as
  satisfied. The re-emitted material consumes the output budget that the real
  remaining hour needed. That makes three confirmed victims of one unguarded loop
  (ep00, ep26, ep45) plus one suspected (ep35).
- **Consequence for the repair plan**: neither episode can be fixed by editing
  `raw.md`. Both need re-transcription of the missing tail, and the overlap guard
  should land first so the redo cannot reproduce the same failure.

**Why the existing content-loss check understated both**: it measures gaps
*between* consecutive timestamps against the text at the gap's start, so it can
only see loss that leaves a hole in the timeline. Loss backfilled by duplicated
or displaced blocks presents as a populated timeline and largely escapes it. The
4-gram coverage map has no such blind spot because it starts from the audio and
asks what is missing from the transcript, rather than starting from the
transcript and asking what looks odd.

### 1.25: A check that starts from the audio, and the wrong suppression it caught

- **Found 2026-08-27**, immediately after 1.24. Having established that 4-gram
  caption coverage localises content loss where the gap-based check cannot, the
  obvious next question was whether ep00 and ep26 were the only two. They were
  not. **ep48 is missing roughly 40 minutes**, and it had been affirmatively
  waived as benign in `data/qa_reviewed.json`.
- **The waiver read**: *"The 40-minute 'hole' is genuine dead air: the episode
  ends at [2:39:48] and the rest of the video is silence, labelled [silence] then
  [end of audio]."* That is an accurate description of what `raw.md` says. It is
  not what the audio contains. The captions carry speech at a steady ~500 words
  per five minutes from 9,500s to 11,900s -- normal conversational density,
  sustained for 40 minutes, which YouTube's ASR does not manufacture over
  silence. The content is coherent and substantive (PH's values, the cost of
  staying in power, PN). Checked against the one benign explanation, a video
  containing a second copy of the episode: the tail shares **0.2%** of its
  4-grams with everything before it. It is new material.
- **`raw.md` ends on a natural sign-off** (*"Selamat malam, jumpa hari Ahad"* at
  `[2:39:35]`), which is exactly why the waiver looked right. A transcript that
  stops at a plausible ending and labels the remainder `[silence]` is
  indistinguishable from a correct one **from inside the transcript**. Only the
  audio settles it.

**The check** (`scripts/check_caption_coverage.py`, signature `caption-coverage`)
slides a 60s window across the caption and scores each bucket by the fraction of
its word 4-grams appearing anywhere in `raw.md`. It runs opposite to every other
check here: it starts from the audio and asks what the transcript is missing,
rather than starting from the transcript and asking what looks odd. That is what
makes it immune to the backfill blind spot -- duplicated blocks, displaced
blocks, and `[silence]` markers all populate the timeline, and none of them
create a 4-gram match.

**Calibration.** An absolute floor does not work, because how closely `raw.md`'s
wording tracks the captions varies by episode. Healthy episodes cluster at 22-28%
baseline coverage with worst dead runs of 0-120s. Four episodes sit at 0-3% for
reasons that are not content loss -- ep02 has English captions against a Malay
transcript, ep21's YouTube ASR runs at half normal word density, ep03's wording
diverges from the captions throughout (its blocks still map to the correct audio
positions, verified), and ep45's `raw.md` is 78% duplicated. Each bucket is
therefore judged against its own episode's median, an episode below 10% baseline
is reported `inconclusive` rather than flagged, and a dead run must reach 10
minutes. Result on the corpus: 59 clean, 5 inconclusive, 3 flagged (ep00, ep26,
ep48), no false positives.

**Two lessons.** First, `fetch_captions`
re-downloaded every `.vtt` on every call; a throttled fetch returns `None`, every
caller reads that as "no captions", and the episode reports clean having never
been examined. Now cached. Second, the expensive one. 1.21 established that a verdict with nowhere to live is a
recurring tax, and the ledger fixed that. ep48 shows the same tool cutting the other
way. **A ledger entry is as permanent as it is convenient, so a wrong one does more
harm than no entry at all.** It turns an open question into a settled answer, and then
nobody checks again. I wrote the ep48 waiver from the transcript alone, to settle a
claim only the audio could settle. Suppress an issue on evidence from outside the file
being reviewed, or leave it flagged.

### 1.26: Restoring four episodes, and when a speaker label is worse than none

- **2026-08-27.** ep00, ep26, ep45 and ep48 were all victims of the same
  unguarded continuation loop (1.22). Between them they were missing about three
  hours of audio. All four are now restored and the loop is guarded.
- **The method, in the order that matters.** 1.24's lesson was to content-align
  before cutting audio; `scripts/align_blocks.py` does it, mapping every block
  to its true audio start by head-phrase matching against the whole caption. Run
  it *first*, every time. It is what showed that ep48's "missing" finale was not
  missing at all -- it was sitting in `raw.md` displaced by 2,384s -- and that
  ep26's blocks were out of order, and not simply shifted.
- **Splice, don't redo.** `scripts/splice_gap.py` keeps the verified head and
  tail verbatim and replaces only the damaged middle. ep48 kept 349 of its
  original blocks, ep00 kept 45 plus its outro, ep26 kept 93. Everything kept
  retains its hand-reviewed speaker labels, which a wholesale redo would have
  destroyed -- the failure recorded for ep25 in an earlier session.

**Naming new speakers from old labels.** The clip is cut to start several hundred
seconds *before* the loss, so its opening turns overlap audio whose speaker is
already known. Two rules make this work:

1. **Match by text, not by timestamp.** `raw.md` can run 16s ahead of true audio,
   and turns are often shorter than that, so "who was speaking at time t" votes
   incoherently. Trigram overlap between new turns and verified ones does not
   care what the timestamps say. On ep48 this took a 3-3 tie to unanimous.
2. **When votes are thin, corroborate with the speaking pattern.** ep00's blocks
   are few and huge, leaving only five verified turns to vote with. The pattern
   settled it: the verified region runs Rafizi 88.1% in 22 long turns against
   Haziq 11.9% in 23 short ones, and the new region runs Speaker 1 at 92.6% in 18
   long turns against Speaker 2 at 4.5% in 16 short ones. ep26 matched too
   (77/23 against 97/3). A guest answering at length and a host asking briefly is
   a shape that survives re-transcription.

**ep45 got no labels, deliberately.** Its diarization collapsed the whole panel
into one cluster holding 98.8% of the text, with the host's intro and Rafizi's
reply inside a single turn (*"...bersama saya dan saudara Rafizi Ramli.
Waalaikumsalam Salam sejahtera Esok demo"*). Mapping that cluster to a name would
have asserted that Rafizi said things the host said, across a three-hour episode.
The `Speaker N` labels were stripped instead, restoring the unlabelled form the
file already had. **A confident wrong label does more harm than an absent one.** An absent
label advertises the gap. A wrong one gets trusted, quoted, and carried into
`interview*.md`. That is 1.25's wrong waiver again, one layer down.

**Reversed on 2026-08-28, and ep45 is now labelled.** The call above was right for the
evidence available at the time; a per-block voiceprint pass resolved it later. See 1.31.

**Known limitation of restored stretches.** Local ASR's turns are far coarser
than Gemini's -- ep26's new region averages 3,088 chars per turn against 227 in
its verified region -- so some host questions are absorbed into long answers.
That is the 1.11 coarse-VAD artifact, accepted here because the alternative was
65 minutes of nothing. Two spots in ep48 also need an ear: forced alignment split
one sentence across speakers at `[2:29:42]` and `[2:42:09]`, left as-is rather
than hand-adjusted.

**Also settled**: ep00's `Rashidi bin Haji Bandar Ahmad`, carried for several
sessions as a suspected invention, is real -- the man introduces himself on the
audio. ep00 is a town-hall, and its small diarization clusters are audience
questioners, labelled `Audience` per the file's existing convention.

**Corpus inconsistency worth fixing later**: ep26 writes `[Rafizi]:` and
`[00:02:51]` where the rest of the corpus writes `Rafizi:` and `[2:51]`. The
splice preserved ep26's local convention rather than mixing two inside one file.

### 1.27: Seven episodes filed Rafizi's words under a co-host's name

- **Found 2026-08-28**, while auditing name *spellings*. Seven episodes gave most
  of the transcript to the wrong person: ep24, ep25, ep27, ep42 and ep52 to
  `Haziq`, ep34 to `Farhan (Pa'an)`, ep36 to `Cincong`. Between them that is
  roughly 17 hours of speech, including ep42's `aku menteri paling gagal` and
  ep36's `masa saya menteri itu dulu`, lines only Rafizi can say.
- **Root cause:** 1.26's collapse (one diarization cluster holding 90%+ of an
  episode) happening *without* being noticed, and then a review pass naming that
  cluster after whoever it saw first. ep45 got caught because it was being looked
  at. These seven were not.
- **Why every check missed it.** Each file was internally consistent. There is no
  textual signature: a merged cluster reads exactly like a coarse-VAD episode,
  which the corpus is full of legitimately. Neither is block size a signature --
  the corpus median dominant block runs 960 chars and healthy episodes reach
  6,674, so ep27's 16,563-char block is unremarkable here. Every check in
  `qa_check.py` judged one episode in isolation, and in isolation these look fine.

**What actually separates them: comparison across episodes.** Rafizi is the
principal, so his share of the text is stable corpus-wide. The median is 87%, healthy
episodes run 68-99%, and these seven sat at 0-7%. That is now a permanent check
(`speaker-attribution` in `qa_check.py`), and it would have caught all seven on the
first run. Two guest-led episodes sit legitimately low, ep05 at 37% and ep21 at 49%,
both well clear of the 25% floor.

**Confirming it acoustically, which is the part that mattered.** A share anomaly
says *something* is wrong, not who is who, and the plan going in was to rename
`Cincong` to a sitting MP's real name. Doing that on text evidence would have put
Lee Chean Chung's name on 92% of an episode he barely speaks in -- a worse error
than the typo it was meant to fix. `scripts/verify_speaker_voiceprint.py` settles
it without an LLM: average Rafizi's voice from episodes whose labels are already
trusted, then score every cluster in every suspect episode against it by cosine
similarity on speaker embeddings.

The numbers were unambiguous. Rafizi scores 0.928 against himself across two
different episodes, which is the ceiling the method can reach; all seven dominant
clusters landed 0.945-0.967. The secondary labels landed 0.30-0.51, and per-block
scoring confirmed no guest label held any Rafizi speech at all (every block below
0.80, standard deviation 0.04-0.13, so single voices rather than merges). It also
corrected two guesses I had made from the text: ep27's and ep34's second voice is
Farhan (Pa'an), not Haziq, and ep36's is neither.

**Two traps in that method, both worth knowing before trusting a number.** A span
runs from a block's timestamp to the next block's, so a brief interjection's window
bleeds into the neighbouring speaker's audio: anything under about a minute of total
speech scores toward whoever surrounds it. A co-host reference built only from brief
interjections inherits the same bleed, which is why the `Haziq` reference reads 0.73-0.85
against confirmed-Rafizi clusters. Compare which reference wins by how much, not one
score against one threshold.

**`Cincong` is a real nickname, settled by the audio and by Rafizi himself.** At
ep36 `[05:48]` Rafizi addresses the man in the room in the second person: *"Masa tu
Cincong adalah pegawai penyelidik Dato' Seri Anwar Ibrahim. You were research officer
Dato' Seri Anwar tahun 2008 ke 2012, sebelum you bertanding first time di Semambu
2013"*, and at `[06:47]` *"Cincong di Indera Mahkota, saya dekat Kemaman"*. Lee Chean
Chung won Semambu in 2013 and Indera Mahkota is the neighbouring Pahang seat. So the
413 in-dialogue mentions stay exactly as spoken -- they are what was said, by name, on
air -- and the real identity is carried in the `guests` field instead. `[06:47]` also
settles his role: *"Cincong kurang bernasib baik hari ini... kerana dijemput"*, an
invited guest, not a co-host.

**Fixing it.** `scripts/relabel_speakers.py` applies a whole mapping in one pass over
the block headers, because renaming A to B and then B to A with two passes files
everything under A and silently destroys a swap. Three of the seven needed exactly
that swap. Body text is never touched: a name spoken inside dialogue is transcript,
not a label.

**The rewrites had to be regenerated, not renamed.** `interview*.md` inherited the
bad attribution (ep24 gave `Haziq` 77% of the rewrite, ep52 66%), and their label
sets had drifted from `raw.md` in ways no mapping can express -- ep27's rewrite
invented `Speaker 1`, `Host` and `Speaker 2`, and ep34's carried both `Rafizi` and
`Rafizi Ramli` as separate speakers. All 21 files were regenerated from the corrected
`raw.md`, the same call 1.26 made for ep00, ep26 and ep45.

**The lesson, and it is not the one 1.26 taught.** 1.26 said a confident wrong label
does more harm than an absent one, and that still holds. This adds the harder half:
a whole-episode mislabel cannot be detected from inside that episode, because
everything there agrees with it. It only shows up against the other 66. Any future
check on speaker identity should compare across the corpus, and confirm against the
audio before renaming anyone.

### 1.28: One name, eight spellings, and why a nickname was not a nickname

- **Found 2026-08-28**, immediately after 1.27, while standardising names. ASR renders
  the same person's name differently almost every time it hears it, and the variants
  do not look like each other. Lee Chean Chung appears across the corpus as
  `Cincong`, `Cincung`, `Cengcung`, `Chenchung`, `Cenchong`, `Chin Chong`,
  `Chinchong`, `Chin Chiong`, `Cian Chun`, and inside `bercincung` and `bercencong`.
- **Root cause:** nothing in the pipeline knows what a name is. Each mention is
  transcribed independently from sound, so a name the model has no prior for comes out
  differently depending on the surrounding audio.

**The trap: the most common garble looked like a real word.** `Cincong` is also
ordinary Malay for fuss or chatter, so every occurrence read as plausible speech and
the archive carried it as an on-air nickname for months. It even survived a first
correction pass, because I preserved one occurrence as "the real Malay word" on the
strength of the phrase *"Jangan tambah banyak-banyak cincong"*. That parse was wrong.
It is direct address: *"Don't add too much, Chean Chung"*. The repo owner, a native
speaker, heard it correctly on the first listen.

`bercincung` fooled me the same way and worse. Both `raw.md` and the YouTube captions
independently produced a `ber-` prefixed form (`wari bercincung` and `bi bercencong`),
which reads exactly like a Malay verb, so I argued from the shared prefix that it could
not be the name. It is *"YB Chean Chung"*. The agreement between two sources meant only
that both mis-heard the same sound the same way, which is what you would expect from
two ASR systems on one audio track. **Two independent transcripts agreeing is not
corroboration when both are guessing at the same acoustics.**

**What did work.** Content, not phonetics. Three separate episodes identify him by
facts that can be checked against the public record, and all three agree:

| Episode | What is said | Checks out as |
|---|---|---|
| ep36 `[05:48]` | Rafizi, in the second person: "you were research officer Dato' Seri Anwar 2008 ke 2012, sebelum you bertanding first time di Semambu 2013" | Won Semambu in 2013 |
| ep30 | "YB Wong Chen, Ahli Parlimen Subang... YB Chean Chung, Ahli Parlimen PJ" | Both seats correct |
| ep50 | "YB Chean Chung pun, Ahli Parlimen PJ pun telah disekat" | MP for Petaling Jaya |

**`Aziz` is Haziq, and this one nearly went wrong in the other direction.** A previous
session's audit had recorded `Aziz` as an invented name that "does not exist". It is a
real person: the co-host, whom Rafizi addresses by it. The tell is in ep47 --
*"Pa'an pun sebut. You pun sebut Aziz"* -- naming him beside the other co-host. A blind
rename would have been just as bad, because six unrelated real people share the name
here: Tok Guru Nik Aziz, Umar Abdul Aziz, Putera Abdul Aziz, Aziz Ishak (1960s
Agriculture Minister), Aziz Ahmad, Azeez Rahim (Tabung Haji chairman), and a viewer
called Azizan Aziz. A first pass caught 87 occurrences; inspecting them dropped it to
64, because `apa nama` sitting next to the name marks a third party -- it is what
someone says groping for a name they cannot recall, which never happens for the person
sitting across the table.

**Rules that came out of this.**

1. A garbled name is corrected to a **precise** form, not necessarily a full one:
   `Chean Chung` in dialogue, `Lee Chean Chung` in the `guests` field.
2. Full names belong to the speaker label and the `guests` field. Dialogue keeps what
   was actually said.
3. Never conclude a name-shaped token is an ordinary word from spelling alone, and
   never accept two ASR sources agreeing as proof. Check the content, or ask someone
   who knows the audio.
4. Print every occurrence before a name substitution runs. Both name fixes in this
   session would have corrupted real people's names without that step.

**Reading the transcript is not the same as hearing it, and I kept forgetting that.**
Three times in one session I reasoned from the text to a confident wrong answer, and
each time the repo owner settled it by ear in one line:

| I argued | Actually |
|---|---|
| *"banyak-banyak cincong"* is the ordinary Malay word, so keep it | Direct address: "don't add too much, Chean Chung" |
| `bercincung` has a `ber-` verb prefix in two independent sources, so it cannot be a name | It is "YB Chean Chung" |
| *"Makcik Roziah"* who pools capital for an anchovy-peeling machine is an illustrative village auntie | It is YB Rodziah Ismail, the MP for Ampang, doing constituency work |

The failure mode is the same each time: a garbled name reads as *plausible* Malay, and
plausibility is exactly what a text-only check cannot distinguish from correctness. The
tooling in this repo can narrow a corpus of 26,467 word forms down to a review queue of
about 250 names, which is worth a great deal. It cannot close that queue. **On names,
treat the text as generating candidates and a person who knows the audio as the only
thing that resolves them.** Ship timestamped links, not conclusions.

`Makcik Rodziah` produced one more find on the way: ep04's rewrite rendered her as
`Puan Wan Rodziah`, stacking an honorific and inserting a `Wan` that is not part of her
name. That is 1.20 again, in a spot no speaker-label check would ever look, because it
sits in the middle of dialogue rather than in a label.

**And then I over-corrected, which is its own lesson.** Having just caught that invented
`Wan`, I found the label `Wan Afiq` in ep46, ep50 and ep51 and built what looked like a
solid case against it: the name is never spoken, all 18 dialogue mentions say only
`Afiq`, he introduces himself in ep46 as *"Bersama saya, Afiq"*, and `git log -S` traced
the string's first appearance to an "Add interview rewrite" commit rather than to any
audio-grounded speaker-ID pass. I normalised 188 labels to `Afiq`.

**`Wan Afiq` was correct.** The show captions him on screen, in an on-air name graphic,
in the very episode I was checking. The whole argument rested on a bad premise: that a
name absent from dialogue is suspect. Nobody says their own surname mid-conversation.
Rafizi is called `Rafizi` on air roughly six thousand times and his name is still Rafizi
Ramli. Provenance did not help either -- `git log -S` shows when a *string* first
appeared, which for a label the rewrite stage happens to write first says nothing about
whether the underlying fact was known.

**The video is a source, and it had not occurred to me.** Thumbnails and lower-third
graphics name guests and stand-in hosts directly, produced by the people in the room. On
a name question that is stronger evidence than the transcript, the captions, and the
commit history combined, and it costs one glance. Check it before arguing from absence.

The voiceprints did hold up here, and settled the part the graphic could not:

| Cluster | Verdict |
|---|---|
| ep46 `Wan Afiq` vs ep50 `Wan Afiq` | **0.914** -- the same man, so he is in both, not only ep50 |
| ep46/ep50 `Wan Afiq` vs the Haziq references | 0.28-0.36, against 0.921 Haziq-to-Haziq |
| ep51 `Afiq` | 0.784 against Farhan (Pa'an), 0.38 against the real Wan Afiq -- a mislabel, corrected |

So he stood in for Haziq across two episodes rather than one, and a third episode's
`Afiq` was never him. **Ask the audio who is speaking, ask the video what he is called.**

Checking the thumbnails properly then produced two more corrections in ep46 alone, both
in the same glance:

- The guest labelled `Amin Sahmat` for months is **Amir Sahmat**. The thumbnail captions
  him, and the dialogue corroborates once you look for it: Rafizi introduces the pair
  with *"Ni Afiq orang Terengganu, ni Amir orang Selayang"*. (`Amir Hamzah` also appears
  in that episode and is the Finance Minister, a different man, left alone.)
- He is a **co-host**, not a guest. ep46 is the episode where Haziq was away and two
  people stood in for him, so its cast is Rafizi, Wan Afiq and Amir Sahmat with no guest
  at all.

The pattern across 1.27 and 1.28 is consistent enough to state plainly: the transcript
and the captions are two guesses at the same audio, the voiceprints establish *identity*
without ever establishing a *name*, and the only cheap source of ground-truth names is
the video the audio was extracted from. It should be the first check on any name
question, not the last.

**One more calibration, and it stops the next session from breaking something that
works.** After the seven episodes were fixed, ep51's `Haziq` label still looked wrong:
0.635 and 0.616 against the two Haziq references, which agree with each other at 0.921.
I flagged it as the last open item. The owner checked five turns spread across the
episode and every one is Haziq.

The label was right the whole time. That cluster is 10.4 minutes, which sounds
comfortably long, but it is 54 *short interjections* rather than sustained speech, so
almost every 8-second sampling window contains Rafizi answering on either side. The
minute-long threshold in the tool is not enough on its own -- **what matters is whether
the individual turns are long, not whether the minutes add up.**

Practical rule: on a cluster of short turns, roughly 0.60-0.80 means the method cannot
resolve it, not that the label is wrong. Do not relabel on a score in that band. Go to
the video, or ask. Had I "fixed" ep51 on the strength of 0.635, I would have taken a
correct label off a real person for the second time in one day.

### 1.29: Three speaker-label gotchas that keep recurring

Moved out of ARCHITECTURE.md on 2026-08-28: these are failures and their fixes, not
the stack as it stands, so they belong here. The convention itself stays in
[ARCHITECTURE.md](ARCHITECTURE.md#speaker-naming-convention).

**Local-ASR redo silently wipes previously-applied speaker names, confirmed
recurring, 2026-08-26:** any episode reprocessed via `--engine local` for an
unrelated reason (corruption fix, drift fix, filler-loop fix) gets a
completely fresh pyannote diarization pass with no memory of prior manual
naming -- it always emits new anonymous "Speaker N" labels, silently
reverting any naming work already done on that episode. First confirmed on
ep25 (a manual naming commit followed one day later by a "redo via local
ASR" commit that reset it back to generic labels), then found to affect the
majority of a 39-episode backlog re-identified this session, none of which
`qa_check.py` flags, since generic labels aren't a defect it checks for. No
permanent fix implemented: before assuming an episode's generic labels mean
it was never reviewed, check `git log -- <path>/raw.md` for a naming commit
followed by a later local-ASR-redo commit, and budget for redoing the
naming pass as a required last step after any such redo.

**A same-person self-intro quirk that can look like a second speaker,
confirmed on 5+ episodes:** Rafizi occasionally delivers the show's usual
third-person-style opening line himself ("...macam biasa bersama saudara
Rafizi Ramli...") instead of Haziq doing it, then continues straight into
first-person content in the same breath. Read as two different people from
the phrasing alone, this looks exactly like a diarization merge between an
announcer and Rafizi; it isn't. Confirmed via cross-checking who a "Speaker
N" cluster's later, unambiguous content belongs to (personal claims like
being personally sued, or reminiscing about a specific ministerial
portfolio) before concluding a cluster needs splitting. Seen on ep05, ep39,
ep40, ep44, and ep58.

**Two label-vs-real-person mismatches found and fixed before running this rename,
both confirmed by direct audio listening, not guessed from text alone**:
- ep30's raw `"Farhan"` label is a genuine third recurring panelist, not a
  mislabeled Haziq (an earlier session's working theory, based on a since-corrected
  Gemini redo that had wiped a prior manual correction): confirmed by his own
  words in the transcript ("memang like Haziq mentioned just now", explicitly
  distinguishing himself from Haziq) plus consistent panelist-level participation
  across the full 2.5-hour episode, not one-off guest content.
- ep39's raw `"Farhan Iqbal"` label (217 turns) was actually Haziq's voice:
  an isolated per-run Gemini diarization slip specific to this one episode, not
  a pattern affecting the other 10 episodes where `"Farhan Iqbal"` legitimately
  appears. Fixed to `"Haziq Azfar"` (later shortened to `Haziq` by the archive
  rename) before running the rename, so it wasn't caught in the blanket
  substitution. The real `"Iqbal"` in ep39 (85 turns) is a separate, correctly
  labeled recurring guest, confirmed distinct from Haziq by ear.

This confirms the standing risk noted elsewhere in this doc: per-run label
inconsistency in Gemini's diarization is real and episode-specific, not just a
theoretical concern; don't assume a mislabel found in one episode generalizes to
every other episode using the same label, and don't assume a same-named label
found correct in one episode generalizes either. Each case needs its own check.

### 1.30: Why the obvious generic-label rule is wrong

The rewrite stage leaves 1,441 speaker labels as `Host`, `Speaker 2`, `Interviewer`
and similar, in episodes where `raw.md` already carries a real name. The information
exists, so this looks like a pure mechanical fill-in.

The rule that suggests itself -- *map the generic label to the single non-Rafizi speaker
in `raw.md`* -- is wrong, and I caught it only by printing the mapping before running it.
It produces:

| Episode | Would map | To | Who that actually is |
|---|---|---|---|
| ep02 (2024 run) | `Moderator` | `Prof. Barjoyai` | the **guest** |
| ep05 | `Host` | `Dato' Dr. Syed Azuan Al-Idrus` | the **guest** |

The rule assumes the one non-Rafizi speaker in `raw.md` must be the host. In a
guest-interview episode it is the guest, and the host was never given a `raw.md` label at
all -- so the rule confidently assigns the host's questions to the guest.

Adding one condition makes it safe: **the target must be a known recurring host**
(Haziq, Farhan (Pa'an), Iqbal, Wan Afiq). With that, 558 labels across six episodes were
resolved and both bad cases were correctly skipped. The remaining 1,441 have two or more
candidates fitting, so they stay generic rather than being guessed -- consistent with
1.26's finding that an absent label advertises the gap while a wrong one gets trusted.

### 1.31: Labelling ep45 by scoring blocks instead of clusters

- **2026-08-28.** ep45 had been the corpus's one unlabelled episode since 1.26, on the
  grounds that its diarization collapsed into a single cluster and naming that cluster
  would credit Rafizi with the host's words.
- **The wrong diagnosis first.** Asked why it could not simply be labelled, I said it
  needed re-processing: fresh diarization, then forced alignment to cut the blocks at
  speaker boundaries. The repo owner pushed back -- ep45 had already been rebuilt more
  than once -- and was right. The transcript content is fine and QA is clean. Nothing
  needed re-processing.

**What actually worked: stop asking about clusters, ask about blocks.** Every previous
speaker check took a diarization cluster and tried to name it. When the diarizer collapses,
there is only one cluster and the question has no answer. But the *blocks* are still
separate objects, and a block can be scored on its own by sampling several points inside it
and embedding each. Two numbers come out of that, and they answer different questions:

  - the mean similarity to each reference says **who** the block mostly is;
  - the agreement between a block's own samples says **whether it is one voice at all**.

On ep45's 33 measurable blocks that gave 10 clean Rafizi blocks, 8 that score higher
against Farhan (Pa'an) than Rafizi, 4 whose internal samples disagree outright (self-
agreement 0.04-0.52), and the rest Rafizi-dominant but impure. Note the large blocks land
at 0.82-0.89 where a clean Rafizi cluster elsewhere hits 0.945-0.967 -- that gap is the
host speech folded into them, visible as a number.

**It also corrected a standing assumption.** Every earlier note on ep45 treated its
co-host as unidentified. He is **Farhan (Pa'an)**: the eight interviewer-shaped turns
("Tapi saya nak tanya YB", "Sekejap, saya ada soalan lagi") score 0.71-0.85 against his
voiceprint and 0.12-0.39 against Haziq's.

**The decision, which was the owner's to make.** Labelling all 49 blocks knowingly accepts
one error: `[00:44]` opens with the host's greeting before Rafizi replies, and is labelled
Rafizi. That is the same coarse-block artifact every other episode carries -- ep58's Rafizi
block contains "bersama saudara Rafizi Ramli" -- so the choice was between one file that is
uniquely unattributed and one that is inconsistent with the corpus in a documented,
understood way. The owner chose consistency.

**The general lesson.** 1.26's rule stands: do not put a confident wrong label on a real
person. But "we cannot name this cluster" is not the same as "we cannot attribute this
episode", and for two sessions those were treated as the same sentence. When cluster-level
diarization fails, drop to the block and ask again.

**A postscript on reading output too early.** ep45's rewrite took 31.6 minutes. Eighteen
minutes in, its `interview*.md` files carried a fresh mtime from an unrelated write, so I
read them, found the old pre-labelling content, concluded the regeneration had failed to
carry the new labels through, and committed that conclusion. It had not failed. The real
output attributes 201 of 215 turns to a named person (Rafizi 110, Farhan (Pa'an) 60,
Haziq 31) against 122 in what I had read. **A regeneration is not finished when an output
file's mtime changes -- `process_rewrite` writes all three files at the end, so check
whether the process is still alive, not the timestamp.** The post-regeneration sequence
caught the damage on the next run, which is the argument for having it written down.

### 1.32: The YB honorific, garbled twelve more ways

- **2026-08-28.** Found while checking, contextually rather than by keyword, whether the
  giant single-speaker blocks in ep45 and its peers really are Rafizi talking. A vocative
  the roster did not recognise kept appearing at segment transitions: `Obi`, `Ovi`,
  `Oibi`. The owner identified all three on sight as **YB**, the same garble that earlier
  produced `Bobby` (1.20) and `Wabi` (b2a8fe1). A position-based sweep then found nine
  more spellings, including `WB` at 102 occurrences in `raw.md` alone.
- **Fixed:** 944 substitutions across 168 files via `scripts/fix_yb_honorific.py`, plus
  four anchored edits for a separate rewrite-stage garble (below). Final family:
  `baby` (543), `WB` (234), `obi` (38), `ovi` (14), `ubi` (13), `oibi` (8), `waibi` (5),
  `bobby` (4), `abby` (2), `bibi` (1), `yobi` (1), `abie` (1).

**Guessing spellings does not close a garble family; detecting the position does.** Three
rounds of "what else could Y-B sound like" kept finding one or two more. What finished it
was searching the *slot* instead: any short token sitting between a segment opener
(`baik`, `okey`, `seterusnya`, `tahniah`) and the next clause. In that slot `yb` appears
301 times, `baby` 43, `wb` 33, and every other token is an ordinary Malay or English
function word. That is a closed list, and it produced `WB` and `bibi`, which no amount of
guessing had.

**Eight spans had to be protected, and no rule found them -- only reading did.** A blind
substitution corrupts real text: `ubi keledek` is sweet potato (ep07), `baby sharks`
(ep16), `baby formula` (ep29) and `baby boomer` (ep29) are genuine English introduced by
the *rewrite*, and ep24's `rasa macam baby umur 20 tahun` is a real baby inside a
longevity argument. A regex classifier over `raw.md` scored these at **zero**, because
`raw.md` contains none of them -- the English ones exist only in `interview-en.md`.
**Check the rewrites separately; they have vocabulary the raw transcript does not.**

- **Left alone deliberately:** ep51 `[02:46]` "ada sekali tu Abi datang memang hambat
  sikit" is narrative, not vocative, so `abi` is excluded from the tool entirely. ep40's
  "Entah-entah dengan baby kawan" parses either way and is left for an ear.
- **The rewrite stage garbles YB too, independently of the ASR.** ep50's `raw.md` reads
  "Airplane mode tu YB" and all three rewrites turned it into "abi". So `raw.md` being
  correct does not mean the rewrites are: the same honorific can be right upstream and
  wrong downstream, which no `raw.md`-only check can see.
- **Why this matters beyond spelling.** Every one of these tokens is a co-host addressing
  Rafizi, so each marks a turn boundary. In ep58's 62-minute block labelled `Rafizi`,
  "Okey baik, menarik, Oibi, 2 jam 10 minit" is a co-host at the 54% mark. That makes the
  garble a text-only detector for speaker changes inside the collapsed blocks, needing no
  audio -- see the block-granularity audit alongside this entry.

### 1.33: Word-level labelling shreds sentences, and naming the pieces is worse than not

- **2026-08-28.** Near a real speaker change, the word-level pass in
  `reattribute_blocks.py` flickers and chops one phrase into alternating fragments under
  different names: ep15 `[2:00:59]` reads `Haziq: Ini` / `Rafizi: scaling up,` /
  `Haziq: commercial` / `Rafizi: operation.` Four names on one phrase is four claims, and
  at most one arrangement is right.
- **Fixed:** 65 runs across 25 episodes now carry a single `Multiple speakers` turn with
  the fragments joined by `...`, via `scripts/group_shredded_turns.py`. Every word stays
  in order; the false precision goes. The convention is the repo owner's.

**Merging the fragments into a neighbour asserts the opposite of the truth.** The first
version folded each fragment into the surrounding label, and verification killed it:
ep12 `[07:58]`'s "beria ok seterusnya" is the run-sheet voice, which is never Rafizi, and
ep13 `[03:06]`'s "pun tak boleh?" completes a real question. In both the fragment is a
genuine short turn and the NEIGHBOUR'S TAIL is what sits under the wrong name. Direction
is not recoverable from text, so the only safe move is to make no claim at all.

**The detector had to be narrowed twice, and both drafts failed for the same reason --
treating Malay as if it were English.** Counting particles as mid-sentence markers
matched 2,181 spans, because `Tak` and `Okey` are ordinary sentence *openers*, not
continuations. Dropping that but grouping any alternating run still matched 482,
including runs holding substantive paragraphs; ep01's "Dari mana?" / "Daripada Johor
Bahru." is real rapid dialogue, correctly attributed, and blobbing it destroys good
information. Three conditions together match 65: three or more consecutive turns, every
turn eight words or fewer, and every seam mid-sentence.

**Two silent-data-loss bugs sat in the write path, both found by inspecting the diff
rather than the output.** Rebuilding the body from parsed turns drops every line the turn
regex does not match -- 37 stage directions such as `[00:00] [music/intro]` across 21
episodes. None were in the 25 target files, so this would have stayed invisible until the
first run over ep23. And `splitlines()` discards the trailing newline, which rewrote the
last turn of 7 files as a no-op diff. The write path now edits only the lines a run
covers and asserts the word sequence is unchanged.

**`Multiple speakers` is a label, so the roster tool listed it as a guest.** It was
already sitting in ep42's and ep55's `guests:` from the previous session's manual
application. Added to `rebuild_roster.py`'s `DROP` pattern alongside `overlapping
speaker`. Any new non-person label needs the same treatment.

### 1.34: The two attribution checks, and the two ways the second one misfired

- **2026-08-28.** QA reported the corpus clean at 0/67 while ep45 held a 41-minute block
  labelled with one name. Two signatures were added, and honest counts followed: 28/67,
  then 12/67 as the fixes landed.
  - `oversized-block` -- any block over `MAX_BLOCK_SECONDS` (1200), **counted regardless
    of how many labels the file carries**. The previous rule required a suspicious label
    distribution as well, which is precisely what a collapsed cluster does not have.
  - `unlabelled-host` -- a roster member whose own label holds none of the transcript.
    Compares on the first name token, since ep08 labels the principal "YB Rafizi" and an
    exact compare would report him missing.

**A share threshold cannot express this check; only zero can.** Firing at under 1% flagged
ep33 and ep49, where Farhan's turns are complete coherent questions inside well-diarized
episodes of 447 and 316 blocks -- he is the producer and is genuinely quiet. It then
flagged ep44's Farhan at 0.9% immediately after the owner had confirmed that exact label
from the video. Quiet is not the same as absent, and no percentage separates them.

**Zero seconds is not zero turns, and the difference is a false claim.** `label_seconds`
measures each turn by the gap to the next timestamp, so a label whose every turn is
shorter than the one-second stamp resolution measures as exactly 0. ep42's sole
`[2:13:12] Farhan (Pa'an): tahulah` is followed by another turn at `[2:13:12]`, so a
present, correct, owner-consistent label was reported as "no label at all". The check now
counts turns. **A derived measurement standing in for a raw one will eventually round a
real value to the sentinel that means absent** -- the same shape as the circular waiver
this whole audit started from, where an artefact was used as evidence about itself.

### 1.35: Reading the camera, when the audio methods have run out

- **2026-08-28.** The podcast cuts to whoever is talking, so a video frame is direct
  evidence of a speaker. `scripts/frames_at.py` fetches a window, samples it at 1 fps,
  burns the absolute timestamp onto each frame and tiles them into ONE image.
  `--at 03:19 51:58` gives one padded row per turn; `--range` gives a continuous stretch.
- **Validated before use, against answers already known.** On ep55 the owner had
  adjudicated three consecutive turns by ear. The frames reproduced all three: Rafizi
  alone at 16:05-16:09, a cut to Haziq at 16:10-16:11, back to Rafizi at 16:12.

**The cut lags the speech by about two seconds, and not by a fixed amount.** At ep55's
16:08, which the owner identified as Haziq, the shot is still Rafizi; it cuts at 16:10.
A single-second screenshot is therefore worthless. Every target is padded two seconds
either side -- the owner's instruction after watching the same lag himself.

**A cluster can hold two people, so identification has to be per TURN, not per cluster.**
The first pass here assumed a pyannote cluster was one person and planned to identify each
once. ep36's `Speaker 3` broke it: its 03:19 turn cuts to the guest Lee Chean Chung and
its 51:58 turn cuts to the laptop seat. Identify the turn.

**Two-shots and full-screen graphics prove nothing**, and roughly a third of frames are
one or the other. UNKNOWABLE has to be an allowed answer or the method quietly degrades
into guessing.

**Locating a second inside a collapsed block needs a separate tool.** A 62-minute block
carries exactly one timestamp, so there is nothing to aim at.
`scripts/cohost_candidates.py` finds candidate seconds from two text-only signals: a
`YB` vocative, which is always someone ADDRESSING Rafizi and so never Rafizi speaking,
and run-sheet phrases. Timestamps come from the caption track's word-level timings, used
purely as an index -- no caption text is written into any transcript, since `raw.md` is
the reviewed artefact. It found 63 candidates across the 12 oversized blocks, and
independently rediscovered the "Baik. Menarik YB. 2 jam 10 minit" moment at ep58's
2:09:18 that 1.32 had recorded by hand.

**Candidate density is itself evidence.** ep47 has 25 candidates in 48 block-minutes and
ep58 has 25 in 102; ep40 has 1 in 20. A block nobody interrupts is what a real monologue
looks like, which is the same conclusion guard 3 reached acoustically for ep27, ep36 and
ep51.

**This detector only exists because the honorific was normalised first** (1.32). Before
those 944 fixes most of these vocatives read as `baby`, `WB` or `Oibi` and matched
nothing.

### 1.36: The clustering threshold works, but only with the speaker count removed

- **2026-08-28.** Twelve episodes still held 96-99.5% of their speech in one cluster even
  when told the exact speaker count, so `reattribute_blocks.py`'s guard 1 refused all of
  them. `num_speakers` had been the only dial tried. `clustering.threshold` fixes ep58,
  the worst of them -- but only when the count hint is dropped.

**The two settings are mutually exclusive, not additive**, and this is the whole reason
the dial looked dead. pyannote ignores `clustering.threshold` whenever `num_speakers` is
set: it solves for whatever cut height yields exactly that many clusters instead. Passing
both silently gives count-only behaviour, so a threshold sweep run that way measures
nothing at all.

**Measured against video, not against plausibility.** The frames pass (1.35) had already
established the speaker at 14 seconds inside ep58's two collapsed blocks -- 13 Haziq, 1
Rafizi -- which turned the re-cut into something testable for the first time:

| config | clusters | top cluster | confirmed-Haziq seconds landing outside the dominant cluster |
|---|---|---|---|
| `num_speakers=3` (shipped) | 3 | 98.4% | **0 of 13** |
| `+ min_cluster_size=4` | 3 | 98.5% | not run, no separation to test |
| `+ min_cluster_size=1` | 3 | 99.8% | not run, worse |
| **`threshold=0.55`, no hint** | 5 | 87.8% | **10 of 13**, all in one 15.3-min cluster |
| `threshold=0.45`, no hint | 14 | 77.0% | 8 of 13, but split across THREE clusters |

The confirmed-Rafizi second lands in the dominant cluster under every config, so the
threshold configs gain recall without losing that precision check.

**Over-splitting is its own failure mode, not a milder version of success.** `0.45` scores
a lower collapse share than `0.55` and is worse: Haziq shatters across three clusters, and
a speaker spread thin across many clusters cannot be named by voiceprint or by word
overlap. `min_cluster_size` is not a useful dial here at all -- no effect at 4, actively
worse at 1, which shatters the episode into 351 clusters.

**`0.55` still over-splits three people into five clusters**, and the two spare clusters
carry mid-sentence fragments of Rafizi. Naming has to resolve those before any write.

### 1.37: What the video pass actually fixed, and what it did not

- **2026-08-28.** QA 12/67 -> 9/67. ep36, ep42, ep58 and ep60 cleared.
- **ep58, the worst episode in the corpus, is fixed.** 39 turns -> 174, longest block
  62.4 min -> 14.5 min, Haziq 0 labels -> 50. Text verified identical at 20,061 words
  either side, so only boundaries and labels moved.
- **21 more labels rewritten from frames alone** across ep36, ep42 and ep60, plus 3 the
  owner adjudicated directly from the video.

**Three independent methods agreed on ep58, having been derived separately.** The frames
put Haziq at 13 seconds inside the collapsed blocks; `threshold=0.55` put 10 of those 13
in one 15.8-minute cluster; the voiceprint scored that cluster Haziq at **0.946** against
Rafizi 0.675. Agreement between an acoustic clustering, an acoustic embedding and a video
frame is the strongest evidence this repo has ever had for a speaker label.

**The re-cut recovered a quiet speaker instead of dissolving him.** ep58's old labels held
2.4 minutes of Farhan across 19 interjections; the new `SPEAKER_00` holds 2.3 minutes and
scores Farhan **0.908**. Guard 2 exists to catch the opposite outcome and it was not needed.

**Over-splitting resolved to the truth, not to a new person.** `threshold=0.55` produced 5
clusters for 3 people. The two spares scored 0.838 and 0.813 toward Rafizi -- below the
usable floor, so the voiceprint correctly refused to name them -- and frames at three of
their longest turns showed Rafizi mouth-open with no cut. Both were Rafizi. **A dial that
over-splits is recoverable; one that collapses is not**, which is the asymmetry that makes
0.55 the right setting even though 0.45 scores a lower collapse share.

**A cluster can hold two people, so a per-cluster verdict can be wrong even when the
majority is right.** ep36's `Speaker 4` was 5 Farhan turns and 2 Rafizi fragments; its
`Speaker 3` was Rafizi twice and unknowable twice. Naming either wholesale would have
written a false label.

**What the video could NOT settle, and why the count is honest.** Roughly a third of
sampled seconds are two-shots or full-screen graphics, where no answer exists. ep58's
2:09:18 -- the one moment 1.32 had found by hand -- came back UNKNOWABLE: Rafizi on
screen, mouth closed, listening. Two candidates resolved to **Rafizi saying "YB" himself**
(ep47 46:59, ep58 2:28:01), so the text cue has real false positives and cannot drive
re-attribution alone.

**Six roster overrides remain and they are the true remainder**: Haziq in ep21, ep27, ep31
and ep47; Farhan in ep39 and ep55. ep47 is proven collapsed by video (11 of 17 sampled
seconds are Haziq inside its two 24-minute "Rafizi" blocks) and simply has not been re-cut
yet.

### 1.38: Five more episodes, and a host nobody knew was missing

- **2026-08-28.** QA 6/67 -> 1/67. ep21, ep27, ep31, ep40 and ep41 re-cut at
  `clustering.threshold=0.55`. Text verified identical in all five (19,927 / 17,746 /
  18,193 / 15,826 / 20,702 words). Haziq recovered in every one, scoring **0.935-0.971**
  against his voiceprint.

**In ep40 and ep41 Haziq was not on the roster at all**, so `unlabelled-host` could not
fire -- that check only compares against the names already listed. The episodes read as
two-person shows. The re-cut found a third host that no text-based check could have
looked for, which is the limit of any rule that starts from the roster.

**Where word-overlap and voiceprint DISAGREE, the disagreement is the diagnosis.** For
ep27's 10-minute cluster the overlap says "Rafizi 100%" and the voiceprint says Haziq
0.962. Both are correct statements: those words *were* filed under Rafizi, and that is
precisely the misattribution being repaired. This is why
`map_clusters_to_old_labels.py` must never name a host. It named ep21's guest at 99% in
the same run, which is what it is for.

**ep41's remaining 20.3-min block is waived on THREE lines, and is the standard the
earlier waivers failed to meet.** (1) Zero co-host markers in 1,829 words, the same
signature as ep51's block and the opposite of ep47's, which returned 15 and 10 hits and
proved collapsed. (2) The threshold dial split THIS episode's other three oversized blocks
(49, 39 and 28 min) and declined this one -- a real claim, unlike the withdrawn version
that relied on a speaker count pyannote ignores. (3) Frames at 38:00, 45:00 and 52:00 show
Rafizi alone, no cut, mouth open in all 15, under a persistent presentation overlay.

**ep26 needed its own decision.** Its labels came from Gemini, not pyannote, and guard 2
had already refused a re-cut once because it would have cut Haziq from 11.6 to 4 minutes.
But frames at three candidate seconds show Haziq mouth-open in a close single shot inside
blocks labelled Rafizi, so the blocks *are* collapsed. It has only two speakers, both with
voiceprint references, so a re-cut is recoverable and guard 2 remains the backstop. **The
rule "never re-cut another engine's labels" is really "never re-cut without a guard and a
way to re-name".**

**Process: `| tail -40` on a five-episode driver destroyed three episodes' output.** The
re-cuts had already been written, so the voiceprint pass simply had to be re-run -- but
only because the tool is idempotent and the scores are recomputable. Do not pipe a
long-running batch through `tail`.

### 1.39: Withdrawing the ep43 fabrication finding, and calibrating the two checks it prompted

**The headline finding of the 2026-08-28 published-files audit was wrong, and this entry
withdraws it.** That audit reported that ep43's `interview.md` had Rafizi citing five oil
production figures -- 30,629 / 38,041 / 28,325 / 25,389 / 34,195 KTOE -- that appeared
nowhere in `raw.md`, attributed to a named government agency, invented to fill a
208-second hole. A full sweep of every figure in the corpus found the opposite. All five
are in `raw.md`. He read them into a calculator one digit at a time and the ASR wrote each
digit as its own token:

| `interview.md` | `raw.md`, same sentence |
|---|---|
| `38,041 KTOE` | `38.041 KTOE. Kali 7333.` |
| `34,195` | `pengeluaran kita Kira 3, 4, 1, 9, 5 Kali 7333` |
| `28,325 KTOE` | `Ambil 2011. 2011, 28, 3, 2, 5. KTOE x 7333` |
| `25,389 KTOE` | `dia tinggal RM25,389. 333 bahagi 365` |
| `30,629` | `Itu 36. 30,600. 629. Okey. Kali...` |

The rewrite was tracking the transcript closely, not inventing. The tell is that it also
faithfully copies raw's ASR noise, keeping `RM615,000` and `RM569,000` as ringgit amounts
where the units are barrels per day. The 208-second "hole" is not one either: the block at
`[44:30]` holds 2,048 characters, 9.85 chars/sec against a corpus median of 12.1.

**Why the original audit got it wrong is the part worth keeping.** It searched `raw.md` for
the figure as written and, not finding it, concluded invention -- then explained the
absence with a mechanism (a content hole) that sounded right and was never measured. Two
plausible stories agreeing with each other is not corroboration. The same audit correctly
warned that two of its own new checks over-fired and were only caught because the owner
pushed back on a count; this is the third instance, and it survived longer because it was
the alarming finding rather than the boring one.

**The hole-predicts-fabrication hypothesis is dead.** Measured at every altered figure, the
worst unexplained gap is 51.7 seconds. `MIN_CONTENT_HOLE_SECONDS = 240` was never the
reason anything was missed; lowering it to 120 flags 34 of 67 episodes and 42 gaps, not one
of which contains an altered figure. Leave it alone.

**What the sweep did find is real, smaller, and a different shape**: single digits changed
between `raw.md` and the published text, in the same sentence, with dense transcript either
side. YBkM-ep06 prints `45 bilion` two clauses after printing `4.5 bilion USD` from the
same source; `240 juta USD` for raw's `340 juta`; `25.8 sen` for raw's `26.8 sen`.
YBhM-ep21 prints `8.2 bilion` where raw says `8.2 juta` -- a 1000x error on a global market
size. That is `scripts/check_figures.py`.

**Two matching regimes, and the split is the whole design.** A figure carrying a scale word
is compared BY VALUE, because digits alone cannot separate 4.5e9 from 45e9 and that exact
pair is a confirmed defect. A plain figure is compared by digit CONCATENATION over a short
window, because that is the only way `3, 4, 1, 9, 5` matches `34,195`. Getting there needed
four corpus measurements, each of which had been a guess: the scale-word list is counted
from the corpus (`bilion` 3029, `juta` 2647 ... `triliun` 22 -- missing that one spelling
alone put five episodes on the list); suffixed scales (`9.6B`, `227k`) are as common as
spelled ones; bare four-digit years are excluded because all 12 year-shaped flags traced to
raw's `50-an`/`60-an` decade shorthand; and a bare number may borrow a scale word stated up
to 4 tokens away, because a speaker says the unit once and then lists values against it.

Result: 12 of 67 episodes, 24 figure strings. It catches 5 of 7 hand-verified defects and 0
of 6 hand-verified legitimate reconstructions. **The 2 misses are structural, not a
threshold to chase.** In YBhM-ep14 raw reads `RM30,000 kalau 10, RM300` and the published
text prints `RM10,300`; in YBkM-ep04 raw reads `250, 450` and the text prints `RM200.5,
RM400.5`. Every digit is present -- only the grouping is wrong. The permissive concatenation
that makes ep43 pass correctly is exactly what lets these through, and tightening it
re-flags all five ep43 figures. That is the worse trade.

**`label-mismatch` went from 25 episodes to 2, and it was comparing the wrong thing.** It
compared label STRINGS across the three derived files, so it flagged every episode where a
role had been translated -- `Host` -> `Hos`, `Speaker (unidentified)` -> `Penutur (tidak
dikenali)`. That is correct translation of a non-name. What must not differ between a file
and its own translation is the set of PEOPLE NAMED, so it now compares those, with a
bilingual role-word stoplist. The 2 survivors are real: YBhM-ep11's mixed file splits one
person into `Iqbal` (55 turns) and `Ikhbal` (9) where the English file correctly has all 64
as one, and YBhM-ep14's Malay file replaces the named Haziq with a bare role.

**Three smaller corrections in the same pass.** `TURN_RE` had the colon optional, so ep20's
`**Beza Krim dengan Fleximat** --`, a bolded topic phrase opening a continuation paragraph,
parsed as a speaker; 40,032 labels in the derived files carry a colon and exactly one bold
run does not, so the colon is now required. `placeholder-label` only ever read `raw.md`,
which is allowed to be mid-work -- a new `published-placeholder` reads the derived files and
finds 9 episodes shipping diarizer cluster ids, ep54 printing all 97 turns as `Speaker 1`/
`Speaker 2` and ep56 doing it 121 times beside a `Speaker 1 (Rafizi Ramli)` that gives the
name away. And `generic-label` was double-reporting those same turns, which is why it read
26 episodes and now reads 19.

Corpus after the pass: 37 of 67 flagged, from 43.

### 1.40: Fixing what 1.39 found, and the bias that nearly put the wrong names in

**Content fixed.** Five altered figures: YBkM-ep06's `45 bilion` for raw's `4.5 bilion`
(printed two clauses after the correct value, from the same source), `240 juta` for
`340 juta`, `25.8 sen` for `26.8 sen`; YBhM-ep07's back-computed `RM10-12 bilion` where raw
says ten; YBhM-ep10's `RM1.69` where raw says `RM1.99`. Plus ep11's mixed file splitting
Iqbal into `Iqbal` and `Ikhbal`, ep14's Malay file replacing the named Haziq with two role
words, and spurious duplicate turns in ep17 and ep27 -- in both cases the FIRST copy, which
sat between a question and someone else's answer while the second got the real reply.

**Adjudicating instead of trusting the count found six matcher bugs**, every one of which
had been producing a confident false positive: an ellipsis before a number stopped it
tokenising (`...91 juta`), the ASR spells decimals as `3 point 3` and `32. 2`, `BR1M` parsed
as one million, Malay glues `-lah` onto `bilion`, and a comma-thousands number with a
decimal tail returned no value at all. **That last one made me truncate ep22's `RM1,666.67`
before checking the full raw string, which reads `RM1,666.6667`.** The published figure was
correct and I broke it; reverted in the same session. Grep a window wide enough to contain
the whole number before concluding anything about it.

Four figure flags and two duplicate flags are now adjudicated benign in
`data/qa_reviewed.json` with the evidence, not silenced. The interesting one is ep21, where
the rewrite CORRECTS the transcript: raw says `pasar global 8.2 juta ... Ia 4.2%`, but
347/8.2 is 42x, while 347e6/8.2e9 is 4.23%. The ASR mis-heard the unit and the rewrite
fixed it. Publishing raw's `juta` would have been the error.

**121 placeholder turns named, and the near-miss is the lesson.** `name_published_placeholders.py`
matches each published turn to its raw block by rare-word overlap and renames a `Speaker N`
only when the turns agree. Extending it to role labels exposed a bias that was also
affecting the numbered ones: it proposed `Interviewer` -> Rafizi, and Rafizi is the
interviewEE. The score was measuring shared TOPIC, and because he speaks most and at
greatest length his blocks win any overlap comparison by sheer volume. Dividing by
sqrt(block length) flips those to the right people.

Even corrected, role labels land at 55-76% agreement, so they stay out of scope --
ambiguous, not mis-scored. And a literal-substring trace of each turn's opening clause now
has to confirm the vote at 80% before anything is written. That gate is what keeps ep56's
`Speaker 2` a placeholder: 65% over 43 traces, because its turns splice two raw speakers
together, starting with an opening that merges Rafizi `[00:44]` and Haziq `[00:45]`.

Two guards decided more than the scoring did. **A placeholder that raw.md ALSO carries is
not a dropped name**, it is raw's own unidentified speaker -- that alone stopped ep26, ep36
and ep53 from being confidently mislabelled, because the right answer was never in the
candidate set. And elimination: once ep54's `Speaker 2` is Rafizi at 94%, a two-speaker
episode leaves exactly one reading for `Speaker 1`.

Applied to ep03, ep16, ep37, ep51, ep54, ep56, each re-audited afterwards by the literal
trace: ep16 Haziq 29/29 and Rafizi 34/35, ep54 Haziq 26/26, ep51 Haziq 32/35 and Farhan
20/21, ep03 Syed Munawar 8/8, ep56 Rafizi 51/53.

**Corpus: 43/67 flagged at the start of 1.39, 27/67 now, stable across consecutive runs.**

### What is still open, and why it is not a threshold problem

- **`generic-label`, 18 episodes.** `Host`, `Interviewer`, `Moderator`, `Hos` standing in
  for names raw.md has. Measured above at 55-76% agreement per turn, which is not good
  enough to write. These need the rewrite re-run with the names in the prompt, not a
  cleverer matcher.
- **`malay-loss`, 14 episodes.** All early; ep24 onward score ~0. Legacy damage from a
  rewrite that anglicised a code-switched original, and only regeneration fixes it.
- **`published-placeholder`, 5 episodes.** ep26/ep36/ep53 correctly refuse because raw is
  unidentified too; ep37 and ep56 have leftover labels whose turns merge speakers.
- **`unsourced-figure` 4, `placeholder-label` 4, `duplicate-turn` 2, `inline-turn-marker`
  1** -- the figure and duplicate ones are the adjudicated-benign set.

**The repo is NOT clean and should not be published yet.** The two big classes are known,
measured, and traceable to the rewrite stage rather than to the checks.

### 1.41: ep61, where the transcript looked complete and was 92% one loop

The first Gemini pass on ep61 ended at `[2:55:06]` against a 2:54:39 runtime, so I looked
at the last timestamp and called coverage complete. It was 430 blocks holding **35 distinct
texts** -- the same passages re-emitted every ~8m20s, 92% of the body duplicated, roughly
seven minutes of real content stretched over three hours.

`qa_check.py` caught all of it and I had not run it: 381 duplicate blocks, 2402s of missing
middle, and a warning that the raw came from `gemini-flash-lite-latest` after two models
fell back. **The checks were not the weak link here; skipping them was.** Timestamp
coverage says nothing about content coverage, and a continuation loop is exactly the defect
that keeps the clock looking healthy.

**Recovery, in the order that worked.** Local ASR removed the loop (120k chars against
Gemini's 7k unique) but pyannote returned five turns for the whole episode, two of them
64k and 53k characters. `reattribute_blocks.py --threshold=0.55` re-cut those into 204
turns and surfaced four speakers where the file had one. Voiceprints then separated them
cleanly: 149.6 min at 0.961 against Rafizi, 20.9 min at 0.943 Haziq against 0.667 Rafizi.
Two short clusters -- 1.2 min averaging 5s turns, and 18 seconds -- the tool itself calls
unresolvable, and they stay `Speaker ?`.

**And on ep62 that recovery step crashed outright.** `reattribute_blocks.py` read
`roster_size(ep_dir)` unconditionally, which opens `interview.md` -- a file a raw-only
episode does not have. So the command this entry prescribes could not run in exactly the
situation it is prescribed for: a fresh episode whose blocks collapsed, before any
published file exists. It worked on ep61 only because ep61 had already been through the
full pipeline. `n_spk` is used only by the `num_speakers` mode, so it is now read only when
no `--threshold` is given, with a message naming `--threshold=0.55` when the roster is
missing. Checked while fixing it: the pyannote call already did
`kwargs = {} if threshold else {"num_speakers": n_speakers}`, so nothing was silently
passing both modes -- the count was computed needlessly and then crashed.

Worth noting for the next episode: at threshold 0.55 the re-cut had ALREADY been tried
against the looped raw and its guard refused to write, because non-dominant speech would
have fallen from 30.8 to 20.7 minutes. The same threshold on the same audio then worked
once the text underneath was real. **The guard was protecting against bad input, not a bad
threshold**, which is not something the abort message can tell you.

**Rewrite variance is larger than the engine choice.** Four runs on this one episode, as a
share of raw.md: Gemini quota-failing mid-run gave 24/24/13, Claude gave 32/20/19, Gemini
on the corrected raw gave 63/60/64 and passed `check_rewrite_complete` for the first time,
and a fourth run on that same input came back 39/34/35. Keep the best output and measure
it; do not assume a rerun is an improvement.

Also fixed: four Whisper degeneration loops (887 characters of `m`, 886 of `r`), the show
name garbled to "Yang Berti Menteri", and `(Akta 672)` in all three published files -- a
real statute number the rewrite supplied from world knowledge, which the speaker never
says. A correct fact the transcript did not contain is still an insertion.

ep61 ends with two flags, both familiar: 1393s of missing middle from VAD chunking, and
40% Malay loss in the rewrite, the same class as the 14 older episodes.

**Correction, added in 1.42: the missing middle was not missing.** Every second of it is
in the file, filed under the wrong timestamp. See below.

### 1.42: ep61 was not missing content, and a cache that could hide the ones that are

`qa_check.py` reported ep61 as missing 1393s from the middle, 13% of the episode, across
two gaps. Every second of it is in the file. The two gaps are timestamps pointing at the
wrong place in the audio.

`align_blocks.py` shows it directly. The block claiming `[4715]` truly starts at 4981s and
the next, claiming `[5480]`, truly starts at 5004s -- 23 seconds apart in real audio, 765
apart on the claimed clock. The second gap is the same shape: `[9264]` truly starts at
9844s, its 4575 characters run to roughly 10222s, and the following block sits at 10275s.
Continuous audio, both times. `check_timestamp_drift.py` puts a number on it: **max drift
472s, 12 of 12 caption samples matched**, with the whole middle displaced while the first
and last twenty minutes sit within 20s of truth.

Corroborating from the other direction, `check_caption_coverage.py` finds a worst dead run
of 0s, and scoring the caption in 300s windows against raw.md gives 11-26% coverage in all
35 of them, with no dip at either suspect window -- flat, low, and uniform, because local
ASR wording diverges from YouTube's throughout, not because content is absent.

**The reasoning error is the one from 1.39, in a new place.** `lost_content_holes` reads
raw.md's own timestamps and infers loss from a gap it never checks against the audio. It
cannot distinguish "this content is gone" from "this content is filed under the wrong
second", and it reports the alarming reading of the two. Meanwhile the check that measures
the thing directly, and whose own message says content is absent "rather than merely
mistimed", was sitting in the same run saying the episode was fine. Nothing connected them.

**The fix: let the check that measures content overrule the check that infers it.** Caption
coverage starts from the audio and asks what has no counterpart *anywhere* in raw.md, which
is position independent and therefore still valid under any amount of drift. When its
longest low run is shorter than `MIN_CONTENT_HOLE_SECONDS`, no hole of that size can be
real, and the `content-loss` flag is rewritten as `hole-is-mistimed` pointing at the
timestamps instead. Both thresholds are the same 240s, so there is no new constant to
calibrate.

One detail worth keeping: the gate cannot demand *zero* low buckets. ep61 has exactly one,
a 17-second partial bucket past the caption end holding the sign-off, scoring 0.000. An
absolute-zero gate would have failed on noise at the last bucket of the episode.

**The prerequisite nobody would have asked for.** Letting a cached verdict suppress a
content-loss report makes staleness dangerous in a way it was not before. `data/
caption_coverage.json` and `data/timestamp_drift.json` had no notion of which raw.md they
described, and both had outlived 52 of the 67 rewrites that followed them -- so before the
suppression could be trusted, every verdict needed stamping with `common.body_digest()` of
the body it was computed from, and `qa_check.py` needed to drop any verdict whose stamp
does not match what is on disk. Unstamped counts as mismatched, which is why both checkers
had to be re-run corpus-wide in the same change. The digest covers the body only, so
refreshing a view count in frontmatter does not throw away a verdict about the text.

**Fixing the actual defect: `retime_blocks.py`.** The timestamps were still wrong, and no
tool moved them -- the repair tools all re-transcribe or re-cut, which would have thrown
away the hand-edits this file already carries. This one rewrites `[h:mm:ss]` prefixes and
nothing else: 204 blocks in, 204 out, one text change in the whole file and that was an
unrelated speaker label.

Anchors come from `align_blocks.py`, and the filter that matters is ordering, not score.
Speech runs forward, so the true anchors form an increasing sequence and a false phrase-lock
usually does not fit it; the longest increasing subsequence drops the liars without needing
to know which they are. **I guessed at a score floor first and the measurement killed it.**
On ep61's 132 matched blocks, scores run 4-11, the ordering filter alone rejects 6 and
leaves 80% of the body's characters anchored, while a floor of 6 leaves 57% and a floor of 7
leaves 42% -- so the floor would have traded away most of the evidence to remove liars the
ordering filter removes for free. It now defaults to `align_blocks.py`'s own
MIN_MATCHING_WORDS, which accepts every match it found.

**The 0s result is circular and does not count as verification.** After writing, the drift
check reported max drift 472s -> 0s on 12/12 samples -- inevitable, because the anchors were
set from the caption and the drift check then asks the caption whether they match. The
honest measure is holding anchors out: train on half the 126 anchors, predict the other 62
and compare. **Median error 4s, p90 11s, worst 15s**, and the same at a two-thirds split.
That is the number that describes the 78 interpolated blocks, since the anchors are exact by
construction. Against a before of median 16s, mean 124s, worst 586s, with 37 anchored blocks
off by a minute or more and 26 off by five minutes or more.

Also on ep61, and not found by any check: **the owner heard Farhan interject at 2:51:42-58,
where raw.md had `Speaker ?` and all three published files said Haziq.** The video settles
it -- `frames_at.py` over 2:51:38-2:52:02 holds the desk two-shot with Rafizi and Haziq both
in frame until 2:51:42, cuts at 2:51:43 to a close single of a third man in a different room
with his own mic, and cuts back to the two-shot at 2:52:00. Haziq is visibly sitting there
not speaking. This is the 18-second cluster `verify_speaker_voiceprint.py` called
unresolvable in 1.41, and 20 blocks shared that one `Speaker ?` label, so the other 19 --
the separate 1.2-minute cluster of ~5s turns -- are untouched and still unresolved. The
rewrite had also dropped the temple's Malay name, `Persatuan Penganut Dewa Kuan Ti`,
restored now in all three files. **Nothing in the suite can catch this class.** A confident
wrong name reads exactly like a right one, and the only reason it surfaced is that someone
who knows the show watched the episode.


### 1.43: Sensing the speaker instead of trusting the label, measured against gold data

The owner's framing, and the reason this came before any more episode fixes: *"if we can't
get this right and finetune to sense this, we will be stuck in a loop of neverending issue
forever."* So this is a proof of concept scored against the first turn-level gold data in
the project -- 18 turns of ep61 the owner wrote out by hand after watching and listening,
now in `data/speaker_ground_truth.json`. No episode file was touched.

**The starting numbers.** `raw.md` gets 11 of 18 = 61%, and the error is entirely
one-sided: Haziq 9/9, Rafizi 2/9, with every failure a short Rafizi turn absorbed into a
neighbouring Haziq block. `interview.md` matches `raw.md` in all 18 rows, which settles
that the rewrite propagates attribution rather than setting it, so nothing downstream of
`raw.md` can repair this.

**Splitting the metric was the first thing that paid.** `_gt_score.py` reported one label
per gold turn, so a diarizer that merged two turns and one that segmented perfectly but
misnamed both scored identically -- and they need opposite fixes. Scored apart, pyannote at
`clustering.threshold=0.55` puts a boundary within 0.75s of only **8 of the 16** gold
speaker changes, and its **oracle ceiling is 67%**: even naming every cluster by its own
majority cannot beat that, because one cluster swallows five short Rafizi turns and then
votes Haziq. Its `pure@80` of 89% looks healthy and means the opposite of what it appears
to -- a turn reads as 100% inside one cluster precisely because that cluster ate the whole
exchange.

**Stage A turned out to be free.** A turn change is a pause, and the YouTube caption track
timestamps every word. Cutting at every gap of >=0.4s finds **16 of 16** gold speaker
changes against pyannote's 8, at about 3x more boundaries than there are turns. That trade
is the right way round here: `merge_same_speaker.py` repairs over-segmentation, and nothing
recovers words from a merge.

**Two failed attempts, both worth recording, because each was the obvious thing.**

`v1` built voiceprints from `raw.md`'s long Haziq and Rafizi blocks and scored **44%, worse
than the baseline**. The references agreed with each other at 0.936 while each agreed with
itself at 0.923 and 0.905 -- no discriminative direction was left. Root cause: **6 of the 8
blocks ep61's `raw.md` labels Haziq at >=40s measure as Rafizi**, while all 39 long Rafizi
blocks agree with their label. The co-host label cannot seed a co-host reference on this
corpus. (That finding is a machine measurement against a 90-second passage, so it is logged
as a lead to check on video, not acted on.)

`v2` tried to discover the co-host acoustically: mean-centre segment embeddings, 2-means,
name the cluster nearer the Rafizi anchor. It scored **61%, tying the baseline and
reproducing its exact one-sided bias**. Rafizi holds 148 of the episode's 175 minutes, so
the pool mean *is* Rafizi; mean-centring removed the signal rather than the channel, and
2-means returned near-antipodal centroids at cosine -0.995 along essentially noise. The
degenerate split reported itself as "distinct", which is now a guard in the tracked script.

**Why one voiceprint and a threshold can never work here, measured rather than assumed.**
Scored by plain cosine against a Rafizi reference, 80 Rafizi blocks span 0.473-0.927 and 66
co-host blocks span 0.448-0.919. The distributions sit on top of each other: on 3-second
clips of a single recording the cosine is dominated by room and channel, not identity. Only
the **difference of two class means** cancels the common component, so the axis needs both
ends -- which is exactly why a co-host seed is unavoidable.

**What broke the deadlock.** `YB` addresses Rafizi, so no `YB` is ever Rafizi speaking. It
is the one cue on this corpus that is structural rather than stylistic, and the gold passage
backs it -- turns 1, 10 and 12 all carry `YB` and are all Haziq. Seeding the co-host end
from ep61's YB occurrences (`v3`) reached **67% and, more importantly, lifted Rafizi recall
from 2/9 to 7/9**, breaking the one-sided bias for the first time.

`v4` then fixed the three things `v3` was visibly wasting: 34 of 56 segments fell under the
embedding floor and *inherited* a neighbour's name, which is the absorption bug at smaller
scale; one seed clip sat on the wrong side of the axis it helped define; and 9 clips is a
thin class mean. Merging to a floor so every unit is scored on its own audio, dropping
wrong-side seeds, and one round of self-training from the most confidently scored segments
gives **15 of 18 = 83%, with 16/16 boundary recall and Haziq 8/9, Rafizi 7/9**.
Self-training sharpened ep61's reference cosine from 0.693 to 0.363, and converges in one
round -- rounds 2 and 3 change nothing.

**This does not reopen text inference.** `feedback_never_infer_speaker_from_text` still
holds. Text is consulted once, to aim a microphone at about ten clips, then averaged and
discarded. Every turn is decided by voice, and no turn's label is an inference from its own
words.

**The sweep says the merge floor is the only knob that matters.** At 0.7 boundary recall is
16/16 and the score 83%; at 1.0 it is 13/16 and 78%; at 1.4 it is 12/16. Merging to get
longer, better-scored segments destroys exactly the short-turn boundaries the whole exercise
exists to recover. `keep=80` is worse than `keep=20`, because widening the kept set dilutes
each class mean with segments that were never confidently scored. All 54 rows are in
`data/diarization_bakeoff.json`, together with every rejected approach.

**Where it stops is a hard floor, not a tuning problem.** The same three turns fail in every
configuration that reaches 83%: `Mana ada cuti?` (0.36s), `Ya.` (no matched words) and `Kita
memang beria.` (0.24s). They are the three shortest in the passage, and the embedder needs
0.6s. Sub-second backchannels are out of reach, and `Ya.` is also the turn the gold data
flags as carrying no textual cue at all -- neither signal reaches it. The direct attack is
an embedding model with a shorter minimum window, not more parameters.

**How thin this evidence is, stated plainly.** One passage, 18 turns, so a single turn is
5.6%, and the parameters were tuned on it -- untuned defaults scored 78%, tuned 83%. Both
beat 61%, but only a second hand-checked passage separates the method from the tuning. The
one piece of independent support is the seed supply: `YB` appears a median of 50 times per
episode and at least 4 times in all 68, and **ep61's 13 is the second-thinnest in the
corpus**, so 83% was reached close to the worst case. That is evidence about the seed, not
about the score. Nothing gets rewritten from this until a second passage agrees.

### 1.44: Chunking MAI-Transcribe-2, and the 500 that turned out to be silence

Chunking was the known task: diarization 503s above roughly 30 minutes (1.43's successor
entry in ARCHITECTURE.md has the ladder), so a 3h55m episode needs eight requests, and
`transcribe_mai.py` now cuts them, stitches the phrases with each chunk's start added back
onto every phrase and word offset, and refuses to write `raw.md` because MAI numbers speakers
per request.

**The unplanned part.** Chunk 0 came back `HTTP 500 InternalServerError` with a GUID for a
detail, and kept coming back that way. What separated signal from noise was that a
neighbouring chunk succeeded on its first try:

| request | result |
| --- | --- |
| 0-1800s, stream copy | 500, three times |
| 0-1800s, re-encoded | 500 |
| 1800-3600s | 200, 311 phrases |
| 600-2400s (the previous session's clip) | 200, 379 phrases |

The re-encode failing killed the container theory: different bytes, same audio, same error.
So the previous session's known-good 30-minute clip was located inside the source by
correlating energy envelopes, and it starts at 600s, not 0 -- the 0-1800s range had never
been tested. Laddering from zero then gave the shape:

| request | result |
| --- | --- |
| 0-60s, 0-300s, 0-600s | 200 |
| 0-1200s | 500 |
| 5-1800s | 500 |
| 15-1800s, 30-1800s | 200 |

The first 43 seconds of ep62 are digital silence, exact zeros, with the first word at 00:44.
The proof, rather than the pattern: prepend 45 seconds of silence to the clip that returns
200 and that same clip returns 500. So a long request whose audio opens with silence fails,
and both of this service's real limits are undocumented and have unrelated error codes -- 503
`diarization_unavailable` for length, an opaque 500 for leading silence. The fix is one
`silencedetect` call per chunk: start at the first sound less a second of run-up, add the trim
back onto the offsets. Also added: each chunk's response is saved and reused, so a run that
dies on chunk 6 does not re-buy chunks 0 to 5.

**Then the repo's own guard fired on healthy output.** The stitched result was 1,669 turns
with a 34% duplicate share, which the transcriber refused to write as an ep61-shaped
degeneration loop. It was not. Measured: 322 turns of "Hmm.", 93 of "Mm.", 29 of "Ha.", and
duplicate share by length floor 34.4% over all turns, **0.0% over turns of 20 characters or
more**, with not one repeated text over 80 characters. The guard was written for coarse
blocks, where a repeat means a loop; at one phrase per 4.6 seconds a repeat mostly means
someone said "Hmm." So it now counts only turns of 20 characters or more, and a second check
refuses more than 4 identical turns in a row -- measured at 2 in MAI's ep62 and 1 in every
current `raw.md`, so a filler loop like ep56's still trips it.

**Speaker reconciliation, and what MAI's own diarizer got wrong.** 20 clusters over 8 chunks,
embedded from real speech spans (MAI gives every phrase a duration, so a span does not run to the
next block and does not bleed into the neighbour) and grouped by cosine similarity with one
constraint: two clusters of the same chunk never merge, because MAI already ruled they are
different people. That constraint is what exposed the flaw. Rafizi arrived as two groups
scoring 0.962 and 0.939 against his reference, and they could not be joined by similarity
because chunk 6 contains a cluster from each -- MAI split him in two inside one request. So
groups are named first and joined by name afterwards.

Final: Rafizi 207.2 min at 0.962, Haziq 11.4 min at 0.965, Farhan 0.3 min at 0.804, and 49
turns of "Hmm."/"Yeah." (305 chars of 172,201) left as `Speaker ?` because every turn in
their cluster is under the 2 seconds the embedder needs. A cluster id in `raw.md` would be
worse than an admitted unknown; nine episodes already shipped diarizer ids that way.

**What the comparison says, and what it does not.** Against the same audio's local-ASR
`raw.md`: 1,613 blocks against 184, mean stamp gap 8.7s against 76.8s, longest gap 271s
against 1,259s, 29,810 words against 26,206, and no empty 5-minute window either way.
Rafizi's share of words is 90.7% against 93.4%, so **ep62's 93% single label is a real
property of the episode and not a collapse** -- two independent engines measure it. The
FELDA bias terms survive, including `Koperasi Permodalan FELDA`, which the local ASR never
produced. The open disagreement is `Farhan (Pa'an)`: 279 words locally, 94 in MAI, on 18
seconds of scored audio. That is a question for the video.

Nothing was adopted. ep62's `raw.md` carries this week's filler fixes and voiceprint naming,
and replacing it wholesale would discard them for a granularity win the owner has not asked
for.

### 1.45: Reading the camera on ep62's Farhan disagreement, and what it says about MAI

1.44 left one thing open: `Farhan (Pa'an)` holds 279 words in ep62's local-ASR raw and 94 in
MAI's, and no similarity score settles which is right. The camera does, because this show
cuts to whoever is talking (1.35).

**Fix the faces before reading any frame.** Three people, and two of them are men in dark
clothes at similar desks, so the identification came from turns where BOTH engines already
agree: 0:06:16 is Haziq by both, 0:02:11 is Rafizi by both, 3:44:52 and 1:27:26 are Farhan by
both. That gives Rafizi in black with a tablet and a white mug, Haziq in a light blue shirt
with a laptop, and Farhan in a black "97" hoodie against a plain wall. `frames_at.py` needed
one change to run at all: it read `video_id` out of `interview.md`, and ep62 has nothing but
`raw.md`, which is precisely the state an episode is in when the video is most needed.

**Ten disputed regions, and the split is not even.** Eight show Farhan on camera mid-speech
in a single close shot, so the local raw is right and MAI folded his words into Rafizi or
Haziq: 0:11:48 (23 words), 1:00:12 (8), 2:27:17 (40), 2:50:13 (41), 3:12:26 (30), 3:37:39
(19), 3:53:51 ("Longest episode.") and 3:54:15 (12). One goes the other way: at 3:53:48 the
shot is Rafizi, so "4 jam kau gila kau. So kalau kita start, kita kena start." is his, and
the local raw had split that sentence mid-phrase between Haziq ("...4 jam kau") and Farhan
("gila kau..."), which is a block boundary cutting a sentence rather than a speaker judgment.
The tenth, 3:27:09's one-line interjection, stays unresolved: the camera holds Rafizi through
his own surrounding turn and never cuts, so nothing in that window is evidence either way.
Row 1 of
`frames_ep62_farhan_b.png` is the clearest single frame in the set: Haziq at 0:11:50, then
the cut to Farhan at 0:11:51 who is still speaking at 0:11:54.

**The mechanism is in MAI's own clusters, not in the reconciler.** At phrase level, Farhan's
3:12:26 question carries MAI's `speaker 2` for chunk 6 -- the same cluster that holds 22.5
minutes of Rafizi. That is why chunk 6 produced two clusters both scoring as Rafizi, 0.962
and 0.939: one of them is contaminated, and a voiceprint mean over 22 minutes cannot see a
15-second passenger. `[3:11:35]` in MAI's raw is therefore a single 1,000-word turn holding
three people. So MAI's granularity win is real on average and not uniform, and the thing it
genuinely adds for Farhan is his backchannels, which the local pipeline drops.

**Two more of MAI's labels checked, both wrong (added after the retime of 1.47).** The
mid-sentence-continuation detector nominated 20 blocks where MAI's label differs from the
local raw's. The two largest were read from the video: `[0:16:10]` (185 words) and
`[0:18:02]` (374 words), both Rafizi locally and Haziq in MAI. Twenty frames across four
sampled moments -- 0:16:18-22, 0:16:48-52, 0:18:18-22, 0:19:28-32 -- show Rafizi alone in
close shot, mouth open, and never show Haziq. Both stay as they are. MAI's label record on
this episode is now wrong 10 times out of 12 wherever it was checked against the camera, so
the remaining 11 nominations are treated as suspects against MAI, not against raw.md.

**What this changes.** ep62's local `raw.md` keeps its Farhan attribution, which was correct
in 8 of the 10 places the two engines fought over. One turn of it is now known to be wrong
(3:53:48-50, Rafizi's sentence split across two labels) and one stays open. A corpus-wide MAI swap would
have moved 175 words of Farhan onto the wrong host in this episode alone. Any adoption has to
be per episode and has to keep the local labels where the local labels win.

### 1.46: An acronym pass, and the two fixes that would have broken real text

Owner-directed after reading ep62's MAI transcript: "YMDB is actually 1MDB, and baby is YB".
Both were true, and the scan around them found more. 74 corrections across 19 files, each
one checked against a source outside this repo before it entered `fix_proper_nouns.py`.

| garble | correct | count | what settled it |
| --- | --- | --- | --- |
| YMDB | 1MDB | 34 in 14 episodes | corpus already writes 1MDB 889 times; all 34 contexts read |
| IMDB | 1MDB | 1 | ep35, "perkara seperti IMDB dahulu" |
| Peter Sonda{h,r,k,l} | Peter Sondakh | 21 | Rafizi's blog, 1.00 on two 2017-03 posts |
| Raja Wali | Rajawali | 3 | same blog posts, "pemilik PT Rajawali" |
| Gavco / Gafco / GAFCO | GovCo | 3 | GovCo Holdings Bhd, the MoF lender |
| Raisin Sky | Brazen Sky | 1 | 1MDB's BVI vehicle at BSI Singapore |
| SCBRE | CBRE | 1 | the valuer in the Grand Plaza prospectus |
| sinergi Selangkawi | St. Regis Langkawi | 2 | blog post on the hotel and the LICC |
| baby | YB | 8 | `fix_yb_honorific.py`, which already knew this garble |

**The `baby` one had already been fixed, and came back.** `fix_yb_honorific.py` has carried
"baby" in its garble list since the YB pass, and its own header says a corpus-wide text fix
does not survive a later re-transcription of one episode. ep62 was transcribed after that
pass, so the garble is there and nowhere else. Run it after any raw.md regeneration.

**One candidate failed its check and was not applied.** ep26's "Eagle Plantations" looked
like a garble of Eagle High Plantations. Rafizi's own blog slug uses that short form, so it
stays, and the map records why so nobody re-raises it. That is the case for checking the
blog rather than reasoning from the corpus: the corpus cannot tell a short form from a
mishearing.

**Two guards added, because a corpus-wide run would have damaged real text.** The dry run
offered three non-ep62 substitutions. Two were real: ep21's "my wife was still in hospital
about to deliver our baby", and ep40's "a friend's baby", which is the English side of a
sentence whose Malay the KEEP list already protects as ambiguous — the guard existed on one
side of a translation pair and not the other. Both are now in KEEP. The third, ep24's
"proksi obi sendiri", is left alone and documented: `interview-ms.md` has "proksi sendiri",
`raw.md` has neither, so the word entered at the rewrite and nothing in the repo settles it.

**The backspace trap caught this session too.** Writing `\b` into a script through a shell
heredoc produced a literal backspace byte, exactly as 1.42 records, and the two new KEEP
patterns silently matched nothing — the dry run still offered the real babies. It was caught
by re-running the dry run and noticing the count had not moved, not by reading the file,
where the byte is invisible. Anything containing a regex now goes through a file written by
an editor tool, never through a heredoc.

### 1.47: Retiming ep62, and the caption anchors that were fifteen seconds early

`check_timestamp_drift.py` had never run on ep62. When it did, it flagged 398s of drift, and
the flag was real: measured against MAI's per-word offsets, 51 of 74 matchable blocks sat
within 30s of their stamp and the median was +0.8s, but the stamps ran minutes early in
stretches -- +271s and +286s around 0:51-0:52, +250s and +265s around 1:45-1:46, and +399s to
+502s from 1:59 to 2:06. No content was missing. The words were all there under stamps up to
eight minutes early, which is the failure mode 1.42 describes: a gap in the claimed timeline
is indistinguishable from absent speech unless you measure the audio.

**The obvious fix made things worse, and only a crosscheck showed it.** `retime_blocks.py`
anchors on caption matches. Applied straight, it fixed all 11 badly-drifted blocks and moved
35 correctly-stamped ones from about 1s of error to about 16s. The cause is in
`align_blocks.py`: a match returns the start of the best-matching WINDOW, and a window is
`MATCH_WINDOW_WORDS=40`, so the answer lands up to 40 words before the words being searched
for. Measured against MAI's word offsets, the caption anchors carried a median bias of
**-16.0s with sd 6.6s**. That is nothing beside a 500s displacement and it is worse than
doing nothing to a block that was already right.

Two changes, then the retime:

  - `align_blocks.py` now times a match at the FIRST MATCHED WORD inside the winning window
    rather than at the window's start. This fixes the bias for the caption path too.
  - `align_blocks.py --from-mai` anchors on MAI-Transcribe-2's word offsets and writes
    `_<tag>_align_mai.json`, so the two alignments can be compared instead of overwriting
    each other. The captions then stay what they have always been: the independent check.

The two alignments agree within 15s on 83 of the 94 blocks both matched, median +0.0s. The 11
that disagree wildly are false phrase-locks on short generic blocks, which is what the
longest-increasing-subsequence filter already existed to drop.

**A guard refused the episode on a property of its own input.** `retime_blocks.py` demanded
strictly increasing timestamps, and ep62's raw.md carries 7 places where two short turns
share a second. It now refuses on time running BACKWARDS, and separately refuses if the
output has more ties than the input, which is what would catch interpolation collapsing a
stretch of blocks onto one second.

Retimed on 105 MAI anchors holding 94% of the body's characters, against captions' 86 and
82%. Worst move 501s. Validated against the caption anchors, which were not used to build it:
median error 4.0s -> 0.0s, mean 59.2s -> 2.5s, max 504s -> 19s, 13 blocks over 60s -> 0.
`check_timestamp_drift.py` went from FLAGGED 398s to ok 20s, `verify_words_unchanged.py`
reported 26,692 words identical, and the oversized-block waiver went dormant because the
21-minute block was partly its neighbour's mis-stamp and the longest span is now 1031s.

**One more label defect surfaced while crosschecking.** Frames at 2:09:03-07 show Rafizi
talking, and MAI has one Rafizi turn there, while raw.md had split his sentence across two
speakers again -- Haziq holding "tu bukan percuma. Bila you dah commit a mistake yang sebesar
itu, kalau you nak reverse" and Rafizi continuing "pun, you nak backtrack". Haziq's actual
contribution is one "Hmm." Fixed. A detector for blocks that open mid-sentence after a label
change then nominated 51 candidates, MAI disagreeing with 20; the two largest were read off
the video and both went to raw.md, so MAI's labels are wrong 10 times out of 12 wherever the
camera has been consulted on this episode. The remaining 11 are listed and unapplied.

### 1.48: Segments, a merged transcript, and the model that beat Sonnet on the thing that matters

The owner read ep62's MAI transcript and judged it better than the local ASR and Gemini on
both text and diarization, then asked two questions: write the interview files from it, and
can a cheaper model do the writing.

**The merged transcript.** MAI wins on everything except the third host, so
`merge_mai_local_labels.py` takes MAI's words and timings and transplants `Farhan (Pa'an)`
from the local raw where the local raw's words match. Three rules, each added because the
version without it was wrong: match on WORDS rather than time spans (a span match handed
Farhan a 59-word Rafizi answer that merely started a second before a Farhan block ended);
anchor the video-verified regions on a PHRASE rather than a timestamp (1.47's retime had
moved every block by up to eight minutes, so the stamps from the video pass landed in
whatever block had slid under them, and one verified Farhan region became a 600-word Rafizi
block whose vocabulary dragged a dozen turns across); and require a turn to contain a word
that is not a vocalisation ("Hmm." scores 1.00 against any block containing a "hmm"). 14
turns move, Farhan goes from 94 to 253 words. What it cannot reach is 7 MAI turns of 200+
words where MAI's own diarization collapsed -- `[3:11:35]` is 604 words holding Rafizi,
Farhan's question and Haziq's backchannels -- and those need the turn cut, not relabelled.

**Segments come from the show's own chapter marks.** `segment_episode.py` reads the YouTube
description, so the topic boundaries are the publisher's. That is not sufficient on its own:
ep62's FELDA chapter is 26,730 of the episode's 30,000 words, because the show marks one
chapter and then talks for three hours. Long chapters are re-cut at turn boundaries,
preferring a speaker change so a segment never opens mid-answer. ep62 becomes 29 segments
averaging about 1,028 words.

**The bake-off, and why three segments rather than one.** Same prompt, same confirmed-name
list, four models. Measured on length, Malay function-word density, figures preserved, and
speaker labels -- the four things that have actually gone wrong here.

| segment | claude-sonnet-5 | gemini-3.5-flash | gemini-flash-lite | nemotron:free |
| --- | --- | --- | --- | --- |
| 26 figures | 24/24 | 20/24 | 24/24 | - |
| 10 figures | 17/24 | 13/24 | 24/24 | 2/24 |
| 27 figures | 17/20 | 18/20 | 20/20 | - |
| Malay, worst | 0.81 | 0.56 | 1.00 | 0.05 |
| seconds | 43-115 | 26-36 | 5.5-6.2 | 101 |

**A single segment would have chosen the wrong model.** On segment 26 Sonnet kept every
figure and looked like the obvious answer; on segment 10 it kept 17 of 24 while a model an
eighth of its size kept all 24 on all three. Sonnet polishes hardest, and polishing is
exactly what drops a number out of a passage where the same figure is read three times.
`gemini-flash-lite-latest` is nearly a verbatim copy -- it left "jolo sendirilah" where
Sonnet tidied to "jolok sendiri lah" -- so it passes a completeness gate by editing very
little, which is a real trade-off rather than a free win.

**The free arm failed in the way this corpus cannot tolerate.** OpenRouter's
`nemotron-3.5-lightning:free` returned 1.40x the length with a Malay ratio of **0.05**: it
translated code-switched speech into English wholesale, kept 2 figures of 24, and dropped
`Farhan (Pa'an)` as a speaker entirely. A length check alone would have called it complete.
That is why the Malay-density measure exists.

**Provider notes, all of which cost a failed call to learn.** The `claude` CLI takes its
prompt on stdin, not argv. `gemini-2.0-flash` and `gemini-2.5-flash` now 404 for this key
while `gemini-3.5-flash` and `gemini-flash-lite-latest` work. OpenRouter's free slugs move;
deepseek's free variant is gone. NVIDIA's `llama-3.3-70b` is retired. **Azure Foundry text
models need a deployment created in the portal** -- the Speech key alone returns
`DeploymentNotFound` -- so the $200 credit cannot be spent on rewrites until someone deploys
a model there, and it expires around 2026-10-07.

### 1.49: Asking a model to watch the video, and reading its "unclear" answers

1.45 read ep62's Farhan disagreement off video frames by hand: MAI's labels lost 8 of 10
against the camera. That left eleven more MAI-versus-local disagreements and no appetite for
eleven more contact sheets, so `verify_speakers_video.py` muxes the downloaded video with the
local audio and sends a 14-second clip to `gemini-3.8-flash` with the cast described by
clothing. One of the eleven, 0:11:50, was a region already read by hand; it came back Farhan,
which is the control that makes the other ten worth reading.

The headline tally was 3 for the local raw, 3 for MAI, 5 unclear. That tally is the wrong
thing to read.

**An "unclear" verdict still carries evidence, in the `seen` field.** At 2:06:07 the model
answered unclear and described Rafizi on camera with his hand on his face and his mouth not
moving while someone else speaks. That does not name the speaker but it eliminates one, and
the disagreement was Rafizi-or-Haziq. Three of the five unclears settle that way. The two
that carry nothing are 3:54:36, a two-shot for the whole clip, and 1:05:18, where the model
says the quoted phrase is never spoken -- a stamp that is still out after 1.47's retime.

**The prompt sends the head of a turn, so the answer covers the head of a turn.** ep62's
local blocks run to forty seconds and longer, and the clip covers fourteen. At 0:36:24 the
model saw Rafizi speaking, then the camera cut to Haziq replying `Saya rasa dah` -- inside a
single block labelled Rafizi. At 2:06:07 the eliminated head sits in a block whose later
sentences are plainly Rafizi recounting his own campaigning. Neither is a label to change;
both need the turn cut. Only three of the eleven were relabelled, and each is a block
sandwiched between two Rafizi blocks with the split falling mid-sentence -- 0:55:54 breaks
`Jadi sudah tentulah / perbincangan tentang`, 1:50:25 breaks `Jadi saya tanya / soalan lah`,
3:35:00 breaks `Sedangkan dalam geran RM45 / juta kan?`. Those are the local diarizer
inventing a boundary, not a speaker change, and the camera confirms Rafizi at each head.

**A disagreement can be an artefact of the comparison rather than of either transcript.** The
candidate list paired each local block with whichever MAI turn sat under its stamp. At 05:58
that pairing said local-Haziq against MAI-Rafizi. MAI actually labels that question Haziq, at
its own 06:12; the local block's stamp is fourteen seconds early and the pairing had grabbed
the turn before. An anchor added for it forced a real MAI Rafizi turn to Haziq at word
overlap 0.43, which is what a shared-function-word score looks like when two Malay sentences
have nothing to do with each other. Removed. Check that a disagreement exists before
adjudicating it.

**MAI's record against the camera on this episode is now 8 losses and 3 wins.** The three
wins are all the same shape -- a sentence the local diarizer cut in half -- so they do not
soften 1.45's finding, which was about MAI absorbing a third speaker into Rafizi.


### 1.50: The owner's ear on three labels, and the backchannels that were not in raw.md

The three blocks 1.49 relabelled were checked by ear: Rafizi throughout all three, no cut-in
from the co-host at any of them. The camera read was right and nothing was reverted.

**What the owner heard that the transcript does not contain.** At two of the three, the only
thing the co-host contributes is "hmm" -- and raw.md carries no such token at either spot.
The local ASR drops backchannels; MAI transcribes them. So a report of "Haziq says hmm here"
is a fact about the audio that only MAI's output records, and reconciling it means editing
MAI's side, not the local raw. Worth stating because the instinct is to go looking in the
file the owner was shown, and the words are not there to find.

**527 of MAI's 1,613 turns are one grunt each, and 426 of them are the same person's.** That
is not a defect in a raw transcript. It is a defect in the source a rewrite reads, where a
speaker's argument arrives as a dozen fragments separated by someone else's "Hmm." The
earlier session had already produced a filler-stripped reading copy, `raw_clean.md`, from a
throwaway script that no longer exists -- so the cleaning was not reproducible and the actual
rewrite source, `raw_merged.md`, still had every one of them. `strip_filler_turns.py` makes
it a tracked step.

Three decisions in that tool, each aimed at a way this repo has been burned:

- **The unit of deletion is a whole turn, never a word inside a sentence.** A turn goes only
  when every token in it is in the lexicon. An inline `Uh,` in a real sentence stays. 1.36's
  filler-collapse regex was correct for the instance it was written for and stripped genuine
  interjections elsewhere in the same file; a turn with no words in it cannot have that
  problem.
- **The lexicon is closed and excludes every word that means something.** `Ya` x16, `Okey`
  x11, `Yes` x4, `Betul` x3, `Yap` x3 are all one-word turns and all stay. Agreement is
  content. The tool prints the one-word turns it KEPT so the lexicon is judged rather than
  trusted.
- **It counts every non-lexicon word before and after and refuses to write unless they
  match.** 27,903 words, identical.

**A guard against short segments made the longest one.** Re-segmenting the stripped file
produced a 2,205-word piece where the cap is 1,800. Two causes, both from the same mistake of
testing a limit after the fact rather than before it: `split_turns` folded a runt tail back
into the previous piece without asking whether that piece had room, and it tested the hard
cap only after appending a turn, so MAI's 618-word collapsed turn at 3:11:35 landed on a
piece already holding 1,587. Both fixed. 27 segments, mean 1,083, max 1,601, and the 29,253
words and 1,086 turns are conserved exactly.

Removing the backchannels also removes cut points, which is why segments got longer rather
than shorter: `split_turns` prefers to cut where the speaker changes, and 527 fewer turns
means 527 fewer chances to find one.


### 1.51: What the research says this pipeline has been getting wrong

A five-thread research pass on 2026-09-08 -- diarization, Malay models, LLM cleanup, video
speaker detection, and a corpus of 20 recent YouTube talks -- against the question of what a
citable transcript needs. Full consolidation lives in the `transcript-pipeline` skill. What
follows is only the part that contradicts something this repo currently does.

**The local ASR is at about 20% word error on this exact material, and we never knew.**
Revolab publishes the only Malaysian ASR benchmark with a podcast category -- casual register,
code-switching, multiple speakers. Whisper large-v3 scores **20.52** there, fifth from bottom
of fourteen systems. ElevenLabs Scribe v2 is 4.77, ILMU v4.2 is 4.03. The gap between that and
Whisper's 7.9% on FLEURS is the whole problem with FLEURS: it is read news prose with no
code-switching, and it overstates real Malay by roughly 2.5x. **MAI-Transcribe-2 is absent from
every Malay benchmark that exists**, so the engine ep62 was transcribed with has no published
Malay number at all. The harness is MIT and adding a backend is about forty lines.

**Two habits here are backed better than they looked, and one is backed worse.** Cutting turns
at caption word gaps has no academic name, but it is how the DIHARD and VoxConverse *ground
truth* annotations were built, at a 200-250 ms threshold. The two-ended voice axis is
nearest-class-mean classification, and the reason a single voiceprint plus a threshold provably
could not work is now stateable in one line: argmax needs relative ordering, a threshold needs
absolute separation. Against that, **the 0.4s pause threshold is not defensible from the
turn-taking literature** -- in ordinary conversation 70-82% of between-speaker intervals are
under 500 ms and about 40% are overlaps with no silence at all, so that threshold fires more
often inside a turn than at a boundary. It works here because a formal interview is a different
regime, which means it has to be justified by measurement on this corpus and nothing else.

**Better boundaries alone do not buy better attribution.** In the closest published system,
turn-derived segmentation scored 10.08 against a uniform-segmentation baseline of 7.76, and
only won at 5.33 once must-link/cannot-link constraints were propagated through the affinity
graph. Our 16/16 boundary recall is the front half of a method whose back half we have not
built.

**The rewrite stage is built on the wrong primitive.** Silent translation, dropped figures and
invented labels are consequences of free-form regeneration, not of weak prompting, and the
literature has bounded them since 2019 by making the model emit *edits* over the source rather
than new text. Over an API the equivalent guarantee is a JSON edit list where every `find`
string must be a literal substring of the source. Constraining speaker labels to a closed enum
makes an invented label impossible rather than detectable. Two independent YouTube channels
observe the same thing from the outside: general LLMs rewrite transcripts when asked to clean
them.

Three measured rates make this concrete for Malay specifically. On human-annotated
Malay-English dialogues, models drop the Malay content 48-95% of the time, shift meaning
through translation 11-90%, and misattribute a speaker 3-76%. Those are our three defects, with
frequencies. The same work found similarity metrics stay high while the content is wrong, which
is why `check_figures.py` counting digits was the right instinct and an NLI faithfulness score
would not have been. It also found translate-then-process gives **no** benefit for
Malay-English, unlike Mandarin-English -- so that idea is closed.

**The video check was running near-blind.** Multimodal video input samples at 1 frame per
second by default, and the vendor docs warn that motion detail is lost at that rate. Judging
lip-sync from fourteen stills is the worst case for that default, and it explains the five
"unclear" verdicts and the wrong read at 2:06:07 that two acoustic sources overturned. The fix
is setting the sampling rate and resolution tier explicitly, and passing precomputed shot
boundaries and word timings instead of asking the model to derive them.

**Sailor2's 32% truncation was never a quality problem.** Its config sets
`max_position_embeddings: 4096`. Check the context length before diagnosing a truncation as a
capability limit.

**The Malay wordlist question has a right answer and a harmful wrong one.** MALINDO_Morph
(CC BY 4.0, one 16 MB file, no install) rejects `sesemah` and accepts `selsema`. The common
hunspell ms_MY dictionary is derived from an Indonesian affix file and lacks the correct
Malaysian `selesema` entirely, so it would flag the right word as the error. DBP's PRPM forbids
reuse and also rejects `selsema`, `korang` and `camtu`. Measured over eight of this repo's own
`raw.md` files -- 92,725 tokens -- MALINDO plus a colloquial allow-list plus clitic stripping
brings out-of-vocabulary down to 3.2% of types and 1.39% of tokens, which is a reviewable
queue. Clitic stripping alone removed 61 of 251 flags, because `subsidilah` and `malaysialah`
are productive forms. Edit-distance clustering of what survives collapsed six spellings --
`equinas`, `equinaz`, `equina`, `ikuinas`, `ikuinat`, `ikuina` -- into one garbled proper noun,
Ekuinas. That is the `Grand Consington` class of defect, found automatically.

**Two name authorities beat everything we use now.** SPR's open data publishes 9,918
candidacies carrying the ballot-paper spelling, which is the legally gazetted form of a
politician's name. Digital Hansard exposes undocumented but fully open JSON over 4,086 sittings
back to 1959, and searching it for `Grand Plaza Kensington` returns three hits -- independent
confirmation of the ep62 correction that Rafizi's blog produced, from a source whose archive
does not stop in 2022.

One methodological note about the YouTube half. Ranking the search results by view count
surfaced "Best AI Note Takers" and a workflow-automation video; the audience for a diarization
talk is small, so views measure reach, not relevance. Re-ranked on topic, twenty videos yielded
95 claims, and the strongest were the three that independently agreed with the papers: VAD
prevents hallucination and looping, multimodal transcription lacks reliable sentence-level
timestamps, and code-switching degrades every multilingual model. Everything else the corpus
produced was product comparison.


### 1.52: The caption yardstick was short by 18%, and it read as a clean result

Measuring MAI-Transcribe-2 against the local ASR on ep62 needed an independent reference, and
the only one available is YouTube's caption track. Building that comparison found a defect in
the checker that has been using the same track since 1.24.

`caption_words` matched a single pattern, `<HH:MM:SS.mmm><c>word</c>`. YouTube puts an inline
timestamp before every word in a cue **except the first**, so the opening word of each cue was
never counted. On ep62 that dropped **5,142 of 28,510 words, 18% of the track**. Two smaller
errors sat underneath it: `&gt;&gt;`, YouTube's speaker-change marker, was being read as a
word by a second parser written for this comparison, worth about 5% the other way; and cues
carrying no inline timings are usually the settled repeat of the cue before them, so their
words need deduplicating against what has already been emitted -- but only the repeated
prefix, because short interjections arrive as plain cues and nothing else records them.

**The bug hid behind its own consistency.** Because the undercount is uniform, every episode's
whole-file word ratio landed between 1.11 and 1.15, and the floor sat at exactly 1.11. That
looked like a corpus property. 1.24 read it as one, and recorded that the model "emitted 26%
more words than YouTube's caption ASR" and that "every clean episode in this corpus sits near
1.1x". Both statements were measuring the parser.

Corpus-wide, before and after: median ratio 1.15 to 0.94, minimum 1.11 to 0.89, and **47 of 53
episodes now sit below 1.00**. The local ASR does not produce more words than the caption
track. It produces about 8% fewer. ep62 goes from 1.12 to 0.92.

**Window-level coverage flagging is unaffected, and that was worth confirming rather than
assuming.** A uniform undercount cancels in a relative check, so the empty-window test reads
zero flags before and zero after across all 53 episodes. Only the ratio metric was wrong.

The two parsers now agree at 28,510 and 28,509 words on ep62, written independently against
different requirements. That agreement is the check; a single parser rewritten by the same
person on the same day would only have reproduced its own assumptions.

### 1.53: What MAI and the local ASR actually cost in lost words

With a trustworthy reference, `asr_disagreement.py` scores both engines against the same
caption track through the same Malay normalizer, so spelling convention is not counted as
error. This is a disagreement rate and not a word error rate -- the captions carry their own
mistakes -- but both engines are judged on identical terms.

| Engine | tokens | disagree | sub | ins | del |
|---|---|---|---|---|---|
| Whisper large-v3, local | 27,074 | 20.2% | 8.2% | 2.3% | **9.8%** |
| MAI-Transcribe-2 | 30,574 | **14.4%** | 7.4% | 5.8% | **1.3%** |

**Substitutions are nearly equal; deletions differ by a factor of eight.** The two engines hear
individual words about as well as each other. They differ on whether the words reach the file.
The local engine is missing 2,856 words of content against an independent transcription of the
same audio, and MAI 369. That is 1.51's published finding -- Whisper large-v3 at 20.52% WER on
Malaysian podcast audio, driven by deletion -- reproduced on this corpus with local data.

MAI's higher insertion rate is partly a virtue rather than a defect: it transcribes
backchannels that both the captions and the local engine drop, and 527 of its ep62 turns are a
single vocalisation. That accounts for some of the 5.8%, not all of it.

Neither file is pristine engine output -- both carry proper-noun corrections, and the local one
has had six degenerated filler runs collapsed, which removed spurious words and so flatters its
insertion column. The deletion gap is far too large to be explained by either.

Still missing: a number for MAI on the same yardstick as the published leaderboard. That needs
the Revolab public split, which is gated to an authorized list. Adding MAI to their harness is
a `BaseASRModel` subclass, roughly 40 lines. Tracked in `MODEL_LANDSCAPE.md`.


### 1.54: MAI-Transcribe-2 benchmarked, and it is the best engine measured

`MODEL_LANDSCAPE.md` carries the table. What belongs here is the method and the two things
that went wrong on the way to it.

MAI appears on no Malay benchmark, so its accuracy on this corpus was unknown while it was
already the engine in use. The Revolab benchmark is the only public one with a `podcast`
category. Their harness is MIT, so `scripts/revolab_run_mai.py` posts the 820 clips and
reproduces their scoring: both references normalized, both aligned per row, the lower-error
one kept, corpus WER as total errors over total reference length.

**Result: 3.96% overall and 3.39% on podcast, first of sixteen rows.** ElevenLabs Scribe v2 is
4.83/4.77, ILMU v4.2 is 7.66/4.03, and the local Whisper fallback is 15.61/20.52. The engine
already in use is six times more accurate on podcast audio than the fallback, and no engine
change is warranted.

**The prediction about transcribe style was wrong, and the run says so.** Going in, the
expectation was that `verbatim` would be penalised against references that omit fillers, so
both styles were run to measure the cost of the production setting. There is no cost:
`verbatim` scores 3.96% and `clean` 5.21%, because the benchmark's references are themselves
verbatim and `clean` deletes real words. Deletion goes 1.45% to 3.04%; singing goes 10.27% to
27.85%. Running both was still right -- it is what turned an assumption into a measurement --
but the assumption was backwards.

**Two failures worth recording.**

Their `run_eval.py` could not run at all. `datasets` 5 decodes audio through torchcodec, which
needs FFmpeg's shared libraries, and the FFmpeg on this machine is a static build with no DLLs
beside it. Reading the parquet with pyarrow and posting the stored bytes untouched sidesteps
that, and avoids a decode-and-re-encode round trip their path performs.

The first validation attempt returned **105% WER for every model**, which is the signature of
total misalignment rather than of bad models. Their committed manifests are stored in a
different order from the parquet: only 208 of 820 references matched at the same index, though
all 820 matched somewhere. Pairing by reference text instead reproduced published figures to
within 0.12 points on four of five models and reproduced the per-category podcast column
exactly for every model. **The validation is the reason the MAI number is worth anything** --
a scorer that has never been shown to reproduce a known result is just arithmetic about
itself.

The one residual is Deepgram Nova-3 at 24.61% against a published 25.63%. Clips sharing
identical reference text can pair to the wrong audio, which costs most on a high-error model.
The MAI rows are keyed by row id and unaffected.


### 1.55: The first diarization measurement, and the shipped labels lose a fifth of Haziq

Every DER in this file up to here came from someone else's corpus. There has never been a
speaker reference for this podcast, so the attribution work has been steered by argument.
`scripts/camera_speakers.py` builds one from the video: LR-ASD scores whether the visible
mouth matches the audio, YuNet plus SFace say whose face it is, and the two together give a
per-second label wherever exactly one identified person is speaking. On ep62 that covers
**12,473 of 14,101 seconds, 88%**, written as `data/camera_ref_ep62.rttm` with a matching
UEM.

**DER and JER at collar 0 with overlap counted, inside the UEM. Per-speaker recall on the
12,079 seconds every system labels, so no column rests on a different denominator:**

| system | DER | JER | Rafizi | Haziq | Farhan |
|---|---|---|---|---|---|
| raw.md as shipped | **3.0%** | 33.7% | 99% | **67%** | 76% |
| pyannote 3.x thr=0.55 | 4.6% | **21.6%** | 99% | **85%** | 75% |
| MAI + voiceprint stitching | 5.3% | 51.4% | 96% | 86% | **11%** |
| MAI, chunk ids unstitched | 87.3% | 93.2% | -- | -- | -- |

**DER is the wrong headline for this corpus and JER is the right one.** Rafizi holds 95.5%
of the speaking time, so getting him right and losing both co-hosts still scores well. That
is exactly what the shipped file does: best DER of any row at 3.0%, worst per-speaker recall
on Haziq.

**The published transcript is worse than the diarizer it was built from.** pyannote's raw
clustering recovers 85% of Haziq's speaking time; ep62 as shipped recovers 67%. Eighteen
points were lost in the naming stage after diarization, and 153 of Haziq's 457 seconds are
attributed to Rafizi. The three longest disagreements were checked frame by frame: at
1:59:31, 0:51:28 and 1:46:04 the camera holds a sustained single close shot of Haziq at his
laptop, mouth open, while raw.md credits those seconds to Rafizi.

**MAI's Farhan problem now has a number.** It matches pyannote on Haziq at 86% and recovers
11% of Farhan, sending 53 of his 103 seconds to Rafizi and 38 to Haziq. Unstitched, MAI's
per-chunk ids give 22 clusters for 3 people and 87.3% DER -- that is what the API returns
before the voiceprint join repairs it, and it is why the join exists.

**What the reference cannot be used for.** Rafizi's identity is anchored independently, by
the owner's ear at three timestamps and by LR-ASD agreeing at all three. Haziq's and
Farhan's names came from which face the camera holds during turns already labelled that way
-- a 52% and 62% plurality, not a proof -- so those two names are **not independent of
raw.md** and agreement figures involving them are partly circular. The headline finding
survives that, because "Haziq's seconds went to Rafizi" only needs the Rafizi anchor.

**Four defects hit while building it, each of which produces a plausible-looking wrong
answer rather than an error.**

`-ss` before `-i` with `-c:v copy` desyncs every chunk. Stream-copied video starts at the
nearest keyframe before the requested time and then resets its timestamps to zero, while
re-encoded audio starts exactly on time. Chunks came out 600.24s and 600.16s against
600.000s of audio: six frames of lip-sync offset, fed to a model whose only job is judging
lip-sync, plus the same error in every timestamp the reference emits. Coarse-seek 20s early,
then seek accurately on the output and re-encode -- 15,000 frames, 600.000s, frames matching
the source at +0.

Eyewear splits one person into several face clusters. Rafizi puts his glasses on partway
through and owns five of the episode's eight clusters. One-cluster-one-speaker would have
built a six-speaker reference for a three-person episode.

No global similarity threshold separates these three. Rafizi's within-person minimum is 0.35
and his maximum against Haziq is 0.40 -- they overlap, so every cut-off misclassifies
somebody. Nearest-neighbour argmax over a multi-vector gallery works because a real match
lands at 0.86-0.98 and the one stranger in the episode scored 0.22.

Greedy per-label argmax fabricated a per-speaker result. Mapping each system label to the
reference speaker it covers most let MAI's `Haziq` label claim Rafizi (445s against 389s),
which reported MAI recalling **0%** of Haziq when it had in fact labelled 389 of his 457
seconds correctly. DER uses a maximum-weight matching; so must any per-speaker breakdown
sitting beside it.

**Validation, before any of the above was believed.** The chunked run reproduces the 11
clips the method was validated on at 100% sign agreement and r=0.88. It gets 5 of 5
owner-confirmed timestamps right, including 0:05:58, where a general-purpose video model
read "mouth closed, off-camera host speaks" and three independent sources now say Rafizi.
The speaking-score threshold was swept rather than chosen: coverage is flat from -1.0 to 0.0
and falls away above it, so the default sits at the knee.

### 1.56: pyannoteAI Precision-2 trialled, and it loses to the free model

`MODEL_LANDSCAPE.md` carries the table. `scripts/pyannoteai_diarize.py` runs it. Two full
passes over ep62 took 188s and 284s and about 8 of the trial's 150 hours.

**It is worse than pyannote 3.x, which is free and already in the pipeline.** Confusion 2.2%
against 1.8%; per-speaker recall 95/81/67 against 99/85/73. Its headline DER of 10.8% against
4.6% overstates the gap, because most of that is VAD disagreement -- it claims less speech
than a reference that labels whole seconds -- but it does not win on any column.

**Voiceprint enrolment works, and is the part worth copying.** Three voiceprints cut from
camera-confirmed single-speaker runs matched all three hosts: Farhan 90 with a 64-point
margin, Rafizi 95 over Haziq's 80, Haziq 90 over Rafizi's 81. Enrol from the camera
reference, never from `raw.md`'s labels -- those labels are the thing under test, and
enrolling on a wrong one teaches the wrong voice.

**Enrolment cannot fix this pipeline's defect.** `diarize` and `identify` returned identical
3,882-segment outputs; enrolment only renames clusters. The repo does not lose Haziq by
misnaming a cluster -- pyannote already names its clusters and still reaches 85% where the
shipped file reaches 67%. The loss is in cutting clusters into transcript blocks, which no
diarizer or enrolment service touches.

**Three API details, each of which wastes a run if got wrong.** `identify` has two separate
flags: `exclusive_matching` (default True) forces segments onto enrolled speakers, while
`exclusive` asks for non-overlapping output -- they are not the same switch. The response
carries **both** a `diarization` list of anonymous `SPEAKER_NN` and an `identification` list
with the enrolled names; reading the first one throws away the entire point of enrolling.
And `retrieve` already blocks and polls internally, so wrapping it in a polling loop just
polls twice.

**DER had to be split before any of this could be read.** A single DER cannot separate a
system that puts the wrong name on speech from one that did not think there was speech
there. `scripts/score_attribution.py` splits it, and the split changes the ranking: `raw.md`
scores 0% missed **by construction**, because its blocks tile continuously and it can never
be charged for missing speech. That is why it posts the best DER in the table while being
last on confusion.

### 1.57: Splitting mixed blocks recovers Haziq, and four bugs found by looking at the diff

`scripts/split_mixed_blocks.py`, applied to ep62. Word-level attribution against the camera
reference, which is what a reader of the transcript actually experiences:

| | Rafizi | Haziq | Farhan | overall |
|---|---|---|---|---|
| before | 99% (23262/23426) | **68%** (659/967) | 78% (181/233) | 97.9% |
| after | 99% (23249/23426) | **87%** (840/967) | 78% (181/233) | **98.6%** |

186 blocks became 214, twelve of them split. 181 more of Haziq's words are now under his
own name, Rafizi loses 13 of 23,426, Farhan is untouched. `verify_words_unchanged.py`
reports 26,690 words identical, so only labels and boundaries moved.

**The cheap version was tried first and does not work.** Renaming each block by the
pyannote cluster that dominates it moves no text and is therefore safe, but it takes Haziq
from 65% to 63%, and on the MAI transcript it takes Farhan from 12% to 0%. The gain exists
only if the text is cut. There is no risk-free version of this change.

**Word times are borrowed from MAI.** raw.md has none. MAI transcribed the same audio and
returns per-word offsets, so each raw.md word is aligned to MAI's word sequence and takes
its clock. 89.6% match exactly, the largest interpolated gap is 33 words, and no word's
time runs backwards. Residual error against the existing block stamps is 1.9s median,
about five words at this speech rate, which is why the cut point is approximate and the
guards matter.

**Four bugs, and three of them scored as success before the diff was read.**

*The anti-shredding guard ate the minority speaker.* Requiring a run to reach four words
before becoming its own block is right for a run that would introduce a NEW name, and
catastrophic applied to the block's existing label: Farhan speaks 233 words across 103
seconds in short bursts, almost all under four words, and folding them took him from 78%
to 14%. A run carrying the block's own label is never folded, however short.

*One person had two names.* Cluster names were built from `Farhan` while the guard compared
against `Farhan (Pa'an)`, so every Farhan word compared unequal to itself. That reported
his recall collapsing to 14% when nothing had moved. One canonical short form is now used
for naming, guarding and scoring alike.

*Same-speaker splits fragmented phrases.* `Sesama. Tak tahu` came out as `Sesama. Tak` plus
`tahu`, both labelled Rafizi. Merging adjacent runs that share a name before emitting cut
the splits from 33 to 12 with no loss of accuracy -- 21 of them were pointless.

*A discovered speaker lost their alias.* A split that finds Farhan inside a Rafizi block
wrote a bare `Farhan:` beside 27 existing `Farhan (Pa'an):` labels. New names now map back
to whichever full form the file already uses.

**The scoring alone would have shipped all four.** Overall word accuracy read 98.5% with
the same-speaker fragmentation and the stripped alias both present. Only reading the diff
line by line found them. A metric that improves is not evidence that the change is right.

Also fixed, all caught by the owner reading the file and all verified in context first:
`Jerobo` to `Jerebu`, `threats` to `Threads` (the Meta platform, from "trending dekat"),
`bertibaran` to `bertebaran`, and `baca Faisal Felda` to `baca fasal FELDA`. None was
applied corpus-wide: of the corpus's 22 instances of "threats", ep13's reads "threats,
ancaman" -- the English word followed by its Malay gloss -- and is correct.

### 1.58: A four-way code audit before the corpus re-cut, and the first fixes

Four read-only reviews over `scripts/` on 2026-09-09, one per pipeline stage, found 40
confirmed defects. None had produced a visible error; each reported success or an improving
number. The list lives in the reviewers' output and in the fixes below; the recurring
shapes are worth naming because a 68-episode batch would repeat each one 68 times.

**Rebuild-from-parsed-blocks deletes what the parser did not match.** `split_mixed_blocks.py`
and `reattribute_blocks.py` both wrote raw.md from their block list alone, so every line
that is not a `[stamp] Label:` block vanished: 37 stage directions across 21 episodes. The
word-count guard could not see it, because both sides of its comparison were built from the
matched blocks. ep62 has no such line, which is why it never showed. `split_mixed_blocks.py`
now rebuilds line by line and replaces only the block lines; tested on ep08 (145 blocks, 3
stage lines) as an identity and with a synthetic split. `reattribute_blocks.py` still has
the bug and is not to be used with `--write` until it gets the same treatment.

**A speaker who owns no cluster is erased by a split.** Cluster names come from a word-count
vote, so a minority speaker who shares every cluster never names one. Inside their block
every word maps to someone else's run and the label disappears. ep61's Farhan turn at
2:51:41, confirmed by the owner by ear and by video, has exactly this shape. Blocks whose
label names no cluster are now left whole and reported.

**Default output paths were single-episode.** `camera_speakers.py run` skips any chunk file
that already exists in `--out`, and chunk names carry only the offset. Running a second
episode into the default directory would have reported full progress having processed
nothing, and `reference` would have labelled ep62's tracks with the new episode's uri. The
tracks directory now records its video and both stages refuse a mismatch.

**An unidentified face that is talking never vetoed.** Tracks the gallery could not name
were dropped before the "exactly one person talking" test, so on a guest episode the
guest's crosstalk becomes a confident host label and the guest's solo speech leaves the UEM
as if nobody spoke. Unknown faces now count toward overlap. On ep62, where all three people
are in the gallery, the rebuilt reference differs from the tracked one by 2 seconds.

**Exit codes said nothing.** The split tool exited 0 whether it wrote, refused, or dry-ran;
`verify_words_unchanged.py` exited 0 on a bad git ref after printing "skipped". A batch
loop reads exit codes. Refusal is now exit 2 and a bad ref is a failure.

**Still open from the audit, in the order they block work:** `gate_rewrite.py` promotes a
candidate that falls below the generic-label floor, which its own docstring says is only
possible by inventing attributions, and its cast check counts `Muzik/Intro` and `Multiple
speakers` as speakers on 32 episodes; `transcribe_mai.py` keys its chunk cache by index
only, so a different `--chunk-minutes` silently drops or duplicates the tail; the
`_drop_reemitted_prefix` stitcher in `lib_gemini.py` can glue a cut turn mid-word and append
it again in full on the live rewrite path; `dedupe_raw.parse_caption_words` drops the first
word of every caption cue and three checkers still use it (1.52 fixed one of four); QA
waivers are not bound to the raw.md they judged; `score_attribution.py` scores stamp windows
and never scores the last block.

**The unattended run.** `scripts/nightly_recut.py` does the evidence gathering for a list of
episodes newest first, writes nothing to `episodes/`, and leaves one JSON per episode plus a
summary table under `data/_nightly/`: audio, MAI word times on a network thread, pyannote at
threshold 0.55, the camera reference in a per-episode tracks directory, and the split tool
as a dry run against that reference. Whether to write is a morning decision taken after
reading the diff.

**What the first night measured (2026-09-10 morning).**

- *MAI was down for four hours, and the reason was not load on the service as a whole.*
  Every chunk of 15 or 30 minutes returned HTTP 408 "The operation was timeout" after a fixed
  122 seconds, from 23:24 to past 07:00. Probed in the morning: a one-minute clip returned in
  2 s, 5 minutes with diarization took 98 s, 15 minutes without diarization took 5 s. The
  gateway cuts at 120 s and the diarization sub-service was the part too slow to fit. Nothing
  downstream uses MAI's per-request speaker ids, so `transcribe_mai.py --no-diarization` is
  now the mode for the re-cut; all six queued episodes transcribed in about a minute each.
- *A chunk file reused by name cost 15 minutes of ep61 silently.* Chunk files are named by
  index and start, so a 30-minute plan picked up the 15-minute `chunk00_43.mp3` left by the
  night's retry loop. 900-1800 s was never sent, the last-stamp gate passed at 100%, and the
  word clock borrowed from it was 827 s off in that stretch. Reuse now requires the duration to
  match, and the verdict refuses a transcript with more than 300 s between two turns. Same
  class as the cache-by-index defect the audit listed, one line away from it.
- *Captions are as good a word clock as MAI for cutting blocks.* On ep61 the two clocks gave
  the same result: Haziq 74-75% -> 87%, Rafizi and Farhan unchanged, 18 splits against 17,
  the one difference a block at 28:51. So an episode without MAI still runs; 60 have captions.
- *ep61 written* (29be56c): 17 of 203 blocks split, words identical, 43 of 44 recorded owner
  decisions located by text and preserved, gold passage byte-identical; the 44th is a
  superseded rule with no text. `check_owner_decisions.py` now runs before every write, and
  it matches by a rule's own text rather than by stamp, because a split re-uses its parent's
  stamp and ep61's 1:22:10 names two blocks.
- *ep60 refused, correctly.* The file as shipped scores 97.5% at word level against the camera
  and the proposal scored 97.3%. Its guest was invisible to the reference until
  `guest_gallery.py` named the one unidentified face cluster (1,659 of 1,660 unidentified
  talking seconds) against the one un-galleried real label in raw.md; coverage 80% -> 93%.
  Its open defect is Farhan at 19 of 100 camera seconds, and pyannote gave him no cluster, so
  no split can reach it.
- *RTTM names with spaces.* "Sum Dek Jo" split into three whitespace fields and every reader
  scored a speaker called "Sum" at 0%. Written with underscores now, read back as spaces.
- *The ep62 gallery transfers.* 97% of ep61's face tracks and 94% of ep60's (with the guest)
  identified without anyone looking at a contact sheet.

## Rewrite, translate and metadata stage

### 2.1: Choosing a fallback provider

- **Found:** the rewrite stage originally only used Gemini. When Gemini's
  account-level billing was blocked (prepayment credits exhausted, confirmed across
  multiple independently-issued keys, tying the block to the underlying Cloud
  Billing account rather than any one key or project), a fallback provider was
  needed here too.
- **Fix / decision (model):** `claude-sonnet-5`, chosen over `claude-opus-5` for
  cost (this stage runs four calls per episode: one rewrite plus two translations
  plus metadata extraction, across dozens of hour-plus episodes) and over
  `claude-haiku-4-5` to avoid losing nuance on mixed-language political content.
  That Haiku exclusion was a judgment call at design time; later tested directly to
  check whether it was worth revisiting for cost. It wasn't: Haiku silently dropped
  roughly half of a Malay translation on a test episode while still ending the file
  cleanly (not an obvious mid-sentence cutoff), a completion-loop robustness failure
  specific to Haiku, not just a capability gap. Sonnet stays the default.
- **Fix (first implementation):** called the Anthropic Messages API directly
  through the `anthropic` Python SDK. That needs a standalone `ANTHROPIC_API_KEY`,
  which wasn't available for this project.
- **Fix (rewritten):** shell out to the `claude` CLI in headless mode (`claude -p`)
  instead, which uses whatever Claude Code authentication is already configured
  locally, with no separate API key needed.
- **Found (a real cost issue):** without an explicit `--system-prompt` override and
  a full `--disallowedTools` list, each one-off CLI call reloaded Claude Code's
  entire default system prompt and tool schemas fresh: about 21,000 cache-creation
  tokens and $0.08 per call, even on a trivial request.
- **Fix:** overriding both cut that to about 500 tokens and $0.0016 per call,
  roughly a 48x reduction with no effect on output quality for these pure
  text-generation calls.
- **Found (no subprocess timeout, confirmed to hang indefinitely):** `_run_claude`'s
  `subprocess.run` call had no `timeout=`. One specific episode's rewrite hung twice
  in a row: the CLI subprocess sat alive at near-zero CPU for 45+ minutes each time,
  never returning, with nothing in stdout/stderr to explain why (a fresh `claude -p
  "say ok"` sanity check in between the two hangs came back in 3.5s, so the CLI
  itself wasn't broadly broken; something about that specific call hung).
- **Fix:** added a bounded `CLI_TIMEOUT_SECONDS = 600` so a hang raises
  `RuntimeError` and flows into the existing `retry()` wrapper instead of blocking
  the whole pipeline forever with no way to detect it from outside.
- **Found (`retry()` only catches exceptions, never validates content: a
  schema-conformant placeholder sailed through undetected):** found while
  processing ep47: `extract_metadata`'s single unchunked call (the only
  rewrite-stage call that passes the *entire* `clean_text` in one shot, unlike
  rewrite/translate which are chunked) occasionally returns valid JSON matching
  `META_SCHEMA` but with generic stub content instead of real extraction: `topics:
  ["Topic A", "Topic B"]`, `summary: "Test summary."` (ep13) and `topics: ["Topic
  one", "Topic two"]` (ep47), the literal text of a schema-conformance example
  rather than anything about the actual transcript.
- **Root cause:** `retry()` (`scripts/common.py`) only retries on a raised
  exception and never inspects whether the result is plausible, so this passed as a
  clean first-attempt success both times, with no error, no retry, and no signal
  anywhere in the pipeline's output.
- **Context:** confirmed to have already silently corrupted a previously-committed,
  previously-"clean" episode (ep13): this was not caught by any existing
  `qa_check.py` signature before now.
- **Fix:** fixed with `_looks_like_placeholder()` in `lib_claude_rewrite.py`:
  rejects this exact signature (regex match on `"test summary"` and `"topic
  [a-z0-9]+"`) and raises, so `retry()` naturally retries it like any other failure.
  Both ep13 and ep47 were re-extracted with real metadata.

### 2.2: Claude silently condensing heavily disfluent chunks instead of fully rewriting them

- **Found:** ep45 and ep49's rewrites both improved sharply on a retry elsewhere in
  the pipeline but stayed well under `qa_check.py`'s 0.35 file-level truncation
  threshold, with the shortfall concentrated in specific chunks rather than spread
  evenly. `retry()` only catches exceptions, so a chunk that "succeeds" with
  `stop_reason=end_turn` (not `max_tokens`, so `_generate_with_continuation` never
  kicks in) after being heavily condensed sails through undetected, same failure
  class as 2.1's placeholder-metadata bug but on the clean-rewrite/translate calls
  instead.
- **Root cause:** isolated on ep45's worst chunk, the episode's opening ~20 minutes
  of heavily disfluent political banter (short interjections, "kan"/"lah"/"hmm",
  one-word reactions like "Ya." or "Panglima. Panglima."). The model has a genuine
  tendency to compress this register well below a full rewrite regardless of
  explicit instructions not to. Ruled out as a chunk-size-only or prompt-wording-only
  problem, and ruled out extended thinking eating the output budget (disabling it via
  `--effort low` barely moved an isolated test's ratio: 0.46 -> 0.49). Not fully
  deterministic either: 9 sampled attempts on this one chunk across different chunk
  boundaries, chunk sizes, and effort levels ranged from 0.13 to 0.51, clustering
  tightly *within* one CLI invocation's retry attempts (5 consecutive attempts in one
  run landed 0.127-0.136) but shifting noticeably *between* separate invocations of
  the same prompt and chunk.
- **Fix (partial):** `lib_claude_rewrite.py` now uses a smaller chunk size than
  Gemini's (`CLAUDE_CHUNK_CHARS = 20_000` vs. `lib_gemini.py`'s `CHUNK_CHARS =
  40_000`) and `--effort low` on every CLI call, both of which measurably helped in
  isolated single-sample tests, plus a per-chunk length check
  (`MIN_CHUNK_RATIO = 0.10`) in `rewrite_clean`/`translate` that raises and retries a
  chunk whose result comes back under 10% of its input length. This is a genuine
  ceiling, not the 1:1 ratio full, working rewrites land at on less disfluent content
  (confirmed: ep30/ep37 redos landed at ratio 0.96); retries could not reliably
  force this specific content above roughly 0.3, so the floor is calibrated to stop
  retrying once retries stop helping, not to guarantee a good outcome.
- **Not fixed:** an episode with a segment like ep45's opening can still legitimately
  land below `qa_check.py`'s 0.35 file-level threshold after this fix. That's the
  checklist correctly flagging a real, only partially-mitigated compression issue for
  a human to look at, not a bug to silence by loosening the file-level threshold.


### 2.3: Why the label backlog is a prompt bug, and what a deterministic pass cannot reach

27 of 68 episodes are flagged, and 32 of those flags are the same two signatures:
`generic-label` on 17 episodes, where a published file prints `Interviewer` or `Host` while
raw.md names the person, and `malay-loss` on 15, where the rewrite anglicised a
code-switched original. Both nominally want the rewrite re-run. Before doing that at scale I
tried to reach them deterministically, and the measurements are worth keeping because they
close the option off.

**Per-label naming cannot work, because the ambiguity is real.** `name_published_placeholders.py`
already handles role labels and refuses all 17. Its refusal branch was discarding the reason,
so it printed a vote and no explanation; with the reason restored, 13 of the labels refuse on
vote agreement of 41-76% and that is the correct answer. ep22's `Host` covers Haziq 88 turns,
Rafizi 54 and Farhan 28 -- one role word standing in for three people, with no single right
name. ep05's `Host` votes Rafizi 35/35 only because raw.md names exactly one speaker in that
episode, which is an artifact rather than evidence.

**Per-turn naming reaches 11% and clears nothing.** The obvious next move is to stop
aggregating: the tool computes a match per turn and then throws it away, so ep22's `Host`
could in principle become 88 Haziq turns and 54 Rafizi ones. Measured against the only
evidence strong enough to act on, a literal trace of the turn's opening clause: of 1824
placeholder turns across every published file, **193 trace to exactly one raw speaker, 1042
have no trace at all, and 589 have openings too short to mean anything.** Zero traces are
ambiguous, so the method is sound where it fires -- it just fires on 11%, and no episode is
cleared by it. Also a correction: the tool's docstring says the rewrite "usually leaves the
opening clause intact", and that is true of 11% of turns, not most.

**I blamed the prompt, and the control run says otherwise.** `CLEAN_PROMPT_TEMPLATE` did
have real gaps -- it said "with the actual speaker names from the transcript" and then never
forbade substituting a role word, never said what to do with a speaker the transcript leaves
unnamed, and never forbade merging two labels; its language rule was an instruction with
nothing measurable attached, unlike point 5's concrete "at least 70% of character length"
that is why ep61's one passing run passed. Those gaps are now closed, with an explicit
prohibition and a countable Malay floor, and one edit covers both engines because
`lib_claude_rewrite.py` imports the template.

**But the fix is not what repaired ep03.** Run on the densest 59-turn chunk of YBhM-ep03,
the new prompt returned 94% of the input length, 59 of 59 turns, 95% of the Malay and no
role labels. Then the control: **the OLD prompt on the identical chunk returned 95%, 59 of
59 turns and 98% of the Malay.** Both are fine. The 47% incumbent was not the current
pipeline condensing; it was a stale artifact of an earlier one, and a plain regeneration
took the episode to 97% completeness, 27.1% Malay against raw's 27.4%, and 0 generic turns
from 81. **The claim I was about to act on -- that every model drops turns because a 20k
chunk invites omission -- did not survive its own control.** It is content-specific: log
2.2's 0.13-0.51 spread was measured on ep45's opening, and ep03's hardest chunk is simply
not that content.

**The bake-off, on the other cluster, with a control.** ep03's chunk was a weak test of the
label rule: it had three real names and no generic labels to begin with. So the same
harness was pointed at ep10, whose published file prints `Host` **396** times against a raw
that names Iqbal, Chak Onn Lau and Rafizi. Densest 20,000-char window: 154 turns, 19.2%
Malay. Four runs, `claude-sonnet-5` at `--effort low`, 1.5 minutes each:

| prompt | chars | turns | malay | labels |
|---|---|---|---|---|
| OLD r1 | 98% | **154/154** | 96% | expands `Rafizi` -> `Rafizi Ramli` |
| OLD r2 | 98% | **154/154** | 97% | expands `Rafizi` -> `Rafizi Ramli` |
| NEW r1 | 96% | **154/154** | 99% | exact |
| NEW r2 | 96% | **154/154** | 100% | exact |

**Neither prompt produces a single `Host`.** So ep10's 396 of them are stale too, and the
same conclusion now holds on both clusters: the 26 remaining flags are old output, not
current behaviour, and the backlog is a batch job rather than a research problem. The new
prompt is worth keeping on a smaller claim than the one I made for it -- 3-4 points more
Malay retained, and it stops the `Rafizi Ramli` expansion that
`normalize_speaker_labels.py` exists to undo -- but it fixes nothing that is currently
broken.

Method note, since `scripts/_rewrite_bakeoff.py` is a probe and stays untracked under the
`scripts/_*.py` convention: score TURN COUNT, not length. Length is the number that reads
like completeness and is the easiest to satisfy while dropping content -- a model can reach
100% of the character count by padding one turn and dropping ten. Turn count is the only
score that sees omission directly, and it is what separated "the pipeline condenses" from
"this file is old".

A second hypothesis died the same way. Since ep03's bad `interview.md` carried no `model:`
line, legacy-era output looked like it might be identifiable by that absence -- but only 1
of 68 episodes has the field at all, so it separates nothing.

**Two clusters, not one backlog.** Scoring all 68 episodes on completeness, Malay loss and
generic-turn count splits the 27 flags cleanly, and the two halves want opposite handling:

  - **Content lost, labels fine.** ep14 at 55% completeness and 57% Malay loss, ep02b 59/47,
    ep04a 62/56, ep61 64/40, ep06b 66/73, ep02a 76/42, ep01b 79/56, ep05a 82/62, ep01a 82/34.
    Early-era output. Regeneration is a clear win here -- ep03b went 47% -> 97%.
  - **Labels bad, content fine.** ep10 at 80% completeness with **396** generic turns, ep56
    100% with **267**, ep22 91/192, ep04b 87/180, ep33 98/96, ep37 93/75, ep19 92/69,
    ep53 99/57. Regenerating these risks content that is already good in order to fix a
    label, which is exactly the trade the gate's completeness veto refuses.

**`gate_rewrite.py`, because a re-run is a coin flip.** ep61's four runs on identical input
returned 24%, 32%, 63% and 39% of raw's length, and `regenerate_rewrites.sh` overwrites the
incumbent before anyone has seen what came back. The gate regenerates into a sandbox, scores
the candidate against the incumbent on the three axes the suite actually flags, and restores
the incumbent unless the candidate wins. Completeness is a veto rather than one term in a
sum: losing content to gain a label is not a trade worth making.

**Two bugs found on the way, both of the silently-wrong kind.**

Six tags are ambiguous -- both shows have an ep01 through ep06, and they are different
episodes. Every tool resolved a tag with `[...][0]`, taking whichever the manifest listed
first. All six are in the rewrite backlog, so the first batch run would have regenerated the
wrong episodes and reported success. `common.resolve_tag` now raises with the candidates
listed (`ep03:bakar`, `ep03:berhenti`). `splice_gap.py` still carries the old pattern.

The gate's own first scorer counted the honest-unknown markers as defects -- `Speaker ?`,
`Speaker (unidentified)`, `Penutur (tidak dikenali)`, `Penceramah ?` -- and scored 3-6
against four episodes `qa_check.py` calls clean. That is the third time a new check in this
project has over-fired on exactly this marker. The fix was to stop inventing a measure and
reuse `label_drift_audit.GENERIC`, the regex that raises the flag being tracked: 1824 turns
corpus-wide, zero on any clean episode. **A gate that does not measure the same thing as the
flag it is gating will promote a candidate the suite then rejects.**

### 2.4: The batch, and the flag that was blaming the wrong stage

15 episodes through `gate_batch.sh`, six at a time, 71 minutes wall clock. **15 promoted, 0
restored.** QA 26 -> 12 of 68.

| episode | completeness | Malay (raw in brackets) | generic turns |
|---|---|---|---|
| ep14 | +43% | 9.7% -> 23.1% (22.8) | - |
| ep05b | +40% | 27.9% -> 31.4% (31.7) | -36 |
| ep02b | +37% | 14.4% -> 26.5% (27.0) | -48 |
| ep61 | +36% | 16.0% -> 26.3% (26.5) | - |
| ep04a | +34% | 10.6% -> 24.1% (24.3) | - |
| ep06b | +32% | 5.4% -> 20.0% (19.7) | -60 |
| ep02a | +21% | 13.2% -> 22.4% (22.9) | +150 |
| ep01b | +19% | 11.0% -> 24.9% (25.0) | - |
| ep10 | +16% | - | **-396** |
| ep11 | +15% | - | -36 |
| ep01a | +14% | 15.9% -> 24.0% (24.2) | -15 |
| ep05a | +13% | 7.5% -> 19.2% (19.6) | -42 |
| ep07b | +13% | 24.0% -> 29.1% (30.2) | - |
| ep04b | +10% | 20.9% -> 25.0% (25.5) | -180 |
| ep06a | +8% | 17.9% -> 23.8% (24.0) | - |

The column to read is Malay, not completeness: **every episode lands within 0.5 points of
its own raw density.** ep06b went 5.4% -> 20.0% against a raw of 19.7%. That is not an
improvement in a score, it is the code-switching in the mixed-language file existing again.

**The one that went the wrong way, and why it was right.** YBkM-ep02's generic turns went
84 -> 234 and the gate promoted it anyway, because `verdict()` vetoed a completeness or
Malay regression but I never wrote the symmetric check for labels. That veto now exists --
**every axis that raises a flag needs one, or the gate trades one flag for another.**

But reverting the episode would have been wrong, because the regression was not a
regression. **`raw.md` labels 78 of its own turns `Moderator:`.** The new rewrite copied
that verbatim, which is exactly what the new prompt tells it to do; the OLD file scored
better only because it had invented named attributions for 50 of those 78 turns. The
honest output looks worse to the checker than the dishonest one did.

**So `generic-label` was blaming the wrong stage.** Its message claims the rewrite
"discarded names the transcript already had", and across the 12 remaining episodes **351 of
1080 flagged turns, 32%, carried a label `raw.md` itself uses** -- entirely so on YBkM-ep02,
ep53, ep26 and ep36. There was no name to discard. `raw-unnamed-speaker` now reports these
at the raw stage with the fix that actually applies (identify the speaker from video,
description or voiceprints), and `generic-label` excludes them. `placeholder-label` could
not have caught them: it only matches numbered clusters, and these are role words.

That is the fourth check in this project to over-fire on its first contact with the corpus,
and the first to do it in a way that pointed the work at the wrong stage rather than merely
inflating a count. **A false positive costs a look; a mislabelled cause costs a batch run.**

### 2.5: The name that the majority spelling got wrong, and the one it got right

The corpus garbles Malaysian names, and the planned fix was a corrections pass. Doing it
turned up the reason it could never have been automated.

**First, a counting error worth naming.** `grep -oh "Fuzia"` reports 60 hits in raw.md and
209 in the published files, so the garble looked like it outnumbered the correct spelling
almost as badly as the Farhash case. It does not: **`Fuzia` is a prefix of `Fuziah`**, so
that grep was counting every correct spelling as a defect. With a negative lookahead the
real garble count is 24 against 244 correct. I had already quoted the inflated figure
before checking it. Any count of a name that is a prefix of another name needs an explicit
boundary, and `\b` is not safe to write here either -- through a nested heredoc it becomes
a literal backspace and then silently matches nothing, which is the same class of failure.

**Then the actual trap.** Fuziah Salleh's surname is garbled to `Saleh` 13 times, and the
obvious sweep is `Saleh` -> `Salleh` across the corpus: 266 against 89 looks like a garble
that has taken over. Splitting by the preceding word kills that idea immediately:

| preceded by | `Salleh` | `Saleh` | correct |
|---|---|---|---|
| Akmal | 0 | **35** | **`Saleh`** -- one L |
| Fuziah | 3 | 13 | `Salleh` |
| Mat | 7 | 11 | either |
| Tun | 1 | 0 | `Salleh` |

Verified against sources rather than guessed: **Muhamad Akmal bin Saleh**, UMNO Youth chief,
really does spell it with one L, so the sweep would have corrupted 185 correct occurrences
across raw and published. **Mat Salleh / Mat Saleh are both attested** for the
colloquialism -- the OED's etymology entry lists "Malay mat saleh" -- so neither is a
garble and both stay as spoken. The corrections are therefore two-word patterns
(`Fuziah Saleh` -> `Fuziah Salleh`) where the first name disambiguates the surname.

**The rule: a name is not a spelling to normalise by majority vote.** The majority form was
wrong for Fuziah and right for Akmal, in the same corpus, four words apart. This is also
why `check_proper_nouns.py` cannot be turned into a fixer -- its `RARE_MAX = 4` promotes a
frequently-repeated garble to an "established spelling", which is the same majority
argument, and it would have been confidently wrong here.

`fix_proper_nouns.py` holds the reviewed map, one entry per owner decision, plus an
explicit not-corrected list carrying the sources, so the analysis is not redone. 51
corrections applied across raw.md and the published files.

**One ordering gotcha, for any future pass.** Correcting files while `gate_rewrite.py` is
mid-run is wasted work: the gate copies its final decision back over the episode directory
at the end, reinstating whatever the rewrite produced. ep37 needed the pass run twice for
exactly that reason. The tool is idempotent, so the fix is to re-run it after any batch
rather than to sequence around it.

## Local-ASR diarization: two follow-up fixes from a code review

Found during a code review of the forced-alignment work above, both fixed
2026-08-25:

- **Orphan "Speaker ?" words, confirmed shipped on ep13**: a word whose
  forced-aligned timestamp lands in a gap between diarization turns (common
  for short/isolated words: numbers, filler, single-word interjections)
  used to get labeled `"Speaker ?"` and split into its own one-word line,
  tearing it out of the real speaker's surrounding turn. `qa_check.py` has no
  detector for this pattern, so it shipped silently: confirmed real
  examples in ep13's `raw.md` (`[02:35] Speaker ?: 13`, `[08:50] Speaker ?:
  memang`, etc.), all sitting between two turns from the SAME real speaker.
  Fixed in `lib_local_asr.py`'s `_speaker_lines`: a word with no diarization
  overlap now attributes to whichever speaker is already talking, only
  falling back to `"Speaker ?"` if there's no established speaker yet (the
  very first word of a chunk with zero overlap). ep13's already-shipped
  `raw.md` was hand-patched to match (5 orphan lines merged into their
  neighbors), since a full re-run wasn't needed to fix already-correct text.
- **Overly broad exception handler in `lib_forced_align.py`**: the CTC
  target-length fallback (see above) caught bare `RuntimeError`, which would
  also silently swallow something like a CUDA out-of-memory error and
  downgrade that chunk to whole-chunk labeling with zero log output. Now
  checks the exception message for the specific `"targets length is too long
  for CTC"` string before applying the fallback, and re-raises anything else.

### 2.6: Three of the last five flags were stale output, and a defect no check can see

The handoff said the five remaining flags were "one defect class, all needing the owner's
ear." Three were not, and measuring the gap between `raw.md` and the published files was
enough to tell which:

| ep | raw generic | published generic | floor | what it actually was |
|---|---|---|---|---|
| ep56 | 0 | 267 | 0 | stale published output |
| ep41 | 0 | 3 | 0 | a co-host buried inside a Rafizi block |
| ep26 | 11 | 39 | 33 | raw fixed earlier, published never regenerated |
| ep53 | 22 | 57 | **66** | published sat BELOW the floor |
| ep19 | 2 | 6 | 6 | genuinely unresolved |

ep56's `raw.md` names every turn while its published files printed `Speaker 2` **89 times
in each of three files**. That is the 2.4 lesson again -- assume nothing about a flag until
raw and published are compared -- and it was sitting behind a diagnosis that said the audio
was the problem.

**The gate could not have promoted ep53, because its label axis had no floor.** `generic_turns`
counted every generic published turn raw-blind. Correct for ep56, where raw names everything
and the gap is the rewrite's alone. Wrong in the other direction: where raw leaves a turn on
`Speaker 3`, no faithful rewrite can name it, so an honest candidate RISES toward raw's own
count and the veto reads that as a regression. ep53's incumbent scored 57 against a floor of
66 -- **nine turns below what raw supports, which is only reachable by inventing
attributions** -- so every honest candidate would have been rejected for stopping guessing.
This is exactly the inversion `check_published` already corrected when it stopped blaming
the rewrite for 351 turns raw itself leaves unnamed; the gate had kept the old definition.
`generic_floor()` fixes it, and nine cases pin the behaviour, including the historic
YBkM-ep02 regression (33 -> 234), which still rejects even with a Malay gain.

Verdicts: ep26, ep53 and ep56 promoted, **ep41 rejected at 3 -> 24 generic turns**, which is
the gate doing its job against rewrite variance. QA 5 -> 4.

**ep53 was burying turn markers, and the check under-reported it by six.** Its
`inline-turn-marker` flag said one lost paragraph break. There were seven markers across six
blocks, because the check `break`s after the first. Four of those blocks opened with a label
holding **no words at all** -- `[2:05:27] Speaker 3: [2:05:29] Speaker 1: Baik Dah meletup
pun` -- a diarizer segment the ASR returned nothing for, where the empty label reads as the
owner of the text that follows. Worst single case: `[34:39] Speaker 2` held an entire
run-sheet segment ("Sekarang kita kena Tengok pula AMK buat hal apa minggu ini") that
published under Rafizi, and this repo already records that the run-sheet voice is never
Rafizi. `split_inline_turns.py` splits them and drops the wordless ones; the check now counts
every block. Contained to ep53 corpus-wide.

**ep41 is a defect class nothing detects.** Its `[2:33:49] Rafizi` block runs 13,774
characters and holds a co-host's devil's-advocate question verbatim at character 13,179,
answer following. No inline marker, so the splitter cannot see it. A real name, so no
placeholder check fires. All the text present, so no completeness check fires. **The rewrite
was the only stage that noticed** -- it split the question out and, having no name, wrote
`Speaker`, which is the flag. `name_published_placeholders.py` refused to name it, scoring
Rafizi 3/3 on word overlap, and the refusal saved a wrong rename: the turn opens "YB, sedikit
soalan devil's advocate" and Rafizi IS the YB. Its own comment predicted this -- role labels
scored by overlap measure shared topic, and Rafizi wins any overlap by volume.

Corpus-wide the shape is visible: median block 81 characters, p95 2,450, **53 blocks over
8,000 and every one of the largest fourteen labelled Rafizi**. A vocative `YB` inside a
Rafizi block fires on 95 blocks -- he does not address himself as YB.

**And I wrote a tool that already existed.** `cohost_candidates.py` has used the YB-vocative
signal since 1.32, with run-sheet phrasing as a second signal and word-level caption timings
instead of the interpolation I built. I only found it in ep41's own `oversized-block` waiver,
which cites it. Mine was deleted; searching the repair tools before writing would have cost
a minute. The signal is also not flag material either way -- Rafizi RELAYING speech aimed at
him looks identical ("Orang tanya saya, YB, you bising lah"), and so does reading a letter
aloud (ep43's "Untuk makluman YB, saya telah dihubungi"). A speech-verb filter catches 8 of
8 real buried turns but only 2 of 5 quotations, because the introducer sits a whole sentence
back, and ~40% false positives over 82 blocks is the over-firing that took `generic-label`
to 351 turns.

**The reason the existing tool missed ep41 is worth more than the tool I wrote.** It windows
each block as `[start, next_block_start)` and reports `0 candidates from 1846 words` for the
very block holding three YB vocatives. The block was stamped 2:33:49-2:51:37 while its text
ran to 2:52:19, because the FOLLOWING blocks were mistimed by 30-55s -- so the vocatives sat
at or past `end` and fell outside the window. **A pass with this tool is only as good as the
timestamps bounding it**, and the waiver that trusted its zero for ep41's other block was
resting on that. Retimed from the captions (2:52:22 / 2:52:35 / 2:52:37 / 2:53:13), the
ordering is monotonic and the tool's zero for that block is now true rather than an artefact.

**One trap re-hit, already written down in 2.5.** Patching `check_figures.py` through a
heredoc turned `\b` into a literal backspace (0x08) and left `SCALE_WORD` matching nothing
at all -- not just the word being added, every scale word. 2.5 records this exact failure.
Writing regex backslashes through a nested heredoc does not work; use an editor.

ep56's promotion surfaced a figure flag that was a check gap, not a fabrication. Raw says
`Hmm 40 40 miliar lah 1.6B`; the rewrite printed the house spelling `40 bilion`. `miliar` was
missing from `SCALE`, so raw's figure never tokenised and the published one had nothing to
match. Same number, same 1e9. Added -- and note a bare `miliar` grep counts 6 because it is
a substring of **familiar**, the same prefix trap as 2.5's `Fuzia`/`Fuziah`; with a boundary
there is exactly one in the corpus.

Remaining: ep19 (2 turns), ep26 (11), ep41 (1), ep53 (22). All need the audio.
`adjudicate_speakers.py` puts the 35 raw-side ones on one page, each linked into the video
six seconds early with the turn either side, and prints no guess -- the ep26 reading that
inferred a speaker from mid-sentence continuation was wrong, and the owner's per-turn answer
split two of those blocks across three speakers.

**Owner adjudicated both buried turns by ear, and corrected me on one.** ep41's
devil's-advocate question is Haziq, as expected. ep53's block is a five-way split, and the
part I read wrongly is the one I would have written in:

    [1:45:35] Rafizi  ... Spine punya apa nama ni masalah kan. Baik, kita dah lama ni
                          tau pasal ni kan.
    [1:46:03] Haziq       Ya, 1 jam 45 minit.
    [1:46:05] Rafizi      1 jam 45 minit pasal benda ni? Eh tak lah. Okay, so kita nak
                          kena pergi kepada killer question. ... kenapa jadi macam ni?
    [1:46:18] Haziq       Soalan yang menarik
    [1:46:19] Rafizi      Kan aku dah tanya kau. Aku dah bagi tip dulu tadi. ...

I had argued "Baik, kita dah lama ni tau pasal ni kan" was a co-host on REGISTER grounds --
timekeeping plus a segment transition, and this repo records that the run-sheet voice is
never Rafizi. **It is Rafizi.** The register heuristic is sound as a signal and useless as
a verdict: Rafizi runs the clock and calls the next segment himself. The rewrite failed the
same way in the opposite direction, grouping Rafizi + Haziq + Rafizi into one unlabelled
turn -- the identical seam error as ep26, where a boundary between two Rafizi turns
straddling an interjection read as a single speaker. **Two independent attempts to infer
this from text, two wrong answers, one right answer from four seconds of listening.**

Timestamps for the new sub-turns come from the episode's YouTube caption track, not from
interpolation. Reusing the parent block's stamp -- the ep26 precedent -- would have put
ep41's question at 2:33:49 when the captions place it at 2:51:37, seventeen minutes out,
because the split sits at 95% of a 13,756-character block. `audio/<video_id>.ms.vtt` is
already on disk for both.

**And the caption `>>` markers are not a speaker-change signal, though they look like one.**
They land exactly on ep53's four boundaries, which is what made them tempting. In ep41 they
also fire three times inside what the owner reads as one continuous Haziq question ("marah
orang semua kata rakyat ketagih", "Jadi yalah", "er juga disumbangkan oleh ahli politik").
Useful for finding a moment; not evidence of who is speaking.

Adjudications recorded in `data/speaker_adjudications.json`, which also carries the one thing
deliberately NOT touched: ep41's next three blocks ([2:51:37] Haziq, [2:51:45] Rafizi,
[2:51:46] Haziq) are shredded mid-sentence against captions that hold 2:52:19-2:52:34 as
one voice with a change only at 2:52:35.

**Closed at QA 0/68.** The owner adjudicated all 35 remaining cluster turns across ep19,
ep26 and ep53 in two messages, given a link per turn seeked six seconds early with the turn
either side. 13 were substantive rulings, one of them a text correction; the 20 residual
one-word acknowledgements went to `Speaker ?` without a listen, on the owner's standing
principle that substance outranks per-fragment attribution. Crosstalk that cannot be
apportioned gets `Multiple speakers` -- a different claim from `Speaker ?`, which is one
unidentified person. Corpus-wide: 0 numbered clusters in raw, 0 in the published files, 0
buried turn markers, 0 unlabelled turns, 0 backward jumps.

`apply_split_map.py` applies the map and refuses to change words -- every operation is a
relabel, a boundary move or a retime, and the word sequence of a touched block is asserted
identical before and after. Building it surfaced three things the naive version got wrong:

- **A timestamp is not unique.** ep26 repeats 14 of them and ep53 17, partly because a split
  re-uses the parent stamp. Keying rules on the stamp alone matched two turns at ep26
  `[09:59]` -- `Speaker 1: "Itu zaman"` and `Rafizi: "dahulu. Ini ada orang tag lah..."`.
  Rules now pin the label and the text, and a long block can pin by prefix.
- **An anchor can repeat inside its own block.** ep53 `[2:19:13]` is "Human resource Itu je
  lah kot Okay Okay Human resource lah Takde", so "cut after Human resource" had two valid
  answers and the owner's Rafizi turn is the first. Ambiguity is refused, not resolved by
  taking the first match.
- **It has to be idempotent**, because the map is re-run whole as it grows. Without that a
  rename is a silent no-op, a merge eats the following turns, and a `text_now` whose
  `text_was` already changed aborts the run.

One narrow exception to the no-words rule: `text_now`, used once. ep19 `[1:43:04]` was
transcribed "MRT." and the caption reads ">> Hmm." I had reasoned at length about who would
guess MRT in a quiz about debt-causing projects -- confident analysis of a word nobody said.
The owner's other quotes normalise punctuation ("Kita.... Ah itu Jason" for raw's "Kita Itu
Jason") and were deliberately NOT applied: that is rewriting the transcript, not attributing it.

Still open, both recorded in `data/speaker_adjudications.json` rather than guessed: **ep19's
roster** (the owner places Farhan at 2:24:55, but raw never labels him and
`rebuild_roster.py` derives hosts FROM those labels, so it cannot discover him), and
**ep41's three retimed blocks**, whose labels remain shredded mid-sentence against captions
that hold 2:52:19-2:52:34 as one voice.

### 2.7: Turns the diarizer split at pauses, and a heuristic that tested at 14%

The diarizer cuts on silence, not on speaker changes, so one person's continuous speech
arrives as several turns under one name. ep41 shipped this:

    [2:53:13] Rafizi: ... Pasal perubahan iklim 10 15 tahun
    [2:54:43] Rafizi: Aku
    [2:54:44] Rafizi: orang cakap pasal Climate change ...

"Aku" is the first word of the sentence below it. Nothing in the pipeline ever merged these
-- 707 runs in raw.md across 45 of 68 episodes, and **1,175 runs across 185 of the 204
published files**, so the reader-facing files were worse than raw. 2,924 turns merged.

**Checked before writing, because merging grows a block's measured span.** `wall-of-text`
is gated on a block holding more than one inline turn marker and a merged block holds
exactly one, so it cannot fire. `oversized-block` reads wall-clock span, which does grow
for 15 episodes -- simulated across all 68 and **zero** cross the 20-minute threshold. The
real cost is seek points: ep26's 14-turn Rafizi run becomes one block with one timestamp.

**The owner asked whether `Speaker ?` could be guessed from context -- "usually its
rafizi". It is the right intuition about the corpus and the wrong one about these turns,
and their own adjudications prove it.** Of 44 turns they had just identified, Rafizi was 24
(55%), so blind guessing is wrong 45% of the time. The structural version does far worse:
of 7 unknown turns sitting between two turns by the SAME person, predicting that person
was right **once**, and that one was really three speakers.

    ep53 11:41    Rafizi | ? | Rafizi  ->  Haziq
    ep53 34:39    Rafizi | ? | Rafizi  ->  Haziq
    ep53 1:58:48  Rafizi | ? | Rafizi  ->  Farhan
    ep53 2:59:47  Rafizi | ? | Rafizi  ->  Multiple speakers
    ep19 1:43:04  Rafizi | ? | Rafizi  ->  Haziq

14%, worse than ignoring the neighbours entirely. The reason is that these are not a random
sample: **a turn becomes an unknown cluster precisely because the diarizer heard something
the neighbours are not.** Same mechanism that made `name_published_placeholders.py` score
ep41's turn Rafizi 3/3 on a turn opening "YB, sedikit soalan" when Rafizi IS the YB.

So the resolution was structural rather than a guess: fold only **backchannel** -- laughter
and acknowledgement tokens, 93 of them -- into the preceding named turn, where being wrong
costs nothing a reader relies on, and leave every turn carrying a proposition as
`Speaker ?`. The filter is deliberately narrow, and single words that look small are
excluded on purpose: `0.017` is a figure, `Forward` and `Juali` are content, and
`Saya boleh lihat.` recurs six times across five episodes as somebody's actual sentence.

**Adding Farhan to ep19's roster immediately raised `unlabelled-host`, by construction.**
`rebuild_roster.PRESENT_UNLABELLED` exists to add a person raw.md never labels;
`unlabelled-host` flags exactly that. Every entry in the one trips the other. Waived with
the strongest evidence of the three such waivers: ep39 and ep55 rest on "no evidence he
spoke at all", whereas ep19's Farhan demonstrably spoke -- jointly with Rafizi at
[2:24:55], already in the transcript under `Multiple speakers`.

**Disk.** The repo was 14 GB, `audio/` all of it: 8.2 GB of decoded 16 kHz WAVs that
`verify_speaker_voiceprint.load_audio()` rebuilds with ffmpeg whenever one is missing.
`cleanup_scratch.py` frees them and keeps both sources -- the .m4a because re-downloading
needs yt-dlp plus the PO-token server plus YouTube's cooperation, and the .vtt because 63 MB
of captions are the ground truth behind every timing check. It refuses to run while a gate
is mid-flight: `data/_*_incumbent` is not a leftover then, it is the only copy of the
published files a losing candidate would be restored from.

### 2.8: The topic lists were thin because the prompt never asked, and two bugs that hid it

The owner read the output and found the main theme of episode after episode missing from
its own topic list: `Gen Z` in ep52, `e-Fishery` and `KWAP` in ep56, `Rohingya` in ep53,
`AUKU` in ep60. Three separate defects, and the interesting part is that only one of them
was where I first looked.

**One. The prompt never asked for topics.** `META_PROMPT_TEMPLATE` carried a full paragraph
on how to sort hosts from guests and said **nothing at all** about `topics` -- no count, no
coverage requirement, no instruction to work through the episode. One line for a
three-hour episode was a valid response, and for five episodes that is what came back:
ep25, ep29, ep34, ep35 and ep37 each carried a single topic. The prompt now states what a
topic list must do, including the two rules the owner supplied: name the SUBJECT rather
than the speaker (a guest is not a topic and is already in `guests`), and the title's theme
must appear.

**Two. I went looking for the answer in the wrong place first.** Before finding the prompt
I built a statistical extractor over the transcripts -- acronyms and capitalised phrases,
ranked by TF-IDF -- and put it in a README column. It missed the same themes, each for its
own reason, which is the tell that the approach was wrong rather than under-tuned:

  Rohingya    the phrase pattern required TWO capitalised words, so single-word proper
              nouns were invisible
  e-Fishery   lowercase-initial and hyphenated, spelled four ways, matching no pattern
  AUKU        in only two episodes, so an episode-spread threshold of five dropped it
  KWAP        six mentions, below every threshold
  Gen Z       offered `Zaim Zulkifli` instead: a guest, and the wrong kind of answer

Every one of those was already written in the frontmatter. "Krisis pelarian Rohingya di
Malaysia" was sitting in ep53's file the whole time. **The `topics:` list is the only place
anything in this pipeline read an episode, and I detoured around it to compute a worse
answer from surface patterns.** The column is gone at the owner's call and the statistical
tables with it; TOPICS.md now prints the curated lines verbatim and computes nothing.

**Three. Two bugs were hiding the scale of it.** `common.frontmatter_md` called `yaml.dump`
with no `width`, so it wrapped list items at 80 characters with a two-space continuation.
Valid YAML -- and every frontmatter reader in this repo parses with a regex of the shape
`^topics:\n((?:- .*\n)*)`, which stops at the first continuation line. So a wrapped entry
truncated the list and hid every entry after it. **24 episodes shipped that way before
today**: ep11's twelve topics read as three, and my coverage report said the mean was 49%
when it was really 78%. `frontmatter_md` now passes a large width and
`normalize_frontmatter_lists.py` repaired what was on disk.

The second was mine and worse. `read_frontmatter_body` strips a leading "# Interview" from
the body and `frontmatter_md` does not write it back -- the pair is asymmetric, because the
creators in `transcribe_episode.py` prepend the heading themselves. So a read-modify-write
DELETES it, and my first `write_topics` did exactly that to **147 files**, taking the
corpus from 68 headings to 19. `rebuild_roster.py` had been dodging this for months by
re-reading the body's first line and prepending it, which works only while that line is
the heading. `common.set_frontmatter_list` now replaces one field surgically and asserts
the body is unchanged; both writers use it. Repaired by taking each body from git and
substituting only the topics block, then verifying all 272 bodies byte-identical.

**The score is the show's own chapter markers.** 39 of the 68 YouTube descriptions carry
timestamped segment titles written by the people who made the episode, and they were
sitting unused in `data/manifest.json` -- ep35 has nine, including "Bloomberg Kasi Kantoi
Azam Baki" and "Isu Rumah Ibadat", which is exactly what its title promises and its
one-line topic list omitted. `gate_topics.py` re-extracts and promotes only on better
coverage of those chapters. An external reference, for the same reason the QA suite checks
transcripts against YouTube's captions rather than against themselves.

Mean coverage 49% -> 82%, 53 of 68 episodes promoted, 1,020 topic lines against 716.
ep35 went from 1 topic covering 1 of 9 chapters to 14 covering 8.

**The gate's first rule was wrong too, and threw away its best results.** Requiring
coverage AND line count to both be non-decreasing rejected ep28's candidate at 15/15
chapters against the incumbent's 9/15, for having 16 lines instead of 19; ep13's 17/18
against 11/18 lost on 14 against 15. Line count is a proxy, coverage is the thing itself.
Coverage decides now and line count only breaks a tie.

**Still open: 29 episodes have no chapter markers**, so nothing external scores them. They
fall back to line count, which is weak. ep25 is the one to look at first -- one topic, no
chapters.

### 2.9: A sentence nobody said, in 98 files, and the four ways I nearly broke the corpus removing it

`Sila berasa bebas untuk menyukai, melanggan, maju dan memberi ganjaran untuk menyokong
lajur Der Spiegel dan Diandian` appeared **142 times across 98 files**, 29 of them
`raw.md`. It is a Malay rendering of Chinese YouTube-subtitle boilerplate that
mesolitica's Whisper absorbed from its training data. Nobody on this podcast says it.

The interesting part is not the hallucination. It is that a text-only deletion of a
sentence that is provably not speech took four attempts to get right, and **every one of
the four failures was caught by a check rather than by reading the output.**

**First, the question that had to be answered before deleting anything: did it REPLACE
real speech, or sit beside it?** Deleting an insertion is safe. Deleting a replacement
loses words permanently and hides that they were ever lost. The answer came from the
YouTube caption track: take the words either side of the hallucination in raw, and ask
whether both sides land inside ONE window of the captions. If they do, the real speech
runs straight through the spot. **41 of 41 checkable occurrences: yes. Zero
counter-examples.** ep05's and ep12's six occurrences have no caption file on disk and
remain unverified.

The first version of that probe scored the two sides INDEPENDENTLY and measured the
distance between their best windows. It reported 5 replacements. All 5 were artifacts --
the before-side window landed 33 to 106 words early, and the printed span then showed the
before-side text sitting at its own tail. **The metric was measuring anchor-localisation
error and calling it lost speech.** Contiguity inside a single window cannot fail that
way, because a window containing both sides IS the answer.

**Bug 1: a whole-file punctuation tidy would have destroyed every ellipsis in 98 files.**
The seam left by a deletion needs repair, so I normalised punctuation with
`([.,]) ?\1+` -> `\1`. On `...` that produces `.`. It ran over the entire file, not the
edit site. A dry run would never have shown it, because **a dry run prints what it
deletes, and this was damage to text it did not touch.** Found by a check that counts
`...` in, minus `...` inside removed spans, against `...` out. Repair is local to the join
now.

**Bug 2: `\s` matches newlines, and that welds two speakers together.** With `\s*` in the
closing pattern, the match for ep12's boilerplate ran past the end of the sentence and ate
the `\n\n` after it:

    before: ... dalam kerajaan. [BOILERPLATE]\n\n[1:09:24] Haziq: lajur ... Baik, baik
    after:  ... dalam kerajaan. [1:09:24] Haziq: Baik, baik

One speaker's turn marker ends up buried inside another's block -- the exact defect
`check_published` exists to find. **Four episodes lost a paragraph break (ep12, ep37,
ep42, ep46) and qa_check went from 0/68 to 4/68.** I only caught it because I had captured
a `check_published` baseline on the pristine corpus BEFORE applying, and could compare 2
against 6. Every whitespace class in the patterns is `[ \t]` now, and a
newline-conservation check makes the failure mechanical rather than lucky.

**Bug 3: a fixed-length trailing run cuts a word in half.** A `[^.!?\n\]]{0,20}` tail
landed exactly inside `der` and shipped `r Spiegel and Diandian` into ep21. Two files
showed a word-count that was one HIGHER than the arithmetic predicted, which is the
signature: the span reported a word (`de`) that was not actually gone, because its other
half (`r`) stayed. Fixed by deleting the pattern that needed the tail; a greedy body up to
the last tail marker covered the same cases.

**Bug 4: a survivor check keyed on the giveaway vocabulary is blind to fragments.** The
hallucination straddles block boundaries, so ep20 carries `Sila berasa bebas untuk
menyukai,` with the rest of it in the next turn. That fragment contains no `Der Spiegel`,
no `Diandian`, and not even the `menyukai, melanggan` pair -- so a survivor check keyed on
those reported a clean corpus while three fragments sat in it, in three files. The check
keys on the translationese LEAD-IN now, which is what a fragment always retains.

**The invariant that finally made the thing safe.** Not a better regex -- a guard. A span
may be deleted only if **every word in it comes from the hallucination's own lexicon**.
The boilerplate is built entirely from a closed vocabulary (`sila`, `berasa`, `bebas`,
`untuk`, `menyukai`, `melanggan`, `maju`, `ganjaran`, `menyokong`, `lajur`, `der`,
`spiegel`, `diandian`, and their English and short-Malay equivalents), so any span that
has reached into real speech carries a word from outside it and is refused. That single
rule caught bug 3 by itself: `de` is not a word in the lexicon. Complete spans must ALSO
carry the giveaway vocabulary, because `dan ini untuk` is all lexicon and all real Malay.

**And the thing the guard cannot do, which is why shape still matters.** `Jangan lupa
untuk melanggan` is REAL SPEECH on this show -- the hosts plug Rafizi's own channel, and
ep16 has Haziq joking about having to (`melanggan dan melanggan, celaka teruk`). It is
also one of the hallucination's lead-ins. Every word of the real plug is in the lexicon,
so the guard is blind to the difference; only the sentence shape separates them. Lead-ins
are therefore split in two: `LEAD_SAFE` (`Sila berasa bebas untuk` -- translation register
with no spoken equivalent) where any boilerplate continuation can go, and `LEAD_RISKY`
(`Jangan lupa untuk`, `Feel free to`) where a fragment needs the hallucination's own comma
list first. One instance survived by luck of punctuation before this split existed: ep15's
`jangan lupa untuk melanggan.` escaped only because the full stop defeated an
end-of-line lookahead.

**The rewrite had also LAUNDERED it.** Six occurrences carry no channel name at all,
because the translation dropped them and kept the call to action: `[Silakan follow, like,
subscribe kepada channel ini.]` in ep28, `Feel free to like, subscribe, and support this
column.` in ep16, `[Feel free to like, subscribe, and support this show.]` in ep17. Each
interrupts unrelated speech; ep50's lands in the middle of Rafizi saying he is not
involved in whatever anger there is at Farhan. A pattern keyed only on `Der Spiegel` would
have left all six in the published files, and a pattern keyed on a bare `like, subscribe`
would have deleted the hosts' genuine plugs.

**Method note, for the next bulk edit.** Three things paid for themselves: capturing a
checker baseline on the pristine corpus before applying anything, so a regression is
visible as 2 -> 6 rather than as an absolute number that looks plausible; making the
verifier operate on the tool's real output instead of a single-pass prediction of what it
would match, because `scrub()` loops and can delete spans that only become matchable after
an earlier removal; and reading eight sample seams by eye AFTER all the automated checks
passed, which is how the orphaned `]` in ep28-ms and ep05's three stranded blank lines
were found. Both then became checks.

One more repeat of an old lesson: **a `.replace()` whose needle never matches reports
success.** Two of four substitutions in one shell heredoc silently did nothing, because
the heredoc ate `\]` and `\s`. The symptom was a regex behaving exactly as it had before
being "fixed". Assert that the needle was found, or edit the file directly.

Result: 142 spans removed, 98 files changed, qa_check 0/68, check_published back to its
pristine baseline of 2, check_figures 0/68, check_names unchanged at its one waived
expansion, and every real `menyukai` / `melanggan` / `jangan lupa untuk melanggan` still
in place.

### 2.10: A transcript that ended 30 minutes early and passed every check

`gemini-3.8-flash` transcribed ep62 (3h55m21s, the longest episode in the corpus) with no
loop at all -- a real improvement on ep61, where the same family of models produced 430
blocks holding 35 distinct texts. 267 blocks, 267 distinct, 0% duplicated.

It also stopped at 3:25:08 and wrote an ending nobody said.

```
[3:24:58] Haziq: ... a closing thank-you and sign-off
[3:25:04] Rafizi Ramli: ...
[3:25:06] Farhan: ...
[3:25:08] [music/outro]
[3:55:22] [end of audio]
```

The captions show the hosts at that moment mid-analysis of a named UK company filing in
FELDA's corporate records, and carry **1,334 more cues and 3,003 more words** afterwards,
running to 14099s. The real ending at 3:54 is different wording entirely, including
`then I'm exhausted sebab 4 jam dah`. So 12.7% of the episode is missing and the seam is
covered by an invented farewell.

**Three checks passed it, and the third is the interesting one.**

| check | reading | why it missed |
|---|---|---|
| duplicate share | 0.0% | correct, and irrelevant. There was no loop |
| stamp coverage | 100.0% | the model wrote `[3:55:22]` itself. Its clock is not evidence |
| word ratio vs captions | 1.10x | see below |

Over the 87% it did cover, the model emitted **26%** more words than YouTube's caption ASR.
That is normal and not a defect -- caption ASR drops words, and every clean episode in this
corpus sits near 1.1x. But that surplus numerically paid for the missing 13%, landing the
whole-file ratio at a healthy 1.10. **A whole-file word count cannot see a truncation,
because verbosity in the covered part funds it.** The two numbers are indistinguishable:
ep61's reviewed raw.md scores 1.11 and ep62's truncated one scores 1.10.

`check_content_coverage.py` bins both sources into 5-minute windows and flags a window
holding under 15% of its caption words. ep62's hole shows up as six consecutive empty
windows starting at 3h25m; ep61 comes back clean across all 35.

**The first version of that checker was wrong, and the control is what caught it.** It
charged every block's words to the block's start stamp, so ep61's reviewed raw.md reported
six empty windows over 17.2% of its runtime. Nothing was missing. This corpus has blocks
spanning minutes -- one ep62 block covers 896 seconds of continuous speech -- so a checker
built that way has a false-positive rate that scales with block length, which is precisely
this corpus's known defect. Fixed by giving each block the interval from its own stamp to
the next one and spreading its words across it. Still an approximation, now unbiased with
respect to block length.

Two things generalise:

- **Run a known-good control before believing a new checker.** Had ep61 not been run
  through it, the ep62 result would have looked like confirmation instead of coincidence,
  and the threshold would have been tuned to a broken measure.
- **A model's own timestamps are not evidence about a model's own coverage.** Anything the
  engine under test produced is inadmissible as the yardstick for it. The captions work
  because nothing in this pipeline generates them.


### 2.11: ep62's raw.md is now MAI's words under the camera's names, and why the scorer says that is worse

The owner read ep62's raw.md on 2026-09-10 and sent back 13 text corrections and three
regions that "feel weird": a sentence ends under one speaker and its second half continues,
in lowercase, under another. `[18:00] Haziq: ... Yelah, Yi Leong` / `[18:02] Rafizi: dia
lawyer kan.` Counting that shape across the file -- block ends without terminal punctuation,
next block is another speaker and starts lowercase -- gave **44 of 180 blocks**. The first
explanation, that the camera re-cut's borrowed word clock (about 2 s out) placed the cuts,
was checked against the file's history and is wrong. The count was 11 of 53 blocks when
raw.md came off the local ASR, 63 of 184 after `reattribute_blocks.py` re-cut the blocks on
pyannote's turn boundaries, 43 of 186 just before the camera split, 69 of 182 just after it,
and 44 once the owner's corrections landed. So the defect is the local pipeline's block
re-cut: a diarizer boundary falls where the voice changes, and the local ASR's text at that
second is mid-sentence because the word clock it is cut on is a segment clock, not a word
clock. The camera split added to it and later passes took that back. It is corpus-wide --
2,349 of 15,939 blocks by the same heuristic, ep60 (never re-cut) at 81 of 240 -- with the
caveat that the heuristic over-counts on local-ASR text with poor punctuation.

MAI's own transcript of the same audio has a clock per word and better text (1.3% deletions
against the local ASR's 9.8%, ENGINEERING_LOG 1.45), but its diarization loses Farhan. So
`scripts/mai_camera_raw.py` builds raw.md from MAI's words and turns and labels each word
from the camera reference at that word's own time. Three rules, in order: a turn of three
words or fewer keeps MAI's label (the show never cuts to a grunt, so the camera is wrong
about backchannels by construction); otherwise the camera's speaker where it sees one;
otherwise MAI's label from the merged sandbox file, which carries the video-confirmed Farhan
regions. Long turns the camera splits are cut with `split_mixed_blocks.py`'s own smoothing
and sentence snap. The word sequence is asserted equal to MAI's and stamps non-decreasing.

| | current raw.md (local text, camera cut) | MAI words + camera |
|---|---|---|
| blocks | 180 | 1,694 |
| words | 26,203 | 29,812 |
| mid-sentence speaker cuts | 44 | 7 |
| owner's 13 garbles present | 13 | 3 (JCOM, Pepecat, expose) |
| video-confirmed Farhan regions kept | 14/14 | 14/14 |
| seconds under the wrong name, blocks of 4+ words | 142 | 82 |
| block-scorer confusion vs camera | 1.6% | 3.8% |

**The last row is the trap.** The new file scores worse on the block scorer while being
better on every row above it. `score_attribution.py` lets a block own every second until the
next block starts, and the new file has 778 one-word grunt blocks -- `[49:13] Haziq: Hmm.`
-- each of which owns the pause after it while the camera stays on Rafizi. 363 of the 470
confused seconds are those. Splitting the confusion by block class before reading the total
is what showed it; the total alone would have rejected the better file, which is the same
lesson as [[feedback_metrics_pass_broken_output]] with the sign reversed.

Adopted as raw.md at the owner's decision, with J-KOM x2, Pecat x1 and exposé x4 (the noun
uses; `yang saya expose paling awal` is the verb and stays) applied by hand. The other ten
corrections MAI already had right unaided. `check_figures` and the interview now share a
source, which they did not while the plan was to rewrite from a sandbox file.

**Left for the owner:** the corpus writes the Community Communications Department as
`JKOM` 366 times, `J-KOM` 31 times and `JCOM` 4 times outside ep62. The official form is
J-KOM. That is a corpus-wide name correction and goes through `fix_proper_nouns.py` with the
owner's say-so, not by majority.

**The per-segment gate exists now**, `scripts/rewrite_segments.py`, and its first bake-off
on three ep62 segments settled two things. Haiku translated two of three segments wholesale
into English (Malay density 0.00 and 0.12 against a floor of 0.80) -- the same failure it
showed on whole episodes, now caught per segment instead of per file. And the figure gate was
too strict for a polishing model: Sonnet's "missing" figures were `2/3` written as `dua
pertiga` and `2 3 orang` as `dua tiga orang`. A missing integer 0-12 is now accepted when its
Malay or English number word appears more often in the output than in the input. With that,
Sonnet passes 2 of 3 (it still dropped a `99` and a false-start `20` on segment 10) and
gemini-flash-lite 3 of 3 at 2-6 s a segment, editing very little. Which polish level to ship
is the owner's call, still open.


### 2.12: ep62's interview files, segment by segment, and the four figures the gate sent back to the owner

The first episode written by `rewrite_segments.py` (ARCHITECTURE, "Writing the interview files
from segments"). 26 segments, three stages, 78 outputs, every one measured before it was kept.

**The gate earned its keep on figures, and in both directions.** Four segments it refused were
right to refuse in a way no length or language check could see: Sonnet had read `2.2.26
billion` as `2.263 billion`, `1.5.19 eh, September 2014` as `15.9`, `20, uh, 20 tu` as `2020`
and `2016- 13` as `2013`. Each was a garble in the raw that the model resolved by guessing.
The owner listened: `benda ni dah 15 tahun`, `daripada 2020 kan, dia di bawah Datuk Seri
Azmin`, `2.2-2.6 billion`, `dua ribu en--eh tiga belas`, and 1.5.19 turned out to be a
paragraph number Rafizi was reading from page 62 of the 2019 FELDA White Paper ("Kes 7:
Pembelian Park City Grand Plaza Kensington 1.5.19 Pada 8 September 2014"). raw.md was fixed,
the segments re-run, all four passed first time with every figure kept.

The other refusals were the gate being too literal, and each became a rule: `137, eh, 193
juta` losing its 137 is a self-correction (accepted by hand, `--accept-figures`, after the
printed context is read); `tahun 60-an` becoming `the 1960s` is a year written out; `2/3`
becoming `dua pertiga` is a number word; `4,800` and `4800` are one figure. And the Malay
stage's floor was wrong: a Malay translation of colloquial Malay formalises it, so `tu`, `ni`,
`kan`, `lah` fall away and the function-word count drops to 0.60 of the input with nothing
lost. The test that it translated is that the English function words vanish, which they did
(49 to 1 on the worst segment).

**Two things --write got wrong on the first pass**, both found by reading the output rather
than the checkers: it stamped `model: claude-haiku-4-5-20251001` on Sonnet's text because it
took the model from the command line instead of from the segments' reports, and MAI's `Podcast
Yang Menteri Menteri` had flowed from raw into all three files and the summary. The first is
fixed in the tool; the second is a fix_proper_nouns rule (7 occurrences, all ep62, against 424
correct).

Cost of the episode: about $8 on the Claude seat -- 31 mixed calls, 55 translation calls, one
metadata call. Baselines after: qa 0/69, check_figures 0/69, check_published 0 on ep62,
check_rewrite_complete ok (en 1.08, ms 0.99 of interview.md).

**Addendum, the same evening.** The owner read the result and asked two things the gate does
not measure. Why does a speaker's turn break into a dozen paragraphs -- because MAI's raw is
one block per phrase and the rewrite kept the structure one to one; every earlier episode
came from long local-ASR blocks and never showed it. And why does the interview still carry
"Ya.", "Hmm." and "Uh," -- because the prompt asked for smoothing and the model did a little.
Both are now rules with tools behind them (`clean_interview.py`, `merge_adjacent_turns.py`),
run inside `--write`: ep62's interview went 1,100 -> 382 turns, 49 retort turns and 678 filler
words gone, every other word asserted in place. raw.md lost its 544 grunt blocks the same way
(`strip_filler_turns.py`), which also removed the block one owner decision named (1:08:44, a
laugh); the record notes it.

One more class surfaced while reading: 56 short turns whose words repeat the neighbouring
speaker's -- Haziq: "Ringgit." after Rafizi's "15,000 ringgit". The caption track, an
independent transcription, has the phrase twice for 40 of them: the co-host echoing the last
word is a habit of the show, not a duplication. 16 have no caption witness either way and are
left as MAI heard them (two voice clusters, distinct word times).

**Corpus-wide, the same day.** The owner asked for the newspaper-copy rules on every episode.
Deterministic, no model calls: 69 episodes, 495 retort turns dropped, 3,742 filler words
removed, 648 slip-ins dropped, 1,034 same-speaker joins across the interview files. Two guards
came out of reading the diff before committing. A slip-in carrying a figure -- `Iqbal: -35.`,
`Rafizi: 46, awak 46.` -- was being dropped for interrupting a sentence although nobody around it
repeats the number; five such lines. A figure now only goes when the surrounding speaker says
it, and a diff check confirms every removed digit survives in the kept text (0 lost). And the
pass was not idempotent: a join exposes a new sandwich, a drop makes two turns adjacent, so a
second run changed ep62 again. It now runs to a fixpoint; a second pass over all 69 changes
nothing. Baselines identical before and after: qa 0/69, check_figures 0/69, check_published's
three pre-existing flags.

**ep61 adopts the MAI+camera raw, 2026-09-10.** Two gates had to be built first, and both
were built because the same defect had already destroyed one owner decision on this episode.

*Locating a decision when the words are not the same.* Every earlier pass moved labels over
fixed words, so a decision could be found by its text. MAI's transcript is a different
engine: the same speech spelled differently, split over more blocks, with the fillers the
local model dropped. Substring lookup found 6 of ep61's 44 recorded decisions.
`scripts/lib_locate.py` scores candidate windows on CHARACTERS, over a window wide enough for
inserted fillers, which is what makes Malay affixation harmless -- the decision reads
"pandangan lain sikit" and MAI heard "Aku berpandangan lain sikitlah", sharing no whole word
with it. Result on the same file: 38 preserved, 4 partly kept, 1 mismatched, 1 with no text
to search for. The 4 partial ones are all one benign shape, worth knowing because it looks
like damage: the local block glued two speakers together, the candidate splits them, so the
located span straddles the cut. The 1 mismatch is the same shape around the Farhan
interjection at 2:51:42, where the candidate agrees with the owner's own window and the
decision's snippet reaches back into Rafizi's words.

*A stamp cannot locate anything here.* All 11 of ep61's `Speaker ?` confirmations were
recorded against a stamp 3 to 21 s away from its own words. The frame at the stamp showed
Rafizi in all 11. At the words' real time the camera shows Rafizi in 9 and Haziq in 2 --
04:46 belongs to words at 05:05, 06:52 to words at 07:08. Nine were right for the wrong
reason: the episode is 86% Rafizi, so a frame sampled 20 s away usually still lands on him.
The owner was shown both readings and kept Rafizi for both; `data/forced_labels.json` now
holds those rulings and `mai_camera_raw.py` applies them after the camera pass, refusing to
run if a ruling cannot be located. DER 2.3% -> 2.4% is what the two cost.

*The gold passage is carved out, not overwritten.* ep61's owner-dictated passage is exactly
where the camera fails: the shot is a full-screen graphic, so the reference gives Haziq's
"Baik YB, cuti panjang YB buat apa?" to Rafizi and Rafizi's answer to Haziq. The current
raw.md's 14 blocks for it are spliced in verbatim, replacing 79 candidate blocks (356 MAI
words), with the seam found by words because the two files' clocks differ by up to 26 s. Name
corrections run before the splice, so the owner's bytes are never rewritten, and the checker
tests containment rather than list equality, which leaves a re-cut on either side free to
differ.

Adopted result: JER 55.5% -> 13.8%, Haziq recall 66% -> 90%, 552 -> 74 seconds under the
wrong name, 101 of 252 -> 59 of 2,425 blocks holding more than one speaker, longest block 742s
-> 52s. The file gains about 3,000 words the local ASR dropped and now runs to the sign-off at
2:54:18, where the old one stopped at 2:51:43 with 2.5 minutes missing. No gap over 60 s
anywhere in it. Baselines held: qa 0/69 with 10 waived, check_published 2/69, check_figures
0/69, check_names 1 episode. `interview*.md` is stale until `rewrite_segments.py` runs, and no
checker sees that -- it is the same blind spot the published-file checks were written for.

**J-KOM, corpus-wide, the same day.** Jabatan Komunikasi Komuniti hyphenates its own name and
the corpus had 366 unhyphenated against 39 correct, so the majority spelling was the wrong
one. 370 replacements over 28 episodes, both patterns word-anchored, which counting the odd
forms first decided: `KPJKOM` x2 keeps its spelling (KP is the Ketua Pengarah; nobody writes
KPJ-KOM) and `JKOM-nya` x2 is matched on purpose. All 153 changed lines were read and each
differs from its old line only by the acronym. Baselines captured on the pristine corpus
first and all four held.

## History moved out of CLAUDE.md, 2026-09-27

A prompt audit shortened four passages in CLAUDE.md to their current rule, because every
session loads that file. The owner approved the change. The full original text is kept
here, unchanged.

**Rule 6, the `--episode=` flag of `merge_same_speaker.py`:**

> **IT IS `--episode=<tag>`, NOT A BARE TAG, and the difference is the whole corpus.** This
> script takes no positional argument. `merge_same_speaker.py ep32 --write` ignores the tag
> and edits EVERY episode with a same-speaker run. That happened on 2026-09-14 and silently
> changed interview files in ep35, ep37 and ep38 while the intent was ep32 alone; the table
> below carried the wrong form, which is how it happened. The script now refuses an argument
> it does not recognise and names the likely intent.

**Rule 7, the owner-ruling path in `move_hanging_words.py`:**

> Where the camera has no coverage, a recorded owner ruling moves it instead (ep56 01:24).
> **That sentence was ASPIRATIONAL until 2026-09-15**, and it is the kind of claim this file
> warns about: the tool's `owner_rulings()` required keys shaped `ep56@01:24`, and not one of
> the 114 stamp keys in `data/speaker_adjudications.json` has ever been written that way.
> Every one is a bare stamp in a tag-named section, the shape this file mandates and
> `check_owner_decisions.py` reads. So the path was dead code and ep56's own ruling was
> invisible to it. Fixed, with a digit guard so `ep2` cannot match `ep27_rule7_...`. Two
> consumers read that file; when the key shape changes, check BOTH.

**Rule 7, what the owner's rulings measured:**

> **What the owner's rulings measured, and why the fix was allowed to write.** The bar this
> rule set was that a candidate leaves the list only when a MEASURED tool moves it, never on
> a better guess. On 2026-09-13 the owner ruled all 11 `tail` boundaries after looking at
> contact sheets, and **every one went the way the camera had already read it** -- 11 of 11
> against a human eye. Their words: *"Actually all these can be verified visually..."* That
> retired the escalation: 21 tails and 6 whole blocks were then moved across 17 episodes,
> every word conserved by the existing guard, and the corpus went from 35 contested plus 11
> tail to zero of each.

**Rule 9, the frontmatter cast found on the first pass:**

> **Also fixed by this rule's first pass, and it is the class to watch:** the frontmatter
> cast is written by the rewrite pipeline from the transcript, and nothing ever compared it
> to the episode's own description or to who actually speaks. 7 episodes name a speaker in
> raw.md who is in neither `hosts:` nor `guests:` (ep01 Najib and Nazri, ep02 Prof.
> Barjoyai, ep03 Faiz, ep06 Eric See-To, ep07 Daniel, ep08 `YB Rafizi` as a label variant,
> ep09 Rodziah Ismail). `Multiple speakers` and `Audience` are sanctioned labels and are not
> findings.

## Moved from ARCHITECTURE.md, 2026-09-27

The owner asked for ARCHITECTURE.md to describe only the pipeline as it stands, in plain
and short form. Every section below was in ARCHITECTURE.md until then: dated incident
write-ups, measurements and evaluations. They are kept here unchanged, one heading level
lower. New blocker write-ups go into this file from now on.

### Retrying Gemini on a previously-failed episode

Landing on a weak fallback model (e.g. `gemini-3.5-flash`) doesn't always mean the
episode's content triggers `PROHIBITED_CONTENT` on every stronger model: that's
confirmed deterministic for ep13 (see above), but the fallback chain also advances on
plain free-tier quota exhaustion (20 requests/day per model) or a model being
temporarily unavailable, which a standalone single-episode retry (full quota, not
mid-batch) can sidestep entirely. Confirmed on ep53, 2026-08-25: a fresh single-episode
`--engine gemini` retry succeeded (via `gemini-3.6-flash` -> `gemini-3.1-pro-preview` ->
`gemini-3.5-flash` on quota/availability fallbacks, not a content block) and produced a
completely different, much smaller class of error than the original attempt's
~140,000-char repetition-loop degeneration: 14 duplicate blocks from a
continuation-loop hallucination (see `dedupe_raw.py`), not a repetition loop. Worth a
standalone retry before assuming `--engine local` is required, unless the episode has
already shown a *deterministic* content block on retry (ep13's case).

**New duplicate pattern found while fixing ep53's residual duplicates**: after
`dedupe_raw.py` resolved every duplicate group its caption cross-check could confirm,
6 groups remained unresolved (captions didn't cover those phrases). All 6 shared an
exact, systematic pattern: the same content appeared twice with identical MM:SS but a
different hour digit (e.g. `[1:38:29]` and `[2:38:29]`): a continuation-loop
hallucination that re-emitted an already-covered block but mislabeled its hour. Since
one of the 6 pairs was the episode's closing sign-off ("terima kasih... jumpa lagi
minggu depan"), and a sign-off can only be near the true end of a long episode (this
one is 3h0m), narrative logic alone (independent of captions) confirmed the later
timestamp (`2:xx:xx`) was correct in every pair and the earlier one (`1:xx:xx`) was the
fabricated duplicate: the opposite of a naive "keep the first occurrence" heuristic,
which would have been wrong here. Worth checking for this exact hour-shifted pattern
before falling back to manual case-by-case judgment on caption-unresolved duplicates.

**A hand-rolled fix caused its own bug here, worth remembering**: repairing those 6
duplicates via a one-off script that split the body on `"\n\n"` and rejoined the kept
blocks with a single `"\n"` silently collapsed every paragraph break in the whole file
into one undifferentiated block, caught immediately by `qa_check.py`'s wall-of-text
check, not silently shipped, but a reminder that block-splitting logic needs the exact
same separator on the way back out as the way in.

### MAI-Transcribe-2 via Azure: an evaluation path, and its four undocumented limits

Not part of the pipeline. `scripts/transcribe_mai.py` and `scripts/reconcile_mai_speakers.py`
transcribe an episode with Microsoft's MAI-Transcribe-2 into `data/_mai_<video_id>/`, for
comparison against the local ASR. Nothing writes to `episodes/`.

    python scripts/transcribe_mai.py <video_id> --dry-run        # request, chunk plan, cost
    python scripts/transcribe_mai.py <video_id> --extra-phrase FELDA
    python scripts/reconcile_mai_speakers.py <video_id> --matrix

Credentials are `AZURE_SPEECH_KEY` and `AZURE_SPEECH_ENDPOINT`, both User-scope environment
variables that the script also reads from the registry, because a fresh shell does not
inherit them. **The endpoint is not the host the portal shows on its Foundry tab.** That tab
gives `https://<resource>.services.ai.azure.com`, which serves Agents and model inference;
the Speech REST API needs `https://<resource>.cognitiveservices.azure.com`. Only six regions
carry the model (`centralindia eastus northeurope southeastasia westus westus2`) and a
resource elsewhere fails rather than falling back.

**Limit 1: diarization dies above roughly 30 minutes.** Laddered on ep62 audio:

| audio | size | result |
| --- | --- | --- |
| 10 min | 4.8 MB | HTTP 200, 149 phrases, 2 speakers |
| 30 min | 14.4 MB | HTTP 200, 406 phrases, 2 speakers |
| 60 min | 28.8 MB | HTTP 503 `diarization_unavailable` |

The error names its own cause, and it is the diarization sub-service rather than the
transcription. Published ceilings are under 5 hours and 300-500 MB, so the 3h55m 113 MB file
was inside every documented limit. Chunks are therefore 30 minutes.

**Limit 2: leading silence makes a long request return HTTP 500.** ep62 opens with 43
seconds of digital silence, exact zeros, and every request starting there failed
deterministically -- 0-1200s, 0-1790s, 0-1800s, 0-1810s, stream-copied and re-encoded alike
-- while 15-1800s and 30-1800s returned 200 and 0-600s returned 200. Prepending 45 seconds
of silence to a clip that returns 200 makes that same clip return 500, which is the proof
rather than the correlation. So `cut_chunks()` starts each chunk at its first sound less one
second of run-up, measured with `silencedetect`, and adds the trim back onto the offsets. The
opaque 500 on the full file was this, not the 503 above: two different limits, two different
errors, neither documented.

**Chunking costs speaker continuity, and that is what the second script is for.** MAI numbers
speakers per REQUEST, so chunk 3's `speaker 0` is not chunk 0's, and a chunked run refuses to
write `raw.md`. `reconcile_mai_speakers.py` embeds each chunk's clusters from their own speech
spans, groups them across chunks by cosine similarity (single-link, and two clusters of one
chunk never merge), then names each group against the same cast voiceprints
`verify_speaker_voiceprint.py` uses. Groups that come back with the same name are joined
afterwards, which is needed: MAI split Rafizi into two clusters inside ep62's chunk 6, so his
207 minutes arrived as two groups scoring 0.962 and 0.939 against his reference.

Two guards were recalibrated for this granularity, both against measurements rather than
taste. The distinct-speaker floor is now applied PER CHUNK, since a union across eight chunks
hides a single chunk's collapse. The duplicate-text share now counts only turns of 20
characters or more, and a separate check refuses more than 4 identical turns in a row: ep62's
MAI output repeats short backchannels constantly -- 322 turns of "Hmm.", 93 of "Mm." -- which
is 34% of all turns, 0.0% of turns over 20 characters, and no repeated text over 80
characters at all. The loop this guard exists for, ep61's Gemini raw, was long text.

What ep62 measured, MAI against the same audio's local-ASR `raw.md`:

| | local ASR | MAI chunked |
| --- | --- | --- |
| blocks | 184 | 1,613 |
| mean gap between stamps | 76.8s | 8.7s |
| longest gap | 1,259s | 271s |
| words | 26,206 | 29,810 |
| coverage per 5-min window | no holes | no holes |
| Rafizi share of words | 93.4% | 90.7% |

The 93% one-label share is therefore not a diarizer collapse: two independent engines
measure it. `Grand Plaza Kensington`, `FIC London Hotel` and `Koperasi Permodalan FELDA`
survive as bias phrases, the last of which the local ASR never produced at all.

**MAI loses the third host, and the video says so.** `Farhan (Pa'an)` holds 279 words in the
local raw and 94 in MAI's. `frames_at.py` was run on ten regions where the two disagree, with
the three faces first fixed from turns both engines agree on -- Rafizi in black with a
tablet, Haziq in a light blue shirt with a laptop, Farhan in a black "97" hoodie. Eight of
the ten show Farhan on camera mid-speech in a single close shot, so the local raw is right
and MAI folded those words into Rafizi or Haziq: 0:11:48, 1:00:12, 2:27:17, 2:50:13, 3:12:26,
3:37:39, 3:53:51 and 3:54:15. One goes the other way: 3:53:48 "4 jam kau gila kau" is
Rafizi, which MAI got and the local raw split mid-sentence between Haziq and Farhan. The
last, the one-line 3:27:09 interjection, is unresolved -- the camera holds Rafizi through his
own surrounding turn and never cuts, so no frame in the window carries evidence.

The mechanism is visible in MAI's own output. Its chunk-6 cluster `c6s2` holds 22.5 minutes
and contains both Rafizi's reading and Farhan's question at 3:12:26, which is why chunk 6
produced two clusters that both scored as Rafizi (0.962 and 0.939) -- one of them is
contaminated, and a high voiceprint score on a 22-minute cluster cannot see a 15-second
passenger. So MAI's finer granularity is not uniform: `[3:11:35]` is a single 1,000-word turn
with three people's speech in it. What MAI does add is Farhan's backchannels, which the local
raw mostly drops.

**The eleven remaining disagreements, read off the video by a model.**

    python scripts/verify_speakers_video.py 0M5hweswMpE --candidates data/_ep62_todo11.json         --out data/_ep62_video_verdicts.json

`verify_speakers_video.py` muxes the downloaded video with the local audio and sends a
14-second clip per candidate to `gemini-3.8-flash`, with the same three clothing descriptions
used above. 0:11:50 was included as a control because the frames had already been read by
hand; it came back Farhan. Read the `seen` field and not just the verdict -- three of the
five "unclear" answers describe a mouth that is not moving, which eliminates one of the two
candidate speakers and settles the case.

Three labels in ep62's `raw.md` changed as a result, all Haziq to Rafizi: 0:55:54, 1:50:25
and 3:35:00. Each is a block sandwiched between two Rafizi blocks with the boundary falling
mid-sentence, so the local diarizer had invented a boundary rather than heard a speaker
change. The other eight were not applied. Two carry no evidence (a two-shot, and a stamp
still out after the retime), one was not a real disagreement, and five are long blocks where
the clip only covers the head -- 0:36:24 holds Rafizi speaking and then Haziq replying inside
one block, which needs the turn cut and not the label changed.

Beyond those three labels, nothing has been adopted into `episodes/`.

**The third limit: diarization does not fit the gateway's timeout under load.** On 2026-09-10
every request of 15 or 30 minutes returned HTTP 408 after a fixed 122 seconds for four
hours, while a one-minute clip returned in 2 s. Probed apart: 5 minutes WITH diarization took
98 s; 15 minutes WITHOUT took 5 s. The gateway cuts at 120 s and the diarization sub-service
is the part too slow to fit. Nothing downstream uses MAI's per-request speaker ids (the
voiceprint join loses Farhan, and the split tool takes clusters from pyannote and its
reference from the camera), so the mode for the re-cut is:

    python scripts/transcribe_mai.py <video_id> --no-diarization

**The fourth limit: the bias-phrase context list caps at 50 items.** `bias_phrases()`
sends the show's cast plus every capitalised name from `fix_proper_nouns.py`'s corrections
map as recognition bias. That map only grows, and ep63 (2026-09-12) was the first new
transcription since it crossed 50 -- `HTTP 400: Context list cannot have more than 50
items`. Fixed by truncating to 50, with episode-specific `--extra-phrase` terms and the
core cast placed first so a corpus-wide correction is what gets dropped for budget, never
an episode's own bias term. Anything past ~50 corrections will keep losing the newest
entries silently unless this list is pruned or the API allows more.

**Building raw.md from MAI's words** (`mai_camera_raw.py epNN`, ENGINEERING_LOG 2.11): where an
episode has MAI words and a camera reference, this replaces the local-ASR text with MAI's and
labels every word from the camera at its own time; turns of three words or fewer keep MAI's
label, uncovered words fall back to it. It changes the words, so `verify_words_unchanged.py`
does not apply -- the guard is that the output's word sequence equals MAI's, and the file is
read before it is adopted. ep62 is the first episode written this way.

**The fallback is trusted only when it names a person (2026-09-12).** A new premiere is
transcribed `--no-diarization` (the Azure timeout, "the third limit" below), so MAI has no
voice cluster of its own and the fallback is the episode's current raw.md -- for a brand-new
episode, a collapsed pyannote run with only `Speaker 1`/`Speaker 2`. ep63 shipped with 24% of
its words on those placeholders even though the camera read Rafizi at the exact seconds
(the `[05:51] Cuma,` case). Three changes, all gated on the
fallback label matching `GENERIC` (`Speaker N` / `Speaker ?`), so an episode whose MAI turns
carry real names behaves exactly as before:

1. A short turn takes the camera's majority over its own words when the fallback is generic.
   Rule 1 protects a real short interjection from the on-screen face; a placeholder has no
   identity to protect.
2. A word the camera does not cover takes the camera majority of ITS OWN TURN when the
   fallback is generic and the camera saw the rest of the turn.
3. Where the camera saw none of the turn, `data/diar_<vid>_t055.json` (the nightly pyannote
   run) is the last fallback, CLAUDE.md rule 4's order -- but a cluster gets a name only if
   `DIAR_PURITY` (90%) of its camera-covered seconds carry one name over `DIAR_MIN_COVERED`
   (60 s). On ep63 that named 2 of 11 clusters (Rafizi 98.3% of 7,879 s; Sum Dek Joe 90.0% of
   983 s) and refused the rest, including Haziq's at 69%. The map is printed on every run.

ep63 after the three: 23,938 words, generic labels 24% -> 1.9%. The remaining 434 words are the
honest residue -- turns the camera never saw, in clusters the camera cannot vouch for.

**Four changes measured against the owner's hand edit of ep65 (2026-09-26).** The owner
corrected ep65's pipeline raw.md while watching the video, and `compare_owner_edit.py` scores
any build against that copy (`--out=` for a trial, `--exclude=<from>-<to>` for a span whose
reference label is itself in question). Each row is scored on top of the rows above it:

| change | wrong words (of 20,537) | owner speaker changes found |
|---|---|---|
| before | 621 | 139 of 270 |
| a pyannote second goes to the cluster holding most of it, named only if that cluster is | 612 | 150 |
| without MAI diarization, a MAI phrase takes one label, the camera's majority | 596 | 149 |
| cluster purity read on seconds wholly inside a segment | 595 | 146 |
| `CAMERA_LAG = 0.5`: a word is read against the camera half a second later | 544 | 159 |

1. The old `setdefault` over `int(a)..int(b)+1` gave a named cluster every second it touched,
   so an unnamed cluster's interjection took the named neighbour's name.
2. A MAI phrase edge sits at 268 of the owner's 270 speaker changes, so a camera cut inside a
   phrase is the camera lagging, not a new speaker. Gated on `cluster is None`: an episode
   whose MAI turns carry diarization is unchanged.
3. A segment's partial first and last seconds are where the camera still shows the previous
   speaker. ep65's Haziq cluster read 82.4% with them (refused) and 96.1% without (named).
   The 0.90 threshold is unchanged. ep63's Haziq cluster reads 88.1% and is still refused.
4. Swept on the step-1 build: 0 s 366 wrong words, 0.25 s 335, 0.5 s 308, 1 s 338, 1.5 s 400,
   2 s 478. Part of it is `camera_per_second` truncating each cut to the whole second.

Leave-one-out on the step-1 build with all four in place (28:10-30:50 left out, 308 wrong
words): reverting the purity change gives 402, the lag 366, the majority-cluster fix 354, the
phrase rule 341. `SHORT_TURN_WORDS` stays 3: at lag 0.5, 4 gives 325 and 8 gives 405.

The lag is the one change a second episode argues against, weakly. Against ep62's committed
raw.md (owner-read, 14 owner corrections, but built with no lag) the lag costs 20 words, 107 to
127. That reference agrees with a no-lag build by construction, so it cannot settle the lag;
the owner's next hand-edited episode can. The 2 s in `check_overlap_boundaries.py` and
`move_hanging_words.py` is a different rule (rule 7), which the owner confirmed 11 of 11, and
ep65 did not test it: those tools moved nothing on ep65.

Checked outside ep65: step 1 built with the old and the new code for ep53, ep26, ep62, ep61,
ep57 and ep49 breaks none of their recorded owner decisions, and keeps two more on ep62 and
one more on ep57.

The same episode also had an unenrolled guest. Its camera reference passed
`check_camera_reference.py` because the check compares the reference against raw.md's own
word shares, and raw.md had been BUILT from that reference -- circular. Haziq's "daripada
perspektif Jo" in the text was the signal; the gallery was rebuilt by reusing Sum Dek Joe's
30 face vectors from ep60's per-episode gallery (same guest, no bijection needed), and the
reference went from 2 speakers / 8,175 s to 3 speakers / 9,191 s, with unknown-face talking
time falling from the whole guest to 5 s. The gate's blind spot: an adopted raw.md can no
longer disagree with the reference it came from, so for adopted episodes the check has to be
run against the PRE-adoption raw (`data/_ep63_raw_before_adopt.md` here) or against the MAI
turn count for a label the gallery lacks.

Two guards came with it. A chunk file is reused only if its duration matches the plan --
chunk files are named by index and start, and a 30-minute plan once picked up a 15-minute
`chunk00` left by an earlier run, dropping 900-1800 s of ep61 without any check noticing. And
the verdict refuses a transcript whose last turn ends before 95% of the runtime or that has
more than 300 s between two turns, which is the hole the last-stamp check cannot see.

**A disputed digit is settled by counting witnesses before it goes to an ear (2026-09-12).**
raw.md has three independent ASR readings of every figure: MAI's words, the local-ASR raw
(`git show` of the pre-adoption file, or `data/_old_<tag>_raw.md`), and the YouTube caption
track in `audio/<vid>.*.vtt`, plus whatever arithmetic the speaker states in the sentence.
Two of three agreeing against the third, with the arithmetic on their side, is a decision,
not a guess; the fix goes into `fix_proper_nouns.py` anchored on the full phrase. ep48's
"RM2.05 kepada RM1.09" (MAI) became RM1.99 this way: the speaker says "turunkan 6 sen", the
local raw heard 1.99, the captions agree. Only a figure the witnesses split on goes to the
owner. Not yet a script; `check_figures.py` finds the candidates, the count is by hand.

**A third witness for a speaker label: `voice_witness.py` (2026-09-12).** The owner's rule is
that a label reaches their ear only when the tools split, and after MAI, the camera and the
camera-vouched clusters an episode still had 61 `Speaker ?` blocks and 46 disputed short
turns. The corpus voiceprint cannot be the third witness (its two cosine distributions
overlap across recordings). An episode-local one can: each named speaker's centroid is built
from THIS recording's camera-attested seconds (same room, same microphones), and every
unnamed window is scored against them. `--validate` holds out every third camera run and
measures the thing before it is trusted; on ep63, 358 windows: 8 s windows 100%, 1.6 s
windows 98.5% at score >= .55 and margin >= .20 and 100% at >= .60 / >= .30. Those are the
`--write` thresholds. Rafizi and Haziq sit close (centroid cosine .68) and the guest far
(.16-.31), so most of what it refuses is a Rafizi/Haziq call on a short window. ep63: 25
labels settled (24 `Speaker ?` blocks named, one short turn moved by a 2-of-3 vote), 37
blocks left as `Speaker ?`. CPU only, by design: the GPU belongs to the camera pass.

**Naming an unenrolled face without a bijection: match it across episodes (2026-09-12).**
`guest_gallery.py` names a face only when one unknown label meets one unknown talking
cluster. ep46 had two of each (Amir Sahmat, Wan Afiq), and ep50 was held because Wan Afiq is
a rotating host. The way out was the face embeddings themselves: ep46's second unknown
cluster matched ep50's only unknown talking cluster at max cosine 0.91 (a true same-face
match on this pipeline lands at 0.86-0.98, camera_speakers note 3), and ep50's host list
names exactly one unknown host, so that face is Wan Afiq in both episodes. With one of two
faces pinned, the other is Amir Sahmat by a two-to-two bijection, and the intro line
"Bersama saya, Afiq. Saya Amir Sahmat" confirms both are present. Frames were read at
0:07:58, 0:35:23, 1:19:23 and 1:34:12 to confirm the two clusters are two different men.
Both per-episode galleries carry this provenance. The general rule: a recurring guest or
rotating host needs a face match to an episode where they are already named, not a human
per episode; the unknown-cluster comparison above is the tool, and it should become a
`guest_gallery.py --match <other vid>` mode rather than a one-off.

**An owner ruling can now cut a fused MAI turn (2026-09-12).** ep53's gate refused the camera
build because MAI had fused Haziq's "Itu jelah kot." with Farhan's "Okey eh, okey." into one
turn, and the owner had ruled them apart. A `forced_labels.json` rule may carry
`split_at_words: true`: `mai_camera_raw.py` cuts the block at the rule's literal words before
relabelling, the words and what follows them go to `who`, what precedes keeps its label, both
halves keep the stamp, and the locator document is rebuilt per rule so a later rule cannot
write the fused turn back. Two gate defects surfaced with it: `check_owner_decisions.py`
now measures a two-word snippet's distance to each block's SPAN, not its stamp (after the
merge a Rafizi block stamped 2:18:42 holds words spoken at 2:19:13), and reports a residual
two-block ambiguity with the owner's name on one of them as kept, not as a mismatch.
`fold_hanging_fragments.py` no longer crashes on the `["Human resource", 1]` split form.

### Writing the interview files from segments

The shipping path for ep62 (2026-09-10) and for every episode after it; the whole-episode
rewrite in transcribe_episode.py remains for the older files. The source is raw.md itself: ep62's
raw.md is MAI's words under the camera's names (`mai_camera_raw.py`, ENGINEERING_LOG 2.11),
so the interview and `check_figures.py` read the same file.

    cp episodes/.../ep62/raw.md data/_ep62_rewrite_source.md
    python scripts/strip_filler_turns.py data/_ep62_rewrite_source.md --write
    python scripts/segment_episode.py ep62 --raw data/_ep62_rewrite_source.md --out data/_ep62_segments.json
    python scripts/rewrite_segments.py ep62 --only 10 21 26 --stage mixed --tries 1   # bake-off
    python scripts/rewrite_segments.py ep62 --instructions data/_ep62_rewrite/instructions.txt
    python scripts/rewrite_segments.py ep62 --write

`rewrite_segments.py` runs one segment at a time, measures each result (length 0.70-1.50 of
the input, Malay function-word density at least 0.80 of the input, every figure present with
small integers allowed as number words, the speaker set identical to the input's, no stamps,
headings or preamble), keeps a passing segment on disk and retries only the failures. The
English stage must LOSE Malay density (ceiling 0.30) or it did not translate; the Malay stage
must keep it. `--write` refuses while any segment of any stage has no accepted file.
`--instructions` appends owner facts to the prompt, such as ep62's two title corrections.

**The show's chapter list is not always in time order (ep65, 2026-09-26).** ep65's
description lists `02:19:06 Pengampunan...` last, after `02:46:50`. `segment_episode.py`
ends each chapter where the next LISTED one starts, so 2:19:06 to the end was segmented twice
and 3,712 words would have been rewritten twice. It now sorts the marks first. Check that the
segments' turn total equals raw.md's block count before any rewrite.

**Shipping mode since 2026-09-27: `--condense`, half length.** The owner read ep65 seg02 and
seg08 rewritten three ways and chose the shortest. `--condense` now appends
`HALF_LENGTH_INSTRUCTION`. GLM-5.3 still stops near 0.80 of the input, because the prompt's
"keep every claim" rule outranks the length target. In this mode `names_dropped` is printed but
not gated (ep65 seg12 lost `Kewangan`), so read it for every segment before `--write`.

**Fact check before the rewrite (2026-09-27).** `rewrite_segments.py` refuses the mixed stage
unless `data/raw_fact_checks.json` holds raw.md's current sha256, written by
`check_raw_facts.py <tag> --record`. It also refuses a segment whose turns are no longer in
raw.md, which is what happened to ep65's seg02 after the owner's `Tan Sri-` correction.
Measured on ep65's pipeline raw.md against the owner's hand edit: 13 of 16 entity corrections
flagged. The three misses were lowercase (`reset`, `refund`, `oi`). A GLM pass that reads each
segment for these was tried and not measured, because NVIDIA returned HTTP 504 on every call.

**Free GLM needs rounds, and has a daily cap (ep16, 2026-09-23/24).** `z-ai/glm-5.2:free`
returned HTTP 429 on most calls at busy hours, but every text it did return passed the gate.
Re-run the same command in a loop with a pause of 90-120 s; accepted segments are cached, so
each round retries only what is missing. Once `free-models-per-day` appears in a report, stop:
the cap resets at 00:00 UTC (08:00 MYT). One episode of about 16 segments fits in one day.

**GLM-5.3 on NVIDIA, reasoning low, is the rewrite engine (ep00, 2026-09-24/25; the owner made
it the default on 2026-09-25 after reading ep00's output).** `--model "nvidia:z-ai/glm-5.3@low"`. The NVIDIA free tier shows only
a 40 requests/minute limit on the account page, with no credit counter. GLM-5.3 reasons by
default there: one segment's three stages took 19 min and the English stage hit HTTP 504 twice.
`@low` sends `reasoning_effort: "low"` and the same segment took 2 min 49 s with every gate
passed; `"none"`, `enable_thinking: false` and `thinking.disabled` are all ignored. ep00's 33
files took about 3.5 min each. The two English figure failures were renderings (`20 ribu` as
`20,000`, `12.30` as `12:30`) and were accepted by hand.

**Local models on this PC cannot do the rewrite (measured 2026-09-24).** RTX 2070 8 GB, Ryzen
3700X, 32 GB DDR4, LM Studio 0.4.25 (`rewrite_bakeoff.call_lmstudio`, port 1234 or
`LOCAL_LLM_URL`). GLM-4.7-Flash (31B MoE, 18.3 GB): 5-8 tokens/s, because LM Studio's strict
VRAM cap put only 14 of 47 layers on the GPU even with experts moved to RAM; one mixed stage ran
33 min and never finished. Gemma 4 12B: 11 tokens/s but kept reasoning with it switched off, 28
min per segment. Gemma 4 26B-A4B: the mixed stage lost spoken Malay (gate 0.72). Ternary Bonsai 2
27B (PrismML's llama.cpp fork, whole model on the GPU, 13.7 tokens/s): copied the mixed stage
word for word and did not translate the ms stage. All deleted.

**Stopping a background loop does not stop its Python child.** On 2026-09-24 a stopped
Gemini retry loop started another round and wrote into `data/_ep00_rewrite` beside the GLM-5.3
run. It produced only 429s, so no text was mixed in. Before a new run on the same work folder,
list `Get-CimInstance Win32_Process -Filter "Name like 'python%'"` and read each segment
report's `model` field.

**agy is not a rewrite engine (measured 2026-09-23).** `rewrite_bakeoff.call_agy` runs
Google's Antigravity CLI from an empty temp dir, text only. Sonnet 4.6 inside agy passed two
short segments, then moved long ones to formal Malay (`ini`, `itu`, `sahaja` for `ni`, `tu`,
`je`), which fails the Malay gate at 0.59-0.81. The free Starter quota ran out after about 20
calls. Gemini 3.8 Flash failed one of two.

**Owner rulings for the interview stage (2026-09-23).** A speaker's self-corrected false
start may drop ("500 eh 100000" becomes "100,000"). The figure gate still fails it, so accept
that segment by hand with a reason in its report after reading the passage. `--write` groups
figures of five digits and up with commas; four-digit numbers stay bare because they may be
years. The gates strip commas before comparing.

**A claim check on the mixed stage (2026-09-23, `jev_claim_check.py`).** The measures above
count length, Malay words, figures and labels. None of them sees a CLAIM that changed: a
sentence moved to the wrong speaker, an opinion nobody gave, an argument left out. Jev,
TypeSafe's decision model, answers three yes/no questions per segment in one call, with the
model pinned to `jev-1.13.0`. A score of 0.5 or more on any question fails the gate. The
segment gets one re-rewrite, and a second flag is accepted and marked `JEV FLAG: read it`,
because Jev is a flag for a person, never a verdict. A Jev error is recorded and never
blocks a rewrite. The threshold comes from `--controls`, which damages each rewrite on
purpose. On ep01:bakar's 8 segments, no real rewrite scored above 0.35. No damaged copy
scored below 0.75 on its own question: an invented sentence, two speakers swapped, a third
cut, one turn moved, one turn removed. Cost: about $0.0002 per segment. Jev is weak at
numbers and counting, so figures stay with `check_figures.py`. Needs `TYPESAFE_API_KEY`.

`--published` runs the same check on the published interview.md, for episodes rewritten
whole before segments existed. It cuts raw.md with `segment_episode.segment()`, finds each
cut in interview.md by the segment's first 15 words, and puts the raw side through the same
`clean_body()` the published file got. Without that last step, a slip-in drop that
`clean_interview.py` makes on purpose read as a dropped claim (ep01:bakar, `Kenapa 3 bulan?`).

**What the first corpus-wide run found (2026-09-23).** 612 of 1,153 published segments were
flagged, and a plain word count, with no model involved, explains most of them. 43 of 71
published interview.md files hold under 80% of the words in their raw.md after the same
cleaning, and 13 hold under 60%; ep16:berhenti holds 40%. The mixed gate's floor is 70%. Ten
of those 13 were rewritten whole in the 2026-09-17 regeneration (`be7555b`), which never
passed through the segment gate. ep16, ep44 and ep58 were not in it, and where their short
files came from is not yet traced. Every segment below 60% of its raw words was
flagged "dropped", so Jev agrees with the count. Among segments whose length is intact, 29%
were flagged, which is too many to be a review queue until the length problem is fixed.

**The published interview reads like newspaper copy** (owner's rule, 2026-09-10;
`clean_interview.py`, applied inside `--write` and runnable on any episode). Three closed-lexicon
edits: a turn that is only an acknowledgement, grunt or laugh is dropped ("Ya.", "Okey.",
"Hmm."; "2.3 billion." and "Koperasi?" carry information and stay); filler tokens are removed
inside a turn ("Uh,", "Um.", "Aaa", "Eh,") with the next word capitalised when the filler opened
the sentence; a speaker's consecutive turns become one paragraph (`merge_adjacent_turns.py`).
A fourth edit removes a SLIP-IN: a turn of three words or fewer from another speaker
sandwiched inside one speaker's turns, dropped when that speaker was mid-sentence or the words
are all echoed around it ("Balik kepada cerita." / "Haziq: Perumahan." / "Cerita perumahan
lah."); a short question after a finished sentence stays. Every removed word must be in the
lexicons or be a dropped slip-in, and the rest is asserted identical. On ep62's first output:
1,100 turns -> 252, 49 retort turns, 65 slip-ins, 678 filler words. The owner's read then
showed one "slip-in" was a LABEL error -- "Perumahan." ended Haziq's own sentence, which the
camera had given to Rafizi -- so the rule cleans the prose but cannot fix attribution; the
owner's ear does that (`--show-slips` prints every one for that read). `clean_body()` is the
only place these drops and joins happen. `rewrite_segments.py --write` and the whole-episode
path in `transcribe_episode.py` both run it.

**The prompt does not ask the model to drop or join turns (2026-09-23).** It used to, and point 5
of the same prompt said "Do not condense multiple turns into one", so the two rules disagreed.
Tested on ep62 segment 10: asked to drop and join, GLM 5.2 dropped Rafizi's one-word "4.1." (a
real figure, RMK3's 4.1 billion) in 4 of 4 runs. With the drop-and-join sentence removed it
kept it in 3 of 3, and Sonnet 5 and gemini-flash-lite were unchanged on segments 3, 10 and 20.
The figures gate caught every drop, so nothing shipped; each one only cost a retry. The same
audit removed two self-checks from the prompt ("count the Malay function words, reach 80%",
"at least 70% of the input's length"). A model cannot count reliably, and the gates in
`rewrite_segments.py` measure both.

**Sonnet 5 was the default of `rewrite_segments.py` from 2026-09-23 to 2026-09-25**, when
`nvidia:z-ai/glm-5.3@low` replaced it. On the same three segments,
all three stages, Haiku 4.5 failed the gate 3 times in 9 calls and Sonnet 5 once. Haiku's
failures: one more real figure lost ("2004"), text before the first speaker label, and
`Speaker ?` / `Multiple speakers` translated into `Pembicara ?` / `Pelbagai pembicara` in the
Malay stage. Haiku also took 44-270 s a call against Sonnet's 14-50 s. Sonnet's one failure was
the two false starts "20" and "99", which every model dropped and `--accept-figures` exists for.
Metadata extraction stays at `--effort low`: `medium` raised chapter coverage on one of three
episodes (ep46, 5/9 -> 7/9) and left ep53 and ep57 unchanged, one sample each.

**raw.md is the verbatim layer, minus grunts.** `strip_filler_turns.py` runs on raw.md too
(ep62: 1,689 -> 1,145 blocks, all 27,903 content words unchanged): the owner's standing rule
is that grunts, laughs and retorts that add nothing leave even the verbatim file. Answers stay
-- its lexicon has no "Ya", "Okey" or "Betul".

**What ep62 measured (ENGINEERING_LOG 2.12).** Model: Sonnet, at about $0.10 a segment with
lib_claude_rewrite's flags; gemini-flash-lite passed every gate by copying the input 99%
word-for-word and was dropped, Haiku translated the Malay away. 78 segment outputs, all
accepted: 60 on the first try, 9 on a retry, 9 by hand after a person read the printed
figure context (a self-correction, a false start, "tahun 60-an" written as "the 1960s").
Four segments were refused twice because the raw carried a garbled figure and the model
resolved it by guessing a digit; each went back to the owner's ear and raw.md was fixed first.
A guessed figure never passes.

**Why the filler strip is a step and not a regex.** MAI transcribes the backchannels the
local ASR drops, so 527 of ep62's 1,613 merged turns are one grunt each and 426 of those are
Haziq's. They belong in a raw transcript and they are noise in a rewrite source, where they
cut a speaker's argument into a dozen pieces. `strip_filler_turns.py` drops a turn only when
EVERY token in it is in a closed lexicon of vocalisations, so an inline `Uh,` inside a real
sentence is untouched and `Ya`, `Okey`, `Betul` and `Yes` survive as the answers they are. It
counts every non-lexicon word before and after and refuses to write unless the two multisets
match.

**Why segments.** Every cheap model rejected for the rewrite stage failed on length, not on
comprehension: Haiku dropped about half a translation, a local Sailor2 truncated 32% and
invented a claim, Gemini finished 73-82%. At about 1,200 words none of that appears, and a
segment that fails its gate can be retried alone instead of re-running three hours of text.
Boundaries come from the show's own chapter marks in the YouTube description, with long
chapters re-cut at turn boundaries; ep62 gives 29 segments.

**Why a merged transcript.** MAI-Transcribe-2 beats the local ASR on text, turn granularity
and timing, and loses the third host: `Farhan (Pa'an)` gets 94 words from MAI against 279
from the local ASR, and the camera backs the local ASR 8 times out of 10.
`merge_mai_local_labels.py` keeps MAI's words and transplants Farhan's label where the local
raw's words match, matching on words rather than time spans and anchoring the video-verified
regions on a phrase rather than a timestamp.

**What the bake-off found.** `gemini-flash-lite-latest` kept every figure and all the Malay
on all three segments in 6 seconds each; Sonnet kept 17 of 24 figures on one of them, because
it polishes hardest and polishing is what drops a repeated number; `gemini-3.5-flash` lost
figures on two of three; OpenRouter's free `nemotron-3.5-lightning` translated the Malay into
English wholesale (density 0.05), kept 2 figures of 24 and dropped a speaker. Read
ENGINEERING_LOG 1.48 before choosing, because the trade-off is not "flash-lite wins" -- it is
nearly a verbatim copy, so it passes a completeness gate by editing very little.

**Azure Foundry cannot serve text models on the Speech key alone.** It returns
`DeploymentNotFound` until a model is deployed in the portal, so the credit that expires
around 2026-10-07 is unavailable to this stage until then.

### Reading the speaker off the camera

`scripts/camera_speakers.py` builds a speaker reference from the video instead of from
audio. The show cuts to whoever is talking, so the camera is an observer of the answer that
no audio model can be confounded with. Three MIT models do the work: LR-ASD asks whether the
visible mouth matches the audio, YuNet plus SFace ask whose face it is, and PySceneDetect
finds the shot boundaries. Five stages, each resumable: `census`, `cluster`, `gallery`,
`run`, `reference`.

The output is an RTTM plus a **UEM**, and the UEM carries as much information as the RTTM. A
camera-derived reference is certain in some places and blind in others, so scoring a
diarizer where the reference has no opinion measures noise. Report UEM coverage next to any
DER computed against it -- 88% on ep62.

`cluster` stops and writes a contact sheet for a human to look at. Naming a face is the one
step with no independent check. The sentence here used to call "a speaker is never inferred
from text" a standing rule. Corrected 2026-09-26: that was a session's own conclusion from
four failed single-clue guesses, never an owner ruling. The owner asked on 2026-09-25 for a
whole-passage text reading, measured blind against the camera and against their own
corrected ep65, before it is either used or ruled out.

Four defects found while building it, each of which yields a plausible wrong answer rather
than an error:

1. **`-ss` before `-i` with `-c:v copy` desyncs every chunk.** Stream-copied video starts at
   the nearest keyframe before the requested time, then resets timestamps to zero, while
   re-encoded audio starts on time. Six frames of offset, fed to a lip-sync model. Fix:
   coarse-seek early, seek accurately on the output, re-encode.
2. **Eyewear splits one person into several face clusters.** Rafizi owns five of ep62's
   eight. Use a multi-vector gallery per person, matched on maximum similarity, not a
   centroid.
3. **No global similarity threshold separates these three.** Within-person minimum 0.35,
   cross-person maximum 0.40. Only nearest-neighbour argmax works.
4. **Greedy label mapping fabricates per-speaker results.** It reported MAI recalling 0% of
   Haziq when MAI had labelled 389 of his 457 seconds correctly. Use maximum-weight
   matching, as DER does.

The measured results are in `MODEL_LANDSCAPE.md`; the method and its validation are in
`ENGINEERING_LOG.md` 1.55.

**Guests, and running more than one episode.** Each episode's tracks go to their own
`data/_camera_tracks_<vid>/` (the `run` stage records the video it belongs to and refuses a
mismatch, because chunk files are named by offset only and a second episode into the same
directory used to reuse the first one's chunks). A face the gallery cannot name still counts
toward the overlap test, so a guest's crosstalk is no longer credited to a host. And
`scripts/guest_gallery.py <epNN>` names a guest's face without a person, only when exactly one
real label in `raw.md` is not in the gallery and one cluster of unidentified faces holds at
least 90% of the unidentified talking seconds; it writes `data/_face_gallery_<vid>.json`
(gitignored, biometric) for `reference --gallery`. ep60: 1,659 of 1,660 seconds, coverage 80%
-> 93%. Anything less clean stops and prints the clusters for a person. The full per-episode
procedure is at the top of `ATTRIBUTION_PASS.md`.

**Swapping in another engine's transcript: finding the owner's decisions in it.** A re-cut
keeps the words and moves only the labels, so every recorded decision could be found by its
text. A transcript from a DIFFERENT ENGINE cannot be: MAI spells the same speech
differently, splits it over more blocks, and keeps the fillers the local engine dropped.
Substring lookup located 6 of ep61's 44 recorded decisions. `scripts/lib_locate.py` matches
a passage on CHARACTERS instead, over a window wide enough for inserted fillers, so a Malay
affix is not a miss -- the decision reads "pandangan lain sikit" and MAI heard "Aku
berpandangan lain sikitlah", which shares no whole word with it.
`check_owner_decisions.py` now reports 36 preserved, 4 partly kept, 3 mismatched and 1 with
no text to search for, and prints where each match landed with its score, so a weak match is
visible instead of silent. The 4 partly kept are all the same benign shape: the local block
glued two speakers together and the candidate splits them, so the located span straddles the
cut.

**A stamp never locates a decision; it only breaks a tie between two equally good matches.**
Every one of ep61's 11 `Speaker ?` confirmations was recorded against a stamp 3 to 21 s away
from its own words. The frame at the stamp showed Rafizi in all 11 of them. At the words'
real time the camera shows Rafizi in 9 and Haziq in 2 (04:46 belongs to words at 05:05;
06:52 to words at 07:08). Nine were right for the wrong reason: ep61 is 86% Rafizi, so a
frame sampled 20 s away usually still lands on him. This is the defect that destroyed a
confirmed Farhan turn once, recorded in `data/speaker_adjudications.json` under
`ep61_farhan_restore`.

**The gold passage is carved out, not overwritten.** Where `speaker_ground_truth.json` holds
a passage the owner dictated from ear, `mai_camera_raw.py` splices the current raw.md's
blocks for it into the candidate verbatim and drops the candidate's own blocks for the same
speech; the seam is found by words, not by the clock, because the two files' stamps differ by
up to 26 s. ep61 needs it: the shot through that passage is a full-screen graphic, so the
camera inverts it and gives Haziq's "Baik YB, cuti panjang YB buat apa?" to Rafizi and
Rafizi's answer to Haziq. 14 current blocks replace 79 candidate blocks, 356 MAI words. The
reviewed name corrections run BEFORE the splice, so the owner's bytes are never rewritten,
and the checker tests containment rather than list equality, which leaves a re-cut on either
side of the region free to differ.

**The owner outranks the camera, and the ruling has to outlive the rebuild.**
`data/forced_labels.json` holds the turns where a recorded decision and the camera disagree
and the owner has ruled for their own label. `mai_camera_raw.py` applies them last, locates
each by its words, and stops the run if one cannot be found or spans more than three blocks,
so a ruling can never be silently skipped. ep61 has two, both from the drift above; the owner
was shown the frame at the stamp and the camera at the words and kept Rafizi. The cost is
visible and small: DER 2.3% -> 2.4%.

ep61's candidate against the camera: JER 55.5% -> 13.8%, Haziq recall 66% -> 90%, seconds
under the wrong name 552 -> 74, blocks holding more than one speaker 101 of 252 -> 59 of
2,425. Adopted on 2026-09-10.

### Known limitations

- **The gap is in block cutting, and on ep62 it is now closed.** Measured against the camera
  reference, the pipeline's unaided output recovered 67% of Haziq's speaking time while
  pyannote's own clusters recovered 85% -- eighteen points lost after diarization, in the
  step that turns clusters into transcript blocks, not in the diarizer and not in naming.
  `scripts/split_mixed_blocks.py` re-cuts those blocks and ep62 now sits at 92%.
  **The other 67 episodes have not been done, and the method has been validated on one
  episode only.** Corpus-level DER hides all of this: Rafizi holds 95.5% of ep62's audio,
  and a continuously tiled transcript scores 0% missed by construction. Read confusion.

- **Turn-level attribution is not solved, and it is the largest open defect.** 341
  published turns of 400+ words across 63 episodes sit under one label, and every checker
  in the suite is green while that is true, because no check reads whether a turn holds two
  voices. The diarizer fails in both directions -- long monologues collapse into one label,
  short interjections get absorbed by whoever is next to them -- so no blanket correction
  works and the labels cannot be used as evidence about themselves.

  `scripts/sense_speakers.py` is the proof of concept, measured against the owner's
  hand-written gold passage in `data/speaker_ground_truth.json`: **83% against `raw.md`'s
  61%, with Rafizi recall lifted from 2/9 to 7/9 and boundary recall from 50% to 100%**.
  It takes boundaries from caption word gaps rather than the diarizer, and names each
  segment on a two-ended voice axis seeded by the `YB` vocative. Every attempt, including
  the two that scored at or below the baseline, is recorded in
  `data/diarization_bakeoff.json`, and
  [ENGINEERING_LOG.md 1.43](ENGINEERING_LOG.md#143-sensing-the-speaker-instead-of-trusting-the-label-measured-against-gold-data)
  has the reasoning.

  **It is not ready to rewrite anything.** The evidence is one passage of 18 turns, so a
  single turn is 5.6%, and the parameters were tuned on it (untuned: 78%). A second
  hand-checked passage is the blocking input. Two limits are already known and measured:
  sub-second backchannels are unreachable, because the embedder needs 0.6s and the three
  turns it misses are the three shortest; and the co-host label cannot seed a reference,
  because 6 of the 8 blocks ep61's `raw.md` calls Haziq measure as Rafizi.


- **5 episodes have a cast member present with no speaker label**: three guests
  (ep02, ep05, ep08) and `Farhan (Pa'an)` in ep39 and ep55. This read 20 until the
  speaker-attribution work of 1.35-1.38, and then read 35 too high for a different reason
  -- `RAW_LABEL` excluded parentheses from the name class, so it could not see
  `Farhan (Pa'an)` in any of the 35 episodes that label him that way (1.39). Coarse blocks absorb
  short interjections, so the speech ends up inside someone else's turn and the leftover
  generic clusters are 0.0-2.4 minutes, too short to carry it. The `hosts` field records
  these people anyway (see the naming convention above); what is still missing is the
  block-level attribution, which needs blocks split at speaker boundaries as ep45's were
  (1.31). **Careful if automating: ep60 contains two different Farhans** -- the co-host,
  and a politician described as "anak emas Dato' Seri Anwar".
- **`interview*.md` speaker labels are still generic in 18 episodes.** 121 turns across
  ep03, ep16, ep37, ep51, ep54 and ep56 were named from `raw.md` by
  `name_published_placeholders.py` (1.40), which renames a `Speaker N` only when a literal
  trace of the turn's opening clause confirms the match at 80%. Role labels (`Host`,
  `Interviewer`, `Hos`) are deliberately out of its scope: measured, they sit at 55-76%
  agreement per turn, so they need the rewrite re-run with the names in the prompt rather
  than a better matcher. The pre-1.40 figure was 2,836 labels across 26 episodes:
  `Host` 963, `Speaker 2` 817, `Speaker 1` 418, `Speaker 3` 216, `Interviewer` 209,
  `Moderator` 83, `Hos` 73, `Speaker` 57. Re-measured with `label_drift_audit.py` on
  2026-08-28; the previous figure of 1,366 across 35 episodes predated the re-cuts.
  9 of those episodes ship a numbered diarizer cluster id straight to the reader
  (`published-placeholder`, 1.39), ep54 for all 97 of its turns.
  The rewrite stage invented these where `raw.md` already carries a real name, so the
  information exists -- it just was not carried across. 558 were resolved on 2026-08-28
  in the six episodes where the mapping was forced (exactly one non-Rafizi speaker in
  `raw.md`, that speaker a known recurring host, and no `Speaker N` among the generics).
  The rest need a person, because two or more candidates fit and guessing would put a
  named person on words that may not be theirs.

  A generic label is vague rather than wrong, which is why this is a limitation and not
  a bug. `scripts/label_drift_audit.py` lists the mismatches, and
  [ENGINEERING_LOG.md 1.30](ENGINEERING_LOG.md#130-why-the-obvious-generic-label-rule-is-wrong)
  records the rule that looks right and is not.


- **Fixed, 2026-08-24**: episodes transcribed via `--engine local` previously had
  no speaker diarization at all: `raw.md` was one undifferentiated stream of
  text, and the rewrite stage had to infer who's speaking purely from context.
  **Confirmed as a real, not just theoretical, problem** before the fix: a
  Gemini audio spot-check on one episode's opening exchange found the
  model-inferred rewrite had folded a real Rafizi Ramli line into a generic
  "Podcast Host" turn: an actual misattributed quote. A cheaper alternative,
  asking Gemini for just a chronological speaker-change list (not a full
  transcript) to merge onto existing local-ASR text, was tried and
  abandoned: this show's speakers change every few seconds, so a speaker-only
  pass needs roughly as many continuation rounds as a full transcript would,
  with no real quota saving.

  **The actual fix**: `scripts/lib_diarization.py`, a pyannote.audio pipeline
  run as a separate acoustic pass on the same audio local ASR already
  transcribes: pure voice-embedding clustering, no LLM involved at all, so
  it's immune to every content-based failure mode found elsewhere in this doc
  (PROHIBITED_CONTENT blocks, fallback-model degradation, and the per-run
  label inconsistency confirmed directly on ep13/ep39, where the same real
  speaker got a different invented name in different Gemini attempts). Output
  is anonymous "Speaker N" labels (numbered by first appearance, consistent
  within an episode since they're real voice clusters). It still needs a
  manual naming pass afterward, same as Gemini's own generic labels do, just
  without the added risk of the label itself drifting between attempts.

  **Chunk-level labeling was itself a real bug, fixed 2026-08-24**: originally
  each up-to-28-second VAD chunk from `lib_local_asr.py` was labeled with
  whichever diarized speaker had the most time overlap with the *whole*
  chunk, so a short interjection from a second speaker inside a longer
  chunk was silently swallowed into the dominant speaker's line, with zero
  trace in the output. Confirmed as a real, not just theoretical, problem via
  direct audio listening on ep30: a 25-second span containing two short
  interjections from a third voice ("Farhan") produced only one Rafizi-Ramli
  line, the interjections nowhere in the transcript. Root cause was NOT
  pyannote's clustering (it correctly detects the second voice at the right
  moments); it was throwing away that resolution by labeling per chunk
  instead of per word.

  Considered and rejected: (1) NVIDIA NeMo / the `whisper-diarization`
  GitHub project's full pipeline: its diarization module still doesn't
  handle overlapping speech either (same gap as pyannote), and re-running ASR
  through `faster-whisper` would mean converting the existing
  `mesolitica/malaysian-whisper-medium-v2` checkpoint to CTranslate2 format,
  a bigger lift for no proven gain over what's already working. (2)
  `ctc-forced-aligner` (the PyPI package `whisper-diarization` itself uses for
  precise word timing): needs a native C++ extension that fails to build on
  this Windows/Python 3.14 setup (`error LNK2001: unresolved external symbol
  PyInit_align_ops`), no prebuilt wheel exists for this platform.

  **What shipped instead**: `scripts/lib_forced_align.py`, using torchaudio's
  official MMS forced-aligner (`torchaudio.pipelines.MMS_FA`): pure Python,
  no native extension, already an implicit dependency via pyannote.audio.
  Each VAD chunk is still transcribed once as a whole (preserves ASR
  quality/context), then the transcript is force-aligned word-by-word against
  that chunk's audio, and each word gets its own speaker label via
  `lib_diarization.label_for_range`. Consecutive same-speaker words are
  grouped back into lines. Numbers and punctuation-only tokens (e.g.
  "RM11,000") have no letters in the aligner's label set (a-z plus apostrophe)
  and get their timestamps interpolated from neighboring aligned words.
  **Needs torchaudio's CUDA build installed explicitly**: the default PyPI
  torchaudio wheel is CPU-only, version-mismatched against torch's own CUDA
  build, and only registers a CPU kernel for the `forced_align` op: moving
  the model to CUDA against that wheel fails outright, not just slower.
  Fixed via `pip install torchaudio==<ver>+cu130 --index-url
  https://download.pytorch.org/whl/cu130` (matching torch's own cu130 build).
  Confirmed on the ep13 redo: ~21s/chunk on the wrong (CPU) wheel vs.
  ~4.5s/chunk after installing the matching CUDA build, a real difference at
  full-episode scale (339 chunks), even though it's still slower than the
  pre-forced-alignment baseline (~2s/chunk) since alignment is genuine added
  work, just a cheap single feed-forward pass rather than autoregressive
  generation.

  **CTC's own length constraint can crash this outright**: forced alignment
  requires the target token sequence to be no longer than the audio's frame
  count. Violated directly on the ep13 redo when one ASR chunk degenerated
  into a repetition-loop hallucination (~140k chars repeated, producing an
  889-token target against a 114-frame emission): `RuntimeError: targets
  length is too long for CTC`, crashing the whole run partway through instead
  of just that one chunk. Fixed in `lib_forced_align.align_words`: on that
  RuntimeError, fall back to one span covering the whole chunk (same as the
  old chunk-level behavior) so the pathological chunk's garbage text still
  comes through and `qa_check.py`'s existing repetition-loop detector can
  flag it exactly as before, instead of the whole redo dying.

  **Residual limitation, not fully solved**: word-level attribution fixed the
  *invisibility* problem (a second speaker's words now reliably show up
  labeled differently), but pyannote's own turn-boundary placement is still
  off by a few hundred milliseconds on split-second interjections, so a word
  or two right at a speaker-change boundary can still land on the wrong
  label. This is close to the practical limit for any turn-based acoustic
  diarizer on genuinely fast back-and-forth speech, not something a
  different tool would cleanly fix, confirmed by testing both the old
  chunk-level and new word-level approaches side by side on the same ep30
  clip. Worth re-checking by ear on episodes with heavy rapid-fire banter,
  same as any diarization output. **Validated as a real net improvement, not
  just a synthetic-test win**: on ep13's full redo, a passage the old
  chunk-level approach had flattened entirely into one continuous "Rafizi
  Ramli" block turned out, on the repo owner's direct audio confirmation, to
  be genuine fast back-and-forth between Rafizi and Haziq, exactly the class
  of previously-invisible content this fix targets.

  Also fixed in the same pass, discovered while testing this:
  - The local ASR call didn't pin `language`/`task` in `generate_kwargs`, so
    this multilingual Whisper checkpoint's auto-detection occasionally
    misfired on short/atypical chunks and silently produced an English
    translation instead of a Malay transcription (confirmed directly on the
    same ep30 test clip). Now pinned to `language="ms", task="transcribe"`.
  - VAD chunking splits audio every ~28s regardless of speaker continuity, so
    one uninterrupted speaker turn spanning multiple chunks used to produce
    several separate output lines with no new information in the extra
    timestamps (confirmed on ep13: 442 lines collapsed to 131 after fixing
    this). `transcribe_raw_local` now merges consecutive same-speaker lines
    across chunk boundaries before writing `raw.md`.

  **ep13 naming pass done, 2026-08-24, redone after the above fixes**: sample
  clips extracted per speaker and confirmed by the repo owner by ear
  (`Speaker 1` = Rafizi Ramli; `Speaker 2` = Haziq Azfar) before applying the
  labels to
  `raw.md` and the three `interview*.md` rewrites: confirm-before-applying
  this way avoids guessing from turn count or content alone.

  Requires a Hugging Face token with access to 3 gated repos (accept terms
  for all three, or the pipeline 403s partway through loading):
  `pyannote/segmentation-3.0`, `pyannote/speaker-diarization-3.1`, and
  `pyannote/speaker-diarization-community-1` (a transitive dependency not
  listed on the model card). **Gated-access propagation lag confirmed
  directly**: the HuggingFace web UI and the `model_info()` API both reported
  access as granted well before the actual file-download (resolve) endpoint
  stopped 403ing; don't trust either of those as proof the pipeline will
  actually load; the only real test is trying the download.
- **Proper nouns are checked by corpus comparison, not by a dictionary.**
  `scripts/check_proper_nouns.py` reports names whose spelling is a near-miss of a form
  used consistently elsewhere, and names the episode's own captions never heard. It
  found and fixed 82 mangled mentions of six public figures on 2026-08-28. Roughly 250
  candidates remain queued for a human.

  An earlier plan here was to validate against Dewan Bahasa dan Pustaka's PRPM
  dictionary via the `malaya` library's `dictionary.keyword_dbp()`. **That was dropped,
  for two measured reasons.** The speech is colloquial and code-switched, so a
  standard-Malay check flags well over 100,000 legitimate tokens (`kan` appears 19,493
  times in the corpus, `tak` 18,961, `lah` 14,042). And it fails on the case that
  matters most: `Cincong`, which concealed a sitting MP's name for months, *is* a valid
  Malay word for fuss, so a dictionary would have marked it correct. A dictionary
  answers "is this a word", and the question here is "is this the right person's name"
  (ENGINEERING_LOG.md 1.28).
- Crosstalk-driven entity errors are possible in any Whisper-family transcription,
  local or cloud.
- Gemini's free-tier quota is unreliable for raw transcription on episodes longer
  than roughly an hour in a single call: use `--engine local` for those.
- **The published files can carry the rewrite's own commentary, and no check reads for
  it.** Four instances found by hand on 2026-08-29, all in `interview-en.md`: ep34's
  `RM172,000 [per classroom actually higher -- wait]`, ep53's `[sic -- should be a
  population figure, not currency]`, ep16's `[translator's note: sentence unclear in
  source]`, and ep28's `[Note: he was asked for his view, and he turned the question back
  around.]`. Each was the model reasoning out loud inside text attributed to a named
  speaker. Two of them were even RIGHT about the underlying defect, which is the point:
  the aside was doing the job a check should do.

  A signature is calibrated but not yet wired in. Bracketed spans are a legitimate house
  convention -- 518 of them across the published files are translation glosses
  (`[party]`, `[million]`, `Teguran [a reprimand/note]`) -- so the pattern must key on
  meta-commentary vocabulary (`sic`, `translator`, `wait`, `unclear`, `actually`,
  `probably`, `^Note:`), not on brackets. That vocabulary matches exactly the four
  instances above and nothing else in the corpus. `should be` was tried and dropped: it
  hits ep50's legitimate `who [should be appointed]`.
- **Whisper's subscribe-boilerplate hallucination: FIXED, 142 spans across 98 files**
  (`scripts/remove_asr_boilerplate.py`). The sentence is `Sila berasa bebas untuk
  menyukai, melanggan, maju dan memberi ganjaran untuk menyokong lajur Der Spiegel dan
  Diandian`, a Malay rendering of the Chinese YouTube-subtitle boilerplate that
  mesolitica's Whisper inherited from its training data (Mingjing / 明镜 is Der Spiegel;
  Diandian / 点点 is the other channel). Nobody on this podcast says it. It was found from
  the other end: ep28's published text carried `[aside about liking, subscribing and
  supporting Der Spiegel and Diandian omitted from context]`, the rewrite noticing the
  hallucination and writing a note about it instead of dropping it.

  Deletion was justified BEFORE it was done, not after. `_boilerplate_probe.py` took the
  words either side of each occurrence in raw and asked whether both sides land inside one
  window of the episode's YouTube caption track. 41 of 41 checkable occurrences: yes, zero
  counter-examples, so the hallucination was inserted beside real speech and never
  displaced any. ep05's and ep12's 6 occurrences have no caption file on disk and are the
  unverified remainder. An earlier version of that probe scored the two sides
  independently and measured the distance between them; it reported 5 replacements, all of
  which were the scorer landing 33-106 words early. Contiguity inside ONE window has no
  such failure mode.

  **Four self-inflicted bugs, each caught by a check rather than by luck. This is the
  entry to read before writing another bulk text edit.**
  1. *Whole-file punctuation tidy.* `([.,]) ?\1+` -> `\1` collapses every `...` in a
     transcript into a single full stop. It would have damaged all 98 files, and a dry run
     would not have shown it, because a dry run only prints what it deletes. Repair is
     local to the join now.
  2. *`\s` matches newlines.* A `\s*` in the closing pattern let a span swallow the `\n\n`
     after it and weld the next speaker's block onto the previous turn. ep12, ep37, ep42
     and ep46 lost a paragraph break and qa_check went 0/68 -> 4/68 on buried turn
     markers. Every whitespace class in the patterns is `[ \t]` now.
  3. *Fixed-length trailing runs cut words in half.* A `{0,20}` tail landed inside `der`
     and left `r Spiegel and Diandian` in ep21. The pattern that needed it was deleted
     outright once a greedy body covered the same cases.
  4. *A survivor check keyed on the giveaway vocabulary is blind to fragments.* ep20's
     `Sila berasa bebas untuk menyukai,` carries no channel name, so the checker called
     the corpus clean while three fragments sat in it. `LEFTOVER` keys on the
     translationese lead-in instead.

  **The guard that makes it safe:** a span may be deleted only if every word in it comes
  from the hallucination's own lexicon. The boilerplate is built entirely from that list,
  so any span reaching into real speech is refused automatically -- including a
  half-eaten word. Complete spans must ALSO carry the giveaway vocabulary, since
  `dan ini untuk` is all lexicon and all real Malay.

  **What must NOT be deleted, and nearly was:** `Jangan lupa untuk melanggan` is real
  speech. The hosts plug Rafizi's own channel, and ep16 has Haziq joking about having to
  (`melanggan dan melanggan, celaka teruk`). It is also one of the hallucination's
  lead-ins, and every word of it is in the lexicon, so the guard cannot separate the two --
  only the sentence shape can. Lead-ins are split into `LEAD_SAFE` (translationese with no
  spoken equivalent) and `LEAD_RISKY` (genuinely spoken), and a fragment under a risky lead
  needs the hallucination's own comma list before it can go.

### Gemini cannot replace the camera pass, and the reason is block length (2026-09-11)

**The question, and why it mattered:** the camera reference costs about 3.5 hours of GPU per
episode, measured on ep57. Sixty-three episodes still need one, which is roughly nine days
of the machine running. One 10-minute window of ep62 came back 21 of 22 against the camera,
so a video model looked like it might replace all of it for hours instead of days.

**It does not.** `scripts/gemini_label_blocks.py` labelled 182 blocks across five episodes
that have a camera reference -- ep58, ep59, ep60, ep61, ep62, three 10-minute windows each.
Agreement with raw.md is 86%, with the camera 80%. Per episode it runs from 97% on ep58 down
to 77% on ep59, so the single ep62 window was the top of a wide spread, not a typical result.

**The split that settles it is block length:**

| words in the block | blocks | agrees with raw.md |
|---|---|---|
| 20 or more | 89 | 96% |
| 7 to 19 | 44 | 93% |
| 4 to 6 | 25 | 68% |
| 3 or fewer | 24 | 54% |

Long turns never needed help: MAI and the camera already agree on them. Short turns are
exactly where the camera is weakest -- pyannote's embedder has a 0.6 s floor, and the
sensing work scored 0 of 5 on short co-host calls -- and every open speaker question in this
repo lives there. On those the model is a coin flip. When it disagrees with raw.md the camera
backs raw.md 12 times and the model 6, so a dissent from it is twice as likely to be wrong as
right.

**A guess that did not survive the data, recorded because it was convincing:** the first
disagreements all had a low camera share, so it looked like the model was really finding
badly cut blocks that hold two speakers. Splitting by purity killed that -- blocks the camera
says hold one speaker throughout score 88%, mixed blocks 84%. Length explains the failures;
impurity does not.

**Two operational facts.** `gemini-3.8-flash` became unusable during the run: it hangs rather
than answering, timing out at 90 s on a one-word text prompt, while `gemini-3.5-flash`
replied in 22 s. A 503-only fallback therefore waits out the full timeout on every window,
which is why `ask()` now treats a hang as a fallback condition too. And the Files API still
answers "the file failed to be processed" for these clips, so a window goes inline and must
stay under 20 MB -- 10 minutes at 640 wide and 10 fps is about 9.5 MB.

**What the tool is still good for:** one named window and one disputed label, the way
`verify_speakers_video.py` settled 11 of ep62's, with the camera or a person holding the
other end. Numbers and method in `data/gemini_label_blocks_measured.txt`.

### `Speaker ?` was invisible to every checker, and three regexes are why (2026-09-11)

The corpus carried 33 `Speaker ?` blocks in raw.md and 114 in the published
interview files. `qa_check.py` reported 2 of 69 episodes flagged and neither was
for this. ep33 shipped 25 `Speaker ?` turns to the reader in `interview.md`, 32 in
`interview-en.md` and 12 in `interview-ms.md` while its own raw.md named all four
speakers and carried no unknowns at all.

Three separate patterns each walked past the label:

| pattern | file | why it missed |
|---|---|---|
| `RAW_LABEL` | `label_drift_audit.py` | character class `[\w '.()-]` has no `?` |
| `GENERIC` | `label_drift_audit.py` | `Speaker` alternative is anchored with `$` |
| `DERIVED_PLACEHOLDER_RE` | `check_published.py` | matches `Speaker \d+` only |

All three now accept it. `check_published.py` goes from 2 of 69 episodes flagged to
12.

**Correction, made the same day.** Calling all three a bug was too broad.
`speaker_adjudications.json:_fillers_note` says `Speaker ?` "raises no QA flag
(check_published.PLACEHOLDER_RE matches only NUMBERED clusters, deliberately)" --
the owner set ep53's 12 filler turns to it on the standing principle that substance
outranks per-fragment attribution, and not being flagged was the point. So the flag
now fires only where raw.md does NOT carry `Speaker ?` itself. Where raw carries
one, the published one is faithful passthrough of an acknowledged unknown; where
raw names everyone and the published file does not, the name was dropped. That is
the ep33 case and it is the one worth reporting. Same exclusion `generic-label`
already applied. published-placeholder therefore covers 9 episodes, not 10.

`check_owner_decisions.py` also needed teaching: a decision naming NO ONE (`null`,
or `Speaker ?`) has nothing for the gate to check, and asserting otherwise would
mean an unknown must STAY unknown. `_fillers_note` calls those entries
"Reversible", and the ep53 camera reference duly named three of the twelve -- and
showed the `Speaker 3` cluster they came from had mixed Haziq with Rafizi.

#### The caption track settles what reading cannot

`Speaker ?` looks like a speaker question and mostly is not. Read against the
episode's YouTube caption track at the block's stamp, the 33 raw blocks came apart
into three classes, recorded per block in `data/speaker_q_caption_resolved.json`:

  - **9 hold words nobody said.** `Saya boleh lihat.` appears 8 times in the corpus
    and never once from a named speaker: 7 as `Speaker ?` and 1 under an invented
    `Audience` label in ep00. It is the Whisper "I can see." hallucination on
    non-speech. At ep03 2:02:21 the caption is `[Muzik]`; at ep41 1:59:42 it is
    `minum [mendengus] air`.
  - **11 are one sentence split across two blocks.** The fragment finishes the
    sentence before it or starts the one after, and merging needs no name.
  - **13 stay unknown** on purpose. Four need the owner's ear, four are held because
    the fragment could be a real short turn, five are in blocked ep53.

#### Naming a published `Speaker ?` from raw.md: refused, 0 of 114

`name_published_placeholders.py` votes once per label, which is right for
`Speaker 1` (one voice by construction) and wrong for `Speaker ?` (a per-turn
marker). `name_published_unknowns.py` was written to resolve them one turn at a
time by literal trace, and it resolves none of them. That is the finding, not a
failure of the tool.

A trace proves the words are PRINTED inside a block carrying a name. It proves the
person said them only if the block holds one turn. On ep33, 11 published unknowns
traced into a single 13,857-character block labelled Rafizi, at offsets from 49% to
99%, while the median block in that file is 66 characters. The rewrite had split
that block into an alternating argument -- "More than that, more than that." against
"I disagree, I disagree." -- so the block is two people and its label names one.
Same lesson as `lib_locate.py`: a block label cannot locate a speaker inside the
block.

So ep33's published `Speaker ?` labels are the pipeline being honest, and
regenerating its interview files would not fix them. **The defect to fix is the
13,857-character raw block**, which is the `project_published_turn_collapse` class
and needs the owner's ear or a camera reference ep33 does not have.

### A camera reference can be confidently wrong: unenrolled guests (2026-09-11)

The face gallery holds the three regulars. A guest's face matches nobody, so the
pass hands his segments to the nearest gallery member, which is always Rafizi
because he is on screen most. The output looks completely normal.

ep33's full 152-minute pass produced 71% coverage, 400 segments and a well-formed
RTTM:

| | Rafizi | Wong Chen | Haziq | Farhan |
|---|---|---|---|---|
| raw.md | 70.9% of time | **18.3%** | 10.0% | 0.8% |
| reference | 93.8% | **0.0%** | 4.7% | 1.5% |

Wong Chen has 172 blocks and 20.1% of raw's words. Adopting that reference would
have put a named politician's words under Rafizi's name.

**DER was 11.9%, which passes. JER was 48.1%, against ep52's 16.3%.** This is the
DER trap documented under "Reading the camera off the video", hit from the other
direction: DER is dominated by whoever speaks most, so losing a speaker who holds a
fifth of the episode barely moves it.

Three references already on disk fail the same way, found by the new check and listed
with their blind speakers in `data/camera_reference_limits.json`:

    ep50   Wan Afiq                   11.5% of raw's words -> 0.0%
    ep52   Zaim Zulkifli 9.4%, Syuk 8.6%          -> 0.0% both
    ep55   four guests, 5.4-7.6% each             -> 0.0% all

ep52 is adopted and was checked: its raw.md still names both guests, 65 blocks each,
so the adoption kept raw's labels where the camera was blind and no damage was done.

**Enrollment works** -- this is not a flaw in the approach. ep60's guest Sum Dek Joe
is 15.3% of raw's words and 14.4% of the reference's time, and it passes.

#### The gate

`scripts/check_camera_reference.py` compares the CAST, not the timing: a speaker
holding at least 5% of raw's words must retain at least a fifth of that share in the
reference. Keyed on characters rather than seconds, because block durations come from
stamps and stamps drift. It says nothing about whether the boundaries are right, so
it is a gate before scoring and never a substitute for it.

Wired into the two places that would otherwise consume a bad reference silently:

  - `nightly_recut.py` gates the reference and skips the split dry run on failure.
  - `fold_hanging_fragments.py` refuses by default. Its condition 1 is "the camera
    covers NONE of the fragment's seconds", which a reference blind to a speaker
    makes trivially true for every fragment that person speaks -- so it would fold
    their words into whoever is on either side.

#### Consequence for the queue

**Check the cast before spending 2.5 hours of GPU on an episode with a guest.** ep36
was pulled from the queue on this basis before it started (guest Lee Chean Chung, 45
of 99 blocks). ep33 and ep36 both need the gallery rebuilt with their guest enrolled.

A bad run does not waste the GPU time: `data/_camera_tracks_<vid>/` keeps every face
track and mouth-sync score, so a corrected gallery can be re-matched against the
existing tracks without re-running the video stage.

#### `guest_gallery.py`: naming a guest without a human, when the bijection allows it

For a single guest whose face cluster holds at least 90% of the episode's
unidentified talking seconds, the guest can be named by a measurable bijection --
no visual identification needed. `scripts/guest_gallery.py epNN` does this and
writes a per-episode `data/_face_gallery_<vid>.json` (gitignored: face embeddings
are biometric data).

ep33 resolved this way (Wong Chen, 99% of 2,039 unidentified talking seconds) using
the tracks already cached from the rejected pass -- no new GPU. Re-matched reference:
Wong Chen 20.4% of time against raw's 20.1% of words, both within the gate's margin.
Adopted.

Two cases the bijection correctly refuses, both left open for a person:

  - **ep50's Wan Afiq is frontmatter-classified a host, not a guest** (he recurs in
    ep46 too), and the script refuses to auto-name any host regardless of match
    quality -- a wrong name here would corrupt every episode he appears in, not one.
  - **ep36 has zero cached tracks** (its GPU run was pulled before it started), so
    there is no cluster to match against yet; it still needs the full pass.

#### A single GPU means camera passes are never concurrent, and the failure is silent

The corpus has exactly one usable GPU (RTX 2070). Two `camera_speakers.py run`
processes started at once do not error cleanly -- they raced for the PO-token
server `yt_download.ensure_pot_server()` sets up for video downloads, and the
loser's yt-dlp call saw only storyboard formats from YouTube's `web_embedded`
client and failed with "Requested format is not available." It read exactly like
a transient YouTube block, not a local resource conflict.

This happened once, from a broken wait-loop: a malformed PowerShell one-liner
meant to gate ep36 behind ep41's completion errored on its first check, which
made the bash `while` loop exit immediately and start ep36 while ep41 still held
the GPU. ep41's own `camera_run` step failed 130.9 minutes in. The resume-safe
chunk cache (`if dest.exists(): continue` in `camera_speakers.py cmd_run`) limited
the real loss to the one in-flight chunk (~10 min), not the full run -- but the
lesson is the gate, not the recovery: **never chain a second GPU pass on anything
other than the first process's own log content.** `while ! grep -q "^[0-9:]+
finished:" <log>; do sleep 300; done` is bash-only and was already the pattern the
prior session used; a `Get-Process -Id` check added a second, needlessly fragile
path to the same answer.

#### Rule 9 closed ep52 and half of ep55, and the tool refused three correct answers first (2026-09-15)

`data/camera_reference_limits.json` listed ep52 and ep55 as blind references a gallery
merge could not fix, because their six guests are enrolled nowhere and
`guest_gallery.py`'s bijection needs exactly one unnamed guest. Both were worked through
rule 9. ep52 is closed. ep55 has two of four guests named and two escalated.

**What the census settles before any photograph is fetched.** Cluster the census, then
group clusters into PEOPLE using two tests: centroid cosine, and whether the two clusters
ever appear in the same sampled second. The second is the hard one -- two faces in one
frame are two people whatever the cosine says. ep55 resolves to exactly six people for a
cast of six, and ep52 to four for four. That is worth doing first, because it tells you how
many names you actually need and stops you naming the same person twice.

**Three defects, all of which made a tool REFUSE a correct answer.** This is the failure
mode that hides, because refusing looks responsible:

1. `identify_person.py match` compared CLUSTERS, not people. Samsu Adabi owns ep55 clusters
   3 and 78; his portrait scored +0.694 and +0.665 on them, so the margin test reported
   "two clusters are too close to separate" and refused. The next different person was at
   +0.207.
2. Grouping the clusters then broke ep52, because the group's mean centroid sits away from
   every view that fed it. Zaim Zulkifli fell from +0.676 to +0.540, under the floor, while
   his margin GREW. A person is scored on their BEST cluster now, which is the rule
   `camera_speakers.py` already states for its own gallery.
3. `guest_gallery.py` hardcoded the shared gallery, so a guest rule 9 had just enrolled
   into `data/_face_gallery_<vid>.json` still read as unnamed. Same miss as the reference
   call had. Fixed, and it is what let ep52's bijection name Syuk after Zaim was enrolled.

**What a photograph has to look like to clear the 0.55 floor.** Measured on eight
photographs today:

| photograph | best cluster | cos | verdict |
|---|---|---|---|
| Sinar Daily news photo, Harith, face dominant and unobstructed | 40 | +0.756 | ACCEPT |
| Wiki Impact studio portrait, Zaim | 2+12 | +0.676 | ACCEPT |
| Wikimedia portrait, Samsu Adabi | 3+78 | +0.694 | ACCEPT |
| campaign poster, Harith, heavy colour grade | 40 | +0.511 | right face, under floor |
| graduation portrait, Tang Hong Yau, mortarboard over the chin | 83+84 | +0.391 | under floor |
| three channel stills, Syed Azuan, glasses plus a peaked cap | 60 | +0.32 to +0.38 | under floor |

The pattern is not photo quality. It is occlusion and colour: a plain frontal face clears
0.65, and glasses, a cap, a mortarboard or a heavy colour grade each drop it to roughly
half. The weak cases still RANK the right cluster first every time, and that is the trap --
rule 8 says agreement among weak witnesses is not identification, so they stay unnamed.

**A group photograph cannot be passed to `match`.** `photo_vec` takes the LARGEST face in
the still. Zaim's second witness was an eight-face rally photo where the largest face is
somebody else, so it was scored face by face instead: exactly one face matched his portrait
at +0.757 with every other at or below +0.157, and that face scored +0.661 on his cluster
against +0.233 on the other guest.

**ep55's last two faces went to the owner, and both came back the same day.** Cluster 60
is a man wearing a red cap and a yellow polo both printed `DSA`, in an episode whose cast
includes Dato' Dr. Syed Azuan Al-Idrus, known as DSA. That is documentary evidence, not a
face score, and this repo has no mechanism for it. The owner ruled `yes all is DSA` and
`all is Ubat i think?` off the contact sheet at `data/_ep55_faces.png`. The seconds are on
the video clock, so `https://youtu.be/4mmuPwkB5f4?t=<s>` lands exactly.

**The hedge in the second ruling did not matter, and that is the useful part.** Enrolling
cluster 60 as DSA left exactly one unnamed guest and one cluster holding 100% of the
remaining unidentified talking time, so `guest_gallery.py` named Tang Hong Yau on its own
measurement. The owner's eye and the bijection agree without either depending on the other.
The rebuilt reference then tracks every speaker's word share within about two points --
Rafizi 68.4% of camera time against 67.1% of words, Haziq 7.8/9.7, Samsu 7.5/6.7, Tang
6.0/5.3, Harith 5.4/5.8, DSA 4.8/5.3 -- which is the corroboration that all four faces are
on the right people, and it is not available until the last one is named.

**`check_owner_decisions.py` understands one kind of owner ruling, and there are two now.**
It reads every key whose first character is a digit as a TURN ATTRIBUTION and looks for the
owner's words in raw.md. A face identity at a video second has no turn and no text. Written
as bare stamp keys, which is what CLAUDE.md rule 7 mandates for the other kind, ep55's
twelve rulings produced ten `not locatable` lines and two `MISMATCH` lines, one of which
read as raw.md contradicting the owner at 2:53:30 where raw.md says `Multiple speakers` and
nothing is wrong. So the section
`ep55_rule9_faces_owner_ruled_2026_09_15` keys on the cluster and carries the seconds
INSIDE the value. **Rule 7's key shape is not the universal shape; it is the shape for a
ruling the gate has to verify against text.**

**Corpus state after all of this: `check_camera_reference.py` reports 37 usable, 0
refused.** The blind-reference class that started with ep33 on 2026-09-11 is closed.


#### The concurrency rule now has a lock, and Git Bash is why it needed one (2026-09-15)

The section above ends on "never chain a second GPU pass on anything other than the
first process's own log content." That is still right, and it is not enough, because
on 2026-09-15 a second chain started without anybody chaining it.

**What happened.** A chain launched at 10:52 failed on its first video download.
It was stopped with `kill <pid>` from Git Bash and a new chain started at 10:57. The
new chain's first chunk failed in 55 seconds with
`FileNotFoundError: work\k0\pywork\scene.pckl`, which reads like a broken LR-ASD
install. It was not. `Get-CimInstance Win32_Process` showed **four** `nightly_recut.py`
processes alive: `kill` in Git Bash stops the shell's job, not the Windows process
behind it, so both earlier chains were still running and invisible.

**Why a second chain corrupts the first rather than just competing for the GPU.**
`camera_speakers.py cmd_run` names its scratch directory from the chunk offset alone:
`data/_lrasd/work/k<offset>`. The episode is not in the name. So every chain processing
its first chunk uses `work/k0`, and `shutil.rmtree(work, ignore_errors=True)` at the top
of the loop deletes whatever the other chain has already written there. One process
detects its scenes, the other deletes `pywork` underneath it, and the write fails. The
trailing `PermissionError: ... k0.mp4 is being used by another process` on the cleanup
path is the same collision seen from the other side.

**The mechanism.** `nightly_recut.claim_the_gpu()` writes its pid to
`data/_nightly/chain.pid` and refuses to start while that pid is alive, naming the pid
and the `Stop-Process` command that clears it. A stale lock from a dead pid is taken,
not honoured, so a crashed chain does not block the next one. `atexit` removes it. This
closes the first of the three rules CLAUDE.md lists as having no mechanism.

**A separate fix in the same session, and it is not the concurrency one.** The 10:52
failure had its own cause. `ensure_pot_server()` returns as soon as the bgutil server
answers `/ping`, but the server cannot mint a PO token for a few seconds after that.
yt-dlp asks, gets nothing, and falls back to the format list available without a token,
which on these videos is four storyboard images. The error is again "Requested format is
not available", the same string the concurrency race produces, which is why the two were
easy to confuse. `nightly_recut.video()` now retries once after 15 seconds. Only the
first episode of a chain is exposed, because the server stays warm afterwards.

**The check that separates these two causes**, since they share an error string: count
the `python` processes before believing either diagnosis.

```powershell
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Select-Object ProcessId, CommandLine
```

#### A hyphen-prefixed video id breaks the reference call, not just this once

ep41's resumed run above still failed after the GPU contention was fixed --
`camera_reference: FAILED in 0.0 min`, `error: the following arguments are
required: uri`. The cause was unrelated to the contention: ep41's video id is
`-HujDcVKHzU`, and `nightly_recut.py`'s `camera_reference()` passed it as the
first positional argument, before `--tracks`/`--out`/`--runtime`. argparse reads
a token starting with `-` as an unknown option unless `--` marks the end of
options, so it never bound to `uri` at all. Fixed by moving `vid` after a
trailing `--`, last in the argument list. Two other episodes share the same
risk (`-NjVESCWO8w`, `-tpyLr5kwxI`) and are now covered by the same fix.

### `check_agencies.py`: the checker CLAUDE.md rule 2 was missing (2026-09-12)

Rule 2 ("every government agency cited is correct") was written with an explicit gap:
`check_names.py` cross-checks a person, nothing cross-checked an agency. This is that
checker. Four defects on its first corpus-wide run, all now fixed in
`fix_proper_nouns.py`'s reviewed map:

1. `Kementerian Keuangan` / `Menteri Keuangan`, 16 occurrences across ep12, ep17, ep18,
   ep25, ep28, ep29, ep34, plus ep29's interview.md. `keuangan` is the Indonesian word;
   Malaysia's ministry is Kementerian Kewangan. ep15 writes both forms in one sentence,
   which is what proves the ASR did it and not the speaker.
2. ep09's interview.md and interview-ms.md write `keuangan` where raw.md says `kewangan`
   correctly -- the rewrite introduced it, published-only.
3. ep15 `Menteri Kawangan`, ep27 `Jabatan Perkuam Negara` (the Attorney General's
   Chambers), one occurrence each.
4. ep05's interview.md and interview-ms.md cite `Seksyen 122B Akta SPRM 2009` in a passage
   about who appoints the Chief Justice. raw.md never says SPRM. Local ASR heard
   `Akta JSC 2009`, MAI heard `Akta JAC 209`, and the Judicial Appointments Commission Act
   2009 (Act 695) is exactly the law for appointing judges, so the rewrite swapped one
   commission for another. Fixed in all three files.

**The roster is the authority, and the roster can be wrong.** Its first version carried
`Kementerian Pertanian dan Keselamatan Makanan`, taken from Wikipedia's cabinet table.
The corpus said `Keterjaminan`, and the ministry's own portal (kpkm.gov.my) says the
corpus was right. The entry was the defect. Every entry now carries a `source` URL, and
an agency's own site outranks any third party.

**Two measured limits.** A lowercase garble is invisible: both sides of a comparison must
be written as a title, because without that condition the first run returned 52 hits and
30 were an ordinary Malay word after the head word (`kementerian dengan`, 7,220
occurrences of `dengan` in raw). The known cost is ep35's `Menteri yang kewangan` and
ep42's `Menteri kelihatan`. And the extension rule is tested against every roster name,
not the closest one: ep28's `Menteri Pertanian dan` truncates KPKM but scores closer to
`Menteri Pertahanan`, and checking only the closest match reported Aziz Ishak as Defence
Minister when he ran Agriculture.

One false positive survives by design, ep16's `Kementerian Kerana` (the conjunction
`kerana`, capitalised by the ASR). This is a review list, like `check_names.py`, not a
gate -- 15 hits corpus-wide, small enough to read, and reading them is the point.

### `check_overlap_boundaries.py`: rule 7's detector, and what it measures (2026-09-12)

Rule 7 (overlapping speech never silently merged into the wrong speaker) had a proposed
heuristic and no code. This is the detector half. It reports and never writes, because
rule 7's own instruction for an indecisive margin is to mark and escalate.

It reads each pair of adjacent blocks where the first ends without terminal punctuation
and the second, under a different name, opens in lower case -- one sentence across two
labels -- then reads the camera reference per second and judges AT THE BOUNDARY.

Two things the first version got wrong, both fixed by measurement rather than argument:

1. **The unit is a pair, not the A/B/A sandwich rule 7's prose describes.** Across the 22
   adopted episodes the sandwich occurs once (ep48 at 1:17:30); the pair occurs 66 times.
   MAI punctuates the end of a phrase, so after `merge_same_speaker.py` the first speaker
   rarely resumes in a third block -- the torn sentence ends at the handover. The first
   version, written to the sandwich shape, found 0 candidates in ep63 and reported clean.
2. **The verdict is decided at the edge, not over the window.** ep44's 1:21:26 reads
   `Rafizi 842s, Haziq 4s` over its whole window and `Haziq 2s, Rafizi 1s` over its first
   three seconds. A long turn can be correctly labelled and still open with words that
   belong to the previous speaker, which is exactly what rule 7 is about.

Corpus-wide result AS OF 2026-09-12: 66 candidates, 31 attested by the camera (real
handovers -- the co-hosts do finish each other's sentences), 35 contested, 0
camera-blind. **Superseded: the list is empty as of 2026-09-14, 0 contested and 0
tail, after the owner ruled the tail signature 11 of 11 and `move_hanging_words.py`
gained the branch it was missing. See "rule 7's tail" below, and treat
`check_overlap_boundaries.py --all` as the only live number.**
`data/rule7_contested_boundaries.md` is kept as the record, not a queue.

Two limits, both in the docstring. `check_camera_reference.py` is circular on an adopted
raw, so the tool prints each speaker's share of camera seconds instead of gating on it --
a speaker at 0.0% there makes every verdict worthless for that person's turns. And the
boundary second comes from the block stamp, which only holds for an adopted MAI raw; the
tool refuses any other raw rather than trusting a drifting clock.

### YouTube's caption `isSpeakerChange` flag: fetched, measured, rejected (2026-09-12)

The owner noticed YouTube's own transcript appears to separate speakers and asked whether it
could cross-check the contested boundaries. It carries a real signal we had never looked at,
and the signal does not survive measurement.

**What exists.** The `.vtt` format this repo downloads carries NO speaker information: 64
caption files, zero markers of any kind. The `json3` format does -- every segment can carry
`isSpeakerChange: true` alongside `utf8`, `tOffsetMs` and `acAsrConf`. Fetch it with
`python -m yt_dlp --skip-download --write-auto-subs --sub-langs ms --sub-format json3`.
That is why this was never seen before: the flag is dropped in the conversion to WebVTT.

**What it measures against the camera (ep61).** 1,147 caption change points against the
camera reference's 216. 83% of camera changes have a caption change within 3 s, which looks
excellent until the density is accounted for: with 1,147 points over 9,700 s, a RANDOM
second lands within 3 s of one with probability 69%.

**What it measures against the owner's own rulings.** Eleven boundaries the owner settled by
eye and ear on 2026-09-12, six of them real speaker changes and five of them places where
raw.md had a change that is not there. Scored at face value, the flag agrees on 4 of 11.
Sweeping the offset from -4 s to +4 s and the tolerance from 1.0 s to 2.5 s, the best
combination (-1 s, 2.5 s) reaches 7 of 11 -- and that offset was fitted to these same eleven
cases. The per-episode chance rate for a "change" answer is 13% to 32%.

**Verdict.** Not evidence at the resolution rule 7 needs. It is recall without precision: it
fires on nearly every pause, so it cannot say a boundary is real, and it carries no identity,
so it can never say who. Do not re-test it without new data; re-test only if YouTube starts
exposing speaker LABELS rather than change flags.

**What does work, already measured and in the repo:** caption WORD GAPS, not the change
flag. `data/` holds that earlier result -- boundaries from caption word gaps scored 16/16
against pyannote's 8/16 (see the diarization sensing note in memory and
`check_caption_coverage.py` for the caption plumbing).

#### The tail side of a torn sentence, and why only the camera can see it (2026-09-12)

`check_overlap_boundaries.py` judged only the SECOND block's opening seconds. The owner
read ep63's 1:58:44 and said Haziq starts with `tapi kalau tengok pada trend` -- words that
were sitting at the END of Rafizi's block, where no test in the tool could reach them. All
three interview files had inherited them as Rafizi's closing line.

The camera can see that case, and the reason is the flaw everything else has to work
around: the show's cut LAGS the speech by about two seconds. So if the camera already shows
B during A's final seconds, B had started before the cut, and A's last words are probably
B's. That is now a signature of its own, `tail`, with a link eight seconds early.

Eleven boundaries corpus-wide carry it. They are candidates for an ear, not verdicts: ep62
at 3:43:52 reads `Farhan (Pa'an): ...White pap-` / `Rafizi: dalam white paper pun sama juga`
and that is a real interruption, which looks identical to the defect from the outside.

#### The cast gate was wired into the wrong step, and two episodes adopted on blind references (2026-09-13)

`check_camera_reference.py` exists because a reference can be CONFIDENTLY WRONG: a guest
who is not in the face gallery gets handed to the nearest gallery member, and the
attribution score still looks clean. It was wired into `fold_hanging_fragments.py`, which
is step 4b of `adopt_mai_camera_raw.py`.

The overnight queue of 2026-09-13 showed what that misses. ep42 and ep39 both have a
speaker the reference cannot see -- Zikri Kamarulzaman at 14.2% of raw's words against 0.0%
of camera time, Iqbal at 5.3% against 0.0%. Step 4b refused and printed its refusal. The
script then ran steps 5 to 8 and wrote both candidate raws anyway. Traced afterwards by
locating every old guest block in the new file: 16 of ep42's 74 Zikri blocks came back
under a host, including his own introduction, `bagi yang tak kenal saya, saya Zikri`, as
Rafizi. Both adoptions were reverted by hand before any commit.

**The gate now runs before step 1**, with `--force-blind-reference` for the case where
someone has read `data/camera_reference_limits.json` and knows why a reference is safe.
Verified both ways: ep42 refused, ep40 passed.

**The fix for a blind reference, in order:** `guest_gallery.py <tag>` names the face when
the episode leaves no choice (one guest in the frontmatter, one cluster holding nearly all
the unidentified talking time -- ep42 measured 97%), then
`camera_speakers.py reference <vid> --gallery data/_face_gallery_<vid>.json`, then
`check_camera_reference.py`, then adopt. ep39 cannot take that path: Iqbal is listed as a
HOST, so the one-guest bijection does not apply, and two clusters talk. That one needs a
census, a contact sheet and a person's eye.

#### ep39 needed no person after all: `identify_person.py`, and why every tool read only the corpus (2026-09-13)

The section above ends "that one needs a census, a contact sheet and a person's eye."
That was wrong twice, and the owner named the reason: *"Do we become to rigid in our tools
that we so narrow down that we can't think outside the box?"*

**First, the census never needed the GPU.** `camera_speakers.py census` is
`cv2.FaceDetectorYN` plus `cv2.FaceRecognizerSF`, both OpenCV DNN on CPU. Only LR-ASD's
active-speaker pass needs CUDA. ep39's census was queued behind a four-episode GPU chain
for nothing; run alone it took 9 minutes and sampled 1,033 faces from 170 minutes.

**Second, and this is the real gap: every naming tool read the corpus's own files.**
raw.md's labels, the frontmatter cast, camera clusters, voice centroids. All 27 people the
corpus can name came from inside it. Rules 1 and 2 have said to web-verify a name since the
beginning, yet no script did, and the show's own YouTube description has been sitting in
`data/manifest.json` for all 70 episodes with no cast check reading it. So the loop's last
step was always "no internal tool can name this, escalate", which is not the same statement
as "unidentifiable".

`identify_person.py` closes it. A public photograph of a named person is an independent
witness in exactly the sense `camera_speakers.py` is: no audio model made it and it did not
come from this corpus. It is compared to face clusters the same way, SFace embeddings and
cosine, reusing `camera_speakers.FLOOR` 0.55 and `MARGIN` 0.10.

**It is calibrated before it is trusted, because rule 8 forbids a confident guess.**
`calibrate` runs the matcher against faces the gallery already holds and prints the matrix:

| reference photo | Farhan | Haziq | Rafizi | verdict |
|---|---|---|---|---|
| Rafizi (Wikimedia) | +0.068 | +0.234 | **+0.740** | right, margin +0.506 |
| Anwar Ibrahim | +0.087 | +0.070 | +0.151 | below the 0.55 floor, rejected |
| Nik Nazmi | +0.091 | +0.046 | +0.174 | below the floor, rejected |

So it names a known face across a different camera and year, and it rejects a stranger.
`match` then refuses three ways: under the floor, two clusters inside the margin, or a
cluster that already matches a gallery face (which would rename a known person).

**ep39's answer.** Two independent photographs of Iqbal Fatkhi, from wikiimpact.com and
projectliber8.org, both pick cluster 0: +0.672 and +0.710, with the next cluster at +0.085
and +0.180. Cluster 0 scores +0.229 against the closest of the three known hosts, while
clusters 5, 1, 2 and 8 match them at +0.947, +0.876, +0.759 and +0.587. Enrolled with
within-person minimum 0.63 against cross-person maximum 0.38. He is Editor-in-Chief of
Cilisos Media, which is why ep10 is titled `Yang Berhenti Menteri X CiliSos`.

**Two things the method does not license.** A search for a common given name returns
several different people, so the name must come from the episode's own text or the show's
description, never the photo caption -- ep39 says `kenapa kita jemput Iqbal` and
`dah 3-4 kali dijemput`. And a high score against a mixed cluster names two people at
once, so `match` prints each cluster's internal cohesion (ep39's were 0.864 to 0.896).

#### `check_cast.py`: the frontmatter cast was a derived claim nothing checked (2026-09-13)

`guest_gallery.py` runs its bijection on `guests:`. ep39 lists Iqbal under `hosts:`, so it
never tried, and it said so honestly rather than guessing. The `hosts:`/`guests:` fields
are written by the rewrite pipeline from the transcript, which makes them a DERIVED claim,
and nothing compared them to the episode's own words or to who actually speaks.

Three signatures, report-only. Four rounds of noise had to be cut, and each cut is a
lesson about this corpus:

1. **52 hits, mostly `YB Rafizi`.** It is ep08's stray label variant, not a person, and
   every episode opens with `bersama YB Rafizi`, so it fired on all 70. Honorifics are now
   stripped for comparison only.
2. **`bersama Trump`, `bersama Netanyahu`.** A bare intro-formula scan cannot tell a guest
   from a subject. The signature is now cross-episode: it fires only for a person the
   corpus labels SOMEWHERE ELSE, so it can only flag someone it already knows how to name.
3. **Two filler words of slack was still too loose.** It caught ep48's `kalau tengok Nik
   lah kan ... Nik Nazmi` and ep35's `aku dah nasihat dia pasal Farhan` -- people being
   discussed. The name must now follow the formula directly, in the opening 120 lines, and
   an `ABSENT` test kills ep35's `saudara Farhan tak ada pada hari ini`, which says
   outright that he is not there.
4. **Two people can share a given name.** The match is on the first word, because the text
   says `saudara Faiz` where the label says `Faiz Ahmad`. ep03's `Faiz (Financial Faiz)`
   and ep04's `Faiz Ahmad` each flagged the other's episode until the same extension test
   `check_agencies.py` uses was applied.

**A trap worth writing down: both shows have an ep01 through ep06, and they are different
episodes.** `common.raw_for_tag()` already refuses a bare ambiguous tag and demands
`ep03:bakar` or `ep03:berhenti`. A checker that globs paths itself bypasses that guard and
merges two episodes' data under one tag, which is what produced the Faiz pair above.
`check_cast.py` now carries the same suffix.

Final: 3 findings. ep39's `guest-as-host`, fixed via `common.set_frontmatter_list` to
`guests: [Iqbal Fatkhi]` (rule 3's full name) with the H1 verified intact. ep08's 60 `YB
Rafizi` turns, left alone and recorded in `data/qa_reviewed.json` as
`open-until-reprocessed` -- it is a local-ASR raw with no camera reference, and the owner's
standing rule is to reprocess, never hand-patch. `normalize_speaker_labels.py` could not do
it either: that tool only rewrites the `**Name:**` label in interview*.md, never raw.md's
`[time] Name:`. ep02:bakar's `Prof. Barjoyai` against `Prof. Emeritus Dr. Barjoyai Bardai`,
recorded benign: rule 3 working, and the prefix test misses it only because the full name
inserts words in the middle instead of appending.

#### rule 7's tail: the owner ruled it 11 of 11, so the tool writes now (2026-09-13)

`check_overlap_boundaries.py` classes a pair `tail` when the camera shows the NEXT speaker
for at least 2 of the 3 seconds before the boundary, skipping the block's own first second
because the cut lags speech by about two seconds. All 11 tail boundaries were escalated
with a `?t=` link and a contact sheet. The owner ruled every one the way the camera had
already read it -- the words at the end of the first block belong to the next speaker --
and added *"Actually all these can be verified visually..."*

**What `move_hanging_words.py` was blind to.** `split_tail()` returns the words after a
block's LAST sentence end. Six of the eleven blocks contain no sentence end at all: the
whole 2-to-7-word block is the hanging fragment, so `tail` was empty and the pair was
skipped in silence. ep62 `White pap-`, ep57 `Itu sebenarnya ialah`, ep56 `Dan kita telah
pun bersetuju aa langkah-langkah`, ep49 `So my concern masa itu ialah` and `Consistently,
the only`, ep47 `Kerana, kerana beritanya ialah`.

**The new branch gives the camera a veto, and the branch above it does not.** That is
deliberate, not an inconsistency. For a partial tail the SHAPE decides, because a sentence
is not split between two speakers and a camera cut is not a speaker change. For a WHOLE
block shape cannot decide, because rule 7 says a short block between two different
speakers may be a real interruption. What decides it is the measured tail signature.
Where the camera has no coverage, a recorded owner ruling moves it instead (ep56 01:24),
because rule 4 puts a person above every tool.

**A bug that made every rule-7 ruling unenforced.** `check_owner_decisions.py` skips any
key whose first character is not a digit, and it only reads a section whose name contains
the episode tag. The `ep33@22:47` keys used for the four boundaries decided on 2026-09-12
satisfied neither, so the gate silently checked nothing. All 15 rule-7 decisions now live
in per-episode sections with bare stamp keys, and the gate reports them: ep33 2, ep46 1,
ep47 2, ep49 4, ep50 2, ep51 1, ep54 1, ep56 7, ep57 11, ep62 16, all preserved,
0 mismatched.

Result: 21 tails and 6 whole blocks moved across 17 episodes, every word conserved by the
existing guard, then `merge_same_speaker.py` for rule 6. The detector went from
0 contested / 11 tail to **0 contested / 0 tail across all 27 episodes with a camera
reference**. 10 published turns in 7 episodes then disagreed with raw.md and are being
regenerated: ep33, ep42, ep47, ep48, ep50, ep53, ep54, ep62.

#### ep32's camera pass died because its video file vanished mid-run (2026-09-14)

`nightly_recut.py ep32 ep29 ep28 ep27 --hours 11` logged one line about it:

```
15:19:28   camera_run: FAILED in 45.5 min
```

That line reads as forty-five minutes of GPU time thrown away, and it is wrong twice over.
The report JSON held the real cause. ffmpeg exited `4294967294`, which is `-2` unsigned,
ENOENT:

```
[in#0 @ ...] Error opening input: No such file or directory
Error opening input file ...\data\_video\UF8RxxOiWDA_480p.mp4.
```

**The video was deleted while the job was reading it.** Five of eighteen chunks had already
been written, so the file existed for the first 46 minutes. Nothing in the pipeline deletes
it at that point: `nightly_recut.py` unlinks the video only AFTER `camera_run` and
`camera_reference` in the same loop iteration, and `cleanup_scratch.py` does not target
`data/_video` at all. The process tree was a single chain, so no second nightly run raced
it. **The cause is outside the pipeline and was not identified.** The likeliest candidate is
a manual cleanup, because `data/_video` is named as a cleanup target in the session-closing
checklist.

**Two asymmetries made this worse than it needed to be.**

1. **A model failure is tolerated and a missing input is fatal.** When `Columbia_test.py`
   produces no tracks, the loop prints `FAILED` for that chunk and continues. When ffmpeg
   cannot open a file, `check=True` raises and the whole episode dies. The second case is
   the recoverable one.
2. **`video()` checks only `p.exists()`**, then `camera_run` reads that file for two to
   three hours with no further check. There is no lock and nothing re-verifies it.

**What was actually lost: one chunk, about nine minutes.** The chunk loop skips a chunk
whose json is already on disk (`if dest.exists(): continue`), which is the same recovery the
concurrent-GPU section above describes. So ep32 resumes at chunk six and needs thirteen
chunks, not eighteen. Its video has to be re-downloaded first, which `video()` does
automatically because the file is gone.

**The fix is a log line, not a guard.** A guard cannot stop an external process from
deleting a file, and re-checking the path per chunk would only move the traceback. What was
missing is the operator being told the run is resumable. `camera_run` now prints, on
failure only:

```
  RESUMABLE: 5 chunk(s) on disk, a re-run skips them; MISSING INPUT: data\_video\UF8RxxOiWDA_480p.mp4
```

It names any input that has gone missing, because ffmpeg's `check=True` turns that into a
traceback in a JSON field rather than a sentence in the log the operator reads.

#### The rewrite stage changes figures, and nothing could fix them (2026-09-14)

`check_figures.py` had flagged 7 episodes for a while and no one had ruled on any of them.
Audited all nine flagged figures. Seven are real and **the published text is the wrong side
in every one**:

| episode | published said | correct | scale of the error |
|---|---|---|---|
| ep31 | `75 juta` | `7.5 juta` | ten-fold |
| ep34 | `RM75 bilion` | `RM7.5 bilion` | ten-fold, tax refunds |
| ep49 | `scuba 677` | `scuba` | a number that was never said |
| ep49 | `1B di Pandan` | `di Pandan` | the English rewrite expanded it to `seat 1B` |
| ep49 | `Facebook 3.3 juta` | `Facebook 3 juta` | a decimal invented from `3 point` |
| ep52 | `47K` | `47 kes` | 47 court cases became 47 thousand |
| ep55 | `200 juta` | `700 juta` | highway cost, wrong by 500 juta |
| ep59 | `rugi 120 juta` | `rugi 102 juta` | transposed digits |

Two are not defects. ep34's `45 bilion` is a substring of `RM22.45 bilion`, which raw.md
supports. ep41's `1.99` is raw's `seringgit 99 sen` written in digits, which is correct
style for an interview file.

**Two different defects hide under one signature, and they need opposite fixes.**

- **Six of the seven came from the pre-adoption local-ASR raw.** The rewrite copied a bad
  source faithfully. Verified by reading each episode's old raw from `data/_old_*_raw.md` or
  from git history before the adoption commit. Regenerating the published files from the MAI
  raw fixes these by itself.
- **ep52's `47K` was invented at the rewrite stage from a correct source.** The MAI raw, the
  pre-adoption raw, AND the Malay captions all say `DNAA 47 kes`. `47K` exists in no witness.
  So regeneration can reproduce it, and ep52 needs a specific re-check after any rewrite.
  This is the one case that proves regeneration is not a guarantee.

**Every verdict has two independent witnesses**, per the owner's rule of 2026-09-12 that a
disputed digit is settled by witness count. The witnesses are raw.md (MAI), the Malay
caption track, the pre-adoption raw, and the sentence's own arithmetic. ep34 is the
strongest: the captions say `7.5 bilion` four times and `75 bilion` never, and the sentence
calls the payment higher than the PM's commitment of 4 bilion, which 7.5 exceeds narrowly
and 75 overshoots absurdly.

**`scripts/fix_published_figures.py` is the mechanism that was missing.** A figure
correction cannot live in `fix_proper_nouns.py`, whose map is corpus-wide: a bare `200 juta`
or `47K` is not safe to rewrite across 70 episodes. So the map here is keyed by episode,
holds literal strings only with no regexes at all, and declares the occurrence count each
rule expects. It refuses to write when a count has moved, because that means the file was
regenerated or already corrected and the rule no longer describes the text it was reviewed
against. It never touches raw.md.

**Where the RAW carries the wrong digit instead, the fix goes elsewhere**, and ep31 has one
of each in the same episode. Its raw said `180.8 million` where every other witness said
`184.8`: the local raw, the captions three times, and the arithmetic (462 million MMAG
shares at 40 sen is 184.8 million exactly, and the episode's own title puts Farhash's loss
at RM97.5 juta, which is 184.8 minus the 87.32 he sold for). That correction went into
`fix_proper_nouns.py`, labelled there as a figure, because that map is the one reviewed list
`mai_camera_raw.py` applies during the build. A fix recorded anywhere else is wiped by the
next re-adoption.

Result: `check_figures.py` went from 7 of 70 flagged to 2 of 70, and both survivors are the
non-defects above. Verdicts and evidence for all nine live in `data/qa_reviewed.json`.

#### `not locatable` is a verification gap, not a lost decision (2026-09-15)

The session-closing checklist says to read `check_owner_decisions.py`'s `not locatable`
count, because "a decision the gate cannot verify is one that can be silently reverted."

**Re-measured 2026-09-15, after ep24, ep25 and ep26 adopted.** The audit has to read every
`data/speaker*.json`, not just `speaker_adjudications.json`. A first pass read only that one
file and reported 24 in three episodes, missing ep19 entirely, because ep34's two rulings
live in `speaker_owner_ear_2026_09_11.json`. Nine files carry a tag-keyed ruling.

    159  decisions across 25 episode tags
    108  preserved
      7  partly kept
      0  MISMATCHED
     25  not locatable: ep19 (1), ep34 (2), ep53 (7), ep61 (15)

**Audited every text-less decision by hand. All are honoured in the current raw**, and the
camera independently agrees at almost every second. The count measures what the gate can
PROVE, not what the corpus has kept.

    114 stamped owner decisions in data/speaker*.json
     82 the gate can read today
      6 carry a bare `text` key, which the gate ignores
     26 carry no text at all, only a stamp

The gate reads `text_now`, then `text_was_startswith`, then `text_was`, then falls back to
whatever block sits at the stamp. After an episode is re-adopted the stamps move, so the
fallback finds nothing and a text-less record becomes unverifiable.

**Three looked like conflicts and none was.** Each was an artefact of checking by stamp,
which CLAUDE.md warns against in exactly these words: a stamp cannot locate a decision.

- `ep61_farhan_restore@2:51:15` carries `at_now: 2:51:41`, and the raw holds
  `[2:51:42] Farhan (Pa'an)`. Honoured. Two records share the `2:51:15` key and name
  different speakers, because they describe different seconds.
- `ep61_owner@07:44` has a bare `text` of `Sila lapuk kepada pihak berkuasa.` MAI reads
  `[07:47] Rafizi: Okey. Sila lapor kepada pihak berkuasa.` Honoured, and the old record's
  own words were the garble.
- `speaker_from_gold.json:ep61@02:36` sits inside the gold passage, which the gate verifies
  separately: 346 words found in order, 0 under a different speaker.

**Adding `text` to the gate's fallback chain was considered and REJECTED.** It would help 3
of the 6, because the others (`Juali`, `Kan?`, `tu`) are under the two-word minimum that
stops a fuzzy match. And the one substantial case is `Sila lapuk`, a garble absent from the
new raw, so it would not locate cleanly. It would fuzzy-match somewhere else instead, which
is the ep31 failure of 2026-09-15: a 0.60-score match 38 minutes from its own stamp.

**What would actually close the gap** is `text_now` on the 26 stamp-only records, written
from the current raw. That is real work and it is not urgent, because the decisions are
being honoured. Do it per episode the next time each one is touched, the way ep31's two were.

#### ep26, ep25 and ep24 adopted: what each one needed, and it was different each time (2026-09-15)

Three episodes in a row, three different blockers. The reason to record them together is
that none of the three was a camera failure, and a session that assumes a refusal means
"rerun the camera pass" will waste hours on all three.

**ep26 needed the owner's ear on two moments, and the two were not the same kind of
question.** The adoption gate reported one MISMATCH and one PARTLY KEPT. Before escalating,
the camera's UEM was read at both seconds, which is what separated them:

| moment | owner | candidate | camera |
|---|---|---|---|
| 2:24:04 `Kita lupa, kita lupa.` | Farhan (Pa'an) | Rafizi | covers 8644-8645 and reads Rafizi |
| 2:26:46 `Point finger kepada Fuziah.` | Rafizi | Haziq | no coverage, so the label came from a fallback |

The second one was already settled by CLAUDE.md rule 4's evidence order: a fallback is the
weakest witness and the owner's ear is the strongest, so the owner was right and the camera
never dissented. Only the first was a real disagreement, and the owner ruled Farhan there
too. Their words: *"Kita lupa, kita lupa is Farhan, Memang teruk ah korang this week is
Rafizi"*, and on the other, *"Haziq did say Fuziah, but he just reiterate what Rafizi is
saying. So appoint it to Rafizi only."*

Both went into `data/forced_labels.json`, not into a commit message, so they survive the
next rebuild. `mai_camera_raw.force_labels()` applies them after the camera pass and before
the gate, which is the only place a ruling can land without hand-patching a raw. The gate
then read 6 preserved, 0 mismatched, over 14 decisions.

**Two anchor details that matter for the next ruling.** MAI writes `Kita lupa, kita lupa`
twice in ep26, at 2:23:37 and at 2:24:04, so the `at` hint is the only thing selecting the
right one; `force_labels` prints a WARNING when a second match scores equally and the stamp
breaks the tie. And MAI cut `Point finger kepada Fuziah.` across two blocks, so that anchor
spans both and sets both. `Ada tu.` at 2:26:45 stays Haziq: no ruling covers it, and a
ruling is not extended by inference.

**ep25 needed no person at all, and the cast gate said otherwise at first.** It refused:
`Faizal Rahman raw 7.3% of words, reference 0.0% of time`. The 2026-09-14 recipe for that
refusal is to look for the guest in another episode's gallery, and it did not apply here.
Faizal Rahman is in ep02, ep03, ep04 and ep52 of the corpus, but in no
`data/_face_gallery_*.json` anywhere, so there were no vectors to merge.

`guest_gallery.py` settled it without a photograph. ep25's cast has two guests, Razeef
Rakimin already enrolled and Faizal Rahman not, so exactly one name was unclaimed. One
cluster of 96 tracks held 421s of the 427s of unidentified talking time, which is 99%, and
the next cluster held 3s. That is the bijection, and it named him. Then `reference` reran
with no GPU, `unknown face talking` fell from the refusal's level to 19s, and the gate
passed at 4.7% against 7.3% of the words.

**Read `unknown face talking` before deciding a refusal needs a person.** ep25's was the
whole of one guest. ep24's is 117s spread thin, its identified rate is only 72%, and its
gate passes on three speakers, so nothing is missing there.

**ep24 needed nothing, and its two failures were both false.** `split_dry_run` refused,
which is correct behaviour and not a blocker: the split tool measured its own output as
slightly worse (15940 words right to 15930) and refused to write. Adoption does not use it.
The `YB garble` count of 1 is the word `baby` in `rasa macam baby umur 20 tahun`, a real
English word inside `GARBLE`'s alternation, and it was 1 before adoption too.

**One real find, and it is in the published file rather than the raw.** `check_figures.py`
now flags ep24's `300 bilion`. The old local-ASR raw wrote `taburan hujan dia dalam satu
hari berapa? 300 bilion. Alhamdulillah 300ml Sehari`, and rainfall is not measured in
billions. MAI transcribes the same seconds as `300? 300. 300. Alhamdulillah. 300 mililiter
sehari`, with no figure word at all. So the adoption fixed a fabricated scale word, and the
flag is pointing at interview.md, which is one of the 40 stale published files. It clears
when the rewrite is regenerated.

#### `check_agencies.py`: a trailing hyphen is a self-repair, never a garble (2026-09-15)

ep24 38:32 produced `garbled-agency: raw.md writes 'Jabatan Komuni- Komuniti' where the
verified name is 'Jabatan Komunikasi Komuniti'`. Reading the sentence killed it. Rafizi is
correcting himself out loud: `Jabatan Komuni- Komuniti. Komuniti. Komunikasi komuniti. Ha
kan, J-KOM.` He reaches the roster name two words later. Rule 5 keeps a self-repair, so
there was nothing to fix, and fixing it would have deleted real speech.

MAI marks a cut-off word with a trailing hyphen, and no roster name has a word ending in
one, so `garbles()` now breaks on any candidate word ending in `-`. This is the same class
as ep16's `Kementerian Kerana`, which STOPWORDS closed on 2026-09-12: a checker offering a
confident agency name for something that is not an agency name at all.

Regression-tested on four inputs, because a guard that silences a real defect is worse than
the false positive it removes:

| input | reported |
|---|---|
| `Kementerian Keuangan akan bayar` (the real Indonesian garble) | yes, offers Kementerian Kewangan |
| `Jabatan Komuni- Komuniti. Komuniti. Komunikasi komuniti.` | no |
| `di Kementerian, Kerana kalau betul` (ep16) | no |
| `Jabatan Komunikasi Komuniti ada lagi.` | no |

Corpus-wide the count went from 1 issue to 0.

#### ep21, ep22 and ep23 adopted, and MAI regressed a DIGIT this time (2026-09-15)

**ep21's cast gate produced the largest refusal this project has seen, and no person was
needed to clear it.** `Dr. Rais Hussin raw 51.3% of words, reference 0.0% of time`. The
missing speaker was not a minor guest, he was the co-lead of the episode. The reference
covered only 4468s of a 9574s runtime because more than half the talking was an unnamed
face.

He is in no `data/_face_gallery_*.json` and speaks in no other episode, so there was nothing
to merge. `guest_gallery.py` named him anyway: 71 tracks held 4500s of the 4505s of
unidentified talking time, which is 100%, and exactly one guest name was unclaimed. After a
`reference` rerun with no GPU, coverage went 4468s to 8917s, 93% of the runtime, and the
gate passed at 49.9% of the time against 51.3% of the words.

**Three refused cast gates in two days, all closed by the bijection and none by a
photograph.** ep25's Faizal Rahman at 99%, ep21's Dr. Rais Hussin at 100%, and ep29's Iqbal
by the gallery merge on 2026-09-14. Try `guest_gallery.py` BEFORE reaching for rule 9's
photograph path. The photograph is only needed when two or more names are unenrolled, which
`corpus_status.py` now names per episode.

**MAI regressed a figure, and this is the first measured instance of that.** The known class
was names: `Izzah` to `Izah`, 194 fixes over 20 episodes. ep21 adds a digit.
`check_figures.py` flagged `95.6` in the published text with no counterpart in the new raw,
because MAI transcribes the same words as `90.6% accurate`.

`figure_witness.py` settled it without a human ear, which is what it exists for:

| witness | reads |
|---|---|
| pre-adoption local-ASR raw | 95.6 |
| English caption track, matched at 0.52 by lib_locate | `the last six to 95 6 6 accurate` |
| MAI, the new raw | 90.6 |

Two independent witnesses against one, under the owner's 2026-09-12 rule. The fix went into
`fix_proper_nouns.py`, which is the only reviewed map `mai_camera_raw.py` applies during the
build, so a re-adoption cannot restore 90.6. It is the second figure entry in that map, and
`fix_published_figures.py`'s own docstring is what says a raw-side digit belongs there.

**Read this part before concluding MAI is the weaker witness.** MAI is better in that exact
sentence on every other count. The local raw heard `the last six take tu` and `When tengah
ni`; MAI hears `the last six state tu` and `When Terengganu`, and Terengganu is a state in a
sentence about six state polls. So the digit had to be measured rather than decided by which
engine usually wins.

**ep21's second flag is the opposite direction, and it needs no fix.** The published text and
the old raw both say the BRICS population is `4.2 juta`, 4.2 million. MAI says `4.2
billion`, and the captions say `4 2 two billion`. MAI is right and the old raw was also
translating English speech into Malay, which is the known mistranslation defect. The flag
clears when the published files are regenerated.

#### HANDOFF files are pruned to two, and the rule has a script (2026-09-15)

Four had accumulated: 09-12, 09-13, 09-14, 09-15. Owner's decision: *"why is there
accumulated handoff md files, just delete those after one session ahead perhaps"*.

The cost was not disk. CLAUDE.md's own opening paragraph still said *"Read
`HANDOFF_2026-09-13.md` first, then `HANDOFF_2026-09-12.md`"* two days after those stopped
being the newest, so the file that tells a session where to start pointed at stale state.
That paragraph now says to read the newest and only the newest.

`scripts/prune_handoffs.py` keeps the newest two and deletes the rest, ordered by the DATE IN
THE FILENAME rather than by mtime, because reading or copying a file changes its timestamp.
Two rather than one, because the newest can be half-written when a session ends
unexpectedly. The session-closing checklist hook now runs it as part of step 5, so the rule
has a mechanism instead of depending on someone noticing the pile.

Checked both deleted files for anything durable first. ep09-12's process-failure section is
in memory as `feedback_no_em_dash.md` and the Stop hook now enforces it. ep09-13's standing
decision, reprocess with the camera and never hand-patch a local raw, is in CLAUDE.md's
no-mechanism list and in memory.

#### The adoption sequence had a missing second pass, and rule 7 went to 1 because of it (2026-09-16)

ep20, ep19 and ep18 adopted clean overnight, every gate passing. Then
`check_overlap_boundaries.py --all` reported **1 contested** across 46 episodes, after days
at 0, plus 2 tails.

**The cause is the order of two steps that each change the other's input.** Adoption runs
`move_hanging_words.py` at step 5 and `merge_same_speaker.py` at step 6. The merge joins
blocks, so a tail that had a grunt or a short turn after it ends up adjacent to a different
block than the one step 5 looked at. A second move pass then finds real tails. Measured: one
each in ep18, ep19 and ep22, all three already adopted and reported clean.

CLAUDE.md rule 6 states the mirror of this and has since ep32: *"Re-run this step AFTER the
rule 7 move, not only before it."* Rule 8 states the general form. Neither was wired into
the sequence, so both depended on someone re-running the tool by hand. **Step 6c now does
it**, and it is the third time this exact class has been found: a rule that exists, is
written down, and has no mechanism.

**`--camera-veto` is ON at step 6c and off at step 5, deliberately.** Step 5's default was
measured against the owner's ear 11 of 11 on 2026-09-13, and every one of those 11 was a
boundary where the camera shows the NEXT speaker during the previous block's last seconds.
A tail the camera attests to the CURRENT speaker is the other shape and that measurement
does not cover it. ep18's 1:32:59 is the case, so it is left for an ear rather than moved on
a rule measured for something else.

#### `fold_hanging_fragments.py`: condition 1 refused the case where its evidence was strongest

ep20 1:47:19 is the SANDWICH shape CLAUDE.md rule 7 names, and the second in the adopted
corpus after ep48 1:17:30. Haziq reads a press statement listing Malaysia's exports:

    [1:47:05] Haziq:  ...eksport utama Malaysia seperti minyak sawit,
    [1:47:19] Rafizi: barangan berasaskan getah,
    [1:47:20] Haziq:  produk koko, komponen dan alat ganti pesawat dan farmaseutikal.

The middle item of Haziq's own list was labelled Rafizi. The camera reads **Haziq for all
3 seconds**. The fold refused it anyway, because condition 1 was "the camera covers NONE of
the fragment's seconds" and any attestation disqualified the fragment.

**Condition 1 now has a second branch, and it is strictly safer than the first rather than a
loosening.** Condition 1 exists to stop a minority speaker being deleted when the camera
says they really did finish someone else's sentence. That danger requires the camera to
attest a DIFFERENT name from the neighbours. Where every attested second votes for the SAME
name that sits on both sides, the camera corroborates the fold and only the fragment's own
label dissents.

**A guard had to come with it, and ep18 is why.** The new branch made
`[1:29:34] Haziq: Baik. Kandungan pengajaran` a fold candidate. That block is Haziq's own
`Baik.` followed by the start of Rafizi's sentence, so folding the whole thing would have
given Rafizi a word Haziq said. A sentence ending INSIDE the fragment means two sentences
and possibly two speakers, which is `move_hanging_words.py`'s partial-tail case. The fold
now skips any fragment containing `[.?!]` followed by a space.

Regression-checked as a dry run on eleven adopted episodes before writing anything. Only
ep20 gains a fold. ep61's nine camera-attested fragments, the safety case this condition was
built for, are still counted as attested and left alone.

#### Auditing owner decisions: do NOT pass a guessed `--current` (2026-09-16)

`check_owner_decisions.py` takes `--current <the raw the decisions were recorded against>`.
A standalone re-audit has to either pass the right file or pass none. Passing a GUESSED one
produces false verdicts in both directions, and this is worth recording because a false
MISMATCH is worse than no record.

Measured on the same corpus, same minute, three ways:

| `--current` | preserved | partly | MISMATCHED | not locatable |
|---|---|---|---|---|
| none | 108 | 8 | 0 | 24 |
| guessed `data/_old_<tag>_raw.md` for every tag | 120 | 8 | **2** | 10 |

Both ep61 "mismatches" under the guess are false. `ep61_farhan_restore@2:51:15` reports a
disagreement at 2:50:42, and the raw holds `[2:51:42] Farhan (Pa'an): Tak, maps, maps lain.`
exactly as ruled; the anchor text is the OLD raw's wording and lib_locate fuzzy-matched it
into a long Rafizi block. `ep61_from_owner_gold@01:55` reports Rafizi, and the raw holds
`[01:55] Haziq: Okey. Okey, baik YB.` as ruled; that anchor's words belong to Rafizi's 01:36
turn, so the recorded text is wrong for that stamp, not the label.

**The authoritative run is the one inside `adopt_mai_camera_raw.py`**, at the moment of
adoption, where `--current` is the committed raw the decisions were actually recorded
against. ep20 demonstrates the difference: preserved inside adoption, 1 not locatable in a
standalone run with no `--current`.

#### `check_owner_decisions.py`: the fallback chain was missing its last link

ARCHITECTURE.md has described this gate's chain as `text_now`, then
`text_was_startswith`, then `text_was`, then "whatever block sits at the stamp". The last
link only ran when the record had NO text at all. A record whose text existed but fell under
the two-word minimum printed `cannot locate` and stopped.

That two-word minimum was added 2026-09-15 for a good reason: a one-word snippet matches
everywhere. It had a side effect nobody measured.

  - **ep34 2:04:29** carries `0.0179`, one token. The block on that second is Haziq, exactly
    as the owner ruled. Now reported `preserved at the stamp`.
  - **ep19 1:43:04** carries `text_now: "Hmm"`. MAI transcribes those seconds as `No.` and
    the block IS Haziq as ruled. Two blocks share that second with different names, so the
    stamp alone cannot say which turn the owner meant. Reported `AMBIGUOUS, kept`, the same
    verdict a two-word snippet sitting in two blocks already gets.

**The condition is strict, so this verifies rather than waives.** Exact label match at the
stamp counts as preserved; the owner's label merely being present counts as ambiguous-kept;
a different label still reports, and so does a second with no block. Corpus-wide the
not-locatable count went 25 to 24 while three more episodes were adopted.

#### The owner's two rulings, and one of them corrected my method (2026-09-16)

**ep18 1:32:59. Owner: all Rafizi, and the camera could have told me.** Their words:
*"the first one is all rafizi, theres no Haziq at all in there. heck, this can be verified
with video evidence, dont need me to verify"*. They are right, and I escalated a boundary
the camera had already settled.

The mistake was reading only the boundary seconds, which is what
`check_overlap_boundaries.py` prints. Reading the WHOLE span answers it:

    1:32:59-1:33:25   Rafizi 26/26
    1:33:25-1:33:29   Rafizi 2, uncovered 2      <- the block labelled Haziq
    1:33:29-1:33:32   Rafizi 3/3

Haziq appears nowhere. `Yang itu tidak, tidak belum, belum kita dengar secara
menyeluruhlah kan.` is one Rafizi sentence MAI cut in two, and the second half took a Haziq
label from the fallback. `move_hanging_words.py` wanted to move the TAIL INTO Haziq, which
is the wrong direction entirely. The fix is to give Haziq's block to Rafizi, and it is in
`data/forced_labels.json`.

**BEFORE ESCALATING A BOUNDARY, READ THE CAMERA ACROSS THE WHOLE SPAN.** Rule 9's principle
is that the tools come first, and rule 8's residue is only what they cannot settle. A
boundary print is not the whole evidence.

**ep19 23:21. Owner: Haziq, starting at `tapi kita ada segmen keras sangat`.** Two
independent signals corroborate them, so this is not their ear alone. The `YB ya` vocative
at MAI word-time 1418s addresses Rafizi, so the speaker is not Rafizi, and that vocative
scored 6/6 against the camera's 0/8 in this corpus. And the camera reads Haziq 4s over
23:41-23:51 and 9s over 23:51-24:01, covering the parliamentary question being read out.
The camera shows Rafizi through 23:41 because the cut lags speech by about two seconds and
Rafizi's `Memali.` ends at 1410s, which is rule 7's own measured finding.

Recorded as two rules so the whole handover moves, including the one-word `Okey.` at 23:34
that the owner's quote includes. MAI hears `tuduh statement` where the owner hears `segmen`,
so the anchors use MAI's words.

#### A short block labelled against the only talking face: 457 of them, and I had the camera wrong

**CORRECTION, same day.** An earlier version of this section said the camera cannot settle a
backchannel and that there was "no tool to build for it". Both were wrong, and the owner
caught it: *"no haziq at all, its all Rafizi. Haziq just hmm hmm humming. this also can be
clarified via video"*.

**The camera reference is LR-ASD lip-sync, not the cut.** `camera_speakers.py` drops a second
where the visible face's mouth is shut and counts it as `on-screen-but-silent`. Its own
docstring says so. So a second labelled Rafizi does not mean "the shot was on Rafizi"; it
means Rafizi's mouth produced that audio. I reasoned from the wrong premise and told the
owner the camera was blind here.

**ep18 1:35:02, checked properly.** `data/_camera_tracks_KbbtwFgvTmw` holds exactly ONE face
track across 5698-5707, scoring 1.09 to 3.41 in every second. One person visibly talking for
ten straight seconds. MAI's word times put `podcast.` at 5701.4, `Kan?` at 5703.0 and `Jadi`
at 5703.2: one continuous utterance. The candidate held TWO blocks on that second, `Haziq:
Hmm.` and `Haziq: Kan?`. The humming is Haziq's and the tag question is Rafizi's, exactly as
the owner described. Recorded in `data/forced_labels.json`.

**THE SIZE OF THE CLASS, measured.** The test is: a block of three words or fewer, the same
name on both sides, the camera naming that neighbour, exactly one face track on screen, and
its lip-sync score positive in every second of the block.

    710  short dissenting blocks measured across 46 adopted episodes
    527  have exactly ONE face track on screen
    457  of those have that one mouth moving in EVERY second of the block
      4  of the 457 contain a `YB` vocative, so that speaker is not Rafizi
     43  episodes affected; ep33 holds 63, ep57 25, ep38 24

**IT DOES NOT MEET RULE 8's BAR, AND MUST NOT WRITE YET.** Only a witness measured at 100% on
its held-out class may write a label. Cross-checked against every recorded owner ruling with
matching text, the test has exactly two data points:

| moment | owner | the test | note |
|---|---|---|---|
| ep18 1:35:02 `Kan?` | Rafizi | Rafizi | agrees |
| ep53 29:58 `Okey. Baik, YB.` | Haziq | Rafizi | CONTRADICTS, and it carries a `YB` vocative |

One for, one against. The vocative guard would exclude the failure, which leaves one for and
none against, and n=1 is not a class. The precedent for authorising a tool like this is
rule 7's tail: the owner ruled 11 boundaries, the camera matched 11 of 11, and only then was
the tool allowed to write.

**A METHOD WARNING, because the first validation pass was noise.** It matched any ruling whose
text CONTAINED the block's text, and these blocks are one word, so ep61's `Ya.` matched 15
unrelated rulings and produced "42 agrees, 29 contradicts". Both numbers were meaningless.
Require the ruling's normalised text to EQUAL the block's text. This is the same defect memory
records as "anchor patterns tightly".

**Word-gap timing does NOT separate the classes**, tested rather than assumed. Measured on
ep18's 20 cases from MAI's word times, the gaps around `Kan?` are 0.30s and 0.10s, which is
mid-distribution: `Kan.` at 1:27:23 is 0.02s/0.26s and `Jepun.` at 1:27:40 is 0.12s/0.02s,
both ordinary backchannels. No threshold works, so the lip-sync test is the only candidate.

**Rule 1 of `mai_camera_raw.py` stays as it is until that measurement exists.** Its stated
reason, that the camera "is wrong about it by construction", is false for the one-face case,
and its conclusion may still be right for the rest. 453 relabels on one confirmed example
would be exactly the bulk write this repo has been burned by before.

#### `drop_orphan_backchannels.py`: the owner's answer to an unattributable turn (2026-09-16)

After the blind sample scored the lip-sync test at 12 of 19, the owner asked the question
that dissolves the problem instead of solving it: *"actually anything offscreen, and the word
is just not adding in to anything, we can just safely omit?"*

**Half of that is not mechanisable and half is.** Nothing can detect "offscreen", which is
the whole finding: the camera is LR-ASD lip-sync, it credits the one visible talking face,
and no threshold separates the two cases. But "the word adds nothing" is decidable from a
closed lexicon. So the tool drops the contentless subset and leaves the rest alone.

Measured across every adopted raw.md, short turns sitting between two blocks of the same
other speaker:

    231  a pure acknowledgement           -> dropped
     52  borderline, the owner's call     -> left alone, lexicon deliberately excludes them
   1197  carry content                    -> left alone, rule 8 residue for an ear

First pass removed **169 turns and 193 spoken words across 37 files**, with no word added
anywhere. Adoption runs it at step 6d, then merges again, so a re-adoption reproduces it.

**The excluded 52 are excluded for a reason each.** `Betul.` (14), `Ya, betul.` (8), `Kan.`
(5), `Kan?` (4), `Setuju.` (3), `Alhamdulillah.` (3), `Right?` (2). `Setuju.` means "I
agree", which is a stance rather than a signal. `Alhamdulillah.` is a religious expression.
`Kan?` is often the MAIN speaker's own tag question, which the owner's ep18 1:35:02 ruling
established. Widening the lexicon deletes from the verbatim source and needs the owner.

**Condition 2 is what makes this safe, and it is easy to miss.** The block either side must
carry the SAME name, and not this block's name. Without it, dropping every `Okey.` would
delete Haziq's real segment handovers, and `Okey, baik YB, selesai` is a turn rather than a
backchannel.

**TWO GUARDS EARNED THEIR PLACE ON THE FIRST RUN.**

1. **It refuses a raw.md that does not declare `model: microsoft/MAI-Transcribe-2`.** The
   first corpus-wide dry run offered to edit ep07, ep08, ep10, ep11 and ep14, none of them
   adopted. Excluding `model: mesolitica` is not enough: ep07 and ep10 carry no `model:` line
   at all, which is `check_raw_engine.py`'s `raw-engine-unknown` case. Requiring the MAI
   build positively is the only test that holds. **This closes one of the two rules CLAUDE.md
   listed as having no mechanism.**
2. **The word-conservation guard refused the first write attempt, correctly.** It compared
   the removed text against the whole removed BLOCK, so the stamp and the speaker name read
   as unexplained losses: `extra={'Haziq': 3, '24': 1, '28': 1, ...}`. The tool exited 1 and
   wrote nothing. A loop that had read the printed count instead of the exit status reported
   "DROPPED 169" while the corpus was untouched, which is worth remembering: **read the exit
   status, not the summary line.**

**Seven turns were skipped because an owner decision names them**, including ep39's `Ya.`
labelled Iqbal and ep42's `Yep.` labelled Zikri Kamarulzaman. Condition 5 prints them rather
than removing them silently. Those rulings answered "who said it", not "should it stay", so
they are a genuine conflict for the owner rather than something to resolve by inference.


#### The stance turns are kept and labelled `Speaker ?` (2026-09-16)

Owner's ruling on the 52 the drop lexicon deliberately excluded: *"leave the 52 then. think
the betul, setuju, kan etc is an answer of their own. and we cant identify whose speaking,
just leave is Speaker ?"*

That is CLAUDE.md rule 8's own convention, applied rather than invented. The turn carries
meaning, so rule 5 keeps it. No evidence can name it, so the label becomes the repo's
per-turn unknown instead of a wrong name. `drop_orphan_backchannels.py` grew a second closed
lexicon, `STANCE`, and a second verdict.

**33 relabelled, not 52.** The 169 drops and the merges that followed changed adjacency, so
19 of the original 52 no longer sit between two blocks of the same other speaker. The shape
condition is evaluated on the file as it stands, which is correct.

**Five were credited to a named GUEST, and that is the worse error.** Wong Chen (3), Nik
Nazmi (4), Amir Sahmat, Zaim Zulkifli and Iqbal each lost a false attribution. Putting
`Betul.` in a guest's mouth is a claim about a real person; `Speaker ?` is not.

**Guards: labels only.** The relabel refuses unless the exact block line appears once, and
two separate counters assert the change. One compares every word in the file, expecting only
the old speaker names to leave. The other compares SPOKEN words alone, because the first
cannot tell a speaker name from a spoken word. Measured on the real run: 16 files, 0 spoken
words lost, 0 gained.

**`check_published.py` had to learn about them, and the first attempt was wrong.** Its
`raw-unnamed-speaker` advice is "identify the speaker", which is exactly what must not
happen here. It now subtracts the deliberate unknowns by importing
`drop_orphan_backchannels.is_stance`, so the rule lives in one place and the two cannot
drift. A first version also emitted its own informational signature, and `qa_check.py`
folded that in as an issue: the flagged count went 35 to 47 across 16 episodes with nothing
wrong in any of them. An inflated count is the same defect as a false MISMATCH, so the
informational line was removed and only the exclusion kept. Back to 35 of 70.

### Unattended adoption, and the NTFS trap that blocked 12 episodes (2026-09-16, fixed 2026-09-17)

**`overnight_corpus.py` adopts without a person reading each diff.** That is a deliberate
departure. `nightly_recut.py` states at the top that it "Writes NOTHING to episodes/" and
that adopting is "a morning decision, taken after reading the diff, never by this script".
The owner changed the instruction: *"can we get the leftover episode by today? dont wait
for me, do one episode then move on to the next. Anything that need my clarification after
all else fails, bring it after the corpus is done so I can verify"*.

Three things made it safe enough to obey. The cast gate stops a blind reference at step 0.
The owner-decision gate stops a broken ruling at step 2. And `adopt_mai_camera_raw.must()`
now reads every write step's exit code, which landed the same day after ep61 shipped 704
filler words because a refusal was printed and then ignored.

It never passes `--force-blind-reference`, never uses `git commit --no-verify`, and never
retries a refusal with a looser flag. A refusal ends that episode and the loop moves on.
Everything refused lands in `data/_overnight_report.md` for one conversation at the end.

#### A colon in a tag became an NTFS alternate data stream

**12 episodes could not run through this pipeline, and the filesystem was the reason
rather than the models.** `ep01` through `ep06` exist in BOTH shows, so
`common.raw_for_tag` refuses the bare tag and asks for `ep05:bakar`. Every artifact in the
camera path is named from the tag: `data/camera_ref_<tag>.rttm`, `data/camera_ref_<tag>.uem`.

Measured on 2026-09-16, writing `data/camera_ref_ep05:bakar.rttm`:

```
target exists: True
BASE file created instead: True 0
listing match: ['_colon_test2_ep05']
```

The content went into a hidden `:bakar.rttm` **alternate data stream** on a 0-byte file
called `camera_ref_ep05`. `Path.exists()` returned True throughout, a directory listing
showed only the empty file, and git would have committed the empty one. So nothing would
have reported a problem: the reference would read as present, be silently empty, and the
adoption would run against nothing.

`overnight_corpus.remaining()` therefore excluded any tag that matched two episodes, and
said why at the exclusion.

#### FIXED 2026-09-17: `common.artifact_tag()`, plus a test so the 31st site cannot miss it

`common.artifact_tag(tag)` returns the filesystem-safe form, `ep05:bakar` to
`ep05-bakar`. It is for ARTIFACT NAMES ONLY. `common.tag_from_artifact()` reverses it.
Two tools need that reverse, because they discover episodes by globbing those names:
`check_camera_reference.py --all` and `check_overlap_boundaries.py --all`. The episode
tag itself keeps the colon everywhere else, because `raw_for_tag` and `resolve_tag`
already take that form.

The fix changed 30 sites across 22 scripts. The camera and adoption path holds most:
`adopt_mai_camera_raw.py` (the reference, the `_old_` copy, the candidate),
`mai_camera_raw.py`, `nightly_recut.py`, `overnight_corpus.py`, `corpus_status.py`,
`check_camera_reference.py`, `check_overlap_boundaries.py`, `fold_hanging_fragments.py`,
`move_hanging_words.py`, `name_generic_blocks.py`, `voice_witness.py`. The rewrite and
diagnostic scripts carry the rest.

Four things the fix turned up, none of them the colon itself:

1. **`check_camera_reference.py` exited 0 on a missing reference.** It printed `no
   reference at ...` and counted nothing. A caller reading only the exit code therefore
   read "usable". A named tag with no reference now counts as refused. The no-argument
   sweep still exits 0, because there nothing was asked for.
2. **`check_owner_decisions.py` globbed the bare tag** and would have died with `0
   episodes match ep05:bakar` at adoption step 2. It reads `common.raw_for_tag` now.
   `guest_gallery.py` had the same line.
3. **`corpus_status.py` showed one row per folder but looked up one reference per bare
   tag**, so both ep05 rows read the same file, and the ready and waiting lists printed
   tags no tool accepts. The tag carries its show there now.
4. **`overnight_corpus.remaining()` qualifies instead of dropping.** The queue went from
   3 episodes to 15, which is every unadopted episode `check_raw_engine.py` names.

**A second pass traced what the chain and the adoption actually invoke, and found four
more.** The colon was never the problem in these. Each one resolved the tag by globbing.

`merge_same_speaker.py` is the one that matters, because it failed in silence.
`--episode=ep06:berhenti` was tested as `only not in d.name` against a folder slug, so it
matched NO folder, and the run touched nothing and printed no error. Rule 6 would have
gone unenforced on all twelve episodes. The filter is now an exact folder from
`common.raw_for_tag`, so a bare ambiguous tag refuses and names its candidates. That is
the opposite of the trap at the top of that file, where a bare tag edited every episode.

`split_mixed_blocks.py` and `score_attribution.py` exited `no raw.md`, and
`verify_speaker_voiceprint.episode_dir` raised `matched 0 episode folders`, which took
`voice_witness.py` down with it. All three read `common.raw_for_tag` now.
`score_attribution.py` needed `from common import raw_for_tag` rather than `import
common`: `common` is already a local in its `main()`, holding the set of seconds every
system labelled, so the module was shadowed and the first run raised
`UnboundLocalError`.

**The mechanism is `scripts/test_tag_paths.py`.** A fix applied by hand at 30 sites is a
fix the 31st site will miss. The test round-trips the two helpers first. It then scans
`scripts/*.py` for an f-string that puts a tag placeholder next to a filename extension
or a path separator. A line holding `artifact_tag` passes. Globs against `episodes/` pass
too, because a glob is not a filename. To check the test itself, add
`f"data/camera_ref_{tag}.rttm"` to any script: it failed with that file and line, and it
passed again once the line was gone.

**One bug in `overnight_corpus.py` itself is worth keeping, because it is the same class.**
Its `run()` helper returned `out[-tail:]` with a 4000-character default, and
`remaining()` parsed that truncated text. The six `yang-bakar-menteri` rows sit at the TOP
of `check_raw_engine.py`'s listing, so they were cut, and the function reported 13
unambiguous tags when the answer is 9. It had never seen the duplicates it existed to
exclude. `tail=0` now means do not truncate.

### `check_cast.py` stripped one honorific, and Malaysian titles come in stacks

Found on 2026-09-17 during a session-close audit. `check_cast.py` reported ep02:bakar as
`missing-from-cast`: raw.md labels `Prof. Barjoyai`, while `guests:` holds
`Prof. Emeritus Dr. Barjoyai Bardai`. Rule 3 says exactly this shape is correct, because
the frontmatter takes the full name and the body stays verbatim.

The gate has an extension test for it, and the test could not see the match. Its
`HONORIFIC` pattern was anchored and unquantified, so it removed `Prof. ` and stopped.
`Emeritus Dr. Barjoyai Bardai` is not a prefix of `Barjoyai` in either direction. The
pattern now repeats over a run of titles and knows `Emeritus`. The loop then retries the
extension test on the stripped forms.

**Why it matters beyond one episode.** A false finding trains the next session to read
that gate as noise. The cast check exists to catch a real one: raw.md naming a person the
frontmatter never lists. ep02's name is not that, and it was the only finding the gate
had. Corpus-wide the count is now 0 of 70.

One care point in the widening. `bare` at the same line feeds the separate ABSENT
signature. That signature needs the cast AND the speakers. Splitting out a cast-only set
without keeping `bare` raised a `NameError` on the first run.

### ep00 is a wide stage shot, so the face detector was blind to it (2026-09-17)

ep00 is the pilot, recorded live in a hall on 2025-05-10, not in the studio. The camera
sits at the back and holds a wide two-shot. The title screen fills the top third of the
frame and a face is about 20 pixels tall.

YuNet cannot detect a face that small. That is the whole of the reference's
`no face 2960s` out of a 7938 second runtime, and of Haziq landing on 51 seconds, 1.2% of
the reference, against 8.7% of raw.md's words. `check_camera_reference.py` refused the
reference, correctly, and the episode was adopted under `--force-blind-reference`.

**Cropping the stage strip and upscaling it makes the same frames readable.** The command
that proved it, on clips already in `data/frames_cache/`:

```
ffmpeg -i <clip> -vf "fps=1,crop=150:170:195:100,scale=600:-2,tile=5x1" out.png
```

The face, the glasses and the microphone at the mouth all become clear. So the camera
signal was present the whole time and the detector never saw it.

**Read this as a class, not as one episode.** Any live or stage episode has the same
framing, and the detector has been silently blind to all of them. ep05:berhenti came out
of the chain the same day at 7% identified and 35% coverage, which is the same signature.
The fix to build is a crop-and-upscale pre-pass: detect on the enlarged strip, then map
the box back to full-frame coordinates. For ep00 that would replace 56% confident
coverage with a real reference, at the cost of one more camera pass of about 88 GPU
minutes.

#### What the zoom settled, and the two labels it could not

The owner's ruling at `[05:42]` is the identity anchor. Haziq is the man in the maroon
polo with glasses on the left; Rafizi is in the patterned batik on the right. From there
the zoom read four blocks the reference had wrong, all of them in the forum section where
the public asks questions from the floor:

| block | was | is | evidence |
|---|---|---|---|
| 1:51:44 | Audience | Rafizi | he lifts the mic to his mouth at 1:51:45; Haziq's is in his lap |
| 2:02:17 | Haziq | Rafizi | Rafizi on mic for all five seconds; the caption runs the sentence through the split |
| 1:50:50 tail | Haziq | Audience | Haziq lowers his mic at 1:51:03, as the tail's first word lands |
| 1:57:51 tail | Haziq | Audience | same shape, 1:58:03 |

Two more needed the owner's ear, because the camera looks away at both. `[2:11:29]` cuts
to the wide hall 0.4 seconds before the words start, and `[1:12:20]` is a reaction shot
of Rafizi listening while the interviewer speaks off frame. The owner ruled Rafizi and
Haziq. Both are recorded in `data/speaker_adjudications.json` under
`ep00_owner_ruled_2026_09_17`, and all five enforceable changes are in
`data/forced_labels.json` under `ep00`, so a rebuild keeps them.

**One trap in writing those rules.** `mai_camera_raw.py` applies its own name corrections
BEFORE `force_labels()`, so an anchor carrying a name the map rewrites fails on the next
rebuild. The 1:50:50 anchor originally ran through `Haziq Asfar`, which
`fix_proper_nouns.py` now corrects to `Haziq Azfar` at the owner's word. Stop an anchor
short of any name a map can touch.

### Two `check_published.py` flags fired on correct work (2026-09-17)

Both surfaced the first time a MAI adoption met a fresh regeneration, and each one pointed
a session at work that was already right.

**The `Speaker ?` exclusion was inverted.** The published-placeholder flag asks whether
raw.md carries `Speaker ?` itself, and it asked `raw_generic` after the raw-side loop had
already subtracted the deliberate unknowns and deleted the key. So an episode whose
unknowns are ALL deliberate lost the key and had its published files flagged, while an
episode with a mix kept the key and was excluded. ep08, ep11, ep18, ep19 and ep21 were
each reported for faithfully copying out a label the owner asked for: `Betul.`, `Kan.`,
`Alhamdulillah.`, every one from the STANCE lexicon in CLAUDE.md rule 5. Fixed by
capturing `raw_has_unknown` before the subtraction. The ep33 case it exists for still
fires: there the published file prints `Speaker ?` while raw.md holds none.

**`Audience` is a sanctioned label and was being reported as a gap.** CLAUDE.md rule 9
says so in as many words. `Multiple speakers` never reached the flag because
`label_drift_audit.GENERIC` does not list it, so only `Audience` was ever caught, and
ep00's 20 turns came back as `raw-unnamed-speaker` telling the reader to go and identify
a member of the public with video frames. The same comparison missed that
interview-ms.md's `Hadirin` and raw.md's `Audience` are one concept, so the faithful
translation read as the rewrite discarding a name. A `SANCTIONED` prefix pattern now
covers all three role words in both places.

Corpus-wide, `check_published.py` went from 12 flagged episodes to 7. Nothing was masked:
ep31, ep41 and ep61 still report a published `Speaker ?` their raw.md does not support,
and all three are in the regeneration queue.

### `move_hanging_words.py --write` refused a whole batch when two moves chained (fixed 2026-09-18)

ep11 held four movable tails and `--write` refused all of them with `REFUSING: '[1:30:31]
Iqbal: think apakah ...' is not unique`. The anchor was unique in the file. The tool applied
the moves in stamp order against a running copy of the text, and the third move (1:30:24
into 1:30:31) rewrote the 1:30:31 header to carry the new stamp and the moved words. The
fourth move (1:30:31 into 1:30:42) then looked for the old 1:30:31 header, found zero
copies, and the `!= 1` guard reported it as "not unique". Nothing was written, so ep11's
four tails and ep10's seven sat in the adopted raw after adoption reported success, and the
handoff recorded it as "refuses a whole batch when one anchor is not unique".

The fix is one word: the loop now runs `reversed(moves)`. A move only rewrites its own
block's tail and the NEXT block's header, so applying the latest move first leaves every
earlier anchor intact. Two moves that chain (B receives A's tail and gives its own tail to
C) are the only case the order matters for, and reversed order handles it. The word-order
guard and the stamp-order guard run unchanged after the loop. Result: ep11 4 tails and
ep10 7 tails moved, rule 7 went 6 contested to 2, and the two left (ep06:berhenti) are
shapes no tool moves: a whole block the camera reads as the first speaker, and a next
block whose HEAD belongs to the previous speaker.

### ep06:berhenti's two contested boundaries, ruled by ear (2026-09-18)

The two `?t=` links from the previous section's fix went to the owner. Both rulings
were confirmed against the camera before writing, per rule 4's evidence order.

**29:36, a WHOLE-BLOCK relabel, not a tail move.** The block was labelled Zaim Zulkifli
and reads as Rafizi continuing his own previous sentence: "...subjected to the collective
responsibility, responsibility kepada kementerian," (29:27, Rafizi) into "responsibility
kepada stakeholders yang berjuta-juta ni." (29:36). Owner: "Rafizi speaking. can check
with camera reference." The rttm reads Rafizi across 1774-1782s, spanning the block.
Relabelled and merged into the 29:27 block under rule 6.

**36:26, a HEAD move, the mirror of the tail case `move_hanging_words.py` already
handles.** Zaim's 36:18 block ends mid-sentence with no terminal punctuation ("...bukan
si- sistem, simptom"); the sentence's completion, "yang sebenarnya menjadi enabler
kepada sistem itu.", was sitting at the START of the next block (Rafizi, 36:26) instead
of the end of Zaim's. The tool only looks for a tail hanging off the END of a block, so
it never proposed this move. Moved by hand, guarded the same way: exact substring,
asserted unique, word order preserved. Camera reads Zaim_Zulkifli across 2178-2186s
(the sentence's completion) and Rafizi from 2190s, consistent with the ruling.

Both recorded in `data/speaker_adjudications.json` under
`ep06:berhenti_rule7_owner_ruled_2026_09_18`. `check_overlap_boundaries.py --all` is
back to 0 contested corpus-wide.

## Siri Forum BERSAMA, a third series, 2026-09-27 and 2026-09-28

### 1.59: A forum video is not a podcast video, and five fixes it needed

The owner added a new series on 2026-09-27: live public forums on the same channel, a
moderator, a panel of four, and questions from the floor. Two episodes: `ep01:forum`
(tKxIBnLIJkA) and `ep02:forum` (Byir6MLBXIQ). The standard raw.md pipeline ran on both, and
five things broke or needed a change.

1. **Two series were hardcoded.** `common.show_era_dir()` knew only the two podcast
   eras, and four scripts built `yang-{x}-menteri` by hand (`corpus_status.py`,
   `overnight_corpus.py`, `adjudicate_speakers.py`, `frames_at.py`). The forum ids are in
   `common.FORUM_BERSAMA_VIDEO_IDS`, the folder is `siri-forum-bersama`, and every site now
   takes the suffix from the folder name, so `ep01` refuses and lists three options.
2. **The shared face gallery named only Rafizi.** The first camera reference covered 39%
   of ep01, with 5,039 talking seconds on unknown faces. The fix was a gallery for each
   video, built from the pre-roll cover card: the card shows every panellist with a
   printed name, and the census puts each card face in its own cluster of exactly 94
   (ep01) or 89 (ep02) faces. The live clusters were scored against those card faces and
   against earlier corpus galleries (Nik Nazmi, Wong Chen, Sum Dek Joe), and coverage rose
   to 76% and 78%. Faizal Rahman scored 0.526, under the 0.55 floor, and was named only
   because he was the one panellist left and the next name scored 0.152.
3. **A new episode has no committed raw.md.** `adopt_mai_camera_raw.py` reads the
   committed file for owner decisions. For an uncommitted episode, pass
   `--current <local raw>`.
4. **The camera gave floor questioners to panellists.** In the Q&A the camera stays on a
   panellist while someone in the hall speaks. `2:42:34 Rafizi: Saya Yusof bin Ibrahim
   daripada Pahang` was one of four. pyannote put each questioner in a separate cluster
   with no camera overlap, and that is what caught them. The fixes and their evidence are
   in `data/_forum/ep0N_relabels.json` (local), and the owner's rulings are in
   `speaker_adjudications.json`.
5. **The video overshoots the forum.** A party song and room talk run before and after.
   Owner's ruling: raw.md keeps only the formal forum, from the moderator's opening to his
   closing thanks.

### 2.13: One cleaned transcript per forum, and six checkers that could not see it

The owner's spec: no interview files. One full-length, lightly cleaned transcript in the
original mixed language, following Hansard rules, because "this forum is like parliment
setting on its own". `rewrite_segments.py --forum` does it with `FORUM_PROMPT_TEMPLATE` on
the mixed stage only, and `--write` makes `transcript.md` with the cast from
`FORUM_CAST` (the cover card). The length gates are the normal full-length ones.

The first `--write` passed every checker because no checker read the file.
`check_published`, `check_figures` (through `DERIVED`), `check_names`, `check_slurs`,
`check_agencies` and `check_cast` all opened `interview.md` by name. Each now falls back to
`transcript.md`.

Adding a speaker called `Nik Mustapha Nik Hassan` made `check_cast.py` flag ep49, which
introduces `Nik Nazmi`: the rule matched on the first word only, and `Nik` is a name
prefix. Prefixed names (`Nik`, `Wan`, `Syed` and similar) now match on two words.

The fact check before the rewrite (`check_raw_facts.py`) listed 484 capitalised words
across both raw.md files. 35 were MAI garbles, each confirmed against the caption track and
a web source, and added to `fix_proper_nouns.py`. Several also corrected podcast
episodes: `Jolo` (Jho Low) x17, `Akmal Salleh` (Saleh) x102, `Zafrol` (Zafrul) x19. One
pattern, `Faizah Rahman`, was applied corpus-wide by mistake and changed ep41, where the
name is not sourced. ep41 was restored from git, and the pattern is now anchored to the
forum's own phrase.

## ep66, a free ASR engine test, and the owner-edit install, 2026-10-02 to 2026-10-04

### 2.14: The Azure credit ends about 2026-10-07, and a free engine was scored against two owner edits

MAI-Transcribe-2 stays the engine. The question was whether a free local engine could replace
it when the credit ends. `scripts/local_asr_words.py` runs a local engine over one episode
and writes its words in MAI's response shape, one phrase per pause of 0.2 s or more.
`ASR_WORDS_DIR` (read by `mai_camera_raw.py` and `move_hanging_words.py`) points the whole
adoption pipeline at those words, and `compare_owner_edit.py` scores the result against the
owner's hand-corrected raw.md. Camera, pyannote and voice witness are unchanged, so only the
words engine differs.

| engine | ep65 words different | ep65 labels right | ep66 words different | ep66 labels right |
|---|---|---|---|---|
| MAI-Transcribe-2 | 0.6% | 98.5% | 1.0% | 93.2% |
| Whisper-large-v3-turbo | 15.8% | 98.2% | 14.1% | 93.0% |
| malaysian-whisper-medium-v2 | 16.8% | 97.9% | not run | not run |
| Polyglot-Lion-1.7B | 23.4% | 97.9% | not run | not run |

The word columns favour MAI, because the owner edited MAI's text. The label columns do not.
Polyglot-Lion is out: no punctuation, numbers spelled as words, Chinese characters for filler
sounds. Whisper-turbo is the free fallback; the owner reads about 3,200 differing words per
episode against about 200 for MAI.

Two traps. A 28 s VAD chunk as one phrase gave 14 to 18% of the owner's speaker changes,
because the pipeline labels a phrase as a whole; splitting at 0.2 s gave 55%. And
`run_engine_trial.py`-style scripts restore raw.md with `git checkout`, which does nothing for
a new episode whose folder is untracked: back the file up and restore from the backup.

### 2.15: `install_owner_edit.py`, and a replacement that destroyed a spoken self-correction

The owner's edited copy has turns with no timestamp. `scripts/install_owner_edit.py` stamps
each from MAI's word times, refuses a label no speaker of the episode uses (it caught
`RafiziL`, `HAziq` and three missing colons) and refuses backwards stamps. Stamps are
compared in whole seconds, because a stamped turn after a fractional one looked backwards.

The fact check on ep66 verified 76 names and acronyms through one read-only subagent and
corrected 25 spellings. One blanket replacement was wrong: `Seremban 2` to `Seremban 3`
matched 4 times where the web check expected 1, and the owner's text at 2:41:09 reads
`Seremban 2 ke Seremban 3 ni. Seremban 2 ke Seremban 3? Seremban 3.`, a spoken
self-correction. A count that differs from the expected count has to stop the run, and a
speaker's own slip stays verbatim. All four were restored.

Honorifics: the sources disagree on `Datuk` and `Dato'`. The PMO profile writes `YAB Dato'
Seri Anwar` and its 2022 headline `Datuk Seri`; Parliament writes `Dato' Sri Haji Tajuddin`;
Najib's own style is `Dato' Sri`, which the show's ep65 title uses. ep66 now uses the form each
person's own source gives for Najib, Tajuddin, Raffe Chekku, Shahrir Abdul Jalil and Aidit
Ghazali. Anwar and everyone else stay `Datuk`. The rest of the corpus uses `Datuk Seri` 1,901
times and `Dato' Seri` 15 times, so ep66 is now inconsistent with it for those five people.
37 verified entities went into `data/entity_roster.json`.

### 2.16: Honorifics: the grade is spoken, the spelling follows the person's own official source (2026-10-04)

The owner asked for a corpus-wide check of Dato', Datuk, Tan Sri and similar, with raw.md and the
interview files staying true to what is spoken in the video.

The grade is audible and is never changed. The YouTube caption track agrees with raw.md's grade in
2,311 of 2,315 located mentions (99.8%), so a title that differs from the person's real one, such
as `Datuk Seri Hadi` written 237 times for a Tan Sri since 2021-11-13, is the speaker's own and
stays. `check_honorifics.py` prints these as INFO and fixes nothing. Of the 4 caption
disagreements, one was a parser bug (`tunjukkan` read as `Tun`), one a stutter, one a correct
`Datin Seri Rosmah`, and one a real MAI garble: ep54 29:54 `Datuk Seri. Tan Sri Mat Nor` where the
captions hear `Datuk Seri Sanusi Mat Nor`. That line is not fixed yet.

Dato' and Datuk, Seri and Sri are said the same way, so the spelling follows the person's own
official page, one form per person. The rule (says.com) is: Dato' and Dato' Seri from the nine
state rulers, Dato' Sri only from the Sultan of Pahang, Datuk and Datuk Seri from the Agong or a
governor; there is no `Datuk Sri`. The authority is the register of federal and state honours at
istiadat.gov.my: the page carries all 115,725 awards as a JavaScript array, with the conferring
authority and the title per award (it holds no Johor awards). It confirmed 21 of 22 roster
entries; Saifuddin Abdullah's only Seri-grade award is Pahang's, so he is `Dato' Sri`, though
Parliament writes `Dato' Seri`.

Result: `data/honorific_roster.json` (22 people, 79% of the Datuk/Dato' mentions in raw.md) and
`scripts/check_honorifics.py`. 6,567 token changes in 276 files, every one a title spelling
(5,537 Datuk to Dato', 817 Datuk Seri to Dato' Sri, 180 Sri to Seri, 7 Seri to Sri) or UITM to
UiTM. The 7 episodes whose owner-decision gate shows a mismatch or an unlocatable ruling show the
same numbers before and after.

Traps. A subagent's web table listed "GRADE MISMATCH" rows (Hadi, Najib `Datuk Najib` x12) and
applying them would have rewritten what the speaker said. A bash heredoc halves backslashes, so
a regex written in one became a control character twice; write scripts with the file tool.
`Seremban 2` in ep66 is a spoken self-correction and stays.

## ep67, the first episode on local Whisper, 2026-10-09 to 2026-10-10

### 2.17: The guest's face was never in the gallery, and the gate could not see it

- **Context:** ep67 ran the new local path (Whisper-large-v3-turbo, pyannote, camera). The
  owner edited the pipeline raw.md and found Sum Dek Joe, a recurring guest the YouTube
  description names ("penyertaan Saudara Sum Dek Joe"), labelled `Speaker 4` and `Speaker ?`.
  Against the owner's copy the pipeline was 88.0% right on labels, and 2,028 of Joe's words
  were `Speaker 4`.
- **Cause:** ep67 had no per-video face gallery, so the shared gallery ran (Rafizi, Haziq,
  Farhan, Zaim). Joe was an unknown face, so the camera reference left his seconds out. His 30
  face vectors were already in the ep60 and ep63 galleries and nothing copied them. The
  cast gate passed because it reads the names in the pipeline raw.md, which had no Joe label.
  Rule 9, step 3 (the description) was not applied, and the handoff wrote "probably Joe".
- **Measured:** with Joe added, the reference names 923 s of him and leaves Rafizi's 10,586 s
  unchanged. Against the owner's labels it agrees on 99.0% of 496 camera seconds in his blocks
  (2.1% of the seconds in Rafizi's blocks show Joe, the cut lag). After the owner's copy was
  installed, `check_camera_reference.py` refused the old reference ("Sum Dek Joe ... MISSING")
  and accepted the new one.
- **Fix:** `camera_speakers.py reference` seeds the guest vectors from the description
  (`seed_guests_from_description`). With no gallery, it rebuilt the identical RTTM. It also
  seeds a person the description only mentions (Wong Chen); that face matched nobody in the
  output. `install_owner_edit.py --also-known` lets the owner's label through.
- **Not fixed:** a guest new to the corpus; see ARCHITECTURE.md, Known limits.

### 2.18: Stamps are already accurate; a threshold only makes them worse

- **Test:** 390 stamped blocks, each located in two independent word timelines: the caption
  and the Whisper forced-alignment times. Stamps are whole seconds, so a median offset of 0.5 s
  early is rounding down. Against the Whisper times 95% of stamps are within 1.0 s.
- **Result:** retiming from the caption made the stamps worse against the Whisper times (mean
  error 0.38 s kept, 0.47 to 0.51 s at any threshold from 0.5 s to 5 s). Retiming from Whisper
  gained nothing against the caption. `check_timestamp_drift.py` is not usable at this scale:
  its noise floor is 100 to 250 s.
- **Rule used:** move a stamp only when both timelines agree within 1.5 s and the stamp is off
  by more than 2 s. That moved 4 of 390. One timeline alone fails to locate about a third of
  the blocks (short or edited openings), so a single source is not trusted.
- **`move_hanging_words.py`:** a one-word tail such as `Dia` matched an earlier `dia` nearer
  the block's stamp (ep67 1:36:05 took 1:36:03) and the adoption stopped with "stamps would run
  backwards". A moved tail is now never stamped before its own block.

### 2.19: Smaller lessons from ep67

- `rewrite_segments.py` buffers its output when redirected, so a background run's log stays
  empty for the whole run; use `python -u`. Progress shows in the work directory.
- A figure gate trips when the English stage writes `3-4,000` as `3,000 to 4,000` or `50 ribu`
  as `50,000`. Read the text before accepting; the figures were present.
- `fix_proper_nouns.py` is corpus-wide: adding `eFishery` also corrected ep56 and ep57.
- A bash heredoc corrupted a regex's word-boundary escape again (see 2.16). Use the file tool.
