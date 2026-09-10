# Open questions for the owner, newest first

Anything that needs the owner's ear or their ruling, recorded the moment it is found. A
question that lives only in a chat message or a commit message gets lost -- ep61 lost a
confirmed Farhan turn that way (`data/speaker_adjudications.json`, `ep61_farhan_restore`).

Answered items move to the episode's own record: `data/speaker_adjudications.json` for
speaker rulings, `scripts/fix_proper_nouns.py` for names, `data/forced_labels.json` for a
label the owner keeps against the camera.

## ep59, found 2026-09-10 while adopting the MAI+camera raw

1. **`rugi 120 juta` or `rugi 102 juta`?** At `[1:17:19]`, Tabung Haji's loss from
   discontinued operations. The local ASR heard `120 juta` and all three published files
   print it; MAI heard `102 juta`. Two engines, transposed digits, and no way to choose
   between them from the text -- this needs your ear, or the figure from THHE's own
   financial statement. `check_figures.py` flags ep59 until it is settled.
   Nothing has been changed: raw.md carries MAI's `102`, the published files still say `120`.

2. **`9 point.8 billion`, MAI's spelling of `9.8 bilion`.** Same block region,
   `[1:26:35]`. This one is not a disagreement about the number, only about how MAI writes a
   spoken decimal, and it is the second half of what `check_figures.py` reports on ep59. Say
   the word and I will normalise `N point.M billion` to `N.M bilion` across the MAI raws --
   it is an artefact of the engine, not something anyone said differently. Left alone for now
   because it changes words in raw.md.

## ep45, found 2026-09-10 while fixing the Pa'an spelling

3. **`[34:14] Farhan (Pa'an): Tak tahu, Pa'an punya pandangan?`** The block is labelled
   Farhan and the words address Pa'an, which is Farhan himself. One of the two is wrong, and
   by the standing rule I do not infer a speaker from text, so nothing was changed. The same
   turn reads that way in all three published files. Worth a listen when ep45 comes up.
