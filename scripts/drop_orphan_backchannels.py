"""Drop a contentless backchannel turn that sits inside one speaker's continuous run.

WHY THIS EXISTS. Owner's decision 2026-09-16, after a 19-row blind sample measured the
one-face lip-sync test at 12 of 19: *"actually anything offscreen, and the word is just not
adding in to anything, we can just safely omit?"*

The problem it answers is unsolvable by evidence. A short turn between two blocks of the
same other speaker cannot be attributed: the camera reference is LR-ASD lip-sync, so it
credits the one visible talking face, and 10 of the owner's 19 rows were the other person
speaking OFF FRAME where no camera can see them. Measured, no threshold separates the two
cases: the on-screen minimum score runs -0.49 to 3.77 and the offscreen one -0.82 to 2.99,
and the offscreen mean is HIGHER. So rule 1 of mai_camera_raw.py stays, and for the subset
that carries no content the owner's answer is to remove the turn rather than guess its name.

WHAT IT REMOVES, AND WHAT IT REFUSES. Measured across every adopted raw.md, 1480 short
turns have this shape. 231 are a pure backchannel and go. 52 are borderline and are
DELIBERATELY NOT IN THE LEXICON, because they carry a position rather than a signal:
`Betul.` (14), `Ya, betul.` (8), `Kan.` (5), `Kan?` (4), `Setuju.` (3), `Alhamdulillah.`
(3), `Right?` (2). `Setuju.` means "I agree", which is a stance. `Alhamdulillah.` is a
religious expression. `Kan?` is often the MAIN speaker's own tag question, which the owner's
ep18 1:35:02 ruling established. The remaining 1197 carry content and stay wrong until an
ear rules them. Do not widen ACK without the owner: this is a deletion from the verbatim
source.

FIVE CONDITIONS, ALL REQUIRED:

  1. The turn's every token is in ACK, a CLOSED LEXICON. No regex, no similarity. That is
     the standing rule for any deletion in this repo.
  2. The blocks either side carry one and the same name, and it is not this block's name.
     Without this, dropping every `Okey.` would delete Haziq's real segment handovers
     ("Okey, baik YB, selesai"), which are turns, not backchannels.
  3. At most MAX_WORDS tokens.
  4. Neither this block nor its neighbours carry a generic label. `Speaker ?` and
     `Multiple speakers` are different claims and this tool has no opinion on them.
  5. No owner decision names the turn. The decision files are read directly and a named
     turn is printed and skipped, never quietly removed.

WHY IT RUNS AFTER THE MERGE, not inside strip_filler_turns.py at step 3: before the merge a
backchannel's neighbour is often another fragment of the same sentence rather than the
speaker's own block, so condition 2 cannot fire. Same reason the fold runs late.

Dropping a turn makes its two neighbours adjacent, so merge_same_speaker.py MUST run after
this. adopt_mai_camera_raw.py step 6d does both.

  python scripts/drop_orphan_backchannels.py ep20
  python scripts/drop_orphan_backchannels.py ep20 --write
"""
import argparse
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
GENERIC = re.compile(r"^(Speaker|Multiple|Audience)", re.I)
PUNCT = re.compile(r"[^\w\s'-]")
MAX_WORDS = 3
MAI_MODEL = "microsoft/MAI-Transcribe-2"

# CLOSED LEXICON. Pure acknowledgement tokens only: they signal "I am listening" and assert
# nothing. `ha`, `eh`, `aa` and `oh` are absent on purpose -- CLAUDE.md rule 5 keeps them
# because they carry meaning in spoken Malay, and a turn containing one is not dropped here.
ACK = {"ya", "yaa", "yah", "yeah", "yep", "yup", "yes",
       "ok", "oke", "okey", "okay", "baik", "yalah"}

DECISION_FILES = ["speaker_adjudications.json", "speaker_video_confirmed.json",
                  "speaker_video_confirmed_ep61_round2.json", "speaker_q_video_confirmed.json",
                  "speaker_from_gold.json", "forced_labels.json",
                  "speaker_owner_ear_2026_09_11.json"]


def tokens(text):
    return [t for t in (PUNCT.sub("", w).lower() for w in text.split()) if t]


