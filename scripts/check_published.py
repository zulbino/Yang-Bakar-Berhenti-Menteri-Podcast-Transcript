"""Check the PUBLISHED files against raw.md. Nothing else in the suite did.

Every other check reads `raw.md`. But `raw.md` is not what a reader sees -- the three
`interview*.md` files are, and until now those were only checked for existence, a
character-length ratio, one bold label, and an absolute Malay-density floor set 4.6x below
the corpus minimum, so it could never fire. An audit on 2026-08-28 found five fabricated
statistics in ep43's published text, thousands of placeholder labels standing in for named
speakers, and proper nouns the rewrite made WORSE than the transcript it was rewriting.
QA reported 0/67 clean throughout.

That is the same shape as the two earlier false-clean incidents (ENGINEERING_LOG 1.25, and
the circular waiver withdrawn the same day): the check could not see the defect it existed
to catch. The fix is not a better threshold, it is reading the other file.

THRESHOLDS ARE CALIBRATED FROM THE CORPUS, NOT CHOSEN. Where a distribution has a natural
break the break is the threshold, and the margin is recorded here so a later reader can
tell a measured number from a taste-based one.

Returns [(signature, message)] so `qa_check.py` can fold these in beside its own.
"""
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_language_drift import malay_ratio, strip_frontmatter
from label_drift_audit import GENERIC, RAW_LABEL, norm

DERIVED = ["interview.md", "interview-en.md", "interview-ms.md"]

# Relative Malay loss, raw.md -> interview.md. The distribution is bimodal: median 0.011,
# p75 0.107, then a cluster of 14 episodes running from 0.178 to 0.726. The gap between
# the 14th worst (0.178) and the 15th (0.045) is 13 points, so 0.15 sits inside a natural
# break rather than on a slope. All 14 are early episodes; ep24 onward score ~0, so this
# is legacy damage and not a current regression.
MAX_MALAY_LOSS = 0.15

# A turn repeated verbatim is a chunk-boundary artefact, not speech. Measured: 8 instances
# in 4 episodes, every one a defect -- ep27's repeated line was fabricated outright, and
# ep17's duplicated a line raw.md contains once. Short turns legitimately repeat ("Ya.",
# "Betul."), so only turns of 6+ words count.
MIN_DUP_WORDS = 6

GROUP_LABEL = re.compile(
    r"^(multiple|overlapping|beberapa|ramai|penceramah bertindih|beberapa penutur)",
    re.I)
# The colon is REQUIRED. Measured: 40,032 labels in the derived files carry it and
# exactly ONE bold run does not -- ep20's "**Beza Krim dengan Fleximat** --", a topic
# phrase opening a continuation paragraph. With the colon optional that one line parsed
# as a speaker named "Beza Krim dengan Fleximat" and drove a label-mismatch flag.
TURN_RE = re.compile(r"^\*\*([^*]{2,40}?):\*\*\s*(.*)$")
# A turn whose LABEL IS MISSING ENTIRELY, which TURN_RE cannot see because it requires the
# colon. When the rewrite detects a voice change it has no name for, it usually writes
# `Speaker`; ep53 instead bolded the turn's first sentence and emitted no label at all:
#
#   **Baik, kita dah lama ni tau pasal ni kan.** Ya, 1 jam 45 minit ... killer question.
#
# Invisible to every label check, so it scored BETTER than a generic label and the gate
# promoted it. Requires a sentence-like lead (a space, so `**RM40**` in running prose does
# not match) and no colon, which is what separates it from a real turn.
UNLABELLED_TURN_RE = re.compile(r"^\*\*([^*:]{12,120}?)\*\*\s+\S")
# A raw.md block holding two or more of these has lost a paragraph break. qa_check's
# wall-of-text signature also demanded >20,000 chars, which is why ep53's seven such
# blocks all passed.
INLINE_TURN_RE = re.compile(r"\[(?:\d+:)?\d+:\d+\]\s*[^:\n]{1,40}:")
# ONLY NUMBERED clusters. "Speaker ?" is NOT flagged: it is the deliberate marker for a
# turn nobody could identify, and ARCHITECTURE.md's position is that a wrong name is worse
# than none. A first version flagged it and reported 26 episodes, most of them for honestly
# marked unknowns -- the same over-firing as the 1% unlabelled-host threshold that flagged
# genuinely quiet co-hosts. A NUMBERED cluster is different: it is a re-cut that was never
# named, i.e. unfinished work.
PLACEHOLDER_RE = re.compile(
    r"^\[(?:\d+:)?\d+:\d+\]\s*(SPEAKER_\d+|Speaker\s+\d+)\s*:", re.M)
