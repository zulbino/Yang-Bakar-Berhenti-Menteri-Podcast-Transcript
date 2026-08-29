"""Merge consecutive turns that carry the SAME named speaker into one turn.

The diarizer cuts at pauses, not at speaker changes, so one person's continuous speech
arrives as several turns under one name:

    [2:53:13] Rafizi: ... Pasal perubahan iklim 10 15 tahun
    [2:54:43] Rafizi: Aku
    [2:54:44] Rafizi: orang cakap pasal Climate change ...

Three blocks, one speaker, and "Aku" is a fragment of the sentence that follows it. Nothing
is gained by keeping them apart and a reader loses the sentence. Corpus-wide: 707 runs in
raw.md across 45 episodes (1,150 turns), and 1,175 runs across 185 of the 204 published
files (1,868 turns).

ONLY NAMED SPEAKERS ARE MERGED, and this is the part that matters. Two consecutive
`Speaker ?` turns are not evidence of one person -- `Speaker ?` means "nobody identified
this", so merging two of them would assert they are the same unidentified person, which is
a claim nobody made. Same for `Multiple speakers`: two crosstalk runs merged into one would
imply a single continuous stretch of the same voices. Both are left alone, along with every
other generic label, so this tool can only ever join speech that is already attributed to
one named person.

SAFE AGAINST THE TWO CHECKS THAT MEASURE BLOCK SIZE, verified before writing:
  `wall-of-text` is gated on a block holding MORE THAN ONE inline turn marker, and a merged
  block holds exactly one, so it cannot fire.
  `oversized-block` measures a block's wall-clock span, which merging DOES grow -- 15
  episodes' longest block gets longer. Simulated across all 68: **zero** would cross the
  20-minute threshold, so no new flags.

THE ONE REAL COST: intermediate timestamps disappear. A 14-turn Rafizi run in ep26 becomes
one block with one seek point instead of fourteen, which is a loss for anyone hunting a
moment in a three-hour episode. The owner's call, made deliberately.

  python scripts/merge_same_speaker.py                 # report
  python scripts/merge_same_speaker.py --write
  python scripts/merge_same_speaker.py --raw-only --write
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_published import DERIVED
from label_drift_audit import GENERIC

ROOT = Path(__file__).resolve().parent.parent
RAW_TURN = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]\s*([^:\n]{1,40}?)\s*:\s*(.*)$")
PUB_TURN = re.compile(r"^\*\*([^*]{2,40}?):\*\*\s*(.*)$")
# `Speaker ?` and `Penutur (tidak dikenali)` are honest-unknown markers, not names, and
# GENERIC does not match them -- so they need excluding explicitly or they would merge.
UNKNOWN = re.compile(r"^(speaker|penutur|penceramah)\s*\?+$|tidak dikenali|unidentified"
                     r"|^multiple speakers$|^beberapa penutur$", re.I)


def mergeable(label):
    return not GENERIC.match(label) and not UNKNOWN.match(label.strip())


# --- second pass: fold an unknown BACKCHANNEL turn into the named turn before it ---
#
# This one MAKES A CLAIM, unlike the same-label merge above, which makes none. Folding
# `Speaker ?` "Hmm" into Rafizi's turn asserts Rafizi said it, and the owner's own
# adjudications show the preceding speaker is a poor predictor: of 7 unknown turns sitting
# between two turns by the SAME person, 6 turned out to be somebody else. A turn becomes an
# unknown cluster precisely because the diarizer heard something the neighbours are not.
#
# It is done anyway, on the owner's decision, and only where being wrong carries no
# content: an acknowledgement noise in the wrong mouth changes nothing a reader relies on.
# So the filter is deliberately narrow -- laughter and acknowledgement tokens ONLY.
# Everything with a proposition stays `Speaker ?`, including single words that look small:
# `0.017` is a figure, `Forward` and `Juali` are content, and `Saya boleh lihat.` recurs
# six times across five episodes and is somebody's actual sentence.
LAUGH = re.compile(r"^(?:ha|he|hi|hu){2,}$", re.I)
BACKCHANNEL = {
    "hmm", "hm", "hmmm", "mmm", "mm", "mhm", "haa", "ha", "hah", "heh", "aha",
    "uh", "uhh", "eh", "ehh", "ah", "ahh", "oh", "ohh", "erm", "er", "aa", "aaa",
    "ya", "yes", "yeah", "ok", "okay", "okey", "han",
}


def is_backchannel(said):
    toks = [t.strip(".,?!…\"'*-…").lower() for t in said.split()]
    toks = [t for t in toks if t]
    if not toks or any(any(c.isdigit() for c in t) for t in toks):
        return False
    return all(t in BACKCHANNEL or LAUGH.match(t) for t in toks)


def fold_unknown_fillers(text, pattern, rebuild):
    """Append an unknown backchannel turn to the preceding NAMED turn."""
    blocks = text.split("\n\n")
    out, folded = [], 0
    for b in blocks:
        m = pattern.match(b.strip())
        said = m.group(3 if pattern is RAW_TURN else 2) if m else None
        label = (m.group(2 if pattern is RAW_TURN else 1).strip()) if m else None
        pm = pattern.match(out[-1].strip()) if out else None
        prev_label = (pm.group(2 if pattern is RAW_TURN else 1).strip()) if pm else None
        if (m and label and UNKNOWN.match(label) and is_backchannel(said)
                and pm and prev_label and mergeable(prev_label)):
            out[-1] = rebuild(pm, (pm.group(3 if pattern is RAW_TURN else 2).rstrip()
                                   + " " + said.strip()).strip())
            folded += 1
            continue
        out.append(b.strip() if m else b)
    return "\n\n".join(out), folded


def merge_blocks(text, pattern, rebuild):
    """Join consecutive blocks whose label matches, using `rebuild(head, joined_text)`."""
    blocks = text.split("\n\n")
    out, merged = [], 0
    for b in blocks:
        m = pattern.match(b.strip())
        if not m:
            out.append(b)
            continue
        label = m.group(2 if pattern is RAW_TURN else 1).strip()
        said = m.group(3 if pattern is RAW_TURN else 2)
        prev = out[-1].strip() if out else ""
        pm = pattern.match(prev)
        prev_label = (pm.group(2 if pattern is RAW_TURN else 1).strip()) if pm else None
        if pm and prev_label == label and mergeable(label):
            out[-1] = rebuild(pm, (pm.group(3 if pattern is RAW_TURN else 2).rstrip()
                                   + " " + said.lstrip()).strip())
            merged += 1
        else:
            out.append(b.strip() if m else b)
    return "\n\n".join(out), merged


def spoken(text, pattern):
    """Every word anyone says, in order, with turn markers stripped."""
    out = []
    for b in text.split("\n\n"):
        m = pattern.match(b.strip())
        out += (m.group(3 if pattern is RAW_TURN else 2) if m else b).split()
    return out


def main():
    write = "--write" in sys.argv
    raw_only = "--raw-only" in sys.argv
    no_fold = "--no-fold-fillers" in sys.argv
    tot, tot_fold, touched = 0, 0, 0
    for d in sorted((ROOT / "episodes").glob("*/*")):
        names = ["raw.md"] if raw_only else ["raw.md"] + DERIVED
        for name in names:
            p = d / name
            if not p.exists():
                continue
            is_raw = name == "raw.md"
            pattern = RAW_TURN if is_raw else PUB_TURN
            rebuild = ((lambda m, t: f"[{m.group(1)}] {m.group(2).strip()}: {t}") if is_raw
                       else (lambda m, t: f"**{m.group(1).strip()}:** {t}"))
            text = p.read_text(encoding="utf-8")
            # Fold the unknown backchannel FIRST, so a filler sitting between two turns by
            # the same person does not block them from merging afterwards.
            new, folded = ((text, 0) if no_fold
                           else fold_unknown_fillers(text, pattern, rebuild))
            new, n = merge_blocks(new, pattern, rebuild)
            if not n and not folded:
                continue
            # Compare the SPOKEN words only. A merge necessarily removes the absorbed
            # turn's "[stamp] Label:" prefix, so comparing every token would always
            # differ -- which is what the first version of this assertion did, and it
            # fired on the first episode. What must not change is what anyone said.
            assert spoken(new, pattern) == spoken(text, pattern), \
                f"{p}: merge changed the words"
            tot += n
            tot_fold += folded
            touched += 1
            extra = f" +{folded} filler" if folded else ""
            print(f"  {n:>4} merged{extra:<12} {d.name[:40]:<42} {name}")
            if write:
                p.write_text(new, encoding="utf-8")
    print(f"\n{tot} same-speaker turn(s) merged, {tot_fold} unknown backchannel turn(s) "
          f"folded, across {touched} file(s)")
    print("written -- raw.md changes do NOT need a rewrite regeneration: no check compares "
          "raw and published turn BOUNDARIES, only labels, names and figures"
          if write else "dry run -- pass --write to apply")


if __name__ == "__main__":
    main()
