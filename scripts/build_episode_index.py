"""Regenerate EPISODES.md from the episode frontmatter.

The index exists for two reasons. It gives a reader one page listing every episode, and
it gives crawlers a path to the transcripts: GitHub's robots.txt blocks `/*/tree/` and
`/*/raw/` but not `/*/blob/`, so a folder listing is not crawlable while these links are.

Guests come from the `guests` frontmatter, which `data/_roster.py` derives from the
`raw.md` speaker labels. Co-hosts and the producer are never listed here -- that field
holds actual guests only.

  python scripts/build_episode_index.py
"""
import glob
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "EPISODES.md"
SERIES = [
    ("yang-bakar-menteri", "Yang Bakar Menteri", "{n} episodes, 2024 run."),
    ("yang-berhenti-menteri", "Yang Berhenti Menteri", "{n} episodes, 2025 rename onward."),
]
FIELD_RE = {k: re.compile(rf"^{k}:\s*(.*)$", re.M)
            for k in ("title", "youtube_url", "publish_date", "duration")}
LIST_RE = {key: re.compile(rf"^{key}:\s*(\[\]|\n(?:- .*\n)*)", re.M)
           for key in ("hosts", "guests")}


def cell(text):
    """Escape what would otherwise break out of a markdown table cell."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def read_fields(path):
    text = path.read_text(encoding="utf-8")
    frontmatter = text.split("---", 2)[1]
    out = {}
    for key, pattern in FIELD_RE.items():
        m = pattern.search(frontmatter)
        out[key] = (m.group(1).strip().strip("'\"") if m else "")
    for key, pattern in LIST_RE.items():
        m = pattern.search(frontmatter)
        out[key] = re.findall(r"- (.+)", m.group(1)) if m else []
    return out


def episode_rows(series_dir):
    rows = []
    for d in glob.glob(str(ROOT / "episodes" / series_dir / "*")):
        d = Path(d)
        interview = d / "interview.md"
        raw = d / "raw.md"
        if not raw.exists():
            continue
        # interview.md carries hosts/guests; fall back to raw.md for the rest
        fields = read_fields(interview if interview.exists() else raw)
        if not fields["title"]:
            fields.update({k: v for k, v in read_fields(raw).items() if v})
        number = re.search(r"-ep(\d+)-", d.name).group(1)
        rel = f"episodes/{series_dir}/{d.name}"
        links = " · ".join(
            f"[{label}]({rel}/{name})" for label, name in
            (("raw", "raw.md"), ("mixed", "interview.md"),
             ("EN", "interview-en.md"), ("MS", "interview-ms.md"))
            if (d / name).exists())
        rows.append((
            fields["publish_date"], number,
            f"| {number} | {fields['publish_date']} | "
            f"[{cell(fields['title'])}]({fields['youtube_url']}) | "
            f"{fields['duration']} | {cell(', '.join(fields['hosts']))} | "
            f"{cell(', '.join(fields['guests']))} | {links} |"))
    rows.sort(reverse=True)  # newest first
    return [r[2] for r in rows]


def main():
    blocks, total = [], 0
    for series_dir, heading, blurb in SERIES:
        rows = episode_rows(series_dir)
        if not rows:
            continue
        total += len(rows)
        blocks.append(f"## {heading}\n\n{blurb.format(n=len(rows))}\n\n"
                      "| Ep | Date | Title | Length | Hosts | Guests | Transcripts |\n"
                      "|---|---|---|---|---|---|---|\n" + "\n".join(rows))

    header = (
        "# Episode index\n\n"
        "Every episode, newest first, with direct links to all four transcript files.\n\n"
        f"{total} episodes. `raw` is the close-to-verbatim transcript,\n"
        "`mixed` keeps the original code-switched English and Bahasa Melayu, and `EN` / `MS` are\n"
        "the full translations. See the [README](README.md) for what each file is, and the\n"
        "[accuracy note](README.md#accuracy-note) before citing anything.\n\n"
        "Rafizi hosts throughout. Haziq and Farhan (Pa'an) are the regular co-hosts, and\n"
        "Iqbal, Wan Afiq and Amir Sahmat stood in on the episodes where a regular could not\n"
        "make it. The Guests column lists guests only, never the cast.\n\n"
        "This column reports what each transcript actually names, so it under-reports rather\n"
        "than guesses. Where it shows Rafizi alone, a co-host is usually present in the audio\n"
        "but was never named in that episode; where it is empty, that episode carries no\n"
        "speaker labels at all, because its diarization collapsed and a wrong name would have\n"
        "been worse than none. Both cases are covered in\n"
        "[ARCHITECTURE.md](ARCHITECTURE.md#known-limitations).\n")

    OUT_PATH.write_text(header + "\n" + "\n\n".join(blocks) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH.relative_to(ROOT)}: {total} episodes")


if __name__ == "__main__":
    main()
