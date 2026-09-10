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

- **`Asyraf Wajdi` looks settled -- 35 published occurrences still say `Ashraf`.** Datuk Dr
  Mohd Asyraf Wajdi Dusuki. Counting every file equally gives a dead heat, Ashraf 35 to
  Asyraf 35, which is why this first looked unanswerable. **Split by file type it is not
  close.** In raw.md, which is what an engine actually heard, it is **Asyraf 15 to Ashraf 2**,
  and ep60's MAI raw spells it Asyraf six times unaided. The Ashraf majority sits entirely in
  the rewritten interview files, and those are generated FROM raw, so they are not a witness
  to anything -- counting them equally would let the rewrite outvote the audio. The press
  agrees with raw: the Berita Harian report cited in `fix_proper_nouns.py` is
  `asyraf-wajdi-serah-lod-rm5-juta`.
  **So the machines have answered the spelling. What needs the owner is the write.** 33
  occurrences in published files and 2 in raw would change, and the precedent in this map is
  that a name goes in only after an external source AND the owner's word -- that is how
  `Ismail Salleh` went in, in two stages. Nothing is blocked and no checker flags it, because
  check_names treats Ashraf and Asyraf as the same person. Say the word and it is one entry
  in the reviewed map.
  Raised 2026-09-11 while adopting ep56, where MAI's `Asravu HD` was mapped to `Asyraf
  Wajdi`. That mapping first went in as `Ashraf` to match ep56's own published files and was
  corrected the same night, once the by-file-type count showed the published spelling was the
  weaker witness.

## Waiting on a machine, not on the owner

- **The "YB" handoff turns -- and YOUR EAR HAS ALREADY RULED ON TWO OF THEM.** Only the
  co-host and Pa'an call Rafizi "YB", so a turn labelled Rafizi that addresses him is wrong.
  **ep53 proves the pattern and proves the camera causes it.** Adopting ep53 was REFUSED by
  `check_owner_decisions.py` because the MAI+camera candidate wanted to relabel two turns you
  had already adjudicated by ear in `data/speaker_adjudications.json` (`ep53_round2`):

      [29:59]   Haziq: Okey, baik, YB.                              -> candidate said Rafizi
      [2:05:29] Haziq: Baik Dah meletup pun ... Okay YB             -> candidate said Rafizi

  Both are short turns ending in a vocative "YB" at a question-to-answer boundary, both are
  Haziq by your ear, and the camera puts both on Rafizi -- because the mixer cuts to whoever
  is ABOUT TO answer. `mai_camera_raw.py` protects only turns of three words or fewer, and
  these run four to twelve. **So the class is real, it is caused by the camera, and it is
  already confirmed twice.**

  **What is left to decide: the 14 candidates in the seven already-adopted episodes**, where
  no adjudication existed to catch it. ep57 has 5, ep56 1, and eight sit in ep00, ep05, ep12,
  ep13, ep16, ep31, ep35, ep48:

      ep57 [02:43]   Tapi jadi kita start terus, YB.
      ep57 [10:26]   Okey, baik. Selesai YB.
      ep57 [10:40]   Haji, RCI Tabung Haji yang barbarunilah YB.
      ep57 [10:46]   Ini lama ni YB.
      ep57 [3:29:27] Gotong-royong pun aku kena pergi juga eh. IRL YB, demi demi IRL.
      ep56 [11:32]   Kalau lompat parti, kosongkan, maka jatuh talak. Tapi lama sangat YB.

  **STILL DO NOT APPLY THIS AS A TEXT RULE**, for two reasons that survive the ep53
  confirmation. ep53 `Pernah kan, YB Chean Chung` is Rafizi correctly naming another member,
  title first -- a word-level rule corrupts it. And ep57's `[3:29:27]` says `aku`, which is
  Rafizi's own register, so it may genuinely be his. A machine cannot settle these either:
  `gemini_label_blocks.py` measured 68% on turns of 4-6 words and, when it dissents from the
  file, the camera backs the file 2 to 1 (`data/gemini_label_blocks_measured.txt`).
  So this is 14 lines for your ear, and `data/forced_labels.json` is where a label you keep
  against the camera belongs.

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
