# Open questions for the owner, newest first

The owner's standing goal: **need fewer human checks.** So a question goes here only after
the machines have been asked. Three witnesses exist and none of them is a person:

1. **The camera** -- `scripts/camera_speakers.py` reads whose face is on screen when a word
   is spoken. It answers speaker questions.
2. **The caption track** -- YouTube's own transcription, in `audio/<vid>.*.vtt`, made by
   neither of our two engines. `scripts/figure_witness.py epNN` uses it to answer figure
   questions.
3. **The web** -- a published report settles a company's number better than anyone's memory.

A question that lives only in a chat message gets lost: ep61 lost a confirmed Farhan turn
that way (`data/speaker_adjudications.json`, `ep61_farhan_restore`). Answered items move to
the episode's own record -- `data/speaker_adjudications.json` for speaker rulings,
`scripts/fix_proper_nouns.py` for names, `data/forced_labels.json` for a label the owner
keeps against the camera.

## Nothing needs the owner right now

## Closed 2026-09-10, by machine, no owner time spent

- **ep59 `rugi 120 juta` or `rugi 102 juta`?** ANSWERED: **102**. The caption track, which
  neither engine produced, reads `pasaran saham jatuh balik ah rugi 102 juta okey, loss from
  discontinued operation`. MAI heard 102, the captions heard 102, only the local ASR heard
  120. raw.md carries 102 and is correct. The three published files still print 120 and are
  wrong; they are regenerated from raw.md, so the number corrects itself then.
  `check_figures.py` flags ep59 until that happens, which is a flag pointing at real work.
