# Architecture

How an episode goes from a YouTube URL to four transcript files: the models and tools
in the stack, how to set it up and run it, and how the output gets verified.

This file describes the stack **as it currently stands**. Every failure I hit while
building it is in [ENGINEERING_LOG.md](ENGINEERING_LOG.md),
numbered `1.x` for the transcription stage and `2.x` for the rewrite stage. References
below of the form "1.17" point there.

## Pipeline

```mermaid
flowchart TD
    A[YouTube playlist] -->|build_manifest.py| B[data/manifest.json]
    B --> C[transcribe_episode.py / batch_process.py]
    C --> D[yt_download.py: download audio]
    D --> E{Raw stage engine}
    E -->|"--engine gemini (default)"| F["lib_gemini.py:<br/>upload audio, transcribe_raw"]
    E -->|--engine local| G["lib_local_asr.py:<br/>mesolitica Whisper + Silero VAD"]
    F --> H[raw.md]
    G --> H
    H --> I{Rewrite stage engine}
    I -->|"--rewrite-engine gemini (default)"| J["lib_gemini.py:<br/>rewrite_clean, translate, extract_metadata"]
    I -->|--rewrite-engine claude| K["lib_claude_rewrite.py:<br/>claude CLI headless"]
    J --> L[interview.md, interview-en.md, interview-ms.md]
    K --> L
    L --> M[qa_check.py audit]
    M --> N[QA_CHECKLIST.md]
```

Each episode goes through two independent stages, and each stage can run on either
of two engines:

| Stage | Default engine | Fallback engine | Flag |
|---|---|---|---|
| Raw transcription | Gemini (audio in, transcript out) | Local ASR (`mesolitica/malaysian-whisper-medium-v2`) | `--engine local` |
| Rewrite, translate, metadata | Gemini (chunked text calls) | Claude CLI (`claude -p`, headless) | `--rewrite-engine claude` |

The two stages are split on purpose: a failure partway through the slow,
audio-dependent raw stage never loses work from the (comparatively fast) rewrite
stage, and the two stages turned out to need different fallbacks for different
reasons (see below).

## The stack

| Job | Tool | Why this one |
|---|---|---|
| Playlist and metadata | `yt-dlp` via `build_manifest.py` | Also the source of every episode description, which settles guest names (1.20) |
| Audio download | `yt-dlp` + `bgutil` PO-token server + Node | The only client/format combination YouTube still serves (see setup) |
| Raw transcription (default) | Gemini `gemini-3.7-flash` | Transcribes and diarizes in one pass; handles a 3.5hr episode inside the 65k output limit (1.4) |
| Raw transcription (fallback) | `mesolitica/malaysian-whisper-medium-v2` + Silero VAD | Malay-specific; runs offline when Gemini is unavailable or billing-blocked (1.2, 1.15) |
| Speaker labels, fallback path | `pyannote.audio` 3.1 + forced alignment | Local ASR has no diarization of its own. Unreliable on some episodes -- see Known limitations |
| Rewrite / translate / metadata (default) | Gemini, chunked text calls | |
| Rewrite / translate / metadata (fallback) | `claude` CLI, headless (`claude -p`) | Uses an existing Claude Code seat rather than an API key (2.1) |
| Ground truth for verification | YouTube auto-captions (`audio/<video_id>.ms.vtt`) | Free, already downloaded, and they cover the full runtime (1.11) |
| Second, independent recording | `@mediarakyat` re-uploads of the same episodes | Their captions are generated separately, so a finding can be confirmed without reusing the same caption run. They also supplied captions for two episodes that had none. They do not cover ep03-14 (1.16) |
| Timing sanity | `check_timestamp_drift.py` | Head-phrase match against captions (1.23) |
| Content-loss detection | `check_caption_coverage.py` | 4-gram coverage, starts from the audio (1.25) |
| Everything else | `qa_check.py` into `QA_CHECKLIST.md` | Runs every known failure signature; verdicts persist in `data/qa_reviewed.json` (1.21) |

Hardware: one RTX 2070 (8GB). A second GTX 970 in the same machine is too old for the
CUDA builds used here, so always set `CUDA_VISIBLE_DEVICES=0` (1.3).

