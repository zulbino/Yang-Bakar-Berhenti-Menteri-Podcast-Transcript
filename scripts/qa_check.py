"""Audit all episodes for known pipeline failure signatures and write a checklist.

Checks per episode:
  - raw.md exists and has sane [MM:SS] timestamp coverage vs duration_seconds
    (catches incomplete transcription and hallucinated runaway timestamps)
  - raw.md has real paragraph breaks between turns, not one wall-of-text block
    (catches the missing-"\n\n" bug that silently bypasses chunking)
  - interview.md / interview-en.md / interview-ms.md exist and are not
    disproportionately short vs raw.md (catches the resulting truncated rewrite)
  - raw.md doesn't contain leaked model reasoning ("the prompt") or backtick-
    wrapped timestamps in place of real transcript content
  - raw.md uses "[MM:SS] Speaker: text" on one line consistently, not split
    across two lines
  - interview.md / interview-ms.md actually contain Malay content when their
    own frontmatter claims language: mixed/ms (catches the rewrite stage
    silently translating everything to English instead of preserving it)
  - cross-references data/manifest.json to list episodes with no episodes/
    folder yet (never run through the pipeline at all)

Usage:
  python scripts/qa_check.py            # writes QA_CHECKLIST.md
"""
import json
import re
from pathlib import Path

from common import episode_slug
from lib_gemini import MODEL_FALLBACK_CHAIN

ROOT = Path(__file__).resolve().parent.parent
EPISODES_DIR = ROOT / "episodes"
MANIFEST_PATH = ROOT / "data" / "manifest.json"
OUT_PATH = ROOT / "QA_CHECKLIST.md"

TIMESTAMP_RE = re.compile(r"\[(?:(\d+):)?(\d+):(\d+)\]")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

MIN_COVERAGE_PCT = 95
MAX_COVERAGE_PCT = 150
MAX_BLOCK_CHARS = 20_000  # a single real speaker turn is never this long
MIN_INTERVIEW_RATIO = 0.35  # interview.md chars / raw.md chars, calibrated against known-good episodes (0.74-0.93)

# Signature of a specific failure mode: the model gets stuck second-guessing its
# own timestamp count and leaks its reasoning into the transcript instead of
# producing one (e.g. "Wait, let me look at the text of the prompt again..."),
# usually replacing the episode's opening minutes with backtick-wrapped
# timestamps instead of the normal [MM:SS] format. Coverage/wall-of-text checks
# miss it since the transcript recovers into normal content later on.
# "let me (read|look at)" alone false-positived on real speakers reading a
# social media post aloud mid-interview -- require the "prompt" self-reference
# or the backtick timestamp format, not generic hedging phrases.
LEAKED_REASONING_RE = re.compile(r"\bthe (?:user'?s )?prompt\b", re.IGNORECASE)
BACKTICK_TIMESTAMP_RE = re.compile(r"`(?:\d{1,2}:)?\d{2}:\d{2}`")

