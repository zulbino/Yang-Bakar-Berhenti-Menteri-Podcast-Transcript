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
     SHORT_TURN_WORDS is the line. EXCEPTION: when the fallback label is a generic
     placeholder (Speaker N / Speaker ?), there is no voice identity to protect -- that is
     a collapsed pyannote cluster from an episode transcribed --no-diarization -- and the
     camera's read wins even for a short turn. Every new premiere hits this case
     (HANDOFF_2026-09-12.md section 3).
  2. Otherwise the camera's speaker at that word's time, where the camera sees one.
  3. Otherwise MAI's label for the turn (taken from the merged sandbox file, which already
     carries the Farhan corrections the owner confirmed on video).

A long MAI turn that the camera says has two speakers is cut at the change, using the same
smoothing and sentence-snap guards as split_mixed_blocks.py, so a one-second flicker cannot
invent a turn and a cut lands on a full stop when one is within three words.

THE GOLD PASSAGE IS CARVED OUT. Where data/speaker_ground_truth.json holds a passage the
owner dictated from ear, the current raw.md's blocks for that passage are spliced in
verbatim and the candidate's own blocks for the same speech are dropped. On ep61 the camera
inverts that passage -- it gives Haziq's "Baik YB, cuti panjang YB buat apa?" to Rafizi and
Rafizi's answer to Haziq -- because the shot there is a graphic, not a face. The seam is
found by WORDS, not by the clock, since the two files' stamps differ by up to 26 s. The
reviewed name corrections are applied before the splice, so the owner's bytes are untouched.

A HANGING FRAGMENT THE CAMERA CANNOT SEE is fixed by scripts/fold_hanging_fragments.py,
which runs AFTER strip_filler_turns.py -- not here. Inside this tool the fragment's
neighbours are usually a one-word grunt turn rather than the speaker's own speech, so the
"same speaker either side" test fails and the fragment survives; ep61's 27:24 escaped that
way. Run the sequence at the top of ATTRIBUTION_PASS.md, in order.

THE OWNER OUTRANKS THE CAMERA. `data/forced_labels.json` holds the turns where a recorded
owner decision and the camera disagree and the owner has ruled for their own label. They
are applied last, located by words, and a text that cannot be found or that matches more
than three blocks stops the run rather than being skipped quietly. On ep61 there are two,
both from a stamp that sits 16-19 s before its own words.

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
from lib_locate import Doc, tokens  # noqa: E402
from split_mixed_blocks import BLOCK_RE, fmt, secs, smooth, snap_to_sentences  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SHORT_TURN_WORDS = 3
GENERIC = re.compile(r"^Speaker\s*(\d+|\?)$")   # a placeholder, not a person
DIAR_PURITY = 0.90      # a pyannote cluster is named only if the camera agrees this often
DIAR_MIN_COVERED = 60   # ... over at least this many camera-covered seconds
GOLD_PAD = 60
MAX_FORCED_BLOCKS = 3          # a block starting just before the region can carry its first words
SEAM_WORDS = 8
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
            # Without diarization every phrase has speaker None; then a phrase is the turn,
            # otherwise one chunk would collapse into a single turn and rule 1 would vanish.
            if (turns and ph.get("speaker") is not None and turns[-1]["chunk"] == p
                    and turns[-1]["cluster"] == ph.get("speaker")):
                turns[-1]["w"].extend(words)
            else:
                turns.append({"chunk": p, "cluster": ph.get("speaker"), "w": words})
    # MAI does not always list phrases in time order: ep60 has "Ha." at 29:58 listed before
    # "Ada kan, pan check lah" at 29:53. The transcript is read in time order, so sort.
    turns.sort(key=lambda t: t["w"][0].t)
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
        name = f[7].replace("_", " ")          # RTTM writes a space as an underscore
        a, dur, who = float(f[3]), float(f[4]), CAMERA_NAME.get(name, name)
        for t in range(int(a), int(a + dur)):
            out[t] = who
    return out


