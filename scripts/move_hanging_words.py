"""Move a hanging half-sentence to the speaker who finishes it.

WHY. The owner, on ep61, 2026-09-10:

    [40:06] Haziq: Sempena uh menyambut Hari Kemerdekaan. Ha, jadi kita ada
    [40:12] Rafizi: satu topik, iaitu topik. Topik berat ni.

    "it should be ... [40:06] Haziq: Sempena uh menyambut Hari Kemerdekaan.
     [40:12] Rafizi: Ha, jadi kita ada satu topik ... do check hanging words that
     suddenly different speaker continuing it, its unheard of"

They are right, and it is a different defect from the one `fold_hanging_fragments.py`
handles. There the WHOLE block was mislabelled. Here the block is correctly Haziq up to
"Kemerdekaan." and the four words after it belong to the next block. Nobody stops in the
middle of their own sentence and lets the other host finish it.

WHERE IT COMES FROM. MAI emits one phrase per turn when it runs without diarization, and a
phrase boundary is a pause, not a speaker change. A pause lands mid-sentence often enough
that the camera then labels the first half and the second half separately.

WHAT MOVES. Only the tail of the block AFTER its last sentence end, only when the next block
starts lower-case under a different name, and only when the tail is at most MAX_TAIL_WORDS
long. Nothing is rewritten: the words keep their order, the file keeps every word, and the
assert at the end proves it.

THE CAMERA DOES NOT GET A VETO HERE, and that is a deliberate reversal. The first version
left a tail alone when the camera attested the current speaker, and on ep61's 40:06 the
camera does attest Haziq for those four seconds -- yet the words are Rafizi's, as the owner
said. The reason is already recorded in ATTRIBUTION_PASS.md: **a camera cut is not a speaker
change.** The show cuts to whoever it wants, including a reaction shot of the person who is
about to answer, and the owner has confirmed twice before that blocks split this way were
one speaker throughout. Their instruction, 2026-09-10: *"ive been repeating this hanging
sentence by different speakers multiple times, it should not be repeated again."*

So the SHAPE decides: a sentence is not split between two speakers. The camera vote over the
tail's own word times is still read out of MAI's word list and printed, because it is
evidence worth seeing, and `--camera-veto` restores the old behaviour for a one-off check.
The length guard is what keeps this safe: a tail longer than MAX_TAIL_WORDS is a turn of its
own, not a hanging fragment, and it is printed for a person instead of moved.

  python scripts/move_hanging_words.py ep61
  python scripts/move_hanging_words.py ep61 --write
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
import strip_inline_fillers  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"^\[([\d:]+)\]\s*([^:\n]{0,40}?):\s*(.*)$", re.M)
WORD = re.compile(r"[0-9A-Za-zÀ-ɏ']+")
MAX_TAIL_WORDS = 12
MIN_ATTEST = 2                # the camera's own `tail` bar: one stray second is the cut
GOLD_PAD = 60                # the same padding check_owner_decisions.py uses
SEARCH_WINDOW = 180          # seconds either side of the block stamp to look for the words
# The inline fillers strip_inline_fillers.py removes from raw.md at step 3 of the adoption.
# times_of() must skip these in MAI's word list or its sequence match cannot find a block
# whose fillers are already gone. Imported rather than copied so the two cannot drift.
FILLER_TOKENS = {f.lower() for f in strip_inline_fillers.FILLERS}


def secs(t):
    q = [int(x) for x in t.split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(q)))


def fmt(s):
    s = int(s)
    return f"{s//3600}:{s%3600//60:02d}:{s%60:02d}" if s >= 3600 else f"{s//60:02d}:{s%60:02d}"


def toks(text):
    return [w.lower() for w in WORD.findall(text)]


def mai_words(vid):
    """[(token, seconds)] for every word MAI transcribed, in time order."""
    out = []
    for path in sorted(glob.glob(str(ROOT / f"data/_mai_{vid}/mai_response_*.json"))):
        blob = json.load(io.open(path, encoding="utf-8"))
        base = blob.get("_chunk_start_s", 0)
        for phrase in blob.get("phrases", []):
            for w in phrase.get("words") or []:
                token = toks(w["text"])
                if token:
                    out.append((token[0], base + w["offsetMilliseconds"] / 1000))
    out.sort(key=lambda x: x[1])
    return out


def gold_window(vid):
    """The owner-dictated passage, if this episode has one. Its words never move."""
    import json as _json
    path = ROOT / "data" / "speaker_ground_truth.json"
    if not path.exists():
        return None
    for g in _json.load(io.open(path, encoding="utf-8")).values():
        if not isinstance(g, dict) or g.get("video_id") != vid:
            continue
        found = re.findall(r"(\d{1,2}:\d{2}(?::\d{2})?)", g.get("region", ""))
        if len(found) >= 2:
            return secs(found[0]) - GOLD_PAD, secs(found[1]) + GOLD_PAD
    return None


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


def times_of(tail, words, near):
    """When were these words spoken? Matched as a sequence, nearest the block's stamp."""
    want = toks(tail)
    if not want:
        return []
    # MAI'S WORD LIST STILL CONTAINS THE FILLERS raw.md NO LONGER DOES, so the sequence
    # match has to skip them. strip_inline_fillers.py runs at step 3 of the adoption and
    # this runs at step 5, so by now a block reading `Cuma dia` was actually spoken as
    # `cuma uh dia`. Matching the block's tokens against the unstripped list finds nothing,
    # the caller reports `camera no coverage`, and the whole-block branch then REFUSES a
    # move the camera could attest -- rule 7 requires the camera to name the next speaker
    # there, so a false negative reads as an honest refusal and goes to the owner instead.
    # ep27's 05:25 escalated on 2026-09-15 for exactly this, and the camera had said Rafizi
    # for the whole of 306-328s. The owner spotted it: "his face clearly on turn?"
    # Dropped by the SAME closed lexicon that removed them, never by a general skip, so a
    # real word can never be stepped over to force a match.
    words = [(w, t) for w, t in words if w not in FILLER_TOKENS]
    best = None
    for i in range(len(words) - len(want) + 1):
        if words[i][0] != want[0]:
            continue
        if [w for w, _ in words[i:i + len(want)]] != want:
            continue
        gap = abs(words[i][1] - near)
        if gap <= SEARCH_WINDOW and (best is None or gap < best[0]):
            best = (gap, i)
    if best is None:
        return []
    return [t for _, t in words[best[1]:best[1] + len(want)]]


