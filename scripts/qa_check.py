"""Audit all episodes for known pipeline failure signatures and write a checklist.

Checks per episode:
  - raw.md exists and has sane [MM:SS] timestamp coverage vs duration_seconds
    (catches incomplete transcription and hallucinated runaway timestamps)
  - raw.md has real paragraph breaks between turns, not one wall-of-text block
    (catches the missing-"\n\n" bug that silently bypasses chunking)
  - raw.md doesn't repeat the same long block verbatim at different timestamps
    (catches a continuation-loop hallucination that still passes the timestamp
    coverage check since the fabricated timestamps stay in a plausible range)
  - raw.md doesn't have a long run of consecutive short blocks with identical
    text at different timestamps (catches a distributed repetition-loop
    degeneration too small-per-block for the checks above to see)
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
  - raw.md's own printed timestamps never drop backward by more than 30s
    (catches hard resets, block reorders, and digit typos -- free, no caption
    or API needed, see ENGINEERING_LOG.md 1.16)
  - raw.md's mid-file timestamp gaps are explained by the amount of text at each
    gap's start (catches content silently dropped from the MIDDLE of an episode,
    which the end-of-file coverage check above cannot see, see ENGINEERING_LOG.md 1.17)
  - raw.md's timestamps don't land on round :00 seconds far more often than
    chance (catches a raw.md that is a fabricated summary outline rather than a
    transcript, see ENGINEERING_LOG.md 1.18)

Adjudicated verdicts live in data/qa_reviewed.json, keyed by episode slug and
signature name. This file is regenerated from scratch on every run, so its
checkboxes cannot hold review state -- without that ledger, every session
re-investigates the same already-resolved episodes and the flagged count never
moves. See ENGINEERING_LOG.md 1.21.

Usage:
  python scripts/qa_check.py            # writes QA_CHECKLIST.md
"""
import json
import re
from pathlib import Path

from common import episode_slug
from lib_gemini import MODEL_FALLBACK_CHAIN

ROOT = Path(__file__).resolve().parent.parent
import check_published  # published-file signatures; see its docstring
import check_figures  # published figures vs raw.md; see its docstring

EPISODES_DIR = ROOT / "episodes"
MANIFEST_PATH = ROOT / "data" / "manifest.json"
DRIFT_PATH = ROOT / "data" / "timestamp_drift.json"
COVERAGE_PATH = ROOT / "data" / "caption_coverage.json"
REVIEWED_PATH = ROOT / "data" / "qa_reviewed.json"
OUT_PATH = ROOT / "QA_CHECKLIST.md"

TIMESTAMP_RE = re.compile(r"\[(?:(\d+):)?(\d+):(\d+)\]")
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

MIN_COVERAGE_PCT = 95
MAX_COVERAGE_PCT = 150
MAX_BLOCK_CHARS = 20_000  # a single real speaker turn is never this long

# A block this long in WALL-CLOCK time is suspect no matter how many labels it carries.
# Kept separate from MAX_BLOCK_CHARS on purpose: the char threshold is gated on
# `n_turns > 1` because it targets merged paragraph breaks, and that gate is exactly how
# a 62-minute collapsed block passed QA for a month. Some episodes really do contain a
# 20-minute monologue (ep36, ep51 and ep44's Bloomberg read-out are confirmed by
# reading them), so this flags for adjudication rather than asserting a bug -- record the
# verdict per episode in data/qa_reviewed.json, never by widening this rule.
MAX_BLOCK_SECONDS = 1200

# Fire on a roster member with NO label at all, not on a small share.
#
# A 1% threshold looked reasonable and was wrong. It flagged ep33 and ep49, whose Farhan
# turns are complete coherent questions ("Sorry, saya ada a bit of a soalan tambahanlah.
# Sebagai layman...") in episodes diarized into 447 and 316 blocks -- he is simply quiet,
# being the producer. It then flagged ep44's Farhan at 0.9% immediately after the repo
# owner confirmed that label from the video. A co-host who really does speak 1.6 minutes
# in a three-hour episode is correctly labelled, not defective.
#
# Zero is the honest signal: the roster says they took part and the transcript gives them
# nothing, so their words are inside somebody else's block. Where a tiny share IS a
# symptom, the episode is collapsed and `oversized-block` already flags it -- ep41's
# Farhan sits at 1.0 min but its 48-minute block keeps the episode on the list.