def diar_per_second(path, camera):
    """{second: name} from a pyannote run, for the clusters the camera can vouch for.

    CLAUDE.md rule 4: pyannote is the LAST fallback, only where neither MAI nor the camera
    covers a moment. A cluster gets a name only when DIAR_PURITY of its camera-covered
    seconds carry one name over at least DIAR_MIN_COVERED seconds; every other cluster
    stays anonymous. On ep63 that names two of eleven clusters (Rafizi 98.9%, the guest
    96.0%) and refuses Haziq's at 79%."""
    by_cluster = {}
    for a, b, sp in json.loads(Path(path).read_text(encoding="utf-8")):
        for t in range(int(a), int(b) + 1):
            by_cluster.setdefault(sp, set()).add(t)
    names, report = {}, {}
    for sp, secs_ in by_cluster.items():
        seen = Counter(camera[t] for t in secs_ if t in camera)
        covered = sum(seen.values())
        top, n = seen.most_common(1)[0] if seen else ("-", 0)
        ok = covered >= DIAR_MIN_COVERED and n / covered >= DIAR_PURITY
        report[sp] = f"{top} {n / covered:.1%} of {covered}s" + ("" if ok else " (refused)") if covered else "no camera overlap (refused)"
        if ok:
            names[sp] = top
    out = {}
    for sp, secs_ in by_cluster.items():
        if sp in names:
            for t in secs_:
                out.setdefault(t, names[sp])
    return out, report


def gold_region(vid):
    """The owner-dictated passage for this video: (start, end, its region text)."""
    truth = json.loads((ROOT / "data" / "speaker_ground_truth.json").read_text(encoding="utf-8"))
    for g in truth.values():
        if not isinstance(g, dict) or g.get("video_id") != vid:
            continue
        m = re.findall(r"(\d{1,2}:\d{2}(?::\d{2})?)", g.get("region", ""))
        if len(m) >= 2:
            return secs(m[0]), secs(m[1]), g["region"]
    return None


def carve_in_gold(lines, episode_raw, vid):
    """Splice the current raw.md's gold-passage blocks into the candidate's lines."""
    region = gold_region(vid)
    if not region:
        return lines, "no gold passage recorded for this video"
    lo, hi, text = region
    cur = Doc(episode_raw.read_text(encoding="utf-8"))
    keep = [i for i, b in enumerate(cur.blocks) if lo - GOLD_PAD <= secs(b[0]) <= hi]
    if not keep:
        sys.exit(f"REFUSING: gold passage {text!r} matches no block in {episode_raw}")
    cand = Doc("\n\n".join(lines))
    head = cand.locate(" ".join(tokens(cur.blocks[keep[0]][2])[:SEAM_WORDS]),
                       near=secs(cur.blocks[keep[0]][0]))
    tail = cand.locate(" ".join(tokens(cur.blocks[keep[-1]][2])[-SEAM_WORDS:]),
                       near=secs(cur.blocks[keep[-1]][0]))
    if not head or not tail:
        sys.exit(f"REFUSING: cannot find the gold passage {text!r} in the candidate by its words")
    b0, b1 = cand.owner[head["tok0"]], cand.owner[tail["tok1"]]
    if b1 < b0:
        sys.exit(f"REFUSING: the gold passage seams cross in the candidate ({b0} > {b1})")
    dropped = sum(len(tokens(cand.blocks[i][2])) for i in range(b0, b1 + 1))
    print(f"gold carve-out {text!r}: {len(keep)} current blocks spliced in verbatim, "
          f"replacing candidate blocks {b0}-{b1} ({dropped} MAI words)")
    print(f"  seam before: {lines[b0 - 1] if b0 else '(file start)'}")
    print(f"  first kept:  {cur.line(keep[0])[:100]}")
    print(f"  last kept:   {cur.line(keep[-1])[:100]}")
    print(f"  seam after:  {lines[b1 + 1] if b1 + 1 < len(lines) else '(file end)'}")
    return (lines[:b0] + [cur.line(i) for i in keep] + lines[b1 + 1:],
            f"{len(keep)} blocks from {text}")


