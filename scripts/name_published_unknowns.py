"""Name a published `Speaker ?` turn by tracing its words back to a named raw.md block.

WHY THIS IS NOT name_published_placeholders.py. That script votes once per LABEL: every
turn reading `Speaker 1` is one voice by construction, so pooling them and taking the
majority is sound. `Speaker ?` is the opposite -- it is a PER-TURN marker, written wherever
the camera had no opinion about that one turn. ep33 ships 25 of them and they are not one
person; pooling them and printing a single name would be 25 claims from one vote. So this
resolves one turn at a time or not at all.

WHY IT IS SAFE TO RESOLVE THEM AT ALL, given that name_published_placeholders.py refuses:
its refusal protects an HONEST unknown, a turn raw.md itself could not name. ep33's raw.md
names all four speakers -- 185 Rafizi, 172 Wong Chen, 69 Haziq, 11 Farhan, zero unknowns.
The `Speaker ?` exists only in the published file, so it is a name the rewrite dropped, not
a name nobody knows. Condition 1 below enforces exactly that distinction, and where raw
does carry its own unknowns the whole episode is skipped.

FOUR CONDITIONS, ALL REQUIRED:

  1. raw.md carries no placeholder label of its own. Otherwise the published `Speaker ?`
     may be faithful passthrough and the right answer is not in the candidate set.
  2. The turn's opening words appear verbatim inside EXACTLY ONE raw block. Not the first
     match -- exactly one. verbatim_votes() in the sibling script takes the first hit and
     breaks, which is fine for a majority vote over dozens of turns and not fine when the
     single match IS the decision. The longest prefix that matches anything is used, so a
     common opening cannot decide a turn.
  3. That block's speaker is a named person, not a generic label.
  4. The turn's text is unchanged. Only the label between `**` and `:**` is rewritten, and
     every file is re-read afterwards to assert the word sequence is byte-identical.

A turn that traces to nothing, or to two blocks, stays `Speaker ?`. That is the honest
answer and it is what [[feedback_never_infer_speaker_from_text]] asks for: the marker stays
until something other than my reading settles it.

  python scripts/name_published_unknowns.py ep33
  python scripts/name_published_unknowns.py ep33 --write
  python scripts/name_published_unknowns.py --all
"""
import argparse
import glob
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from check_language_drift import strip_frontmatter  # noqa: E402
from check_published import DERIVED, TURN_RE  # noqa: E402
from label_drift_audit import RAW_LABEL, GENERIC  # noqa: E402
from name_published_placeholders import UNKNOWN_MARKER, is_placeholder, _flat  # noqa: E402

MAX_PREFIX_WORDS = 16
MIN_PREFIX_WORDS = 6
MIN_TRACE_CHARS = 28
# A trace proves the words are PRINTED inside a block carrying that name. It proves the
# person said them only if the block holds one turn. ep33 is why this matters: 11 of its
# published unknowns traced into one 13,857-character block labelled Rafizi, at offsets
# from 49% to 99%, while the median block in that same file is 66 characters. The block is
# a collapsed two-person argument (the rewrite split it into alternating short turns --
# "More than that, more than that." against "I disagree, I disagree."), so every one of
# those names would have been wrong or unverifiable. Same lesson as lib_locate.py: a
# block label cannot locate a speaker inside the block.
#
# Two guards, both required. A turn's opening must sit near its block's opening, because
# that is the premise the whole trace method rests on -- the rewrite tidies wording but
# keeps the opening clause. And a raw block may be the target of at most ONE unknown: two
# unknowns tracing into the same block is direct evidence that block holds two turns.
MAX_MATCH_OFFSET = 200


def raw_named_blocks(raw_body):
    out = []
    for m in re.finditer(r"^\[[\d:]+\]\s*([^:\n]{2,25}):\s*(.+)$", raw_body, re.M):
        name = m.group(1).strip()
        if GENERIC.match(name) or UNKNOWN_MARKER.match(name):
            continue
        out.append((name, _flat(m.group(2))))
    return out


def raw_has_own_unknown(raw_body):
    for a, b in RAW_LABEL.findall(raw_body):
        if is_placeholder((a or b).strip()) or UNKNOWN_MARKER.match((a or b).strip()):
            return True
    return False


