"""Diarize an episode with pyannoteAI's hosted Precision-2, with optional voiceprints.

WHY TRY IT. The camera reference (`scripts/camera_speakers.py`) showed the gap on ep62 is
not the diarizer -- pyannote 3.x already recovers 85% of Haziq's speaking time while the
shipped raw.md recovers 67%. What is untested is whether a better diarizer plus ENROLLED
VOICEPRINTS closes the remaining 15%, because that is the one thing no local model here can
do: it turns "cluster 2" into "Haziq" without a naming stage to lose points in.

THE TRIAL IS FINITE. 150 hours and 10 voiceprints, and one pass over ep62 is 3h55m of it.
So this caches every response under data/_pyannoteai/ and never re-submits a job whose
result is already on disk. Delete the cache file to force a re-run, deliberately.

TWO MODES.

  diarize    plain speaker diarization, clusters with no names. Comparable to pyannote 3.x
             and MAI, and the row that answers "is the hosted model better".
  identify   diarization against enrolled voiceprints, so segments come back NAMED. This is
             the mode worth the trial. `exclusive` forces every segment to one of the
             enrolled speakers instead of allowing unknown ones -- correct here only if the
             episode really has no fourth voice, which the camera census can confirm.

VOICEPRINTS COME FROM CAMERA-CONFIRMED AUDIO, NOT FROM raw.md's LABELS. Enrolling on a
segment whose label is wrong teaches the wrong voice, and raw.md's labels are exactly what
is under test. `--enroll-from` reads the camera RTTM and cuts the longest single-speaker
runs, which are the segments with the strongest evidence behind them.

  python scripts/pyannoteai_diarize.py 0M5hweswMpE --enroll-from data/camera_ref_ep62.rttm
  python scripts/pyannoteai_diarize.py 0M5hweswMpE --mode identify --exclusive
"""
import argparse
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "_pyannoteai"
AUDIO = ROOT / "audio"
ENROLL_SECONDS = 30          # pyannoteAI asks for 10-30s of clean single-speaker audio
MIN_RUN = 12                 # a run shorter than this is not worth enrolling on


def api_key():
    key = os.environ.get("PYANNOTEAI_API_KEY")
    if not key and sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                key = winreg.QueryValueEx(k, "PYANNOTEAI_API_KEY")[0]
        except FileNotFoundError:
            pass
    if not key:
        sys.exit("PYANNOTEAI_API_KEY is not set.\n"
                 "  Create a key at https://dashboard.pyannote.ai then:\n"
                 "  [Environment]::SetEnvironmentVariable("
                 "'PYANNOTEAI_API_KEY','<key>','User')")
    return key


def longest_runs(rttm, per_speaker=1):
    """The longest uninterrupted single-speaker runs, per speaker, from a camera RTTM."""
    runs = defaultdict(list)
    for line in open(rttm):
        p = line.split()
        runs[p[7]].append((float(p[3]), float(p[4])))
    out = {}
    for name, segs in runs.items():
        segs.sort(key=lambda s: -s[1])
        out[name] = segs[:per_speaker]
    return out


def cut(video_id, start, duration, dest):
    """16 kHz mono wav, which is what the API wants and what avoids a server-side resample."""
    src = AUDIO / f"{video_id}.m4a"
    if not src.exists():
        sys.exit(f"{src} not found")
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", str(start), "-t", str(duration), "-i", str(src),
                    "-ac", "1", "-ar", "16000", str(dest)], check=True)
    return dest


