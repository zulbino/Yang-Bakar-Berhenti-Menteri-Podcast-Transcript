"""Was raw.md transcribed by the best engine we actually have words from?

WHY THIS EXISTS. The owner, 2026-09-13: *"i saw some episodes that considered clean in the
qa checklist hasnt been run through mai transcribe? or do we exclude some that already have
high pass score or something"*

Nothing is excluded, and that is the problem. MAI has been run on all 70 episodes and the
words are on disk. But raw.md is only REBUILT from them during
`adopt_mai_camera_raw.py`, which needs a camera reference first. So 39 episodes were
marked clean in QA_CHECKLIST.md while raw.md still came from an engine measured six times
worse, and the checklist had no way to say so.

THE MEASUREMENT THAT MAKES THIS A DEFECT, not a preference. On Revolab's public Malaysian
split, MAI-Transcribe-2 scores 3.39% WER on podcast audio and
`mesolitica/malaysian-whisper-medium-v2` scores 20.52%. See MODEL_LANDSCAPE.md. A clean row
on a 20.52% raw.md means "no known failure signature fired", never "the words are right" --
and the QA checklist says exactly that in its own header. This check makes the engine
visible instead of leaving it to be inferred.

TWO SIGNATURES, both report-only:

  raw-engine-superseded  MAI words exist for this video and raw.md was transcribed by
                         something else. Names the engine, because the gap differs: local
                         Whisper is 20.52%, and the gemini/speechmatics raws were one-off
                         recovery passes.
  raw-engine-unknown     raw.md records no model at all. 18 episodes predate the field, so
                         a reader cannot tell what produced the words. Not a transcription
                         defect by itself, but it means the row above cannot be trusted
                         either way.

WHY IT IS NOT A FAILURE TO FIX RIGHT NOW. Rebuilding raw.md needs a camera reference, and
the owner's standing rule of 2026-09-12 is to REPROCESS an episode with the camera rather
than hand-patch its local-ASR raw, one at a time. So this check exists to keep the backlog
honest and visible, not to push a fix. `corpus_status.py` shows the same thing as live
state; this puts it where a reader of the QA checklist will see it.

  python scripts/check_raw_engine.py
  python scripts/check_raw_engine.py --episodes ep35 ep36
"""
import argparse
import glob
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
BEST = "mai"                 # substring match: the frontmatter spells it several ways
# Measured word error rate on podcast audio, Revolab's public Malaysian split. Quoted so a
# report line carries the size of the gap rather than just naming a model.
WER = {"mai": "3.39%", "mesolitica": "20.52%"}


def raw_model(fm):
    m = fm.get("model") or fm.get("models") or ""
    if isinstance(m, dict):
        m = m.get("raw.md") or m.get("raw") or ""
    return str(m)


def read(ep_dir):
    raw = Path(ep_dir) / "raw.md"
    if not raw.exists():
        return None
    text = raw.read_text(encoding="utf-8")
    fm = yaml.safe_load(text.split("---")[1]) if text.startswith("---") else {}
    return fm or {}


def check(ep_dir):
    fm = read(ep_dir)
    if fm is None:
        return []
    vid = fm.get("video_id")
    model = raw_model(fm)
    have_mai = bool(glob.glob(str(ROOT / f"data/_mai_{vid}" / "mai_response_*.json")))
    issues = []
    if not model:
        issues.append((
            "raw-engine-unknown",
            "raw.md records no `model:` -- it predates the field, so what transcribed "
            "these words is not recoverable from the file. Rebuilding it through "
            "adopt_mai_camera_raw.py records it.",
        ))
    elif BEST not in model.lower() and have_mai:
        gap = next((f", measured {v} WER against MAI's {WER['mai']} on podcast audio"
                    for k, v in WER.items() if k in model.lower()), "")
        issues.append((
            "raw-engine-superseded",
            f"raw.md was transcribed by {model!r}{gap}, and this episode's MAI words are "
            f"already on disk in data/_mai_{vid}/. It needs a camera reference, then "
            f"adopt_mai_camera_raw.py. A clean row only means no known failure signature "
            f"fired, never that the words are right.",
        ))
    return issues


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--episodes", nargs="*")
    a = p.parse_args()

    only = set(a.episodes) if a.episodes else None
    n = 0
    for raw in sorted(glob.glob(str(ROOT / "episodes" / "*" / "*" / "raw.md"))):
        d = Path(raw).parent
        tag = d.name.split("-")[3]
        if only and tag not in only:
            continue
        found = check(d)
        if found:
            print(f"\n{tag}  {d.name}")
            for sig, why in found:
                print(f"   [{sig}] {why}")
            n += len(found)
    print(f"\n{n} raw-engine issue(s)")


if __name__ == "__main__":
    main()