# 1.11's objective test for whether an oversized block is a real defect, applied
# here instead of being left to prose. The bug this check was written for is
# MERGED TURNS -- paragraph breaks lost, so several speakers' turns run together.
# A block that merged turns still contains their inline "[MM:SS] Speaker:"
# markers, so counting them separates the two cases:
#   1 marker  -> one genuine long monologue (the coarse-VAD-merge artifact). Not
#                a defect; ep41/ep43/ep44/ep58 were all reclassified this way in
#                earlier sessions, yet kept being re-flagged every run.
#   2+        -> turns really were merged. Still a defect.
INLINE_TURN_RE = re.compile(r"\[(?:\d+:)?\d+:\d+\]\s*[^:\n]{1,40}:")
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

# The continuation loop in lib_gemini.py's transcribe_raw asks the model to
# "continue from where you left off" across multiple rounds for long episodes,
# judging progress by the last timestamp emitted. When the model backtracks and
# re-emits an already-covered passage under new (fabricated) timestamps instead of
# truly continuing, that heuristic still looks satisfied -- timestamps keep
# climbing -- so it passes silently. Confirmed directly: one episode had the same
# ~1,600-word passage repeated verbatim at three different timestamps. The runaway-
# timestamp check above only catches this when the fabricated timestamps overshoot
# the real duration; a duplicate block whose timestamps stay in a locally-plausible
# range needs its own check.
#
# The original floor of 300 chars, and the original prefix regex requiring a
# colon-terminated speaker label, together let the worst case in the corpus pass
# silently. ep45 has 1028 duplicate blocks (one passage repeated 19 times) but
# its blocks carry no speaker label ("[1:31:57] Sufi tahap tinggi...", not
# "[1:31:57] Rafizi: Sufi tahap tinggi..."), so "[^:]*:" never matched and left
# each block's unique timestamp in the comparison key, making every repeat look
# distinct -- the same root cause already noted for short_block_loops below.
# ep00 and ep26's duplicates are also real but only 60-283 chars, under the old
# floor. Both fixed here: strip the timestamp whether or not a speaker label
# follows, and drop the floor to 60. Calibrated corpus-wide -- at 60 chars this
# flags exactly ep00, ep26 and ep45 and nothing else, so a naturally recurring
# short reaction ("Ya", "Baik") stays below it on real content.
DUPLICATE_BLOCK_MIN_CHARS = 60
SPEAKER_PREFIX_RE = re.compile(r"^\[(?:\d+:)?\d+:\d+\]\s*(?:\[?[A-Za-z][\w '.-]{0,30}\]?:\s*)?")

# Separate failure mode from the duplicate-block hallucination above: instead of
# re-emitting a whole earlier passage under a new timestamp, the model gets stuck
# repeating the same short phrase over and over within what should be one turn.
# Confirmed on two real episodes (ep13, ep53), both landing on the weakest reachable
# fallback model (gemini-3.5-flash) after every stronger model hit a PROHIBITED_CONTENT
# block. Both happened to also strip paragraph breaks (so the wall-of-text check caught
# them by coincidence), but nothing stops the same repetition from occurring with normal
# timestamp breaks still in place, which would pass every other check silently.
# Tuned against a real false positive: two speakers riffing on a "nyet nyet nyet nyet"
# joke repeated the word ~8 times (real content) but only spans ~40 chars -- requiring
# the total repeated span to reach REPETITION_MIN_SPAN_CHARS excludes that while still
# catching both confirmed bugs (ep13's ~40x "SMS ke apa, " and ep53's ~140,000-char
# repeat of a full sentence).
REPETITION_RE = re.compile(r"(.{8,150}?)\1{3,}", re.S)
REPETITION_MIN_SPAN_CHARS = 150

