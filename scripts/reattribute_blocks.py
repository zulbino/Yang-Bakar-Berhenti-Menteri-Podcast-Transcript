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

WINDOW_S = 45.0
ACCEPT_FRACTION = 0.62
WORDS_PER_S = 2.6          # measured on this corpus; over-feed is intentional
OVERFEED = 1.9

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


def word_times(text, audio, sr, t0, t1):
    """Absolute (word, start, end) for every token in `text` across [t0, t1)."""
    import lib_forced_align
    words = text.split()
    out, pos, t = [], 0, t0
    while pos < len(words) and t < t1 - 0.2:
        w_end = min(t + WINDOW_S, t1)
        seg = audio[int(t * sr):int(w_end * sr)]
        if seg.shape[0] < sr * 0.5:
            break
        take = max(8, int(WORDS_PER_S * (w_end - t) * OVERFEED))
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


def label_for(segs, start, end):
    best, best_ov = None, 0.0
    for s, e, lab in segs:
        ov = min(end, e) - max(start, s)
        if ov > best_ov:
            best_ov, best = ov, lab
    return best


def resplit(block, segs, audio, sr):
    timed = word_times(block["text"], audio, sr, block["start"], block["end"])
    turns, cur, cur_start, cur_words = [], None, block["start"], []
    for w, s, e in timed:
        spk = label_for(segs, s, e) or cur
        if spk != cur:
            if cur_words:
                turns.append((cur_start, cur, " ".join(cur_words)))
            cur, cur_start, cur_words = spk, s, []
        cur_words.append(w)
    if cur_words:
        turns.append((cur_start, cur, " ".join(cur_words)))
    return turns
