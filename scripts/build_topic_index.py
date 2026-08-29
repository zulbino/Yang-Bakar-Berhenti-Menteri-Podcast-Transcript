"""Generate TOPICS.md: what each issue was discussed in, across every episode.

WHY THIS EXISTS. An issue in this podcast spans episodes -- PADU is discussed in 23 of
them, Tabung Haji in 17, the Johor-Singapore SEZ in 10 -- and until now nothing connected
them. The `topics:` frontmatter is good and was invisible, sitting in 68 separate files,
while README.md (the file a search engine actually reads) listed episodes only by number,
date and title. So a reader who wanted "what has he said about PADU" had to open 23 files
and already know which ones.

WHAT IT CANNOT DO, stated in the output itself because it matters. This index shows WHAT
WAS SAID AND WHEN, with a link into the video. It does not adjudicate whether a claim is
true, or who said a thing first. "Was PADU a bad idea" and "did Rafizi originate the SEZ"
need sources beyond one podcast; what this can give is the primary record, in order, which
is the input to answering them and not the answer.

HOW THE ENTRIES ARE CHOSEN -- mechanically, so the index cannot quietly editorialise:
  Issues and institutions   ALL-CAPS acronyms of 3-8 chars appearing in >= MIN_EPISODES
                            episodes. Currency (`RM1`, `RM100`) is excluded; it is a
                            number, not a subject.
  People and bodies         Capitalised multiword phrases in >= MIN_EPISODES episodes,
                            matched WITHIN a line so a phrase cannot form across a line
                            break (an earlier version produced "Bahasa / Melayu" that way).
  Per-episode topics        The `topics:` frontmatter verbatim. Not re-worded here: it is
                            the only human-authored description of each episode.

Mention counts come from interview.md, the mixed-language published file, because that is
what a reader lands on. First-mention timestamps come from raw.md, which is the only file
that still carries them, and become YouTube links seeked to that second.

  python scripts/build_topic_index.py            # writes TOPICS.md
"""
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import episode_number, episode_path, show_era_dir

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "TOPICS.md"
MIN_EPISODES = 5
# Or heavily discussed in ONE episode: a deep dive is as searchable as a
# recurring thread, and spread alone dropped AUKU (49 uses in ep60).
MIN_IN_ONE_EPISODE = 12
TOP_N = 4              # how many "most discussed in" episodes to link per topic

ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{2,7}\b")
# Within a line only -- `[ ]` not `\s`, so a phrase cannot straddle a newline.
PHRASE = re.compile(r"\b([A-Z][a-z][\w'’-]*(?:[ ]+[A-Z][a-z][\w'’-]*){1,2})\b")
RAW_TURN = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]\s*[^:\n]{1,40}:\s*(.*)$")

# Currency amounts and the show's own furniture: not subjects anyone searches for.
SKIP_ACRO = {"YBM", "YBHM", "YBKM", "YANG", "THE", "AND", "OKEY", "OKAY", "TIDAK", "SAYA",
             "KITA", "DAN", "INI", "ITU", "APA", "TAPI", "JADI", "LAH", "KAN", "YES", "NOT",
             "FOR", "YOU", "WAS", "ARE", "BUT", "ALL", "CAN", "HAS", "HIS", "SEBAB", "EPISOD",
             "NAK", "ADA", "PUN", "DIA", "TAK", "MACAM", "SEMUA", "BILA", "KALAU", "BOLEH"}
SKIP_PHRASE = {"Rafizi Ramli", "Podcast Yang Berhenti", "Yang Berhenti Menteri",
               "Yang Bakar Menteri", "Ya Allah", "Hidup Keras", "Bahasa Melayu",
               "Prime Minister", "Perdana Menteri"}

# A REVIEWED map, one entry per decision, in the spirit of fix_proper_nouns.py -- not
# algorithmic normalisation. Counting variants separately fragments exactly the subject a
# reader came for: the Johor-Singapore SEZ splits into JSSEZ (7 episodes), SEZ (5) and
# JS-SEZ (4, below the cut entirely), so no row shows the real 10-episode span. Only true
# synonyms are merged.
#
# NOT merged, though it looks tempting: GLC and GLIC are different things (a
# government-linked company versus a government-linked INVESTMENT company), and PRU is
# general elections in general while GE15 is one of them.
ALIASES = {
    "MACC": "SPRM",     # same body, English name
    "KWSP": "EPF",      # same body, Malay name
    "JSSEZ": "JS-SEZ",
    "SEZ": "JS-SEZ",    # in this corpus every SEZ mention is the Johor-Singapore one
    "IRB": "LHDN",      # Inland Revenue Board = Lembaga Hasil Dalam Negeri
}
CANON_LABEL = {
    "SPRM": "SPRM / MACC",
    "EPF": "EPF / KWSP",
    "JS-SEZ": "JS-SEZ (Johor-Singapore SEZ)",
    "LHDN": "LHDN / IRB",
}


