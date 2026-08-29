"""Remove the Whisper subscribe-boilerplate hallucination from raw.md and the published
files.

THE SENTENCE NOBODY SAID. `Sila berasa bebas untuk menyukai, melanggan, maju dan memberi
ganjaran untuk menyokong lajur Der Spiegel dan Diandian` is a Malay rendering of Chinese
YouTube-subtitle boilerplate that `mesolitica/malaysian-whisper-medium-v2` inherited from
its training data (Mingjing is Der Spiegel, Diandian is the other channel). It was found
from the far end: ep28's published text carried `[aside about liking, subscribing and
supporting Der Spiegel and Diandian omitted from context]`, the rewrite noticing the
hallucination and writing a note about it instead of dropping it.

DELETION IS SAFE, and that was measured rather than assumed. `_boilerplate_probe.py` took
the words either side of every occurrence in raw and asked whether both sides land inside
ONE window of the episode's YouTube caption track. 41 of 41 checkable occurrences: yes.
Zero replacements. The captions run straight through the spot, so the hallucination sits
beside real speech and never displaced any. The 6 unchecked ones are ep05's and ep12's,
whose caption files are not on disk.

FIVE SHAPES, because the hallucination arrives broken in several ways:

  1. Whole, standing on its own or dropped mid-sentence inside real speech.
  2. Wrapped in em dashes by the rewrite, which must go with it.
  3. Truncated by a block boundary, leaving a headless fragment after a speaker label
     (`[2:18:25] Haziq: maju dan memberi ganjaran ...`) or a tailless one before the break
     (`... Barisanan Sila berasa bebas untuk menyukai, melanggan,`).
  4. LAUNDERED BY THE REWRITE into a generic call to action with the channel names
     dropped: `[Silakan follow, like, subscribe kepada channel ini.]`, `Feel free to like,
     subscribe, and support this column.` Six of these, and each one interrupts unrelated
     speech -- ep50's lands in the middle of Rafizi talking about Farhan.
  5. The rewrite's own note ABOUT the hallucination, which is not speech either.

ONLY THE SPAN GOES, NEVER THE SENTENCE. The hallucination lands mid-sentence inside real
speech, and deleting the enclosing sentence would destroy the transcript:

  ... curi roti kena penjara seminggu [BOILERPLATE]
  Jadi kalau pada YB -- bukanlah YB ada akses kan, [BOILERPLATE]
  Itu menunjukkan ... Tan Sri Muhyiddin Yassin -- [BOILERPLATE] -- bahawa setakat ini ...

REPAIR IS LOCAL, and this is the second thing that had to be fixed rather than assumed. A
first version normalised punctuation across the WHOLE file with `([.,]) ?\\1+` -> `\\1`,
which collapses every `...` in the transcript into a single full stop. It would have
damaged all 98 files, and the dry run would not have shown it, because a dry run only
prints what it deletes. Repair now touches the join and nothing else.

  python scripts/remove_asr_boilerplate.py            # dry run, prints every edit
  python scripts/remove_asr_boilerplate.py --write

Verify by re-grepping the corpus, never by reading this tool's own count. Twice now a
pattern has reported a clean run while a lowercase instance survived (`cephlos`, then
`ultracel`).
"""
import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Unambiguously the hallucination: nobody on this podcast says "Der Spiegel" or
# "Diandian", and `menyukai, melanggan` is machine-translation register, not spoken Malay.
NARROW = re.compile(r"Der Spiegel|Diandian|menyukai, melanggan", re.I)
# The laundered form. Narrower than a bare `like, subscribe` on purpose: it needs the
# full call-to-action shape AND a channel-ish object, so an ordinary mention survives.
GENERIC = re.compile(
    r"(?:Silakan[ \t]+follow|Please[ \t]+follow|(?:Please[ \t]+)?[Ff]eel[ \t]+free[ \t]+to)"
    r"[^.!?\n\]]{0,60}?like,[ \t]*subscribe[^.!?\n\]]{0,60}?"
    r"(?:channel|column|columns|show|saluran|ruangan|lajur)[^.!?\n\]]{0,20}", re.I)
MARKER = re.compile(NARROW.pattern + "|" + GENERIC.pattern, re.I)

