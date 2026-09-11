"""Before a re-cut is written: does every recorded owner decision on this episode survive it?

WHY. The owner's speaker decisions live in tracked JSON under data/ (adjudications, regions
confirmed on video, `Speaker ?` namings, the gold passage). ep61 lost one such decision once
because a later pass never looked (ATTRIBUTION_PASS.md, "Read the episode's history first").
This makes the look mechanical: for every decision it finds the turn in the CURRENT raw.md by
its stamp, takes that turn's opening words, finds those words in the CANDIDATE file, and
requires the candidate's label to be the owner's. A decision it cannot locate is reported,
never silently passed.

A candidate built by a DIFFERENT ENGINE spells the same speech differently, so the substring
lookup alone is not enough: it left 37 of ep61's 44 decisions "not locatable" against the MAI
transcript. When it misses, lib_locate.Doc matches the passage on characters and prints where
it landed and how well it scored. A stamp only breaks a tie between two equally good matches,
never locates on its own -- ep61 has a block whose stamp is 26 s from its own words.

The gold passage is checked differently: the owner dictated it from ear, so its text is not
the candidate's text. It is compared WORD BY WORD WITH ITS LABELS rather than block by block,
because the decision the owner made is about who says which words. Merging same-speaker
blocks or dropping a grunt turn re-blocks the region without touching that mapping, and a
block-level comparison reads both as damage -- it did, on ep61, the day after the swap.

  python scripts/check_owner_decisions.py ep61 data/_nightly/ep61_preview_raw.md

This is a PRE-SWAP gate: the decisions are located through the raw.md they were recorded
against. Once the candidate has been written into episodes/, that file is gone, and the run
reports the decisions it can no longer find a snippet for -- ep61 went from 38 preserved to
26 preserved and 13 without text for that reason alone. To check after a swap, hand it the
committed file the decisions belong to:

  git show HEAD~1:episodes/.../raw.md > data/_old_raw.md
  python scripts/check_owner_decisions.py ep61 episodes/.../raw.md --current data/_old_raw.md
"""
import glob
import io
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib_locate import Doc, tokens  # noqa: E402
from strip_inline_fillers import INLINE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
BLOCK = re.compile(r"^\[([\d:]+)\]\s*([^:\n]{0,40}?):\s*(.*)$", re.M)
GOLD_PAD = 60
DECISION_FILES = ["speaker_adjudications.json", "speaker_video_confirmed.json",
                  "speaker_video_confirmed_ep61_round2.json", "speaker_q_video_confirmed.json",
                  "speaker_from_gold.json",
                  "speaker_owner_ear_2026_09_11.json"]


def secs(t):
    q = [int(x) for x in t.split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(q)))


def short(w):
    return w.split(" (")[0].strip()


def names_nobody(who):
    """A decision that deliberately names NO ONE, so there is nothing for the gate to check.

    Two shapes mean this. `null` is written where the evidence ran out and the record says
    so -- data/speaker_owner_ear_2026_09_11.json uses it for ep53 2:14:42, which the camera
    cannot see. `Speaker ?` is the repo's marker for the same thing, and 12 of ep53's
    filler turns carry it because the owner downgraded a bogus `Speaker 3` cluster without
    listening. Checking a candidate against either one asserts that an unknown must STAY
    unknown, which is wrong: they are explicitly reversible on better evidence, and the
    ep53 camera reference later named three of those twelve.
    """
    return who is None or who.strip().lower().rstrip("?").strip() in ("speaker", "")