def is_backchannel(text):
    tk = tokens(text)
    return bool(tk) and all(t in ACK for t in tk)


def short(name):
    return name.split(" (")[0].strip()


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
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    path = Path(common.raw_for_tag(a.tag))
    text = path.read_text(encoding="utf-8")

    # REFUSES AN UNADOPTED EPISODE, and this closes one of the two rules CLAUDE.md lists as
    # having no mechanism: "Reprocess an unadopted episode with the camera; never hand-patch
    # its local-ASR raw." A first corpus-wide dry run offered to edit ep07, ep08, ep10, ep11
    # and ep14, none of them adopted. Excluding `model: mesolitica` is NOT enough: ep07 and
    # ep10 carry no `model:` line at all because they predate the field, which is
    # check_raw_engine.py's `raw-engine-unknown` case. So this requires the MAI build
    # positively rather than excluding the engines it knows about.
    if MAI_MODEL not in text:
        sys.exit(f"REFUSING: {a.tag}'s raw.md does not declare `{MAI_MODEL}`, so it is not "
                 f"the MAI+camera build. A deletion here would be wiped by adoption anyway. "
                 f"Run nightly_recut.py then adopt_mai_camera_raw.py first.")

    blocks = BLOCK.findall(text)
    decided = decision_texts(a.tag)

    drop, skipped = [], []
    for i in range(1, len(blocks) - 1):
        st, who, said = blocks[i]
        before, after = blocks[i - 1][1], blocks[i + 1][1]
        if GENERIC.match(who) or GENERIC.match(before) or GENERIC.match(after):
            continue
        if before != after or short(who) == short(before):
            continue
        if not said or len(said.split()) > MAX_WORDS or not is_backchannel(said):
            continue
        low = said.lower()
        if any(low == d or low.strip(".?!") == d.strip(".?!") for d in decided):
            skipped.append((st, who, said))
            continue
        drop.append((i, st, who, before, said))

    for st, who, said in skipped:
        print(f"  SKIPPED, an owner decision names it: [{st}] {who}: {said}")
    for _, st, who, nbr, said in drop:
        print(f"  drop [{st}] {who}: {said}   (inside a {short(nbr)} run)")

    words = sum(len(s.split()) for *_, s in drop)
    print(f"{a.tag}: {len(drop)} orphan backchannel turn(s) to drop, {words} word(s), "
          f"{len(skipped)} skipped as owner decisions")

    if not drop or not a.write:
        if drop:
            print("\n-- dry run, pass --write to apply")
        return 0

    # Remove whole blocks by their exact text, then assert nothing else moved. A block is
    # matched on its full rendered line, so a stamp collision cannot take the wrong one.
    paras = text.split("\n\n")
    targets = Counter(f"[{st}] {who}: {said}" for _, st, who, _, said in drop)
    kept, taken = [], Counter()
    for p in paras:
        key = p.strip()
        if targets[key] > taken[key]:
            taken[key] += 1
            continue
        kept.append(p)
    if sum(taken.values()) != len(drop):
        sys.exit(f"REFUSING: matched {sum(taken.values())} block(s) but planned {len(drop)}")
    out = "\n\n".join(kept)

    # The expected loss is the WHOLE removed block, stamp and speaker name included, not
    # just its spoken text. A first version compared only `said` and the guard correctly
    # refused, reporting `Haziq`, `24`, `28` and the rest as unexplained losses.
    lost = Counter(re.findall(r"[\w'-]+", text)) - Counter(re.findall(r"[\w'-]+", out))
    expect = Counter()
    for _, st, who, _, said in drop:
        expect.update(re.findall(r"[\w'-]+", f"[{st}] {who}: {said}"))
    if lost != expect:
        sys.exit("REFUSING: the words removed are not the words planned. "
                 f"extra={dict(lost - expect)} missing={dict(expect - lost)}")
    path.write_text(out, encoding="utf-8")
    spoken = sum(len(re.findall(r"[\w'-]+", s)) for *_, s in drop)
    print(f"   verified: {len(drop)} whole block(s) removed and nothing else changed; "
          f"{spoken} spoken word(s) left the file")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
