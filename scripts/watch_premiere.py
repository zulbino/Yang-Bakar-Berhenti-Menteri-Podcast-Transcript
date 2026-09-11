"""Wait for a YouTube premiere to finish, then run the safe first half of the pipeline.

WHY NOT TRANSCRIBE IT LIVE, which is the question this answers. A premiere is a
PRE-RECORDED file played out on a schedule, so there is no live audio to capture: probing
GJyo38Kmyt8 returns "Premieres in 91 minutes" rather than a live manifest. Capturing it as
it airs would take the full runtime, about three hours at 1x. Downloading the finished file
took 0.6 min on ep33 and 1.0 min on ep41, measured 2026-09-11. Live capture is therefore
roughly 180x slower for a byte-identical result.

Nor is there anything to capture WITH. No script in this repo has a real-time mode --
zero matches for realtime, websocket or continuous_recognition. MAI is wired to the batch
`transcriptions:transcribe` endpoint and already 503s above ~30 minutes of audio, and the
Gemini path has recorded billing blockers. Everything that gives this pipeline its value
needs the complete file anyway: the camera pass, MAI's word timings, and the caption track.

So the useful thing is not speed of transcription, it is not being asleep at the moment the
file becomes available. This polls, then runs the steps that are safe unattended.

WHERE IT DELIBERATELY STOPS. It does NOT run the camera pass, and that is today's lesson
rather than caution for its own sake. On 2026-09-11 a full 152-minute pass on ep33 produced
a reference that gave its guest Wong Chen 0.0% of the time against 20.1% of raw's words,
because the face gallery holds only the three regulars. Three references already on disk
fail the same way. The cast is not known until the transcript exists, so the camera pass
has to wait for a human to look at who is in the episode. The script prints the cast and
stops.

It also uses --engine local rather than Gemini. On ep61 the Gemini raw looped 92% of the
episode while its last timestamp still matched the runtime, so it looked complete and was
about seven minutes of real content stretched over three hours. qa_check.py caught it. That
is why qa_check runs here before anything is believed.

  python scripts/watch_premiere.py GJyo38Kmyt8
  python scripts/watch_premiere.py GJyo38Kmyt8 --poll 300 --max-hours 10
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "manifest.json"
PY = sys.executable
LOG = ROOT / "data" / "_premiere_watch.out"


def say(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def probe(video_id):
    """(available, info). A premiere reports is_upcoming and raises on extract."""
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(f"https://www.youtube.com/watch?v={video_id}",
                                  download=False)
    except Exception as e:
        return False, str(e)[:200]
    status = info.get("live_status")
    # is_upcoming = not started. is_live = airing, so the file is not complete yet.
    # post_live = just finished and still being processed; duration is trustworthy by then.
    if status in ("is_upcoming", "is_live"):
        return False, f"live_status={status}"
    if not info.get("duration"):
        return False, "no duration yet"
    return True, info


def add_to_manifest(info):
    """A premiere is often not in the playlist yet, so build_manifest would not see it."""
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if any(r["video_id"] == info["id"] for r in rows):
        say("already in the manifest")
        return
    rows.append({
        "video_id": info["id"],
        "title": info.get("title"),
        "youtube_url": f"https://www.youtube.com/watch?v={info['id']}",
        "upload_date": info.get("upload_date"),
        "duration_seconds": int(info.get("duration") or 0),
        "view_count": info.get("view_count") or 0,
        "channel": info.get("channel"),
        "description": info.get("description") or "",
    })
    MANIFEST.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    say(f"appended to the manifest: {info.get('title')} "
        f"({int(info.get('duration') or 0) // 60} min)")


def run(label, cmd):
    say(f"--- {label}: {' '.join(str(c) for c in cmd)}")
    t0 = time.time()
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = ((r.stdout or "") + (("\nSTDERR:\n" + r.stderr) if r.stderr.strip() else ""))[-1500:]
    say(f"--- {label}: {'ok' if r.returncode == 0 else 'FAILED'} in "
        f"{(time.time() - t0) / 60:.1f} min\n{tail}")
    return r.returncode == 0


def cast_of(video_id):
    import re
    from collections import Counter
    hits = list(ROOT.glob(f"episodes/*/*/raw.md"))
    for p in hits:
        if video_id in p.read_text(encoding="utf-8")[:2000]:
            names = Counter(re.findall(r"^\[[\d:]+\]\s*([^:\n]{1,40}?):",
                                       p.read_text(encoding="utf-8"), re.M))
            return p, names
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--poll", type=int, default=300, help="seconds between probes")
    ap.add_argument("--max-hours", type=float, default=12.0)
    a = ap.parse_args()

    say(f"watching {a.video_id}; it is a premiere, so nothing exists to fetch until it ends")
    deadline = time.time() + a.max_hours * 3600
    info = None
    while time.time() < deadline:
        ok, res = probe(a.video_id)
        if ok:
            info = res
            say(f"available: {info.get('title')} "
                f"({int(info.get('duration') or 0) // 60} min, "
                f"live_status={info.get('live_status')})")
            break
        say(f"not ready ({res})")
        time.sleep(a.poll)
    if not info:
        say("gave up waiting")
        return 1

    add_to_manifest(info)
    if not run("audio+raw+rewrite", [PY, "scripts/transcribe_episode.py", a.video_id,
                                     "--engine", "local"]):
        say("transcribe_episode FAILED -- stopping, nothing further is safe unattended")
        return 1
    # Always, and before believing the transcript: ep61's looped raw ended at the right
    # timestamp and was 92% duplicate.
    run("qa_check", [PY, "scripts/qa_check.py"])

    path, names = cast_of(a.video_id)
    if names:
        say(f"cast in {path.parent.name}:")
        for n, c in names.most_common():
            say(f"    {n:<24}{c:>5} blocks")
        regulars = {"rafizi", "haziq", "farhan (pa'an)"}
        guests = [n for n in names if n.strip().lower() not in regulars
                  and not n.strip().lower().startswith(("speaker", "multiple"))]
        if guests:
            say(f"GUEST(S) PRESENT: {', '.join(guests)}. Do NOT run the camera pass until "
                f"the face gallery has them enrolled -- an unenrolled guest is handed to the "
                f"nearest gallery member, which is how ep33's reference gave Wong Chen 0% "
                f"and Rafizi 93.8%. See data/camera_reference_limits.json.")
        else:
            say("no guests: the three regulars only, so the camera pass is safe to run.")
    say("done. The camera pass is deliberately NOT started.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
