"""Re-extract an episode's `topics:`, and keep it only if it covers more of the episode.

WHY THE OLD LISTS ARE THIN. `META_PROMPT_TEMPLATE` gave detailed instructions for hosts
and guests and said NOTHING about topics -- no count, no coverage requirement, no
instruction to work through the whole episode. So the model was free to return one line
for three hours, and for five episodes it did: ep25, ep29, ep34, ep35 and ep37 each carry
a single topic. The prompt now states what a topic list has to do; this re-runs it.

THE SCORE IS THE SHOW'S OWN CHAPTER MARKERS. 39 of the 68 YouTube descriptions carry
timestamped chapter titles written by the people who made the episode -- ep35 has nine,
including "Bloomberg Kasi Kantoi Azam Baki" and "Isu Rumah Ibadat", which is exactly what
its title promises and its one-line topic list omits. Coverage is the share of those
chapters that some topic line accounts for. It is a real external reference rather than a
model judging itself, which is the same reason the QA suite checks transcripts against
YouTube's captions instead of against the transcript.

  coverage   share of chapters whose distinctive words appear in some topic line
  count      number of topic lines

COVERAGE decides; line count only breaks a tie. Requiring both to be non-decreasing was
the first rule here and it discarded the best results in the batch -- ep28's candidate
covered 15/15 chapters against 9/15 and lost on having 16 lines instead of 19. Same
promote-or-restore shape as `gate_rewrite.py`, and for the same reason: re-running a model
is a coin flip, so nothing overwrites a good list for being newer.

EPISODES WITH NO CHAPTERS CANNOT BE SCORED THIS WAY, and there are 29 of them. They fall
back to line count, which is weak -- read the result before trusting it.

  python scripts/gate_topics.py --report            # coverage for all 68, no calls
  python scripts/gate_topics.py ep35 ep29
  python scripts/gate_topics.py ep35 --write
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_topic_index import segments_by_video, episodes
from common import read_frontmatter_body, set_frontmatter_list

ROOT = Path(__file__).resolve().parent.parent
DERIVED = ["interview.md", "interview-en.md", "interview-ms.md"]
# Words that carry no subject: Malay and English function words, plus the show's furniture.
# A chapter counts as covered when its remaining words overlap a topic line.
STOP = set("""
the a an and or of to in on for with at by from is are was were be been as that this it
its their his her our your not no but if so than then there here what why how who whom
which when where all any some more most other another such only own same too very can
will just don should now dan atau untuk dengan pada dari yang ini itu ada tak tidak kita
saya dia mereka kami awak anda apa siapa mana bila kenapa macam jadi tapi kalau sebab
lagi juga pun sahaja saja memang akan sudah dah belum masih boleh nak mahu kena buat
pergi datang tengok cakap kata rasa tahu faham dapat bagi ambil letak lepas masa hari
tahun bulan orang semua banyak sikit besar kecil baik okey betul salah intro outro
episod episode ybm rafizi ramli soalan segmen bahagian part
""".split())


def words(text):
    return {w for w in re.findall(r"[A-Za-z][\w'-]{2,}", text.casefold())
            if w not in STOP}


def coverage(topics, chapters):
    """(covered, total) chapters accounted for by some topic line."""
    if not chapters:
        return 0, 0
    blob = words(" ".join(topics))
    covered = 0
    for _, label in chapters:
        want = words(label)
        # A chapter with no content words of its own cannot be missed by a topic list.
        if not want or want & blob:
            covered += 1
    return covered, len(chapters)


def read_topics(ep_dir):
    fm, _ = read_frontmatter_body(ep_dir / "interview.md")
    return list(fm.get("topics") or [])


def write_topics(ep_dir, topics):
    """Write the new list into all three published files, leaving bodies untouched.

    Surgical, via `common.set_frontmatter_list`. The first version of this used
    read_frontmatter_body + frontmatter_md and deleted the "# Interview" heading from
    every file it wrote -- 147 of them -- because that pair is asymmetric.
    """
    for name in DERIVED:
        path = ep_dir / name
        if path.exists():
            set_frontmatter_list(path, "topics", topics)


def extract(ep_dir, engine_name):
    from check_language_drift import strip_frontmatter
    text = strip_frontmatter((ep_dir / "interview.md").read_text(encoding="utf-8"))
    if engine_name == "claude":
        import lib_claude_rewrite as engine
        client = None
    else:
        import lib_gemini as engine
        client = engine.make_client()
    return engine.extract_metadata(client, text)["topics"]


def verdict(old_cov, old_n, new_cov, new_n, total):
    """COVERAGE decides. Line count only breaks a tie.

    An earlier version required BOTH coverage and line count to be non-decreasing, and it
    threw away the best results in the batch: ep28's candidate covered 15/15 chapters
    against the incumbent's 9/15 and was rejected for having 16 lines instead of 19, and
    ep13's 17/18 against 11/18 was rejected for 14 against 15. Line count is a proxy for
    thoroughness; chapter coverage is the thing itself, and a shorter list that accounts
    for more of the episode is a better list.
    """
    if total:
        if new_cov > old_cov:
            return True, (f"PROMOTE: chapters {old_cov}/{total} -> {new_cov}/{total}, "
                          f"lines {old_n} -> {new_n}")
        if new_cov < old_cov:
            return False, (f"REJECT: chapters {old_cov}/{total} -> {new_cov}/{total}, "
                           f"coverage lost")
        if new_n > old_n:
            return True, (f"PROMOTE: coverage level at {new_cov}/{total}, more detail: "
                          f"lines {old_n} -> {new_n}")
        return False, (f"REJECT: coverage level at {new_cov}/{total} and no more detail "
                       f"({old_n} -> {new_n} lines)")
    if new_n <= old_n:
        return False, f"REJECT: no chapters to score and {new_n} lines against {old_n}"
    return True, f"PROMOTE: no chapters to score, lines {old_n} -> {new_n} (READ IT)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="*")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--engine", default="claude", choices=["claude", "gemini"])
    args = ap.parse_args()

    segs = segments_by_video()
    eps = {tag: (vid, d, topics) for _, tag, _, vid, d, topics in episodes()}

    if args.report:
        rows = []
        for tag, (vid, d, topics) in eps.items():
            cov, total = coverage(topics, segs.get(vid, []))
            rows.append((total and cov / total, total, len(topics), tag))
        rows.sort(key=lambda r: (r[1] == 0, r[0], r[2]))
        print(f"{'ep':12}{'topics':>7}{'chapters':>10}{'covered':>9}")
        for pct, total, n, tag in rows:
            cov = f"{int(pct * total)}/{total}" if total else "-"
            print(f"{tag:12}{n:>7}{total or '-':>10}{cov:>9}")
        scorable = [r for r in rows if r[1]]
        print(f"\n{len(scorable)} of {len(rows)} episodes have chapter markers to score "
              f"against; mean coverage {sum(r[0] for r in scorable) / len(scorable):.0%}")
        return

    for tag in args.tags:
        match = [t for t in eps if t.endswith(tag) or t == tag]
        if len(match) != 1:
            raise SystemExit(f"{tag}: matched {match or 'nothing'}")
        vid, d, old = eps[match[0]]
        chapters = segs.get(vid, [])
        old_cov, total = coverage(old, chapters)
        print(f"\n{match[0]}  {d.name[:52]}")
        print(f"  incumbent  {len(old)} line(s), {old_cov}/{total or '-'} chapters covered")
        new = extract(d, args.engine)
        new_cov, _ = coverage(new, chapters)
        print(f"  candidate  {len(new)} line(s), {new_cov}/{total or '-'} chapters covered")
        ok, why = verdict(old_cov, len(old), new_cov, len(new), total)
        print(f"  {why}")
        if ok and args.write:
            write_topics(d, new)
            print("  WROTE")
        elif ok:
            print("  would write -- pass --write")


if __name__ == "__main__":
    main()
