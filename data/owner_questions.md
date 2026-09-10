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

## One real question for the owner

- **`Ashraf Wajdi` or `Asyraf Wajdi`? The corpus says both, exactly 35 times each.** Datuk
  Dr Mohd Asyraf Wajdi Dusuki. The press spells it **Asyraf** -- the Berita Harian report
  already cited in `fix_proper_nouns.py` is `asyraf-wajdi-serah-lod-rm5-juta`. So the
  70 occurrences should probably all become `Asyraf`, but that is a corpus-wide normalisation
  over 70 spots and the machines cannot settle it: this is the exact shape of the trap in
  [[project-name-corrections-rule]], where the majority spelling was right for Akmal Saleh
  and wrong for Fuziah Salleh in the same corpus. A 35/35 split has no majority at all.
  Nothing is blocked on this and no checker flags it, because raw and published agree
  wherever they sit. Asked 2026-09-11 while adopting ep56, where MAI's `Asravu HD` was
  mapped to `Ashraf Wajdi` -- the spelling ep56's own published files already use -- purely
  so that one episode stayed self-consistent. That choice is not a vote on the question.

## Waiting on a machine, not on the owner

- **The "YB" handoff turns: 13 short ones, 5 of them in ep57.** Only the co-host and Pa'an
  call Rafizi "YB", so a turn labelled Rafizi that addresses him is wrong. The first count
  said 198 turns across 54 episodes, which overstated it badly: in a long Rafizi block the
  "YB" is nearly always a third-person mention or a swallowed interjection. Filtered to
  turns of twelve words or fewer, the whole corpus holds **14**, and one of those --
  ep53 `Pernah kan, YB Chean Chung` -- is Rafizi correctly naming another member, title
  first. That leaves 13, and ep57 has 5 of them:
  `[02:43] Tapi jadi kita start terus, YB.`, `[10:26] Okey, baik. Selesai YB.`,
  `[10:40] Haji, RCI Tabung Haji yang barbarunilah YB.`, `[10:46] Ini lama ni YB.`,
  `[3:29:27] Gotong-royong pun aku kena pergi juga eh. IRL YB, demi demi IRL.` -- and the
  last of those says `aku`, which is Rafizi's own register, so it may be right.
  The other eight sit in ep00, ep05, ep12, ep13, ep16, ep31, ep35, ep48.
  **The cause is a cutting problem, not a naming one:** the vision mixer cuts to the person
  about to answer, so at a question-to-answer boundary the camera is already on Rafizi while
  the co-host is still speaking. `mai_camera_raw.py` keeps the previous label only for turns
  of three words or fewer, and these run four to twelve.
  DO NOT fix this from the text -- `YB Chean Chung` is the proof of why, and text has been
  measurably wrong on this corpus before. Ask a machine: `gemini_label_blocks.py` labels a
  block from the picture and the voice, and `verify_speakers_video.py` settled 11 of ep62's
  labels that way. Only what the model and the camera BOTH move should move.
  Reproduce the list with a twelve-word cap on the `YB` vocative; there is no checker yet.

## Waiting on the camera pass, not on the owner

- **ep45 `[34:14] Farhan (Pa'an): Tak tahu, Pa'an punya pandangan?`** The block is labelled
  Farhan and the words address Pa'an, who IS Farhan, so one of the two is wrong. Do not spend
  the owner's time on it: ep45 has no camera reference yet, and when the corpus pass builds
  one the camera will say who was on screen at that moment. Re-check this line then. The same
  turn reads that way in all three published files, which are regenerated anyway.
