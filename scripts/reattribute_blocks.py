"""Re-cut a raw.md's speaker blocks at real speaker changes, WITHOUT re-transcribing.

Why not just re-run the pipeline: `process_raw(force=True)` overwrites raw.md wholesale
and then deletes the cached audio, destroying every hand-edit the file has accumulated
(ep45 alone carries 62 -- the show-name fix, four YB garbles, Cincong -> Chean Chung).
This keeps the text byte-for-byte and only moves the speaker boundaries.

How it works, per block:
  1. Diarize the whole episode once with an exact `num_speakers` from the roster.
     Without that hint pyannote collapses these panels into one cluster holding 90%+
     of the audio (ENGINEERING_LOG 1.26); a min/max range does not help, only an
     exact count does (probe: ep45 goes 2 clusters -> 3, matching its voiceprint scan).
  2. Walk the block's audio span in windows, forced-aligning the next slice of the
     block's own text against each window to recover absolute word times.
  3. Label each word by diarization overlap and re-emit the block split at changes.

Step 2 is the delicate part. Forced alignment assumes the text matches the audio, so
handing it more text than the window contains compresses everything. The window is
therefore deliberately over-fed and only the words aligning inside the first
ACCEPT_FRACTION of it are kept; the rest are re-aligned by the following window, whose
start time is anchored to where the last accepted word actually ended. Errors cannot
accumulate past one window because every window re-anchors on acoustic evidence.
"""
import json, os, re, sys, time
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")  # hard rule: never the GTX 970
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Diarization islands shorter than this are noise, not turns. Without smoothing, the
# per-word labelling flickers across a real speaker change and tears single sentences
# into 1-3 word scraps under alternating names -- 306 isolated tears plus 267 alternating
# chains already in the corpus from the original run (scripts/merge_torn_scraps.py counts
# them). Those cannot be repaired from text afterwards, because the scrap is often a
# genuine short turn and it is the neighbour's tail that is misnamed, so the direction is
# only knowable from audio. Fixing it here, before any word is labelled, is the only
# place the information exists.
#
# 0.9s is above pyannote's flicker and below a real interjection: "hmm" and "betul" run
# past a second in this corpus, and ep51's confirmed Haziq turns average 15s.
MIN_ISLAND_S = 0.9

# If one cluster still holds this much of the audio, the collapse was NOT fixed and the
# output must not be written. An exact num_speakers rescues most of these panels but not
# all: ep45/ep44/ep43 land near 92.9/6/1, while ep58 stays at 98.4/1.1/0.5 and ep41 at
# 99.5/0.5. Writing those replaces real names with anonymous collapsed clusters, which is
# strictly worse than leaving the file alone, and naming such a cluster is the exact error
# ENGINEERING_LOG 1.26 was written about. Verified on one episode is not verified.
MAX_COLLAPSED_SHARE = 0.95

# Second guard, independent of the first. Never write an attribution that gives the
# non-dominant speakers LESS time than the file already had. ep26 slipped past the
# collapse check and would have cut Haziq from 11.6 min to 4: its existing labels came
# from Gemini, not pyannote, so they were already better than anything this tool produces
# there. A fix that has to be judged against the previous state needs to actually compare
# with it, not just check its own output looks plausible.
MIN_MINORITY_RETENTION = 0.80

# Third guard. Even when nothing regresses, refuse to write unless the run actually buys
# something: a materially shorter longest block, or materially more time for the quiet
# speakers. ep27/ep36/ep51 passed both guards above and still gained nothing -- their
# longest blocks came out unchanged at 23.6, 22.6 and 20.9 minutes and minority time moved
# by tenths of a minute. All they did was trade real names for "Speaker N", which then has
# to be re-earned by a voiceprint pass for no benefit.
#
# When this fires it is usually informative rather than a failure: ep36's and ep51's long
# blocks were independently confirmed by reading as genuine Rafizi monologues, so
# diarization leaving them whole is the CORRECT answer. Those belong in
# data/qa_reviewed.json with that evidence, not in another re-cut.
MIN_IMPROVEMENT = 0.15