# A third repetition variant, distinct from both above: instead of one unbroken
# run of literal text, the same short reaction repeats as its own separate
# [MM:SS]-stamped block, over and over, for an extended stretch. Confirmed on
# ep49 (raw.md produced by the weak gemini-3.5-flash-lite fallback): "[MM:SS]
# ah,\n\n" repeated ~4,800 times consecutively, spanning roughly 30 minutes of
# real audio with no other content -- about half the file. Neither check above
# catches it: REPETITION_RE only matches one unbroken run of literal text, but
# each block here has a different timestamp, breaking up the literal match;
# duplicate_blocks() only flags blocks at or above DUPLICATE_BLOCK_MIN_CHARS
# (300 chars), but each "ah," block here is only ~10-15 chars. Needs its own
# check: many consecutive short blocks, below the duplicate-block size floor,
# with identical text once the timestamp/speaker prefix is stripped.
SHORT_LOOP_MIN_RUN = 20
SHORT_LOOP_MAX_CHARS = DUPLICATE_BLOCK_MIN_CHARS
# Confirmed on ep49's actual degenerate blocks: they carry no speaker label at
# all ("[15:46] ah,", not "[15:46] Speaker 1: ah,"), so SPEAKER_PREFIX_RE (which
# requires a colon-terminated label) never matches and leaves each block's
# unique timestamp in place, defeating the identical-text comparison below.
# Strip just the leading timestamp, whether or not a speaker label follows.
LEADING_TIMESTAMP_RE = re.compile(r"^\[(?:\d+:)?\d+:\d+\]\s*")

MODEL_RE = re.compile(r"^model:\s*(\S+)", re.M)

# Free, no-API detector for the timestamp corruption bug catalog in
# ENGINEERING_LOG.md 1.16: walk each block's own leading timestamp in file order
# and flag a drop of more than this many seconds below the running maximum
# seen so far. Corpus-wide, this alone found every hard-reset/reorder bug the
# caption-based checks already knew about (ep32) PLUS two neither had
# surfaced (ep45's garbled-hour typo, ep05's block reorder), because both
# preserve locally-correct individual timestamps and only show up as an
# ordering violation, not a drift value.
BACKWARD_JUMP_THRESHOLD_SECONDS = 30

# The coverage check above only asks whether the LAST timestamp reaches the end
# of the audio, so an episode that silently drops most of its MIDDLE still passes
# as clean. Confirmed on ep00 (marked clean while missing ~41% of its runtime,
# including a 16-minute hole between [1:42:11] and [1:58:38]) and on ep26. The
# backward-jump check can't see these either -- the gaps jump forward, and the
# printed timestamps stay perfectly monotonic through them.
#
# A naive "big gap between consecutive timestamps" check is useless here: it
# over-flags 63 of 67 episodes, because raw.md merges a long monologue into one
# timestamped block, so a genuine 6-minute monologue looks like a 6-minute gap
# (the coarse-VAD-merge artifact, ENGINEERING_LOG.md 1.11). Scoring each gap against
# how much text actually sits at its start fixes that -- Malay speech in this
# corpus runs roughly 13 chars/sec, so a 982s gap opening from a 60-char one-liner
# is missing content while a 2568s gap opening from a 33,000-char wall of text is
# not.
#
# Lead-in and tail are deliberately excluded: intro music before the first words
# is normal, and the tail is already covered by the coverage check. Blocks holding
# only a bracketed non-speech marker are skipped too -- ep48 genuinely ends at
# [2:39:48] and leaves 40 minutes of dead air labelled "[silence]" before
# "[end of audio]", which is not lost content.
#
# Calibrated corpus-wide: these thresholds flag exactly ep45, ep26, ep00 and ep35.
# The next-worst episode lands at 6%, comfortably below the 10% floor.
SPEECH_CHARS_PER_SECOND = 13.0
MIN_CONTENT_HOLE_SECONDS = 240
MAX_LOST_CONTENT_PCT = 10
NON_SPEECH_BLOCK_RE = re.compile(r"^\[(?:\d+:)?\d+:\d+\]\s*[\[(][^\])]*[\])][\s.]*$")

