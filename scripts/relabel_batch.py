"""Relabel every episode the owner has not corrected, into REVIEW COPIES, and write one report.

Owner's decision 2026-10-18: Nemotron 3 labels the older episodes too, the owner's rulings stay
locked (voice_label_raw.py), and nothing published changes until the owner has read the report.
Each copy goes to data/_relabel/<tag>/raw.md beside the untouched original, and REPORT.md lists
every episode by the share of words whose speaker changed, with the largest changes as ?t= links.

    python scripts/relabel_batch.py            # every episode, skipping finished ones
    python scripts/relabel_batch.py ep33 ep40  # just these
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "_relabel"
GOLD = {"ep65", "ep66", "ep67", "ep68"}          # the owner's own corrections; never relabelled
TURN = re.compile(r"^\[([\d:]+)\]\s*([^:\n\[\]]{1,40}?):\s*(.*)$")
SHOW = {"yang-bakar-menteri": "bakar", "yang-berhenti-menteri": "berhenti", "siri-forum-bersama": "forum"}


def episodes():
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    tags = []
    for e in manifest:
        m = re.search(r"-(ep\d+)-", common.episode_slug(e))
        if m:
            tags.append((m.group(1), SHOW[common.show_era_dir(e)], e["video_id"]))
    count = {}
    for t, _, _ in tags:
        count[t] = count.get(t, 0) + 1
    return [(t if count[t] == 1 else f"{t}:{s}", s, v) for t, s, v in tags
            if not (s == "berhenti" and t in GOLD)]


def words(path):
    out = []
    for line in path.read_text(encoding="utf-8").split("# Raw Transcript", 1)[1].splitlines():
        m = TURN.match(line.strip())
        if m:
            h = [int(x) for x in m.group(1).split(":")]
            sec = h[0] * 3600 + h[1] * 60 + h[2] if len(h) == 3 else h[0] * 60 + h[1]
            out += [(m.group(2).strip(), w, sec) for w in m.group(3).split()]
    return out


def changes(old, new):
    """Runs of words whose label changed: (start second, words, old label, new label)."""
    runs, cur = [], None
    for (a, w, _), (b, _, s) in zip(old, new):
        if a != b:
            if cur and cur[2] == a and cur[3] == b:
                cur[1] += 1
            else:
                cur = [s, 1, a, b]
                runs.append(cur)
        else:
            cur = None
    return runs


def main():
    only = sys.argv[1:]
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for tag, show, vid in episodes():
        if only and tag not in only and tag.split(":")[0] not in only:
            continue
        d = OUT / common.artifact_tag(tag)
        d.mkdir(exist_ok=True)
        orig, copy, log = d / "raw_before.md", d / "raw.md", d / "log.txt"
        if not (ROOT / "data" / f"_mai_{vid}" / "mai_words.json").exists():
            subprocess.run([sys.executable, str(ROOT / "scripts" / "mai_words_from_responses.py"),
                            tag, "--write"], cwd=ROOT)
        if not (copy.exists() and "label changed" in (log.read_text(encoding="utf-8") if log.exists() else "")):
            shutil.copy(common.raw_for_tag(tag), orig)
            shutil.copy(orig, copy)
            print(f"== {tag}", flush=True)
            r = subprocess.run([sys.executable, str(ROOT / "scripts" / "voice_label_raw.py"), tag,
                                "--raw", str(copy), "--write"], cwd=ROOT, capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
            log.write_text(r.stdout + r.stderr, encoding="utf-8")
            if r.returncode:
                print(f"   FAILED: {(r.stdout + r.stderr).strip().splitlines()[-1:]}", flush=True)
        text = log.read_text(encoding="utf-8") if log.exists() else ""
        m = re.search(r"label changed (\d+) \(([\d.]+)%\)", text)
        if not m:
            rows.append((tag, vid, None, text.strip().splitlines()[-1:] or ["no log"], [], ""))
            continue
        old, new = words(orig), words(copy)
        runs = sorted(changes(old, new), key=lambda r: -r[1])[:10]
        spk = re.search(r"words per speaker: (.*)", text)
        rows.append((tag, vid, float(m.group(2)), int(m.group(1)), runs, spk.group(1) if spk else ""))
        print(f"   {tag}: {m.group(2)}% of words changed speaker", flush=True)

    def link(vid, s):
        return f"https://youtu.be/{vid}?t={max(0, s - 5)}"

    lines = ["# Nemotron relabel: review report", "",
             "Review copies only. Published raw.md files are unchanged. Owner's rulings are locked.", "",
             "| episode | words changed | speakers after |", "|---|---|---|"]
    done = sorted([r for r in rows if r[2] is not None], key=lambda r: -r[2])
    for tag, vid, pct, n, runs, spk in done:
        lines.append(f"| {tag} | {n} ({pct:.1f}%) | {spk} |")
    for tag, vid, pct, n, runs, spk in [r for r in rows if r[2] is None]:
        lines.append(f"| {tag} | FAILED: {' '.join(n)} | |")
    for tag, vid, pct, n, runs, spk in done:
        lines += ["", f"## {tag}: {pct:.1f}%", ""]
        for s, k, a, b in runs:
            lines.append(f"- [{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}]({link(vid, s)}) "
                         f"{k} words: {a} -> {b}")
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT / 'REPORT.md'}")


if __name__ == "__main__":
    main()
