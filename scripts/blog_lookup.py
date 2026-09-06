"""Resolve a garbled proper noun against Rafizi's own blog archive.

WHY. Every name incident in this corpus is the same shape: the ASR produces something that
is not a word, no check can tell a garbled real name from a correct one, and the corpus
cannot answer it from inside itself. `fix_proper_nouns.py` holds 48 owner-confirmed repairs
precisely because there was no better authority to consult.

rafiziramli.com is a better authority than a general web search for this corpus, because it
is the same speaker writing about the same material. ep62 demonstrates it: the episode
discusses a FELDA subsidiary paying "FIC London Hotel Limited" inside somewhere the caption
ASR rendered "Grand Consington". The archive has a 2017 post naming
`FIC London Hotel Pte Limited` as owner of the FELDA hotel `Grand Plaza Kensington`. Both
garbles resolved from one slug.

WHAT IT INDEXES, AND WHAT IT DELIBERATELY DOES NOT. Only the URL slugs from the public
sitemap. Slugs are the post titles, so they already carry the names, companies, acts and
acronyms -- which means we get the benefit without copying anyone's articles into this repo.
Nothing here stores or reproduces post text.

LIMITS, both of which matter when reading a result:

- **The archive stopped on 18 November 2022**, when the author entered government. It is
  strong on the pre-2022 exposes the podcast keeps referring back to (FELDA/FGV, 1MDB,
  Tabung Haji, PTPTN) and has nothing on post-2022 policy.
- **A match is a CANDIDATE WITH A CITATION, not permission to edit.** Same rule as
  everything else here: a name goes into raw.md and `fix_proper_nouns.py` only once the
  owner confirms it. This tool exists so the owner is shown a sourced candidate instead of
  being asked to remember.

    python scripts/blog_lookup.py "Grand Consington"
    python scripts/blog_lookup.py FIC London Hotel
    python scripts/blog_lookup.py --refresh "Kensington"
"""
import argparse
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITEMAP = "https://rafiziramli.com/sitemap-1.xml"
# Deliberately under data/_* so .gitignore keeps it out of the repo. The cache is ~900 of
# someone else's post titles, it regenerates from one sitemap fetch with --refresh, and this
# repo should not carry an index of another site's content.
CACHE = ROOT / "data" / "_rafizi_blog_slugs.json"
BASE = "https://rafiziramli.com/"

WORD_FLOOR = 0.70   # see score(): every known garble in this corpus clears it

# Malay function words and blog-title boilerplate. A slug is a whole sentence, so without
# this the fuzzy match keeps landing on connectives instead of names.
STOP = set("""
di ke dan atau yang untuk pada dari dengan ini itu adalah ada tidak bukan akan telah sudah
sebagai oleh kepada dalam atas bawah bagi apa siapa kenapa mengapa bila mana bagaimana
perlu mesti boleh dapat hanya juga masih lagi pun para kah lah nya se ber me men meng
bermakna berkenaan mengenai terhadap seperti kerana sebab jika kalau maka supaya agar
rm juta bilion ribu peratus tahun bulan hari
""".split())


def fetch_slugs():
    import requests

    r = requests.get(SITEMAP, headers={"User-Agent": "Mozilla/5.0 (transcript-archive)"},
                     timeout=60)
    r.raise_for_status()
    urls = re.findall(r"<loc>([^<]+)</loc>", r.text)
    slugs = []
    for u in urls:
        tail = u.replace(BASE, "").strip("/")
        parts = tail.split("/")
        if len(parts) >= 3 and parts[0].isdigit():
            slugs.append({"url": u, "year": parts[0], "month": parts[1],
                          "slug": parts[-1]})
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(slugs, indent=2), encoding="utf-8")
    return slugs


def slugs(refresh=False):
    if refresh or not CACHE.exists():
        return fetch_slugs()
    return json.loads(CACHE.read_text(encoding="utf-8"))


def words_of(slug):
    return [w for w in slug.split("-") if w]


def content_words(slug):
    return [w for w in words_of(slug) if w not in STOP and len(w) > 2]


def score(query_words, slug):
    """Mean of each query word's best match in the slug, plus the word it aligned to.

    Per-word-then-averaged, NOT a single best match anywhere. The first version took the
    maximum over all pairs, and on "Grand Consington" every FELDA hotel post scored 1.00 by
    matching the common word "grand" -- right cluster, useless ranking, and the match that
    mattered was invisible. Averaging makes a slug earn its rank by explaining the WHOLE
    query, so the post carrying both `grand` and `kensington` outranks one carrying only
    `grand`.

    Calibration, measured on this corpus's actual garbles: consington/kensington 0.80,
    zilinggong/xilinggong 0.90, wasiah/wasia 0.91, kuanti/kuan 0.80, perbeja/pepejal 0.71,
    and consington/plaza 0.00. A per-word floor of 0.70 separates all of them from noise.
    """
    candidates = content_words(slug) or words_of(slug)
    total, alignment, per_word = 0.0, [], {}
    for qw in query_words:
        best, best_word = 0.0, ""
        for sw in candidates:
            ratio = difflib.SequenceMatcher(None, qw, sw).ratio()
            if ratio > best:
                best, best_word = ratio, sw
        total += best
        per_word[qw] = best
        alignment.append(f"{qw}->{best_word}" if best >= WORD_FLOOR else f"{qw}->?")
    # THE MEAN ALONE IS NOT TRUSTWORTHY, and this is measured rather than hypothetical:
    # "atas wasiah" scored 0.71, over the floor, on a junk `atas`->`akta` match while
    # `wasiah` matched nothing at all. A short common word can carry the average while the
    # word actually being asked about fails. So a row counts as a candidate only if the
    # query's DISTINCTIVE word -- its longest -- clears the floor on its own. A
    # citation-shaped result built from noise is worse than no result: it looks sourced.
    distinctive = max(query_words, key=len)
    return total / len(query_words), " ".join(alignment), per_word[distinctive] >= WORD_FLOOR


def search(query, limit=6, refresh=False):
    qw = [w.lower() for w in re.findall(r"[\w']+", query)]
    if not qw:
        return []
    results = []
    for row in slugs(refresh):
        s, window, is_candidate = score(qw, row["slug"])
        if not is_candidate:
            continue
        results.append((s, window, row))
    results.sort(key=lambda r: r[0], reverse=True)
    return results[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("term", nargs="+")
    ap.add_argument("--refresh", action="store_true", help="re-fetch the sitemap")
    ap.add_argument("--limit", type=int, default=6)
    args = ap.parse_args()

    query = " ".join(args.term)
    hits = search(query, args.limit, args.refresh)
    print(f'"{query}"  -- {len(slugs())} posts indexed, archive ends 2022-11-18\n')
    if not hits:
        distinctive = max(re.findall(r"[\w']+", query), key=len)
        print(f"  NO CANDIDATE. Nothing in the archive matches {distinctive!r} above "
              f"{WORD_FLOOR:.2f}.")
        print("  That is an answer, not a failure. The archive covers the pre-2022 exposes")
        print("  (FELDA/FGV, 1MDB, Tabung Haji, PTPTN) and will not hold every name.")
        sys.exit(1)
    for s, window, row in hits:
        print(f"  {s:.2f}  matched {window!r}")
        print(f"        {row['year']}-{row['month']}  {row['slug'][:96]}")
        print(f"        {row['url']}")
    print("\nA match is a candidate with a citation. The owner confirms before anything "
          "reaches raw.md or fix_proper_nouns.py.")


if __name__ == "__main__":
    main()
