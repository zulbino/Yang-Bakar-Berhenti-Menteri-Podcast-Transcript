"""Correct ASR-garbled proper nouns across raw.md and the published files.

The local ASR and every rewrite engine garble Malaysian names, and the garble sometimes
outnumbers the correct spelling, so `check_proper_nouns.py` cannot infer which form is
right -- its `RARE_MAX = 4` even promotes a frequently-repeated garble to an "established
spelling". This applies corrections the owner has confirmed, one name at a time.

Every entry needs an owner decision behind it. A name is not a typo to be normalised by
majority vote: "Saleh" appears 266 times against "Salleh" 89, and those are not one
person spelled two ways -- which is exactly why this file holds a reviewed map rather
than a similarity heuristic.

  python scripts/fix_proper_nouns.py              # dry run, prints per-file counts
  python scripts/fix_proper_nouns.py --write

Each pattern uses an explicit negative lookahead rather than `\\b`, because a `\\b`
written into a file through a nested heredoc becomes a literal backspace and then
silently matches nothing (ENGINEERING_LOG 1.42).
"""
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (regex, replacement, why). Longest/most-specific first, so a broader pattern cannot
# eat a more specific one's match.
CORRECTIONS = [
    (r"Fuzi Asaleh",
     "Fuziah Salleh",
     "Fuziah Salleh, PKR secretary-general. Garbled once, in ep37, inside a list of "
     "PKR figures -- 'orang macam Fuzi Asaleh, orang macam Izzah, orang macam Ramanan' "
     "-- which is what identifies it."),
    (r"Fusyah Saleh(?![A-Za-z])",
     "Fuziah Salleh",
     "Third garble of the same name, once."),
    (r"Fuziah Saleh(?![A-Za-z])",
     "Fuziah Salleh",
     "Her SURNAME, correctable only as a two-word pattern. A blanket Saleh -> Salleh "
     "would be wrong: the corpus's 266 `Saleh` and 89 `Salleh` cover at least four "
     "referents, and 35 of them are Akmal Saleh, whose name really does take one L. "
     "Fuziah 13x `Saleh` / 3x `Salleh`, Mat 11/7, Tun Salleh Abas 0/1."),
    (r"Fuzia(?![A-Za-z])",
     "Fuziah",
     "Same person, first name only. 24 occurrences against 244 already correct, and all "
     "24 are unambiguously her: 'setiausaha agung, Fuzia', 'Fuzia Saleh boleh "
     "dipertimbangkan untuk kur[angkan]'. Owner-confirmed 2026-08-29."),
    # Ceplos, the online political persona. Verified to exist before any substitution:
    # the label began as netizen shorthand for a social-media figure known for political
    # video content. ep07 makes the referent certain from inside the corpus -- "kemunculan
    # yang kalau di media sosial orang panggil 'cheplos' kan? Aku pun kena pergi Google
    # cheplos ni apa". Established spelling is overwhelming and not a bare majority
    # argument: 478 correct in the published files against these 16, and every one of the
    # 16 was read in context first.
    (r"Cepulau(?![A-Za-z])",
     "Ceplos",
     "ep34 x6 across all three published files: 'Cepulau masih lagi macam biasa ... dia "
     "dalam bubble dia'. Gemini's audio read of the same seconds heard 'Che Pblos', so "
     "two independent ASRs mangled one name two ways."),
    (r"Cephlos(?![A-Za-z])",
     "Ceplos",
     "raw x7, ep26/ep27/ep41: 'Walaupun Cephlos tak puas hati', 'ada ayat-ayat Cephlos "
     "ni', 'mungkin Cephlos yang repost'."),
    (r"cephlos(?![A-Za-z])",
     "ceplos",
     "One lowercase instance, ep41 interview.md: 'ini mungkin cephlos yang repost'. "
     "Missed by the capitalised entry above -- which is the argument for verifying a "
     "substitution by re-grepping rather than by reading the tool's own count."),
    (r"Cheplos(?![A-Za-z])",
     "Ceplos",
     "Capitalised form of the ep07 garble; kept separate from the lowercase entry so "
     "running-text case is preserved -- the corpus uses `ceplos` lowercase 222 times."),
    (r"cheplos(?![A-Za-z])",
     "ceplos",
     "ep07 x10 across the three published files, inside the quoted phrase where Rafizi "
     "says he had to look the term up."),
    # Farhash Wafa Salvador Rizal Mubarak, Anwar's former political secretary, the MMAG /
    # HeiTech Padu shareholder. Owner-identified 2026-08-29 and verified: Wikipedia, and The
    # Edge on his RM97.48m MMAG loss -- a figure that is in ep31's own FOLDER NAME
    # (`ep31-dpa-sprm-farhash-rugi-rm97-5-juta`), so the corpus knew the name while the text
    # garbled it. The corpus also settles it from inside: raw ep41 writes the full
    # `Datuk Seri Farhaj Wafa Salvador Rizal Mubarak`.
    #
    # `Farhan` is deliberately NOT in this list. It is the CO-HOST's name -- 3,279 speaker
    # labels read `Farhan (Pa'an)` -- and it is ALSO used for Farhash in body text
    # (`sama ada Fuziah ke Farhan ke, Setiausaha Politik Datuk Seri Anwar ni`). One line even
    # distinguishes them mid-sentence. Those need reading one at a time; a pattern would
    # rename the co-host in thousands of places.
    (r"Farhad Hashim",
     "Farhash Wafa Salvador",
     "ep31's frontmatter summary, x3 files: 'the Farhad Hashim/MMAG share transaction "
     "controversy'. Two errors in one -- wrong given name and a surname he does not have. "
     "Listed before the bare `Farhad` entry so the more specific pattern wins."),
    (r"Farhaj(?![A-Za-z])", "Farhash",
     "645 occurrences (500 published, 145 raw). Never the co-host: no speaker label "
     "contains it, and its contexts are the share dealings, the defamation suit and the "
     "PKR fights."),
    (r"Farhajnya(?![A-Za-z])", "Farhashnya",
     "The same name with the Malay enclitic attached: 'Yang siasat Farhajnya kita tak "
     "tahu'. Needs its own entry because the lookahead above refuses to split a word."),
    (r"Farhaish(?![A-Za-z])", "Farhash",
     "17 occurrences: 'Dato Ishak ke Farhaish dapat ni kan', 'paling beria Farhaish punya "
     "ni kot'."),
    (r"Farhaq(?![A-Za-z])", "Farhash",
     "One occurrence, and the same sentence names him twice: 'melawan Farhaj dalam parti. "
     "Kalau tidak Farhaq ni dah kawal semua'."),
    (r"Farhaib(?![A-Za-z])", "Farhash",
     "One occurrence: 'Setiap perkara yang Farhaib buat itu saham yang dia beli'."),
    (r"Farhad(?![A-Za-z])", "Farhash",
     "11 occurrences, all him, and one sentence again names him twice: 'Ruben inilah "
     "peguam Farhad. Dan Farhaj pun tak cerdik'. Ruben is Sandraruben Neelamagham, the "
     "lawyer whose firm acted for Farhash -- owner-identified and press-verified."),
    (r"Farha(?![A-Za-z-])", "Farhash",
     "10 occurrences of the truncated form, every one him: 'Anwar Ibrahim dan Farha', "
     "'isu Farha ini ialah isu PKR', 'Soal Farha, soal Rahmanan'. The lookahead is what "
     "keeps this off `Farhan`, `Farhash` and `Farhad`."),
    # Eric See-To, the pro-Najib commentator who writes as Lim Sian See -- one person under
    # two names, owner-confirmed. Established spelling 178 times (135 published, 43 raw).
    (r"Eric Sito(?![A-Za-z])", "Eric See-To",
     "8 occurrences. ep58 puts both his names in one passage: 'yang mana Najib, yang mana "
     "Lim Sian Si. Yang bagus Eric Sito tu lah kan'. NOT touched: `Eric Fikri` / `Eric "
     "Fitri`, 11 occurrences, which is a VIEWER asking a question ('next question from "
     "Eric Fitri, 7290') and a different man entirely."),
    # raw-only tidy-ups. The published files already render both correctly, so this only
    # stops raw and published disagreeing for the name checks.
    (r"Lim Gotong(?![A-Za-z])", "Lim Goh Tong",
     "raw ep58 x2. Lim Goh Tong, the Genting founder, whose business partner in that "
     "passage is Najib's grandfather. Published already says Lim Goh Tong x6."),
    (r"Tuan Seri Noah(?![A-Za-z])", "Tan Sri Noah",
     "raw ep58 x1, in the same sentence. Published already says Tan Sri Noah x3."),
    # Ultras Selangor, the Selangor FC supporters' group, and its contraction Ultrasel.
    # Read off the VIDEO: the segment card in ep34 reads `ULTRASEL / LEPAK SEL` over a news
    # clip about 33 Selangor fans remanded. Owner-confirmed both forms 2026-08-29. Neither
    # `Altras` nor `Atasel` nor `Ultracel` is a word, and the speaker says the name four
    # times in one breath, which is why the ASR produced four different spellings of it.
    (r"Altras Selangor(?![A-Za-z])", "Ultras Selangor",
     "raw ep34. The group's full name; the published files already had it right 8 times."),
    (r"Altrasel(?![A-Za-z])", "Ultrasel", "raw ep34 x2, published x2."),
    (r"Atasel(?![A-Za-z])", "Ultrasel", "raw ep34 x1, published x2."),
    (r"Ultracel(?![A-Za-z])", "Ultrasel", "published ep34 x4, raw x1 lowercase."),
    (r"Ultra Cell(?![A-Za-z])", "Ultrasel", "raw ep34 x1. Captions heard `ultraell`."),
    (r"ultracel(?![A-Za-z])", "Ultrasel",
     "The lowercase one, raw ep34: `Di Terengganu, ultracel lepak sel` -- the clip's own "
     "title card, which reads ULTRASEL / LEPAK SEL on screen. Second time a capitalised "
     "pattern reported a clean run while a lowercase instance survived; grep after every "
     "substitution."),
    # Aircraft makers in the ep21 procurement discussion with Dr Rais Hussin. Both garbles
    # are in raw only -- the published files already read Boeing and Airbus -- so this just
    # stops raw and published disagreeing.
    (r"Boying(?![A-Za-z])", "Boeing",
     "raw ep21 x1: 'Jadi jika ini adalah kes, Boying, Petronas'. Owner-confirmed. The same "
     "episode spells Boeing correctly 5 times, and so do the YouTube captions."),
    (r"(?<![A-Za-z])Ebas(?![A-Za-z])", "Airbus",
     "raw ep21 x1: 'Kita mempunyai Ebas. Kita mempunyai Boeing' -- a tender-comparison "
     "list, so the pairing identifies it. Captions heard the tail as `bas, kita ada "
     "Boeing`. Uses a lookBEHIND as well, since `Ebas` could otherwise sit inside a word."),
    (r"Mujan Yassin(?![A-Za-z])", "Muhyiddin Yassin",
     "raw ep05 x1: 'Tan Sri Mujan Yassin tak offer apa-apa' about the BN-PN meeting at St "
     "Regis. Owner-confirmed 2026-08-29. Established 1,135 times (262 raw, 873 published) "
     "against this single garble, and the published file already expanded it correctly, so "
     "this only stops raw and published disagreeing for check_names."),
    # The two men served letters of demand over the RCI Tabung Haji report, in ep60's UMNO
    # segment at 9:08. Each name occurs exactly ONCE per file and nowhere else in 168
    # hours, so nothing inside the corpus could identify them and no established spelling
    # existed to compare against. The press identified them, and four details in the
    # episode agree: both names in the same order, the `LOD 5 juta` figure Haziq gives at
    # 9:44, Asyraf Wajdi himself coming up at 18:25 on Tabung Haji, and raw's garbled
    # `susa agong UMNO` opening the segment on a party post. Owner-confirmed 2026-08-29
    # against the Berita Harian report.
    # https://www.bharian.com.my/berita/nasional/2026/08/1601917/asyraf-wajdi-serah-lod-rm5-juta-kepada-ismail-salleh-abied-abdullah
    #
    # This is the pair the rewrite had published as `Ismail Sabri` and `Ahmad Zahid`, so
    # the correction runs in two stages: the fabrication was reverted to what the ASRs
    # heard, and only now, with an external source, does the real spelling go in.
    (r"Ismail Saleh(?![A-Za-z])", "Ismail Salleh",
     "ep60 x1 in each of the four files: 'Jadi Ismail Saleh dapat LOD'. Datuk Dr Ismail "
     "Salleh, of Amanah's national leadership council. TWO L's for this man and ONE for "
     "Akmal Saleh, 185 times, in the same corpus -- which is why this is a two-word "
     "pattern like the Fuziah surname fix and not a `Saleh` sweep."),
    (r"Abid Abdullah(?![A-Za-z])", "Abied Abdullah",
     "ep60 x1 in each of the four files, immediately after Ismail Salleh. A social-media "
     "account owner, reported as Habin Faisal Mohamed. The lookahead is load-bearing "
     "beyond the usual reason: the corpus holds 11 `Abidin`, and a pattern on bare `Abid` "
     "would eat every one of them."),
]

