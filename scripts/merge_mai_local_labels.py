"""Take MAI's words and timings, keep the local raw's speaker where the local raw is right.

WHY BOTH. On ep62 MAI-Transcribe-2 wins on everything except one thing. Its text is cleaner,
its turns are 1,613 against the local ASR's 184, and its timings are per word, which is what
retimed the local file in the first place. But it loses the third host: `Farhan (Pa'an)` gets
94 words from MAI and 279 from the local ASR, and the camera says the local ASR is right --
8 of the 10 disputed regions show Farhan alone in close shot, mid-speech (ENGINEERING_LOG
1.45). The cause is inside MAI: two of its per-chunk clusters hold two people each, and a
voiceprint mean over 22 minutes cannot see a 15-second passenger.

So this moves a MAI turn to Farhan when the local raw says those same words were Farhan's.

HOW A TURN IS MATCHED, and why not by time. Both files are on the same clock now, but the
local blocks are coarse: a block's span runs to the next block's start, which overruns the
speech by seconds. Matching on span alone hands Farhan a 59-word Rafizi answer that merely
starts one second before a Farhan block ends. So a MAI turn moves only when its WORDS are
in the local Farhan block's text -- MIN_WORD_OVERLAP of them -- and the best-scoring nearby
Farhan block wins rather than the first one found.

VERIFIED lowers the bar rather than removing it. The regions in VIDEO_CONFIRMED were read
off the video, so their speaker is settled and only the question of which MAI turn carries
the words remains; those match at VERIFIED_OVERLAP instead of MIN_WORD_OVERLAP. 2:27:17
scores 0.57 against the ordinary cutoff of 0.60 and is Farhan beyond doubt -- Haziq addresses
him by name in the turn before it, "Macam mana Pak An lepas dengar?".

WHAT THIS CANNOT FIX. Where MAI's own diarization collapsed, the words are inside a turn
that also holds another speaker, and relabelling the turn would move that speaker's words
too. ep62's `[3:11:35]` is one turn of about 1,000 words containing Rafizi, Farhan's 3:12:26
question and Haziq's backchannels. Those are reported and left alone; splitting them needs
the turn cut, not the label changed.
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]\s*([^:\n]{1,40}):(.*)$", re.M)
MIN_WORD_OVERLAP = 0.60
NEAR_SECONDS = 8            # how far a MAI turn may sit outside a local block and still match
COLLAPSE_WORDS = 200        # a turn this long is a diarization collapse, not a turn
# A turn made only of vocalisations matches any block that happens to contain one: "Hmm."
# scores 1.00 against a 42-word block whose text has a "hmm" in it, which moved a listener's
# backchannel onto the person being listened to. So a turn must carry at least one word that
# is not a vocalisation before it can move. A length floor was tried first and was wrong for
# the opposite reason: "Longest episode." is two words and video-confirmed.
FILLERS = {"hmm", "hmmm", "mmm", "mhm", "mhmm", "mmhmm", "ahh", "aha", "haa", "haah",
           "hah", "ooh", "uhh", "umm", "err", "yeah", "okey", "okay"}

# Read off the video, frame by frame, at 1 fps with 2s of padding.
#
# ANCHORED ON A PHRASE, NOT A TIMESTAMP, and that is not a style choice. The first version
# of this list held the stamps as read during the video pass; retiming the local raw then
# moved every block by up to eight minutes, the stamps landed inside whatever block had
# slid under them, and a verified Farhan region became a 600-word Rafizi block whose
# vocabulary then dragged a dozen unrelated turns across. Same lesson as everywhere else in
# this repo: never derive a block from a stamp. The phrase is matched in the local raw and
# the block containing it is the verified one.
#
# 3:53:48 "4 jam kau gila kau" is deliberately absent: the camera confirmed Rafizi there and
# MAI already says Rafizi, so there is nothing to move.
VIDEO_CONFIRMED = {
    "0M5hweswMpE": [
        ("Ramai-ramai orang buat komen", "Farhan (Pa'an)"),
        ("Dia buat satu company to hold", "Farhan (Pa'an)"),
        ("Banyak sangat benda berlaku", "Farhan (Pa'an)"),
        ("melibatkan projek pembinaan", "Farhan (Pa'an)"),
        ("If you use certain parameters untuk inflate", "Farhan (Pa'an)"),
        ("What was public's reaction", "Farhan (Pa'an)"),
        ("Longest episode", "Farhan (Pa'an)"),
        ("after your comments ni", "Farhan (Pa'an)"),
    ],
}
VERIFIED_OVERLAP = 0.35


def seconds(stamp):
    parts = [int(p) for p in stamp.split(":")]
    return parts[0] * 3600 + parts[1] * 60 + parts[2] if len(parts) == 3 else parts[0] * 60 + parts[1]


def stamp(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"[{h}:{m:02d}:{s:02d}]" if h else f"[{m:02d}:{s:02d}]"


def blocks_of(path):
    return [(seconds(s), label.strip(), text.strip())
            for s, label, text in BLOCK.findall(path.read_text(encoding="utf-8"))]


def words_of(text):
    return [w for w in re.findall(r"[a-z']+", text.lower()) if len(w) > 2]


def local_spans(blocks, runtime, label_prefix):
    out = []
    for i, (start, label, text) in enumerate(blocks):
        if not label.startswith(label_prefix):
            continue
        end = blocks[i + 1][0] if i + 1 < len(blocks) else runtime
        out.append((start, end, text))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", help="episode tag, e.g. ep62")
    ap.add_argument("--mai", help="MAI raw.md; defaults to the sandbox for this video")
    ap.add_argument("--label", default="Farhan (Pa'an)",
                    help="the label to transplant from the local raw")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    import glob
    matches = glob.glob(str(ROOT / "episodes" / "*" / f"*-{args.tag}-*"))
    if len(matches) != 1:
        sys.exit(f"{args.tag} matched {len(matches)} episodes")
    local_path = Path(matches[0]) / "raw.md"
    fields, _ = common.read_frontmatter_body(local_path)
    video_id = fields["video_id"]
    runtime = fields["duration_seconds"]
    mai_path = Path(args.mai) if args.mai else ROOT / "data" / f"_mai_{video_id}" / "raw.md"
    if not mai_path.exists():
        sys.exit(f"{mai_path} not found")

    local = blocks_of(local_path)
    mai = blocks_of(mai_path)
    spans = local_spans(local, runtime, args.label)
    print(f"{args.tag}: {len(mai)} MAI turns, {len(local)} local blocks, "
          f"{len(spans)} local {args.label!r} blocks")

    # Each verified phrase names one local block; carry that block's speaker.
    verified = []
    for phrase, who in VIDEO_CONFIRMED.get(video_id, []):
        hits = [(i, b) for i, b in enumerate(local) if phrase.lower() in b[2].lower()]
        if len(hits) != 1:
            print(f"  [warn] {phrase!r} matched {len(hits)} local blocks, skipped")
            continue
        i, (bstart, blabel, btext) = hits[0]
        bend = local[i + 1][0] if i + 1 < len(local) else runtime
        if blabel != who:
            print(f"  [warn] {phrase!r} sits in a {blabel!r} block, not {who!r} -- skipped")
            continue
        verified.append((bstart, bend, btext, who))
    print(f"  {len(verified)} of {len(VIDEO_CONFIRMED.get(video_id, []))} verified phrases "
          f"located in the local raw")

    moved, forced, out = [], [], []
    for start, label, text in mai:
        new = label
        turn = words_of(text)
        movable = any(w not in FILLERS for w in turn)
        best_verified, who_verified = 0.0, None
        for a, b, ltext, who in verified:
            if not (a - NEAR_SECONDS <= start <= b + 2) or not turn:
                continue
            pool = set(words_of(ltext))
            score = sum(1 for w in turn if w in pool) / len(turn)
            if score > best_verified:
                best_verified, who_verified = score, who
        if (movable and who_verified and best_verified >= VERIFIED_OVERLAP
                and label != who_verified):
            new = who_verified
            forced.append((start, label, who_verified, text, best_verified))
        elif movable and not label.startswith(args.label):
            best = 0.0
            for a, b, ltext in spans:
                if not (a - NEAR_SECONDS <= start <= b + 2) or not turn:
                    continue
                pool = set(words_of(ltext))
                best = max(best, sum(1 for w in turn if w in pool) / len(turn))
            if best >= MIN_WORD_OVERLAP:
                new = args.label
                moved.append((start, label, text, best))
        out.append((start, new, text))

    print(f"\nmoved on word overlap: {len(moved)} turns, "
          f"{sum(len(t.split()) for _, _, t, _ in moved)} words")
    for start, label, text, score in sorted(moved, key=lambda r: -len(r[2].split()))[:8]:
        print(f"  {stamp(start)} {label} -> {args.label}  overlap {score:.2f}  {text[:52]}")
    print(f"\nforced by video: {len(forced)}")
    for start, label, who, text, score in forced:
        print(f"  {stamp(start)} {label} -> {who}  overlap {score:.2f}  {text[:52]}")

    collapsed = [(s, l, t) for s, l, t in out if len(t.split()) >= COLLAPSE_WORDS]
    print(f"\nMAI turns of {COLLAPSE_WORDS}+ words -- diarization collapses this cannot "
          f"reach: {len(collapsed)}")
    for s, l, t in collapsed:
        print(f"  {stamp(s)} {l} {len(t.split())} words")

    counts = {}
    for _, label, text in out:
        counts[label] = counts.get(label, 0) + len(text.split())
    print(f"\nwords per speaker: {counts}")

    if not args.write:
        print("\n-- dry run, pass --write to produce the merged file --")
        return

    body = ["# Raw Transcript", ""]
    for start, label, text in out:
        body.append(f"{stamp(start)} {label}: {text}")
        body.append("")
    merged_fields = dict(common.read_frontmatter_body(mai_path)[0])
    merged_fields["note"] = (
        f"{merged_fields.get('note', '')} MERGED: text and timings from MAI-Transcribe-2, "
        f"speaker labels for {args.label} taken from the local-ASR raw.md where its words "
        f"match, plus {len(forced)} regions read off the video. See "
        f"scripts/merge_mai_local_labels.py.").strip()
    dest = mai_path.with_name("raw_merged.md")
    dest.write_text(common.frontmatter_md(merged_fields, "\n".join(body)), encoding="utf-8")
    (dest.with_name("merge_report.json")).write_text(json.dumps({
        "moved": [{"at": stamp(s), "from": l, "overlap": round(o, 2), "text": t}
                  for s, l, t, o in moved],
        "forced_by_video": [{"at": stamp(s), "from": l, "to": w, "overlap": round(o, 2),
                             "text": t} for s, l, w, t, o in forced],
        "unreachable_collapsed_turns": [{"at": stamp(s), "label": l, "words": len(t.split())}
                                        for s, l, t in collapsed],
        "words_per_speaker": counts,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