WINDOW_S = 45.0
ACCEPT_FRACTION = 0.62
# Words per second is measured PER BLOCK (its own word count over its own duration)
# rather than fixed corpus-wide. Speech density varies far too much between a rapid
# exchange and a slow explanation for one constant: with a fixed 2.6 w/s and 1.9x
# over-feed, ep45's assigned shares came out 95.3/3.6/1.1 against the diarization's own
# 92.5/6.2/1.3, i.e. roughly half of the second speaker's time leaked to the first
# because over-fed windows compress the alignment and push words across boundaries.
# Matching the block's real density lets OVERFEED drop close to 1, which is what keeps
# the recovered word times honest.
OVERFEED = 1.25
MIN_WORDS_PER_S = 1.2

TS = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*([^:]{1,40}?):\s*(.*)$")


def secs(t):
    p = [int(x) for x in t.split(":")]
    return p[0] * 3600 + p[1] * 60 + p[2] if len(p) == 3 else p[0] * 60 + p[1]


def fmt(s):
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def parse_blocks(raw_text, duration):
    body = raw_text.split("# Raw Transcript", 1)[-1]
    blocks = []
    for line in body.splitlines():
        m = TS.match(line.strip())
        if m:
            blocks.append({"start": secs(m.group(1)), "label": m.group(2).strip(), "text": m.group(3)})
    for i, b in enumerate(blocks):
        b["end"] = blocks[i + 1]["start"] if i + 1 < len(blocks) else max(duration, b["start"])
    return blocks


def cached_diarization(video_id, audio, sr, n_speakers):
    path = ROOT / "data" / f"diar_{video_id}_n{n_speakers}.json"
    if path.exists():
        return [tuple(x) for x in json.loads(path.read_text())]
    import torch
    from pyannote.audio import Pipeline
    pipe = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1", token=os.environ["HF_TOKEN"])
    if torch.cuda.is_available():
        pipe.to(torch.device("cuda"))
    waveform = torch.from_numpy(audio).float().unsqueeze(0)
    out = pipe({"waveform": waveform, "sample_rate": sr}, num_speakers=n_speakers)
    seen, segs = {}, []
    for turn, _, spk in out.exclusive_speaker_diarization.itertracks(yield_label=True):
        seen.setdefault(spk, f"Speaker {len(seen) + 1}")
        segs.append((turn.start, turn.end, seen[spk]))
    segs.sort()
    path.write_text(json.dumps(segs))
    return segs


def smooth_islands(segs, min_island_s=MIN_ISLAND_S):
    """Drop sub-threshold turns that sit between two turns of one other speaker.

    Only islands are removed, never a short turn at the edge of a longer run by the same
    speaker, so a genuine brief interjection that pyannote resolved confidently survives.
    """
    out = [list(s) for s in segs]
    dropped = 0
    i = 1
    while i < len(out) - 1:
        prev, cur, nxt = out[i - 1], out[i], out[i + 1]
        if (cur[1] - cur[0] < min_island_s
                and prev[2] == nxt[2] and prev[2] != cur[2]):
            prev[1] = nxt[1]          # absorb the island and its far neighbour
            del out[i:i + 2]
            dropped += 1
            continue
        i += 1
    return [tuple(x) for x in out], dropped


def word_times(text, audio, sr, t0, t1):
    """Absolute (word, start, end) for every token in `text` across [t0, t1)."""
    import lib_forced_align
    words = text.split()
    span = max(t1 - t0, 1.0)
    wps = max(MIN_WORDS_PER_S, len(words) / span)   # this block's own speech density
    out, pos, t = [], 0, t0
    while pos < len(words) and t < t1 - 0.2:
        w_end = min(t + WINDOW_S, t1)
        seg = audio[int(t * sr):int(w_end * sr)]
        if seg.shape[0] < sr * 0.5:
            break
        take = max(8, int(wps * (w_end - t) * OVERFEED))
        chunk = words[pos:pos + take]
        aligned = lib_forced_align.align_words(" ".join(chunk), seg, sr)
        span = w_end - t
        cutoff = span * ACCEPT_FRACTION if w_end < t1 else span
        keep = [(w, s, e) for w, s, e in aligned if e <= cutoff] or aligned[:1]
        if len(chunk) < take:                      # last of the text, keep all of it
            keep = aligned
        for w, s, e in keep:
            out.append((w, t + s, t + e))
        pos += len(keep)
        advance = max(keep[-1][2], 1.0)
        t += advance
    for w in words[pos:]:                          # audio ran out before the text did
        out.append((w, t1, t1))
    return out