# What a LEFTOVER looks like. MARKER is not enough for this job: ep20's truncated
# `Sila berasa bebas untuk menyukai,` carries no channel name, so a MARKER-only survivor
# check reported a clean corpus while three fragments sat in it. Any appearance of a
# translationese lead-in is a leftover, whatever follows it.
LEFTOVER = re.compile(
    r"Sila[ \t]+(?:berasa[ \t]+)?(?:rasa[ \t]+)?bebas[ \t]+untuk|Der Spiegel|Diandian"
    r"|menyukai,[ \t]*melanggan|like,[ \t]*subscribe|\[aside about liking"
    # `[Ff]eel free to like` on its own. ep20's English file ends a turn on `Next. Feel
    # free to like,` with the rest in the next block, and a check keyed on `like,
    # subscribe` walked straight past it.
    r"|[Ff]eel[ \t]+free[ \t]+to[ \t]+like", re.I)

# How the boilerplate ENDS. It carries no sentence punctuation of its own, so a tail
# marker plus an optional terminal is the right-hand boundary.
TAIL = (r"(?:Diandian(?:'s)?|Der Spiegel|lajur ini|saluran ini|rancangan ini"
        r"|ruangan ini|channel ini|this[ \t]+(?:column|channel|show)|menyokong)")

# How it BEGINS, in two tiers, because the lead-ins are not equally safe.
#
# SAFE: nobody on this podcast says `Sila berasa bebas untuk`. It is translation register
# with no spoken equivalent, so any boilerplate continuation after it can go, even a
# fragment truncated before the channel names.
LEAD_SAFE = (r"(?:Sila[ \t]+(?:berasa[ \t]+)?rasa[ \t]+bebas[ \t]+untuk"
             r"|Sila[ \t]+berasa[ \t]+bebas[ \t]+untuk)")
# RISKY: these ARE spoken here. `Jangan lupa untuk melanggan` is a real plug for Rafizi's
# own channel, and ep16-ms has Haziq joking about having to make it. `Feel free to` is
# ordinary English. A fragment under these leads needs the hallucination's own comma list
# before it can be deleted.
LEAD_RISKY = (r"(?:Jangan[ \t]+lupa[ \t]+untuk|(?:Please[ \t]+)?[Ff]eel[ \t]+free[ \t]+to"
              r"|Silakan[ \t]+follow|Please[ \t]+follow)")
LEAD = f"(?:{LEAD_SAFE}|{LEAD_RISKY})"

# EVERY WHITESPACE CLASS HERE IS HORIZONTAL-ONLY, AND THAT IS THE MOST IMPORTANT LINE IN
# THIS FILE. `\s` matches newlines. With a vertical class in BRACKET_CLOSE, WHOLE matched ep12's
# `Sila berasa bebas untuk ... menyokong` and then swallowed the `\n\n` after it, welding
# the next speaker's block onto the previous turn:
#
#   before: `... dalam kerajaan. [BOILERPLATE]\n\n[1:09:24] Haziq: lajur ... Baik, baik`
#   after:  `... dalam kerajaan. [1:09:24] Haziq: Baik, baik`
#
# Four episodes lost a paragraph break that way -- ep12, ep37, ep42, ep46 -- and qa_check
# went from 0/68 to 4/68 on buried turn markers. The boilerplate never spans a newline
# within a single shape; block-straddling is what FRAGMENT and TAILLESS are for.
DASH = r"(?:[ \t]*(?:—|--)[ \t]*)?"
BRACKET_OPEN = r"\[?[ \t]*"
# The terminal can fall on EITHER side of the closing bracket. ep28-ms writes
# `[Silakan follow, like, subscribe kepada channel ini.]` -- full stop INSIDE -- and an
# earlier version that only allowed `].` left the bracket stranded in the sentence:
# `UBN yang disebut. ] Reaksi daripada media sosial`.
BRACKET_CLOSE = r"[ \t]*[.!?]?[ \t]*\]?[ \t]*[.!?]?"

