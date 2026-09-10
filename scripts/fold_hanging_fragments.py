"""Give a hanging fragment the camera cannot see to the speaker on both sides of it.

WHY. MAI-Transcribe-2 emits one phrase per turn when it runs without diarization, so one
sentence arrives as several turns and the camera labels each of them separately. Where the
camera has no opinion for those seconds -- a graphic on screen, a wide shot, a frame the
active-speaker model would not commit on -- the label falls back to the old transcript's
label for that time, and the result is a sentence split between two people:

    [2:42:27] Haziq: Mereka ini uh dah berdepan
    [2:42:32] Rafizi: dengan semua ini selepas 2018. Betul. Cluster mahkamah...

The owner found that shape on ep61 and asked for it gone. It is a labelling artefact, not
speech: nobody says five words and hands the rest of the sentence to someone else.

FIVE CONDITIONS, ALL REQUIRED, and the camera one is the whole safety argument:

  1. The camera covers NONE of the fragment's seconds. A fragment the camera ATTESTS is
     never folded, however short and however mid-sentence -- that is exactly how a minority
     speaker gets deleted, and this corpus has done it once already (ATTRIBUTION_PASS.md,
     the Farhan turn at 2:51:42). On ep61 the camera attests nine of the twelve hanging
     fragments: Haziq really does finish Rafizi's sentences, for 2 to 11 seconds at a time.
  2. The blocks either side carry one and the same name, and it is not this block's name.
  3. The fragment is at most MAX_WORDS long.
  4. It ends without terminal punctuation and the next block starts lower-case.
  5. No owner decision names it. The decision files are read directly; a fragment whose
     text matches one is skipped and printed, never quietly relabelled.

WHY IT IS A SEPARATE STEP, run AFTER strip_filler_turns.py: inside mai_camera_raw.py the
fragment's neighbours are often a one-word grunt turn ("Uh.") rather than the speaker's own
speech, so condition 2 fails and the fragment survives. ep61's 27:24 fragment escaped that
way. Once the grunts are gone the real neighbours are adjacent.

Only labels change. The word sequence is asserted identical before anything is written.

  python scripts/fold_hanging_fragments.py ep61
  python scripts/fold_hanging_fragments.py ep61 --write
"""
import argparse
import glob
import io
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"^\[([\d:]+)\]\s*([^:\n]{0,40}?):\s*(.*)$", re.M)
MAX_WORDS = 10
DECISION_FILES = ["speaker_adjudications.json", "speaker_video_confirmed.json",
                  "speaker_video_confirmed_ep61_round2.json", "speaker_q_video_confirmed.json",
                  "speaker_from_gold.json", "forced_labels.json"]


def secs(t):
    q = [int(x) for x in t.split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(q)))


def camera_seconds(path):
    out = {}
    for line in io.open(path, encoding="utf-8"):
        f = line.split()
        if f[0] != "SPEAKER":
            continue
        a, dur = float(f[3]), float(f[4])
        for t in range(int(a), int(a + dur) + 1):
            out[t] = f[7].replace("_", " ")
    return out


def decision_texts(tag):
    """Every snippet of text an owner decision on this episode is recorded against."""
    out = []
    for name in DECISION_FILES:
        path = ROOT / "data" / name
        if not path.exists():
            continue
        blob = json.load(io.open(path, encoding="utf-8"))
        for section, rules in blob.items():
            if section.startswith("_") or tag not in section.lower():
                continue
            items = rules.values() if isinstance(rules, dict) else rules
            for r in items:
                if not isinstance(r, dict):
                    continue
                for key in ("text", "text_now", "text_was", "text_was_startswith"):
                    if r.get(key):
                        out.append(r[key].lower())
                for part in r.get("split", []):
                    if len(part) > 1 and part[1]:
                        out.append(part[1].lower())
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--reference", help="default data/camera_ref_<tag>.rttm")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    raw_path = common.raw_for_tag(a.tag)
    path = Path(raw_path)
    text = path.read_text(encoding="utf-8")
    camera = camera_seconds(a.reference or ROOT / "data" / f"camera_ref_{a.tag}.rttm")
    blocks = BLOCK.findall(text)
    decided = decision_texts(a.tag)

    folds, skipped, attested = [], [], 0
    for i in range(1, len(blocks) - 1):
        (st, who, said), (_, before, _), (nxt, after, next_said) = (
            blocks[i], blocks[i - 1], blocks[i + 1])
        if before != after or who == before or not said or not next_said:
            continue
        if len(said.split()) > MAX_WORDS:
            continue
        if said.rstrip()[-1] in '.?!:"' or not next_said.split()[0][:1].islower():
            continue
        vote = Counter(camera.get(t) for t in range(secs(st), max(secs(st) + 1, secs(nxt))))
        if any(k for k in vote if k):
            attested += 1
            continue
        if any(d[:40] in said.lower() or said.lower()[:40] in d for d in decided):
            skipped.append((st, who, said))
            continue
        folds.append((i, st, who, before, said))

    for st, who, said in skipped:
        print(f"  SKIPPED, an owner decision names it: [{st}] {who}: {said}")
    for _, st, who, to, said in folds:
        print(f"  fold [{st}] {who} -> {to}: {said}")
    print(f"{a.tag}: {len(folds)} hanging fragment(s) the camera cannot see, "
          f"{attested} left alone because the camera attests them, {len(skipped)} skipped as "
          "owner decisions")

    if not folds or not a.write:
        if folds:
            print("\n-- dry run, pass --write to apply")
        return

    out = text
    for _, st, who, to, said in folds:
        old = f"[{st}] {who}: {said}"
        assert out.count(old) == 1, f"{old!r} is not unique in the file"
        out = out.replace(old, f"[{st}] {to}: {said}")
    before_words = re.sub(r"^\[[\d:]+\]\s*[^:\n]{0,40}?:\s*", " ", text, flags=re.M).split()
    after_words = re.sub(r"^\[[\d:]+\]\s*[^:\n]{0,40}?:\s*", " ", out, flags=re.M).split()
    if before_words != after_words:
        sys.exit("REFUSING TO WRITE: the word sequence changed")
    path.write_text(out, encoding="utf-8")
    print(f"wrote {path} -- labels only, {len(before_words)} words unchanged")


if __name__ == "__main__":
    main()