def owner_rulings(tag):
    """{stamp: speaker} from data/speaker_adjudications.json, for this episode only.

    THE SHAPE IS A BARE STAMP KEY IN A SECTION WHOSE NAME CARRIES THE EPISODE TAG, e.g.
    section `ep56_rule7_tail_owner_ruled_2026_09_13` holding key `01:24`. That is what
    CLAUDE.md rule 7 mandates and what check_owner_decisions.py reads.

    THIS FUNCTION USED TO REQUIRE `ep56@01:24` INSTEAD, and measured on 2026-09-15 not one
    of the 103 stamp keys in that file has ever been written that way. So every owner ruling
    was invisible here and this whole path was dead: CLAUDE.md's claim that "where the camera
    has no coverage, a recorded owner ruling moves it instead (ep56 01:24)" was never true
    through this tool. It is the same defect CLAUDE.md already records against
    check_owner_decisions.py, which "silently voided every rule-7 ruling until 2026-09-13",
    repeated in the other consumer. Found because ep27's 05:25 refused to move after the
    owner ruled it by eye.

    The tag test needs a digit guard, or `ep2` would match section `ep27_rule7_...`. The
    `<tag>@<stamp>` form is still accepted so nothing that adopts it later breaks.
    """
    path = ROOT / "data" / "speaker_adjudications.json"
    if not path.exists():
        return {}
    out = {}
    for section, group in json.load(io.open(path, encoding="utf-8")).items():
        if not isinstance(group, dict):
            continue
        tagged = section.startswith(tag) and not section[len(tag):len(tag) + 1].isdigit()
        for key, entry in group.items():
            if not isinstance(entry, dict) or not entry.get("who"):
                continue
            if key.startswith(tag + "@"):
                out[key.split("@", 1)[1]] = entry["who"]
            elif tagged and key[:1].isdigit():
                out[key] = entry["who"]
    return out


