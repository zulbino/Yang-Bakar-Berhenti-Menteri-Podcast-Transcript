"""Keep an owner-dictated WORD correction from being silently reverted by a rebuild.

WHY THIS EXISTS, and why it is the second time. `check_owner_decisions.py` guards a
SPEAKER LABEL. `forced_labels.json` re-applies one over the camera. Neither touches the
TEXT, and the owner sometimes corrects the words rather than the name: they listen, and
they dictate what was actually said.

ep34 2:04:29 is the case. The owner corrected raw's `0.017` to `0.0179` by ear on
2026-09-11, in the sequence Rafizi "ha cuba bagi" / Haziq "0.0179" / Rafizi "maksudnya
lebih kurang 18 juta, 17.9". The next turn's `17.9` is consistent with 0.0179 and not with
0.017, so the ear was right. MAI hears `0.017`. Adoption rebuilds raw.md from MAI's words,
so it overwrote the correction on 2026-09-14. That was caught by hand, restored by a
one-off guard, and the commit named the durable fix as "next". It was not done, so the
2026-09-16 re-adoption reverted the SAME digit again.

The gate cannot see these either: `lib_locate` needs three tokens and `0.0179` is one, so
`check_owner_decisions.py` reports "no usable text for the turn" rather than a mismatch.
Unverifiable means silently revertible.

WHAT IT READS. Every record in data/speaker_*.json that carries BOTH `text_was` and
`text_now`. That pair means the owner changed the words. A record with `text_now` alone is
a label ruling and belongs to the other gate, not here.

THREE STATES, and only one of them is actionable:

  APPLIED   raw.md already holds `text_now`. Nothing to do.
  REVERTED  raw.md holds `text_was` and not `text_now`. A rebuild undid the owner. --write
            restores it, refusing unless `text_was` appears exactly once.
  CLEARED   neither string is in raw.md, so the owner's wording is gone and nothing was
            reverted. Reported, not escalated. To have such a correction checked from now
            on, give the record `anchor_was` and `anchor_now`, written against the words
            raw.md holds today. ep61 14:52 needed exactly that: the dictated sentence
            matched nothing while `kitchen` had been reverted to `keychain` in five places.

`text_was` being a PREFIX of `text_now` is why APPLIED is tested first. ep61 02:53 corrects
`Nebulizer tu memang hydrogen` to `Nebulizer tu memang hydrogen ke?`, so the old string is
still present inside the new one, and testing REVERTED first calls a satisfied record
broken.

  python scripts/check_owner_text.py              # every episode, report only
  python scripts/check_owner_text.py ep34          # one episode
  python scripts/check_owner_text.py ep34 --write  # restore what a rebuild reverted
"""
import argparse
import glob
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIGURE = re.compile(r"\d[\d.,]*\d|\d")


def records():
    """Every owner-dictated text correction, as (tag, source, section, stamp, was, now)."""
    out = []
    for path in sorted(glob.glob(str(ROOT / "data" / "speaker_*.json"))):
        blob = json.loads(io.open(path, encoding="utf-8").read())
        for section, body in blob.items():
            if not isinstance(body, dict):
                continue
            # An era-suffixed tag (`ep02:berhenti`) needs the suffix too, or the bare
            # `ep02` this used to capture is ambiguous between eras and every record for
            # a colon-tagged episode silently never matches (found on ep02:berhenti's
            # 02:28 correction, 2026-09-18).
            tag = re.match(r"(ep\d+(?::[a-z]+)?)", section)
            if not tag:
                continue
            for stamp, rec in body.items():
                if isinstance(rec, dict) and "text_was" in rec and "text_now" in rec:
                    out.append((tag.group(1), Path(path).name, section, stamp) + anchors(rec))
    return out


