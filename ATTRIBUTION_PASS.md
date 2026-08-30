# Attribution pass, one episode at a time

The order to fix an episode's speaker labels, working newest first: ep61, then ep60, ep59,
ep58 and down. One episode per day. Everything here was learned on ep61 and is written so
the next pass costs a fraction of what the first one did.

Read [ENGINEERING_LOG.md 1.43](ENGINEERING_LOG.md#143-sensing-the-speaker-instead-of-trusting-the-label-measured-against-gold-data)
once for why the method is shaped this way. You do not need to re-derive any of it.

## The rule that matters most

**Long evidence is stable. Short evidence is not.**

Measured on ep61: a change that should have been neutral moved the per-turn score from 83%
to 72%, on two turns scoring −0.006 and −0.010. Under that same change, the 16 whole-episode
disagreement regions kept their spans, directions and scores exactly. Regions carry 20–56
seconds of speech; the unstable turns carry under a second.

So the pass below acts on **regions of 15 seconds or more** and leaves short turns alone.
That is not caution for its own sake — it is where the evidence is.

## Before you start

Capture the baseline. A regression has to read as `2 → 6`, not as a plausible absolute:

```
python scripts/qa_check.py            # ep61 baseline: 0/68
python scripts/check_published.py     # ep61 baseline: 2/68
python scripts/check_figures.py       # ep61 baseline: 0/68
```

Check the YB garbles first, because they seed the whole method:

```
python scripts/fix_yb_honorific.py <epNN>            # dry run
python scripts/fix_yb_honorific.py <epNN> --write
```

ep61 held 70 of them where every other episode holds 0–19, because its `raw.md` was
regenerated from local ASR after the corpus-wide fix ran. **Re-run this after any `raw.md`
regeneration** — a corpus-wide text fix does not survive one episode being re-transcribed.
Read every hit before writing: all 70 sat in a vocative slot, but `ubi keledek`, `baby
boomer` and `baby sharks` are real and the `KEEP` list exists for them.

## The pass

### 1. Audit

```
python scripts/audit_block_attribution.py --episode <epNN> --min-region 15 \
    --out data/_audit_<epNN>.json
```

Prints how much speech sits under a label the audio disputes, per label, and ranks the
contiguous disagreeing regions by seconds at stake. It ends with a ready-to-paste
`frames_at.py` line for the top regions. It writes nothing to any episode file.

It refuses to report if the two voices fail to separate — a collapsed axis silently labels
everything one name, which is how an earlier attempt scored the baseline exactly while
looking like it worked.

### 2. Check every region on video

```
python scripts/frames_at.py <epNN>:berhenti --pad 3 --at <mid> <mid> ...
```

The show cuts to whoever is talking, so a frame is direct evidence — **on a long region**.
Three ways it lies, all of which cost time on ep61:

- **A two-shot proves nothing.** Both hosts in frame says nothing about who is speaking.
- **A full-screen graphic proves nothing.** Two ep61 blocks sat under a TikTok slide and a
  Tabung Haji card, with nobody on screen at all.
- **A camera cut is not a speaker change.** The show cuts to reaction shots. Two ep61 blocks
  cut mid-block and I read that as two voices in one block; the owner confirmed both were
  one person throughout.

Do not run two `frames_at.py` invocations concurrently on the same episode unless they have
different `--out` names. The staging directory is keyed on the output name for exactly this
reason, and before that fix two parallel runs produced a sheet showing the wrong timestamps
with blank rows — a silent wrong answer.

### 3. Apply only what the video confirmed

```
python scripts/build_region_split_map.py --audit data/_audit_<epNN>.json \
    --confirmed 1,2,3,... --out data/speaker_video_confirmed_<epNN>.json \
    --frames "frames_<epNN>.png"
python scripts/apply_split_map.py data/speaker_video_confirmed_<epNN>.json          # dry run
python scripts/apply_split_map.py data/speaker_video_confirmed_<epNN>.json --write
python scripts/_verify_words.py <epNN> HEAD
```

`apply_split_map.py` asserts the word sequence of every touched block is unchanged.
`_verify_words.py` then asserts it file-wide against git, which catches anything a second
tool did in between. Expect word counts to be identical and every diff to be an intended
substitution.

One map file is applied once. Re-running a file whose blocks have already been split fails,
and that is correct behaviour rather than a bug.

Cut points take the whole whitespace-delimited token. Taking them at a `[\w']+` boundary
splits `Tuh...` into `Tuh` and a free-standing `...`, which `apply_split_map.py`'s word
check collapses — its own marker for an unapportionable run. Its assertion caught this.

Mid-sentence cuts are not automatically damage. Baseline it: ep61's block boundaries were
already 65% mid-sentence, so the new cuts at 50% were better than the file's own standard.

### 4. Short blocks and `Speaker ?`

**Never name these from the sensing score.** On ep61's short blocks, scored against the
owner's answers, the method said Rafizi 15 times and was right 15 times, and said Haziq 4
times and was wrong 4 times. 78% overall, and every error a false co-host call.

So: a Rafizi call on a short block is trustworthy. A co-host call is not, and needs video or
the owner before it is written. Where neither can answer, leave the placeholder. A
placeholder tells the reader nobody knows; a wrong name tells them something false in a
named politician's mouth.

Where the owner's gold passage reaches a block, the gold decides. Keep those in their own
file so a later reader can tell owner evidence from a frame.

### 5. Published files

```
python scripts/gate_rewrite.py <epNN> --tries 3
```

The published `interview*.md` files carry whatever labels `raw.md` had when they were
generated, so they need regenerating after `raw.md` changes — 10 of ep61's 15 corrected
regions still read the old name until this ran. The rewrite stage is not deterministic and
its variance is larger than the choice of engine: four runs over ep61 returned 24%, 32%,
63% and 39% of raw's length. `gate_rewrite.py` sandboxes each try and promotes only a
candidate that scores better, so a bad run leaves the episode untouched. It is slow —
budget an hour for a 3-hour episode at `--tries 3`.

Finish `raw.md` completely before running it. It reads `raw.md` at generation time, so an
edit part-way through leaves the tries inconsistent.

Mandatory afterwards, because the metadata stage rewrites the roster and reverts labels:

```
python scripts/rebuild_roster.py --write
python scripts/normalize_speaker_labels.py --write
python scripts/build_episode_index.py
python scripts/qa_check.py
```

### 6. Close out

Compare against the baseline from the start, commit, push, then
`python scripts/cleanup_scratch.py`.

## What to hand the owner

A short list of only what no automated evidence can reach, each with a timestamped YouTube
link and the reason it is unresolvable — see `data/ep61_open_items.md` for the shape. Note
which are *vague rather than wrong*, because that distinguishes "nobody knows" from "someone
is quoted falsely" and only the second is urgent.

Count the items in that file against the items you actually left open. ep61's listed five
and silently dropped a sixth, so the owner never saw `[07:44]`.
