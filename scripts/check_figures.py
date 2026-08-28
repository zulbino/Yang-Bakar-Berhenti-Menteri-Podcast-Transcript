"""Flag figures in the PUBLISHED files that have no counterpart in raw.md.

A number is the one thing in a transcript a reader is most likely to quote and least able
to sanity-check. An audit on 2026-08-28 suspected ep43 of fabricating five oil-production
statistics; a full sweep found the opposite -- Rafizi read them into a calculator
digit-by-digit ("Kira 3, 4, 1, 9, 5"), the ASR shredded them, and the rewrite joined them
back up correctly. What the sweep DID find was quieter and real: single digits changed
between raw.md and the published text, in the same sentence, with no hole to blame.

So the check has to be built the other way round from how it was first imagined. Matching
too loosely is the failure mode that matters here, because a matcher that accepts any
rearrangement of the digits accepts `45 bilion` as evidence for raw's `4.5 bilion`.

TWO MATCHING REGIMES, and the split is what makes the check work:

  * A figure carrying a SCALE WORD (`4.5 bilion`, `340 juta`) is compared BY VALUE.
    Digits alone cannot separate 4.5e9 from 45e9, and that exact pair is a confirmed
    defect in YBkM-ep06.
  * A PLAIN figure (`38,041`, `34,195`) is compared by DIGIT CONCATENATION over a short
    window of raw tokens, because this speaker dictates long numbers one digit at a time
    and the ASR writes each digit as its own token. `3, 4, 1, 9, 5` has to match `34195`.

MEASURED, on 67 episodes and roughly 20,000 figures: 12 episodes flagged, 24 figure
strings (about 21 once the English and Malay renderings of one figure are collapsed). It
catches 5 of the 7 hand-verified defects and none of the 6 hand-verified legitimate
reconstructions.

The 2 it misses are worth naming, because they are a property of the approach and not a
threshold anyone can tune away. In YBhM-ep14 raw says `RM30,000 kalau 10, RM300` and the
published text prints `RM10,300`; in YBkM-ep04 raw says `250, 450` and the published text
prints `RM200.5, RM400.5`. Every digit is present in raw -- only the GROUPING is wrong. The
same permissive digit-concatenation that makes ep43's `3, 4, 1, 9, 5` -> `34,195` pass
correctly is what lets these two through. Tightening it to catch them re-flags all five
ep43 figures, which is the worse trade: those are correct.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_language_drift import strip_frontmatter
from check_published import DERIVED, TURN_RE

# Spellings taken from the corpus, not from a dictionary. Counting every scale word across
# raw.md and the three derived files gives: bilion 3029, juta 2647, billion 1415, million
# 1151, ribu 731, thousand 124, trillion 38, trilion 34, triliun 22, jt 6. Missing `triliun`
# alone put five episodes on the flag list -- ep17 and ep34 both say `1.7 triliun` and
# `1.3 triliun` in raw and the rewrite renders them `trillion`.
SCALE = {
    "ribu": 1e3, "juta": 1e6, "jt": 1e6, "bilion": 1e9, "biliun": 1e9, "billion": 1e9,
    "trilion": 1e12, "triliun": 1e12, "trillion": 1e12,
    "million": 1e6, "thousand": 1e3,
}
# Only 3+ digit figures. Below that the corpus is dominated by years, ages, section
# numbers and prices that recur everywhere, so every short figure finds a spurious match
# and the check says nothing.
MIN_DIGITS = 3
# A bare four-digit number in this range is a year, and years are the one figure class the
# rewrite is EXPECTED to expand: this corpus says decades out loud as `50-an`, `60-an`,
# `70-an`, `30-an`, and the rewrite writes `1950s`, `1960s`, `1970s`, `1930s`. Every one of
# the 12 year-shaped flags in the first full run traced back to that shorthand, so they are
# excluded. The cost is real and worth stating: a year the rewrite got WRONG now passes
# silently. Nothing else in the suite covers that.
YEAR = re.compile(r"1[89]\d\d|20\d\d|2100")
# How many raw digit-tokens may be consumed to rebuild one published figure. Measured:
# ep43's worst genuine case is `30,600. 629.` -> `30,629`, which needs 3 tokens with one
# skipped. 4 admits that; 6 starts accepting unrelated digits from the next sentence.
WINDOW = 4
# Values within this relative distance count as the same figure, absorbing the rounding a
# translation legitimately does (`RM569,000` <-> `569 ribu`).
VALUE_TOL = 0.005

# How far a scale word may sit from a bare number and still apply to it. A speaker states
# the unit once and then lists values against it -- ep57's raw reads "satu 10 bilion, satu
# lagi berapa? 9.6", where the 9.6 is billions by context and nothing else. Measured: 6
# tokens covers every such case in the corpus; beyond ~10 a "bilion" in one sentence starts
# lending its scale to unrelated numbers in the next.
SCALE_REACH = 4
# The ASR writes suffixed scales as often as spelled ones: `9.6B`, `227k`, `22.7k`.
SUFFIX = {"k": 1e3, "rb": 1e3, "j": 1e6, "m": 1e6, "b": 1e9, "t": 1e12}

NUM = re.compile(r"(?<![\d.,])(\d[\d.,]*\d|\d)"
                 r"(?:\s*(ribu|juta|jt|bilion|biliun|billion|trilion|triliun|"
                 r"trillion|thousand|million)\b"
                 r"|\s?([kKbBmMtT]|[rR][bB])(?![A-Za-z0-9]))?", re.I)


def digits(s):
    return re.sub(r"\D", "", s)


def parse_value(raw_num, scale_word):
    """Best-effort numeric value. Returns None when the separators are ambiguous."""
    t = raw_num.strip().rstrip(".,")
    if not t:
        return None
    # A single trailing group of exactly 3 after a comma is a thousands separator; a
    # 1-2 digit tail is a decimal. `38.041` is ambiguous and deliberately yields None so
    # such figures fall through to digit matching instead of a bogus value comparison.
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+", t):
        val = float(t.replace(",", ""))
    elif re.fullmatch(r"\d+[.,]\d{1,2}", t):
        val = float(t.replace(",", "."))
    elif re.fullmatch(r"\d+", t):
        val = float(t)
    else:
        return None
    w = (scale_word or "").lower()
    return val * SCALE.get(w, SUFFIX.get(w, 1))


def figures(text):
    out = []
    for m in NUM.finditer(text):
        num, scale = m.group(1), m.group(2) or m.group(3)
        if len(digits(num)) < MIN_DIGITS and not scale:
            continue
        if YEAR.fullmatch(num) and not scale:
            continue
        out.append((m.group(0).strip(), digits(num), parse_value(num, scale), bool(scale)))
    return out


def raw_evidence(raw_body):
    toks, scales = [], []
    for m in NUM.finditer(raw_body):
        w = (m.group(2) or m.group(3) or "").lower()
        toks.append((m.group(1), digits(m.group(1)),
                     parse_value(m.group(1), w)))
        scales.append(SCALE.get(w, SUFFIX.get(w)))
    values = {v for _, _, v in toks if v is not None}
    # Let a bare number borrow a scale word stated nearby, so a listed value counts as
    # spoken even when the speaker only said the unit once.
    for i, (_, _, v) in enumerate(toks):
        if v is None or scales[i] is not None:
            continue
        lo, hi = max(0, i - SCALE_REACH), min(len(toks), i + SCALE_REACH + 1)
        for s_ in {x for x in scales[lo:hi] if x}:
            values.add(v * s_)
    return toks, values


def _concat_match(target, toks, i):
    """Can `target` be rebuilt from raw tokens starting at i, allowing one skip?"""
    for skip in (False, True):
        acc, used = "", 0
        for j in range(i, min(i + WINDOW + 1, len(toks))):
            d = toks[j][1]
            if not d:
                continue
            if skip and used == 1 and not target.startswith(acc + d):
                continue  # drop one interrupting token, e.g. `30,600. 629` -> `30,629`
            acc += d
            used += 1
            if acc == target:
                return True
            if not target.startswith(acc):
                break
    return False


def _zero_padded(a, b):
    """Same figure, one of them carrying trailing zeros the other drops.

    ep54's raw says `RM634,000` where the published text says `634` -- the ASR bolted a
    spurious RM and three zeros onto a like count, and the rewrite stripped them, which is
    the right call. Only applies to figures with NO scale word, so it cannot be used to
    argue that raw's `4.5 bilion` supports a published `45 bilion`.
    """
    if not a or not b or a == b:
        return a == b and bool(a)
    lo, hi = (a, b) if len(a) < len(b) else (b, a)
    # Both bounds are load-bearing. A first version allowed any number of zeros against a
    # stem of any length, which let raw's bare `7` (from "kereta 7-8") stand as evidence for
    # a published `700,000` -- a confirmed defect in YBhM-ep06 that the check then passed.
    # Three zeros is one scale step, and a 2-digit stem is the shortest that is not noise.
    if len(lo) < 2 or len(hi) - len(lo) > 3:
        return False
    return hi.startswith(lo) and set(hi[len(lo):]) == {"0"}


def supported(fig_digits, fig_value, has_scale, toks, values):
    if has_scale and fig_value is not None:
        # Value regime: digits cannot tell 4.5 bilion from 45 bilion.
        return any(abs(fig_value - v) <= VALUE_TOL * max(abs(fig_value), abs(v))
                   for v in values)
    if fig_value is not None and any(
            abs(fig_value - v) <= VALUE_TOL * max(abs(fig_value), abs(v))
            for v in values):
        return True
    if any(_zero_padded(fig_digits, d) for _, d, _ in toks):
        return True
    return any(_concat_match(fig_digits, toks, i) for i in range(len(toks)))


def check(ep_dir):
    raw_path = ep_dir / "raw.md"
    if not raw_path.exists():
        return []
    toks, values = raw_evidence(strip_frontmatter(raw_path.read_text(encoding="utf-8")))
    unmatched, issues = {}, []
    for name in DERIVED:
        path = ep_dir / name
        if not path.exists():
            continue
        for line in strip_frontmatter(path.read_text(encoding="utf-8")).splitlines():
            m = TURN_RE.match(line.strip())
            body = m.group(2) if m else line
            for shown, d, val, has_scale in figures(body):
                if not supported(d, val, has_scale, toks, values):
                    unmatched.setdefault(shown, set()).add(name)
    if unmatched:
        shown = ", ".join(f"{k!r}" for k in sorted(unmatched)[:4])
        issues.append((
            "unsourced-figure",
            f"{len(unmatched)} figure(s) in the published text have no counterpart in "
            f"raw.md ({shown}) -- in YBkM-ep06 this caught `45 bilion` printed in the same "
            f"sentence as raw's `4.5 bilion`, and `240 juta USD` for raw's `340 juta`"))
    return issues


def main():
    root = Path(__file__).resolve().parent.parent / "episodes"
    flagged = total = 0
    for ep_dir in sorted(root.glob("*/*")):
        found = check(ep_dir)
        total += 1
        if not found:
            continue
        flagged += 1
        tag = re.search(r"-(ep\d+)-", ep_dir.name)
        label = tag.group(1) if tag else ep_dir.name[:14]
        print(f"\n{label}{' (2024)' if 'bakar' in str(ep_dir) else ''}")
        for _, msg in found:
            print(f"   {msg}")
    print(f"\n{flagged} of {total} episode(s) flagged")


if __name__ == "__main__":
    main()