# ep35's raw.md is not a transcript at all: it is a Gemini-written summary outline
# posing as one, and it passed every check above as clean. Its giveaway is timing
# that was invented rather than measured -- real ASR timestamps land on arbitrary
# second values, but an outline lands on round minute boundaries constantly.
# ep35 has 25% of its timestamps ending in :00 against 1.7% expected by chance,
# and it is the only episode in the corpus above 8%, so this separates cleanly.
# (Its content confirms it independently: numbered lists inside "speech", agenda
# labels, third-person descriptions of what was said, and written-register marks
# real speech never has such as "/" and parenthetical glosses.)
ROUND_TIMESTAMP_PCT_THRESHOLD = 12
ROUND_TIMESTAMP_MIN_SAMPLES = 20
# Bottom of the fallback chain, only reached once every better model is exhausted or
# down -- confirmed prone to silently dropping code-switched content (see
# lib_gemini.py's MODEL_FALLBACK_CHAIN comment and the language-mistranslation
# writeup). Flag any output file produced by one of these so it gets a closer look
# even when the density/ratio checks above don't catch anything.
WEAK_MODELS = set(MODEL_FALLBACK_CHAIN[6:])

# check_timestamp_drift.py is a sampling heuristic with a documented search-radius
# limitation (1.11), so a small reported drift is not evidence of a defect. The
# corpus splits cleanly: two episodes report 8s and 22s of drift on 1.5-2.7 hour
# recordings -- within caption-alignment noise, and not actionable at any effort
# level -- while every other flagged episode reports 325s or more. Flagging the
# trivial pair alongside genuine 5-18 minute displacements made the checklist read
# as 12 problems when it holds 10.
MIN_ACTIONABLE_DRIFT_SECONDS = 60

# Seven episodes filed most of Rafizi's speech under a co-host's name and passed every
# check above, because nothing here compared one episode against the rest of the corpus.
# Each looked internally consistent: the diarizer had merged the speakers into a single
# cluster, and the naming pass then labelled that cluster after whoever it saw first.
#
# He is the show's principal, so his share of the text is stable corpus-wide and the
# outliers separate cleanly: the median is 87%, healthy episodes run 68-99%, and the
# seven bad ones sat at 0-7%. Flagging any episode where a label other than his holds
# the most text catches all seven.
#
# Two legitimate exceptions, so this reports rather than assumes: a guest-led interview
# really can leave the guest with the larger share (ep05 at 53%, ep21 at 51%, both
# confirmed by voiceprint), and ep45 is deliberately unlabelled. Verify a flag with
# scripts/verify_speaker_voiceprint.py before renaming anything -- that compares voices
# across episodes and is the only check here immune to a whole-episode mislabel.
PRINCIPAL_LABELS = {"Rafizi", "Rafizi Ramli", "YB Rafizi"}
MIN_PRINCIPAL_SHARE_PCT = 25


def principal_share(body):
    """Share of transcript text under the principal's label, and the label holding most."""
    totals = {}
    for match in INLINE_TURN_RE.finditer(body):
        label = body[match.start():match.end()].split("]", 1)[1].strip().rstrip(":").strip()
        end = body.find("\n\n", match.end())
        text = body[match.end():end if end != -1 else len(body)]
        totals[label] = totals.get(label, 0) + len(text)
    total = sum(totals.values())
    if not total:
        return None, None, 0
    principal = sum(chars for label, chars in totals.items() if label in PRINCIPAL_LABELS)
    dominant = max(totals, key=totals.get)
    return 100 * principal / total, dominant, 100 * totals[dominant] / total


def label_seconds(body, duration):
    """Seconds of runtime under each speaker label, measured by gap to the next stamp."""
    marks = []
    for match in INLINE_TURN_RE.finditer(body):
        stamp = TIMESTAMP_RE.search(body, match.start(), match.end())
        if not stamp:
            continue
        h, m, sec = stamp.groups()
        start = (int(h) if h else 0) * 3600 + int(m) * 60 + int(sec)
        label = body[match.start():match.end()].split("]", 1)[1].strip().rstrip(":").strip()
        marks.append((start, label))
    totals = {}
    for i, (start, label) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else max(duration or start, start)
        totals[label] = totals.get(label, 0) + max(0, end - start)
    return totals, marks


