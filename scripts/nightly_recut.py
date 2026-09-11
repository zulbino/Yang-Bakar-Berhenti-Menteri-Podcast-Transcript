"""Unattended, per-episode evidence gathering for the attribution re-cut. Writes NOTHING to episodes/.

WHY. Re-cutting one episode by hand cost a session of reading and steering, and the corpus has
68. The compute is free (one GPU, prepaid Azure credit); the expensive part is a person or a
model reading each step. So every step here runs unattended and leaves a compact report, and
the morning's work is reading data/_nightly/summary.md, not running tools.

WHAT IT PRODUCES per episode, newest first, stopping before a new GPU stage would pass the
deadline:

  audio/<vid>.m4a                     downloaded if missing
  data/_mai_<vid>/                    MAI-Transcribe-2 word times (network thread, in parallel)
  data/diar_<vid>_t055.json           pyannote clusters at threshold 0.55 (GPU)
  data/_camera_tracks_<vid>/          LR-ASD + face tracks, per-episode dir (GPU, the slow one)
  data/camera_ref_<tag>.rttm/.uem     camera speaker reference
  data/_nightly/<tag>.json            every step's status, seconds, and output tail
  data/_nightly/summary.md            one table row per episode

The 480p video is deleted after the camera run. The split tool runs as a DRY RUN against
the camera reference and its report is captured; whether to write is a morning decision,
taken after reading the diff, never by this script.

  python scripts/nightly_recut.py ep61 ep60 ep59 ep58 --hours 9
"""
import argparse
import glob
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import yt_download  # noqa: E402

NIGHTLY = ROOT / "data" / "_nightly"
VIDEO_DIR = ROOT / "data" / "_video"
PY = sys.executable


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def run(cmd, tail=2500, **kw):
    """Run a subprocess, return (ok, combined output tail)."""
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", **kw)
    out = (r.stdout or "") + (("\nSTDERR:\n" + r.stderr) if r.stderr.strip() else "")
    return r.returncode == 0, out[-tail:]


def resolve(tag, manifest):
    hits = glob.glob(str(ROOT / f"episodes/*/*-{tag}-*/raw.md"))
    if len(hits) != 1:
        raise SystemExit(f"{tag}: {len(hits)} raw.md matches, need exactly 1: {hits}")
    head = io.open(hits[0], encoding="utf-8").read(4000)
    vid = re.search(r"video_id:\s*(\S+)", head).group(1)
    dur = next(e["duration_seconds"] for e in manifest if e["video_id"] == vid)
    return Path(hits[0]).parent, vid, dur


def step(report, name, fn):
    t0 = time.time()
    try:
        ok, out = fn()
    except Exception as e:  # a failed step is recorded, not raised: the next episode still runs
        ok, out = False, f"{type(e).__name__}: {e}"
    report["steps"][name] = {"ok": ok, "seconds": round(time.time() - t0), "out": out}
    log(f"  {name}: {'ok' if ok else 'FAILED'} in {(time.time() - t0) / 60:.1f} min")
    return ok


def ensure_audio(vid):
    p = ROOT / "audio" / f"{vid}.m4a"
    if p.exists():
        return True, "present"
    yt_download.download_audio(vid, ROOT / "audio")
    return p.exists(), f"downloaded {p.stat().st_size / 1e6:.0f} MB" if p.exists() else "download failed"


def mai(vid):
    out = ROOT / "data" / f"_mai_{vid}"
    if (out / "mai_phrases.json").exists():
        return True, "present"
    out.mkdir(parents=True, exist_ok=True)
    mp3 = out / f"{vid}.64k.mono.mp3"
    if not mp3.exists():
        ok, o = run([str(yt_download._ffmpeg_location()), "-v", "error", "-y",
                     "-i", str(ROOT / "audio" / f"{vid}.m4a"), "-ac", "1", "-b:a", "64k", str(mp3)])
        if not ok:
            return False, "transcode failed: " + o
    return run([PY, "scripts/transcribe_mai.py", vid], cwd=ROOT)