# The same numbered placeholder, but in a PUBLISHED file. ep54 prints all 97 turns as
# "Speaker 1"/"Speaker 2" while its own frontmatter names both hosts, and ep56 prints 121
# such turns next to a "Speaker 1 (Rafizi Ramli)" that gives the name away. raw.md can be
# mid-work; a published file showing a diarizer's cluster id cannot.
DERIVED_PLACEHOLDER_RE = re.compile(r"^(SPEAKER_\d+|Speaker\s+\d+)(?:\s|$)", re.I)


def derived_turns(text):
    out = []
    for line in strip_frontmatter(text).splitlines():
        m = TURN_RE.match(line.strip())
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


# Everything a label can say that is NOT a person's name, in both languages. A label is
# allowed to be translated -- "Host" -> "Hos", "Speaker (unidentified)" -> "Penutur (tidak
# dikenali)" -- because that is correct translation of a role, not speaker drift. Comparing
# label STRINGS flagged 25 episodes and 21 of them were exactly this. What must not differ
# between a file and its own translation is the set of PEOPLE NAMED.
ROLE_WORDS = set("""
host hosts hos ko-hos cohost co-host guest guests tetamu
interviewer interviewers penemubual pewawancara moderator questioner penyoal penanya
audience hadirin penonton speaker speakers penutur penceramah pembicara
unidentified unknown unnamed tidak dikenali dikenal pasti dikenalpasti
other others lain another multiple several beberapa pelbagai berbilang ramai
overlapping bertindih banter sindiran voice suara narrator crew staff
male female lelaki perempuan man woman seorang dan with the of a an
""".split())
NAME_TOKEN = re.compile(r"[A-Za-zÀ-ÿ][\w'’-]*")


def names_in_label(label):
    s = re.sub(r"[\[\]()]", " ", label)
    s = re.sub(r"\b(speaker|penutur|penceramah)\s*[\d?]+\b", " ", s, flags=re.I)
    s = s.replace("/", " ")
    return {t for t in NAME_TOKEN.findall(s)
            if t[0].isupper() and t.lower() not in ROLE_WORDS}


def raw_speaker_names(raw_body):
    names = set()
    for a, b in RAW_LABEL.findall(raw_body):
        name = (a or b).strip()
        if name and not GENERIC.match(name):
            names.add(norm(name))
    return names