def longest_block_seconds(body, duration):
    """(seconds, start_second, label) of the block occupying the most wall-clock time."""
    _, marks = label_seconds(body, duration)
    best = (0, 0, None)
    for i, (start, label) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else max(duration or start, start)
        if end - start > best[0]:
            best = (end - start, start, label)
    return best


def roster(ep_dir, key):
    """hosts/guests from interview.md -- they are NOT in raw.md's frontmatter."""
    path = ep_dir / "interview.md"
    if not path.exists():
        return []
    match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    if not match:
        return []
    listing = re.search(key + r":\s*\n((?:[ \t]*-[ \t]+.*\n)+)", match.group(1) + "\n")
    if not listing:
        return []
    return [x.strip().lstrip("-").strip().strip("'\"")
            for x in listing.group(1).splitlines() if x.strip()]


def unlabelled_roster_members(ep_dir, body, duration):
    """Roster members whose own label holds ~none of the transcript.

    Compares on the first name token: ep08 labels the principal "YB Rafizi", which an
    exact compare would report as a missing person. This is the check that would have
    caught all 19 affected episodes on its first run. `speaker-attribution` cannot,
    because it only fires when a NON-principal label dominates -- the mirror image.
    """
    people = roster(ep_dir, "hosts") + roster(ep_dir, "guests")
    if not people:
        return []
    totals, marks = label_seconds(body, duration)
    total = sum(totals.values()) or 1
    missing = []
    for person in people:
        first = person.split()[0].lower().strip("'")
        held = sum(sec for label, sec in totals.items() if first in label.lower())
        # Count TURNS, not seconds. label_seconds measures the gap to the next stamp, so
        # a label whose every turn is shorter than the one-second stamp resolution
        # measures as exactly zero -- ep42's sole "Farhan (Pa'an): tahulah" at [2:13:12]
        # is followed by another turn at [2:13:12]. Reporting that as "no label at all"
        # is a different and false claim, and one turn is a small share, which this check
        # deliberately does not fire on.
        turns = sum(1 for _, label in marks if first in label.lower())
        if turns == 0:
            missing.append((person, held, 100 * held / total))
    return missing


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


def repetition_loops(body):
    spans = []
    for m in REPETITION_RE.finditer(body):
        span = m.end() - m.start()
        if span >= REPETITION_MIN_SPAN_CHARS:
            spans.append((span, m.group(1)))
    return spans


def duplicate_blocks(body):
    seen = set()
    dup_count = 0
    dup_chars = 0
    for block in body.split("\n\n"):
        block = block.strip()
        if len(block) < DUPLICATE_BLOCK_MIN_CHARS:
            continue
        key = SPEAKER_PREFIX_RE.sub("", block, count=1)
        if key in seen:
            dup_count += 1
            dup_chars += len(block)
        else:
            seen.add(key)
    return dup_count, dup_chars


def short_block_loops(body):
    blocks = [b.strip() for b in body.split("\n\n") if b.strip()]
    runs = []
    prev_key, run_len, run_chars = None, 0, 0
    for block in blocks:
        key = LEADING_TIMESTAMP_RE.sub("", block, count=1) if len(block) < SHORT_LOOP_MAX_CHARS else None
        if key is not None and key == prev_key:
            run_len += 1
            run_chars += len(block) + 2
        else:
            if run_len >= SHORT_LOOP_MIN_RUN:
                runs.append((run_len, run_chars, prev_key))
            run_len, run_chars = (1, len(block) + 2) if key is not None else (0, 0)
        prev_key = key
    if run_len >= SHORT_LOOP_MIN_RUN:
        runs.append((run_len, run_chars, prev_key))
    return runs


def backward_timestamp_jumps(body):
    jumps = []
    running_max = -1
    for block in body.split("\n\n"):
        block = block.strip()
        m = TIMESTAMP_RE.match(block)
        if not m:
            continue
        h, mins, s = m.groups()
        ts = (int(h) if h else 0) * 3600 + int(mins) * 60 + int(s)
        if running_max >= 0 and ts < running_max - BACKWARD_JUMP_THRESHOLD_SECONDS:
            jumps.append((running_max, ts, block[:60]))
        if ts > running_max:
            running_max = ts
    return jumps