**Episode tags are ambiguous and the tools used to resolve them wrongly.** Both shows have
an ep01 through ep06, and they are different episodes; every tool picked its match with
`[0]`, silently taking whichever the manifest listed first, and all six of those tags are in
the rewrite backlog. Use `common.resolve_tag`, which raises with the candidates listed, and
disambiguate with `ep03:bakar` / `ep03:berhenti`. `splice_gap.py` still carries the old
pattern (2.3).

## One-time setup

Requires Python 3, Node.js, ffmpeg, and a `GEMINI_API_KEY`. The local ASR fallback
additionally needs `HF_TOKEN` for pyannote.

YouTube blocks most `yt-dlp` client/format combinations behind PO tokens, SABR-only
streaming, or DRM. The working combination is the `web_embedded` client, a locally-run
PO-token server, and Node.js for JS challenge solving.

```bash
pip install -r requirements.txt

# Build the PO token server once
git clone https://github.com/Brainicism/bgutil-ytdlp-pot-provider ~/bgutil-ytdlp-pot-provider
cd ~/bgutil-ytdlp-pot-provider/server && npm ci && npx tsc

# ffmpeg is required to remux yt-dlp's raw DASH audio fragments into a valid
# container; without it, Gemini's Files API rejects the upload outright.
winget install Gyan.FFmpeg
```