def check(ep_dir):
    issues = []
    raw_path = ep_dir / "raw.md"
    if not raw_path.exists():
        return issues
    raw_body = strip_frontmatter(raw_path.read_text(encoding="utf-8"))

    placeholders = Counter(m.group(1).strip() for m in PLACEHOLDER_RE.finditer(raw_body))
    if placeholders:
        shown = ", ".join(f"{k} x{v}" for k, v in placeholders.most_common(3))
        issues.append((
            "placeholder-label",
            f"raw.md labels {sum(placeholders.values())} turn(s) with a placeholder "
            f"({shown}) -- a published transcript should name the speaker or say nothing, "
            f"and these propagate into the derived files as several ungreppable variants"))

    # Counts every affected block, not just the first. The `break` this replaces reported
    # 1 of ep53's 7 buried markers, so the flag read as a single lost paragraph break when
    # it was six of them plus four labels holding no words at all -- and the flag is the
    # only notice this defect gets, since the merged text publishes under one name.
    buried, first = 0, None
    for line in raw_body.splitlines():
        markers = INLINE_TURN_RE.findall(line)
        if len(markers) >= 2:
            buried += len(markers) - 1
            if first is None:
                first = markers[1]
    if buried:
        issues.append((
            "inline-turn-marker",
            f"raw.md buries {buried} turn marker(s) inside another speaker's block "
            f"(first {first!r}) -- a paragraph break was lost, so one speaker's block "
            f"contains another's words. Fix with scripts/split_inline_turns.py, then "
            f"regenerate: the published files still hold the merged text"))

    names = raw_speaker_names(raw_body)
    # Generic labels raw.md uses itself, i.e. speakers the transcript never named. Role
    # words like `Moderator` and `Audience` are not caught by PLACEHOLDER_RE above, which
    # only matches numbered clusters, so before this they were invisible at the raw stage
    # and surfaced only as a rewrite flag on the published files.
    raw_generic = Counter()
    for a, b in RAW_LABEL.findall(raw_body):
        label = (a or b).strip()
        if GENERIC.match(label):
            raw_generic[label] += 1
    if raw_generic:
        shown = ", ".join(f"{k} x{v}" for k, v in raw_generic.most_common(3))
        issues.append((
            "raw-unnamed-speaker",
            f"raw.md leaves {sum(raw_generic.values())} turn(s) on a generic label "
            f"({shown}) -- a real person the transcript never names, so every derived file "
            f"inherits it. Fix by identifying the speaker (video frames, the episode "
            f"description, voiceprints), not by regenerating the rewrite"))

    label_sets, name_sets = {}, {}
    for name in DERIVED:
        path = ep_dir / name
        if not path.exists():
            continue
        turns = derived_turns(path.read_text(encoding="utf-8"))
        label_sets[name] = Counter(label for label, _ in turns)
        name_sets[name] = {label: names_in_label(label) for label, _ in turns}

        unlabelled = [m.group(1) for m in
                      (UNLABELLED_TURN_RE.match(l.strip())
                       for l in strip_frontmatter(path.read_text(encoding="utf-8"))
                       .splitlines()) if m]
        if unlabelled:
            issues.append((
                "unlabelled-turn",
                f"{name} has {len(unlabelled)} turn(s) with NO speaker label, the first "
                f"sentence bolded in its place ({unlabelled[0][:52]!r}) -- the reader "
                f"attributes it to the previous speaker. ep53 got this where raw.md buries "
                f"a co-host inside a Rafizi block, so the rewrite heard the voice change "
                f"and had no name for it"))

        numbered = Counter(l for l, _ in turns if DERIVED_PLACEHOLDER_RE.match(l))
        if numbered:
            shown = ", ".join(f"{k} x{v}" for k, v in numbered.most_common(3))
            issues.append((
                "published-placeholder",
                f"{name} labels {sum(numbered.values())} turn(s) with a diarizer cluster "
                f"id ({shown}) -- ep54 prints all 97 turns this way while its frontmatter "
                f"names both hosts, and ep56 does it beside a 'Speaker 1 (Rafizi Ramli)' "
                f"that gives the name away"))

        # Exclude the numbered ones: published-placeholder already reports those, and
        # counting them twice made 9 episodes carry two flags for one set of turns.
        #
        # Also exclude labels raw.md ITSELF uses. This flag's whole claim is that the
        # rewrite "discarded names the transcript already had", and where raw carries the
        # same generic label the transcript never had a name to discard -- the rewrite is
        # being faithful, and the missing name is a speaker-attribution gap upstream.
        # Measured before this exclusion: 351 of 1080 flagged turns, 32%, across five
        # episodes -- YBkM-ep02 is entirely this (raw labels 78 turns `Moderator`), and so
        # are ep53, ep26 and ep36. Worse than a false positive, it pointed the work at the
        # wrong stage: regenerating YBkM-ep02 made the count go 84 -> 234 precisely because
        # the new output stopped inventing attributions for turns raw leaves unnamed.
        # Reported below as `raw-unnamed-speaker` instead, which is where the fix belongs.
        generic = {l: n for l, n in label_sets[name].items()
                   if GENERIC.match(l) and not DERIVED_PLACEHOLDER_RE.match(l)
                   and not any(norm(l) == norm(r) for r in raw_generic)}
        if generic and names:
            shown = ", ".join(f"{k} x{v}" for k, v in
                              sorted(generic.items(), key=lambda kv: -kv[1])[:3])
            issues.append((
                "generic-label",
                f"{name} labels {sum(generic.values())} turn(s) generically ({shown}) "
                f"while raw.md names {len(names)} real speaker(s) -- the rewrite discarded "
                f"names the transcript already had"))

        repeated = Counter((l, t) for l, t in turns if len(t.split()) >= MIN_DUP_WORDS)
        for (label, text), count in repeated.items():
            if count > 1:
                issues.append((
                    "duplicate-turn",
                    f"{name} repeats one {label} turn verbatim {count}x "
                    f"({text[:60]!r}) -- a chunk-boundary artefact; in ep27 the repeated "
                    f"line turned out to be fabricated outright"))
                break

    # Compare the PEOPLE NAMED, not the label strings. A role translated into the target
    # language is correct output; a person who exists in one file and not in its own
    # translation is not. On the corpus this moves the signature from 25 episodes to 2:
    # ep11, whose mixed file splits Iqbal into "Iqbal" (55 turns) and "Ikhbal" (9) where
    # the English file correctly has all 64 as one person, and ep14, whose Malay file
    # replaces the named Haziq with the role "Penemubual"/"Pewawancara".
    if len(name_sets) == 3:
        flat = {n: set().union(*v.values()) if v else set()
                for n, v in name_sets.items()}
        shared = set.intersection(*flat.values())
        # A label that already carries a shared name identifies a person the other files
        # know: "Speaker 1 (Rafizi Ramli)" beside their "Rafizi" is one person written two
        # ways. Only labels naming somebody entirely new count.
        unique = {n: {x for label, ns in v.items() if ns and not (ns & shared)
                      for x in ns} - shared
                  for n, v in name_sets.items()}
        if any(unique.values()):
            detail = "; ".join(f"{n}: {sorted(u)}" for n, u in unique.items() if u)
            issues.append((
                "label-mismatch",
                f"the three derived files name different people ({detail}) -- either one "
                f"person is spelt two ways, or a name present in one file was replaced by "
                f"a bare role in its own translation"))

    interview = ep_dir / "interview.md"
    if interview.exists():
        raw_ratio = malay_ratio(raw_body)
        iv_ratio = malay_ratio(strip_frontmatter(interview.read_text(encoding="utf-8")))
        if raw_ratio > 0 and (raw_ratio - iv_ratio) / raw_ratio > MAX_MALAY_LOSS:
            issues.append((
                "malay-loss",
                f"interview.md lost {(raw_ratio - iv_ratio) / raw_ratio * 100:.0f}% of "
                f"raw.md's Malay ({raw_ratio * 100:.1f}% -> {iv_ratio * 100:.1f}% marker "
                f"density) while still declaring itself mixed -- the rewrite anglicised a "
                f"code-switched original"))
    return issues


def main():
    root = Path(__file__).resolve().parent.parent / "episodes"
    counts, flagged, total = Counter(), 0, 0
    for ep_dir in sorted(root.glob("*/*")):
        found = check(ep_dir)
        total += 1
        if not found:
            continue
        flagged += 1
        tag = re.search(r"-(ep\d+)-", ep_dir.name)
        label = tag.group(1) if tag else ep_dir.name[:14]
        print(f"\n{label}{' (2024)' if 'bakar' in str(ep_dir) else ''}")
        for sig in {sig for sig, _ in found}:
            counts[sig] += 1
        for sig, msg in found:
            print(f"   [{sig}] {msg}")
    print(f"\n{flagged} of {total} episode(s) flagged")
    for sig, n in counts.most_common():
        print(f"   {sig:20} {n} episode(s)")


if __name__ == "__main__":
    main()
