# raw.md quality standard

**PARAMOUNT. Applies to every episode, new or old, every time raw.md or any file
derived from it is touched.** raw.md is the source everything else is built from --
interview.md, interview-en.md, interview-ms.md, and every metadata field all inherit
its errors. A mistake here is not one mistake, it is four.

This file governs behavior, not implementation. For how a script works, see
[ARCHITECTURE.md](ARCHITECTURE.md). For the public disclosure of what a machine did
and where it can be wrong, see [METHODOLOGY.md](METHODOLOGY.md). For the per-episode
runbook, see [ATTRIBUTION_PASS.md](ATTRIBUTION_PASS.md).

**Read the NEWEST `HANDOFF_*.md`, and only that one. These are LOCAL working notes and are
deliberately not published** (`.gitignore`, owner's decision 2026-09-13: session state has
no public audience and goes stale in hours). They hold the corpus state and the running
jobs at a point in time. Nothing in them is required to follow the standards below. What is
durable lives here, in [ARCHITECTURE.md](ARCHITECTURE.md) and in
[ENGINEERING_LOG.md](ENGINEERING_LOG.md). For live state run
`python scripts/corpus_status.py`.

**KEEP AT MOST TWO, the newest and the one before it. Delete the rest** (owner's decision
2026-09-15: *"why is there accumulated handoff md files, just delete those after one
session ahead perhaps"*). Four had piled up by then, and this paragraph itself named two
dated files that no longer existed, which is how a stale pointer sends a session to read
the wrong state. `scripts/prune_handoffs.py` does it, and the session-closing checklist
runs it.

## Token efficiency, PARAMOUNT, but never at the cost of the standard above

Be token-efficient. Do not sacrifice quality in any way to get there -- the two are
not actually in tension, because the token cost that matters is reasoning and prose,
not verification:

- **Deterministic checker scripts are free in this economy.** `check_names.py`,
  `check_figures.py`, `check_published.py`, `check_agencies.py`,
  `check_camera_reference.py`, `check_owner_decisions.py`, `qa_check.py`, and every
  multi-pass loop rule 8 asks for
  cost machine time, not conversation tokens. Never skip one of these, or a re-check
  after a change, to save tokens -- that is not what is expensive.
- **What is actually expensive:** re-deriving a fact this file, the local handoff
  notes, git log, or memory already states; narrating exploration instead of stating the
  conclusion with its evidence; verbose recaps of what was just done; sequential tool
  calls where independent ones could run in parallel; open-ended research past the
  point a specific ambiguity is resolved.
- **Read before re-deriving.** `corpus_status.py` for live state, `git log` for an
  episode's history, this file and the local handoff notes for standing rules -- check
  these first; do not re-run a multi-minute investigation to reconstruct something
  already written down.
- **Still do every check in the nine standards below, every time, in full.** "Token
  efficient" describes how the work gets reported and reasoned about, never which
  verification passes get run. A rule from the nine standards being expensive to
  enforce is not a reason to skip it -- it is a reason to say so and fix the checker,
  the same as rule 2's and rule 7's gaps above.

## The nine standards

### 1. Every spoken name is spelled correctly

Web-search or check the show's own YouTube description before accepting or changing
a name -- never by majority vote across the corpus's own files, and never from
memory. `check_names.py` flags names present in a derived file but not in raw.md;
`fix_proper_nouns.py` holds the corpus-wide, reviewed correction map. Both the
government-agency name (Asyraf Wajdi, MARA) and a recurring guest's name (Sum Dek
Joe, 2026-09-12: the show's own two episode descriptions disagreed with each other --
ep60 said "Sum Dek Jo", ep63 said "Sum Dek Joe" -- resolved by his X handle
`@sumdekjoe` and his own academic publications) are the same class of check.

**AND NO SLUR THE SPEAKER DID NOT SAY. Added 2026-09-16, and it is the worst defect the
corpus has shipped.** `Babi` stood in for the honorific `YB` in 39 places, including the
show's own transition line `Okey, baik YB` in ten of them. `babi` is Malay for pig. It went
unseen because `fix_yb_honorific.py` lists twelve spellings of that garble and not this
one, and the adoption report's own "YB garbles" count used the same short list.