def wait(client, job_id, label, poll=15):
    """`retrieve` already blocks and polls, so this only times it and reports failure."""
    began = time.time()
    result = client.retrieve(job_id, every_seconds=poll)
    status = (result.get("status") or "").lower()
    if status in ("failed", "canceled", "cancelled"):
        sys.exit(f"{label}: job {job_id} {status}: {result}")
    print(f"  {label}: {status or 'done'} in {time.time() - began:.0f}s", flush=True)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--mode", choices=["diarize", "identify"], default="diarize")
    ap.add_argument("--enroll-from", help="camera RTTM to cut voiceprint samples from")
    ap.add_argument("--allow-unknown", action="store_true",
                    help="identify mode: permit speakers outside the enrolled set "
                         "(turns exclusive_matching off, which defaults to on)")
    ap.add_argument("--num-speakers", type=int)
    a = ap.parse_args()
    a.exclusive = not a.allow_unknown        # only used to name the cache file

    from pyannoteai.sdk import Client
    client = Client(api_key())
    CACHE.mkdir(parents=True, exist_ok=True)

    prints_path = CACHE / f"{a.video_id}_voiceprints.json"
    voiceprints = json.loads(prints_path.read_text()) if prints_path.exists() else {}

    if a.enroll_from and not voiceprints:
        for name, segs in longest_runs(a.enroll_from).items():
            start, dur = segs[0]
            if dur < MIN_RUN:
                print(f"  {name}: longest run is {dur:.0f}s, under {MIN_RUN}s -- skipped")
                continue
            take = min(ENROLL_SECONDS, dur)
            wav = cut(a.video_id, start, take, CACHE / f"enroll_{name}.wav")
            print(f"  enrolling {name} from {start:.0f}s +{take:.0f}s", flush=True)
            job = client.voiceprint(client.upload(str(wav)))
            voiceprints[name] = wait(client, job, f"voiceprint {name}")["output"]["voiceprint"]
        prints_path.write_text(json.dumps(voiceprints))
        print(f"{len(voiceprints)} voiceprints -> {prints_path}")

    out_path = CACHE / f"{a.video_id}_{a.mode}{'_exclusive' if a.exclusive else ''}.json"
    if out_path.exists():
        print(f"{out_path} already exists -- delete it to re-run and spend trial hours")
        result = json.loads(out_path.read_text())
    else:
        src = AUDIO / f"{a.video_id}.m4a"
        print(f"uploading {src.name} ({src.stat().st_size/1e6:.0f} MB)", flush=True)
        media = client.upload(str(src))
        if a.mode == "identify":
            if not voiceprints:
                sys.exit("identify needs voiceprints -- run with --enroll-from first")
            # TWO DIFFERENT FLAGS, and confusing them wastes a run. `exclusive_matching`
            # forces every segment onto one of the enrolled voiceprints; `exclusive` asks
            # for non-overlapping output. Only the first is the "no unknown speakers"
            # switch, and it already defaults to True.
            job = client.identify(media, voiceprints=voiceprints,
                                  exclusive_matching=not a.allow_unknown,
                                  num_speakers=a.num_speakers)
        else:
            job = client.diarize(media, num_speakers=a.num_speakers)
        result = wait(client, job, a.mode, poll=30)
        out_path.write_text(json.dumps(result, indent=1))
        print(f"-> {out_path}")

    # `identify` returns BOTH lists: `diarization` holds anonymous SPEAKER_NN and
    # `identification` holds the same segments carrying the enrolled name. Reading the
    # first one silently throws away the entire point of enrolling.
    out = result.get("output") or {}
    segs = out.get("identification") or out.get("diarization") or []
    for v in out.get("voiceprints", []):
        c = v.get("confidence", {})
        ranked = sorted(c.values(), reverse=True)
        margin = ranked[0] - ranked[1] if len(ranked) > 1 else ranked[0]
        print(f"  {v['speaker']} -> {v['match']:10} confidence {c}, margin {margin}")
    rttm = CACHE / f"{a.video_id}_{a.mode}{'_exclusive' if a.exclusive else ''}.rttm"
    with open(rttm, "w") as f:
        for s in segs:
            start, end = float(s["start"]), float(s["end"])
            who = s.get("speaker") or s.get("label") or "UNK"
            f.write(f"SPEAKER {a.video_id} 1 {start:.2f} {end-start:.2f} "
                    f"<NA> <NA> {who} <NA> <NA>\n")
    total = defaultdict(float)
    for s in segs:
        total[s.get("speaker") or s.get("label")] += float(s["end"]) - float(s["start"])
    print(f"{len(segs)} segments, {len(total)} speakers -> {rttm}")
    for n, v in sorted(total.items(), key=lambda kv: -kv[1]):
        print(f"    {str(n):12} {v/60:7.1f} min")


if __name__ == "__main__":
    main()
