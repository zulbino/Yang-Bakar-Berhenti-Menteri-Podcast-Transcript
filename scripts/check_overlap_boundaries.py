"""Find the shape CLAUDE.md rule 7 names: one sentence torn across two speakers.

THE SHAPE. Block A ends without terminal punctuation and the NEXT block, under a
different name, opens in lower case -- one sentence carried across two speakers:

    [05:48] Rafizi: ...dia macam kalau
    [05:51] Speaker 2: macam dalam kementerian ini dia ada 2 contoh

Two people talked over each other, and the mixer or the diarizer briefly attended to
whoever was about to speak next, so a few words at the boundary landed on the wrong side
of the cut.

THE UNIT IS A PAIR, not the A/B/A sandwich rule 7's prose describes, and that is a
measurement rather than a preference: across the 22 adopted episodes the sandwich occurs
ONCE (ep48 at 1:17:30) while the pair occurs 66 times. MAI punctuates the end of a phrase,
so after `merge_same_speaker.py` runs the first speaker rarely resumes in a third block --
the torn sentence ends at the handover. A sandwich is still reported, as stronger
evidence, on the candidate's own line.

WHAT THIS IS NOT. It does not relabel anything. `fold_hanging_fragments.py` already
handles the decidable half of this shape -- where the camera covers NONE of B's seconds,
it gives B's words to the speaker on both sides. The half left over is the one rule 7 is
about: the camera DOES have an opinion, and the opinion is contested. Rule 7's own
instruction for that case is explicit: "if the margin is not decisive, do not guess --
mark it and escalate", which is rule 8's escalation with a clickable link. So this reports.

HOW THE CAMERA IS READ. Per-second, from the tracked RTTM reference, across B's window.
Three verdicts:

  attested   The camera gives B's own label at least ATTESTED_SHARE of the covered
             seconds and never gives A's. A real interjection, of the kind ep61 had nine
             of: Haziq genuinely finishes Rafizi's sentences for 2 to 11 seconds at a
             time. Left alone, and counted so the number is visible.
  contested  The camera's covered seconds disagree with B's label, or split between B and
             A. This is the rule 7 residue. Escalated with a link.
  blind      No covered second. `fold_hanging_fragments.py`'s case, not this one's.

TWO LIMITS, both of which decide how far the output can be trusted:

  1. `check_camera_reference.py` is CIRCULAR on an adopted raw -- the raw was built FROM
     the camera, so comparing them cannot detect a reference blind to a real speaker.
     This tool therefore does not gate on it; it prints the per-speaker share of camera
     seconds instead, and a speaker at 0.0% there means the verdicts below are worthless
     for that person's turns.
  2. The window comes from B's own block stamp. On an ADOPTED raw those stamps are MAI's
     word alignment and are sound; on a local-ASR raw they drift by more than the turn's
     own length (159 of ep61's 203 blocks were over 10 s out), so the tool refuses any
     episode whose raw.md is not the adopted MAI build.

  python scripts/check_overlap_boundaries.py ep63
  python scripts/check_overlap_boundaries.py --all
  python scripts/check_overlap_boundaries.py ep63 --links     # caption cues too
"""
import argparse
import io
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
import listen_links  # noqa: E402
from fold_hanging_fragments import BLOCK, camera_seconds, secs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAX_WORDS = 10
# At or above this share of B's covered seconds, the camera is taken to attest B. Set from
# ep61's audited fragments: the nine the camera attested there hold their label for the
# whole fragment, so anything meaningfully below 1.0 is a contested boundary, not a quiet
# interjection.
ATTESTED_SHARE = 0.75
LEAD_IN = 6


def cast_share(camera):
    total = len(camera) or 1
    return Counter(camera.values()), total