def timestamped_blocks(body):
    blocks = []
    for block in body.split("\n\n"):
        block = block.strip()
        m = TIMESTAMP_RE.match(block)
        if not m:
            continue
        h, mins, s = m.groups()
        ts = (int(h) if h else 0) * 3600 + int(mins) * 60 + int(s)
        blocks.append((ts, block))
    return blocks


def lost_content_holes(body):
    """Gaps between timestamps too large to be explained by the text at their start."""
    holes = []
    blocks = timestamped_blocks(body)
    for (ts, block), (next_ts, _) in zip(blocks, blocks[1:]):
        if NON_SPEECH_BLOCK_RE.match(block):
            continue
        spoken = len(LEADING_TIMESTAMP_RE.sub("", block, count=1)) / SPEECH_CHARS_PER_SECOND
        unexplained = (next_ts - ts) - spoken
        if unexplained >= MIN_CONTENT_HOLE_SECONDS:
            holes.append((int(unexplained), ts, next_ts))
    return holes


def round_timestamp_pct(body):
    blocks = timestamped_blocks(body)
    if len(blocks) < ROUND_TIMESTAMP_MIN_SAMPLES:
        return None, len(blocks)
    round_count = sum(1 for ts, _ in blocks if ts % 60 == 0)
    return 100 * round_count / len(blocks), len(blocks)


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
            issues.append(("weak-model", f"raw.md produced by weaker fallback model {models['raw.md']} -- verify content quality closely"))

    if duration:
        covered = last_timestamp_seconds(body)
        if covered is None:
            issues.append(("coverage", "no timestamps found in raw.md"))
        else:
            pct = covered / duration * 100
            if pct < MIN_COVERAGE_PCT:
                issues.append(("coverage", f"raw.md timestamp coverage only {pct:.0f}% (last ts {covered}s of {duration}s)"))
            elif pct > MAX_COVERAGE_PCT:
                issues.append(("coverage", f"raw.md timestamp coverage {pct:.0f}% -- likely hallucinated runaway timestamps"))

    jumps = backward_timestamp_jumps(body)
    if jumps:
        prev_max, ts, sample = jumps[0]
        issues.append((
            "backward-jump",
            f"raw.md timestamp drops backward ({len(jumps)} jump(s), first from "
            f"{prev_max}s to {ts}s at {sample!r}) -- likely a hard reset, block "
            "reorder, or digit typo, see ENGINEERING_LOG.md 1.16",
        ))

    if duration:
        holes = lost_content_holes(body)
        lost = sum(h[0] for h in holes)
        pct = lost / duration * 100
        if pct >= MAX_LOST_CONTENT_PCT:
            worst, ts, next_ts = max(holes)
            issues.append((
                "content-loss",
                f"raw.md is missing content from the middle ({lost}s unexplained across "
                f"{len(holes)} gap(s), {pct:.0f}% of the episode; worst is {worst}s at "
                f"{ts}s -> {next_ts}s) -- gaps too large for the text at their start, "
                "see ENGINEERING_LOG.md 1.17",
            ))

    round_pct, n_stamps = round_timestamp_pct(body)
    if round_pct is not None and round_pct >= ROUND_TIMESTAMP_PCT_THRESHOLD:
        issues.append((
            "round-timestamps",
            f"raw.md has {round_pct:.0f}% of its {n_stamps} timestamps on round :00 "
            "seconds -- timing was invented, not measured, so this file is likely a "
            "fabricated summary outline rather than a transcript, see ENGINEERING_LOG.md 1.18",
        ))

    blocks = body.split("\n\n")
    biggest = max(blocks, key=len, default="")
    max_block = len(biggest)
    n_turns = len(INLINE_TURN_RE.findall(biggest))
    if max_block > MAX_BLOCK_CHARS and n_turns > 1:
        issues.append((
            "wall-of-text",
            f"raw.md has a {max_block}-char block containing {n_turns} inline turn "
            "markers -- turns merged, paragraph breaks lost",
        ))

    block_secs, block_ts, block_label = longest_block_seconds(body, duration)
    if block_secs > MAX_BLOCK_SECONDS:
        issues.append((
            "oversized-block",
            f"raw.md has a {block_secs // 60}-minute block at "
            f"[{block_ts // 60}:{block_ts % 60:02d}] under one label ({block_label!r}) -- "
            "either a real monologue or a collapsed diarization cluster hiding other "
            "speakers; read the block before waiving, and do not treat the single label "
            "as proof it is one person",
        ))

    for person, held, pct in unlabelled_roster_members(ep_dir, body, duration):
        issues.append((
            "unlabelled-host",
            f"{person!r} is on interview.md's roster but has no label at all in raw.md "
            "-- their turns are sitting inside another speaker's blocks",
        ))

    rep_spans = repetition_loops(body)
    if rep_spans:
        total_span, sample = max(rep_spans, key=lambda x: x[0])
        issues.append((
            "repetition-loop",
            f"raw.md has a repetition-loop degeneration ({total_span} chars repeating "
            f"{sample[:60]!r}...) -- model got stuck re-emitting the same short phrase",
        ))

    short_loops = short_block_loops(body)
    if short_loops:
        run_len, run_chars, sample = max(short_loops, key=lambda x: x[1])
        issues.append((
            "short-loop",
            f"raw.md has {run_len} consecutive near-identical short blocks "
            f"({run_chars} chars total, e.g. {sample[:40]!r}) -- likely a "
            "distributed repetition-loop degeneration, not real content",
        ))

    dup_count, dup_chars = duplicate_blocks(body)
    if dup_count:
        pct = dup_chars / len(raw_text) * 100 if raw_text else 0
        issues.append((
            "duplicates",
            f"raw.md has {dup_count} duplicate block(s) repeated verbatim at different "
            f"timestamps ({dup_chars} chars, {pct:.0f}% of raw.md) -- likely a "
            "continuation-loop hallucination, not a transcription error",
        ))

    if LEAKED_REASONING_RE.search(body) or BACKTICK_TIMESTAMP_RE.search(body):
        issues.append(("leaked-reasoning", "raw.md appears to contain leaked model reasoning/meta-commentary instead of transcript content"))

    split_count = len(SPLIT_TIMESTAMP_RE.findall(body))
    if split_count:
        issues.append(("split-timestamp", f"raw.md has {split_count} turn(s) with '[MM:SS]' and 'Speaker: text' split across two lines instead of one"))

    share, dominant, dominant_share = principal_share(body)
    if share is not None and dominant not in PRINCIPAL_LABELS and share < MIN_PRINCIPAL_SHARE_PCT:
        issues.append((
            "speaker-attribution",
            f"raw.md gives Rafizi only {share:.0f}% of the text while {dominant!r} holds "
            f"{dominant_share:.0f}% -- likely a whole-episode speaker mislabel; confirm with "
            f"scripts/verify_speaker_voiceprint.py before renaming",
        ))

    raw_len = len(raw_text)
    for name in ("interview.md", "interview-en.md", "interview-ms.md"):
        path = ep_dir / name
        if not path.exists():
            issues.append(("missing-file", f"missing {name}"))
            continue
        interview_text = path.read_text(encoding="utf-8")
        ratio = len(interview_text) / raw_len if raw_len else 0
        if ratio < MIN_INTERVIEW_RATIO:
            issues.append(("truncated", f"{name} looks truncated (ratio {ratio:.2f} vs raw.md, expected >= {MIN_INTERVIEW_RATIO})"))

        model_match = MODEL_RE.search(interview_text)
        if model_match:
            models[name] = model_match.group(1)
            if models[name] in WEAK_MODELS:
                issues.append(("weak-model", f"{name} produced by weaker fallback model {models[name]} -- verify content quality closely"))

        lang_match = re.search(r"^language:\s*(\S+)", interview_text, re.M)
        language = lang_match.group(1) if lang_match else None
        if language in ("mixed", "ms"):
            density = malay_density(interview_text)
            if density < MIN_MALAY_DENSITY:
                issues.append((
                    "language",
                    f"{name} claims language: {language} but reads as English-only "
                    f"(Malay-marker density {density:.2f}/1000 chars, expected >= {MIN_MALAY_DENSITY})",
                ))

    # Every signature above reads raw.md. These two read the files a reader actually sees.
    # Their absence is why this suite reported 0/67 clean while the published text carried
    # thousands of placeholder labels and a scatter of altered figures.
    issues.extend(check_published.check(ep_dir))
    issues.extend(check_figures.check(ep_dir))

    return issues, models