def collapsed_share(segs):
    """Fraction of diarized time held by the single largest cluster."""
    per = {}
    for s, e, lab in segs:
        per[lab] = per.get(lab, 0.0) + (e - s)
    total = sum(per.values())
    return max(per.values()) / total if total else 1.0


def minority_seconds(spans):
    """Total seconds held by everyone except the single largest speaker."""
    per = {}
    for start, end, lab in spans:
        per[lab] = per.get(lab, 0.0) + max(0.0, end - start)
    if not per:
        return 0.0
    return sum(per.values()) - max(per.values())


def label_for(segs, start, end):
    best, best_ov = None, 0.0
    for s, e, lab in segs:
        ov = min(end, e) - max(start, s)
        if ov > best_ov:
            best_ov, best = ov, lab
    return best


def resplit(block, segs, audio, sr):
    timed = word_times(block["text"], audio, sr, block["start"], block["end"])
    # A word whose span misses every diarization turn keeps whoever is already talking;
    # at the very start of a block there is nobody yet, so fall back to the block's own
    # existing label rather than emitting a None turn.
    turns, cur, cur_start, cur_words = [], None, block["start"], []
    for w, s, e in timed:
        spk = label_for(segs, s, e) or cur or label_for(segs, block["start"], block["end"]) or block["label"]
        if spk != cur:
            if cur_words:
                turns.append((cur_start, cur, " ".join(cur_words)))
            cur, cur_start, cur_words = spk, s, []
        cur_words.append(w)
    if cur_words:
        turns.append((cur_start, cur, " ".join(cur_words)))
    return turns


# Re-cut EVERY block, not just the oversized ones. An earlier version skipped blocks
# under two minutes on the theory that they were already turn-level, and ep45 came out
# with a mixed roster: 92% under a new "Speaker 1" alongside a stale "Rafizi" 3.5% and
# "Farhan" 0.8% left on the untouched short blocks. Those old labels came from the same
# block-level voiceprint pass that is being replaced, so trusting them just preserves the
# error in the gaps. Short blocks align in well under a second, so this costs almost
# nothing and leaves one consistent set of clusters to name.
MIN_BLOCK_S = 0.0


def roster_size(ep_dir):
    import re as _re
    text = (ep_dir / "interview.md").read_text(encoding="utf-8").split("---")[1]
    n = 0
    for key in ("hosts", "guests"):
        m = _re.search(key + r":\s*\n((?:[ \t]*-[ \t]+.*\n)+)", text + "\n")
        if m:
            n += len([x for x in m.group(1).splitlines() if x.strip()])
    return n


def find_episode(ep_tag):
    for d in sorted((ROOT / "episodes").glob("*/*")):
        if re.search(r"-" + ep_tag + r"-", d.name) and "bakar" not in str(d):
            return d
    raise SystemExit(f"no episode dir for {ep_tag}")


