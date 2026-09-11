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

- **CLOSED 2026-09-11 by the owner's ear: the YB handoff turns in ep57 and ep56 are FIXED.**
  Eight turns went to the owner with a YouTube link, a guess column and the video model's
  answer, on their instruction: *"make a column on your guess, then ill check if what i see
  and hear is the same as what you guess"*. **The camera was wrong on all eight.** Verdicts:

  | at | words | was | now |
  |---|---|---|---|
  | ep57 02:43 | Tapi jadi kita start terus, YB. | Rafizi | **Haziq** |
  | ep57 10:26 | Okey, baik. Selesai YB. | Rafizi | **Haziq** |
  | ep57 10:40 | ...Tabung Haji, RCI Tabung Haji yang baru-baru ni lah YB | Rafizi | **Haziq** + words fixed |
  | ep57 10:42 | Itu kau ambil gambar umur aku berapa tu?... | Haziq | **Rafizi** |
  | ep57 10:46 | Ini lama ni YB. | Rafizi | **Haziq** |
  | ep57 10:49 | Aku tak boleh ada janggut sebab | Haziq | **Rafizi** |
  | ep57 3:29:27 | Gotong-royong... / IRL YB, demi demi IRL. | Rafizi | **SPLIT** Rafizi / Haziq |
  | ep56 11:32 | Kalau lompat parti... / Tapi lama sangat YB. | Rafizi | **SPLIT** Rafizi / Haziq |

  Applied, word sequence asserted, 7 blocks merged in ep57 and 1 in ep56, and both episodes
  now read zero YB-vocative turns under Rafizi. `check_owner_decisions` reports ep57 8 of 8
  and ep56 2 of 2 preserved. All four checkers unchanged.
  Recorded in `data/speaker_adjudications.json` (`ep57_yb_ear_2026_09_11`,
  `ep56_yb_ear_2026_09_11`) and in `data/forced_labels.json` so a rebuild keeps them. The
  one-token garble `barbarunilah` went into `fix_proper_nouns.py` for the same reason.

  **HOW THE THREE WITNESSES SCORED, which is the reusable part.** The camera: 0 of 8. The
  video model asked one turn at a time: 3 of 3 before the quota cut it off, all high
  confidence, all against the camera. Reading the dialogue: 6 of 8 exactly right, right as a
  split on the 7th, and wrong on ep57 3:29:27 -- which had been flagged LOW for the correct
  reason, that `aku kena pergi` is Rafizi's register while `IRL YB` addresses him. **Both
  errors were single labels on turns that are actually splits**, so the lesson is not that
  reading is unreliable but that a two-speaker block cannot be scored with one name.

  **STILL OPEN: the 8 remaining candidates**, in ep00, ep05, ep12, ep13, ep16, ep31, ep35 and
  ep48. Deliberately NOT done yet -- those raws will be rebuilt from MAI+camera when their
  camera reference exists, so fixing them now is throwaway work. Re-run the probe then: a
  twelve-word cap on the `YB` vocative, and remember ep53's `Pernah kan, YB Chean Chung` is
  Rafizi correctly naming another member.

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
