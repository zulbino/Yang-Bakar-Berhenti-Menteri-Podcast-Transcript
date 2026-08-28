"""Name the `Speaker N` labels left in the PUBLISHED files, using raw.md as the key.

Nine episodes ship a diarizer cluster id straight to the reader -- ep54 prints all 97 of
its turns as `Speaker 1`/`Speaker 2` while its own frontmatter names both hosts, and ep56
does it 121 times next to a `Speaker 1 (Rafizi Ramli)` that gives the name away. The names
were never missing. They are in `raw.md`, and the rewrite dropped them.

The rewrite edits wording but does not invent content, so a published turn and the raw
block it came from share their rare words -- proper nouns, numbers, unusual verbs. Common
words are useless here because every turn has them, so each word is weighted by how few
blocks contain it, and a turn is matched to the raw block it shares the most weight with.

WHAT THIS REFUSES TO DO is the point. A wrong name is worse than a placeholder: a
placeholder tells the reader nobody knows, a wrong name tells them something false in a
named politician's mouth. So a placeholder is only renamed when its turns agree, and the
script prints the agreement it found so the decision is visible rather than implied.

Default is a dry run. Pass --apply to write.
"""
import argparse
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_language_drift import strip_frontmatter
from check_published import DERIVED, TURN_RE, DERIVED_PLACEHOLDER_RE
from label_drift_audit import RAW_LABEL, GENERIC, norm

ROOT = Path(__file__).resolve().parent.parent
WORD = re.compile(r"[A-Za-zÀ-ÿ][\w'’-]{2,}")
# A word in more than this share of blocks carries no signal -- "yang", "the", "kita"
# appear everywhere. Weighting by inverse block frequency handles this smoothly, but
# dropping the worst offenders outright keeps a long common-word turn from outscoring a
# short turn that shares an actual proper noun.
MAX_DOC_RATIO = 0.30
# A turn matched below this weight is treated as unmatched rather than forced onto its
# best guess. Short interjections ("Betul.", "Ya lah") legitimately score near zero.
MIN_SCORE = 0.15
# Share of a placeholder's MATCHED turns that must agree on one name before it is renamed.
# Set high on purpose: these labels are wrong in a way the reader cannot detect, so the
# bar to overwrite them is agreement, not plurality.
MIN_AGREEMENT = 0.80
# The weaker bar used only once a name is the last one standing (see the elimination pass).
# Below this the vote is a coin flip -- ep51 splits 50/50 between Haziq and Rafizi and ep37
# splits 52/48, and both stay placeholders.
MIN_PLURALITY = 0.60
# A placeholder with fewer matched turns than this is left alone; the agreement figure
# would not mean anything.
MIN_MATCHED = 3
# A turn's opening must be this long before a literal trace means anything; below it,
# "ya betul lah kan" matches half the episode.
MIN_TRACE_CHARS = 28
# Literal traces needed before they OVERRIDE the bag-of-words vote, and the share of them
# that must agree. ep56's Speaker 2 fails here at 65% over 43 traces and stays a
# placeholder, which is the right answer: its turns splice two raw speakers together.
MIN_TRACES = 3
MIN_TRACE_AGREEMENT = 0.80
# Roles need more traces than numbered ids, because a role label can legitimately cover two
# people across an episode ("Host" for whoever is asking) whereas a cluster id is one voice
# by construction. Five is where the surviving role labels are unanimous rather than merely
# ahead.
MIN_TRACES_ROLE = 5


# Numbered cluster ids AND role labels, but they are held to different evidence.
#
# Roles were out of scope for one run, and the reason is worth keeping. Scored by word
# overlap the script proposed `Interviewer` -> Rafizi in two episodes, and Rafizi is the
# interviewEE: the score was measuring shared TOPIC, and he speaks most and at greatest
# length, so his blocks win any overlap comparison by volume. Dividing by sqrt(block
# length) fixes the direction, but role agreement then sits at 55-76% -- ambiguous, not
# merely mis-scored. So a role is renamed ONLY on literal traces, never on the overlap
# vote, and needs more of them (see _confirm). Three clear it: YBkM-ep03's `Host` traces
# 9/9 to Syed Munawar, YBhM-ep37's 6/6 to Haziq, YBhM-ep34's `Speaker` 7/7 to Rafizi.
#
# `Speaker ?` is excluded outright: it is the repo's marker for a turn nobody could
# identify, and trading an honest unknown for a guess is what this refuses to do.
UNKNOWN_MARKER = re.compile(r"^(speaker|penutur|penceramah)\s*\?+$", re.I)