SHAPES = [
    # The rewrite's note about the hallucination.
    # ep28 wrote `dalam 40%... [aside ...] ...then, even Indera Kayangan`. Both ellipses
    # exist only to bracket the omission, so they go with it. Leaving them produced
    # `40%....then`.
    ("ASIDE", re.compile(r"[ \t]*\.{0,3}[ \t]*\[aside about liking[^\]]*\][ \t]*\.{0,3}[ \t]*",
                         re.I)),
    # No GENERIC shape. It existed to catch the laundered form, and its fixed-length
    # trailing run cut `der` in half, leaving `r Spiegel and Diandian` in ep21. WHOLE
    # covers all six laundered instances now that `channel ini` is a tail marker, because
    # their lead-ins (`Silakan follow`, `Please follow`, `Feel free to`) are already in
    # LEAD. GENERIC survives below only as a DETECTOR, for deciding which files to open.
    # A turn whose ENTIRE body is a truncated lead: `**Rafizi:** Berasa bebas...`
    ("EMPTY_LEAD", re.compile(
        r"^(?:\*\*[^*\n]{1,40}:\*\*|\[[\d:]+\][ \t]*[^:\n]{1,40}:)[ \t]*"
        r"(?:Sila[ \t]+)?(?:Berasa|berasa)[ \t]+bebas[ \t]*\.{2,}[ \t]*$"
        r"|^(?:\*\*[^*\n]{1,40}:\*\*|\[[\d:]+\][ \t]*[^:\n]{1,40}:)[ \t]*"
        r"(?:Felt|Feel)[ \t]+free[ \t]*\.{2,}[ \t]*$", re.M)),
    # Headless fragment after a speaker label, with an optional leading ellipsis.
    ("FRAGMENT", re.compile(
        r"(?P<keep>^(?:\[[\d:]+\][ \t]*)?[^:\n]{1,40}:[ \t]*|^\*\*[^*\n]{1,40}:\*\*[ \t]*)"
        r"(?:—|--)?[ \t]*\.{0,3}[ \t]*"
        r"(?:untuk[ \t]+menyukai|menyukai|melanggan|maju[ \t]+dan|memuji[ \t]+dan|memajukan[ \t]+dan"
        r"|memberi[ \t]+maju|membuat[ \t]+dan|lajur|the[ \t]+Der[ \t]+Spiegel|to[ \t]+like|subscribe"
        r"|comment[ \t]+and|follow[ \t]+and|share[ \t]+and)"
        r"[^.!?\n]*?" + TAIL + r"[^.!?\n]*[.!?]?[ \t]*", re.I | re.M)),
    # Whole, including the mid-sentence intrusion and its dashes.
    # The body is GREEDY and there is NO trailing run after the tail. Both details were
    # bugs. A lazy body stopped at the first `menyokong`, which sits mid-boilerplate, and
    # left `lajur -- der Spiegel dan Diandian,` behind. A greedy trailing run then ate
    # past the end into ep21's real speech, `poyo -- okay masa bantu poyo.` Greedy body up
    # to the LAST tail marker, and stop there.
    ("WHOLE", re.compile(DASH + BRACKET_OPEN + LEAD + r"[^.!?\n\]]*" + TAIL
                         + r",?" + BRACKET_CLOSE + DASH, re.I)),
    # Tailless remainder before a block break: a lead that runs to end of line with no
    # channel name to anchor on.
    #
    # THE COMMA PAIR IS LOAD-BEARING. `Jangan lupa untuk melanggan` is REAL SPEECH on this
    # show -- the hosts plug Rafizi's own channel, and ep16-ms has Haziq joking about
    # having to (`melanggan dan melanggan, celaka teruk`). It is also one of the
    # hallucination's lead-ins. Every word of the real plug is in LEXICON, so the guard
    # cannot separate them; only the shape can. The hallucination always runs `menyukai,
    # melanggan` as a comma list, and the real plug never does.
    ("TAILLESS", re.compile(
        DASH + BRACKET_OPEN + r"(?:"
        # Under a SAFE lead, any boilerplate continuation goes. ep20 breaks the block
        # after `Sila berasa bebas untuk menyukai,` with `melanggan, maju dan ...` in the
        # next turn, so requiring the comma pair here left three real fragments behind
        # -- and MARKER could not see them, so the verifier called it clean.
        + LEAD_SAFE + r"[ \t]*(?:menyukai|melanggan|suka|langgan)[^.!?\n]*?"
        + r"|"
        # Under a RISKY lead, only the comma list qualifies.
        + LEAD_RISKY + r"[ \t]*menyukai,[ \t]*melanggan[^.!?\n]*?"
        + r")(?=[ \t]*$)", re.I | re.M)),
    # The English equivalents, both abandoned at a block break. ep12 gets as far as
    # `Feel free to like, subscribe, and give a reward to support—`; ep20 stops dead at
    # `Next. Feel free to like,` with the rest of it in the following turn. Both are
    # translations of a Malay original this tool has already established as the
    # hallucination, and `like,` ending a paragraph is not a sentence anyone speaks.
    ("TAILLESS_EN", re.compile(
        DASH + BRACKET_OPEN + r"(?:Please[ \t]+)?[Ff]eel[ \t]+free[ \t]+to" + r"(?:"
        + r"[^.!?\n]{0,40}?like,[ \t]*subscribe[^.!?\n]*?support(?:ing)?"
        + r"|[ \t]*like,"
        + r")" + DASH + r"(?=[ \t]*$)", re.I | re.M)),
]