Worse, five published passages carried an insult raw.md does not contain, because the
rewrite changed a benign word: ep15 and ep51 turned `bangsa` (race, nation) into `bangsat`
(bastard), ep16 turned `Salawat`, an Islamic blessing, into `celaka` (cursed), and ep42
turned a spoken `damn` into `sial`. So the corpus quoted named, real people saying things
they did not say. All are corrected in `fix_proper_nouns.py`, which is the right home
because the published files are regenerated and a hand fix would not survive.

`check_slurs.py` is the checker. It fails only on a GATE term a published file holds and
raw.md does not, and prints the milder ones without failing -- `syaitan itu ada dalam
perincian` is just "the devil is in the details". **A slur in raw.md is NOT a finding:**
this show discusses race, religion and corruption, so ep21's `babi hutan`, ep33's `daging
babi`, ep28's `gila babi`, ep40's Animal Farm and ep55's eleven mentions of a real pork
issue all stay. Rule 5 keeps any word that carries meaning. Two spans are still open for
the owner's ear, because the word is genuinely ambiguous: ep13 20:20 and ep55 51:46.

### 2. Every government agency cited is correct

Same method as rule 1: web-verify the agency's real name and acronym, don't infer
from how the ASR heard it. `fix_proper_nouns.py` already carries agency fixes (MARA,
J-KOM, WASIA, and now Kewangan, Peguam Negara, JAC) as a subset of its correction map.
**Gap closed 2026-09-12:** `check_agencies.py` is the checker this rule was missing. It
reads `data/agency_roster.json`, a roster web-verified entry by entry with a source URL
on each, and reports two things: a phrase written as a title that nearly matches a
roster name (`Kementerian Keuangan`, the Indonesian spelling, 16 times across 7
episodes), and a roster agency named in interview.md that raw.md cannot source (ep05's
`Seksyen 122B Akta SPRM 2009`, in a passage about who appoints the Chief Justice -- the
act is the Judicial Appointments Commission Act 2009, and raw.md never says SPRM).

The roster is the authority, never the corpus, and the roster itself can be wrong: its
first version carried `Kementerian Pertanian dan Keselamatan Makanan` from Wikipedia's
cabinet table, the corpus said `Keterjaminan`, and kpkm.gov.my says the corpus was
right. Take the agency's own site over any third party, and read a hit before fixing it.

### 3. A guest's name is their full name in metadata, verbatim as spoken in the text