# Standard turn format is "[MM:SS] Speaker: text" on one line. Some episodes
# split the timestamp onto its own line with "Speaker: text" following on the
# next -- content is intact, just non-standard. Require a real speaker label
# on the next line so this doesn't also fire on unrelated corruption that
# happens to leave standalone [MM:SS] lines with no speaker/text at all.
SPLIT_TIMESTAMP_RE = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]\s*\n(?=[A-Z][\w .'-]{0,40}:\s)", re.M)

# The rewrite stage sometimes ignores its own instruction to preserve
# code-switching and translates a "mixed" or "ms" file into plain English
# instead -- confirmed on several episodes by comparing against a genuinely
# mixed raw.md. Length-based truncation checks miss this since translating
# doesn't necessarily shorten the text. Density is calibrated against known
# episodes: real mixed/Malay content scores several to a dozen hits per 1000
# chars; fully English-translated content scores under 0.3.
MALAY_MARKERS = (" yang ", " dan ", " saya ", " kita ", " itu ", " ini ", " tak ", " dengan ", " kepada ", " juga ")
MIN_MALAY_DENSITY = 1.0  # marker hits per 1000 chars, for files claiming language: mixed/ms

MODEL_RE = re.compile(r"^model:\s*(\S+)", re.M)
# Bottom of the fallback chain, only reached once every better model is exhausted or
# down -- confirmed prone to silently dropping code-switched content (see
# lib_gemini.py's MODEL_FALLBACK_CHAIN comment and the language-mistranslation
# writeup). Flag any output file produced by one of these so it gets a closer look
# even when the density/ratio checks above don't catch anything.
WEAK_MODELS = set(MODEL_FALLBACK_CHAIN[6:])


def last_timestamp_seconds(text):
    matches = TIMESTAMP_RE.findall(text)
    if not matches:
        return None
    h, m, s = matches[-1]
    return (int(h) if h else 0) * 3600 + int(m) * 60 + int(s)


def duration_seconds(frontmatter_text):
    m = re.search(r"duration_seconds:\s*(\d+)", frontmatter_text)
    return int(m.group(1)) if m else None


def malay_density(text):
    lowered = text.lower()
    hits = sum(lowered.count(marker) for marker in MALAY_MARKERS)
    return hits / len(lowered) * 1000 if lowered else 0


def check_episode(ep_dir):
    issues = []
    models = {}
    raw_path = ep_dir / "raw.md"
    if not raw_path.exists():
        return ["missing raw.md"], models

    raw_text = raw_path.read_text(encoding="utf-8")
    fm_match = FRONTMATTER_RE.match(raw_text)
    duration = duration_seconds(fm_match.group(1)) if fm_match else None
    body = raw_text[fm_match.end():] if fm_match else raw_text

    raw_model_match = MODEL_RE.search(fm_match.group(1)) if fm_match else None
    if raw_model_match:
        models["raw.md"] = raw_model_match.group(1)
        if models["raw.md"] in WEAK_MODELS:
            issues.append(f"raw.md produced by weaker fallback model {models['raw.md']} -- verify content quality closely")

    if duration:
        covered = last_timestamp_seconds(body)
        if covered is None:
            issues.append("no timestamps found in raw.md")
        else:
            pct = covered / duration * 100
            if pct < MIN_COVERAGE_PCT:
                issues.append(f"raw.md timestamp coverage only {pct:.0f}% (last ts {covered}s of {duration}s)")
            elif pct > MAX_COVERAGE_PCT:
                issues.append(f"raw.md timestamp coverage {pct:.0f}% -- likely hallucinated runaway timestamps")

    blocks = body.split("\n\n")
    max_block = max((len(b) for b in blocks), default=0)
    if max_block > MAX_BLOCK_CHARS:
        issues.append(f"raw.md has a {max_block}-char block with no paragraph breaks (wall-of-text)")

    if LEAKED_REASONING_RE.search(body) or BACKTICK_TIMESTAMP_RE.search(body):
        issues.append("raw.md appears to contain leaked model reasoning/meta-commentary instead of transcript content")

    split_count = len(SPLIT_TIMESTAMP_RE.findall(body))
    if split_count:
        issues.append(f"raw.md has {split_count} turn(s) with '[MM:SS]' and 'Speaker: text' split across two lines instead of one")

    raw_len = len(raw_text)
    for name in ("interview.md", "interview-en.md", "interview-ms.md"):
        path = ep_dir / name
        if not path.exists():
            issues.append(f"missing {name}")
            continue
        interview_text = path.read_text(encoding="utf-8")
        ratio = len(interview_text) / raw_len if raw_len else 0
        if ratio < MIN_INTERVIEW_RATIO:
            issues.append(f"{name} looks truncated (ratio {ratio:.2f} vs raw.md, expected >= {MIN_INTERVIEW_RATIO})")

        model_match = MODEL_RE.search(interview_text)
        if model_match:
            models[name] = model_match.group(1)
            if models[name] in WEAK_MODELS:
                issues.append(f"{name} produced by weaker fallback model {models[name]} -- verify content quality closely")

        lang_match = re.search(r"^language:\s*(\S+)", interview_text, re.M)
        language = lang_match.group(1) if lang_match else None
        if language in ("mixed", "ms"):
            density = malay_density(interview_text)
            if density < MIN_MALAY_DENSITY:
                issues.append(
                    f"{name} claims language: {language} but reads as English-only "
                    f"(Malay-marker density {density:.2f}/1000 chars, expected >= {MIN_MALAY_DENSITY})"
                )

    return issues, models


def format_models(models):
    return "models: " + ", ".join(f"{name}={model}" for name, model in models.items())


def main():
    results = {}
    for ep_dir in sorted(EPISODES_DIR.glob("*/*")):
        if not ep_dir.is_dir():
            continue
        results[ep_dir.name] = check_episode(ep_dir)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    unprocessed = sorted(
        (episode_slug(ep), ep["title"]) for ep in manifest if episode_slug(ep) not in results
    )

    total = len(results)
    broken = {slug: result for slug, result in results.items() if result[0]}

    lines = [
        "# QA Checklist",
        "",
        f"Generated by `scripts/qa_check.py`. {total - len(broken)}/{total} processed episodes clean, "
        f"{len(broken)} flagged, {len(unprocessed)} not yet processed.",
        "",
        "Re-run after any reprocessing batch: `python scripts/qa_check.py`.",
        "",
        "`model:` is only recorded in frontmatter for episodes (re)processed since this "
        "field was added -- older episodes show no model line until reprocessed.",
        "",
    ]
    if broken:
        lines.append("## Flagged episodes")
        lines.append("")
        for slug, (issues, models) in broken.items():
            lines.append(f"- [ ] **{slug}**")
            for issue in issues:
                lines.append(f"  - {issue}")
            if models:
                lines.append(f"  - {format_models(models)}")
        lines.append("")
    if unprocessed:
        lines.append("## Not yet processed")
        lines.append("")
        lines.append("In data/manifest.json but no episodes/ folder yet.")
        lines.append("")
        for slug, title in unprocessed:
            lines.append(f"- [ ] **{slug}** -- {title}")
        lines.append("")
    lines.append("## Clean episodes")
    lines.append("")
    for slug, (issues, models) in results.items():
        if not issues:
            suffix = f" ({format_models(models)})" if models else ""
            lines.append(f"- [x] {slug}{suffix}")
    lines.append("")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_PATH} -- {len(broken)}/{total} flagged, {len(unprocessed)} not yet processed")


if __name__ == "__main__":
    main()