# --- README teaser -------------------------------------------------------------------
# README.md is the file a search engine actually reads, and it listed episodes only by
# number, date and title -- no subject words at all. This puts the recurring subjects
# there, between markers, the same way build_episode_index.py maintains the episode
# tables. Anchors point INTO the two TOPICS.md sections; without them every link landed
# at the top of a 1,400-line file.
# Built from chr(10) rather than an escape, because writing this module through a shell
# heredoc collapsed the backslash and left a raw newline inside the string literal.
BLANK = chr(10) * 2
TEASER_BEGIN = "<!-- BEGIN TOPIC TEASER -- generated by scripts/build_topic_index.py -->"
TEASER_END = "<!-- END TOPIC TEASER -->"
ISSUES_ANCHOR = "TOPICS.md#issues-institutions-and-policies"
PEOPLE_ANCHOR = "TOPICS.md#people-bodies-and-places"
# Party names ARE the show's subject matter, not a topic to filter it by, and the rest is
# generic business/governance vocabulary nobody searches an archive for.
TEASER_SKIP = {"PKR", "PAS", "UMNO", "DAP", "MCA", "MIC", "AMK", "PN", "BN", "PH", "PPBM",
               "CEO", "GDP", "NGO", "KPI", "CFO", "COO", "SOP", "FAQ", "API", "PDF", "URL",
               "AGM", "EGM", "KSU", "VIP", "IPO"}
TEASER_TEXT = {
    "README.md": (
        "## Search by topic",
        "An issue here usually spans several episodes, and a position can change across "
        "them, so reading one episode can mislead you about the argument as a whole. "
        "**[TOPICS.md](TOPICS.md) indexes every recurring subject** -- which episodes "
        "discuss it, which discuss it most, and a link into the video at the first mention.",
        "Most-discussed subjects, with the number of episodes covering each:",
        "People and bodies covered most often:",
        "This is a record of **what was said and when**, not a fact-check. It does not "
        "establish whether a claim is correct, or who said something first -- those need "
        "sources beyond one podcast. What it gives you is the primary material, in order, "
        "with a timestamp so you can hear it yourself.",
    ),
    "README.ms.md": (
        "## Cari mengikut topik",
        "Satu isu di sini biasanya merangkumi beberapa episod, dan pendirian boleh berubah "
        "antaranya, jadi membaca satu episod sahaja boleh mengelirukan anda tentang hujah "
        "keseluruhannya. **[TOPICS.md](TOPICS.md) mengindeks setiap subjek berulang** -- "
        "episod mana yang membincangkannya, mana yang paling banyak, dan pautan ke dalam "
        "video pada sebutan pertama.",
        "Subjek yang paling banyak dibincangkan, dengan jumlah episod yang membincangkannya:",
        "Individu dan badan yang paling kerap disebut:",
        "Ini ialah rekod **apa yang diucapkan dan bila**, bukan semakan fakta. Ia tidak "
        "menentukan sama ada sesuatu dakwaan itu benar, atau siapa yang menyebutnya dahulu "
        "-- itu memerlukan sumber di luar satu podcast. Apa yang ada di sini ialah bahan "
        "primer, mengikut urutan, dengan cap masa supaya anda boleh mendengarnya sendiri.",
    ),
}


def inject_teaser(filename, acro, phrase):
    heading, intro, subj_lead, ppl_lead, caveat = TEASER_TEXT[filename]
    rows = sorted(((CANON_LABEL.get(k, k), len(v)) for k, v in acro.items()
                   if k not in TEASER_SKIP), key=lambda r: (-r[1], r[0]))[:22]
    names = sorted(((p, len(v)) for p, v in phrase.items()),
                   key=lambda r: (-r[1], r[0]))[:14]
    sep = " &middot; "
    section = BLANK.join([
        TEASER_BEGIN, heading, intro, subj_lead,
        sep.join(f"[{n}]({ISSUES_ANCHOR}) ({c})" for n, c in rows),
        ppl_lead,
        sep.join(f"[{n}]({PEOPLE_ANCHOR}) ({c})" for n, c in names),
        caveat, TEASER_END])
    path = ROOT / filename
    text = path.read_text(encoding="utf-8")
    if TEASER_BEGIN in text and TEASER_END in text:
        head, rest = text.split(TEASER_BEGIN, 1)
        text = head + section + rest.split(TEASER_END, 1)[1]
    else:
        # First run: sit above the episode tables, so subject words come before 68 rows.
        text = text.replace("<!-- BEGIN EPISODE LIST",
                            section + BLANK + "<!-- BEGIN EPISODE LIST", 1)
    path.write_text(text, encoding="utf-8")
    return len(rows), len(names)