# DELIBERATELY NOT CORRECTED, verified against sources 2026-08-29. Recorded so the
# analysis is not redone, and because each of these looks like an obvious sweep until
# you check who the name belongs to.
#
#   Akmal Saleh -- ONE L IS CORRECT. 185 occurrences. Muhamad Akmal bin Saleh, UMNO
#     Youth chief; Wikipedia and every news source spell it Saleh. A blanket
#     `Saleh` -> `Salleh` would have corrupted all 185, which is the reason the Fuziah
#     surname fix above is a two-word pattern.
#     https://en.wikipedia.org/wiki/Muhamad_Akmal_Saleh
#   Mat Saleh / Mat Salleh -- BOTH ARE LEGITIMATE. The colloquialism for a Westerner is
#     attested either way; the OED's own etymology entry lists "Malay mat saleh". Not a
#     garble, so 11 `Saleh` and 7 `Salleh` are both left as spoken.
#     https://www.oed.com/dictionary/mat-salleh_n
#   Tun Salleh Abas -- already correct in its single occurrence.
#   mak Saleh / Mak Salleh -- 6 occurrences, referent not established. Left alone.
#
# The general rule this corpus keeps proving: a name is not a spelling to normalise by
# majority vote. The majority form was WRONG for Fuziah and RIGHT for Akmal.


