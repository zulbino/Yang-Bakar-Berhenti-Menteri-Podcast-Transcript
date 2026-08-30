"""Regenerate an episode's rewrite, then keep it ONLY if it measures better.

The rewrite stage is not deterministic and its variance is larger than the choice of
engine. Four runs over ep61's identical raw.md returned 24%, 32%, 63% and 39% of raw's
character count; only one passed `check_rewrite_complete.py` (1.41). So "re-run it to fix
the labels" is a coin flip that can cost a third of the transcript, and `regenerate_rewrites.sh`
writes over the incumbent before anyone has looked at what came back.

This runs the same regeneration into a sandbox, scores the candidate against the incumbent
on the three axes the QA suite actually flags, and promotes it only if it wins. A losing
candidate is discarded and the episode is left exactly as it was, which is the outcome that
needs to be cheap -- otherwise nobody will run the second attempt.

  python scripts/gate_rewrite.py ep02                 # regenerate, score, promote if better
  python scripts/gate_rewrite.py ep02 --score-only    # just score what is on disk
  python scripts/gate_rewrite.py ep02 --tries 3       # best of N, keeps the winner

Scoring, all three from the checks that raise the flags in the first place:

  completeness  len(interview.md) / len(raw.md), plus the en/ms translation ratios.
                A shrink is the failure mode that matters, so this is a hard veto rather
                than one term in a sum: a candidate that loses more than
                COMPLETENESS_TOLERANCE against the incumbent is rejected whatever else it
                improved. Losing content to gain a label is not a trade worth making.
  malay         `check_language_drift.malay_ratio` on interview.md against raw.md, the
                same measure behind the `malay-loss` flag.
  labels        Generic role words and cluster ids in the three published files, the same
                measure behind `generic-label` and `published-placeholder`, floored by
                what raw.md itself leaves unnamed -- a candidate cannot name a turn raw
                does not name, so rising to that floor scores as a gain, not a loss.

MANDATORY afterwards, exactly as for regenerate_rewrites.sh -- the metadata stage rewrites
hosts/guests and reverts labels to "Rafizi Ramli" on every run:

  python scripts/rebuild_roster.py --write
  python scripts/normalize_speaker_labels.py --write
  python scripts/build_episode_index.py
  python scripts/qa_check.py
"""
import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_language_drift import malay_ratio, strip_frontmatter
from check_published import DERIVED, RAW_LABEL, TURN_RE
from label_drift_audit import GENERIC
from common import episode_path, episode_slug, resolve_tag

ROOT = Path(__file__).resolve().parent.parent
# A candidate may come back a little shorter without meaning anything -- the rewrite
# smooths filler, and the corpus's own run-to-run spread at fixed input is wider than this.
# Below it, the candidate is dropping content, which no label improvement outweighs.
COMPLETENESS_TOLERANCE = 0.03
# Same idea for Malay: a couple of points of density is wording, a larger fall is
# anglicisation, which is the defect being fixed.
MALAY_TOLERANCE = 0.02


def read_body(path):
    return strip_frontmatter(path.read_text(encoding="utf-8")) if path.exists() else ""


def generic_turns(ep_dir):
    """Published turns counted by the `generic-label` and `published-placeholder` flags.

    Uses `label_drift_audit.GENERIC`, which is what raises those flags, rather than
    "the label contains no name". The difference is not academic: the honest-unknown
    markers -- `Speaker ?`, `Speaker (unidentified)`, `Penutur (tidak dikenali)`,
    `Penceramah ?` -- contain no name either, and a first version of this counter scored
    3-6 against four episodes qa_check calls CLEAN. Those markers are deliberate and are
    not a defect; flagging them is the over-firing that took `placeholder-label` to 26
    episodes before it was corrected.
    """
    n = 0
    for name in DERIVED:
        for line in read_body(ep_dir / name).splitlines():
            m = TURN_RE.match(line.strip())
            if m and GENERIC.match(m.group(1).strip()):
                n += 1
    return n


