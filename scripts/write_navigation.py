"""Give every transcript file a header that says where it is, and index each run folder.

WHY. Google indexes the transcript files directly. On 2026-09-10 the second result for
"yang berhenti menteri transcript" was titled just `raw.md`, and a visitor clicking it landed
in a three-hour transcript with no episode name, no date and no way back to the rest of the
archive. The files are the front door for most arrivals, so each one has to introduce itself.

WHAT IT WRITES, and both are safe to re-run:

  1. A navigation block in every raw.md and interview*.md, between the frontmatter and the
     file's own H1. It carries the show name, the episode number, the title, the date, the
     length, a link to the video, links to the episode's other three files, and links back to
     the archive. The block sits ABOVE the `# Raw Transcript` heading on purpose: fourteen
     scripts read the body by splitting on that heading, so nothing downstream sees this.
  2. A README.md in each of the two run folders. GitHub renders a folder's README under its
     file list, so `episodes/yang-berhenti-menteri/` stops being 63 unexplained folder names.

The block is delimited by HTML comments, which GitHub does not render, so a second run
replaces it exactly instead of stacking copies.

A REBUILD WIPES IT. `mai_camera_raw.py` writes a fresh body, so this runs last, after every
other step -- `adopt_mai_camera_raw.py` does that. The transcript itself is never touched:
the words below the H1 are asserted identical before anything is written.

  python scripts/write_navigation.py            # report
  python scripts/write_navigation.py --write
"""
import argparse
import glob
import io
import os
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START, END = "<!-- nav -->", "<!-- /nav -->"
NAV = re.compile(re.escape(START) + r".*?" + re.escape(END) + r"\s*", re.S)
FILES = [("raw.md", "verbatim raw transcript"),
         ("interview.md", "interview, original mixed language"),
         ("interview-en.md", "interview in English"),
         ("interview-ms.md", "interview in Bahasa Melayu")]
RUNS = {"yang-berhenti-menteri": ("Yang Berhenti Menteri", "2025 rename onward"),
        "yang-bakar-menteri": ("Yang Bakar Menteri", "the 2024 run")}


def field(text, name):
    m = re.search(rf"^{name}:\s*(.+)$", text, re.M)
    if not m:
        return ""
    return m.group(1).strip().strip("'\"")


def pretty_date(iso):
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        return date(y, m, d).strftime("%d %B %Y").lstrip("0")
    except ValueError:
        return iso


def clean_title(title):
    """The YouTube title repeats the episode number and carries a pipe.

    The pipe is not cosmetic: an unescaped one inside a markdown table cell ends the cell,
    so the generated run index rendered as a broken table on its first run.
    """
    title = re.sub(r"\s*\|\s*YBM(\s*EP)?\s*#?\s*\d+\s*$", "", title.strip().rstrip("'"))
    return title.replace("|", "-").strip(" -")


def episode_meta(folder):
    raw = os.path.join(folder, "raw.md")
    head = io.open(raw, encoding="utf-8").read(1500)
    run = Path(folder).parent.name
    number = re.search(r"-ep(\d+)-", folder)
    return {
        "folder": folder,
        "run": run,
        "show": RUNS.get(run, (run, ""))[0],
        "number": number.group(1).lstrip("0") if number else "",
        "title": clean_title(field(head, "title")),
        "date": field(head, "publish_date"),
        "duration": field(head, "duration"),
        "url": field(head, "youtube_url"),
    }


def block_for(meta, current):
    others = " · ".join(
        (f"**{label}**" if name == current else f"[{label}]({name})")
        for name, label in FILES
        if os.path.exists(os.path.join(meta["folder"], name)))
    return (f"{START}\n"
            f"**{meta['show']} episode {meta['number']} — {meta['title']}**  \n"
            f"{pretty_date(meta['date'])} · {meta['duration']} · "
            f"[watch on YouTube]({meta['url']})\n\n"
            f"This episode: {others}  \n"
            f"The archive: [all episodes](../../../README.md) · "
            f"[in Bahasa Melayu](../../../README.ms.md) · "
            f"[how these were made](../../../METHODOLOGY.md) · "
            f"[this run](../README.md)\n"
            f"{END}\n\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    metas, touched = [], 0
    for folder in sorted(glob.glob(str(ROOT / "episodes/*/*/"))):
        if not os.path.exists(os.path.join(folder, "raw.md")):
            continue
        meta = episode_meta(folder)
        metas.append(meta)
        for name, _ in FILES:
            path = Path(folder) / name
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            body = NAV.sub("", text)
            head, sep, rest = body.partition("\n# ")
            if not sep:
                print(f"  no H1 in {path.relative_to(ROOT)}, skipped")
                continue
            fresh = head.rstrip("\n") + "\n\n" + block_for(meta, name) + "# " + rest
            if fresh == text:
                continue
            touched += 1
            if a.write:
                assert NAV.sub("", fresh).split("\n# ", 1)[1] == rest, "transcript changed"
                path.write_text(fresh, encoding="utf-8")

    # One index per run folder.
    for run, (show, note) in RUNS.items():
        rows = [m for m in metas if m["run"] == run]
        if not rows:
            continue
        rows.sort(key=lambda m: m["date"], reverse=True)
        lines = [f"# {show} — transcripts",
                 "",
                 f"{len(rows)} episodes, {note}, newest first. Every episode folder holds the "
                 "verbatim raw transcript and three interview edits: the original mixed "
                 "Malay/English, one in English, one in Bahasa Melayu.",
                 "",
                 "Back to [the whole archive](../../README.md) · "
                 "[Bahasa Melayu](../../README.ms.md) · "
                 "[how these were made](../../METHODOLOGY.md)",
                 "",
                 "| Ep | Date | Title | Length | Transcripts |",
                 "|---|---|---|---|---|"]
        for m in rows:
            folder = Path(m["folder"]).name
            links = " · ".join(
                f"[{'raw' if n == 'raw.md' else n[10:-3].strip('-') or 'mixed'}]({folder}/{n})"
                for n, _ in FILES if os.path.exists(os.path.join(m["folder"], n)))
            lines.append(f"| {m['number']} | {m['date']} | [{m['title']}]({folder}/) "
                         f"| {m['duration']} | {links} |")
        out = "\n".join(lines) + "\n"
        path = ROOT / "episodes" / run / "README.md"
        if not path.exists() or path.read_text(encoding="utf-8") != out:
            touched += 1
            if a.write:
                path.write_text(out, encoding="utf-8")

    print(f"{len(metas)} episodes, {touched} file(s) "
          + ("written" if a.write else "would change -- pass --write"))


if __name__ == "__main__":
    main()
