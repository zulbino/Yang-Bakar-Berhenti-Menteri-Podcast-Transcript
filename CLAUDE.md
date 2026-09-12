# raw.md quality standard

**PARAMOUNT. Applies to every episode, new or old, every time raw.md or any file
derived from it is touched.** raw.md is the source everything else is built from --
interview.md, interview-en.md, interview-ms.md, and every metadata field all inherit
its errors. A mistake here is not one mistake, it is four.

This file governs behavior, not implementation. For how a script works, see
[ARCHITECTURE.md](ARCHITECTURE.md). For the public disclosure of what a machine did
and where it can be wrong, see [METHODOLOGY.md](METHODOLOGY.md). For the per-episode
runbook, see [ATTRIBUTION_PASS.md](ATTRIBUTION_PASS.md).

**Read [HANDOFF_2026-09-12.md](HANDOFF_2026-09-12.md) before touching anything below --
it has a fully diagnosed bug behind rule 7 (not a hypothetical) and the exact corpus
state and running jobs at the point this file was written.**

## Token efficiency, PARAMOUNT, but never at the cost of the standard above

Be token-efficient. Do not sacrifice quality in any way to get there -- the two are
not actually in tension, because the token cost that matters is reasoning and prose,
not verification:

- **Deterministic checker scripts are free in this economy.** `check_names.py`,
  `check_figures.py`, `check_published.py`, `check_camera_reference.py`,
  `check_owner_decisions.py`, `qa_check.py`, and every multi-pass loop rule 8 asks for
  cost machine time, not conversation tokens. Never skip one of these, or a re-check
  after a change, to save tokens -- that is not what is expensive.
- **What is actually expensive:** re-deriving a fact this file, HANDOFF_2026-09-12.md,
  git log, or memory already states; narrating exploration instead of stating the
  conclusion with its evidence; verbose recaps of what was just done; sequential tool
  calls where independent ones could run in parallel; open-ended research past the
  point a specific ambiguity is resolved.
- **Read before re-deriving.** `corpus_status.py` for live state, `git log` for an
  episode's history, this file and HANDOFF_2026-09-12.md for standing rules -- check
  these first; do not re-run a multi-minute investigation to reconstruct something
  already written down.
- **Still do every check in the eight standards below, every time, in full.** "Token
  efficient" describes how the work gets reported and reasoned about, never which
  verification passes get run. A rule from the eight standards being expensive to
  enforce is not a reason to skip it -- it is a reason to say so and fix the checker,
  the same as rule 2's and rule 7's gaps above.

## The eight standards

### 1. Every spoken name is spelled correctly

Web-search or check the show's own YouTube description before accepting or changing
a name -- never by majority vote across the corpus's own files, and never from
memory. `check_names.py` flags names present in a derived file but not in raw.md;
`fix_proper_nouns.py` holds the corpus-wide, reviewed correction map. Both the
government-agency name (Asyraf Wajdi, MARA) and a recurring guest's name (Sum Dek
Joe, 2026-09-12: the show's own two episode descriptions disagreed with each other --
ep60 said "Sum Dek Jo", ep63 said "Sum Dek Joe" -- resolved by his X handle
`@sumdekjoe` and his own academic publications) are the same class of check.

### 2. Every government agency cited is correct

Same method as rule 1: web-verify the agency's real name and acronym, don't infer
from how the ASR heard it. `fix_proper_nouns.py` already carries agency fixes (MARA,
J-KOM, WASIA) as a subset of its correction map. **Gap:** nothing yet cross-checks an
agency name the way `check_names.py` cross-checks a person's name against the
corpus's own roster -- an agency-roster checker is open work.

### 3. A guest's name is their full name in metadata, verbatim as spoken in the text