def main():
    tag, candidate = sys.argv[1], sys.argv[2]
    current = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--current" else None
    hits = glob.glob(str(ROOT / f"episodes/*/*-{tag}-*/raw.md"))
    if len(hits) != 1:
        sys.exit(f"{len(hits)} episodes match {tag}")
    cur_text = io.open(current or hits[0], encoding="utf-8").read()
    cand_text = io.open(candidate, encoding="utf-8").read()
    vid = re.search(r"video_id:\s*(\S+)", cur_text).group(1)
    cur, cand = BLOCK.findall(cur_text), BLOCK.findall(cand_text)

    def current_block(stamp):
        return [(w, t) for st, w, t in cur if secs(st) == secs(stamp)]

    def candidate_labels(snippet):
        return sorted({short(w) for _, w, t in cand if snippet in t})

    checks = []   # (source, owner's label, snippet of the turn's text)
    for name in DECISION_FILES:
        path = ROOT / "data" / name
        if not path.exists():
            continue
        data = json.load(io.open(path, encoding="utf-8"))
        for section, rules in data.items():
            if section.startswith("_") or not isinstance(rules, dict):
                continue
            blob = json.dumps(rules, ensure_ascii=False)
            if tag not in section.lower() and vid not in blob:
                continue
            for stamp, r in rules.items():
                if not stamp[:1].isdigit() or not isinstance(r, dict):
                    continue
                src = f"{name}:{section}@{stamp}"
                for who, snip, at in r.get("split", []):
                    # A split's text is USUALLY a string, but ep53's 2:19:13 records it as
                    # ["Human resource", 1] -- the text plus which occurrence the owner
                    # meant. Slicing a list with [:45] silently returns a LIST, and the
                    # length test below then died with AttributeError, so the gate CRASHED
                    # instead of reaching a verdict. adopt_mai_camera_raw.py reads that
                    # non-zero exit as "the candidate does not keep a decision", which is
                    # how ep53 looked like a disagreement when it was a bug. One entry in
                    # the corpus is in this form, and it is the only episode with recorded
                    # decisions that this pass has reached, so it had never run clean.
                    # The index is dropped deliberately: lib_locate takes `near=stamp` and
                    # breaks a tie between equally good matches with it.
                    if isinstance(snip, (list, tuple)):
                        snip = snip[0] if snip else ""
                    if snip:
                        checks.append((src, who, snip[:45], secs(stamp)))
                if "who" in r:
                    # Locate by the rule's own text when it has one. A stamp is NOT unique
                    # in this corpus (a split re-uses its parent's stamp), so ep61's
                    # 1:22:10 names two blocks and the first one is not the owner's.
                    snip = r.get("text_now") or r.get("text_was_startswith") or r.get("text_was")
                    if not snip:
                        blk = current_block(r.get("at_now", stamp))
                        snip = blk[0][1] if blk else ""
                    checks.append((src, r["who"], snip[:45], secs(stamp)))

    doc = Doc(cand_text)
    ok = bad = missing = partial = 0
    for src, who, snip, at in checks:
        if names_nobody(who):
            continue
        want = short(who)
        if len(snip.split()) < 2:
            missing += 1
            print(f"  cannot locate ({src}): no usable text for the turn the owner named {who}")
            continue
        if candidate_labels(snip) == [want]:
            ok += 1
            continue
        # A decision recorded before strip_inline_fillers.py ran can carry a filler the
        # file no longer has -- ep62's 35:43 was recorded as "Um. Tan Sri". Match without it.
        found = doc.locate(INLINE.sub(" ", snip), near=at)
        if not found:
            exact = candidate_labels(snip)
            if exact:
                bad += 1
                print(f"  MISMATCH ({src}): owner says {who}, candidate has {exact} | {snip}")
            else:
                missing += 1
                print(f"  NOT FOUND in candidate ({src}): {who} | {snip}")
            continue
        labels = {}
        for label, n in found["labels"].items():
            labels[short(label)] = labels.get(short(label), 0) + n
        total = sum(labels.values())
        where = f"{found['stamp']} score {found['score']:.2f}"
        if found["ambiguous"]:
            where += ", two equally good matches, stamp picked this one"
        if list(labels) == [want]:
            ok += 1
        elif labels.get(want, 0) * 2 > total:
            partial += 1
            print(f"  PARTLY KEPT ({src}) at {where}: {who} holds {labels[want]} of {total} "
                  f"words, the rest is {dict((k, v) for k, v in labels.items() if k != want)}"
                  f" | {snip}")
        else:
            bad += 1
            print(f"  MISMATCH ({src}) at {where}: owner says {who}, "
                  f"candidate has {labels} | {snip}")

    def word_labels(blocks, lo, hi):
        out = []
        for st, who, text in blocks:
            if lo <= secs(st) <= hi:
                out += [(w, short(who)) for w in tokens(text)]
        return out

    # The gold passage: the owner's words keep the owner's speakers, word by word.
    truth = json.load(io.open(ROOT / "data" / "speaker_ground_truth.json", encoding="utf-8"))
    gold_ok = None
    for key, g in truth.items():
        if not isinstance(g, dict) or g.get("video_id") != vid:
            continue
        m = re.findall(r"(\d{1,2}:\d{2}(?::\d{2})?)", g.get("region", ""))
        if len(m) >= 2:
            lo, hi = secs(m[0]), secs(m[1])
            want = word_labels(cur, lo - GOLD_PAD, hi)
            got = word_labels(cand, lo - 2 * GOLD_PAD, hi + 2 * GOLD_PAD)
            hit = None
            for i in range(len(got) - len(want) + 1):
                if [w for w, _ in got[i:i + len(want)]] == [w for w, _ in want]:
                    hit = got[i:i + len(want)]
                    break
            wrong = [] if hit is None else [(a, b) for a, b in zip(want, hit) if a[1] != b[1]]
            gold_ok = hit is not None and not wrong
            if hit is None:
                print(f"  gold passage {g['region']!r}: its {len(want)} words are NOT in the "
                      "candidate in that order")
            else:
                print(f"  gold passage {g['region']!r}: {len(want)} words found in order, "
                      f"{len(wrong)} under a different speaker")
                for (w, a), (_, b) in wrong[:5]:
                    print(f"    {w!r}: owner says {a}, candidate says {b}")

    print(f"\n{tag}: {len(checks)} owner decisions -- {ok} preserved, {partial} partly kept, {bad} mismatched, "
          f"{missing} not locatable" + ("" if gold_ok is None else f"; gold passage {'kept' if gold_ok else 'CHANGED'}"))
    sys.exit(1 if bad or gold_ok is False else 0)


if __name__ == "__main__":
    main()
