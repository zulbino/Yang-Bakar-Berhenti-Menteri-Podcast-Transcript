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
    (r"\bMara\b",
     "MARA",
     "Majlis Amanah Rakyat, an acronym. 13 mixed-case against 89 already-correct MARA. "
     "All 13 checked individually and every one is the agency: `termasuklah Mara dan what "
     "not, Peneraju`, `agensi-agensi tertentu Mara contohnya`, `Teraju ke, Mara ke`, "
     "`1MDB dulu, NFC, Mara, Tabung Haji`, and ep62's `Pasal Mara. Dudley House` -- the "
     "London property scandal. CAPITAL M ONLY. `mara` is also an ordinary Malay verb, so "
     "the lower-case form is deliberately not matched. "
     "NOT DONE, and worth recording as a near miss: `Mas` looked like the same case at 99 "
     "mixed against 44 MAS, and is not. Every one of the 99 is a place -- `Mas Gading`, a "
     "Sarawak constituency, and `Teluk Mas` in Melaka. Replacing them would have turned "
     "real place names into an airline."),
    (r"\b[Ff]elda\b",
     "FELDA",
     "OWNER-supplied, from felda.gov.my, which writes the acronym in full caps throughout "
     "and expands it as Lembaga Kemajuan Tanah Persekutuan. 777 instances were corrected "
     "across 38 files; the corpus had 774 `Felda` against 39 already-correct `FELDA`. "
     "It is an acronym, not a name, so the caps are the correct form rather than a style "
     "preference. The `title:` line is protected by protect_title() -- ep26's YouTube "
     "title genuinely reads `Azam Baki, UEC & Felda | YBM EP 26` and must keep it."),
    (r"Asri muda(?![A-Za-z])",
     "Asri Muda",
     "OWNER-prompted. Mohd Asri bin Muda, PAS president 1969-1982 and the Land minister "
     "responsible for FELDA in the BN government 1973-1978 (en.wikipedia.org/wiki/Asri_Muda), "
     "which is the role ep62 gives him. `Muda` is his father's name and takes a capital. "
     "1 lower-case occurrence against 5 already correct. ANCHORED ON `Asri` because `muda` "
     "is the ordinary Malay word for young and appears 720 times in the corpus."),
    # --- ep62's FELDA chairman succession. The episode walks all five in order, and the
    # ASR garbled every one of them. Owner-confirmed, and each verified externally.
    (r"\bTansi\b",
     "Tan Sri",
     "OWNER-supplied. 11 occurrences across 6 episodes against 54 correct `Tan Sri` in "
     "ep62 alone, every one of them followed by a name: Azan Baki, Khairul Adib x2, "
     "Khalid Ibrahim, Shabery Cheek x2, Ahmad Bahadri x2, Raja Alias, Syarif Ahmad, "
     "Issa Samad. WORD BOUNDARIES ARE LOAD-BEARING. `konsultansi` contains `tansi`, and a "
     "bare substring replace turns it into `konsulTan Sri`. It survives only because the "
     "corpus writes it lower-case; `\\b` and the capital T are both doing work."),
    (r"Ahmad Bahadri(?![A-Za-z])",
     "Ahmad Badri",
     "OWNER-supplied. Tan Sri Ahmad Badri Mohd Zahir, FELDA chairman from July 2026 "
     "succeeding Ahmad Shabery Cheek, Treasury secretary-general 2018-2020 "
     "(thestar.com.my/news/nation/2026/07/15/ahmad-badri-appointed-as-new-felda-chairman). "
     "ep62 describes him as `bekas civil servant, bekas KSP dulu`, which is exactly that "
     "post. 2 occurrences, both ep62."),
    (r"Idris Jusuh(?![A-Za-z])|Ida Yusof(?![A-Za-z])",
     "Idris Jusoh",
     "OWNER-supplied. Datuk Seri Idris Jusoh, FELDA chairman before Shabery Cheek, who "
     "succeeded him in July 2023. 3 occurrences, all ep62, all in one passage listing the "
     "chairmen in order: `bukan Idris Jusuh ke? ... Pengerusi Felda sebelum ... Ida Yusof "
     "kan Datuk Seri Ida Yusof`. Zero correct spellings existed in the corpus before this."),
    (r"Syarici(?![A-Za-z])|(?<=sebelum )Syafiq(?![A-Za-z])",
     "Shabery Cheek",
     "OWNER-supplied. Two more garbles of the same man, in the same chairman-succession "
     "passage. `Syafiq` IS ANCHORED ON THE PRECEDING WORD and must stay that way: it "
     "appears 11 times in the corpus and 10 of those are other people -- Syafiq Iskandar, "
     "Dato' Seri Syafiq Abdal, Syafiq Din. A bare replace would rename three real men."),
    (r"(?<=Tan Sri )Syarif(?= tak payah)",
     "Shahrir",
     "OWNER-supplied. The bare surname, once, in `Tan Sri Syarif tak payah ambil satu sen "
     "pun lah gaji` -- the same man, no salary. ANCHORED ON BOTH SIDES because a bare "
     "`Syarif` is a real Malay name and a real name-part (`Syarifah`), and one unanchored "
     "surname rule is how a corpus-wide name pass corrupts everything it touches."),
    (r"Syarif Ahmad(?![A-Za-z])|Syarif Hamad(?![A-Za-z])",
     "Shahrir Samad",
     "OWNER-supplied. The same Tan Sri Shahrir Abdul Samad as the entry below, garbled two "
     "further ways in a different stretch of ep62. The episode dates him itself: `Tan Sri "
     "Syarif Ahmad, dia kan dilantik jadi pengurusi Felda Januari 2017`. 8 occurrences, "
     "all ep62. `Ahmad` and `Hamad` are both mishearings of his `Abdul`."),
    (r"Issa Samad(?![A-Za-z])",
     "Isa Samad",
     "OWNER-supplied. Tan Sri Mohd Isa Abdul Samad, FELDA chairman until January 2017 and "
     "Shahrir's predecessor. 5 occurrences against 16 already-correct `Isa Samad` in the "
     "same episode."),
    (r"Syarif Samad(?![A-Za-z])",
     "Shahrir Samad",
     "OWNER-supplied. Tan Sri Shahrir Abdul Samad, FELDA chairman from 6 January 2017 "
     "replacing Tan Sri Mohd Isa Abdul Samad, resigned May 2018 "
     "(thestar.com.my/business/business-news/2017/01/06/shahrir-replaces-isa-as-felda-chairman). "
     "16 occurrences: 12 in ep62 and 4 in ep21, against 12 already-correct `Shahrir Samad` "
     "elsewhere in the corpus. ep62's own text dates him -- 'dilantik jadi pengurusi Felda "
     "Januari 2017' -- and ep21's identifies him -- 'seorang sahaja yang pernah menang "
     "gitu', his 1988 Johor Bahru win as an independent. "
     "ANCHORED ON THE FULL TWO-WORD NAME on purpose. A bare `Syarif` would corrupt "
     "`Syarifah`, and this episode also carries `Syarif Ahmad` seven times, which is the "
     "same man again but is left for the owner rather than assumed: `Ahmad` is a plausible "
     "mishearing of his `Abdul`, and guessing a surname is exactly the error this file "
     "exists to prevent."),
    (r"Syarifulcik(?![A-Za-z])|Syabricik(?![A-Za-z])|Syabri Cik(?![A-Za-z])"
      r"|Shabri Chik(?![A-Za-z])|Shabricik(?![A-Za-z])",
     "Shabery Cheek",
     "OWNER-supplied and owner-verified by ear against the video. Datuk Seri Ahmad Shabery "
     "Cheek, FELDA chairman from July 2023, reappointed July 2025 "
     "(en.wikipedia.org/wiki/Ahmad_Shabery_Cheek). Three spellings of one name: `Syabricik` "
     "twice and `Syarifulcik` twice in ep62, `Syabri Cik` once in ep43 inside a "
     "self-correction, 'eh Ismail Sabri pula, Shabery Cheek'. "
     "TITLE NOTE FOR THE REWRITE STAGE, and this is the reason this entry is verbose: "
     "ep62 has Rafizi calling him 'Tan Sri' twice. That is WRONG -- he is a Datuk Seri. "
     "raw.md keeps 'Tan Sri' because raw.md records what was said, and the owner decided "
     "that explicitly. The interview files should use Datuk Seri. Do not add a "
     "Tan Sri -> Datuk Seri rule here; it would rewrite the raw transcript, and the same "
     "two words are correct for other people in this corpus."),
    (r"Sesemah(?![A-Za-z])",
     "Selsema",
     "OWNER-supplied, ep62 MAI transcript. The common cold. The passage is Haziq two weeks "
     "ill -- 'Dua minggu demam tau' / 'Lamanya demam?' / 'Selsema. Tak tahu kenapa.' / "
     "'Sebab air con lama?' / 'Jerebu.' -- so the word is the illness, not a name. NOTE: "
     "Dewan Bahasa's standard spelling is 'selesema' and 'selsema' is the colloquial form; "
     "the owner asked for selsema, which is also what is spoken. Change both entries "
     "together if the house ever prefers the DBP form."),
    (r"sesemah(?![A-Za-z])",
     "selsema",
     "Lower-case half of the entry above, for mid-sentence occurrences."),
    (r"YMDB(?![A-Za-z])",
     "1MDB",
     "OWNER-supplied. 34 occurrences across 14 episodes (ep05 ep18 ep26 ep29 ep31 ep39 "
     "ep42 ep44 ep47 ep48 ep50 ep52 ep58 ep62) against 889 correct 1MDB in the same "
     "corpus. The ASR hears the spoken 'one-em-dee-bee' as one word. Every one of the 34 "
     "was read before this entry was written and every one is the scandal -- Najib, SRC, "
     "The Edge, the vote of no confidence, 'zaman Najib dengan YMDB dulu'. ep44's rewrite "
     "even tried to expand the garble into a gloss, '[Yang Maha Di Bicara?]', which is "
     "what an unfixed garble costs downstream. Not a majority-vote normalisation: YMDB is "
     "not an entity, and the contexts name the one that is."),
    (r"IMDB(?![A-Za-z])",
     "1MDB",
     "ep35, once: 'masa saya melalui perkara seperti IMDB dahulu'. Same acronym, a "
     "different mishearing, and not the film database."),
    (r"Peter Sonda(?:k|h|r|l|ng|)(?![A-Za-z])",
     "Peter Sondakh",
     "OWNER-directed acronym/name pass on ep62. Tan Sri Peter Sondakh, the Indonesian "
     "owner of Rajawali who sold FGV and then FELDA the Eagle High Plantations stake and "
     "who owns the St. Regis Langkawi. The corpus spells him SIX ways -- Sondakh 3, "
     "Sondah 7, Sonda 6, Sondar 4, Sondak 2, Sondal 1 -- and only ep26's three published "
     "files have it right. Confirmed against Rafizi's own blog, which scores 1.00 on two "
     "2017-03 posts naming 'Tan Sri Peter Sondakh, pemilik PT Rajawali'. "
     "ANCHORED ON THE FULL NAME on purpose: a bare Sondal -> Sondakh would rewrite a Malay "
     "vulgarity, and the one occurrence here is 'Peter Sondal lah', the name plus a "
     "particle. The alternation deliberately cannot match the already-correct Sondakh."),
    (r"Raja Wali(?![A-Za-z])",
     "Rajawali",
     "ep62, 3 times, all the Indonesian conglomerate: 'PT Raja Wali milik Tan Sri Peter "
     "Sondakh' and 'kumpulan Raja Wali'. One word, per the blog slug pt-rajawali and "
     "FGV's own filings."),
    (r"Raisin Sky(?![A-Za-z])",
     "Brazen Sky",
     "ep62, once. Brazen Sky Ltd is 1MDB's BVI vehicle that held US$1.1bn in fund units at "
     "BSI Singapore; Rafizi names it as the example of 1MDB at least using invented names "
     "rather than copying a real subsidiary's. MAI-Transcribe-2 heard it correctly on the "
     "same audio, which is the second source."),
    (r"SCBRE(?![A-Za-z])",
     "CBRE",
     "ep62, once, the property valuer whose report sits in the Grand Plaza prospectus. "
     "MAI writes CBRE 4 times on the same audio."),
    (r"(?:GAFCO|Gafco|Gavco)(?![A-Za-z])",
     "GovCo",
     "ep62, twice: 'satu SPV syarikat khas kerajaan yang dipanggil Gavco' and 'pinjaman "
     "2.3 bilion daripada Gavco Holdings Berhad, syarikat di bawah Menteri Kewangan'. "
     "THREE spellings between two engines on the same audio -- the local ASR writes Gavco "
     "and Gafco, MAI-Transcribe-2 writes GAFCO -- which is itself the evidence that none of "
     "them is the real name. "
     "GovCo Holdings Bhd is the Ministry of Finance subsidiary that lent FELDA's FIC "
     "Properties RM2.5bn for the Eagle High purchase, still owed RM2.77bn on a 20-year "
     "Tawarruq running to 2043. The transcript states the lender's own description, so "
     "this is the same entity spelled by ear."),
    (r"Eagle Hypertension(?![A-Za-z])",
     "Eagle High Plantations",
     "PT Eagle High Plantations Tbk, the Rajawali company FGV agreed to buy 37% of in 2015 "
     "and FELDA bought in 2017. Rafizi wrote two 2016-12 posts on it. No occurrence in "
     "episodes/ today -- this is here for the MAI transcripts, where it appears, and so "
     "that bias_phrases() feeds the right name to the next MAI run. NOTE: plain 'Eagle "
     "Plantations' is NOT corrected, because Rafizi's own blog uses that short form."),
    (r"pembinaan sinergi Selangkawi(?![A-Za-z])",
     "pembinaan St. Regis Langkawi",
     "ep62, once, in Haziq reading the audit finding on bad debts. The project is the St. "
     "Regis Langkawi hotel, which MAI writes 14 times on the same audio and which Rafizi's "
     "2017-03 post ties to Peter Sondakh and the RM305m of public money behind it."),
    (r"antarabangsa Selangkawi(?![A-Za-z])",
     "antarabangsa Langkawi",
     "ep62, once, the second half of the same sentence: the Langkawi International "
     "Convention Centre, LICC, named in the same blog post. Anchored to the two words "
     "rather than to Selangkawi alone so the two halves get their own right answers."),
    (r"Baitul Magdis(?![A-Za-z])",
     "Baitul Maqdis",
     "ep61, once. Jerusalem / the Al-Aqsa precinct, used throughout the episode as the "
     "analogy PAS drew for Tabung Haji. The episode itself writes Baitul Maqdis 7 times "
     "against this one Magdis, and Baitulmaqdis is a standard Malay form (ms.wikipedia.org "
     "has 'Sejarah Baitulmaqdis'), so this normalises a garble to the established in-corpus "
     "spelling rather than choosing between two real spellings."),
    (r"Batu Makdis(?![A-Za-z])",
     "Baitul Maqdis",
     "ep61, once, same place and same passage -- 'ibarat pertahanan Batu Makdis'. Third "
     "spelling of the one name."),
    (r"Dewa Kuanti(?![A-Za-z])",
     "Dewa Kuan Ti",
     "OWNER-supplied, ep61: the temple whose grounds hosted a ceramah is the Persatuan "
     "Penganut Dewa Kuan Ti. Anchored on the two-word form ON PURPOSE -- a bare Kuanti -> "
     "Kuan Ti would corrupt ep36's 'minimum order kuantiti' and 'Dia ada kuantitatif', "
     "which are ordinary Malay words containing the same letters. The owner gave this name "
     "in a session whose fix reached only the published files, so a later rewrite "
     "regeneration silently reverted it; correcting raw.md and listing it here is what "
     "makes it survive the next regeneration."),
    (r"Zilinggong(?![A-Za-z])",
     "Xi Ling Gong",
     "OWNER-supplied, ep61, same turn: the temple's name as it appears on Maps. The ASR "
     "heard 'z linggong'. Same reversion story as Dewa Kuan Ti above."),
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
    # Puchong, the Selangor town, in the ep29 UMNO-division story and once in ep45.
    # Owner-confirmed 2026-08-30. The established spelling is already dominant here, 36
    # correct against these 20, and ep29's raw spells it BOTH ways inside one passage:
    # `Aku tak ingat kali terakhir UMNO menang di Puchong. Tahun bila? 2004 kot. 2003
    # sebab Puchon...` -- so this is one ASR being inconsistent, not two referents.
    # Capital P in every replacement, including for the lowercase garble: it is a place
    # name wherever it sits in the sentence.
    (r"Pucung(?![A-Za-z])", "Puchong",
     "ep29 raw + published x14, ep45 raw x1: 'memutuskan hubungan dengan PH di Pucung', "
     "'UMNO bahagian Pucung'."),
    (r"Pucong(?![A-Za-z])", "Puchong",
     "ep29's three published files x1 each plus raw: 'UMNO Pucong punya Azam...'. A "
     "second garble of the same name in the same episode."),
    (r"pucung(?![A-Za-z])", "Puchong",
     "ep29 raw x1, mid-sentence: 'Pasal berianya UMNO bahagian pucung ni'. Listed "
     "separately because a capitalised pattern has twice reported a clean run while the "
     "lowercase instance survived (`cephlos`, `ultracel`)."),
    # ep61's jacket exchange. Rafizi is reaching for the garment's name and the ASR wrote
    # the sound: `Is it bomber ke bomber? Boma. Boma. Boma jaket.` Owner-confirmed
    # 2026-08-30 -- the word is `bomber jacket`.
    #
    # THE REPETITION STAYS. raw carries three `Boma` and the published files two; a
    # speaker hunting for a word is what the passage is ABOUT, so only the spelling moves
    # (see the standing rule against collapsing repeated real words).
    #
    # Both cases are listed separately and each carries a lookahead, because `bomber`
    # appears 14 times in the corpus as ordinary English -- `suicide bomber`, `Unabomber`,
    # and ep51's unrelated `Bomber terus buat sar` -- and none of those may move. A
    # case-insensitive sweep is also wrong here: sentence-initial `Boma.` and mid-sentence
    # `pakai boma jaket` need different capitals.
    (r"Boma(?![A-Za-z])", "Bomber",
     "ep61 x3 in raw, x2 in each published file: 'Is it bomber ke bomber? Boma. Boma "
     "jaket.'"),
    (r"boma(?![A-Za-z])", "bomber",
     "ep61 x1 in each published file, mid-sentence: 'sebab aku pakai boma jaket ni'. "
     "Zero occurrences of either case anywhere outside ep61."),
    (r"Abid Abdullah(?![A-Za-z])", "Abied Abdullah",
     "ep60 x1 in each of the four files, immediately after Ismail Salleh. A social-media "
     "account owner, reported as Habin Faisal Mohamed. The lookahead is load-bearing "
     "beyond the usual reason: the corpus holds 11 `Abidin`, and a pattern on bare `Abid` "
     "would eat every one of them."),
    (r"Akta Sisi Perbeja(?![A-Za-z])", "Akta Sisa Pepejal",
     "OWNER-CONFIRMED, ep61 raw.md x1. The Solid Waste and Public Cleansing Management "
     "Act 2007 (Akta 672). Worth recording HOW it was identified, because the sentence "
     "itself points the wrong way: Haziq names two handovers to the federal government, "
     "solid waste and water, so the water assets alongside it made the Water Services "
     "Industry Act look like the answer. The reply settles it -- Rafizi at [2:14:30] says "
     "`sisa pepejal` six times. The corpus already holds 11 correct `sisa pepejal` and "
     "2 `Akta Sisa Pepejal` against this one garble."),
    (r"Lim Keng Yek(?![A-Za-z])", "Lim Keng Yaik",
     "OWNER-SUPPLIED with the source, ep61 raw.md x2 in one sentence -- `Tun Lim Keng Yek "
     "dulu lah, mendiang Tun Lim Keng Yek`. The late Tun Dr Lim Keng Yaik, Minister of "
     "Energy, Water and Communications when water services were restructured, which is "
     "exactly the era Rafizi is describing. The three published files already say Yaik, "
     "so this is raw.md catching up to them. https://ms.wikipedia.org/wiki/Lim_Keng_Yaik"),
    (r"Kan kitchen ada pakai", "Kan keychain ada pakai",
     "OWNER-CONFIRMED, ep61 raw.md [15:01]. Merch on the desk, and the owner had already "
     "corrected the same mishearing to `keychain` in the adjacent block [14:52]. Left "
     "untouched at the time on purpose -- a word change must not be extended by inference to "
     "a block the owner did not name -- and adjudicated separately on 2026-08-30. Anchored "
     "on the whole phrase because `kitchen` is a REAL kitchen elsewhere: ep22 thanks the "
     "`kitchen crew`, and the corpus holds 12 `the kitchen`."),
    (r"Yang itu kitchen", "Yang itu keychain",
     "Second occurrence in the same sentence, same adjudication."),
    (r"Water assets through vesting(?![A-Za-z])", "Water assets through WASIA",
     "ep61 interview-en.md x1. The English translation rendered the act's shortform as the "
     "concept it performs -- vesting water assets to PAAB is a real WSIA mechanism, so this "
     "is not nonsense, it just deletes the instrument the speaker named. Anchored on the "
     "whole phrase: `vesting` alone appears throughout the corpus, and a `w* vesting` "
     "matches inside `investing`. `through vesting` occurs exactly once."),
    (r"[Ww]asiah(?![A-Za-z])", "WASIA",
     "OWNER-CONFIRMED, ep61 x8 -- 5 lowercase, 3 capitalised, spread over the two turns of "
     "one exchange and NOWHERE else in the corpus, which is what makes a bare pattern safe "
     "here. The shortform for the Water Services Industry Act 2006 (Akta 655), the "
     "instrument the states transferred water assets to the federal government under. "
     "WSIA is the commoner written abbreviation and WASIA is the attested alternative "
     "(scribd.com/document/561622547 titles a deck `WASIA 2006 overview`); WASIA is kept "
     "because this is a transcript and it is what both hosts said out loud -- Rafizi uses "
     "the word himself at [2:14:30], which is also why it was never ASR noise. `wasiat` is "
     "a DIFFERENT and correct word, Lenin's will in ep34, and the lookahead is what keeps "
     "this off it. Note interview-en.md glosses it `[deed of assignment]`, which the "
     "rewrite invented and which is wrong for an act -- fix that gloss by hand, this map "
     "cannot reach it."),
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

    def protect_title(src):
        """Split off any `title:` line so no rule can rewrite it.

        `title:` is YouTube's own video title, copied verbatim. It is a quotation of the
        source, not our prose, and restyling it would make the file disagree with the video
        it cites. This was found when a Felda -> FELDA rule was about to rewrite ep26's
        title from `Azam Baki, UEC & Felda | YBM EP 26`, which is what YouTube actually
        shows. Every rule in this file gets the protection, not just that one.
        """
        m = re.search(r"^title:.*$", src, re.M)
        if not m:
            return "", src
        return src[:m.end()], src[m.end():]

    for path in targets():
        original = path.read_text(encoding="utf-8")
        head, text = protect_title(original)
        hits = {}
        for rx, rep, _ in compiled:
            text, n = rx.subn(rep, text)
            if n:
                hits[rep] = hits.get(rep, 0) + n
                totals[rep] += n
        text = head + text
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
