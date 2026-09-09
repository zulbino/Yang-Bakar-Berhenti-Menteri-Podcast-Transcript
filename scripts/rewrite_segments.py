"""Rewrite an episode segment by segment, gate every segment, retry only the failures.

WHY. Whole-episode rewriting fails in a way no exit code shows: four runs over one raw.md
returned 24%, 32%, 63% and 39% of its length, Haiku dropped half a translation, Gemini
finished 73-82% and split one name into three. `gate_rewrite.py` answers that by rolling
the whole three hours again and keeping the better of two coins. This does the cheaper
thing: `segment_episode.py` cuts the episode into 1,000-1,600 word pieces on the show's own
chapter marks, each piece is rewritten and MEASURED on its own, and a piece that fails is
retried alone while the pieces that passed stay put on disk.

THE GATE measures the four things that have actually gone wrong in this repo, the same four
`rewrite_bakeoff.py` prints, plus two shape checks:

  length      output chars over input chars. Below the floor the model condensed; above the
              ceiling it duplicated or padded.
  Malay       density of Malay function words against the input. The mixed rewrite must keep
              it (anglicising code-switched speech is invisible to a length check); the
              English translation must LOSE it, or it did not translate; the Malay one must
              keep or raise it.
  figures     every number in the input survives, trailing punctuation ignored. A hard gate:
              this is a corpus about money, and Sonnet lost 7 of 24 on one ep62 segment
              while polishing a passage that read the same number three times.
  labels      the output's speaker set equals the input's -- nothing invented (Host,
              Interviewer), nothing merged away. `Speaker ?` is a deliberate marker and
              must survive as itself.
  shape       no timestamps, no headings, no frontmatter, no narration before the first
              turn; the first non-blank line is a bold speaker label.

A segment that passes is written to the work dir as `segNN.md` and is never re-run; every
attempt is kept as `segNN.tryK.md` beside a `segNN.json` of measurements, so a failure can
be read rather than guessed at. Nothing under episodes/ is touched without --write, and
--write refuses while any segment of any stage lacks an accepted file.

  python scripts/segment_episode.py ep62 --raw <transcript> --out data/_ep62_segments.json
  python scripts/rewrite_segments.py ep62 --only 10 26 27          # bake-off on three
  python scripts/rewrite_segments.py ep62                          # all stages, all segments
  python scripts/rewrite_segments.py ep62 --write                  # stitch into episodes/

After --write, the same four steps gate_rewrite.py calls MANDATORY still apply:
rebuild_roster.py --write, normalize_speaker_labels.py --write, build_episode_index.py,
qa_check.py.
"""
import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import episode_path, frontmatter_md, resolve_tag  # noqa: E402
from lib_gemini import CLEAN_PROMPT_TEMPLATE, TRANSLATE_PROMPT_TEMPLATE  # noqa: E402
from rewrite_bakeoff import CALLERS, MALAY, names_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EPISODES_DIR = ROOT / "episodes"
STAGES = ["mixed", "en", "ms"]
TARGET_LANGUAGE = {"en": "English", "ms": "Bahasa Melayu"}

# Floors and ceilings per stage. The mixed floors are the prompt's own (70% length, 80%
# Malay). The translation floors sit a little under check_rewrite_complete.py's whole-file
# floors (en 0.90, ms 0.80) because one segment varies more than a whole file; that check
# still runs on the stitched result. The English ceiling on Malay density is what says
# "this was translated": a segment that keeps a third of its Malay function words was not.
GATES = {
    "mixed": {"len_min": 0.70, "len_max": 1.50, "malay_min": 0.80, "malay_max": None},
    "en": {"len_min": 0.85, "len_max": 1.70, "malay_min": None, "malay_max": 0.30},
    "ms": {"len_min": 0.75, "len_max": 1.70, "malay_min": 0.90, "malay_max": None},
}
LABEL_RE = re.compile(r"\*\*([^*:]{1,40}):\*\*")
SOURCE_LABEL_RE = re.compile(r"^\[[\d:]+\]\s*([^:\n]{1,40}):", re.M)
FIGURE_RE = re.compile(r"\d[\d.,]*")
# A polishing model writes "2/3" as "dua pertiga" and "ada 2 3 orang" as "dua tiga orang". That
# is a rendering, not a loss, so a missing small integer is accepted when its number word appears
# more often in the output than in the input. Only 0-12: nobody writes 2017 or 57 juta in words.
NUMBER_WORDS = {"0": ("kosong", "zero"), "1": ("satu", "one"), "2": ("dua", "two"),
                "3": ("tiga", "three"), "4": ("empat", "four"), "5": ("lima", "five"),
                "6": ("enam", "six"), "7": ("tujuh", "seven"), "8": ("lapan", "eight"),
                "9": ("sembilan", "nine"), "10": ("sepuluh", "ten"), "11": ("sebelas", "eleven"),
                "12": ("dua belas", "twelve")}


