"""Build a raw.md from MAI's words and turns, with each turn labelled from the camera.

WHY. On ep62 two transcripts exist and each is right about a different thing. MAI's text
is the better one: 1.3% deletions against the local ASR's 9.8%, the names right unaided,
1,613 turns against 180 blocks, and a clock per word. But MAI's diarization loses the third
host (Farhan recall 12%) and confuses 5.3% of speech, while the camera reference -- which
speaker the show's own cuts put on screen -- is the most accurate labelling this repo has
(ATTRIBUTION_PASS.md). The tracked raw.md is the local text with camera-corrected labels,
so the published interview would have had to be written from one file and checked against
another. This joins the two: MAI's words, the camera's names.

THREE RULES, in this order, for who a word belongs to:

  1. A short turn keeps MAI's label. The show does not cut to a grunt, so a "Hmm." or a
     "Betul." spoken over the main speaker sits under the main speaker's face; the camera
     is wrong about it by construction and MAI's own voice clustering is the better guess.
     SHORT_TURN_WORDS is the line.
  2. Otherwise the camera's speaker at that word's time, where the camera sees one.
  3. Otherwise MAI's label for the turn (taken from the merged sandbox file, which already
     carries the Farhan corrections the owner confirmed on video).

A long MAI turn that the camera says has two speakers is cut at the change, using the same
smoothing and sentence-snap guards as split_mixed_blocks.py, so a one-second flicker cannot
invent a turn and a cut lands on a full stop when one is within three words.

WORDS NEVER CHANGE. The output's word sequence is asserted equal to MAI's, so every name,
figure and place survives by construction; the only text edits are the reviewed
fix_proper_nouns.py corrections, applied to the body and counted. Stamps are asserted
non-decreasing. The result goes to data/, never episodes/; score it and read it first:

  python scripts/mai_camera_raw.py ep62
  python scripts/score_attribution.py data/camera_ref_ep62.rttm --episode ep62 \
      --blocks mai_camera=data/_ep62_mai_camera_raw.md
  python scripts/check_owner_decisions.py ep62 data/_ep62_mai_camera_raw.md
"""
import argparse
import glob
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
from fix_proper_nouns import CORRECTIONS  # noqa: E402
from split_mixed_blocks import BLOCK_RE, fmt, secs, smooth, snap_to_sentences  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHORT_TURN_WORDS = 3
CAMERA_NAME = {"Farhan": "Farhan (Pa'an)"}


class W(str):
    """A word that remembers its time; smooth()/snap_to_sentences() see a plain str."""
    def __new__(cls, text, t):
        obj = super().__new__(cls, text)
        obj.t = t
        return obj


def mai_turns(video_id):
    """MAI's turns: consecutive phrases of one speaker inside one request, with word times."""
    turns = []
    for p in sorted(glob.glob(str(ROOT / f"data/_mai_{video_id}/mai_response_*.json"))):
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        base = d["_chunk_start_s"]
        for ph in d["phrases"]:
            words = [W(w["text"], base + w["offsetMilliseconds"] / 1000) for w in ph.get("words", [])]
            if not words:
                continue
            if turns and turns[-1]["chunk"] == p and turns[-1]["cluster"] == ph.get("speaker"):
                turns[-1]["w"].extend(words)
            else:
                turns.append({"chunk": p, "cluster": ph.get("speaker"), "w": words})
    return turns


def block_labels(path):
    """{start second: label} for every block in a raw-style file."""
    out = {}
    for stamp, label, _ in BLOCK_RE.findall(path.read_text(encoding="utf-8")):
        out.setdefault(secs(stamp), label.strip())
    return out