def diarize(vid):
    p = ROOT / "data" / f"diar_{vid}_t055.json"
    if p.exists():
        return True, "present"
    code = (
        "import sys,os; os.environ.setdefault('CUDA_VISIBLE_DEVICES','0'); sys.path.insert(0,'scripts')\n"
        "import reattribute_blocks as rb, lib_local_asr, soundfile as sf\n"
        "from pathlib import Path\n"
        f"wav = lib_local_asr._decode_to_wav(Path(r'{ROOT / 'audio' / (vid + '.m4a')}'))\n"
        "audio, sr = sf.read(str(wav), dtype='float32')\n"
        f"segs = rb.cached_diarization('{vid}', audio, sr, None, 0.55)\n"
        "import collections; c=collections.Counter(s[2] for s in segs)\n"
        "print(len(segs),'turns; clusters',dict(c))\n"
    )
    return run([PY, "-c", code], cwd=ROOT)


def video(vid):
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    p = VIDEO_DIR / f"{vid}_480p.mp4"
    if p.exists():
        return True, "present"
    yt_download.ensure_pot_server()
    # Format 135 (854x480 avc1) so the LR-ASD scores stay comparable with the validated ep62 run.
    ok, out = run([PY, "-m", "yt_dlp", "-f", "135/bestvideo[height<=480][ext=mp4]", "--quiet",
                   "--no-warnings", "--js-runtimes", f"node:{yt_download._node_path()}",
                   "--extractor-args", "youtube:player_client=web_embedded",
                   "--ffmpeg-location", str(yt_download._ffmpeg_location()),
                   "-o", str(p), f"https://www.youtube.com/watch?v={vid}"])
    return p.exists(), out or f"{p.stat().st_size / 1e6:.0f} MB"


def camera_run(vid):
    return run([PY, "scripts/camera_speakers.py", "run", str(VIDEO_DIR / f"{vid}_480p.mp4"),
                str(ROOT / "audio" / f"{vid}.m4a"), "--out", f"data/_camera_tracks_{vid}"],
               cwd=ROOT)


def cast_check(tag):
    """Refuse a reference that is missing a speaker raw.md says holds real word volume."""
    return run([PY, "scripts/check_camera_reference.py", tag])


def camera_reference(tag, vid, dur):
    return run([PY, "scripts/camera_speakers.py", "reference", vid,
                "--tracks", f"data/_camera_tracks_{vid}", "--out", f"data/camera_ref_{tag}",
                "--runtime", str(dur)], cwd=ROOT)


def split_dry_run(tag):
    return run([PY, "scripts/split_mixed_blocks.py", tag,
                "--reference", f"data/camera_ref_{tag}.rttm"], cwd=ROOT, tail=6000)