def force_labels(lines, tag):
    """Apply the owner's rulings from data/forced_labels.json over the camera's answer."""
    path = ROOT / "data" / "forced_labels.json"
    rules = json.loads(path.read_text(encoding="utf-8")).get(tag, []) if path.exists() else []
    if not rules:
        return lines, "none recorded for this episode"
    forced = 0
    for r in rules:
        # Rebuilt per rule: a split changes the block list, and a later rule that located
        # against the old document would write the whole fused turn back (ep53 2:19:14).
        doc = Doc("\n\n".join(lines))
        found = doc.locate(r["text"], near=secs(r["at"]) if r.get("at") else None)
        if not found:
            sys.exit(f"REFUSING: owner ruling not locatable in the candidate: {r['text']!r}")
        if len(found["blocks"]) > MAX_FORCED_BLOCKS:
            sys.exit(f"REFUSING: {r['text']!r} spans {len(found['blocks'])} blocks, "
                     "too broad to force a label onto")
        if found["ambiguous"]:
            print(f"  WARNING: {r['text']!r} has a second equally good match; "
                  "the stamp picked this one")
        for i in found["blocks"]:
            stamp, label, body = doc.blocks[i]
            if r.get("split_at_words") and r["text"] in body and body.strip() != r["text"]:
                # MAI fused the owner's turn with its neighbour ("Itu jelah kot. Okey eh,
                # okey."). Cut at the literal words so the ruling lands on them alone; the
                # remainder keeps the label it had, and both halves keep the stamp.
                head, tail = body.split(r["text"], 1)
                # Everything before the words keeps its label; the words and what follows
                # them in the same turn go to the owner's speaker.
                pieces = [p for p in ((label, head.strip()), (r["who"], (r["text"] + tail).strip())) if p[1]]
                print(f"  owner ruling (split): [{stamp}] {label}: {body[:60]} -> "
                      + " / ".join(f"{w}: {b[:30]}" for w, b in pieces))
                lines[i] = "\n\n".join(f"[{stamp}] {w}: {b}" for w, b in pieces)
                lines = [b for l in lines for b in l.split("\n\n")]
                forced += 1
                break          # block indices moved; the next rule re-locates on the new document
            if label == r["who"]:
                continue
            print(f"  owner ruling: {label} -> {r['who']} at [{stamp}] {body[:60]}")
            lines[i] = f"[{stamp}] {r['who']}: {body}"
            forced += 1
    # A split writes two blocks into one line slot; re-split so every later step sees blocks.
    lines = [b for l in lines for b in l.split("\n\n")]
    return lines, f"{forced} blocks set from data/forced_labels.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--reference", help="camera RTTM (default data/camera_ref_<tag>.rttm)")
    ap.add_argument("--out", help="default data/_<tag>_mai_camera_raw.md")
    ap.add_argument("--current", help="the raw.md the owner decisions and the gold passage "
                    "were recorded against. AFTER A SWAP THIS IS REQUIRED: the episode's "
                    "raw.md is then this tool's own previous output, and reading it back "
                    "feeds the fallback labels and the gold splice their own answer.")
    ap.add_argument("--diar", help="pyannote JSON [[start, end, cluster], ...] used as the last "
                    "fallback for words neither the camera nor a named MAI label covers "
                    "(default data/diar_<vid>_t055.json when it exists; --diar none to skip)")
    ap.add_argument("--no-gold-splice", action="store_true",
                    help="do not carve the owner-dictated passage in from the current raw.md")
    a = ap.parse_args()

    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    episode = common.resolve_tag(manifest, a.tag)
    vid = episode["video_id"]
    tag = a.tag.partition(":")[0]
    sandbox = ROOT / "data" / f"_mai_{vid}"
    camera = camera_per_second(a.reference or ROOT / "data" / f"camera_ref_{tag}.rttm")
    diar_path = Path(a.diar) if a.diar and a.diar != "none" else ROOT / "data" / f"diar_{vid}_t055.json"
    diar, diar_report = ({}, {}) if a.diar == "none" or not diar_path.exists() else diar_per_second(diar_path, camera)
    episode_raw = Path(a.current) if a.current else (
        ROOT / "episodes" / common.episode_path(episode) / "raw.md")
    # Fallback labels: MAI's own (merged file first, it carries the video-confirmed Farhan
    # regions) when MAI ran with diarization; otherwise the episode's current raw.md, which
    # is the best labelling that exists for an episode transcribed with --no-diarization.
    tables = [block_labels(sandbox / n) for n in ("raw_merged.md", "raw.md") if (sandbox / n).exists()]
    fallback_name = "MAI's voice-cluster label" if tables else "the current raw.md's label"
    if not tables:
        tables = [block_labels(episode_raw)]
    starts = sorted(tables[-1])

    def mai_label(t0):
        for table in tables:
            if int(t0) in table:
                return table[int(t0)]
        prior = [s for s in starts if s <= t0]
        return tables[-1][max(prior)] if prior else "Speaker ?"

    turns = mai_turns(vid)
    rule_words = Counter()
    disputed = []          # short turns where a named voice cluster and the camera disagree
    moved = Counter()
    cut_turns = 0
    runs_out = []
    for turn in turns:
        own = mai_label(turn["w"][0].t)
        if len(turn["w"]) <= SHORT_TURN_WORDS:
            # Rule 1 protects a real short interjection from the on-screen face, but only
            # when the fallback names a real person. A generic placeholder (Speaker N,
            # Speaker ?) is a collapsed old diarization with no identity to protect, so
            # the camera's read at those seconds is the better evidence (ep63, 05:51
            # "Cuma," -- camera read Rafizi, the fallback said Speaker 2).
            seen = Counter(camera[int(w.t)] for w in turn["w"] if int(w.t) in camera)
            heard = Counter(diar[int(w.t)] for w in turn["w"] if int(w.t) in diar)
            # Voice before face for a short turn, for the same reason rule 1 exists: the
            # show does not cut to an aside, so the camera shows the listener. On ep63 the
            # two disagreed on 46 short turns and the voice said Rafizi in 40 of them.
            if GENERIC.match(own) and heard:
                own = heard.most_common(1)[0][0]
                rule_words["short turn, pyannote cluster (generic fallback)"] += len(turn["w"])
                if seen and seen.most_common(1)[0][0] != own:
                    disputed.append((turn["w"][0].t, own, seen.most_common(1)[0][0], " ".join(turn["w"])))
            elif GENERIC.match(own) and seen:
                own = seen.most_common(1)[0][0]
                rule_words["short turn, camera (generic fallback)"] += len(turn["w"])
            else:
                rule_words["short turn, MAI label"] += len(turn["w"])
            runs_out.append({"n": own, "w": list(turn["w"]), "t0": turn["w"][0].t, "t1": turn["w"][-1].t})
            continue
        runs = []
        # Same exception as rule 1: a word the camera does not cover falls back to MAI's
        # label, unless that label is a generic placeholder and the camera did see the
        # rest of this turn -- then the turn's own camera majority is the better guess.
        seen = Counter(camera[int(w.t)] for w in turn["w"] if int(w.t) in camera)
        heard = Counter(diar[int(w.t)] for w in turn["w"] if int(w.t) in diar)
        if GENERIC.match(own) and seen:
            fill, fill_rule = seen.most_common(1)[0][0], "uncovered, turn's camera majority (generic fallback)"
        elif GENERIC.match(own) and heard:
            fill, fill_rule = heard.most_common(1)[0][0], "uncovered, pyannote cluster (generic fallback)"
        else:
            fill, fill_rule = own, "uncovered, MAI label"
        for w in turn["w"]:
            who = camera.get(int(w.t))
            rule_words["camera" if who else fill_rule] += 1
            who = who or fill
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
        for r1, r2 in zip(runs_out, runs_out[1:]):
            if int(r2["t0"]) < int(r1["t0"]):
                print(f"  {fmt(r1['t0'])} {r1['n']}: {' '.join(r1['w'][:8])} ... -> "
                      f"{fmt(r2['t0'])} {r2['n']}: {' '.join(r2['w'][:8])}", file=sys.stderr)
        sys.exit(f"REFUSING: {backwards} block stamps run backwards")

    # Corrections first, then the splice: the owner's own bytes are never rewritten.
    body = "\n\n".join(f"[{fmt(r['t0'])}] {r['n']}: {' '.join(r['w'])}" for r in runs_out)
    corrections = Counter()
    for rx, rep, _ in CORRECTIONS:
        body, n = re.subn(rx, rep, body)
        if n:
            corrections[rep] += n
    lines = body.split("\n\n")
    gold_note = "not carved out (--no-gold-splice)"
    if not a.no_gold_splice:
        lines, gold_note = carve_in_gold(lines, episode_raw, vid)
    lines, forced_note = force_labels(lines, tag)
    body = "\n\n".join(lines)
    spliced = [secs(m) for m in re.findall(r"^\[([\d:]+)\]", body, re.M)]
    back = [i for i, (x, y) in enumerate(zip(spliced, spliced[1:])) if y < x]
    if back:
        for i in back[:5]:
            print(f"  {lines[i][:80]} -> {lines[i + 1][:80]}", file=sys.stderr)
        sys.exit(f"REFUSING: {len(back)} stamps run backwards after the gold carve-out")

    fields, _ = common.read_frontmatter_body(episode_raw)
    fields["model"] = "microsoft/MAI-Transcribe-2"
    fields["note"] = (
        "Raw transcript from MAI-Transcribe-2 via the Azure Speech API, verbatim style, with "
        "word-level timestamps from the model itself. Speaker labels come from the show's own "
        "camera cuts (scripts/camera_speakers.py, an on-screen active-speaker reference) at the "
        f"time of each word; turns of three words or fewer keep {fallback_name}, and "
        "words the camera does not cover fall back to it. Built by scripts/mai_camera_raw.py; "
        "the word sequence is MAI's, unchanged, apart from the reviewed name corrections in "
        f"fix_proper_nouns.py and the owner-verified passage kept from the previous transcript "
        f"({gold_note}; owner rulings over the camera: {forced_note}). See interview.md for the polished newspaper-style rewrite.")
    out = Path(a.out or ROOT / "data" / f"_{tag}_mai_camera_raw.md")
    out.write_text(common.frontmatter_md(fields, "# Raw Transcript\n\n" + body), encoding="utf-8")

    words_by = Counter()
    for r in runs_out:
        words_by[r["n"]] += len(r["w"])
    total = sum(words_by.values())
    print(f"{len(turns)} MAI turns -> {len(runs_out)} blocks, {total} words, "
          f"{cut_turns} turns cut by the camera")
    print("words labelled by rule:", dict(rule_words))
    if diar_report:
        print("pyannote clusters vs camera:", diar_report)
    if disputed:
        print(f"short turns where the voice cluster (kept) and the camera disagree: {len(disputed)} "
              f"-- CLAUDE.md rule 8 residue, list them for the owner with ?t= links")
        for t, v, c, txt in disputed:
            print(f"  {fmt(t)} voice={v} camera={c}: {txt}")
    print("words per speaker:", {k: f"{v} ({v/total:.1%})" for k, v in words_by.most_common()})
    print("words moved off MAI's label:", {f"{a}->{b}": n for (a, b), n in moved.most_common()})
    print("name corrections applied:", dict(corrections))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
