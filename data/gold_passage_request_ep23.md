# Second gold passage request: ep23, 08:30 to 10:00

**Watch here: https://youtu.be/hVf8FbNa9v0?t=510**

## Why this passage, and why the choice was not mine to bias

The sensing method scores 83% against your ep61 passage, but its parameters were tuned
on that same passage, so the number cannot separate the method from the tuning. A second
passage is the only thing that can.

This window was picked on two label-blind criteria, so the test is not aimed at where the
method already agrees with anything:

- **Rapid exchange.** pyannote counts 12 speaker changes in these 90 seconds, near the
  top of the whole corpus, and your ep61 passage had 16. pyannote is a separate system
  from the method being tested, so using it to choose is not self-selection.
- **Same cast as the gold passage.** raw.md places only Rafizi and Haziq here, so it
  tests the same two-voice shape rather than introducing a third person.

It also differs from ep61 in one way that matters: ep23 has 62 `YB` tokens against ep61's
13. ep61 was nearly the thinnest seed supply in the corpus, so this checks the method under
normal conditions too.

## What I need

A speaker name per turn, the same way you did ep61. Nothing else -- timestamps are not the
problem being solved and I can recover them.

**The list below is a convenience, not a claim.** It is the raw ASR caption text cut at
pauses, so it will be garbled in places and it will split and merge turns wrongly. Re-split,
merge, and correct the words freely. Your ep61 passage was valuable precisely because the
turns were yours, not the machine's -- three of its lessons (a self-answered question is one
speaker, consecutive turns can share a speaker, the same words can belong to different
speakers) only showed up because you did not follow the machine's cut.

If it is easier, ignore the list entirely and write the turns out from scratch.

## The window, cut at caption pauses

| # | at | speaker | text as the ASR heard it |
|---|----|---------|--------------------------|
| 1 | 08:30 | | a kalau tanya kenapa |
| 2 | 08:32 | | akta anti lompat |
| 3 | 08:34 | | parti gagal menghalang |
| 4 | 08:35 | | ahli parlimen melompat parti |
| 5 | 08:37 | | ketawa a |
| 6 | 08:38 | | patut dia cermin diri dululah |
| 7 | 08:39 | | kut hmm |
| 8 | 08:40 | | okey baik yb |
| 9 | 08:41 | | beraria okey |
| 10 | 08:42 | | ini lepas dah beria |
| 11 | 08:46 | | biar gambar berbicara |
| 12 | 08:47 | | oh ya ini memang |
| 13 | 08:49 | | kepada yang jogging tak dapat tengoklah |
| 14 | 08:51 | | ni menang terus |
| 15 | 08:53 | | ni kan tak payah |
| 16 | 08:54 | | tapi yb saya agak takut letak sebab actually |
| 17 | 08:57 | | dia sebenarnya kebakaran |
| 18 | 08:59 | | tu agak sedih sikitlah |
| 19 | 09:00 | | tak tak tapi memang |
| 20 | 09:01 | | ini dia post dekat |
| 21 | 09:03 | | facebook dia |
| 22 | 09:04 | | bukan tak kena saman kan |
| 23 | 09:07 | | memang dia post haji hanafi ahmad cuba |
| 24 | 09:10 | | cuba tengok dengan kasut |
| 25 | 09:12 | | kulit dia tu |
| 26 | 09:13 | | dengan jeans |
| 27 | 09:14 | | dia baju lebih kurang sama col aku a a |
| 28 | 09:18 | | dan gaya |
| 29 | 09:19 | | dia tu nampak sangat |
| 30 | 09:20 | | phot bomb ataupun |
| 31 | 09:22 | | berlakonlah kan |
| 32 | 09:23 | | a siap mengintaingintai tu ketawa tak cuma |
| 33 | 09:28 | | tapi konteks tu dia tu sedihlah mayb |
| 34 | 09:31 | | yalah konteks |
| 35 | 09:32 | | rumah tu semua kan cuma |
| 36 | 09:34 | | pasti yang terbakar |
| 37 | 09:35 | | so budak budakbudak ramai yang menangis |
| 38 | 09:37 | | takut semua kan ni pasti di |
| 39 | 09:39 | | kemaman kan yes cuma sebenarnya |
| 40 | 09:42 | | saya tak tahu ada undangundang ke tidak |
| 41 | 09:45 | | saya tak pasti |
| 42 | 09:46 | | boleh ke tidak buat tu saya check |
| 43 | 09:48 | | aa check gpt |
| 44 | 09:49 | | tadi sebelum yb masuk |
| 45 | 09:51 | | a memang |
| 46 | 09:52 | | civilian tak boleh |
| 47 | 09:53 | | tak boleh ah tak boleh mengendalikan |
| 48 | 09:55 | | kerana dia membahayakan |
| 49 | 09:56 | | nyawa hm contohnya kalau |

## Where the method already knows it is weak, so these are the rows that matter most

On ep61 it missed exactly three turns, all of them the shortest: `Mana ada cuti?` (0.36s),
`Ya.` (two characters) and `Kita memang beria.` (0.24s). The speaker embedder needs 0.6s of
audio and those turns do not have it. Short backchannels in the list above are therefore the
rows that decide whether the residual is really a floor or just ep61 being awkward.