def split_tail(said):
    """The block's last sentence end, and the words after it. ('' , '') when there is none."""
    ends = [m.end() for m in re.finditer(r"[.?!](?=\s|$)", said)]
    if not ends or ends[-1] >= len(said.rstrip()):
        return said, ""
    return said[:ends[-1]].rstrip(), said[ends[-1]:].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--reference", help="default data/camera_ref_<tag>.rttm")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--camera-veto", action="store_true",
                    help="leave a tail alone when the camera attests the current speaker; "
                         "off by default, because a camera cut is not a speaker change")
    a = ap.parse_args()

    raw_path = common.raw_for_tag(a.tag)
    path = Path(raw_path)
    text = path.read_text(encoding="utf-8")
    vid = re.search(r"video_id:\s*(\S+)", text).group(1)
    reference = Path(a.reference or ROOT / "data" / f"camera_ref_{common.artifact_tag(a.tag)}.rttm")
    if not reference.exists():
        sys.exit(f"no camera reference at {reference}")
    camera = camera_seconds(reference)
    words = mai_words(vid)
    if not words:
        sys.exit(f"no MAI word times in data/_mai_{vid}/ -- this tool needs them")

    gold = gold_window(vid)
    ruled = owner_rulings(a.tag)
    blocks = BLOCK.findall(text)
    moves, kept, long_tails, in_gold, blind = [], [], [], [], 0
    wholes, unattested = [], []
    for i in range(len(blocks) - 1):
        (st, who, said), (nxt, who_next, next_said) = blocks[i], blocks[i + 1]
        if who == who_next or not said or not next_said:
            continue
        if said.rstrip()[-1] in '.?!:"' or not next_said.split()[0][:1].islower():
            continue
        head, tail = split_tail(said)
        if not tail:
            # THE WHOLE BLOCK IS THE HANGING FRAGMENT: no sentence end anywhere in it, so
            # there is no tail to split off. Six of the owner's eleven 2026-09-13 rulings
            # are this shape (ep62 3:43:52, ep57 3:27:05, ep56 01:24, ep49 1:11:10 and
            # 1:16:31, ep47 40:41), and the old code skipped every one of them silently.
            #
            # HERE THE CAMERA DOES GET A VETO, unlike the partial-tail case above. Shape
            # alone cannot decide a whole block: rule 7 says a short block between two
            # different speakers may be a genuine interruption. What may decide it is the
            # `tail` signature check_overlap_boundaries.py measures -- the camera showing
            # the NEXT speaker through the block's own seconds -- and the owner confirmed
            # that signature 11 times out of 11.
            if len(said.split()) > MAX_TAIL_WORDS:
                continue
            if gold and gold[0] <= secs(st) <= gold[1]:
                in_gold.append((st, who, said))
                continue
            vote = Counter(camera.get(int(t)) for t in times_of(said, words, secs(st)))
            mine = vote.get(who.split(" (")[0], 0)
            theirs = vote.get(who_next.split(" (")[0], 0)
            if theirs >= MIN_ATTEST and theirs > mine:
                wholes.append((st, who, said, nxt, who_next, dict(vote)))
            elif ruled.get(st) == who_next or ruled.get(nxt) == who_next:
                # The camera cannot see this one, but the owner has. ep56's 01:24 is the
                # case: `camera no coverage`, and the owner ruled it Rafizi on 2026-09-13.
                # Rule 4 puts a person above every tool, so a recorded ruling moves it.
                wholes.append((st, who, said, nxt, who_next, "the owner's own ruling"))
            else:
                unattested.append((st, who, said, nxt, who_next, dict(vote)))
            continue
        if not head:
            continue
        if gold and gold[0] <= secs(st) <= gold[1]:
            in_gold.append((st, who, tail))
            continue
        if len(tail.split()) > MAX_TAIL_WORDS:
            long_tails.append((st, who, tail, nxt, who_next))
            continue
        when = times_of(tail, words, secs(st))
        vote = Counter(camera.get(int(t)) for t in when)
        mine, theirs = vote.get(who.split(" (")[0], 0), vote.get(who_next.split(" (")[0], 0)
        if a.camera_veto and mine > theirs:
            kept.append((st, who, tail, dict(vote)))
            continue
        blind += not any(k for k in vote if k)
        moves.append((i, st, who, head, tail, nxt, who_next, dict(vote)))

    for st, who, tail, vote in kept:
        print(f"  LEFT ALONE at [{st}]: the camera says {who} spoke {tail!r} -- {vote}")
    for _, st, who, head, tail, nxt, who_next, vote in moves:
        print(f"  move {tail!r}\n     out of [{st}] {who} (...{head[-40:]})"
              f"\n     into  [{nxt}] {who_next} -- camera {vote or 'no coverage'}")
    for st, who, tail in in_gold:
        print(f"  INSIDE THE GOLD PASSAGE, left alone at [{st}] {who}: {tail[:60]!r}")
    for st, who, tail, nxt, who_next in long_tails:
        print(f"  TOO LONG TO MOVE at [{st}] {who} -> [{nxt}] {who_next}, "
              f"{len(tail.split())} words, read it: {tail[:90]!r}")
    for st, who, said, nxt, who_next, vote in wholes:
        print(f"  move the WHOLE block {said!r}\n     out of [{st}] {who}"
              f"\n     into  [{nxt}] {who_next} -- attested by {vote}")
    for st, who, said, nxt, who_next, vote in unattested:
        print(f"  WHOLE-BLOCK SHAPE the camera does not attest, left alone at [{st}] {who} "
              f"-> {who_next}: {said[:60]!r} -- camera {vote or 'no coverage'}")
    print(f"{a.tag}: {len(moves)} hanging half-sentence(s) to move ({blind} of them where the "
          f"camera has no opinion either), {len(wholes)} whole block(s) the camera attests, "
          f"{len(unattested)} whole-block shape(s) it does not, {len(kept)} left by "
          f"--camera-veto, {len(long_tails)} too long to move, "
          f"{len(in_gold)} inside the gold passage")

    if not (moves or wholes) or not a.write:
        if moves or wholes:
            print("\n-- dry run, pass --write to apply")
        return

    out = text
    for st, who, said, nxt, who_next, _ in wholes:
        # One atomic replace: the block line, its blank separator and the next block's
        # header all become the next speaker's header carrying these words first. The
        # EARLIER stamp is kept, because that is when the words were actually spoken.
        old = f"[{st}] {who}: {said}\n\n[{nxt}] {who_next}: "
        if out.count(old) != 1:
            sys.exit(f"REFUSING: the block pair at [{st}] is not unique")
        out = out.replace(old, f"[{st}] {who_next}: {said} ")
    # Last move first. When two moves chain (block B receives A's tail AND gives its
    # own tail to C), applying A's move first rewrites B's header, so B's anchor is
    # gone by the time its own move runs. ep11 1:30:24 -> 1:30:31 -> 1:30:42 was that.
    for _, st, who, head, tail, nxt, who_next, _ in reversed(moves):
        old_a = f"[{st}] {who}: {head} {tail}"
        old_b = f"[{nxt}] {who_next}: "
        if out.count(old_a) != 1:
            sys.exit(f"REFUSING: {old_a[:60]!r} is not unique")
        when = times_of(tail, words, secs(st))
        stamp = fmt(when[0]) if when else nxt
        out = out.replace(old_a, f"[{st}] {who}: {head}")
        idx = out.index(old_b)
        out = out[:idx] + f"[{stamp}] {who_next}: {tail} " + out[idx + len(old_b):]

    strip = re.compile(r"^\[[\d:]+\]\s*[^:\n]{0,40}?:\s*", re.M)
    if strip.sub(" ", text).split() != strip.sub(" ", out).split():
        sys.exit("REFUSING TO WRITE: the word sequence changed")
    stamps = [secs(s) for s in re.findall(r"^\[([\d:]+)\]", out, re.M)]
    if any(b < a for a, b in zip(stamps, stamps[1:])):
        sys.exit("REFUSING TO WRITE: stamps would run backwards")
    path.write_text(out, encoding="utf-8")
    print(f"wrote {path} -- {len(moves)} tail(s) and {len(wholes)} whole block(s) moved, "
          f"every word still in order")


if __name__ == "__main__":
    main()