def generic_floor(ep_dir):
    """Generic published turns raw.md itself justifies -- the best any candidate can do.

    The label axis above is raw-blind, which is right when raw.md is fully named: ep56's
    raw names every one of its 138 turns while the published files print `Speaker 2` 89
    times, and that gap is the rewrite's alone. It is wrong the other way. Where raw
    leaves a turn on `Speaker 3`, no faithful rewrite can name it, so a candidate's count
    cannot fall below what raw carries, and a candidate that RISES to this floor is being
    more honest, not worse.

    ep53 is the case that needs it. Its incumbent scores 57 against a floor of 66 -- it
    sits BELOW what raw supports, which is only possible by inventing attributions for
    nine turns raw leaves unnamed. Without the floor the generic-turn veto rejects every
    honest candidate on the grounds that it stopped guessing, the same inversion that made
    `generic-label` blame the rewrite for 351 turns before check_published excluded the
    labels raw shares.
    """
    raw = read_body(ep_dir / "raw.md")
    n = sum(1 for a, b in RAW_LABEL.findall(raw) if GENERIC.match((a or b).strip()))
    return n * len(DERIVED)


AGREEMENT_MIN_WORDS = 8        # below this a published turn carries no matchable signal
AGREEMENT_TOLERANCE = 0.02     # a move smaller than this is noise, not a gain


def attribution_agreement(ep_dir):
    """Share of published turns whose label matches the raw.md block they came from.

    WHY THIS EXISTS. The generic-turn count answers "can the reader attribute this turn at
    all", and it is blind to whether the name is the RIGHT one. That gap cost a full
    three-try run on ep61: raw.md had just had 15 attribution regions re-cut and 14
    `Speaker ?` blocks named, all confirmed on video or against the owner's own gold, and
    every candidate was rejected for "nothing measurably better" because generic turns were
    0 before and 0 after. The candidates carried the corrected names; the gate could not see
    it, and restored the wrong-label incumbent.

    So this measures the thing an attribution pass actually improves. The rewrite edits
    wording but does not invent content, so a published turn and its source block share
    their rare words. Scoring is name_published_placeholders.best_match, reused rather than
    reimplemented: it weights each word by inverse block frequency and divides by
    sqrt(block length), and that division is load-bearing. Without it the score measures
    shared TOPIC and the longest-block speaker wins every comparison -- on this corpus
    always Rafizi. A hand-rolled version of this metric during the ep61 pass omitted the
    normalisation and reported 62 of 190 turns mislabelled, several of which contained a
    `YB` vocative and so were plainly the co-host.

    Only meaningful while raw.md is the trusted artefact, which is the premise of the whole
    pipeline: raw.md is reviewed, the published files are derived from it.
    """
    import name_published_placeholders as npp

    raw = read_body(ep_dir / "raw.md")
    blocks = npp.raw_blocks(raw)
    if not blocks:
        return None
    w = npp.weights(blocks)
    agree = total = 0
    for f in DERIVED:
        # TURN_RE is anchored but carries no re.M -- check_published applies it per line,
        # so finditer over the whole body silently matches nothing and the metric reads None.
        for line in read_body(ep_dir / f).splitlines():
            m = npp.TURN_RE.match(line)
            if not m:
                continue
            label = m.group(1).strip()
            tw = npp.words(m.group(2))
            if len(tw) < AGREEMENT_MIN_WORDS:
                continue
            best, sc = npp.best_match(tw, blocks, w)
            if best is None:
                continue
            total += 1
            agree += (best == label)
    return (agree / total) if total else None


def missing_speakers(ep_dir):
    """Named speakers raw.md has that NO published file mentions at all.

    A percentage cannot express this. ep61's Farhan (Pa'an) speaks once, for 16 seconds, in a
    2h54m episode: dropping him moves attribution agreement by a fraction of a point and
    loses a cast member entirely. Try 1 of a regeneration scored 90.0% against an incumbent's
    88.5% -- a real gain, under the 2-point tolerance -- and was rejected, discarding the only
    candidate that carried him.

    So this counts whole names, not turns. It is the same defect class as check_published's
    `unlabelled-host` flag, applied as a promotion criterion: a candidate that recovers a
    speaker the reader would otherwise never see is better, and one that drops a speaker
    raw.md names is worse, whatever else either did.

    Generic labels are excluded -- `Speaker ?` is not a cast member, and raw.md leaving
    someone unnamed is not the rewrite's fault.
    """
    from label_drift_audit import GENERIC, RAW_LABEL

    raw = read_body(ep_dir / "raw.md")
    names = set()
    for a, b in RAW_LABEL.findall(raw):
        n = (a or b).strip()
        if n and not GENERIC.match(n):
            names.add(n)
    published = " ".join(read_body(ep_dir / f) for f in DERIVED)
    return sorted(n for n in names if n not in published)


