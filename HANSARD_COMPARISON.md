# The raw.md standard against Hansard editing practice

CLAUDE.md's eight rules cite "international Hansard practice" without a source. This file
is the source check, done 2026-09-12 against the primary pages that could be fetched: UK
Commons Hansard (about page and the reporters' blog), Canada's House of Commons Procedure
and Practice chapter 24, Alberta, Manitoba, Victoria, South Australia, and Bermuda's
published style guide. New Zealand's editing-principles page and the Australian DPS policy
PDF were not reachable and are quoted only through search snippets.

## What Hansard does, in one paragraph each

**Removed.** Repetitions and redundancies (UK, 1893 definition still in force), filler
words and false starts (Alberta), "um", "ah", stutters (Manitoba). A repeat used for
emphasis stays (Manitoba, Bermuda s.2.30 keeps "very, very").

**Never removed.** "Nothing that adds to the meaning of the speech or illustrates the
argument" (UK, quoted by every jurisdiction). Alberta Standing Order 113: no change "that
would in any way tend to change the sense of what has been spoken".

**Interjections.** A heckle the speaker responds to is printed; one they ignore is not
(UK, NZ, Victoria, Alberta). Clear words from an unidentified member get their own turn as
"An Hon. Member:" (Canada, Bermuda). Unclear ones become "[Inaudible interjection]" or
"[Interruption.]". Bermuda also has "[Crosstalk]". No jurisdiction folds an interjection
into the main speaker's sentence.

**Inaudible or unattributable.** "[INAUDIBLE 16:44:01]" with a clock time and "[PHONETIC
14:10:18]" for an unverified name (Bermuda s.2.12, 2.16). Misattribution "is the most
serious error a Hansard reporter can make" (UK blog).

**Grammar and facts.** Editors fix grammar, spelling, and obvious slips; they do not fix
a speaker's factual claim. The speaker corrects their own error through a point of order or
a written correction, printed as an erratum linked to the original (UK since 2024, Bermuda
s.2.14, Canada within two hours).

**Attribution and time.** Full identity once, outside the quote: "the Member for East
Yorkshire (Sir Greg Knight)" (UK), "Jenny Kwan (Vancouver East, NDP)" (Canada). Clock time
per speech (UK "4.28pm") or every five minutes (Canada "(1005)"), not per sentence.

## Rule by rule

| CLAUDE.md rule | Hansard principle | Verdict |
|---|---|---|
| 1. Every spoken name spelled correctly, web-verified | "Hansard verifies all quotes and names" (Bermuda s.2.12); UK checks "every name mentioned" | Agrees. Hansard also marks an unverified name in the text; we do not. |
| 2. Every agency correct, web-verified | "Always verify that the acronym used is correct" (Bermuda s.2.2) | Agrees. Hansard expands an acronym at first use; we do not. |
| 3. Full name in metadata, verbatim in the body | Name added once in brackets at first mention; spoken form kept | Agrees. |
| 4. Attribution by best evidence: MAI words, camera, diarizer last | Reporters attribute by sight from the chamber; "cameras don't always pick up all the detail" | Agrees. Both rank a visual read above audio. |
| 5. Remove fillers, never meaning | Alberta: "filler words and false starts"; Manitoba keeps a repeat "used to emphasize a point" | Agrees. Our kept set (`ha`, `eh`, `aa`, `oh`) is the same idea. |
| 6. One person's continuous speech is one block | One speech is one contribution; speaker re-identified only after an interjection | Agrees. |
| 7. Overlap never silently merged into the wrong speaker | Fold if answered, own turn as "An Hon. Member:", or mark "[Interruption.]" | Agrees. We are stricter: Hansard drops an unanswered heckle, raw.md keeps every audible word. |
| 8. Exhaust tools, then escalate with a timestamp link | "[INAUDIBLE 16:44:01]", "An hon. member" | Agrees on method. Hansard prints the unresolved mark in the text; we escalate it privately. |
| raw.md = verbatim minus fillers | "Substantially the verbatim report, with repetitions and redundancies omitted" | Stricter. raw.md keeps repetitions. |
| interview.md = newspaper copy | "Altered to render it more readable but its meaning may not be changed" (Canada) | Looser. Hansard never rewrites wording; interview.md does. Hansard sits between our two files. |

## Where our rules differ, and what Hansard does that we have no rule for

1. **An unverified name has no in-text marker.** Hansard prints "[PHONETIC hh:mm:ss]" until
   it is checked. We verify, but a name still open shows nothing in the file.
2. **Inaudible or unattributable speech has no in-text marker.** Rule 8 escalates to the
   owner; nothing says what the published text shows in the meantime. Hansard shows
   "[Inaudible]" or "An Hon. Member:".
3. **A speaker's own factual error.** Hansard leaves it as spoken and prints a linked
   erratum from the speaker. `check_figures.py` catches drift between raw and published
   copies, but there is no stated policy for a guest's wrong number in raw.md.
4. **A public corrections log.** UK Hansard publishes corrections linked to the original.
   Ours live in `data/speaker_adjudications.json` and git, not in the published file.
5. **Language-switch markers.** Canada prints "[English]" / "[Translation]". Our
   Malay-English files carry no marker, and one known bug silently translated mixed text
   to English (ARCHITECTURE.md, language mistranslation).
6. **Non-verbal events.** "[Laughter]", "[Applause]", "[Pause]" (Bermuda s.2.13).
   interview.md drops laughs by rule; raw.md has no rule either way.
7. **Speaker review before publication.** Every Hansard lets the member read their draft.
   We have owner review, not guest review. A deliberate difference, but unstated.

Items 1 and 2 are the closest to CLAUDE.md rule 7's proposed `[overlapping speech]`
annotation and rule 8's escalation, and could be one convention.

## Sources

- UK Hansard, about: https://hansard.parliament.uk/about
- UK Commons Hansard blog, "10 things you thought you knew":
  https://commonshansard.blog.parliament.uk/2017/07/24/being-a-hansard-reporter-10-things-you-thought-you-knew/
- UK Procedure Committee on correcting the record:
  https://publications.parliament.uk/pa/cm5803/cmselect/cmproced/521/report.html
- Canada, House of Commons Procedure and Practice, ch. 24:
  https://www.ourcommons.ca/procedure/procedure-and-practice-4/ch24-2-e.html
- Alberta, about Hansard: https://www.assembly.ab.ca/assembly-business/transcripts/about-hansard
- Manitoba, about Hansard: https://www.gov.mb.ca/legislature/hansard/hansard_about.html
- Victoria: https://www.parliament.vic.gov.au/hansard
- South Australia: https://www.parliament.sa.gov.au/About-Parliament/Hansard
- Bermuda Hansard style guide (PDF):
  http://parliament.bm/admin/uploads/hansard/0c24a4d52e6825bff64a693fa6364335.pdf