# A speaker label left holding no words at all. Asserting one unidentified person said
# nothing is worse than dropping the line.
EMPTY_TURN = re.compile(
    r"^(?:\*\*[^*\n]{1,40}:\*\*|\[[\d:]+\]\s*[^:\n]{1,40}:)[ \t]*$\n?", re.M)

# Every word the hallucination is built from, in all four languages it appears in. A
# TRUNCATED span cannot contain a channel name -- ep55's stops at `menyukai,` and ep05's
# at `Berasa bebas...` -- so those shapes are guarded by requiring that EVERY word in the
# span comes from this list. Real speech never does; it always brings a word from outside.
LEXICON = {
    "sila", "silakan", "berasa", "rasa", "bebas", "untuk", "menyukai", "melanggan",
    "maju", "memaju", "memajukan", "memuji", "membuat", "memberi", "dan", "ganjaran",
    "menyokong", "sokongan", "lajur", "laluan", "saluran", "ruangan", "rancangan",
    "kepada", "ini", "der", "spiegel", "diandian", "jangan", "lupa",
    "please", "feel", "felt", "free", "to", "like", "liking", "subscribe", "subscribing",
    "comment", "follow", "share", "and", "give", "rewards", "reward", "support",
    "supporting", "boost", "forward", "the", "this", "column", "columns", "channel",
    "channels", "show", "s", "aside", "about", "omitted", "from", "context", "of",
    "for", "in", "a", "giving", "our",
    # ep21's interview-ms.md uses the short Malay forms throughout.
    "suka", "langgan", "beri", "sokong",
}
WORD = re.compile(r"[\w']+")
# Shapes whose span is complete enough to carry the giveaway vocabulary.
NEEDS_MARKER = {"ASIDE", "WHOLE"}


# EMPTY_LEAD deletes the whole line, speaker label included, because the turn holds
# nothing but a truncated lead. The label's words are not boilerplate, so they are
# stripped before the lexicon check rather than added to the lexicon -- putting speaker
# names in there would blind the guard everywhere else.
LABEL_PREFIX = re.compile(r"^(?:\*\*[^*\n]{1,40}:\*\*|\[[\d:]+\]\s*[^:\n]{1,40}:)[ \t]*")


def guard(name, span):
    """Refuse a deletion that is not provably the hallucination.

    Two ways to prove it, in order of strength. The giveaway vocabulary settles it
    outright, whatever the shape. Failing that, a TRUNCATED span qualifies only if every
    word in it comes from the hallucination's own lexicon, because a fragment cut off
    before the channel names has no giveaway left to carry.
    """
    if name == "EMPTY_LEAD":
        span = LABEL_PREFIX.sub("", span)
    # THE INVARIANT, applied to every shape. The hallucination is built entirely from the
    # lexicon, so a span holding any other word has reached into real speech. This also
    # catches a pattern that stops mid-word: `... for supporting -- de` leaves `de`, which
    # is not in the lexicon, and the deletion is refused instead of shipping `r Spiegel`.
    outside = [w for w in (w.removesuffix("'s") for w in WORD.findall(span.lower()))
               if w not in LEXICON]
    if outside:
        raise AssertionError(
            f"{name} span carries non-boilerplate word(s) {outside}: {span!r}")
    # The complete shapes must ALSO carry the giveaway vocabulary. Lexicon-only is not
    # enough for them: `dan ini untuk` is all lexicon and all real Malay.
    if name in NEEDS_MARKER and not MARKER.search(span):
        raise AssertionError(f"{name} matched without the marker: {span!r}")