def parse_model(spec):
    """'claude:claude-haiku-4-5-20251001' -> (caller, model). A bare name means claude."""
    kind, _, model = spec.partition(":")
    if not model:
        kind, model = "claude", kind
    if kind not in CALLERS:
        raise SystemExit(f"unknown provider {kind!r}; one of {sorted(CALLERS)}")
    return CALLERS[kind], model


def strip_stamps(text):
    return re.sub(r"^\[[\d:]+\]\s*", "", text, flags=re.M)


def figures(text):
    return {f.rstrip(".,") for f in FIGURE_RE.findall(text)}


def malay_count(text):
    return sum(1 for w in re.findall(r"[a-z']+", text.lower()) if w in MALAY)


def labels_of(text, source):
    if source:
        return set(SOURCE_LABEL_RE.findall(text))
    return set(LABEL_RE.findall(text))


def clean_output(text):
    """Remove the wrappers models add around the body; the gate then checks none remain."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    lines = text.strip().split("\n")
    while lines and re.match(r"^#{1,6}\s", lines[0]):
        lines.pop(0)
    return "\n".join(lines).strip()


def measure(stage, source, text, names):
    body = strip_stamps(source) if stage == "mixed" else source
    in_labels = labels_of(source, source=(stage == "mixed"))
    out_labels = labels_of(text, source=False)
    fig_in, fig_out = figures(body), figures(text)
    worded = {f for f in fig_in - fig_out if f in NUMBER_WORDS and any(
        len(re.findall(rf"\b{w}\b", text, re.I)) > len(re.findall(rf"\b{w}\b", body, re.I))
        for w in NUMBER_WORDS[f])}
    first = next((ln for ln in text.split("\n") if ln.strip()), "")
    report = {
        "char_ratio": round(len(text) / max(1, len(body)), 3),
        "malay_ratio": round(malay_count(text) / max(1, malay_count(body)), 3),
        "figures_total": len(fig_in),
        "figures_missing": sorted(fig_in - fig_out - worded),
        "figures_worded": sorted(worded),
        "invented_labels": sorted(out_labels - in_labels),
        "missing_labels": sorted(in_labels - out_labels),
        "timestamps_left": len(re.findall(r"\[\d+:\d+", text)),
        "headings": len(re.findall(r"^(#{1,6}\s|---\s*$)", text, re.M)),
        "starts_with_label": first.startswith("**"),
        "names_dropped": [n for n in names
                          if n.lower() in body.lower() and n.lower() not in text.lower()],
    }
    report["failures"] = gate_failures(stage, report)
    return report


def gate_failures(stage, r):
    g = GATES[stage]
    fails = []
    if r["char_ratio"] < g["len_min"]:
        fails.append(f"length {r['char_ratio']:.2f} < {g['len_min']}")
    if r["char_ratio"] > g["len_max"]:
        fails.append(f"length {r['char_ratio']:.2f} > {g['len_max']}")
    if g["malay_min"] is not None and r["malay_ratio"] < g["malay_min"]:
        fails.append(f"malay {r['malay_ratio']:.2f} < {g['malay_min']}")
    if g["malay_max"] is not None and r["malay_ratio"] > g["malay_max"]:
        fails.append(f"malay {r['malay_ratio']:.2f} > {g['malay_max']} (not translated)")
    if r["figures_missing"]:
        fails.append(f"figures missing {r['figures_missing'][:8]}")
    if r["invented_labels"]:
        fails.append(f"invented labels {r['invented_labels']}")
    if r["missing_labels"]:
        fails.append(f"missing labels {r['missing_labels']}")
    if r["timestamps_left"]:
        fails.append(f"{r['timestamps_left']} timestamps left")
    if r["headings"]:
        fails.append(f"{r['headings']} heading/frontmatter lines")
    if not r["starts_with_label"]:
        fails.append("does not open with a speaker label")
    return fails


def build_prompt(stage, source, names, extra):
    if stage == "mixed":
        prompt = CLEAN_PROMPT_TEMPLATE.format(raw_text=source)
        prompt += ("\n\nSpellings confirmed for this episode -- use these exact forms and "
                   "never split one name across two spellings:\n"
                   + "\n".join(f"- {n}" for n in names))
        if extra:
            prompt += "\n\n" + extra.strip()
        return prompt
    return TRANSLATE_PROMPT_TEMPLATE.format(target_language=TARGET_LANGUAGE[stage],
                                            mixed_text=source)


def run_segment(stage, index, source, names, extra, caller, model, tries, workdir):
    """Try up to `tries` times; write the first passing output as segNN.md. Returns report."""
    out = workdir / stage
    out.mkdir(parents=True, exist_ok=True)
    accepted = out / f"seg{index:02d}.md"
    if accepted.exists():
        return {"index": index, "stage": stage, "status": "cached"}
    prompt = build_prompt(stage, source, names, extra)
    attempts = []
    for k in range(1, tries + 1):
        began = time.time()
        try:
            text = clean_output(caller(model, prompt))
            if not text:
                raise RuntimeError("returned nothing")
        except Exception as exc:
            attempts.append({"try": k, "error": str(exc)[:300],
                             "seconds": round(time.time() - began, 1)})
            continue
        report = measure(stage, source, text, names)
        report.update({"try": k, "seconds": round(time.time() - began, 1)})
        attempts.append(report)
        (out / f"seg{index:02d}.try{k}.md").write_text(text, encoding="utf-8")
        if not report["failures"]:
            accepted.write_text(text, encoding="utf-8")
            break
    (out / f"seg{index:02d}.json").write_text(
        json.dumps({"stage": stage, "index": index, "model": model, "attempts": attempts},
                   indent=1, ensure_ascii=False), encoding="utf-8")
    last = attempts[-1] if attempts else {}
    return {"index": index, "stage": stage,
            "status": "ok" if accepted.exists() else "FAILED",
            "tries": len(attempts), "last": last}


def describe(result):
    last = result.get("last", {})
    if result["status"] == "cached":
        return f"  seg {result['index']:02d} {result['stage']:5} cached"
    if "error" in last:
        return f"  seg {result['index']:02d} {result['stage']:5} {result['status']:6} {last['error'][:90]}"
    line = (f"  seg {result['index']:02d} {result['stage']:5} {result['status']:6} "
            f"try {result['tries']}  {last.get('seconds', 0):5.1f}s  "
            f"len {last.get('char_ratio', 0):.2f}  malay {last.get('malay_ratio', 0):.2f}  "
            f"figures {last.get('figures_total', 0) - len(last.get('figures_missing', []))}"
            f"/{last.get('figures_total', 0)}")
    if last.get("failures"):
        line += "\n" + "".join(f"        - {f}\n" for f in last["failures"]).rstrip("\n")
    if last.get("names_dropped"):
        line += f"\n        names dropped: {last['names_dropped']}"
    return line


def stitch(workdir, stage, count):
    parts = []
    for i in range(count):
        p = workdir / stage / f"seg{i:02d}.md"
        if not p.exists():
            raise SystemExit(f"{stage} seg {i:02d} has no accepted output; refusing to write")
        parts.append(p.read_text(encoding="utf-8").strip())
    return "\n\n".join(parts) + "\n"


def write_episode(episode, workdir, count, clean_model):
    from transcribe_episode import episode_common_fields
    import lib_claude_rewrite

    bodies = {stage: stitch(workdir, stage, count) for stage in STAGES}
    out_dir = EPISODES_DIR / episode_path(episode)
    print("extracting metadata (hosts/guests/summary/topics) ...")
    meta = lib_claude_rewrite.extract_metadata(None, bodies["mixed"])
    common = episode_common_fields(episode)
    for key in ("hosts", "guests", "topics", "summary"):
        common[key] = meta[key]

    spec = {
        "mixed": ("interview.md", "# Interview", clean_model,
                  "Polished newspaper-style Q&A rewrite, kept in the original mixed "
                  "English/Bahasa Melayu (closest to how it was actually spoken). Rewritten "
                  "segment by segment, each segment gated on length, Malay density, figures "
                  "and speaker labels. See raw.md for the unedited transcript, or "
                  "interview-en.md / interview-ms.md for single-language versions."),
        "en": ("interview-en.md", "# Interview (English)", clean_model,
               "Full English translation of interview.md (the mixed-language newspaper-style "
               "rewrite), translated segment by segment."),
        "ms": ("interview-ms.md", "# Interview (Bahasa Melayu)", clean_model,
               "Terjemahan penuh Bahasa Melayu bagi interview.md (versi gaya akhbar "
               "dwibahasa), diterjemah segmen demi segmen."),
    }
    for stage, (name, heading, model, note) in spec.items():
        fields = dict(common)
        fields["language"] = stage
        fields["model"] = model
        fields["note"] = note
        path = out_dir / name
        path.write_text(frontmatter_md(fields, f"{heading}\n\n" + bodies[stage]),
                        encoding="utf-8")
        print(f"wrote {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", help="episode tag, e.g. ep62")
    ap.add_argument("--segments", help="json from segment_episode.py (default data/_<tag>_segments.json)")
    ap.add_argument("--workdir", help="default data/_<tag>_rewrite")
    ap.add_argument("--model", default="claude:claude-haiku-4-5-20251001",
                    help="provider:model; provider is claude, gemini or openrouter")
    ap.add_argument("--stage", nargs="*", default=STAGES, choices=STAGES)
    ap.add_argument("--only", nargs="*", type=int, help="segment indices to run")
    ap.add_argument("--tries", type=int, default=3)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--instructions", help="text file appended to the mixed-stage prompt")
    ap.add_argument("--write", action="store_true", help="stitch into episodes/ (needs every segment)")
    a = ap.parse_args()

    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    episode = resolve_tag(manifest, a.tag)
    tag = a.tag.partition(":")[0]
    segments = json.loads(Path(a.segments or ROOT / "data" / f"_{tag}_segments.json")
                          .read_text(encoding="utf-8"))
    workdir = Path(a.workdir or ROOT / "data" / f"_{tag}_rewrite")
    names = names_for(episode["video_id"])
    extra = Path(a.instructions).read_text(encoding="utf-8") if a.instructions else ""
    caller, model = parse_model(a.model)
    indices = a.only if a.only else list(range(len(segments)))

    for stage in [s for s in STAGES if s in a.stage]:
        print(f"== {stage}: {len(indices)} segments, {model}, {a.tries} tries, {a.workers} workers")

        def source_for(i):
            if stage == "mixed":
                return segments[i]["text"]
            p = workdir / "mixed" / f"seg{i:02d}.md"
            return p.read_text(encoding="utf-8") if p.exists() else None

        jobs = [(i, source_for(i)) for i in indices]
        for i, src in jobs:
            if src is None:
                print(f"  seg {i:02d} {stage:5} SKIP   no accepted mixed segment")
        jobs = [(i, s) for i, s in jobs if s is not None]
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            futures = [pool.submit(run_segment, stage, i, src, names, extra, caller, model,
                                   a.tries, workdir) for i, src in jobs]
            results = [f.result() for f in futures]
        for r in sorted(results, key=lambda r: r["index"]):
            print(describe(r))
        failed = [r["index"] for r in results if r["status"] == "FAILED"]
        print(f"   {stage}: {len(results) - len(failed)}/{len(results)} accepted"
              + (f", FAILED {failed}" if failed else ""))

    if a.write:
        write_episode(episode, workdir, len(segments), model)
        print("NEXT: rebuild_roster.py --write, normalize_speaker_labels.py --write, "
              "build_episode_index.py, qa_check.py")


if __name__ == "__main__":
    main()
