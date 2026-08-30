"""Turn video-confirmed attribution regions into an apply_split_map.py split map.

WHY THIS IS A SEPARATE FILE FROM data/speaker_adjudications.json. That file holds what the
OWNER decided by ear, and apply_split_map.py's docstring is explicit that the owner is the
only reliable source for who spoke. The regions here were derived by a tool and then
checked on video, which is strong evidence but a different KIND of evidence. Mixing them
would make the owner's own decisions unauditable later, so they go to
data/speaker_video_confirmed.json with the frame check recorded per region.

WHAT IT DOES. For each confirmed region it writes a `split` entry that cuts the enclosing
raw.md block into up to three turns -- the speech before the region under the block's
existing label, the region itself under the sensed label, and the remainder back under the
existing label. apply_split_map.py then applies it and asserts the word sequence of every
touched block is identical before and after, so no wording can change.

Cut points are LITERAL SUBSTRINGS of the block text, which is what apply_split_map.py
expects, and this refuses to emit one that is not unique inside its block -- a repeated
phrase would silently cut in the wrong place. Timestamps come from the caption word track,
never from interpolating the parent block's stamp (ENGINEERING_LOG 2.6).

Usage:
  python scripts/build_region_split_map.py --audit data/_audit_ep61_postfix.json \\
      --confirmed 1,2,3,4,5,6,7,8,9,10,12,13,14,15,16 --out data/speaker_video_confirmed.json
"""
import argparse
import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from sense_speakers import AUDIO, BLOCK, caption_words, episode_dir, norm, video_id_of

ROOT = Path(__file__).resolve().parent.parent
TAIL_WORDS = 8          # length of a cut-point substring before uniqueness is tested
MIN_REGION_WORDS = 4    # below this a region is too small to cut on safely


def block_tokens(folder, caps):
    """Per raw.md block: its stamp, label, text, and (token, char_end, time) per word.

    Times come from one global difflib pass against the caption word stream, the same
    method the sensing uses, so a garbled word does not break the mapping -- the words
    either side of it still match and pin it.
    """
    body = (folder / "raw.md").read_text(encoding="utf-8").split("---", 2)[2]
    blocks = []
    for m in BLOCK.finditer(body):
        toks = [(w.group(0), w.end()) for w in re.finditer(r"[\w']+", m.group(3))]
        blocks.append({"stamp": m.group(1), "label": m.group(2).strip(),
                       "text": m.group(3), "toks": toks})

    flat, owner = [], []
    for bi, b in enumerate(blocks):
        for ti, (w, end) in enumerate(b["toks"]):
            if norm(w):
                flat.append(norm(w))
                owner.append((bi, ti))

    sm = difflib.SequenceMatcher(a=flat, b=[w for w, _ in caps], autojunk=False)
    times = [None] * len(flat)
    for i, j, k in sm.get_matching_blocks():
        for d in range(k):
            times[i + d] = caps[j + d][1]
    # a token that did not match sits between its matched neighbours
    for i, t in enumerate(times):
        if t is None:
            prv = next((times[j] for j in range(i - 1, -1, -1) if times[j] is not None), None)
            nxt = next((times[j] for j in range(i + 1, len(times)) if times[j] is not None), None)
            times[i] = prv if prv is not None else nxt

    for b in blocks:
        b["timed"] = []
    for i, (bi, ti) in enumerate(owner):
        if times[i] is not None:
            blocks[bi]["timed"].append((ti, blocks[bi]["toks"][ti][0],
                                        blocks[bi]["toks"][ti][1], times[i]))
    return blocks


def stamp_of(seconds):
    s = int(seconds)
    return (f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}" if s >= 3600
            else f"{(s % 3600) // 60:02d}:{s % 60:02d}")


def token_end(text, char):
    r"""Extend a word-match end past any punctuation stuck to it.

    This matters more than it looks. The token positions come from `[\w']+`, which stops
    before trailing punctuation, so a cut taken there splits `Tuh...` into `Tuh` and a
    free-standing `...`. apply_split_map.py's word check collapses " ... " -- its own
    marker for an unapportionable run -- so the orphaned ellipsis vanishes and the two word
    sequences no longer match. Its assertion caught exactly that on ep61's [2:30:31]. This
    ASR emits trailing ellipses constantly, so the cut has to take the whole token.
    """
    while char < len(text) and not text[char].isspace():
        char += 1
    return char