def format_models(models):
    return "models: " + ", ".join(f"{name}={model}" for name, model in models.items())


def main():
    results = {}
    for ep_dir in sorted(EPISODES_DIR.glob("*/*")):
        if not ep_dir.is_dir():
            continue
        results[ep_dir.name] = check_episode(ep_dir)

    if DRIFT_PATH.exists():
        drift_data = json.loads(DRIFT_PATH.read_text(encoding="utf-8"))
        for slug, drift in drift_data.items():
            if not drift.get("flagged") or slug not in results:
                continue
            if (drift.get("max_drift_seconds") or 0) < MIN_ACTIONABLE_DRIFT_SECONDS:
                continue
            issues, models = results[slug]
            issues.append((
                "drift",
                f"check_timestamp_drift.py flagged timestamp mistiming "
                f"(max drift {drift.get('max_drift_seconds', '?')}s, "
                f"{drift.get('samples_matched', '?')}/{drift.get('samples_total', '?')} caption samples matched)",
            ))
            results[slug] = (issues, models)

    if COVERAGE_PATH.exists():
        coverage_data = json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))
        for slug, coverage in coverage_data.items():
            if not coverage.get("flagged") or slug not in results:
                continue
            issues, models = results[slug]
            spans = ", ".join(f"{a}s->{b}s" for a, b in coverage.get("dead_runs", []))
            issues.append((
                "caption-coverage",
                f"raw.md has no counterpart for {coverage['worst_dead_run_seconds']}s of "
                f"captioned speech ({spans}; episode baseline "
                f"{coverage['baseline']:.0%}) -- content absent from the transcript "
                f"rather than merely mistimed, see ENGINEERING_LOG.md 1.25",
            ))
            results[slug] = (issues, models)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    unprocessed = sorted(
        (episode_slug(ep), ep["title"]) for ep in manifest if episode_slug(ep) not in results
    )

    reviewed = {}
    if REVIEWED_PATH.exists():
        reviewed = {k: v for k, v in
                    json.loads(REVIEWED_PATH.read_text(encoding="utf-8")).items()
                    if not k.startswith("_")}

    # An adjudicated signature moves out of the flagged list. Without this,
    # QA_CHECKLIST.md is regenerated from scratch every run and its checkboxes
    # cannot hold review state, so every session re-investigates the same
    # already-resolved episodes -- which is what kept the flagged count static.
    total = len(results)
    benign = {}
    for slug, (issues, models) in results.items():
        verdicts = reviewed.get(slug, {})
        keep, waived = [], []
        for sig, text in issues:
            entry = verdicts.get(sig)
            if entry and entry.get("verdict") == "benign":
                waived.append((sig, text, entry.get("reason", ""), entry.get("date", "")))
            else:
                keep.append((sig, text))
        results[slug] = (keep, models)
        if waived:
            benign[slug] = waived

    broken = {slug: result for slug, result in results.items() if result[0]}

    lines = [
        "# QA Checklist",
        "",
        f"Generated by `scripts/qa_check.py`. {total - len(broken)}/{total} processed episodes clean, "
        f"{len(broken)} flagged, {len(unprocessed)} not yet processed.",
        "",
        f"{sum(len(v) for v in benign.values())} issue(s) across {len(benign)} episode(s) were "
        "reviewed and judged benign -- see the section at the end, and "
        "`data/qa_reviewed.json` for the rationale. Delete an entry there to re-flag it.",
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
            for _sig, issue in issues:
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
    print(f"wrote {OUT_PATH} -- {len(broken)}/{total} flagged, "
          f"{sum(len(v) for v in benign.values())} issue(s) waived as reviewed-benign, "
          f"{len(unprocessed)} not yet processed")


if __name__ == "__main__":
    main()