The `guests:` frontmatter field (in interview.md/-en/-ms) takes the full, correctly
spelled name. raw.md and the interview body text stay verbatim -- if the guest is
addressed as "Joe" on air, raw.md says "Joe". Edit the frontmatter field with
`common.set_frontmatter_list`, never a read-modify-write of the whole file (that pair
dropped the body's H1 from 147 files once; see its docstring for why).

### 4. Speaker turns are attributed using the best available evidence, in this order

MAI's own words and timestamps, the show's camera cuts (`camera_speakers.py`, an
independent on-screen signal), then pyannote diarization only as a fallback when
neither of those covers a moment. This is the whole point of
`adopt_mai_camera_raw.py`. A face not in the gallery is not silently absorbed into
the nearest known face -- `check_camera_reference.py` refuses a reference that is
blind to a real speaker, and `guest_gallery.py` names a guest's face only under a
measurable bijection (one guest, one cluster holding 90%+ of the unidentified talking
time), never a guess.

### 5. Remove filler words and disfluencies, never remove meaning

The correct term is filler words / disfluencies / vocalized pauses, not "retorts".
The test is not a fixed word list, it is whether the sound carries logical or lexical
content: `um`, `uh`, `hmm` on their own don't and go; `ha`, `eh`, `aa`, `oh` carry
real meaning in spoken Malay and stay even though they sound like fillers in English.
`strip_filler_turns.py` drops a turn that is only a vocalization; `strip_inline_fillers.py`
removes the same sounds from inside a real sentence. Never let a corpus-wide pattern
collapse a genuine repeated word (Malay slang, emphasis) -- confirm one instance is
really a bug before scoping a fix to it.

### 6. Don't fragment one person's continuous speech across many timestamps

If the same person is still speaking, it is one block, not five. `merge_same_speaker.py`
joins adjacent same-speaker turns after the fold/move passes run (they create new
adjacency that didn't exist before). A high adjacent-same-speaker count after adoption
is the signal this step is missing or ran too early in the sequence.

### 7. Overlapping speech must never be silently merged into the wrong speaker

**Named defect, not yet fully solved.** The shape: `Speaker 1: "...dia macam kalau"`
immediately followed by `Speaker 2: "macam dalam kementerian ini dia ada 2 contoh..."`
-- a sentence that reads as one continuous thought, torn across two labels. This is
what happens when two people talk over each other: the mixer/diarizer briefly attends
to whoever is about to speak next, and a few words at the boundary get attributed to
the wrong side of the cut.

International Hansard practice has an answer for exactly this, and it validates the
approach already partly built here: an interjection is either folded into the main
speaker's turn (if brief and the speaker responds to it) or marked distinctly as an
interjection -- **never silently merged as if it were the main speaker's own
continuous sentence.** ("The report... leaves out nothing that adds to the meaning of
the speech", the standard formulation used across UK/Canada/NZ/Alberta Hansard.)

What already exists: `fold_hanging_fragments.py` handles the case where the SAME
speaker sits on both sides of a short fragment the camera can't see. `move_hanging_words.py`
moves a sentence's tail into the next block when it's the same speaker finishing
their own thought. Neither currently handles the boundary the user is describing:
a short block sandwiched between two DIFFERENT speakers, where the text is plausibly
one continuous sentence.

Proposed fix, not yet built: a third pass that looks specifically at this shape --
block N-1 (speaker A, no terminal punctuation) / block N (speaker B, short, lowercase
start) / block N+1 (speaker A again, continuing the same sentence). Use word-level
camera confidence at the exact boundary seconds, not the block-level label: if the
camera's confidence for block N is low or contested (overlapping faces, a cut mid-word)
and the text is a clean grammatical continuation of A's sentence, reattribute it to A.
If the margin is not decisive, do not guess -- mark it (e.g. an explicit
`[overlapping speech]` annotation) and escalate per rule 8, rather than silently
picking a side.

### 8. Best guess after every available check and loop; escalate what's left with a timestamp, never a scrub

**What the file shows meanwhile (owner decision 2026-09-12, following Hansard precedent):**
a turn no tool can name is labelled `Speaker ?` -- the repo's per-turn unknown, the same
role as Hansard's "An Hon. Member:" -- never a diarizer cluster id such as `Speaker 2`,
which tells a reader nothing true. The turn itself stays if it carries meaning (Hansard
keeps an interjection the speaker responds to; rule 5 keeps any word with lexical
content). `check_published.py` enforces this: `Speaker N` in raw.md is a
`placeholder-label` defect, `Speaker ?` is not. See HANSARD_COMPARISON.md.

Run every tool this file lists, more than once if the first pass changes the input to
the next. If, after that, no tool can settle it, stop guessing and bring it back with
a **clickable `?t=`-style timestamp link** derived from the caption track (not raw.md's
own clock, which drifts) -- never expect a scroll through the video to find the
moment. This is the standing rule from every attribution pass this corpus has run:
tools decide what tools can decide; a human ear decides the rest, and only that rest.

## The governing principle behind all eight

Every one of the above is enforced by a script that runs the same way every time, not
a one-off manual pass: `check_names.py`, `check_figures.py`, `check_published.py`,
`check_camera_reference.py`, `check_owner_decisions.py`, `qa_check.py`. A rule that
only lives in someone's memory of a past session is a rule that will be skipped on
the next episode -- this is the exact failure ep61 shipped with (three already-settled
rules missing) before the standard became "the ep62 standard applies to every
episode, always, no exceptions for a good score."

Adding a new rule to this file without a script that checks it is incomplete. If no
script exists yet, say so explicitly (see rule 2's gap, rule 7's proposed fix) rather
than letting the rule be aspirational.