def score(ep_dir):
    raw = read_body(ep_dir / "raw.md")
    mixed = read_body(ep_dir / "interview.md")
    if not raw or not mixed:
        return None
    return {
        "completeness": len(mixed) / len(raw),
        "en_ratio": len(read_body(ep_dir / "interview-en.md")) / len(mixed),
        "ms_ratio": len(read_body(ep_dir / "interview-ms.md")) / len(mixed),
        "malay": malay_ratio(mixed),
        "raw_malay": malay_ratio(raw),
        "generic_turns": generic_turns(ep_dir),
        "generic_floor": generic_floor(ep_dir),
        "attribution": attribution_agreement(ep_dir),
        "missing_speakers": missing_speakers(ep_dir),
    }


def verdict(old, new):
    """(promote, reason). Completeness vetoes; the other two decide."""
    if new is None:
        return False, "candidate produced no interview.md"
    dc = new["completeness"] - old["completeness"]
    if dc < -COMPLETENESS_TOLERANCE:
        return False, (f"REJECT: completeness {old['completeness']:.0%} -> "
                       f"{new['completeness']:.0%}, a loss of {-dc:.0%} against a "
                       f"{COMPLETENESS_TOLERANCE:.0%} tolerance")
    if min(new["en_ratio"], new["ms_ratio"]) < 0.85:
        return False, (f"REJECT: a translation came back short "
                       f"(en {new['en_ratio']:.2f}, ms {new['ms_ratio']:.2f}; "
                       f"corpus min is 0.98 and 0.88)")
    dm = new["malay"] - old["malay"]
    dg = old["generic_turns"] - new["generic_turns"]
    if dm < -MALAY_TOLERANCE:
        return False, (f"REJECT: Malay density {old['malay']:.1%} -> {new['malay']:.1%}, "
                       f"more anglicised than the incumbent")
    # Symmetric with the Malay veto, and it was missing on the first batch: without it
    # YBkM-ep02 was promoted on a +9pt Malay gain while its generic labels went 84 -> 234,
    # because "improved something, worsened nothing I check" is not the same as "better".
    # Every axis that raises a flag needs a veto, or the gate trades one flag for another.
    # Attribution is vetoed symmetrically with Malay and generic labels, for the reason the
    # generic veto's own comment gives: every axis that raises a flag needs a veto, or the
    # gate trades one flag for another. A candidate that names turns after the wrong person
    # is worse than one that leaves them generic, whatever else it improved.
    # Losing a whole cast member is categorical, so it is vetoed before the percentages.
    old_missing, new_missing = set(old.get("missing_speakers") or ()), set(
        new.get("missing_speakers") or ())
    if new_missing - old_missing:
        return False, (f"REJECT: drops speaker(s) raw.md names and no published file "
                       f"mentions: {', '.join(sorted(new_missing - old_missing))}")
    recovered = old_missing - new_missing
    da = None
    if new.get("attribution") is not None and old.get("attribution") is not None:
        da = new["attribution"] - old["attribution"]
        if da < -AGREEMENT_TOLERANCE:
            return False, (f"REJECT: attribution agreement with raw.md "
                           f"{old['attribution']:.1%} -> {new['attribution']:.1%}, so more "
                           f"published turns carry a name raw.md does not support")
    floor = new["generic_floor"]
    # A candidate at or below the floor cannot attribute better, so a rise up to it is not
    # a regression -- see generic_floor(). Only a rise ABOVE the floor is the rewrite
    # dropping names raw.md actually had.
    at_floor = new["generic_turns"] <= floor
    if dg < 0 and not at_floor:
        return False, (f"REJECT: generic labels {old['generic_turns']} -> "
                       f"{new['generic_turns']}, {-dg} more turns the reader cannot "
                       f"attribute against a floor of {floor}, whatever else improved")
    # The incumbent sitting below the floor is not a better score, it is a guess: it named
    # turns raw.md leaves generic. Coming up to the floor is the gain.
    unclaimed = at_floor and old["generic_turns"] < floor
    gained_attribution = da is not None and da > AGREEMENT_TOLERANCE
    if (dg <= 0 and not unclaimed and dm <= MALAY_TOLERANCE and not gained_attribution
            and not recovered):
        att = ("" if da is None
               else f", attribution {old['attribution']:.1%} -> {new['attribution']:.1%}")
        return False, (f"REJECT: nothing measurably better (generic turns "
                       f"{old['generic_turns']} -> {new['generic_turns']}, floor {floor}, "
                       f"Malay {old['malay']:.1%} -> {new['malay']:.1%}{att})")
    gains = []
    if dg > 0:
        gains.append(f"{dg} fewer generic turn(s)")
    if unclaimed:
        gains.append(f"labels now at the floor raw.md permits ({floor}); the incumbent sat "
                     f"{floor - old['generic_turns']} below it, attributing turns raw "
                     f"leaves unnamed")
    if dm > MALAY_TOLERANCE:
        gains.append(f"Malay {old['malay']:.1%} -> {new['malay']:.1%}")
    if gained_attribution:
        gains.append(f"attribution agreement with raw.md {old['attribution']:.1%} -> "
                     f"{new['attribution']:.1%}")
    if recovered:
        gains.append(f"recovers speaker(s) the reader could not see: "
                     f"{', '.join(sorted(recovered))}")
    return True, f"PROMOTE: {', '.join(gains)}, completeness {dc:+.0%}"