def is_numbered(label):
    return bool(DERIVED_PLACEHOLDER_RE.match(label.strip()))


def is_placeholder(label):
    if UNKNOWN_MARKER.match(label.strip()):
        return False
    return bool(is_numbered(label) or GENERIC.match(label))


def words(text):
    return {w.lower() for w in WORD.findall(text)}


def raw_blocks(raw_body):
    """[(speaker, wordset)] for every named block in raw.md."""
    out = []
    lines = raw_body.splitlines()
    for i, line in enumerate(lines):
        m = RAW_LABEL.match(line)
        if not m:
            continue
        name = (m.group(1) or m.group(2)).strip()
        if GENERIC.match(name):
            continue
        out.append((name, words(line[m.end():])))
    return out


def weights(blocks):
    df = Counter()
    for _, ws in blocks:
        df.update(ws)
    n = len(blocks) or 1
    return {w: math.log(n / c) for w, c in df.items() if c / n <= MAX_DOC_RATIO}


def best_match(turn_words, blocks, w):
    """Nearest raw block by shared rare words, divided by the block's length.

    The division is not cosmetic. Without it the score measures shared TOPIC and the
    speaker with the longest blocks wins every comparison -- on this corpus that is always
    Rafizi, who is the interviewee, so an `Interviewer` label resolved to him. Normalising
    by sqrt(block length) flips those cases to the right people and, on ep56, moves
    `Speaker 2` off Rafizi and onto Haziq, which a verbatim trace independently confirms.
    """
    best, score = None, 0.0
    for name, ws in blocks:
        if not ws:
            continue
        s = sum(w.get(x, 0.0) for x in turn_words & ws) / math.sqrt(len(ws))
        if s > score:
            best, score = name, s
    return (best, score) if score >= MIN_SCORE else (None, score)


def _flat(s):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


def verbatim_votes(ep_dir, raw_body):
    """Who raw.md says spoke each placeholder turn, by literal substring match.

    Stronger evidence than the bag-of-words score and independent of it: the rewrite
    tidies wording but usually leaves the opening clause intact, so a turn's first seven
    words can often be found verbatim inside exactly one raw block. Where the two methods
    disagree, this one is right -- it decided ep56, where the overlap score said Rafizi at
    64% and the literal traces said Haziq at 65%, and the turns themselves turned out to
    splice two speakers together.
    """
    blocks = [(m.group(1).strip(), _flat(m.group(2))) for m in
              re.finditer(r"^\[[\d:]+\]\s*([^:\n]{2,25}):\s*(.+)$", raw_body, re.M)]
    votes = defaultdict(Counter)
    for name in DERIVED:
        path = ep_dir / name
        if not path.exists():
            continue
        for line in strip_frontmatter(path.read_text(encoding="utf-8")).splitlines():
            m = TURN_RE.match(line.strip())
            if not m or not is_placeholder(m.group(1).strip()):
                continue
            key = " ".join(_flat(m.group(2)).split()[:7])
            if len(key) < MIN_TRACE_CHARS:
                continue
            for spk, btxt in blocks:
                if key in btxt:
                    votes[m.group(1).strip()][spk] += 1
                    break
    return votes


def _confirm(label, who, traces):
    """Does the literal-trace evidence back this name? Returns (ok, note).

    A ROLE label must be carried by traces alone. The bag-of-words score is allowed to
    propose a name for a numbered cluster id and be confirmed, but for `Host` and
    `Interviewer` it is measurably unreliable -- corrected for block length it still only
    reaches 55-76% agreement, and before that correction it was answering `Rafizi` for
    labels belonging to whoever was interviewing him. So roles get no bag-of-words fallback
    and need more traces. Three of them clear that bar outright: YBkM-ep03's `Host` traces
    9/9 to Syed Munawar, YBhM-ep37's 6/6 to Haziq, YBhM-ep34's `Speaker` 7/7 to Rafizi.
    """
    tally = traces.get(label)
    total = sum(tally.values()) if tally else 0
    floor = MIN_TRACES if is_numbered(label) else MIN_TRACES_ROLE
    if total < floor:
        if is_numbered(label):
            return True, "[no literal traces; bag-of-words only]"
        return False, f"[role label, only {total} literal trace(s); needs {floor}]"
    n = tally.get(who, 0)
    share = n / total
    return share >= MIN_TRACE_AGREEMENT, f"[traces {n}/{total} = {share:.0%} {who}]"


