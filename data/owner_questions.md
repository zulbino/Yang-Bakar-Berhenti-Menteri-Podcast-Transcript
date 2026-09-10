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

## Waiting on the camera pass, not on the owner

- **ep45 `[34:14] Farhan (Pa'an): Tak tahu, Pa'an punya pandangan?`** The block is labelled
  Farhan and the words address Pa'an, who IS Farhan, so one of the two is wrong. Do not spend
  the owner's time on it: ep45 has no camera reference yet, and when the corpus pass builds
  one the camera will say who was on screen at that moment. Re-check this line then. The same
  turn reads that way in all three published files, which are regenerated anyway.
