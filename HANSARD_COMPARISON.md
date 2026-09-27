# Our transcript rules against Hansard practice

This archive's editing rules claim to follow "international Hansard practice". This file
checks that claim against primary sources, fetched 2026-09-12: UK Commons Hansard,
Canada's House of Commons Procedure and Practice chapter 24, Alberta, Manitoba, Victoria,
South Australia, and Bermuda's style guide. New Zealand's editing principles and the
Australian DPS policy could not be fetched and are quoted only from search snippets.

## What Hansard does

**Removes** repetitions and redundancies (UK, 1893 definition still in force), filler
words and false starts (Alberta), "um", "ah" and stutters (Manitoba). A repeat used for
emphasis stays (Manitoba; Bermuda s.2.30 keeps "very, very").

**Never removes** "anything that adds to the meaning of the speech or illustrates the
argument" (UK, quoted by every jurisdiction). Alberta Standing Order 113 forbids any change
"that would in any way tend to change the sense of what has been spoken".

**Interjections.** A heckle the speaker answers is printed; one they ignore is not (UK, NZ,
Victoria, Alberta). Clear words from an unidentified member get their own turn as "An Hon.
Member:" (Canada, Bermuda). Unclear ones become "[Inaudible interjection]" or
"[Interruption.]"; Bermuda also has "[Crosstalk]". No jurisdiction folds an interjection
into the main speaker's sentence.

**Unclear speech.** "[INAUDIBLE 16:44:01]" with a clock time, and "[PHONETIC 14:10:18]" for
an unverified name (Bermuda s.2.12, 2.16). Misattribution "is the most serious error a
Hansard reporter can make" (UK blog).

**Facts.** Editors fix grammar, spelling and obvious slips, never a speaker's factual claim.
The speaker corrects their own error, printed as an erratum linked to the original (UK since
2024, Bermuda s.2.14, Canada within two hours).

**Attribution and time.** Full identity once: "the Member for East Yorkshire (Sir Greg
Knight)" (UK). A clock time per speech (UK "4.28pm") or every five minutes (Canada
"(1005)").

## Rule by rule

| Our rule | Hansard | Verdict |
|---|---|---|
| Every spoken name spelled correctly, checked on the web | Bermuda s.2.12 "verifies all quotes and names"; UK checks "every name mentioned" | Agrees. Hansard also marks an unverified name in the text; we do not. |
| Every government agency correct, checked on the web | "Always verify that the acronym used is correct" (Bermuda s.2.2) | Agrees. Hansard expands an acronym at first use; we do not. |
| Full name in metadata, spoken form in the text | Name added once in brackets; spoken form kept | Agrees. |
| Speakers named by the camera before any audio model | Reporters name speakers by sight in the chamber | Agrees. Both rank sight above sound. |
| Remove fillers, never meaning | Alberta removes "filler words and false starts"; Manitoba keeps an emphatic repeat | Agrees. We keep `ha`, `eh`, `aa`, `oh`, which carry meaning in Malay. |
| One person's continuous speech is one block | One speech is one contribution | Agrees. |
| Overlapping speech never merged into the wrong speaker | Fold if answered, give it its own turn, or mark "[Interruption.]" | Agrees, and we are stricter: `raw.md` keeps an unanswered interjection that Hansard drops. |
| A turn no evidence can name is `Speaker ?` | "An Hon. Member:" | Agrees. Adopted 2026-09-12 from this comparison. |
| `raw.md` is verbatim minus fillers | "Substantially verbatim, with repetitions and redundancies omitted" | Stricter. `raw.md` keeps repetitions. |
| `interview.md` is edited newspaper copy | "Altered to render it more readable but its meaning may not be changed" (Canada) | Looser. Hansard never rewrites wording. Hansard sits between our two files. |

## What Hansard does and we do not

1. **Mark an unverified name in the text.** Hansard prints "[PHONETIC hh:mm:ss]" until the
   name is checked. Our files show nothing while a name is still open.
2. **Leave a speaker's factual error and link an erratum.** We check that published figures
   match `raw.md`, but have no stated policy for a guest's wrong number.
3. **Publish corrections next to the text.** Ours live in `data/speaker_adjudications.json`
   and in git history.
4. **Mark language switches.** Canada prints "[English]" / "[Translation]". Our mixed
   Malay-English files carry no marker.
5. **Mark non-verbal events** such as "[Laughter]" (Bermuda s.2.13). `interview.md` drops
   them; `raw.md` has no rule.
6. **Let the speaker review the draft.** We have owner review, not guest review, by choice.

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