def propose(ep_dir):
    """{placeholder: (name, agreement, matched)} plus the per-file evidence."""
    raw_body = strip_frontmatter((ep_dir / "raw.md").read_text(encoding="utf-8"))
    blocks = raw_blocks(raw_body)
    if not blocks:
        return {}, {}
    w = weights(blocks)
    traces = verbatim_votes(ep_dir, raw_body)

    votes = defaultdict(Counter)
    for name in DERIVED:
        path = ep_dir / name
        if not path.exists():
            continue
        for line in strip_frontmatter(path.read_text(encoding="utf-8")).splitlines():
            m = TURN_RE.match(line.strip())
            if not m:
                continue
            label = m.group(1).strip()
            if not is_placeholder(label):
                continue
            who, _ = best_match(words(m.group(2)), blocks, w)
            if who:
                votes[label][who] += 1

    # A placeholder that raw.md ALSO carries is not a dropped name -- it is raw's own
    # unidentified speaker, faithfully passed through. ep26 keeps 19 `Speaker 1` blocks and
    # ep53 keeps 16 `Speaker 3` blocks that nobody has ever identified; matching those turns
    # against the NAMED blocks can only ever produce a confident-looking wrong answer,
    # because the right answer is not in the candidate set.
    raw_placeholders = set()
    for a, b in RAW_LABEL.findall(raw_body):
        name = (a or b).strip()
        if is_placeholder(name):
            raw_placeholders.add(norm(name))

    proposal = {}
    for label, tally in sorted(votes.items()):
        if norm(label) in raw_placeholders:
            continue
        matched = sum(tally.values())
        who, n = tally.most_common(1)[0]
        agree = n / matched if matched else 0.0
        ok, note = _confirm(label, who, traces)
        if matched >= MIN_MATCHED and agree >= MIN_AGREEMENT and ok:
            proposal[label] = (who, agree, matched, note)

    # Elimination. Where one placeholder is settled, the speaker it took is no longer
    # available to the others, and a weaker plurality for a name nobody else claimed is
    # then worth acting on. ep54 is the clean case: Speaker 2 is Rafizi at 94%, the episode
    # has exactly two speakers, so Speaker 1's 66% for Haziq is the only reading left.
    claimed = {v[0] for v in proposal.values()}
    for label, tally in sorted(votes.items()):
        if label in proposal or any(norm(label) == norm(p) for p in raw_placeholders):
            continue
        matched = sum(tally.values())
        who, n = tally.most_common(1)[0]
        agree = n / matched if matched else 0.0
        ok, note = _confirm(label, who, traces)
        if matched >= MIN_MATCHED and who not in claimed and agree >= MIN_PLURALITY and ok:
            proposal[label] = (who, agree, matched, note)
            claimed.add(who)
    return proposal, votes


def apply(ep_dir, proposal):
    changed = 0
    for name in DERIVED:
        path = ep_dir / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        before = text
        for label, (who, _, _, _) in proposal.items():
            text = text.replace(f"**{label}:**", f"**{who}:**")
        if text != before:
            path.write_text(text, encoding="utf-8")
            changed += 1
    return changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="*", help="episode tags, e.g. ep54; default all")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    for ep_dir in sorted((ROOT / "episodes").glob("*/*")):
        tag_m = re.search(r"-(ep\d+)-", ep_dir.name)
        tag = tag_m.group(1) if tag_m else ep_dir.name
        if args.tags and tag not in args.tags:
            continue
        if not (ep_dir / "raw.md").exists():
            continue
        proposal, votes = propose(ep_dir)
        if not votes:
            continue
        print(f"\n{tag} ({'2024' if 'bakar' in str(ep_dir) else '2025-26'})")
        for label, tally in sorted(votes.items()):
            matched = sum(tally.values())
            detail = ", ".join(f"{k} {v}" for k, v in tally.most_common(4))
            if label in proposal:
                who, agree, _, note = proposal[label]
                print(f"   {label:24} -> {who:18} {agree:.0%} of {matched} matched"
                      f"   {note}")
            else:
                print(f"   {label:24}    REFUSED  ({matched} matched) [{detail}]")
        if args.apply and proposal:
            print(f"   wrote {apply(ep_dir, proposal)} file(s)")


if __name__ == "__main__":
    main()
