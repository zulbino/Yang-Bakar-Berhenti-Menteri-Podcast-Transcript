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
                measure behind `generic-label` and `published-placeholder`.

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
from check_published import DERIVED, TURN_RE
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
    if dg < 0:
        return False, (f"REJECT: generic labels {old['generic_turns']} -> "
                       f"{new['generic_turns']}, {-dg} more turns the reader cannot "
                       f"attribute, whatever else improved")
    if dg <= 0 and dm <= MALAY_TOLERANCE:
        return False, (f"REJECT: nothing measurably better (generic turns "
                       f"{old['generic_turns']} -> {new['generic_turns']}, Malay "
                       f"{old['malay']:.1%} -> {new['malay']:.1%})")
    gains = []
    if dg > 0:
        gains.append(f"{dg} fewer generic turn(s)")
    if dm > MALAY_TOLERANCE:
        gains.append(f"Malay {old['malay']:.1%} -> {new['malay']:.1%}")
    return True, f"PROMOTE: {', '.join(gains)}, completeness {dc:+.0%}"


def show(tag, s):
    print(f"  {tag:10s} completeness {s['completeness']:.0%}  malay {s['malay']:.1%} "
          f"(raw {s['raw_malay']:.1%})  en {s['en_ratio']:.2f}  ms {s['ms_ratio']:.2f}  "
          f"generic turns {s['generic_turns']}")


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