def targets():
    return (sorted(ROOT.glob("episodes/*/*/raw.md"))
            + sorted(ROOT.glob("episodes/*/*/interview.md"))
            + sorted(ROOT.glob("episodes/*/*/interview-en.md"))
            + sorted(ROOT.glob("episodes/*/*/interview-ms.md")))


# Every character `join` drops beyond the matched span, so the verifier can audit them
# instead of taking the seam repair on trust.
SEAM_DROPS = []


def join(left, right):
    """Repair only the seam a deletion leaves behind."""
    l_stripped = left.rstrip(" \t")
    r_stripped = right.lstrip(" \t")
    # `X -- <span>, Y` and `X, <span> Y` both leave a doubled or orphaned mark.
    if l_stripped[-1:] in ".,!?;:" and r_stripped[:1] in ".,!?;:":
        SEAM_DROPS.append((l_stripped[-40:], r_stripped[:40]))
        r_stripped = r_stripped[1:].lstrip(" \t")
    if not l_stripped or not r_stripped:
        return l_stripped + r_stripped
    if l_stripped[-1] == "\n" or r_stripped[0] == "\n":
        return l_stripped + r_stripped
    if r_stripped[0] in ".,!?;:":
        return l_stripped + r_stripped
    return l_stripped + " " + r_stripped


def scrub(text, report):
    original_text = text
    for name, rx in SHAPES:
        while True:
            m = rx.search(text)
            if not m:
                break
            keep = m.groupdict().get("keep") or ""
            span = text[m.start() + len(keep):m.end()]
            guard(name, span)
            report.append((name, span.strip(),
                           text[max(0, m.start() - 55):m.start()].replace("\n", "\\n"),
                           text[m.end():m.end() + 55].replace("\n", "\\n")))
            text = join(text[:m.start()] + keep, text[m.end():])
    # Only now, after every shape has run, can a label be left with nothing.
    while True:
        m = EMPTY_TURN.search(text)
        if not m:
            break
        report.append(("EMPTY_TURN", m.group(0).strip(), "", ""))
        text = text[:m.start()] + text[m.end():]
    # Deleting a whole turn leaves its blank line behind, so ep05 came out with three
    # blank lines where Rafizi's `Berasa bebas...` had been. Collapsing is safe ONLY where
    # the file had no such run to begin with; otherwise a pre-existing gap would be
    # silently reformatted, and this tool has no business doing that.
    if not re.search(r"\n{3,}", original_text) and re.search(r"\n{3,}", text):
        text = re.sub(r"\n{3,}", "\n\n", text)
        # The span field stays EMPTY on purpose: it is whitespace only, and any words put
        # here would be double-counted as deleted text by the verifier's word arithmetic.
        report.append(("BLANK_RUN", "",
                       "collapsed blank lines left by a deleted turn", ""))
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    files = touched = edits = 0
    by_shape = {}
    for path in targets():
        original = path.read_text(encoding="utf-8")
        if not MARKER.search(original):
            continue
        files += 1
        report = []
        text = scrub(original, report)
        if text == original:
            print(f"!! {path.relative_to(ROOT)}: marker present but nothing matched")
            continue
        touched += 1
        edits += len(report)
        print(f"\n{path.relative_to(ROOT / 'episodes')}  ({len(report)} edit(s))")
        for name, span, before, after in report:
            by_shape[name] = by_shape.get(name, 0) + 1
            if not args.quiet:
                print(f"  [{name}] ...{before}<<<{span[:88]}>>>{after}...")
        if args.write:
            path.write_text(text, encoding="utf-8")

    print(f"\n{files} file(s) carried the marker, {touched} changed, {edits} span(s) "
          f"removed{'' if args.write else ' (dry run)'}")
    for name, n in sorted(by_shape.items()):
        print(f"  {name}: {n}")


if __name__ == "__main__":
    main()