def cut_text(block, upto_char):
    """The last TAIL_WORDS words ending at upto_char, as a literal substring."""
    upto_char = token_end(block["text"], upto_char)
    words = [(m.group(0), m.start(), m.end())
             for m in re.finditer(r"[\w']+", block["text"][:upto_char])]
    if not words:
        return None
    take = words[-TAIL_WORDS:]
    return block["text"][take[0][1]:upto_char]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", required=True)
    ap.add_argument("--confirmed", required=True,
                    help="comma-separated 1-based region numbers confirmed on video")
    ap.add_argument("--out", required=True)
    ap.add_argument("--frames", default="", help="the contact sheet(s) the check used")
    a = ap.parse_args()

    audit = json.loads(Path(a.audit).read_text(encoding="utf-8"))
    want = {int(x) for x in a.confirmed.split(",") if x.strip()}
    tag = audit["episode"]
    folder = episode_dir(tag)
    vid = audit["video_id"]
    caps = [(norm(w), t) for w, t in
            caption_words((AUDIO / f"{vid}.ms.vtt").read_text(encoding="utf-8"))]
    caps = [c for c in caps if c[0]]
    blocks = block_tokens(folder, caps)

    entries, skipped = {}, []
    for n, r in enumerate(audit["regions"], 1):
        if n not in want:
            continue
        b = blocks[r["block"]]
        inside = [t for t in b["timed"] if r["t0"] - 0.35 <= t[3] <= r["t1"] + 0.35]
        if len(inside) < MIN_REGION_WORDS:
            skipped.append((n, f"only {len(inside)} raw.md words map into the region"))
            continue
        first_ti, last_ti = inside[0][0], inside[-1][0]
        # contiguity: the region must be one run of the block's words
        span = [t for t in b["timed"] if first_ti <= t[0] <= last_ti]
        if len(span) != len(inside):
            skipped.append((n, "region words are not contiguous inside the block"))
            continue

        before = [t for t in b["timed"] if t[0] < first_ti]
        after = [t for t in b["timed"] if t[0] > last_ti]
        parts = []
        if before:
            txt = cut_text(b, before[-1][2])
            parts.append([b["label"], txt, b["stamp"]])
        region_txt = cut_text(b, inside[-1][2])
        parts.append([r["name"], region_txt if after else None, stamp_of(r["t0"])])
        if after:
            parts.append([b["label"], None, stamp_of(r["t1"])])

        if len(parts) == 1:
            # `was` and `text_was` are not optional here. A split re-uses its parent's
            # stamp, so a stamp is NOT unique in this corpus and a bare {"who": ...} can
            # match two turns. apply_split_map refuses rather than guessing, correctly.
            entries.setdefault(b["stamp"], {}).update(
                {"who": r["name"], "was": b["label"],
                 "text_was_startswith": b["text"].strip()[:60]})
            note = "whole block relabelled"
        else:
            bad = [p[1] for p in parts if p[1] and b["text"].count(p[1]) != 1]
            if bad:
                skipped.append((n, f"cut point is not unique in the block: {bad[0][:40]!r}"))
                continue
            if b["stamp"] in entries:
                skipped.append((n, f"block at [{b['stamp']}] already has an entry; "
                                   "two regions in one block need one combined split"))
                continue
            entries[b["stamp"]] = {"split": parts}
            note = f"{len(parts)}-way split"
        print(f"  region {n:>2}  [{b['stamp']}] {b['label']:>14} -> {r['name']:<8} "
              f"{r['secs']:>5.1f}s  {note}")

    if skipped:
        print("\n  SKIPPED, and each of these needs a look rather than a retry:")
        for n, why in skipped:
            print(f"    region {n:>2}: {why}")

    payload = {
        "_README": [
            "Attribution regions found by scripts/audit_block_attribution.py and then",
            "CHECKED ON VIDEO frame by frame. Apply with:",
            "",
            f"    python scripts/apply_split_map.py {a.out}",
            f"    python scripts/apply_split_map.py {a.out} --write",
            "",
            "THIS IS NOT data/speaker_adjudications.json AND MUST NOT BE MERGED INTO IT.",
            "That file holds what the owner decided by ear. These regions were derived by a",
            "tool and then confirmed against the camera, which is strong evidence of a",
            "different kind. Keeping them apart is what lets a later reader tell which",
            "claims rest on the owner's ear and which rest on a frame.",
            "",
            "WHY THE CAMERA IS EVIDENCE HERE. The show cuts to whoever is talking. That is",
            "unreliable for rapid exchange, because the cut lags speech by about 2 seconds",
            "and not by a fixed amount, and a two-shot proves nothing. Every region below is",
            "at least 15 seconds of continuous speech under one label, which is exactly the",
            "case where the camera has settled and the frame is decisive.",
            "",
            "WHAT IS NOT CLAIMED. The sensing score on the owner's 18-turn gold passage moved",
            "between 72% and 83% under a change that should have been neutral, so per-turn",
            "accuracy on SHORT turns is not established. These regions are not short turns,",
            "and their spans and directions were stable across that same change -- which is",
            "why they were worth checking on video and short turns were not.",
        ],
        "_frames": a.frames,
        "_source_audit": a.audit,
        f"{tag}_video_confirmed": entries,
    }
    Path(a.out).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"\nwrote {a.out}: {len(entries)} block entries "
          f"({len(want) - len(skipped)} of {len(want)} regions)")


if __name__ == "__main__":
    main()
