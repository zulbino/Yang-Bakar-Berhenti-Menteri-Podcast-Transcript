"""Apply an owner-adjudicated speaker map to raw.md: renames, splits and merges.

The owner is the only reliable source for who spoke, so their answers arrive as a list of
turns rather than as anything a tool derived. This applies them mechanically and refuses
anything that would change the WORDS, because that is the one error an attribution pass
must never make: every operation below is a relabel or a boundary move, and the word
sequence of a touched block is asserted identical before and after.

Map format, as in `data/speaker_adjudications.json`. Keys starting with `_` are notes and are
ignored, which is where the reasoning and the still-open questions live.

    "ep53_round2": {
      "11:41":   {"who": "Haziq"},                    # rename the turn at this stamp
      "1:43:04": {"who": "Haziq", "text_now": "Hmm"}, # rename AND correct the text (see below)
      "29:59":   {"split": [["Haziq", "Okey, baik, YB.", "29:59"],
                            ["Rafizi", "Beria,", "30:00"]]},
      "05:13":   {"merge": 4, "who": "Multiple speakers"}
    }

  split   [who, text_until, new_stamp] per resulting turn. `text_until` is a literal
          substring; the cut lands after it. The LAST entry may use null to mean "the
          rest". Timestamps come from the caption track, not from interpolation -- see
          ENGINEERING_LOG 2.6 for why the parent block's stamp is wrong for a late split.
  merge   Collapse this many consecutive turns (starting here) into one, joined by " ... ",
          the `group_shredded_turns.py` convention for a run that cannot be apportioned.
  who     The new label. `Multiple speakers` for genuine crosstalk, `Speaker ?` for one
          person nobody could identify -- they are not the same claim.

TEXT CORRECTIONS ARE OPT-IN AND NARROW. `text_now` exists because ep19 [1:43:04] was
transcribed "MRT." and the caption reads ">> Hmm." -- an ASR error, not a label error, and
no amount of attribution work fixes it. It is the only operation here that alters words, it
requires `text_was` to match exactly, and it is reported separately. Do not use it to tidy
wording: the owner's quotes normalise punctuation ("Kita.... Ah itu Jason" for raw's "Kita
Itu Jason") and applying that would be rewriting the transcript, not attributing it.

  python scripts/apply_split_map.py data/speaker_adjudications.json
  python scripts/apply_split_map.py data/speaker_adjudications.json --write
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import episode_path, resolve_tag

ROOT = Path(__file__).resolve().parent.parent
TURN = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]\s*([^:\n]{1,40}?)\s*:\s*(.*)$")
JOIN = " ... "


def words(s):
    return s.replace(JOIN, " ").split()


def to_seconds(stamp):
    """Sort key. Must normalise: "11:41" is 11m41s and "2:05:29" is 2h5m29s, so comparing
    the split parts lexically puts 11:41 after 2:05:29 and the reverse-order guarantee that
    keeps line numbers valid across edits silently breaks."""
    parts = [int(p) for p in stamp.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def build(stamp, who, text):
    return f"[{stamp}] {who}: {text}"


def apply_one(lines, stamp, rule):
    """Rewrite the turn at `stamp` in place. Returns (n_turns_after, kind)."""
    # A timestamp is NOT unique in this corpus -- ep26 repeats 14 of them and ep53 17,
    # because a split re-uses the parent stamp and the ASR emits several turns inside one
    # second. So a rule may add `was` (the current label) and `text_was` to pin which turn
    # it means, and the combination still has to resolve to exactly one.
    def at(stamp_, label=None, text=None, prefix=None):
        out = []
        for i, l in enumerate(lines):
            m = TURN.match(l)
            if not m or m.group(1) != stamp_:
                continue
            if label is not None and m.group(2).strip() != label.strip():
                continue
            if text is not None and m.group(3).strip() != text.strip():
                continue
            # A long block cannot be pinned by quoting it whole, and after a split two
            # turns can share a stamp -- ep41 has two at 2:52:19. A prefix is enough.
            if prefix is not None and not m.group(3).strip().startswith(prefix.strip()):
                continue
            out.append(i)
        return out

    # Two signatures, because the map is re-run whole as it grows: the PENDING one (the
    # label/text the rule expects to find) and the SETTLED one (what the rule leaves
    # behind). Matching the settled signature means the rule already ran -- skip it rather
    # than fail, which is what `was`/`text_was` broke when added for disambiguation.
    hits = at(stamp, rule.get("was"), rule.get("text_was"),
              rule.get("text_was_startswith"))
    if not hits:
        if "merge" in rule:
            for j in at(stamp, rule["who"]):
                got = TURN.match(lines[j]).group(3)
                # `JOIN` present means a shredded merge already ran. A CONTINUOUS merge
                # leaves no marker at all, so it is detected by the text having grown
                # beyond the first fragment it started from.
                first = rule.get("text_was", "").strip()
                if JOIN in got or (first and got.strip().startswith(first)
                                   and len(got.strip()) > len(first)):
                    return 1, "already merged, skipped"
        elif "split" in rule:
            first_who, first_until, _ = rule["split"][0]
            anchor = first_until[0] if isinstance(first_until, list) else first_until
            for j in at(stamp, first_who):
                if anchor and TURN.match(lines[j]).group(3).strip().endswith(anchor.strip()):
                    return 1, "already split, skipped"
        elif "at_now" in rule and "who" not in rule:
            if at(rule["at_now"], rule.get("was"), rule.get("text_was"),
                  rule.get("text_was_startswith")):
                return 1, "already retimed, skipped"
        elif at(stamp, rule["who"], rule.get("text_now")):
            return 1, "already set, skipped"
    if len(hits) != 1:
        extra = "" if "was" in rule else '; add "was": "<current label>" to disambiguate'
        raise SystemExit(f"  {stamp}: matched {len(hits)} turns, expected 1{extra}")
    i = hits[0]
    _, old_who, said = TURN.match(lines[i]).groups()

    # IDEMPOTENCE. The map grows as the owner adjudicates more, so the whole file gets
    # re-run and every earlier rule is re-applied. Without this, a rename becomes a silent
    # no-op, a merge eats the FOLLOWING turns, and a `text_now` whose `text_was` already
    # changed aborts the run. Detect the settled state and skip.
    if "merge" in rule:
        first = rule.get("text_was", "").strip()
        if old_who == rule["who"] and (
                JOIN in said
                or (first and said.strip().startswith(first) and len(said.strip()) > len(first))):
            return 1, "already merged, skipped"
    elif "split" in rule:
        first_who, first_until, first_at = rule["split"][0]
        anchor = first_until[0] if isinstance(first_until, list) else first_until
        if old_who == first_who and anchor and said.strip().endswith(anchor.strip()):
            return 1, "already split, skipped"
    elif "who" in rule and old_who == rule["who"] \
            and said.strip() == rule.get("text_now", said).strip():
        return 1, "already set, skipped"

    if "merge" in rule:
        n = rule["merge"]
        # Turns are separated by a blank line, so consecutive turns are 2 lines apart.
        idx = [i + 2 * k for k in range(n)]
        for j in idx:
            if not TURN.match(lines[j]):
                raise SystemExit(f"  {stamp}: line {j} is not a turn, cannot merge {n}")
        frags = [TURN.match(lines[j]).group(3) for j in idx]
        # Two kinds of merge, and the joiner is the claim being made. `" ... "` is
        # group_shredded_turns.py's marker for a run whose words CANNOT be apportioned --
        # it says "several people, order preserved, attribution dropped". A plain space
        # says "one person said all of this continuously", which is the right join when
        # the fragments form one sentence: ep41's "Keadaan" + "mesti kita semak" and
        # "pada masa" + "itu." are single sentences the diarizer cut mid-clause, and
        # printing an ellipsis there would invent a pause nobody made.
        joiner = rule.get("join", JOIN)
        merged = build(stamp, rule["who"], joiner.join(frags))
        assert words(" ".join(frags)) == words(TURN.match(merged).group(3)), "merge changed words"
        lines[i:idx[-1] + 1] = [merged]
        return 1, f"merged {n} -> 1 as {rule['who']}" + ("" if joiner == JOIN else " (continuous)")

    if "split" in rule:
        rest, out = said, []
        for k, (who, until, new_at) in enumerate(rule["split"]):
            last = k == len(rule["split"]) - 1
            if until is None:
                out.append(build(new_at, who, rest.strip()))
                rest = ""
                break
            # `until` may be [text, nth] where the anchor legitimately repeats. ep53
            # [2:19:13] is "Human resource Itu je lah kot Okay Okay Human resource lah
            # Takde": Rafizi's whole turn is the FIRST "Human resource" and there is no
            # longer substring that ends where it ends, so the occurrence has to be stated
            # rather than guessed. Default stays exact-one, which is what caught this.
            nth = 1
            if isinstance(until, list):
                until, nth = until
            found = rest.count(until)
            if isinstance(rule["split"][k][1], str) and found != 1:
                raise SystemExit(f"  {stamp}: {until!r} appears {found}x in remainder; "
                                 f"give it as [text, nth] to pick one")
            if found < nth:
                raise SystemExit(f"  {stamp}: {until!r} appears {found}x, wanted #{nth}")
            pos = -1
            for _ in range(nth):
                pos = rest.index(until, pos + 1)
            cut = pos + len(until)
            out.append(build(new_at, who, rest[:cut].strip()))
            rest = rest[cut:]
        if rest.strip():
            raise SystemExit(f"  {stamp}: {len(rest)} chars unassigned: {rest[:70]!r}")
        assert words(said) == words(" ".join(TURN.match(o).group(3) for o in out)), \
            f"{stamp}: split changed words"
        lines[i:i + 1] = ["\n\n".join(out)]
        return len(out), " / ".join(f"{w}@{a}" for w, _, a in rule["split"])

    # Timestamp-only move, label and words untouched. Splitting a turn out of a long block
    # can expose that its NEIGHBOURS were mistimed all along: ep41's split put Rafizi's
    # answer at its true 2:52:19 in front of three blocks still stamped 2:51:37-2:51:46,
    # which reads as a backward jump. The captions place those three at 2:52:22, 2:52:35
    # and 2:52:37, so the jump was pre-existing mistiming that the correct stamp revealed.
    if "at_now" in rule and "who" not in rule:
        lines[i] = build(rule["at_now"], old_who, said)
        return 1, f"retimed {stamp} -> {rule['at_now']} ({old_who}, text untouched)"

    new_text = said
    kind = f"{old_who} -> {rule['who']}"
    if "text_now" in rule:
        if rule.get("text_was", said).strip() != said.strip():
            raise SystemExit(f"  {stamp}: text_was {rule.get('text_was')!r} != {said!r}")
        new_text = rule["text_now"]
        kind += f"   TEXT {said!r} -> {new_text!r}"
    lines[i] = build(stamp, rule["who"], new_text)
    return 1, kind


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mapfile")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    spec = json.loads(Path(args.mapfile).read_text(encoding="utf-8"))

    total, text_edits = 0, 0
    for key, rules in spec.items():
        if key.startswith("_") or not isinstance(rules, dict):
            continue
        # Entries are keyed "<tag>" or "<tag>_roundN"; the block-shaped ones from round 1
        # carry "block"/"turns" and are handled by their own historic pass, not here.
        # Round-1 sections carry "block"/"turns"; `_preserved` ones are a historic
        # record in a different schema. Neither is this tool's to re-apply.
        if "block" in rules or key.endswith("_preserved"):
            continue
        tag = key.split("_")[0]
        stamps = {k: v for k, v in rules.items() if not k.startswith("_")}
        if not stamps:
            continue
        d = ROOT / "episodes" / episode_path(resolve_tag(manifest, tag))
        path = d / "raw.md"
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        print(f"{tag}  ({len(stamps)} rule(s))")
        # Latest stamp first: a merge or split shifts every line after it.
        for stamp in sorted(stamps, key=to_seconds, reverse=True):
            n, kind = apply_one(lines, stamp, stamps[stamp])
            if "TEXT" in kind:
                text_edits += 1
            total += 1
            print(f"   {stamp:>9}  {kind}")
        if args.write:
            path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""),
                            encoding="utf-8")

    print(f"\n{total} rule(s) applied, {text_edits} of them correcting transcribed TEXT")
    print("written -- now regenerate: the published files still hold the old labels"
          if args.write else "dry run -- pass --write to apply")


if __name__ == "__main__":
    main()