def candidates(blocks, camera):
    out = []
    for i in range(1, len(blocks)):
        (st, who, said), (_, before, prev_said) = blocks[i], blocks[i - 1]
        nxt = blocks[i + 1][0] if i + 1 < len(blocks) else None
        if who == before or not said or not prev_said:
            continue
        # Both halves are required. A lower-case opening after a full stop is an ASR
        # capitalisation slip, and an unfinished A followed by a capitalised B is an
        # ordinary handover -- only the two together read as one torn sentence.
        if prev_said.rstrip()[-1] in '.?!:"' or not said.split()[0][:1].islower():
            continue
        end = secs(nxt) if nxt else secs(st) + 5
        vote = Counter(camera[t] for t in range(secs(st), max(secs(st) + 1, end))
                       if t in camera)
        covered = sum(vote.values())
        # The boundary itself, not the whole turn: the contested words are the first ones.
        edge = Counter(camera[t] for t in range(secs(st), secs(st) + 3) if t in camera)
        sandwich = (i + 1 < len(blocks) and blocks[i + 1][1] == before
                    and blocks[i + 1][2][:1].islower())
        # THE VERDICT IS DECIDED AT THE EDGE, not over the whole turn, and that is the
        # whole point of rule 7: a long turn can be correctly labelled B and still open
        # with a few words that are A's. ep44's 1:21:26 reads `Rafizi 842s, Haziq 4s` over
        # its window -- overwhelmingly B -- while its first three seconds read
        # `Haziq 2s, Rafizi 1s`. Judging by the window calls that clean; judging by the
        # edge calls it contested, which is what it is.
        if not edge and not covered:
            verdict = "blind"
        elif not edge:
            verdict = "contested" if vote.get(before, 0) else "attested"
        elif edge.get(who, 0) / sum(edge.values()) >= ATTESTED_SHARE:
            verdict = "attested"
        else:
            verdict = "contested"
        out.append((verdict, st, nxt or st, who, before, said, vote, edge, sandwich))
    return out


def report(tag, links=False):
    raw = common.raw_for_tag(tag)
    text = Path(raw).read_text(encoding="utf-8")
    if not re.search(r"^model:\s*microsoft/MAI-Transcribe", text, re.M):
        print(f"{tag}: SKIPPED -- raw.md is not the adopted MAI build, so its block stamps "
              f"cannot locate a boundary second (see this file's limit 2)")
        return None
    ref = ROOT / "data" / f"camera_ref_{tag}.rttm"
    if not ref.exists():
        print(f"{tag}: SKIPPED -- no camera reference at {ref.relative_to(ROOT)}")
        return None
    camera = camera_seconds(ref)
    shares, total = cast_share(camera)
    blocks = BLOCK.findall(text)
    found = candidates(blocks, camera)
    counts = Counter(v for v, *_ in found)
    print(f"\n=== {tag}: {len(blocks)} blocks, camera covers {total}s "
          f"({', '.join(f'{n} {100 * c / total:.0f}%' for n, c in shares.most_common())})")
    print(f"    {counts.get('contested', 0)} contested, {counts.get('attested', 0)} "
          f"attested by the camera, {counts.get('blind', 0)} camera-blind "
          f"(fold_hanging_fragments.py's case)")
    if counts.get("contested"):
        vid = listen_links.video_id(Path(raw))
        cues = listen_links.captions(vid) if links else None
        for verdict, st, nxt, who, before, said, vote, edge, sandwich in found:
            if verdict != "contested":
                continue
            seen = ", ".join(f"{k or 'no opinion'} {n}s" for k, n in vote.most_common())
            at_edge = ", ".join(f"{k or 'no opinion'} {n}s" for k, n in edge.most_common())
            print(f"\n  [{st}] {who}: {said[:110]}")
            print(f"       the sentence starts in {before}'s block"
                  + (f", and {before} resumes after it (SANDWICH)" if sandwich else ""))
            print(f"       camera {secs(st)}-{secs(nxt)}s: {seen or 'nothing'}"
                  f"  |  first 3s: {at_edge or 'nothing'}")
            print(f"       https://youtu.be/{vid}?t={max(0, secs(st) - LEAD_IN)}")
            if cues:
                for s, c in cues:
                    if secs(st) - 8 <= s <= secs(nxt) + 4:
                        print(f"         {s:8.1f}  {c[:88]}")
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="*")
    ap.add_argument("--all", action="store_true", help="every episode with a camera reference")
    ap.add_argument("--links", action="store_true", help="print caption cues per candidate")
    a = ap.parse_args()

    tags = list(a.tags)
    if a.all:
        tags += sorted({p.stem.replace("camera_ref_", "")
                        for p in (ROOT / "data").glob("camera_ref_ep*.rttm")},
                       key=lambda t: -int(re.sub(r"\D", "", t) or 0))
    if not tags:
        ap.error("give an episode tag, or --all")

    totals = Counter()
    for tag in dict.fromkeys(tags):
        counts = report(tag, links=a.links)
        if counts:
            totals.update(counts)
    print(f"\n{totals.get('contested', 0)} contested boundary/boundaries across "
          f"{len(tags)} episode(s) -- rule 7's residue, for an ear, not a tool. "
          f"{totals.get('attested', 0)} attested, {totals.get('blind', 0)} camera-blind.")


if __name__ == "__main__":
    main()