- **ep59 `9 point.8 billion`.** ANSWERED, and the transcript was left alone. This was never a
  disagreement about a number, only MAI's spelling of a spoken decimal, so the fix belongs in
  the checker: `check_figures.py`'s SPOKEN_POINT pattern now accepts a full stop after
  `point`. The captions agree the number is 9.8 bilion. A verbatim raw should keep what was
  said; a false alarm should stop reaching a person. Only two such spellings exist in the
  whole corpus (this one and ep49's `3 point 3 juta`), so no bulk edit was warranted.

## Closed 2026-09-11 by web search, at the owner's instruction

- **`Asyraf Wajdi`, settled and applied to all 71 occurrences.** The owner's answer to being
  asked: *"why wait for me for asyraf wajdi, you can do web search to check what his actual
  name"*. Searched, and it is not close -- **Datuk Dr Asyraf Wajdi bin Dusuki**, MARA chairman
  since March 2023 and UMNO Youth chief 2018-2023. His own Instagram handle is
  `@drasyrafwajdi`, and Wikipedia, Free Malaysia Today, Malaysiakini, Malay Mail and Berita
  Harian all spell it Asyraf. Nothing spells it Ashraf. 35 occurrences changed across 14
  files in ep31, ep39, ep56 and ep60; the corpus now reads Asyraf 71 times and Ashraf never.
  https://en.wikipedia.org/wiki/Asyraf_Wajdi_Dusuki
  **The lesson kept in [[project-name-corrections-rule]]:** counting every file gave a 35/35
  dead heat, and only raw.md pointed the right way (Asyraf 15 to Ashraf 2). The Ashraf
  majority sat in interview files, which are generated FROM raw and cannot corroborate it.
  Ask the web before asking a person, and never count a generated file as a witness.

## Real published errors, waiting on the rewrite rather than on the owner

Both are `check_figures` flags that are CORRECT. Neither needs a decision -- they need the
published files regenerated from the adopted raw, which is the owner's third priority.

- **ep52 prints `47K` where raw says `DNAA 47 kes`.** Forty-seven CASES -- Zahid Hamidi's 47
  charges -- compressed by the rewrite into something that reads as 47,000. All three
  published files carry it. This is the class check_figures exists for, the same shape as
  ep21's `8.2 bilion` for raw's `8.2 juta`.
- **ep59 prints `120 juta` where raw and the caption track both say `102 juta`.** Already
  answered below; only the published files are still wrong.

## ep53: the owner asked to review its 12 `Speaker ?` rulings before anything is written

ep53 holds 26 recorded decisions -- every other episode this pass has reached had ZERO -- and
`check_owner_decisions.py` reports 8 preserved, 4 mismatched, 14 not locatable. Nothing is
written; `raw.md` is untouched. Rebuild the candidate with `mai_camera_raw.py ep53` to re-read
any line below.

**FIRST, a bug that made this look worse than it is.** The gate was CRASHING on ep53, not
judging it. ep53's 2:19:13 records its text as `["Human resource", 1]`, a list, and `snip[:45]`
on a list silently returns a list, so the length test died with AttributeError. adopt reads
that non-zero exit as "a decision was not kept". One entry in the whole corpus is in that
form and ep53 is the only episode with decisions this pass has reached, so the gate had never
once run clean here. Fixed.

**The 12 `Speaker ?` rulings, and what the rebuild does to each. No word is lost anywhere.**

| # | at | your words | what the rebuild does |
|---|---|---|---|
| 1 | 14:11 | `Hmm` | **stays `Speaker ?`** |
| 2 | 18:43 | `Ya.` | grunt-only, step 3 deletes the turn |
| 3 | 51:16 | `Ya` | grunt-only, step 3 deletes the turn |
| 4 | 1:14:05 | `Yes.` | grunt-only, step 3 deletes the turn |
| 5 | 1:34:45 | `Haa` | heard as `Ha.`, grunt-only, deleted |
| 6 | 1:43:25 | `Han,` | absorbed into Rafizi's `Tahan eh. Tunggu, tunggu...` |
| 7 | 1:45:31 | `pun kencing.` | now `Haziq: I think viewers pun kencing.` |
| 8 | 1:45:34 | `tu` | now `Rafizi: Haa tu lah.` |
| 9 | 1:56:37 | `hmm` | grunt-only, step 3 deletes the turn |
| 10 | 2:14:42 | `Teruskan.` | **stays `Speaker ?`**, but MAI hears `10 sen?` |
| 11 | 2:17:33 | `ya?` | now `Rafizi: Oh ya?` |
| 12 | 2:38:40 | `kan. Wah` | now `Rafizi: Wah, manusia.`; the `kan.` ends his previous sentence |

**Read #10 before deciding.** The old raw had `Teruskan.` there. MAI hears `10 sen?`, and the
context settles it: Rafizi has just asked `1 flyer berapa sen?`, and the next turns are
`Mahal lagilah.` and `40, 50 sen.` "Teruskan" (*continue*) is not an answer to that question.
**So several of these rulings were made on words the old ASR got wrong.** Honouring them
literally would pin a label onto speech that was never spoken. #7 is the same shape: the
fragment could not be attributed because the old raw cut the sentence in half.

Five become whole sentences with a clear speaker, five are grunts the settled standard deletes
anyway, and two stay `Speaker ?`. Nothing here needs a ruling reversed -- it needs a decision
about whether a ruling made on a shredded fragment still binds a file where the fragment no
longer exists.

**SEPARATELY, three real disagreements remain, and these are NOT fragment artefacts.** At
2:19:13-18 the owner recorded a four-way split -- `Human resource` Rafizi, `Itu je lah kot`
Haziq, `Okay Okay Human resource lah` Farhan, `Takde` Multiple speakers. MAI cuts the same
speech into `[2:19:13] Rafizi: Human resource.` (right), `[2:19:14] Rafizi: Itu jelah kot.
Okey eh, okey.` (one block holding BOTH Haziq's ruled words and the start of Farhan's), and
`[2:19:18] Multiple speakers: Human resource lah.` (should be Farhan). A forced label can move
a whole block but cannot split one, so the best available result puts `Itu jelah kot. Okey eh,
okey.` under Haziq and leaves Farhan's three opening words with it. That is a real, if small,
loss against what the owner heard, and it is the one part of ep53 that adoption makes worse.

**Already prepared, waiting only on the above:** `data/forced_labels.json` now carries ep53's
two YB-handoff rulings, which the camera had reversed -- `Okey. Baik, YB.` and `Okey YB?`,
both back to Haziq. Those three blocks are confirmed applied.

## Waiting on a machine, not on the owner

- **The "YB" handoff turns: 8 rows for the owner's ear, with a guess to score me against.**
  The owner's protocol, 2026-09-11: *"before you give me the list for me to check by ear, can
  you make a column on your guess, then ill check if what i see and hear is the same as what
  you guess"*. So the guess column below was written from the surrounding dialogue BEFORE any
  model was asked, and the video column was filled afterwards. Every link starts 5 seconds
  early so the lead-in is audible.

| # | listen | episode / at | the words | file says | MY GUESS | video model | your verdict |
|---|---|---|---|---|---|---|---|
| 1 | [02:43](https://www.youtube.com/watch?v=TaoW0I1XqE0&t=158s) | ep57 02:43 | Tapi jadi kita start terus, YB. | Rafizi | **Haziq** (high) | Haziq (high) |  |
| 2 | [10:26](https://www.youtube.com/watch?v=TaoW0I1XqE0&t=621s) | ep57 10:26 | Okey, baik. Selesai YB. | Rafizi | **Haziq** (high) | Haziq (high) |  |
| 3 | [10:40](https://www.youtube.com/watch?v=TaoW0I1XqE0&t=635s) | ep57 10:40 | Haji, RCI Tabung Haji yang barbarunilah YB. | Rafizi | **Haziq** (high) | Haziq (high) |  |
| 4 | [10:42](https://www.youtube.com/watch?v=TaoW0I1XqE0&t=637s) | ep57 10:42 | Itu kau ambil gambar umur aku berapa tu? Aku ada janggut lagi. | Haziq | **Rafizi** (medium) | _quota hit, retry_ |  |
| 5 | [10:46](https://www.youtube.com/watch?v=TaoW0I1XqE0&t=641s) | ep57 10:46 | Ini lama ni YB. | Rafizi | **Haziq** (high) | _quota hit, retry_ |  |
| 6 | [10:49](https://www.youtube.com/watch?v=TaoW0I1XqE0&t=644s) | ep57 10:49 | Aku tak boleh ada janggut sebab | Haziq | **Rafizi** (medium) | _quota hit, retry_ |  |
| 7 | [3:29:27](https://www.youtube.com/watch?v=TaoW0I1XqE0&t=12562s) | ep57 3:29:27 | Gotong-royong pun aku kena pergi juga eh. IRL YB, demi demi IRL. | Rafizi | **Haziq** (LOW) | _quota hit, retry_ |  |
| 8 | [11:32](https://www.youtube.com/watch?v=nXMJ_FxwfjM&t=687s) | ep56 11:32 | Kalau lompat parti, kosongkan, maka jatuh talak. Tapi lama sangat YB. | Rafizi | **SPLIT** (medium) | _quota hit, retry_ |  |

  **Why each guess.** 1: Haziq proposed shortening Beria at 02:34, this continues his own
  proposal, and the pre-MAI raw had it as Haziq with Rafizi answering `Haah.` 2: Haziq is
  closing the segment and times it at 10:28. 3: segment intros are Haziq's job. 5: a comment
  on Rafizi's old photo, addressed to him. 7: **genuinely unsure** -- `aku kena pergi` is
  Rafizi's register and a gotong-royong is a politician's chore, but `IRL YB` addresses YB.
  8: the block holds two people, Rafizi reciting the `jatuh talak` formula and Haziq saying
  it is too long, which is what his `Saya macam dah tak boleh` at 11:37 answers.

  **Rows 4 and 6 are NOT YB turns and are the bonus of reading the region.** ep57's 10:42 and
  10:49 are currently Haziq, and the beard being discussed is Rafizi's -- at 10:51 he explains
  his own beard and moustache went white. So that whole stretch reads as swapped, not just the
  YB lines. Worth one listen while the tab is open.

  **Where the machines stand.** The camera put all six YB turns on Rafizi, which is the defect.
  The video model was asked one turn at a time over a 40-second window -- the mode that settled
  11 of ep62's labels, NOT the bulk mode measured at 68% on turns this short -- and it answered
  Haziq with high confidence on the first three, agreeing with the guess. The remaining five hit
  the Gemini daily quota (HTTP 429) and need a retry: `python scripts/ask_video_one_turn.py ep57
  --turns data/_yb_turns.json --window 40 --json data/_yb_video_verdicts.json`.

- **ep53 is BLOCKED and deliberately not adopted.** The gate refused, ep53's `raw.md` is
  untouched, and its owner labels are intact -- verified. Two of its four recorded decisions
  also report `cannot locate: no usable text for the turn the owner named Rafizi`, which is
  the known limit that a stamp cannot locate a decision. Adopting it needs the two turns
  above pinned in `data/forced_labels.json` first, and that was left for you rather than
  guessed at overnight: this is the exact failure the ep62 standard was written to stop, and
  ep53 is the FIRST episode where this gate has ever fired -- the previous eight all reported
  zero owner decisions.

## Waiting on the camera pass, not on the owner

- **ep45 `[34:14] Farhan (Pa'an): Tak tahu, Pa'an punya pandangan?`** The block is labelled
  Farhan and the words address Pa'an, who IS Farhan, so one of the two is wrong. Do not spend
  the owner's time on it: ep45 has no camera reference yet, and when the corpus pass builds
  one the camera will say who was on screen at that moment. Re-check this line then. The same
  turn reads that way in all three published files, which are regenerated anyway.