def state_of(text, was, now):
    # APPLIED first: `was` can be a prefix of `now` (ep61 02:53), so a `was` hit does not
    # mean the correction is missing.
    if now in text:
        return "APPLIED"
    if was in text:
        return "REVERTED"
    # Neither string is present. The owner's wording is GONE from the file, so nothing was
    # reverted -- the rebuild simply spells the passage differently. This is reported, not
    # escalated. It was called STALE and sent to an ear at first, which over-reported: ep19
    # and ep31 both read that way while the owner's change was in fact in effect.
    return "CLEARED"


def anchors(rec):
    """The strings to test with, which are the owner's words unless a re-anchor exists.

    WHY A RE-ANCHOR. The owner dictates a whole sentence, and a later MAI rebuild respells
    the words around the one they were correcting. ep61 14:52 is the case: they dictated
    `Walau tak, Mummy button badge kitchen...` and MAI now writes `Walau not mummy button
    badge kitchen...`, so the full sentence matched nothing while the actual correction,
    `kitchen` to `keychain`, had been reverted in FIVE places and went unreported.

    `anchor_was` and `anchor_now` hold the same correction written against the current
    words. The owner's own `text_was` and `text_now` are never edited -- they are the
    record of what they said.
    """
    return (rec.get("anchor_was", rec["text_was"]),
            rec.get("anchor_now", rec["text_now"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", nargs="?", help="one episode; default every episode with a record")
    ap.add_argument("--write", action="store_true", help="restore every REVERTED correction")
    a = ap.parse_args()

    rows = [r for r in records() if not a.tag or r[0] == a.tag]
    if not rows:
        print(f"no owner-dictated text correction recorded{' for ' + a.tag if a.tag else ''}")
        return 0

    counts = {"APPLIED": 0, "REVERTED": 0, "CLEARED": 0}
    for tag, source, section, stamp, was, now in rows:
        try:
            path = Path(common.raw_for_tag(tag))
        except Exception as exc:
            print(f"  {tag} {stamp}: cannot read raw.md -- {exc}")
            continue
        text = path.read_text(encoding="utf-8")
        state = state_of(text, was, now)
        counts[state] += 1
        where = f"{source}:{section}@{stamp}"
        print(f"  {state:8s} {tag} {stamp:9s} {where}")
        if state != "APPLIED":
            print(f"           was {was[:70]!r}")
            print(f"           now {now[:70]!r}")
        if state != "REVERTED" or not a.write:
            continue
        hits = text.count(was)
        if hits != 1:
            print(f"           REFUSING to write: {was[:40]!r} appears {hits} times, so the "
                  f"correction cannot be placed without guessing")
            continue
        fixed = text.replace(was, now, 1)
        # The only change permitted is this one span. Everything else, including every other
        # figure in the file, has to read the same afterwards.
        if fixed.replace(now, was, 1) != text:
            print("           REFUSING to write: the replacement would change more than "
                  "the recorded span")
            continue
        before, after = FIGURE.findall(text), FIGURE.findall(fixed)
        changed = [(x, y) for x, y in zip(before, after) if x != y]
        if len(before) != len(after) or len(changed) > 1:
            print(f"           REFUSING to write: {len(changed)} figure(s) would change and "
                  f"the count went {len(before)} -> {len(after)}; exactly one is allowed")
            continue
        path.write_text(fixed, encoding="utf-8")
        note = f", figure {changed[0][0]} -> {changed[0][1]}" if changed else ""
        print(f"           RESTORED in {path.name}{note}")
        counts["REVERTED"] -= 1
        counts["APPLIED"] += 1

    print(f"{len(rows)} owner-dictated text correction(s): {counts['APPLIED']} applied, "
          f"{counts['REVERTED']} reverted by a rebuild, {counts['CLEARED']} cleared "
          f"(the owner's wording is gone, so nothing was reverted)")
    if counts["CLEARED"]:
        print("   CLEARED is not a defect. If one of them is a correction you want checked "
              "from now on, add `anchor_was` and `anchor_now` to that record, written "
              "against the words raw.md holds today.")
    return 1 if counts["REVERTED"] else 0


if __name__ == "__main__":
    sys.exit(main())
