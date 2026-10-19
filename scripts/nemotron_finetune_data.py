"""Training data for fine-tuning Nemotron 3 on the owner's corrected episodes (owner, 2026-10-19).

Each word of the owner's raw.md takes its ASR time (the same alignment voice_label_raw.py uses);
consecutive words of one speaker with gaps under 0.5 s join into one RTTM segment, so the
reference marks speech, silence and the exact switch. `Speaker ?` and `Multiple speakers` words are
left out. Writes data/_finetune/<tag>.rttm, the 16 kHz wav path, and NeMo manifests of 90 s
windows: train on every episode but the held-out one, validate on it.

    python scripts/nemotron_finetune_data.py --hold ep68
"""
import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common
import verify_speaker_voiceprint as V

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "_finetune"
GOLD = ["ep65", "ep66", "ep67", "ep68"]
TURN = re.compile(r"^\[[\d:]+\]\s*([^:\n\[\]]{1,40}?):\s*(.*)$")
WORD = re.compile(r"[\w']+")
SKIP = {"Speaker ?", "Multiple speakers"}
WINDOW, GAP = 90.0, 0.5


def segments(tag):
    raw = common.raw_for_tag(tag)
    head = raw.read_text(encoding="utf-8").split("# Raw Transcript", 1)
    vid = re.search(r"^video_id:\s*(\S+)", head[0], re.M).group(1)
    flat = []
    for line in head[1].splitlines():
        m = TURN.match(line.strip())
        if m:
            who = re.sub(r"\s*\(.*?\)\s*$", "", m.group(1).strip())
            flat += [(who, (WORD.findall(t.lower()) or [""])[0]) for t in m.group(2).split()]
    asr = [(w.lower(), x["t"] / 1000, max(x.get("d", 0), 1) / 1000)
           for t in json.loads((ROOT / "data" / f"_mai_{vid}" / "mai_words.json").read_text(encoding="utf-8"))["turns"]
           for x in t["words"] for w in WORD.findall(x["w"] or "")]
    sm = SequenceMatcher(None, [f[1] for f in flat], [a[0] for a in asr], autojunk=False)
    timed = []
    for x, y, n in sm.get_matching_blocks():
        timed += [(flat[x + k][0], asr[y + k][1], asr[y + k][1] + asr[y + k][2]) for k in range(n)]
    segs = []
    for who, s, e in timed:
        if who in SKIP:
            continue
        if segs and segs[-1][0] == who and s - segs[-1][2] < GAP:
            segs[-1][2] = max(segs[-1][2], e)
        else:
            segs.append([who, s, e])
    print(f"{tag}: {len(timed)} of {len(flat)} words timed, {len(segs)} segments")
    return vid, segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", default="ep68")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    rows = {"train": [], "val": []}
    for tag in GOLD:
        vid, segs = segments(tag)
        rttm = OUT / f"{tag}.rttm"
        rttm.write_text("".join(f"SPEAKER {vid} 1 {s:.3f} {e - s:.3f} <NA> <NA> {w.replace(' ', '_')} <NA> <NA>\n"
                                for w, s, e in segs), encoding="utf-8")
        V.load_audio(vid)
        wav = ROOT / "audio" / f"_{vid}.16k.wav"
        end = segs[-1][2]
        t = 0.0
        while t < end:
            n = len({w for w, s, e in segs if s < t + WINDOW and e > t})
            if n:
                rows["val" if tag == a.hold else "train"].append(
                    {"audio_filepath": str(wav), "offset": t, "duration": WINDOW, "label": "infer",
                     "text": "-", "num_speakers": n, "rttm_filepath": str(rttm), "uem_filepath": None})
            t += WINDOW
    for k, r in rows.items():
        (OUT / f"{k}_hold_{a.hold}.json").write_text("".join(json.dumps(x) + "\n" for x in r), encoding="utf-8")
        print(f"{k}: {len(r)} windows of {WINDOW:.0f} s")


if __name__ == "__main__":
    main()