`scripts/yt_download.py` starts the PO token server automatically if it isn't already
running, and passes `--ffmpeg-location` explicitly (falling back to the winget install
path if `ffmpeg` isn't on `PATH`).

Uploads must force the mime type to `audio/mp4`: the SDK auto-detects `.m4a` as
`video/m4a`, which Gemini's backend silently fails to process (no video track).
`scripts/lib_gemini.py`'s `upload_audio()` handles this.

**Environment variables on Windows.** `HF_TOKEN`, `SPEECHMATICS_API_KEY` and
`GEMINI_API_KEY` are persisted at User scope, but a fresh shell doesn't always
inherit them, and re-persisting appears to work then fails again next session. Read
them from the user environment inside the script, or set them per-run:

```powershell
$env:HF_TOKEN = [Environment]::GetEnvironmentVariable('HF_TOKEN','User')
```

## Running

```bash
# Refresh the episode manifest from the playlist (only episodes >= 1 hour)
python scripts/build_manifest.py

# Process one episode, or everything not yet done (oldest first)
python scripts/transcribe_episode.py <video_id>
python scripts/batch_process.py

# Same, but with either stage on its fallback engine
python scripts/batch_process.py --engine local
python scripts/batch_process.py --rewrite-engine claude

# Audit every episode for known failure signatures, writes QA_CHECKLIST.md
python scripts/qa_check.py
```

### Repair tools

For an episode that's missing content or badly mistimed. **Run the alignment first.**
Establish ground truth before you cut any audio. That is the lesson of 1.18 and 1.24,
and I wasted two transcription runs learning it.

```bash
# Where does each block's text ACTUALLY occur in the audio?
python scripts/align_blocks.py ep48
python scripts/block_origin_map.py ep48

# Replace only the damaged middle, keeping the verified head and tail verbatim
python scripts/splice_gap.py ep48 --clip-start 8500 --keep-until 8960 --gap-from 8960 --gap-to 11071 --tail-from 8966

# Text is fine, clock is wrong: move the timestamps to where the caption says the text
# is, touching nothing else. Needs align_blocks.py first. Dry run by default (1.42)
python scripts/retime_blocks.py ep61
python scripts/retime_blocks.py ep61 --write

# One person's continuous speech arrives as several turns, because the diarizer cuts at
# PAUSES not speaker changes: ep41 had "[2:53:13] Rafizi ... / [2:54:43] Rafizi: Aku /
# [2:54:44] Rafizi: orang cakap pasal Climate change". Merges same-NAMED-speaker runs, and
# folds an unknown backchannel turn ("Hmm", "Hehe") into the named turn before it. Two
# consecutive `Speaker ?` turns are NOT merged -- that would assert one unidentified
# person where nobody claimed one (2.6)
python scripts/merge_same_speaker.py
python scripts/merge_same_speaker.py --write

# Free the derived scratch: 8.2 GB of decoded WAVs that ffmpeg rebuilds on demand, plus
# gate backups and frame caches. Never touches audio/*.m4a or audio/*.vtt (both sources),
# never touches a git-tracked file, and refuses to run while a gate is mid-flight
python scripts/cleanup_scratch.py
python scripts/cleanup_scratch.py --write

# Re-extract an episode's `topics:` and keep it only if it covers more of the episode's
# own YouTube chapter markers. The metadata prompt used to say nothing about topics, so
# five episodes carried ONE line for three hours. Coverage decides, not line count (2.8)
python scripts/gate_topics.py --report
python scripts/gate_topics.py ep35 --write
bash scripts/gate_topics_batch.sh --all

# Put every frontmatter list item back on one line. yaml.dump wrapped at 80 chars and the
# regex readers stop at the first continuation, so 24 episodes' topic lists were silently
# truncated -- ep11's twelve read as three (2.8)
python scripts/normalize_frontmatter_lists.py --write

# Speaker labels that appear in interview*.md but never in raw.md
python scripts/label_drift_audit.py

# A turn marker buried mid-paragraph inside another speaker's block, so the words after
# it publish under the wrong name. Also drops a leading label holding NO words, which is
# a diarizer segment the ASR returned nothing for. ep53 hid six of these plus four
# wordless labels, one of them a whole run-sheet segment publishing as Rafizi (2.6)
python scripts/split_inline_turns.py
python scripts/split_inline_turns.py ep53 --write

# Correct ASR-garbled proper nouns from a reviewed map, one entry per owner decision.
# NOT a majority-vote normaliser: the majority spelling is wrong for Fuziah Salleh and
# right for Akmal Saleh, in the same corpus (2.5). Re-run after any gate batch, which
# copies its own output back over the episode directory
python scripts/fix_proper_nouns.py
python scripts/fix_proper_nouns.py --write

# Remove the Whisper subscribe-boilerplate hallucination, `Sila berasa bebas untuk
# menyukai, melanggan, ... lajur Der Spiegel dan Diandian`, a sentence nobody on the show
# says. Only the SPAN goes, never the enclosing sentence: it lands mid-sentence inside real
# speech. A span is deleted only if every word in it comes from the hallucination's own
# lexicon, which is what refuses a pattern that has drifted into real speech or stopped
# mid-word. `Jangan lupa untuk melanggan` is a REAL host plug and must survive (2.9)
python scripts/remove_asr_boilerplate.py
python scripts/remove_asr_boilerplate.py --write

# Name the `Speaker N` labels the rewrite left in the PUBLISHED files, using raw.md as
# the key. Dry run by default; it prints the agreement it found and refuses anything a
# literal trace of the turn's opening clause does not confirm (1.40).
python scripts/name_published_placeholders.py
python scripts/name_published_placeholders.py ep54 --apply

# Regenerate a rewrite into a sandbox and keep it ONLY if it measures better than what
# is already there, on completeness, Malay density and generic-label count. A re-run is
# a coin flip -- ep61 gave 24/32/63/39% on identical input -- so regenerate_rewrites.sh
# overwriting in place is not safe on an episode whose rewrite is merely imperfect (2.3)
python scripts/gate_rewrite.py ep02:berhenti --score-only
python scripts/gate_rewrite.py ep02:berhenti --tries 2
```

For an episode whose speakers may be named wrongly. **Confirm against the audio before
renaming anyone.** A whole-episode mislabel is invisible from inside that episode, so
text evidence alone is not enough (1.27).

```bash
# Which label is really Rafizi? Voiceprints, no LLM involved
python scripts/verify_speaker_voiceprint.py --all-suspect

# Is one label hiding two voices?
python scripts/verify_speaker_voiceprint.py --episodes ep42 --per-block "Zikri Kamarulzaman"

# No labels at all, because diarization collapsed? Score the blocks, not the clusters
# (1.31) -- mean similarity says who a block mostly is, and the agreement between a
# block's own samples says whether it is one voice at all.
python scripts/verify_speaker_voiceprint.py --episodes ep45 --per-block Rafizi

# Apply the rename. A swap needs a single pass, which is the whole point of this tool
python scripts/relabel_speakers.py ep36 "Cincong=Rafizi" "Rafizi=Cincong" --dry-run

# When both methods above have run out: one HTML page of every unresolved numbered
# cluster, each linked into the video 6s early with the turn either side for context.
# Prints no guess, because text adjacency does not carry direction (2.6)
python scripts/adjudicate_speakers.py

# A co-host buried inside a long block labelled Rafizi. Two text signals, both independent
# of the label under suspicion: a vocative "YB" (never Rafizi, he IS the YB) and run-sheet
# phrasing. Locates the SECOND to look at, via word-level caption timings.
# CAVEAT (2.6): it windows each block as [start, next_block_start), so it under-scans when
# a block's words run past the next block's timestamp. That false negative is why ep41's
# buried question survived a pass with this tool -- fix the timing first
python scripts/cohost_candidates.py ep41 ep53 --min-block=120
```

Timestamps for a turn split out of a long block come from the episode's caption track
(`audio/<video_id>.ms.vtt`), not from reusing the parent block's stamp. ep41's split sits at
95% of a 13,756-character block, where reuse would have been 17 minutes early. The caption
`>>` markers are NOT a speaker-change signal, however much they look like one (2.6).

After relabelling `raw.md`, regenerate the rewrites rather than renaming inside them:
`interview*.md` label sets drift from `raw.md` in ways no mapping can express (1.27).

**Every regeneration needs the same three steps after it.** The metadata stage rewrites
`hosts`/`guests` from scratch and reverts speaker labels to `Rafizi Ramli` each time, so
skipping these silently undoes work:

```bash
python scripts/rebuild_roster.py --write            # hosts/guests, incl. presence calls
python scripts/normalize_speaker_labels.py --write  # short-name convention in the bodies
python scripts/build_episode_index.py               # episode tables in both READMEs
python scripts/qa_check.py                          # then read QA_CHECKLIST.md
```

Regenerate several episodes as separate OS processes rather than sequentially or in
threads: six episodes took 33 minutes in parallel against 26 minutes *each* in series, and
`lib_claude_rewrite` keeps the current model in module-level state that would interleave.

```bash
python -c "import sys; sys.path.insert(0,'scripts');   from transcribe_episode import process_rewrite;   process_rewrite('KYJN-OhRdEA', force=True, rewrite_engine='claude')"
```

The full restoration recipe, including how speakers in newly-transcribed stretches get
named from the episode's existing verified labels, is 1.26.

## Cross-checks: what catches what

No single check is sufficient. Each one misses something another catches. The history
behind this table is 1.11, 1.14, 1.17, 1.23 and 1.25.

| Check | Catches | Blind to |
|---|---|---|
| `coverage` | A transcript ending well before the episode does | Loss backfilled by duplicate or displaced blocks, which leaves the timeline looking full |
| `content-loss` | Gaps between timestamps too large for the text at their start | The same backfill, plus loss papered over with `[silence]` markers (1.25). Also cannot tell absent content from content filed under the wrong second, so `caption-coverage` overrules it -- see `hole-is-mistimed` below (1.42) |
| `hole-is-mistimed` | Not a check of its own: what `content-loss` becomes when caption coverage confirms the text is all present and only the timing is wrong (1.42) | Episodes whose coverage verdict is `inconclusive` or stale, where the loss reading stands unchallenged |
| `caption-coverage` | Audio whose speech has no counterpart anywhere in the transcript | Episodes whose wording diverges from the captions throughout, which report `inconclusive` rather than clean |
| the video itself | Guest and stand-in-host names, from on-screen lower-third graphics and thumbnails, produced by the people in the room (1.28) | Anyone never captioned on screen |
| `drift` | Blocks timestamped far from where they were actually spoken | Sparse or wrong-language captions. Isolated false phrase-locks still need adjudicating by hand |
| `duplicates` | The same block re-emitted at another timestamp | Near-duplicates differing by a word |
| `backward-jump` | Timestamps that decrease | Forward-only corruption |
| `round-timestamps` | Timing invented rather than measured, i.e. a fabricated outline (1.18) | A fabrication that copies plausible timings |
| `wall-of-text` | Turns merged into one undifferentiated block | Genuine long monologues, excluded on purpose by counting inline speaker markers |
| `truncated` | A rewrite disproportionately short against its raw transcript | Condensation that stays above the ratio |
| `language` | A mixed-language transcript silently rewritten to English only | |
| `speaker-attribution` | Most of an episode credited to someone other than Rafizi (1.27) | Wrong names on the *smaller* labels, and legitimately guest-led episodes, which it reports for judgement rather than assuming |
| `generic-label`, `published-placeholder`, `label-mismatch`, `duplicate-turn`, `malay-loss`, `inline-turn-marker` (`check_published.py`) | Defects in the three `interview*.md` files a reader actually sees (1.39) | Anything the rewrite got wrong that still reads as well-formed |
| `raw-unnamed-speaker` | A real person `raw.md` never names, on a role word like `Moderator` or `Audience` that `placeholder-label` misses because it only matches numbered clusters. Split out of `generic-label`, which was blaming the rewrite for 351 turns it had faithfully copied (2.4) | Nothing yet -- but the fix is speaker attribution, not regeneration, so it will not clear from a rewrite batch |
| `unlabelled-turn` | A published turn with NO speaker label at all, its first sentence bolded where the label belongs. `TURN_RE` requires the colon, so this was invisible to every label check -- and therefore scored BETTER than a generic label, which is how `gate_rewrite.py` came to promote one (2.6) | Nothing yet. Note the CAUSE is upstream: raw.md burying a second speaker inside a named block, which no check finds -- see `cohost_candidates.py`, and note its windowing caveat in 2.6 |
| `unsourced-figure` (`check_figures.py`) | A figure in the published text with no counterpart in `raw.md` -- a changed digit or a changed scale word, e.g. `8.2 bilion` for raw's `8.2 juta` (1.39) | Figures whose digits are all present but REGROUPED, e.g. raw's `10, RM300` printed as `RM10,300`. Bare years, excluded on purpose |

Every check above the last two rows reads `raw.md`. **`raw.md` is not what anybody
publishes.** Until 1.39 nothing read the `interview*.md` files except for existence, a
length ratio and a Malay-density floor set below anything the corpus could produce, so the
suite reported 0/67 clean while the published text carried thousands of placeholder labels.
When a suite reports clean, ask which file it read.

`caption-coverage` runs in the opposite direction from the others. **It starts from the
audio and asks what the transcript is missing.** Every other check reads the transcript
and asks what looks odd there. Duplicated blocks, displaced blocks and `[silence]`
markers all fill the timeline, and none of them can fake a 4-gram match, which is how
this check caught ep48 (1.25).

Because `caption-coverage` measures content directly, it is allowed to overrule
`content-loss`, which only infers it from a timestamp gap. That inference cannot separate
absent content from content filed under the wrong second, and it reports the alarming
reading of the two -- ep61 claimed 1393s missing while all 175 of its caption buckets
matched (1.42).

**Two caches feed the suite from outside, and a stale one is now dangerous.**
`data/caption_coverage.json` and `data/timestamp_drift.json` hold verdicts computed in an
earlier run, and one of them can suppress a content-loss report. So each entry carries
`raw_sha`, the `common.body_digest()` of the `raw.md` body it was computed from, and
`qa_check.py` drops any verdict whose stamp does not match what is on disk -- unstamped
counts as mismatched. Re-run the two checkers after any batch that rewrites `raw.md`, or
their flags silently vanish from the checklist:

```bash
python scripts/check_timestamp_drift.py     # minutes
python scripts/check_caption_coverage.py    # slower; 4-gram scan of every caption
```

Verdicts live in `data/qa_reviewed.json`, keyed by episode and signature name, so a
reviewed issue stays reviewed instead of being re-investigated every session (1.21).
**A wrong entry there does more harm than no entry at all.** It turns an open question
into a settled answer, so nobody checks again. Only suppress an issue on evidence from
outside the file being reviewed.

## Why a clean exit code isn't enough

This pipeline has produced eight distinct bugs that returned exit code 0 with no
visible error, while quietly corrupting or skipping output: a free-tier quota check
that never matched its target string, a transcript-wiping edge case in fragment
trimming, hallucinated runaway timestamps that satisfied a naive coverage check,
missing paragraph breaks that silently bypassed text chunking, an argument-parsing
bug that made a 17-episode batch process zero episodes, a continuation-loop
hallucination that duplicated whole passages under fabricated timestamps that stayed
within a plausible range (1.6), a retry wrapper that validated
nothing but the absence of an exception, letting a placeholder metadata stub through
as a "successful" result (2.1), and the same validate-nothing-but-the-
exception gap letting Claude silently condense a heavily disfluent chunk instead of
fully rewriting it (2.2). None of them raised an exception.

That's why `scripts/qa_check.py` exists. Run it after every batch, and read
`QA_CHECKLIST.md` rather than the exit code. It checks for all of
the failure signatures found so far: timestamp coverage against episode duration,
wall-of-text blocks with no paragraph breaks, duplicate blocks repeated at different
timestamps, rewrite files disproportionately short against their raw transcript,
leaked model reasoning in place of transcript content, inconsistent turn
formatting, timestamps that drop backward (1.16), content dropped from the middle
of an episode (1.17), and timing invented rather than measured (1.18). It also
cross-references `data/manifest.json` against the `episodes/` folder to flag
episodes that were never processed at all.

The checklist is only ever as good as the checks in it. I reported the corpus as 53/67
clean until I added 1.17 and 1.18, and then two of those "clean" episodes turned out to
be missing 41% and 80% of their content. Treat a clean row as "no *known* signature
fired", and not as verified.

Every output file's frontmatter also records which model actually produced it
(`model:`), and `qa_check.py` flags any file made by one of the fallback chain's
weakest, most degradation-prone models (`gemini-3.1-flash-lite` and the `gemini-2.5`
line) for a closer look, even when the other checks pass. This field is only
populated for episodes (re)processed after it was added: older episodes show no
model line in `QA_CHECKLIST.md` until reprocessed.

## Speaker naming convention

The recurring cast use short (first) names as the speaker label in **every** file,
`raw.md` and all three `interview*.md` rewrites alike: `Rafizi`, `Haziq`,
`Farhan (Pa'an)`, `Iqbal`, `Wan Afiq`. Every other speaker (guests, one-off
panelists) keeps their full name as the label.

The `hosts` and `guests` frontmatter fields carry the **fullest** form of a person's
name, since they are metadata about who took part.

**`hosts` records who took part, not who got a label.** A cast member is often plainly
present and still unlabelled, because a coarse block swallowed his interjections. The
field is metadata about participation rather than a transcript label, so it goes on
dialogue evidence, held to a deliberate bar: direct address ("Haziq, aku cabar kau"), or a
reference to what the person said earlier in *that* episode ("yang Haziq sebut tadi"). A
passing third-person mention is not enough, and absence is recorded just as carefully --
ep46 and ep50 say outright that Haziq was away ("Haziq tak ada so kita cover lain lah"),
which is exactly where the stand-ins appear. The per-episode calls live in
`PRESENT_UNLABELLED` in `scripts/rebuild_roster.py`, each with the line that justifies it.

**A speaker label names the person, so it uses their real name even when the show only
ever uses a nickname.** ep36's guest is called `Cincong` throughout the audio and is
labelled `Lee Chean Chung`. Words spoken inside the dialogue are never touched to match:
that episode keeps its 25 spoken "Cincong" mentions, and so do ep45, ep50 and ep58.
The label says who is talking; the transcript says what they said.

**This changed on 2026-08-28, on the archive owner's call, and it reversed what this
file said before.** The old convention was short names in `raw.md` and full names in
`interview*.md`, which left `Rafizi` and `Rafizi Ramli` both in play as labels for the
same man and made every cross-file comparison need a mapping table. One form
everywhere removes that. If you find older commit messages or code comments
describing the two-form split, they predate this decision.

Three gotchas keep recurring around these labels: a local-ASR redo wipes names that were
already applied, Rafizi sometimes delivers the show's own third-person intro line
himself, and a label found wrong in one episode does not generalise to the others. All
three, with the evidence, are [ENGINEERING_LOG.md 1.29](ENGINEERING_LOG.md#129-three-speaker-label-gotchas-that-keep-recurring).

## Retrying Gemini on a previously-failed episode

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

## Known limitations

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