def summarize(tag, report):
    st = report["steps"]
    def s(k):
        return "ok" if st.get(k, {}).get("ok") else ("-" if k not in st else "FAIL")
    cov = re.search(r"CONFIDENT \d+s = (\d+%)", st.get("camera_reference", {}).get("out", ""))
    ident = re.search(r"identified \d+ \((\d+%)\)", st.get("camera_reference", {}).get("out", ""))
    sp = st.get("split_dry_run", {}).get("out", "")
    verdict = "REFUSED" if "REFUSING" in sp else ("proposes" if "->" in sp else "-")
    return (f"| {tag} | {s('audio')} | {s('mai')} | {s('diarize')} | {s('camera_run')} | "
            f"{ident.group(1) if ident else '-'} | {cov.group(1) if cov else '-'} | "
            f"{s('split_dry_run')} {verdict} |\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="+")
    ap.add_argument("--hours", type=float, default=9.0,
                    help="do not START a camera run after this many hours")
    ap.add_argument("--skip-mai", action="store_true")
    a = ap.parse_args()

    NIGHTLY.mkdir(parents=True, exist_ok=True)
    manifest = json.load(io.open(ROOT / "data" / "manifest.json", encoding="utf-8"))
    manifest = manifest["episodes"] if isinstance(manifest, dict) else manifest
    began = time.time()
    summary = NIGHTLY / "summary.md"
    if not summary.exists():
        summary.write_text("| episode | audio | MAI | pyannote | camera | faces id'd | UEM cov | split dry run |\n"
                           "|---|---|---|---|---|---|---|---|\n", encoding="utf-8")

    eps = [(t,) + resolve(t, manifest) for t in a.tags]
    for t, d, vid, dur in eps:
        log(f"{t}: {vid} {dur // 60} min  {d.name}")

    # Audio first for everything, so the MAI thread has input for the whole list.
    for t, d, vid, dur in eps:
        ok, out = ensure_audio(vid)
        log(f"{t} audio: {out}")

    mai_done = {t: threading.Event() for t, *_ in eps}
    mai_result = {}

    def mai_worker():
        for t, d, vid, dur in eps:
            t0 = time.time()
            try:
                mai_result[t] = mai(vid) if not a.skip_mai else (True, "skipped")
            except Exception as e:
                mai_result[t] = (False, f"{type(e).__name__}: {e}")
            mai_result[t] = mai_result[t] + (round(time.time() - t0),)
            log(f"  {t} MAI: {'ok' if mai_result[t][0] else 'FAILED'} in {(time.time() - t0) / 60:.0f} min")
            mai_done[t].set()

    threading.Thread(target=mai_worker, daemon=True).start()

    failures = 0
    for t, d, vid, dur in eps:
        report = {"tag": t, "video_id": vid, "duration_s": dur, "steps": {}}
        log(f"=== {t}")
        step(report, "audio", lambda: ensure_audio(vid))
        step(report, "diarize", lambda: diarize(vid))
        if (time.time() - began) / 3600 > a.hours:
            report["steps"]["camera_run"] = {"ok": False, "seconds": 0, "out": "deadline reached, not started"}
            log(f"  deadline reached, skipping camera for {t}")
        else:
            if step(report, "video", lambda: video(vid)):
                if step(report, "camera_run", lambda: camera_run(vid)):
                    step(report, "camera_reference", lambda: camera_reference(t, vid, dur))
                (VIDEO_DIR / f"{vid}_480p.mp4").unlink(missing_ok=True)
        mai_done[t].wait()
        ok, out, secs = mai_result[t]
        report["steps"]["mai"] = {"ok": ok, "seconds": secs, "out": out[-2500:]}
        # The split tool falls back to the caption track as its word clock, so it runs
        # whenever there is a camera reference, MAI or not.
        # Gate the reference on its CAST before anything consumes it. ep33's pass produced
        # a plausible reference -- 71% coverage, 400 segments -- that gave its guest Wong
        # Chen 0.0% of the time while raw.md gives him 20.1% of the words, because the face
        # gallery holds only the three regulars and his face was handed to the nearest
        # member. DER was 11.9%, which passes; JER was 48.1%. Three references already on
        # disk fail the same way (ep50, ep52, ep55).
        if report["steps"].get("camera_reference", {}).get("ok"):
            step(report, "camera_reference_cast", lambda: cast_check(t))
            if report["steps"]["camera_reference_cast"]["ok"]:
                step(report, "split_dry_run", lambda: split_dry_run(t))
            else:
                log(f"  {t}: reference REFUSED on cast, skipping the split dry run")
        failures += sum(1 for v in report["steps"].values() if not v["ok"])
        (NIGHTLY / f"{t}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        with summary.open("a", encoding="utf-8") as f:
            f.write(summarize(t, report))
        log(f"=== {t} done, {(time.time() - began) / 3600:.1f} h elapsed")

    log(f"finished: {failures} failed step(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