def main():
    ep_tag = sys.argv[1]
    probe = "--probe" in sys.argv
    write = "--write" in sys.argv

    ep_dir = find_episode(ep_tag)
    raw_path = ep_dir / "raw.md"
    raw_text = raw_path.read_text(encoding="utf-8")
    fm = raw_text.split("---")[1]
    video_id = re.search(r"video_id:\s*(\S+)", fm).group(1)
    duration = int(re.search(r"duration_seconds:\s*(\d+)", fm).group(1))
    n_spk = roster_size(ep_dir)

    audio_file = ROOT / "audio" / f"{video_id}.m4a"
    if not audio_file.exists():
        import yt_download
        print(f"downloading {video_id} ...", flush=True)
        yt_download.download_audio(video_id, ROOT / "audio")

    import lib_local_asr, soundfile as sf
    print(f"{ep_tag}: {duration/60:.0f} min, roster says {n_spk} speakers", flush=True)
    wav = lib_local_asr._decode_to_wav(audio_file)
    try:
        audio, sr = sf.read(str(wav), dtype="float32")
        t0 = time.time()
        segs = cached_diarization(video_id, audio, sr, n_spk)
        clusters = sorted({s[2] for s in segs})
        raw_turns = len(segs)
        segs, dropped = smooth_islands(segs)
        print(f"  diarization: {len(clusters)} clusters, {raw_turns} turns "
              f"({time.time()-t0:.0f}s)", flush=True)
        print(f"  smoothed out {dropped} island(s) under {MIN_ISLAND_S}s -> "
              f"{len(segs)} turns", flush=True)

        share = collapsed_share(segs)
        if share > MAX_COLLAPSED_SHARE:
            print(f"  ABORT: top cluster still holds {share*100:.1f}% of the audio even "
                  f"with num_speakers={n_spk} -- the collapse is not fixed, so re-cutting "
                  "would only rename real labels to anonymous ones. Left untouched.",
                  flush=True)
            return

        blocks = parse_blocks(raw_text, duration)
        big = [b for b in blocks if b["end"] - b["start"] >= MIN_BLOCK_S]
        print(f"  {len(blocks)} blocks, {len(big)} over {MIN_BLOCK_S:.0f}s to re-cut", flush=True)

        if probe:
            b = max(big, key=lambda x: x["end"] - x["start"] if "--longest" in sys.argv else -x["start"])
            print(f"\n--- probe: block [{fmt(b['start'])}] {(b['end']-b['start'])/60:.1f} min, "
                  f"label {b['label']!r}, {len(b['text'])} chars ---", flush=True)
            t = time.time()
            for start, spk, text in resplit(b, segs, audio, sr):
                print(f"\n[{fmt(start)}] {spk}: {text[:220]}")
            print(f"\n  ({time.time()-t:.0f}s for this block)")
            return

        out, done = [], 0
        for b in blocks:
            if b["end"] - b["start"] < MIN_BLOCK_S:
                out.append((b["start"], b["label"], b["text"]))
                continue
            done += 1
            print(f"  re-cutting [{fmt(b['start'])}] "
                  f"{(b['end']-b['start'])/60:.1f} min ({done}/{len(big)})", flush=True)
            for start, spk, text in resplit(b, segs, audio, sr):
                out.append((start, spk, text))
        print(f"\n  {len(blocks)} blocks -> {len(out)} turns")

        old_minority = minority_seconds(
            [(b["start"], b["end"], b["label"]) for b in blocks])
        new_minority = minority_seconds(
            [(t, out[i + 1][0] if i + 1 < len(out) else duration, lab)
             for i, (t, lab, _) in enumerate(out)])
        if old_minority and new_minority < old_minority * MIN_MINORITY_RETENTION:
            print(f"  ABORT: non-dominant speakers would drop from "
                  f"{old_minority/60:.1f} min to {new_minority/60:.1f} min. The "
                  "existing labels are better than this run; left untouched.",
                  flush=True)
            return

        old_max = max((b["end"] - b["start"] for b in blocks), default=0.0)
        new_max = max((out[j + 1][0] - t if j + 1 < len(out) else duration - t
                       for j, (t, _, _) in enumerate(out)), default=0.0)
        block_gain = (old_max - new_max) / old_max if old_max else 0.0
        minority_gain = ((new_minority - old_minority) / old_minority
                         if old_minority else 1.0)
        if block_gain < MIN_IMPROVEMENT and minority_gain < MIN_IMPROVEMENT:
            print(f"  ABORT: no material gain -- longest block {old_max/60:.1f} -> {new_max/60:.1f} min "
                  f"({block_gain*100:+.0f}%), minority time {old_minority/60:.1f} -> "
                  f"{new_minority/60:.1f} min ({minority_gain*100:+.0f}%). Left untouched; if that "
                  "long block is a genuine monologue, waive it in data/qa_reviewed.json.",
                  flush=True)
            return

        if write:
            head = raw_text.split("# Raw Transcript", 1)[0] + "# Raw Transcript\n\n"
            body = "\n\n".join(f"[{fmt(s)}] {spk}: {txt}" for s, spk, txt in out) + "\n"
            raw_path.write_text(head + body, encoding="utf-8")
            print(f"  wrote {raw_path.name} -- clusters are anonymous, name them next")
        else:
            print("  dry run -- pass --write to apply")
    finally:
        wav.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