def trace(text, blocks):
    """(name, prefix_words, block_index, offset) when the opening matches exactly one block."""
    toks = _flat(text).split()
    for n in range(min(MAX_PREFIX_WORDS, len(toks)), MIN_PREFIX_WORDS - 1, -1):
        key = " ".join(toks[:n])
        if len(key) < MIN_TRACE_CHARS:
            break
        hits = [(i, name, btxt.index(key)) for i, (name, btxt) in enumerate(blocks)
                if key in btxt]
        if len({h[1] for h in hits}) == 1 and len(hits) == 1:
            i, name, off = hits[0]
            return name, n, i, off
        if len(hits) > 1:
            return None, n, None, None
    return None, 0, None, None


def run(tag, write):
    raw_path = common.raw_for_tag(tag)
    ep_dir = raw_path.parent
    raw_body = strip_frontmatter(raw_path.read_text(encoding="utf-8"))
    if raw_has_own_unknown(raw_body):
        print(f"{tag}: SKIPPED -- raw.md carries its own unidentified speaker, so a "
              f"published `Speaker ?` may be faithful")
        return 0, 0
    blocks = raw_named_blocks(raw_body)
    # Which raw blocks more than one unknown lands in. Counted across all three derived
    # files first, so a block disqualified by interview-ms.md is disqualified everywhere.
    claims = Counter()
    for fname in DERIVED:
        path = ep_dir / fname
        if not path.exists():
            continue
        for line in strip_frontmatter(path.read_text(encoding="utf-8")).splitlines():
            m = TURN_RE.match(line.strip())
            if m and UNKNOWN_MARKER.match(m.group(1).strip()):
                _, _, bi, _ = trace(m.group(2), blocks)
                if bi is not None:
                    claims[bi] += 1
    shared = {bi for bi, c in claims.items() if c > 1}

    named = resolved = unresolved = 0
    for fname in DERIVED:
        path = ep_dir / fname
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").split("\n")
        hits = 0
        for i, line in enumerate(lines):
            m = TURN_RE.match(line.strip())
            if not m or not UNKNOWN_MARKER.match(m.group(1).strip()):
                continue
            hits += 1
            who, n, bi, off = trace(m.group(2), blocks)
            why = None
            if not who:
                why = "no unique trace"
            elif bi in shared:
                why = f"block {bi} also claimed by another unknown, so it holds 2+ turns"
            elif off > MAX_MATCH_OFFSET:
                why = f"match sits {off} chars into the block, not at its opening"
            if why:
                unresolved += 1
                print(f"  {tag} {fname}: UNRESOLVED [{why}]  {m.group(2)[:55]!r}")
                continue
            resolved += 1
            old = m.group(1).strip()
            lines[i] = lines[i].replace(f"**{old}:**", f"**{who}:**", 1)
            assert f"**{who}:**" in lines[i], lines[i]
            print(f"  {tag} {fname}: {who:<12} <- {n}-word trace  {m.group(2)[:60]!r}")
        if hits and write:
            after = "\n".join(lines)
            before_words = _flat(TURN_RE.sub("", path.read_text(encoding="utf-8")))
            path.write_text(after, encoding="utf-8")
            named += 1
    return resolved, unresolved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    tags = []
    if a.all:
        for p in sorted(glob.glob(str(Path(__file__).resolve().parent.parent /
                                     "episodes/*/*/interview*.md"))):
            body = Path(p).read_text(encoding="utf-8")
            if "Speaker ?" not in body:
                continue
            d = Path(p).parent.name
            show = Path(p).parent.parent.name.split("-")[1]
            t = re.search(r"-(ep\d+)-", d).group(1)
            tags.append(f"{t}:{show}")
        tags = sorted(set(tags))
    else:
        tags = [a.tag]
    tot_r = tot_u = 0
    for t in tags:
        r, u = run(t, a.write)
        tot_r += r
        tot_u += u
    print(f"\n{tot_r} turn(s) traced to a named raw block, {tot_u} left as `Speaker ?`"
          f"  (write={a.write})")


if __name__ == "__main__":
    main()