The `guests:` frontmatter field (in interview.md/-en/-ms) takes the full, correctly
spelled name. raw.md and the interview body text stay verbatim -- if the guest is
addressed as "Joe" on air, raw.md says "Joe". Edit the frontmatter field with
`common.set_frontmatter_list`, never a read-modify-write of the whole file (that pair
dropped the body's H1 from 147 files once; see its docstring for why).

### 4. Speaker turns are attributed using the best available evidence, in this order

MAI's own words and timestamps, the show's camera cuts (`camera_speakers.py`, an
independent on-screen signal), then pyannote diarization only as a fallback when
neither of those covers a moment, then `voice_witness.py` (the episode's own voices,
learned from the camera's seconds, applied only above its measured `--validate`
thresholds) for what is still unnamed. This is the whole point of
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
removes the same sounds from inside a real sentence.

**WIDENED BY THE OWNER 2026-09-16, and only this far.** A turn of three words or fewer, made
only of pure acknowledgement tokens, sitting between two blocks of the same OTHER speaker, is
REMOVED rather than attributed. Owner's words: *"actually anything offscreen, and the word is
just not adding in to anything, we can just safely omit?"* The reason it cannot be attributed is
measured, not assumed: a 19-row blind sample scored the best available test at 12 of 19, and all
7 misses were the other person speaking OFF FRAME, which no camera can see. `drop_orphan_backchannels.py`
does it, from a CLOSED LEXICON, and adoption runs it at step 6d. 169 turns and 193 spoken words
left the corpus on the first pass.

**RULED 2026-09-16: the stance words are KEPT and labelled `Speaker ?`.** Owner: *"leave the 52
then. think the betul, setuju, kan etc is an answer of their own. and we cant identify whose
speaking, just leave is Speaker ?"* That is rule 8's own convention applied: the turn carries
meaning so it stays, and no evidence can name it, so the label is honest rather than wrong. 33
turns relabelled, spoken words untouched. Several were credited to a named GUEST, which is the
worse error: Wong Chen, Nik Nazmi, Amir Sahmat, Zaim Zulkifli and Iqbal each lost a false
attribution. `check_published.py` excludes these from `raw-unnamed-speaker` by reading
`drop_orphan_backchannels.is_stance`, so the count is not read as unfinished work.

**The second lexicon stops short too.** `Betul.` (14), `Ya, betul.` (8), `Kan.` (5), `Kan?`
(4), `Setuju.` (3), `Alhamdulillah.` (3) and `Right?` (2) are in STANCE and are kept: `Setuju.` is a stance, `Alhamdulillah.` is a religious expression, and `Kan?` is often
the main speaker's own tag question (ep18 1:35:02). A further 1197 blocks of this shape carry
real content and stay. Do not widen the lexicon without the owner: this deletes from the verbatim
source. Never let a corpus-wide pattern
collapse a genuine repeated word (Malay slang, emphasis) -- confirm one instance is
really a bug before scoping a fix to it.

### 6. Don't fragment one person's continuous speech across many timestamps

If the same person is still speaking, it is one block, not five. `merge_same_speaker.py`
joins adjacent same-speaker turns after the fold/move passes run (they create new
adjacency that didn't exist before). A high adjacent-same-speaker count after adoption
is the signal this step is missing or ran too early in the sequence.

**IT IS `--episode=<tag>`, NOT A BARE TAG, and the difference is the whole corpus.** This
script takes no positional argument. `merge_same_speaker.py ep32 --write` ignores the tag
and edits EVERY episode with a same-speaker run. That happened on 2026-09-14 and silently
changed interview files in ep35, ep37 and ep38 while the intent was ep32 alone; the table
below carried the wrong form, which is how it happened. The script now refuses an argument
it does not recognise and names the likely intent.

**Re-run this step AFTER the rule 7 move, not only before it.** ep32's adoption ran the
move at step 5 and the merge at step 6, and the merge then created two NEW torn sentences
that the move would have fixed. `check_overlap_boundaries.py` reported 1 tail on a freshly
adopted episode because of it. Rule 8 already says to run a tool again when a later pass
changes its input, and this is the case that proves it for these two.

### 7. Overlapping speech must never be silently merged into the wrong speaker

**Named defect. Detector built 2026-09-12, fix built and measured 2026-09-14.** The shape:
`Speaker 1: "...dia macam kalau"` immediately followed by `Speaker 2: "macam dalam
kementerian ini dia ada 2 contoh..."` -- a sentence that reads as one continuous thought,
torn across two labels. This is what happens when two people talk over each other: the
mixer/diarizer briefly attends to whoever is about to speak next, and a few words at the
boundary get attributed to the wrong side of the cut.

International Hansard practice has an answer for exactly this: an interjection is either
folded into the main speaker's turn (if brief and the speaker responds to it) or marked
distinctly as an interjection -- **never silently merged as if it were the main speaker's
own continuous sentence.** ("The report... leaves out nothing that adds to the meaning of
the speech", the standard formulation used across UK/Canada/NZ/Alberta Hansard.)

**Current state: `check_overlap_boundaries.py --all` reports 0 contested and 0 tail.**
Re-run it after every adoption; it is the only live number, and the counts below are the
history, not the queue.

Three tools, and the division of labour matters:

- `fold_hanging_fragments.py` -- the SAME speaker sits on both sides of a short fragment
  the camera cannot see.
- `move_hanging_words.py` -- a sentence's tail belongs to the next block. **Two branches
  with deliberately different rules.** For a PARTIAL tail (the block has a sentence end
  before it) the SHAPE decides and the camera gets no veto, because a sentence is not split
  between two speakers and a camera cut is not a speaker change. For a WHOLE block with no
  sentence end anywhere in it, the camera MUST attest the next speaker, because rule 7 says
  a short block between two different speakers may be a real interruption. Where the camera
  has no coverage, a recorded owner ruling moves it instead (ep56 01:24). **That sentence was
  ASPIRATIONAL until 2026-09-15**, and it is the kind of claim this file warns about: the
  tool's `owner_rulings()` required keys shaped `ep56@01:24`, and not one of the 114 stamp
  keys in `data/speaker_adjudications.json` has ever been written that way. Every one is a
  bare stamp in a tag-named section, the shape this file mandates and `check_owner_decisions.py`
  reads. So the path was dead code and ep56's own ruling was invisible to it. Fixed, with a
  digit guard so `ep2` cannot match `ep27_rule7_...`. Two consumers read that file; when the
  key shape changes, check BOTH.
- `check_overlap_boundaries.py` -- report only. Classifies each pair by the camera's read of
  the boundary seconds and escalates the residue with a `?t=` link.

**What the owner's rulings measured, and why the fix was allowed to write.** The bar this
rule set was that a candidate leaves the list only when a MEASURED tool moves it, never on
a better guess. On 2026-09-13 the owner ruled all 11 `tail` boundaries after looking at
contact sheets, and **every one went the way the camera had already read it** -- 11 of 11
against a human eye. Their words: *"Actually all these can be verified visually..."* That
retired the escalation: 21 tails and 6 whole blocks were then moved across 17 episodes,
every word conserved by the existing guard, and the corpus went from 35 contested plus 11
tail to zero of each.

Four corrections the detector needed first, all from the owner's reading:

- **The unit is a PAIR, not an A/B/A sandwich.** The sandwich occurs once in the adopted
  corpus (ep48 1:17:30); the pair occurred 66 times. MAI punctuates the end of a phrase, so
  after `merge_same_speaker.py` the first speaker rarely resumes in a third block.
- **The verdict is taken at the boundary, not over the turn.** ep44's 1:21:26 reads
  `Rafizi 842s, Haziq 4s` across its whole window, which looks clean, and `Haziq 2s,
  Rafizi 1s` across its first three seconds, which is the defect.
- **The block's own first second is skipped**, because the cut lags speech by about two
  seconds.
- **One stray second of the previous speaker is the cut, not a claim on the words**
  (`MIN_EDGE_SECONDS = 2`).

**Two traps to remember when a NEW boundary appears.**

1. `move_hanging_words.py` cannot take a block that ends in terminal punctuation: it fails
   the `no terminal punctuation` guard before a tail is computed. That guard is right in
   general. ep35's 2:11:05 was exactly this, and it went to the owner's ear instead.
2. **MAI transcribing a phrase twice does not mean two people said it.** ep35 held
   `Ada 2 lagi.` twice, 0.6s apart, labelled `Multiple speakers`, and I recorded it as real
   crosstalk on that basis. `frames_at.py` then showed Rafizi with a mug at his lips across
   both tokens, so both were Haziq. The camera was available the whole time. Pull a contact
   sheet before believing a duplicate is two voices.

Owner decisions on this rule live in `data/speaker_adjudications.json` under
`<ep>_rule7_*` sections, with **bare stamp keys in a section whose name contains the
episode tag**. Any other shape is invisible to `check_owner_decisions.py`, which skips a
key whose first character is not a digit -- that bug silently voided every rule-7 ruling
until 2026-09-13.

**That key shape is for a ruling about a TURN, and it is wrong for anything else.**
`check_owner_decisions.py` reads every digit-leading key as a turn attribution and hunts
the owner's words in raw.md. A rule-9 FACE identity is a ruling about a person at a video
second: there is no turn and no text. ep55's twelve face rulings, written as bare stamps on
2026-09-15, produced ten `not locatable` lines and two `MISMATCH` lines, one reading as
raw.md contradicting the owner at 2:53:30 where raw.md says `Multiple speakers` and nothing
is wrong. A false MISMATCH is worse than no record, because the next session will go and
"fix" it. Record a face ruling keyed on the cluster with the seconds INSIDE the value, as
`ep55_rule9_faces_owner_ruled_2026_09_15` does, and confirm the gate reports 0 decisions
for that section rather than a wrong count.

### 8. Best guess after every available check and loop; escalate what's left with a timestamp, never a scrub

**What the file shows meanwhile (owner decision 2026-09-12, following Hansard precedent):**
a turn no tool can name is labelled `Speaker ?` -- the repo's per-turn unknown, the same
role as Hansard's "An Hon. Member:" -- never a diarizer cluster id such as `Speaker 2`,
which tells a reader nothing true. The turn itself stays if it carries meaning (Hansard
keeps an interjection the speaker responds to; rule 5 keeps any word with lexical
content). `check_published.py` enforces this: `Speaker N` in raw.md is a
`placeholder-label` defect, `Speaker ?` is not. See HANSARD_COMPARISON.md.

**What does not count as identification (owner decision 2026-09-12):** a probabilistic vote,
however good. `voice_witness_poc.py` measured a unanimous three-model voice vote at 97.6% on
1.6 s windows; that is 1 in 40 wrong, and the owner ruled those turns stay `Speaker ?`, as
Hansard keeps them. Only a witness measured at 100% on its held-out class (the
`voice_witness.py --write` bars) may write a label. Re-open this only if a future tool
measures 100% on short windows, not because a vote got closer.

Run every tool this file lists, more than once if the first pass changes the input to
the next. If, after that, no tool can settle it, stop guessing and bring it back with
a **clickable `?t=`-style timestamp link** derived from the caption track (not raw.md's
own clock, which drifts) -- never expect a scroll through the video to find the
moment. This is the standing rule from every attribution pass this corpus has run:
tools decide what tools can decide; a human ear decides the rest, and only that rest.

### 9. Exhaust the evidence OUTSIDE the corpus before asking a person

**Owner's rule, 2026-09-13:** *"can we make another rule, do make a verification loop via
tools at hand, web search, social media etc then build it up to confidently identify
instead of waiting for me. I dont want to be a blocker."*

Rule 8 says a human ear decides what tools cannot. This rule narrows what "cannot" means.
Every naming tool this repo had read the corpus's own files -- raw.md's labels, the
frontmatter cast, camera clusters, voice centroids -- so all 27 people it could name came
from inside it. Rules 1 and 2 already say to web-verify a name, yet no script did, and the
YouTube description has been sitting in `data/manifest.json` for all 70 episodes unread by
any cast check. So the loop stopped at "no internal tool can name this face" and escalated.
**That is not the same thing as unidentifiable, and the difference was ep39 waiting on a
person for a face that two public photographs settle in minutes.**

Before escalating an unnamed person, in this order:

1. **The corpus's own other episodes.** A recurring guest has face vectors and a name
   somewhere else; reuse them rather than re-deriving. ep39's Iqbal is a labelled speaker
   in ep10 and ep11.
2. **The episode's own words.** The show introduces everyone: `kita ada saudara Iqbal`,
   `kenapa kita jemput Iqbal`, `dah 3-4 kali dijemput`. That is also the evidence that
   settles host-versus-guest, which ep39 had wrong.
3. **The show's own YouTube description and title**, from `data/manifest.json`. ep10's
   title `Yang Berhenti Menteri X CiliSos` is what identifies Iqbal's organisation.
4. **Web search and a public photograph.** `identify_person.py` compares a public photo
   against the episode's face clusters. A photo is an independent witness in the same
   sense as the camera: no audio model made it and it did not come from this corpus.
5. **Only then**, escalate with a `?t=` link and a contact sheet, per rule 8.

**The measured bar, because rule 8 forbids a confident guess.** `identify_person.py
calibrate` must run first and its matrix must be read. Measured 2026-09-13 against the
gallery's own faces: Rafizi's Wikimedia portrait scores **+0.740** on Rafizi, while Anwar
Ibrahim scores +0.151 and Nik Nazmi +0.174, both under the 0.55 floor. So it names a known
face and rejects a stranger. `match` then refuses three ways: below the floor, two clusters
inside the 0.10 margin, or a cluster that already matches a gallery face. ep39's cluster 0
was accepted on two independent photos at **+0.672** and **+0.710** with the next cluster
at +0.085 and +0.180, and it scores only +0.229 against the closest known host.

**Two things this rule does not license.** A web search for a common given name returns
several different people, so the name must be sourced from the episode's own text or the
show's description, never from the photo caption alone -- and the photo URL is recorded
next to the label so the provenance travels with it. And a high score against a mixed
cluster names two people at once, so `match` prints each cluster's internal cohesion.

**Also fixed by this rule's first pass, and it is the class to watch:** the frontmatter
cast is written by the rewrite pipeline from the transcript, and nothing ever compared it
to the episode's own description or to who actually speaks. 7 episodes name a speaker in
raw.md who is in neither `hosts:` nor `guests:` (ep01 Najib and Nazri, ep02 Prof.
Barjoyai, ep03 Faiz, ep06 Eric See-To, ep07 Daniel, ep08 `YB Rafizi` as a label variant,
ep09 Rodziah Ismail). `Multiple speakers` and `Audience` are sanctioned labels and are not
findings.

## Every standing rule and the mechanism that enforces it

**Read this before assuming any rule below is optional, and re-run the verify command
rather than trusting this table.** Owner's instruction, 2026-09-14: *"anything that we've
raised before about rules, new session should not bypass and suddently forgotten."*

A rule with no mechanism gets skipped. That is not a hypothesis: it is what happened to
rule 2 until 2026-09-12, to rule 7 until 2026-09-13, to rule 9 until 2026-09-13, and to
the owner's writing rules until 2026-09-14, when 34 em-dash violations were measured in a
single session.

| rule | mechanism | verify with |
|---|---|---|
| 1 names, 2 agencies | `check_names.py`, `check_agencies.py` + `data/agency_roster.json`, corrections in `fix_proper_nouns.py` | `python scripts/check_agencies.py` |
| **1b no slur the speaker did not say** | **`check_slurs.py`**. Fails on a GATE term a published file holds and raw.md does not. Corrections go in `fix_proper_nouns.py` so a regeneration keeps them | `python scripts/check_slurs.py` |
| **an owner-dictated WORD, not a label** | **`check_owner_text.py`**, adoption step 7b. Reads every record with `text_was` and `text_now` and restores what a rebuild reverted | `python scripts/check_owner_text.py` |
| **an artifact filename built from an episode tag** | **`common.artifact_tag()`** at every site, `common.tag_from_artifact()` where a tool globs those names. `ep05:bakar` in a path names an NTFS alternate data stream, so the file reads as present and is empty | `python scripts/test_tag_paths.py` |
| **a document whose numbers went stale** | **`check_stale_docs.py`**. Re-runs each generator and diffs it; checks the per-run and corpus totals in README, README.ms and METHODOLOGY | `python scripts/check_stale_docs.py` |
| **a step that refuses must stop the run** | **`adopt_mai_camera_raw.must()`**. Every write step's exit code is now read; ep61 shipped 704 fillers because they were discarded | read the `[n/8]` lines in the adoption log |
| 3 cast metadata | `check_cast.py`, `rebuild_roster.py` (`HOSTS`, `MERGE`, `GUEST_THIS_EPISODE`, `PRESENT_UNLABELLED`) | `python scripts/check_cast.py` |
| 4 attribution order | `adopt_mai_camera_raw.py`, gated at step 0 by `check_camera_reference.py` | `python scripts/check_camera_reference.py <tag>` |
| 5 fillers | `strip_filler_turns.py`, `strip_inline_fillers.py`, `drop_orphan_backchannels.py` (closed lexicon, refuses an unadopted raw) | `python scripts/drop_orphan_backchannels.py <tag>` |
| 6 no fragmented speech | `merge_same_speaker.py` | `python scripts/merge_same_speaker.py --episode=<tag>` |
| 7 overlapping speech | `check_overlap_boundaries.py` detects, `move_hanging_words.py` writes | `python scripts/check_overlap_boundaries.py --all` |
| 8 escalate the residue | `check_owner_decisions.py`, `listen_links.py` for the `?t=` link | `python scripts/check_owner_decisions.py <tag> <raw>` |
| 9 outside evidence first | `identify_person.py` (calibrate before match), `check_cast.py` | `python scripts/identify_person.py calibrate --photos ...` |
| best engine for raw.md | `check_raw_engine.py` | `python scripts/check_raw_engine.py` |
| **one GPU job at a time** | `nightly_recut.claim_the_gpu()` + `data/_nightly/chain.pid` | `Get-CimInstance Win32_Process -Filter "Name like 'python%'"` |
| all of the above, per episode | `qa_check.py` into `QA_CHECKLIST.md`; verdicts persist in `data/qa_reviewed.json` | `python scripts/qa_check.py` |
| **the owner's writing rules** | **`Stop` hook, `~/.claude/hooks/check_reply_style.py`** + the vendored `soundshuman` pack. Blocks the turn and hands back the findings | `python ~/.claude/hooks/test_check_reply_style.py` |
| **read the gate verdict, run the post-steps, THEN commit** | **`.git/hooks/pre-commit` -> `scripts/guard_commit.py`**. Refuses a commit that stages interview files while a queue is live or a verdict is unread | `python scripts/guard_commit.py` |
| no `Co-Authored-By: Claude` | `~/.claude/settings.json`, `attribution.commit = ""` | read that key |
| biometric data, videos, frames, secret sweep stay out | `.gitignore` `data/_*`, `audio/`, `frames_*.png`, `data/frames_cache/` | `git check-ignore -v <path>` |
| handoffs are LOCAL ONLY, and at most two exist | `.gitignore` `HANDOFF_*.md`; past ones purged from history 2026-09-13; `prune_handoffs.py` deletes all but the newest two | `python scripts/prune_handoffs.py` |
| only GPU 0, never the GTX 970 | `os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")` in `camera_speakers.py`, `lib_diarization.py`, `gate_rewrite.py` | `grep -rn CUDA_VISIBLE_DEVICES scripts/` |

**One rule still has NO mechanism.** It is listed so the next session does not mistake
silence for safety. The other one, *reprocess an unadopted episode with the camera, never
hand-patch its local-ASR raw*, was closed on 2026-09-16: `drop_orphan_backchannels.py` refuses
any raw.md that does not declare `model: microsoft/MAI-Transcribe-2`. Excluding the known local
engines was not enough, because ep07 and ep10 carry no `model:` line at all.

1. **Escalate with a clickable `?t=` link, never a bare block stamp.** `listen_links.py`
   builds the link from the caption track. Nothing checks that a message used it.

**Closed 2026-09-15: one GPU job at a time.** `nightly_recut.claim_the_gpu()` writes its
pid to `data/_nightly/chain.pid` and refuses to start while that pid is alive. It had to
exist because a second chain does not merely compete for the GPU -- every chain names its
LR-ASD scratch directory `data/_lrasd/work/k<offset>`, with no episode in the name, so the
second one deletes the first one's work mid-chunk. **`kill <pid>` in Git Bash stops the
shell's job, not the Windows process**, which is how two chains were orphaned and invisible
while a third was started. Count the processes before trusting any diagnosis:
`Get-CimInstance Win32_Process -Filter "Name like 'python%'"`. See ARCHITECTURE.md.

## The governing principle behind all nine

Every one of the above is enforced by a script that runs the same way every time, not
a one-off manual pass: `check_names.py`, `check_agencies.py`, `check_figures.py`,
`check_published.py`, `check_camera_reference.py`, `check_owner_decisions.py`,
`qa_check.py`. A rule that
only lives in someone's memory of a past session is a rule that will be skipped on
the next episode -- this is the exact failure ep61 shipped with (three already-settled
rules missing) before the standard became "the ep62 standard applies to every
episode, always, no exceptions for a good score."

Adding a new rule to this file without a script that checks it is incomplete. If no
script exists yet, say so explicitly (rule 7's proposed fix is the one still open;
rule 2's gap closed on 2026-09-12) rather than letting the rule be aspirational.