def camera_per_second(rttm):
    out = {}
    for line in open(rttm, encoding="utf-8"):
        f = line.split()
        if f[0] != "SPEAKER":
            continue
        a, dur, who = float(f[3]), float(f[4]), CAMERA_NAME.get(f[7], f[7])
        for t in range(int(a), int(a + dur)):
            out[t] = who
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--reference", help="camera RTTM (default data/camera_ref_<tag>.rttm)")
    ap.add_argument("--out", help="default data/_<tag>_mai_camera_raw.md")
    a = ap.parse_args()

    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    episode = common.resolve_tag(manifest, a.tag)
    vid = episode["video_id"]
    tag = a.tag.partition(":")[0]
    sandbox = ROOT / "data" / f"_mai_{vid}"
    camera = camera_per_second(a.reference or ROOT / "data" / f"camera_ref_{tag}.rttm")
    merged, mai_raw = block_labels(sandbox / "raw_merged.md"), block_labels(sandbox / "raw.md")

    def mai_label(t0):
        for table in (merged, mai_raw):
            if int(t0) in table:
                return table[int(t0)]
        prior = [s for s in mai_raw if s <= t0]
        return mai_raw[max(prior)] if prior else "Speaker ?"

    turns = mai_turns(vid)
    rule_words = Counter()
    moved = Counter()
    cut_turns = 0
    runs_out = []
    for turn in turns:
        own = mai_label(turn["w"][0].t)
        if len(turn["w"]) <= SHORT_TURN_WORDS:
            rule_words["short turn, MAI label"] += len(turn["w"])
            runs_out.append({"n": own, "w": list(turn["w"]), "t0": turn["w"][0].t, "t1": turn["w"][-1].t})
            continue
        runs = []
        for w in turn["w"]:
            who = camera.get(int(w.t))
            rule_words["camera" if who else "uncovered, MAI label"] += 1
            who = who or own
            if runs and runs[-1]["n"] == who:
                runs[-1]["w"].append(w)
                runs[-1]["t1"] = w.t
            else:
                runs.append({"n": who, "w": [w], "t0": w.t, "t1": w.t})
        runs = snap_to_sentences(smooth(runs))
        if len(runs) > 1:
            cut_turns += 1
        for r in runs:
            r["t0"] = r["w"][0].t
            for w in r["w"]:
                if r["n"] != own:
                    moved[(own, r["n"])] += 1
        runs_out.extend(runs)

    # Guards: the word sequence is MAI's, and time runs forward.
    src_words = [str(w) for t in turns for w in t["w"]]
    out_words = [str(w) for r in runs_out for w in r["w"]]
    assert src_words == out_words, "word sequence changed"
    stamps = [int(r["t0"]) for r in runs_out]
    backwards = sum(1 for x, y in zip(stamps, stamps[1:]) if y < x)
    if backwards:
        sys.exit(f"REFUSING: {backwards} block stamps run backwards")

    body = "\n\n".join(f"[{fmt(r['t0'])}] {r['n']}: {' '.join(r['w'])}" for r in runs_out)
    corrections = Counter()
    for rx, rep, _ in CORRECTIONS:
        body, n = re.subn(rx, rep, body)
        if n:
            corrections[rep] += n

    fields, _ = common.read_frontmatter_body(ROOT / "episodes" / common.episode_path(episode) / "raw.md")
    fields["model"] = "microsoft/MAI-Transcribe-2"
    fields["note"] = (
        "Raw transcript from MAI-Transcribe-2 via the Azure Speech API, verbatim style, with "
        "word-level timestamps from the model itself. Speaker labels come from the show's own "
        "camera cuts (scripts/camera_speakers.py, an on-screen active-speaker reference) at the "
        "time of each word; turns of three words or fewer keep MAI's voice-cluster label, and "
        "words the camera does not cover fall back to it. Built by scripts/mai_camera_raw.py; "
        "the word sequence is MAI's, unchanged, apart from the reviewed name corrections in "
        "fix_proper_nouns.py. See interview.md for the polished newspaper-style rewrite.")
    out = Path(a.out or ROOT / "data" / f"_{tag}_mai_camera_raw.md")
    out.write_text(common.frontmatter_md(fields, "# Raw Transcript\n\n" + body), encoding="utf-8")

    words_by = Counter()
    for r in runs_out:
        words_by[r["n"]] += len(r["w"])
    total = sum(words_by.values())
    print(f"{len(turns)} MAI turns -> {len(runs_out)} blocks, {total} words, "
          f"{cut_turns} turns cut by the camera")
    print("words labelled by rule:", dict(rule_words))
    print("words per speaker:", {k: f"{v} ({v/total:.1%})" for k, v in words_by.most_common()})
    print("words moved off MAI's label:", {f"{a}->{b}": n for (a, b), n in moved.most_common()})
    print("name corrections applied:", dict(corrections))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