def targets():
    return (sorted(ROOT.glob("episodes/*/*/raw.md"))
            + sorted(ROOT.glob("episodes/*/*/interview.md"))
            + sorted(ROOT.glob("episodes/*/*/interview-en.md"))
            + sorted(ROOT.glob("episodes/*/*/interview-ms.md")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    compiled = [(re.compile(rx), rep, why) for rx, rep, why in CORRECTIONS]
    for rx, rep, _ in compiled:
        # A pattern that lost its escapes matches nothing and reports a clean zero, so
        # prove it is intact before trusting any count below.
        print(f"pattern {rx.pattern!r} -> {rep!r}")

    totals = {rep: 0 for _, rep, _ in compiled}
    touched = 0
    for path in targets():
        text = original = path.read_text(encoding="utf-8")
        hits = {}
        for rx, rep, _ in compiled:
            text, n = rx.subn(rep, text)
            if n:
                hits[rep] = hits.get(rep, 0) + n
                totals[rep] += n
        if text != original:
            touched += 1
            rel = path.relative_to(ROOT / "episodes")
            print(f"  {str(rel):78s} {hits}")
            if args.write:
                path.write_text(text, encoding="utf-8")

    print(f"\n{touched} file(s) {'written' if args.write else 'would change'}")
    for rep, n in totals.items():
        print(f"  -> {rep}: {n}")
    if not args.write:
        print("\n-- dry run, pass --write to apply --")


if __name__ == "__main__":
    main()
