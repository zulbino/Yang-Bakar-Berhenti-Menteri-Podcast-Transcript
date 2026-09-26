"""Fact-check raw.md's names, honorifics, agencies and brands BEFORE the interview rewrite.

WHY. Owner's rule, 2026-09-27: "we might want to have a fact check on the RAW before we
proceed with interview ... we cant afford to have honorific (YB becoming baby or ebbi etc),
name spelling (Dr Samsuri become Shamsuri), and government agency acronym ... or brand name
(like Ridsect)". Every derived file inherits raw.md's spelling, and the existing checkers
(check_names, check_agencies, check_slurs) compare the published files AGAINST raw.md, so a
garble that is already in raw.md passes all of them. `Shamsuri` sat in 41 raw.md turns over
17 episodes, and in 38 published ones, before the owner named it. The check covers the
owner's own hand-edited raw.md too: "I do made some mistakes as well".

WHAT IT REPORTS.
  FAIL    a known garble still present: a YB-honorific garble (fix_yb_honorific.fix) or a
          reviewed correction from fix_proper_nouns.CORRECTIONS that has not been applied.
  REVIEW  an agency-shaped phrase that nearly matches data/agency_roster.json, and every
          capitalised word or acronym that is neither a common word in this corpus nor in
          data/entity_roster.json. Each one is web-verified (CLAUDE.md rules 1 and 2) and then
          added to the roster with a source URL, or corrected in fix_proper_nouns.py. The
          roster only grows, so later episodes review only names not seen before.

WHAT IT CANNOT SEE. A garble written in lowercase as an ordinary word: `reset` for Ridsect,
`refund` for WeFund, `oi` for YB. Measured on ep65: see ARCHITECTURE.md. Those still need a
reading of the text.

  python scripts/check_raw_facts.py ep65
  python scripts/check_raw_facts.py ep65 --raw data/_ep65_review/raw_pipeline.md
  python scripts/check_raw_facts.py ep65 --record      # after the review; refuses on a FAIL

`--record` stores raw.md's sha256 in data/raw_fact_checks.json, and rewrite_segments.py
refuses to rewrite an episode whose raw.md does not match its record.
"""
import argparse
import datetime
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import check_agencies  # noqa: E402
import common  # noqa: E402
import fix_proper_nouns  # noqa: E402
import fix_yb_honorific  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ROSTER = ROOT / "data" / "entity_roster.json"
RECORDS = ROOT / "data" / "raw_fact_checks.json"
BLOCK = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]\s*([^:\n]{1,40}):(.*)$", re.M)
TOKEN = re.compile(r"(?<![\w'])([A-Z][A-Za-z'-]*[A-Za-z]|[A-Z]{2,})(?![\w'])")
COMMON_MIN = 20    # a word written lowercase this often in the corpus is an ordinary word


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def blocks(text):
    return [(s, label.strip(), words) for s, label, words in BLOCK.findall(text)]


def common_words():
    counts = Counter()
    for p in ROOT.glob("episodes/*/*/raw.md"):
        for _, _, words in blocks(p.read_text(encoding="utf-8")):
            counts.update(w for w in re.findall(r"[a-z][a-z'-]*", words))
    return {w for w, n in counts.items() if n >= COMMON_MIN}


def verified_words():
    words = set()
    if ROSTER.exists():
        for e in json.loads(ROSTER.read_text(encoding="utf-8"))["entities"]:
            words.update(re.findall(r"[A-Za-z][A-Za-z'-]*", e["name"]))
    for e in json.loads(check_agencies.ROSTER.read_text(encoding="utf-8"))["agencies"]:
        words.update(re.findall(r"[A-Za-z][A-Za-z'-]*", e["name"]))
        words.update(e.get("acronyms", []) + ([e["acronym"]] if e.get("acronym") else []))
    return words


def check(raw_path):
    text = raw_path.read_text(encoding="utf-8")
    turns = blocks(text)
    fails, review = [], []

    for stamp, label, words in turns:
        _, n = fix_yb_honorific.fix(words)
        if n:
            fails.append(f"[{stamp}] YB garble x{n}: {words.strip()[:120]}")
    body = "\n".join(words for _, _, words in turns)
    for rx, rep, why in fix_proper_nouns.CORRECTIONS:
        for m in re.finditer(rx, body):
            if m.group(0) != rep:
                ctx = " ".join(body[max(0, m.start() - 50):m.end() + 30].split())
                fails.append(f"known correction not applied, {m.group(0)!r} -> {rep!r}: ...{ctx}...")

    _, names = check_agencies.load_roster()
    for (phrase, official), quote in check_agencies.garbles(body, names).items():
        review.append(f"agency  {phrase!r} is close to {official!r}: ...{quote}...")

    ordinary, known = common_words(), verified_words()
    labels = {w for _, label, _ in turns for w in re.findall(r"[A-Za-z][A-Za-z'-]*", label)}
    seen = {}
    for stamp, _, words in turns:
        for m in TOKEN.finditer(words):
            tok = m.group(1)
            # An acronym is never an ordinary word: ep65's `PA` for PH hid behind `pa`.
            if tok in known or tok in labels or (not tok.isupper() and tok.lower() in ordinary):
                continue
            first = seen.setdefault(tok, [0, stamp, " ".join(words[max(0, m.start() - 50):m.end() + 30].split())])
            first[0] += 1
    for tok, (n, stamp, ctx) in sorted(seen.items(), key=lambda kv: kv[0].lower()):
        review.append(f"name    {tok:<16} x{n:<3} first [{stamp}] ...{ctx}...")
    return fails, review


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag")
    ap.add_argument("--raw", help="check this file instead of the episode's raw.md (no --record)")
    ap.add_argument("--record", action="store_true",
                    help="store raw.md's hash as fact-checked; refuses while any FAIL remains")
    a = ap.parse_args()
    raw_path = Path(a.raw) if a.raw else Path(common.raw_for_tag(a.tag))
    fails, review = check(raw_path)
    for f in fails:
        print("FAIL    " + f)
    for r in review:
        print("REVIEW  " + r)
    print(f"\n{raw_path.name}: {len(fails)} FAIL, {len(review)} to review")
    if not a.record:
        return 1 if fails else 0
    if a.raw:
        raise SystemExit("--record takes the episode's own raw.md, not --raw")
    if fails:
        raise SystemExit("not recorded: fix every FAIL first")
    records = json.loads(RECORDS.read_text(encoding="utf-8")) if RECORDS.exists() else {}
    records[a.tag] = {"raw_sha256": sha(raw_path), "date": datetime.date.today().isoformat(),
                      "reviewed": len(review)}
    RECORDS.write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"recorded {a.tag} in {RECORDS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