def to_seconds(stamp):
    parts = [int(p) for p in stamp.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def episodes():
    """[(sort_key, tag, date, title, video_id, dir, topics)] oldest first."""
    out = []
    for d in sorted((ROOT / "episodes").glob("*/*")):
        pub = d / "interview.md"
        if not pub.exists():
            continue
        text = pub.read_text(encoding="utf-8")
        def field(name):
            m = re.search(rf"^{name}:\s*'?(.*?)'?$", text, re.M)
            return m.group(1) if m else ""
        topics = re.search(r"^topics:\n((?:- .*\n)+)", text, re.M)
        topics = [t[2:].strip() for t in topics.group(1).splitlines()] if topics else []
        num = re.search(r"-(ep\d+)-", d.name)
        show = "YBhM" if "berhenti" in str(d) else "YBkM"
        out.append((field("publish_date"), f"{show} {num.group(1) if num else '?'}",
                    field("publish_date"), field("title"), field("video_id"), d, topics))
    return sorted(out)


def first_mention(d, term):
    """(seconds, quote) of the first raw.md turn containing `term` or any of its aliases.

    Must search the aliases too: the canonical label is what the index prints, not
    necessarily what anyone wrote. `JS-SEZ` is the row heading while ep51's raw.md says
    `JSSEZ`, so searching the canonical form alone found nothing and the jump link came
    back empty on exactly the topic the alias map was added to fix.
    """
    raw = d / "raw.md"
    if not raw.exists():
        return None
    variants = [term] + [k for k, v in ALIASES.items() if v == term]
    rx = re.compile("|".join(re.escape(v) for v in variants))
    for line in raw.read_text(encoding="utf-8").splitlines():
        m = RAW_TURN.match(line)
        if m and rx.search(m.group(2)):
            hit = rx.search(m.group(2))
            lo = max(0, hit.start() - 60)
            return to_seconds(m.group(1)), m.group(2)[lo:hit.end() + 90].strip()
    return None


def collect(eps):
    acro, phrase = defaultdict(dict), defaultdict(dict)
    for _, tag, _, _, _, d, _ in eps:
        text = (d / "interview.md").read_text(encoding="utf-8")
        for a in ACRONYM.findall(text):
            if a in SKIP_ACRO or re.fullmatch(r"RM\d+", a):
                continue
            a = ALIASES.get(a, a)
            acro[a][tag] = acro[a].get(tag, 0) + 1
        # JS-SEZ also appears hyphenated, which ACRONYM cannot match as one token.
        n = len(re.findall(r"JS-SEZ", text))
        if n:
            acro["JS-SEZ"][tag] = acro["JS-SEZ"].get(tag, 0) + n
        for line in text.splitlines():
            for p in PHRASE.findall(line):
                if p in SKIP_PHRASE:
                    continue
                phrase[p][tag] = phrase[p].get(tag, 0) + 1
    # Two ways in, because episode SPREAD alone misses the deep dives. AUKU is mentioned 49
    # times in ep60 -- it is in that episode's title -- and in one other episode, so a
    # spread-only rule of 5 dropped the very subject the episode is about. A term heavily
    # discussed in a single episode is exactly what someone searches for.
    def keep(m):
        return {k: v for k, v in m.items()
                if len(v) >= MIN_EPISODES or max(v.values()) >= MIN_IN_ONE_EPISODE}
    return keep(acro), keep(phrase)


def episode_keywords(eps, acro, phrase, n=6):
    """{tag: [term]} -- the terms most distinctive to each episode, for the README column.

    Ranked by TF-IDF, not raw count, because raw count returns the same words for every
    episode: PKR appears in 63 of 68, so it says nothing about which one you are reading.
    Weighting by how FEW episodes carry a term is what surfaces `AUKU` for ep60 (49 uses
    there, 1 anywhere else, and in that episode's own title) over the party names that
    dominate the whole corpus.

    Replaces printing the `topics:` sentences in the table. Those are accurate but long --
    "Reformasi gaji dan agenda 'second term' Anwar Ibrahim" -- and three of them made a row
    unreadable while still missing the headline subject, because the list is not ordered by
    importance: ep60 has "Pemansuhan AUKU" seventh of thirteen.
    """
    n_eps = len(eps) or 1
    pool = {}
    for src in (acro, phrase):
        for term, per_ep in src.items():
            pool[term] = per_ep
    out = {}
    for _, tag, _, _, _, d, _ in eps:
        scored = []
        for term, per_ep in pool.items():
            tf = per_ep.get(tag, 0)
            if not tf:
                continue
            scored.append((tf * math.log(n_eps / len(per_ep)), term))
        scored.sort(reverse=True)
        # Drop a term wholly contained in a higher-ranked one ("Azam" under "Azam Baki").
        picked = []
        for _, term in scored:
            if any(term in kept or kept in term for kept in picked):
                continue
            picked.append(CANON_LABEL.get(term, term))
            if len(picked) >= n:
                break
        # Keyed both ways: by display tag for this module, and by directory name so
        # build_episode_index.py can look one up without reproducing the tag format.
        out[tag] = picked
        out[d.name] = picked
    return out


def table(entries, eps, heading, blurb):
    by_tag = {tag: (d, vid) for _, tag, _, _, vid, d, _ in eps}
    lines = [f"\n## {heading}\n", blurb + "\n",
             "| Topic | Episodes | Most discussed in | Jump to first mention |",
             "|---|---|---|---|"]
    for term, per_ep in sorted(entries.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        top = sorted(per_ep.items(), key=lambda kv: -kv[1])[:TOP_N]
        cells = []
        for tag, n in top:
            d, _ = by_tag[tag]
            rel = f"episodes/{d.parent.name}/{d.name}/interview.md"
            cells.append(f"[{tag}]({rel}) &times;{n}")
        jump = ""
        heaviest_tag = top[0][0]
        d, vid = by_tag[heaviest_tag]
        fm = first_mention(d, term)
        if fm and vid:
            secs, _ = fm
            jump = (f"[{heaviest_tag} @ {secs // 3600}:{secs // 60 % 60:02d}:{secs % 60:02d}]"
                    f"(https://www.youtube.com/watch?v={vid}&t={max(0, secs - 5)}s)")
        label = CANON_LABEL.get(term, term)
        lines.append(f"| **{label}** | {len(per_ep)} | " + " · ".join(cells)
                     + f" | {jump} |")
    return "\n".join(lines)


def main():
    eps = episodes()
    acro, phrase = collect(eps)
    parts = ["""# Topic index

Every recurring subject in the archive, and which episodes it is discussed in. Built by
`scripts/build_topic_index.py` from the transcripts themselves, so it stays in step with
them.

**What this shows, and what it does not.** These are links to *what was said, and when*,
with a timestamp into the video so you can hear it. An issue here usually spans several
episodes and a position can change across them, which is the whole reason this page
exists -- reading one episode can mislead you about the argument as a whole.

It is **not** a fact-check. It does not establish whether a claim is correct, or who said
something first. Questions like "was PADU a bad idea" or "who originated the
Johor-Singapore SEZ" need sources beyond one podcast. What this gives you is the primary
record, in order, which is where answering them starts.

Every transcript is machine-generated and carries the accuracy caveats in
[README.md](README.md#license-and-disclaimer). Check the video before quoting anyone.
"""]
    parts.append(table(acro, eps, "Issues, institutions and policies",
                       f"Acronyms appearing in at least {MIN_EPISODES} episodes, ranked by "
                       f"how many episodes discuss them. Currency amounts are excluded."))
    parts.append(table(phrase, eps, "People, bodies and places",
                       f"Names and multiword terms appearing in at least {MIN_EPISODES} "
                       f"episodes."))

    parts.append("\n## Every episode, and what it covers\n")
    parts.append("Oldest first. Topics are the episode's own description, unedited.\n")
    for _, tag, date, title, vid, d, topics in eps:
        rel = f"episodes/{d.parent.name}/{d.name}/interview.md"
        parts.append(f"\n### {tag} &mdash; {date}\n")
        parts.append(f"[{title}](https://www.youtube.com/watch?v={vid}) &middot; "
                     f"[transcript]({rel})\n")
        for t in topics:
            parts.append(f"- {t}")
    OUT.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"wrote {OUT.name}: {len(acro)} acronym topic(s), {len(phrase)} name topic(s), "
          f"{len(eps)} episodes, {sum(len(e[6]) for e in eps)} episode topics")
    for readme in TEASER_TEXT:
        n_subj, n_ppl = inject_teaser(readme, acro, phrase)
        print(f"  {readme}: teaser with {n_subj} subject(s), {n_ppl} name(s)")


if __name__ == "__main__":
    main()
