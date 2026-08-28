"""Heuristic check: compare Malay function-word density in raw.md vs interview.md
to flag episodes where the clean rewrite likely over-anglicized a mixed transcript."""
import re
from pathlib import Path

MALAY_MARKERS = {
    "yang", "dan", "tak", "kita", "ini", "ada", "dia", "tu", "kat", "macam",
    "boleh", "itu", "juga", "kalau", "saya", "kena", "nak", "dah", "lah",
    "ke", "pun", "sebab", "orang", "apa", "sikit", "aku", "kau", "je",
}


def malay_ratio(text):
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if not words:
        return 0.0
    hits = sum(1 for w in words if w in MALAY_MARKERS)
    return hits / len(words)


def strip_frontmatter(text):
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return text


def main():
    """Behind a guard: qa_check.py imports malay_ratio/strip_frontmatter from here
    via check_published.py, and an unguarded module body printed this whole report
    into the middle of the QA summary."""
    episodes_dir = Path(__file__).parent.parent / "episodes"
    rows = []
    for ep_dir in sorted(episodes_dir.glob("*/*")):
        raw_path = ep_dir / "raw.md"
        interview_path = ep_dir / "interview.md"
        if not raw_path.exists() or not interview_path.exists():
            continue
        raw_text = strip_frontmatter(raw_path.read_text(encoding="utf-8"))
        interview_text = strip_frontmatter(interview_path.read_text(encoding="utf-8"))
        r_raw = malay_ratio(raw_text)
        r_interview = malay_ratio(interview_text)
        drop = r_raw - r_interview
        rows.append((drop, ep_dir.name, r_raw, r_interview))

    rows.sort(reverse=True)
    print(f"{'drop':>7} {'raw%':>6} {'interview%':>11}  episode")
    for drop, name, r_raw, r_interview in rows:
        flag = "  <-- CHECK" if drop > 0.05 else ""
        print(f"{drop*100:6.1f}% {r_raw*100:5.1f}% {r_interview*100:10.1f}%  {name}{flag}")


if __name__ == "__main__":
    main()