def show(tag, s):
    print(f"  {tag:10s} completeness {s['completeness']:.0%}  malay {s['malay']:.1%} "
          f"(raw {s['raw_malay']:.1%})  en {s['en_ratio']:.2f}  ms {s['ms_ratio']:.2f}  "
          f"generic turns {s['generic_turns']} (floor {s['generic_floor']})"
          + ("" if s.get("attribution") is None
             else f"  attribution {s['attribution']:.1%}")
          + ("" if not s.get("missing_speakers")
             else f"  MISSING {','.join(s['missing_speakers'])}"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--tries", type=int, default=1)
    ap.add_argument("--engine", default="claude", choices=["claude", "gemini"])
    ap.add_argument("--score-only", action="store_true")
    args = ap.parse_args()

    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    ep = resolve_tag(manifest, args.tag)
    ep_dir = ROOT / "episodes" / episode_path(ep)
    incumbent = score(ep_dir)
    if incumbent is None:
        raise SystemExit(f"{args.tag}: no raw.md/interview.md to score")

    print(f"{episode_slug(ep)}")
    show("incumbent", incumbent)
    if args.score_only:
        return

    # Not args.tag: a disambiguated tag carries a colon ("ep03:berhenti"), which Windows
    # rejects in a path. The slug is unique by construction.
    sandbox = episode_slug(ep)
    backup = ROOT / "data" / f"_{sandbox}_incumbent"
    if backup.exists():
        shutil.rmtree(backup)
    backup.mkdir(parents=True)
    for name in DERIVED:
        if (ep_dir / name).exists():
            shutil.copy2(ep_dir / name, backup / name)

    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
    import transcribe_episode as T

    best, best_score, best_reason = None, incumbent, "no candidate beat the incumbent"
    for attempt in range(1, args.tries + 1):
        print(f"\n  attempt {attempt}/{args.tries} ({args.engine}) ...", flush=True)
        try:
            T.process_rewrite(ep["video_id"], force=True, rewrite_engine=args.engine)
        except Exception as exc:
            print(f"  attempt {attempt} raised {type(exc).__name__}: {exc}")
            continue
        cand = score(ep_dir)
        if cand is None:
            print("  attempt produced no interview.md")
            continue
        show(f"try {attempt}", cand)
        promote, reason = verdict(best_score, cand)
        print(f"  {reason}")
        if promote:
            keep = ROOT / "data" / f"_{sandbox}_best"
            if keep.exists():
                shutil.rmtree(keep)
            keep.mkdir(parents=True)
            for name in DERIVED:
                if (ep_dir / name).exists():
                    shutil.copy2(ep_dir / name, keep / name)
            best, best_score, best_reason = keep, cand, reason

    for name in DERIVED:
        src = (best or backup) / name
        if src.exists():
            shutil.copy2(src, ep_dir / name)
    print(f"\n  {'KEPT candidate' if best else 'RESTORED incumbent'}: {best_reason}")
    if best:
        print("  Now run: rebuild_roster.py --write, normalize_speaker_labels.py --write, "
              "build_episode_index.py, qa_check.py")


if __name__ == "__main__":
    main()
