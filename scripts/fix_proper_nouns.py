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

# Windows' default console/pipe encoding (cp1252) cannot print a corpus correction that
# contains non-Latin text, such as the CJK garble ep02:berhenti's fix carries. Found when
# `adopt_mai_camera_raw.py` piped this script's stdout and the print crashed before the
# write ever ran, refusing every subsequent adoption corpus-wide until fixed.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
    # OWNER-CORRECTED BY EAR 2026-09-11, while ruling on ep57's misattributed YB turns: the
    # turn reads "...Tabung Haji, RCI Tabung Haji yang baru-baru ni lah YB", and MAI had
    # fused the last four words into one. Not a name, but it belongs here for the same
    # reason a name does -- without it, the next rebuild from MAI reintroduces the garble and
    # silently discards the owner's correction, which is what happened to ep61's Farhan turn.
    # One occurrence in the corpus, and `baru-baru ni` is ordinary Malay that appears
    # correctly elsewhere, so this is anchored on the whole fused token.
    (r"barbarunilah(?![A-Za-z])",
     "baru-baru ni lah",
     "raw ep57 x1 at 10:40: 'RCI Tabung Haji yang barbarunilah YB'. Owner-supplied."),
    # OWNER-INSTRUCTED 2026-09-11: "why wait for me for asyraf wajdi, you can do web search
    # to check what his actual name". Searched, and every source spells it Asyraf -- his own
    # Instagram handle is @drasyrafwajdi, and Wikipedia, Free Malaysia Today, Malaysiakini,
    # Malay Mail and Berita Harian agree. Nothing spells it Ashraf.
    #   https://en.wikipedia.org/wiki/Asyraf_Wajdi_Dusuki
    #   https://www.instagram.com/drasyrafwajdi/
    #
    # WHY A WHOLE-CORPUS COUNT WOULD HAVE PICKED THE WRONG ONE. All files together read
    # Ashraf 35 and Asyraf 35, a dead heat. But raw.md -- the only file that records what an
    # engine heard -- reads Asyraf 15 to Ashraf 2, and ep60's MAI raw spells it Asyraf six
    # times unaided. The whole Ashraf majority sat in interview files, which are GENERATED
    # from raw and cannot corroborate it. Counting every file equally lets the rewrite
    # outvote the audio. No YouTube title contains the name, so nothing is a quotation here.
    (r"Ashraf Wajdi(?![A-Za-z])",
     "Asyraf Wajdi",
     "Datuk Dr Asyraf Wajdi bin Dusuki, MARA chairman since March 2023 and UMNO Youth chief "
     "2018-2023. 33 occurrences in published files and 2 in raw. Two words, so it cannot "
     "touch anyone else named Ashraf."),
    # ep60's guest, recurring in ep63. The show's own two episode descriptions disagree
    # (ep60: "Sum Dek Jo", ep63: "Sum Dek Joe"), and his own X handle @sumdekjoe plus his
    # academic publications (ANU Press, SSRN, AMRO, LinkedIn: "Dek Joe Sum") confirm "Joe".
    (r"\bSum Dek Jo\b",
     "Sum Dek Joe",
     "Web-verified: X @sumdekjoe, published academically as Dek Joe Sum (ANU/AMRO/SSRN). "
     "ep60's raw.md spells it without the final e throughout; ep63's own YouTube "
     "description already has it right."),
    # ep48 38:04, a digit settled by three witnesses, no ear needed: the speaker says the
    # price drops "6 sen daripada RM2.05", so 1.99; the local ASR heard RM1.99; the YouTube
    # captions agree; MAI alone heard RM1.09. Anchored on the full phrase.
    (r"6 sen daripada RM2\.05 kepada RM1\.09",
     "6 sen daripada RM2.05 kepada RM1.99",
     "ep48 raw.md [38:04]: arithmetic + local ASR + captions outvote MAI's 1.09."),
    # ep05:bakar [1:20:11], a digit settled by the local ASR witness, no ear needed: Rafizi
    # describes the middle income band getting squeezed by wage compression, "yang kat
    # tengah ni yang gaji [X] ke 4000". The pre-MAI local-ASR raw.md clearly heard
    # "RM1,800 ke RM4,000" -- a coherent middle-income range -- while MAI alone heard
    # "1008", an implausible salary figure and likely a digit-formation garble of 1,800.
    # No YouTube caption coverage of this passage to add a third witness, but the local
    # ASR is the only other witness and it is unambiguous.
    (r"gaji 1008 ke 4000",
     "gaji RM1,800 ke RM4,000",
     "ep05:bakar raw.md [1:20:11]: local-ASR witness (_old_ep05-bakar_raw.md) says "
     "'RM1,800 ke RM4,000'; MAI alone heard '1008 ke 4000'. 1,800 makes sense as a "
     "middle-income band bound with 4,000; 1008 does not."),
    # The same guest addressed by his nickname on air (ep60, ep63). Owner 2026-09-12: spell
    # it Joe. The lookbehind/lookahead keep ep16's "Hang Jo" (Hangzhou) and ep51's "Jo-
    # Johor" untouched.
    (r"(?<!Hang )\bJo\b(?!-)",
     "Joe",
     "ep60 and ep63 vocative for Sum Dek Joe; excludes Hang Jo (ep16) and Jo- Johor (ep51)."),
    # ep63 [03:10] "Joe dah familiar eh, Brae?" -- the owner's ear: it is YB. Anchored on
    # the phrase; ep54's two "Brae" are a different context (segment name, unverified).
    (r"familiar eh, Brae\?",
     "familiar eh, YB?",
     "Owner-confirmed 2026-09-12, ep63 03:10."),
    # Same guest, two more ASR hearings: MAI wrote "Sam D. Jo" in ep63's host intro, the
    # local ASR wrote "Sam Dek Jo" in ep52's published files. Anchored on the full name.
    (r"\bSam D\. Jo\b",
     "Sum Dek Joe",
     "Same web-verified guest as the entry above; ep63 raw.md [00:49]."),
    (r"\bSam Dek Jo\b",
     "Sum Dek Joe",
     "Same web-verified guest as the entry above; ep52 interview*.md."),
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
    (r"Yang Menteri Menteri(?![A-Za-z])",
     "Yang Berhenti Menteri",
     "The show's own name. MAI-Transcribe-2 hears the opening 'Podcast Yang Berhenti Menteri' "
     "as 'Yang Menteri Menteri' -- 7 occurrences, all ep62 (raw + the three interview files "
     "+ the summary), against 424 correct in the corpus. Anchored on the full three-word "
     "garble; 'Yang Bakar Menteri' is the other show and is untouched."),
    (r"Shahril Samad(?![A-Za-z])",
     "Shahrir Samad",
     "OWNER-caught 2026-09-10 on the MAI transcript of ep62, which hears the FELDA chairman "
     "as `Shahril` 8 times against 2 correct `Shahrir Samad` in the same file. Web-checked: "
     "Tan Sri Shahrir Abdul Samad, FELDA chairman 6 January 2017 to 14 May 2018 "
     "(en.wikipedia.org/wiki/Shahrir_Abdul_Samad; thestar.com.my 2017-01-06). ANCHORED ON "
     "`Samad`: Shahril is a common real given name and must not be touched on its own."),
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
    # MAI heard `Asravu HD` for this man's name in ep56 at 6:40 -- the local ASR had it
    # right and MAI did not, which is the other way round from most of this map. It occurs
    # ONCE in 168 hours, and the sentence identifies him without doubt: Haziq is talking
    # about the content filling his FYP and says the man appeared on the podcast Lebih Masa
    # two months earlier.
    #
    # WHY `Asyraf` AND NOT `Ashraf`, because a whole-corpus count says the opposite. All
    # files together read Ashraf 35 and Asyraf 35, a dead heat. Split by file type it is not
    # close: the raw transcripts, which are what an engine actually heard, read **Asyraf 14
    # and Ashraf 2**, and ep60's MAI raw spells it Asyraf six times. The Ashraf majority
    # lives entirely in the rewritten interview files, which are generated FROM raw and are
    # not a witness to anything. The press agrees with raw -- the Berita Harian report below
    # is `asyraf-wajdi-serah-lod-rm5-juta`. Counting every file equally would have picked the
    # spelling produced by the rewrite over the one heard from the audio.
    # https://www.bharian.com.my/berita/nasional/2026/08/1601917/asyraf-wajdi-serah-lod-rm5-juta-kepada-ismail-salleh-abied-abdullah
    #
    # NOT NORMALISED HERE, and it is an owner question in data/owner_questions.md: 33
    # `Ashraf Wajdi` in published files and 2 in raw. Precedent in this map is that a name
    # goes in after an external source AND the owner confirms it -- that is how Ismail
    # Salleh went in -- so 35 more occurrences wait for them.
    (r"Asravu HD(?![A-Za-z])", "Asyraf Wajdi",
     "raw ep56 x1: 'content-content mengenai Asravu HD'. Datuk Dr Mohd Asyraf Wajdi "
     "Dusuki. Anchored on the full garble, not on `Asravu`, and it appears nowhere else."),
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
    (r"\bJKOM\b", "J-KOM",
     "OWNER-CONFIRMED 2026-09-10, corpus-wide. Jabatan Komunikasi Komuniti, the agency that "
     "replaced JASA in November 2020 and now sits under the Ministry of Communications; its "
     "own portal titles itself `Portal Rasmi J-KOM` and Bernama, Berita Harian and both "
     "Wikipedias write the hyphen. 366 unhyphenated against 39 already correct, so the "
     "majority spelling is the wrong one -- the count is not the evidence here, the agency's "
     "own name is. Anchored on word boundaries for two reasons found by counting the odd "
     "forms first: `KPJKOM` x2 keeps its own spelling, because `KP` is the Ketua Pengarah "
     "and `KPJ-KOM` is not a thing anyone writes, and `JKOM-nya` x2 is matched on purpose, "
     "the Malay possessive riding on the acronym. Speakers also call it Jabatan Penerangan "
     "in the same breath, which is a different agency (JaPen) -- their words, left alone. "
     "https://www.jkom.gov.my/ , "
     "https://www.komunikasi.gov.my/awam/berita/18140-bernama-25-nov-2020-jasa-rebranded-as-j-kom-with-different-roles-functions-saifuddin"),
    (r"\bJCOM\b", "J-KOM",
     "Same agency, same owner decision. 4 occurrences, all in ep26's `media-media kerajaan "
     "yang di bawah JCOM` and its two translations -- the ASR heard a C. No other JCOM "
     "exists in the corpus, and JCOM is a real Japanese cable company, which is why this is "
     "word-anchored and recorded rather than folded into a fuzzy acronym sweep."),
    (r"Pak An(?![A-Za-z])", "Pa'an",
     "OWNER-CAUGHT 2026-09-10 on ep61: the co-host's nickname, settled as `Pa'an` on ep62 and "
     "written that way 4,528 times in this corpus. 9 occurrences, all of them one of the hosts "
     "quoting him -- ep45's `nak menjawab yang Pak An kata kita tak ada budaya itu` in raw and "
     "all three published files, and ep61 once. The lookahead is the whole safety of it: "
     "`Pak Anwar` must never be touched, and the corpus writes the Prime Minister as "
     "`Datuk Seri Anwar` everywhere, so there is nothing else this can reach."),
    (r"\bPaan\b", "Pa'an",
     "Same person, same 2026-09-10 decision, 15 occurrences: ep48 x5 (`menjawab yang Paan kan`, "
     "`yang macam Paan kata tadi`), ep44, and a few more. Word-anchored so it cannot reach "
     "inside another word."),
    (r"Keuangan(?![A-Za-z])", "Kewangan",
     "FOUND BY check_agencies.py 2026-09-12, the first defect it reported. `keuangan` is the "
     "INDONESIAN word; Malaysia's ministry is Kementerian Kewangan (mof.gov.my). 16 "
     "occurrences across ep12, ep17, ep18, ep25, ep28, ep29, ep34, all of them "
     "`Kementerian Keuangan` or `Menteri Keuangan` about the Malaysian ministry -- ep28's "
     "reads `contohnya Kementerian Keuangan. MOF likes to do all this`, which names MOF in "
     "the same breath. ep15 line 69 writes BOTH forms in one sentence (`kepada kementerian "
     "kewangan Asalnya Tetapi Kementerian Keuangan kata`), and that is what proves the ASR "
     "did it and not the speaker. No occurrence anywhere refers to Indonesia's ministry. "
     "https://www.mof.gov.my/portal/en/"),
    (r"keuangan(?![A-Za-z])", "kewangan",
     "The same word, lowercase, and a PUBLISHED-ONLY defect: 1 occurrence in ep09's "
     "interview.md and interview-ms.md where raw.md says `kewangan` correctly (`dia kata "
     "kewangan itu adalah untuk jadikan satu subjek khusus di sekolah`). The rewrite "
     "introduced the Indonesian spelling; raw.md does not need this pattern at all."),
    (r"Menteri Kawangan(?![A-Za-z])", "Menteri Kewangan",
     "Same ministry, a second garble of it, 1 occurrence in ep15 raw: `saya baca "
     "kenyataan-kenyataan daripada Menteri Kawangan Kedua lah, Dato' Seri Amir Hamzah` -- "
     "the Second Finance Minister, named in the same sentence. Two words, so `kawangan` "
     "alone is never touched."),
    (r"Akta SPRM 2009(?![A-Za-z0-9])", "Akta JAC 2009",
     "FOUND BY check_agencies.py's unsourced-agency check 2026-09-12, and the worst of the "
     "four: ep05's interview.md and interview-ms.md cite `Seksyen 122B Akta SPRM 2009`, "
     "naming the ANTI-CORRUPTION commission in a passage about who appoints the Chief "
     "Justice (`siapa nak lantik ketua hakim`). raw.md never says SPRM at all. Two "
     "witnesses settle it: local ASR heard `Akta JSC 2009`, MAI heard `Akta JAC 209`, and "
     "the Judicial Appointments Commission Act 2009 (Act 695, gazetted 8 February 2009) is "
     "exactly the law for appointing judges. The rewrite swapped one commission for "
     "another. https://www.jac.gov.my/en/commission/introduction"),
    (r"Akta JSC 2009(?![A-Za-z0-9])", "Akta JAC 2009",
     "The same citation in ep05 raw.md, 1 occurrence. `JSC` is the local ASR's mishearing "
     "of the same two seconds MAI transcribes as `JAC`, and MAI is the better-measured "
     "engine (3.39% podcast WER against local Whisper's 20.52%). The topic decides it, not "
     "the engine's score: the sentence is about appointing the Chief Justice."),
    (r"Akta JAC 209(?![A-Za-z0-9])", "Akta JAC 2009",
     "The third witness for the same ep05:berhenti citation, found 2026-09-18 when the "
     "MAI+camera adoption's own rewrite gate could not reproduce a figure raw.md never "
     "really had. MAI got the agency name right but dropped the year's trailing digit: "
     "`122B, kan, Akta JAC 209.` The comment above already names this exact reading as one "
     "of the two witnesses that settled `Akta JAC 2009`, so this just gives it its own "
     "pattern instead of leaving the gap the earlier entries' agency-name anchor missed."),
    (r"Suruhanjaya Lantikan Kehakiman(?![A-Za-z])", "Suruhanjaya Pelantikan Kehakiman",
     "FOUND BY check_agencies.py in the end-of-session audit, 2026-09-14: 3 occurrences in "
     "ep30, one in raw.md and one in each of interview.md and interview-ms.md, all in the "
     "same sentence about Tun Abdullah establishing the JAC in 2009. The agency's own site "
     "spells it `Suruhanjaya Pelantikan Kehakiman` (SPK), Akta 695 of 2009, so the ASR "
     "dropped the `Pe` prefix. Three words, so nothing unrelated can match, and the whole "
     "phrase is a proper noun. https://www.jac.gov.my/ms/media/undang-undang"),
    (r"Jabatan Perkuam Negara(?![A-Za-z])", "Jabatan Peguam Negara",
     "1 occurrence in ep27 raw: `kita runding hantar representasi kepada Jabatan Perkuam "
     "Negara`. The Attorney General's Chambers, agc.gov.my, and a representation in a "
     "criminal case goes exactly there. `Perkuam` is not a word. Three words, so nothing "
     "else can match. https://www.agc.gov.my/"),
    (r"90\.6% accurate(?![A-Za-z0-9])", "95.6% accurate",
     "A FIGURE, NOT A NAME -- the second such entry, here for the same reason as the "
     "180.8 one above: this map is the only reviewed correction list mai_camera_raw.py "
     "applies during the build, so a fix recorded anywhere else is wiped by the next "
     "re-adoption. FOUND BY check_figures.py right after ep21 was adopted on 2026-09-15: "
     "the published text cited 95.6 and the new MAI raw said 90.6, so the figure lost its "
     "source. MAI is alone and wrong. Settled by witness count, the owner's rule of "
     "2026-09-12, and scripts/figure_witness.py ran it rather than a human ear: the "
     "pre-adoption local-ASR raw says 95.6, and the English caption track says `the last "
     "six to 95 6 6 accurate` at the same words, matched at 0.52 by lib_locate. Two "
     "independent witnesses against one. MAI is the better transcript in this very "
     "sentence on every OTHER count, which is why the digit needed measuring rather than "
     "a judgement about which engine wins: the local raw heard `the last six take tu` and "
     "`When tengah ni`, where MAI hears `the last six state tu` and `When Terengganu`, and "
     "Terengganu is a state. 90.6 occurs ONCE in the whole corpus, in this episode, so a "
     "corpus-wide anchor is safe. Anchored on the following word `accurate` so a bare "
     "90.6 elsewhere can never match. Rafizi is describing Invoke's own election "
     "prediction record over the last six state polls."),
    (r"180\.8 million(?![A-Za-z0-9])", "184.8 million",
     "A FIGURE, NOT A NAME -- the only such entry in this map, and it is here because this "
     "map is the one reviewed correction list that mai_camera_raw.py applies during the "
     "build, so a fix recorded anywhere else is wiped by the next re-adoption (the same "
     "argument that created data/forced_labels.json). FOUND BY check_figures.py right after "
     "ep31 was adopted on 2026-09-14: the published text cited `184.8 juta` and the new MAI "
     "raw said `180.8 million`, so the figure lost its source. MAI is alone and wrong. "
     "Settled the way CLAUDE.md settles a disputed digit, by witness count, and every "
     "witness available agrees: the local-ASR raw says 184.8, the Malay caption track says "
     "184.8 three times, and 180.8 appears in NO other file in the corpus -- one occurrence "
     "in one episode, which is why a corpus-wide anchor is safe here. Two independent "
     "witnesses beat one under the owner's 2026-09-12 rule, and the arithmetic is decisive "
     "rather than merely two-of-three: Farhash bought 462 million MMAG shares at 40 sen, "
     "and 462m x 0.40 = 184.8m exactly, while 180.8 divides to no whole share count at that "
     "price. The episode's own title agrees too -- `Farhash Rugi RM97.5 juta`, and 184.8 "
     "minus the 87.32 he sold for is 97.5, where 180.8 would give 93.5. Confirmed outside "
     "the corpus per CLAUDE.md rule 9. The neighbouring `484 juta` and `193.6 juta` are NOT "
     "touched: all three witnesses agree on both, so those are what was actually said. "
     "https://theedgemalaysia.com/node/749750"),
    (r"\b4475 hari", "5475 hari",
     "THE SECOND FIGURE IN THIS MAP, ep29, and the only case so far where ALL THREE "
     "TRANSCRIPTS WERE WRONG. Found by check_figures.py the moment ep29 was adopted, "
     "2026-09-14. Three readings of Najib's sentence in days: the pre-adoption local-ASR raw "
     "said `4,045`, MAI said `4475`, the Malay caption track said `40,475`. No two agree, so "
     "witness count cannot settle it and rule 8 would normally send this to the owner's ear. "
     "THE SENTENCE'S OWN ARITHMETIC SETTLES IT INSTEAD -- the fourth witness the owner's "
     "2026-09-12 rule names -- and two independent paths converge. Path one: the same passage "
     "states `Total hukuman penjara yang akan dijatuhkan adalah 15 tahun`, and 15 x 365 = "
     "5475. Path two: Haziq divides 2.3 bilion by the day count and reports `hampir 420 ribu "
     "ringgit` per day; 2.3e9 / 5475 = 420,091, where 4475 gives 514,000 and 40,475 gives "
     "56,800. MAI has every other number in the passage right (15 tahun, 2.3 billion, RM166 "
     "for the stolen formula milk, 420 ribu), so only the day count is wrong. `4475` occurs "
     "exactly ONCE in the whole corpus, so this anchor cannot reach anything else. The "
     "published files carried the old raw's `4,045` and are corrected separately in "
     "fix_published_figures.py."),
    (r"(?<![A-Za-z])Izah(?![A-Za-z])", "Izzah",
     "Nurul Izzah Anwar, and the biggest single name fix in this map: 91 occurrences in "
     "raw.md across 20 episodes plus 28 more in published files. FOUND 2026-09-15 by "
     "check_names.py on ep27, which flagged the published `Nurul Izzah` as unsourced because "
     "the newly adopted MAI raw says `Izah` where the old local-ASR raw had said `Izzah`. So "
     "MAI regressed a name the corpus already had right, and re-adoption is spreading it: "
     "ep27, ep28, ep30, ep31, ep32 and ep35 all carry `Izah` now. Web-verified per rule 1 "
     "rather than by counting: she is PKR's deputy president who asked to resign in August "
     "2026 with Saifuddin Nasution made acting deputy, which is exactly ep31's `Izah dengan "
     "Saifuddin tak bersalam`. "
     "EVERY ONE OF THE 91 WAS READ before this was written, because the corpus is full of "
     "real names ending in the same four letters. The identification is never in doubt: ep31 "
     "says `Izah ini adalah Timbalan Presiden PKR tau. Anak Perdana Menteri`, ep47 says `Izah "
     "dengan ayah dia, Datuk Seri Anwar`, ep35 asks `Who watches your father?` in the same "
     "breath, and ep58 runs the whole resignation. The one hit that is not obviously a person, "
     "ep33's `Izah City Zone`, is settled two sentences later by `promo tentang konsert Siti "
     "Nurhaliza daripada Timbalan Presiden kita`. "
     "LOOKBEHIND AND LOOKAHEAD ARE BOTH REQUIRED, and a bare `Izah` would be a disaster: it "
     "is a substring of Azizah (21 hits, and ep56 has `Wan Azizah ataupun Izah` in one "
     "sentence, the mother and the daughter), plus Nurizah 3, Rizah 3, Faizah 1, Roizah 1. "
     "Tested against all of them. https://en.wikipedia.org/wiki/Nurul_Izzah_Anwar"),
    (r"(?<![A-Za-z])Fuziyah(?![A-Za-z])", "Fuziah",
     "One occurrence, ep37 raw: `orang macam Fuziyah Salleh, orang macam Izah, orang macam "
     "Ramanan`. `Fuziah` appears 218 times in the corpus and `Fuziyah` once, and this map "
     "already carries three reviewed entries settling her name as Fuziah Salleh, PKR "
     "secretary-general. So this is the surname family's given-name twin, found in the same "
     "2026-09-15 pass as the Izzah fix and in the very same sentence. Guarded both sides for "
     "consistency with the entry above, though nothing in the corpus contains `Fuziyah` as a "
     "substring."),

    # ------------------------------------------------------------------------------------
    # `Babi` FOR THE HONORIFIC `YB`, found 2026-09-16. This is the YB-garble family again,
    # in the one spelling nobody had looked for, and it is the worst one: `babi` is Malay
    # for pig, so the corpus was putting a slur in a co-host's mouth where he said `YB`.
    # 59 occurrences of `babi` exist across the corpus. `fix_yb_honorific.py` cannot own
    # this variant, because that script substitutes a TOKEN corpus-wide and many of the 59
    # are the real animal: `babi hutan` (ep21, wild boar), `daging babi` (ep33, pork),
    # `gila babi` (ep28, an intensifier), `Babi-babi tu` (ep40, Animal Farm), and ep55's
    # nine-occurrence discussion of an actual pork issue in a Johor seat. So each entry
    # below is an ANCHORED span, read individually before it was written.
    #
    # DELIBERATELY NOT FIXED, two spans, because the word is genuinely ambiguous there:
    #   ep13 20:20  `Inilah yang berlaku minggu ni, babi.` -- spoken in a RAFIZI block, and
    #               he is the YB, so the vocative reading needs the speaker settled first.
    #   ep55 51:46  `Johor dah nak habis tempoh dah, Babi eh.` -- this is the episode that
    #               discusses a pork issue at length, so proximity cuts both ways.
    # Both need an ear. The rest are certain on the WORDS alone: `baik babi` is not a Malay
    # phrase, and `Settle, babi?` / `Nak baca babi?` mean nothing as the animal.
    #
    # Five of the ten `baik Babi` hits sit in a Rafizi block. That is a LABEL question, not
    # a word question: `Okey, baik YB` is Haziq's own transition line, already settled as
    # his by owner rulings in ep53 and ep57, so those blocks are the rule-7 shape. The word
    # is `YB` either way, which is why these are fixed without waiting on the labels.
    (r"baik Babi", "baik YB",
     "10 occurrences: ep28, ep34, ep54, ep56, ep58 x2, ep58, ep59, ep63. The show's own "
     "transition line, `Okey, baik YB`. `baik babi` is not a Malay phrase."),
    (r"Okey, baik\. Babi,", "Okey, baik. YB,", "ep54 1:04:22, Haziq. Same line, MAI put a full stop before the vocative."),
    (r"Baik, Babi,", "Baik, YB,", "ep24 31:41, Haziq: `Baik, YB, kita next.`"),
    (r"Babi, (\d+) jam (\d+) minit", r"YB, \1 jam \2 minit",
     "ep45 2:52:10 and ep53 2:56:05, both Haziq reading the running time back to Rafizi."),
    (r"Settle, Babi\?", "Settle, YB?", "ep57 03:24. Meaningless as the animal."),
    (r"macam mana Babi\?", "macam mana YB?", "ep27 17:35, Haziq putting a question to him."),
    (r"Nak baca Babi\?", "Nak baca YB?", "ep34 1:55:30: `Nak baca YB?` offers him the answer to read."),
    (r"Babi, realistically", "YB, realistically", "ep34 1:30:39, Haziq."),
    (r"Babi, kalau kena pilih", "YB, kalau kena pilih", "ep56 37:10, Haziq."),
    (r"So Babi, about this", "So YB, about this", "ep50 25:36, Wan Afiq hosting."),
    (r"komando tu Babi", "komando tu YB", "ep50 25:36, Wan Afiq, same turn."),
    (r"Okey, babi\. So saya dibetulkan", "Okey, YB. So saya dibetulkan",
     "ep50 2:17:50, Wan Afiq. Lower case here, which is why a case-sensitive sweep missed it."),
    (r"Okey, babi\. Babi, ada yang mengatakan", "Okey, YB. YB, ada yang mengatakan",
     "ep03:berhenti 1:23:55, the guest Faizal Rahman, doubled at the top of his turn. The "
     "same turn addresses Rafizi as `YB` twice more later (`Apa komen YB?`), found 2026-09-18 "
     "right after the MAI+camera adoption."),
    (r"itu saja Babi", "itu saja YB", "ep35 29:45, Haziq: `Ada, itu saja YB.`"),
    (r"soalan lain lah, Babi", "soalan lain lah, YB", "ep52 1:04:25, Haziq."),
    (r"yang beria, Babi", "yang beria, YB", "ep47 06:41, Haziq. `beria` is the show's own segment word."),
    (r"Tapi Babi\.", "Tapi YB.", "ep62 11:48, Haziq, addressing him before Farhan answers."),
    (r"Babi percaya dengan anti", "YB percaya dengan anti", "ep45 51:55, Haziq asking his view."),
    (r"Babi kata penting pendidikan", "YB kata penting pendidikan", "ep27 17:35, Haziq summarising his position."),
    (r"apa Babi yang katalah", "apa YB yang katalah", "ep63 2:56:57, the guest Sum Dek Joe."),
    (r"Ba- Babi kata tadi", "Ba- YB kata tadi",
     "ep60 2:46:14, Sum Dek Joe. The false start `Ba-` is MAI hearing the same two letters twice."),
    (r"Babi tahu satu harga", "YB tahu satu harga", "ep26 04:44, Haziq: `YB tahu satu harga tu berapa?`"),
    (r"Babi drive sendiri", "YB drive sendiri", "ep19 1:28:32. Meaningless as the animal."),
    (r"tak peduli babi\. RMK", "tak peduli YB. RMK",
     "ep05:berhenti 14:31 (?t=871s), the guest DSA, mid-sentence not after a comma. Owner "
     "ruled 2026-09-18 after listening: `siapa pun tak peduli babi. RMK yang sebelum-sebelum "
     "ni...` -- he addresses Rafizi as YB throughout the rest of the same turn."),
    (r"tempoh dah, Babi eh", "tempoh dah, YB eh",
     "ep55, the guest Dato' Dr Syed Azuan at 52:35 by MAI's clock (raw.md's stamp says "
     "51:46, 49 s out). OWNER RULED 2026-09-16, asked directly and answered *'its YB not "
     "Babi'*. I had left this one out of the first pass on purpose and escalated it, because "
     "the evidence pointed the OTHER way: MAI heard `Babi eh`, YouTube's captions heard "
     "`babi nah`, and ep55 is the episode that discusses a real pork issue at length. Two "
     "independent engines agreeing on a wrong word is not a majority, it is one piece of "
     "audio heard twice. The owner's ear outranks both. "
     "https://youtu.be/4mmuPwkB5f4?t=3155"),
    (r"Babi Roziah", "YB Rodziah",
     "ep04:berhenti ~13:37 (?t=817s, estimated, no caption track). A double garble in one "
     "phrase: `Babi` for the `YB` honorific (this family) AND `Roziah` for `Rodziah`, the "
     "guest named elsewhere in the corpus (ep09, as `Rodziah Ismail`). OWNER RULED "
     "2026-09-19 after being asked: `its YB Rodziah...`. Escalated rather than guessed, "
     "because the context (an ordinary village social-enterprise founder) did not confirm "
     "the YB-garble reading the way the other 36 occurrences did."),

    # ------------------------------------------------------------------------------------
    # SLURS THE REWRITE INVENTED, found 2026-09-16 by the same sweep that caught `Babi`.
    # These are the opposite direction to every entry above: raw.md is RIGHT and the
    # published interview files are wrong. The rewrite turned a benign word into an insult,
    # so the corpus quotes real people saying things they did not say. `check_slurs.py` is
    # the checker; each span below was read against raw.md before it was written.
    (r"budak bangsat enam angka", "budak bangsa enam angka",
     "ep15 16:00, interview.md and interview-ms.md. raw.md reads `budak bangsa enam angka`. "
     "`bangsa` is race or nation; `bangsat` is `bastard`. One letter, added by the rewrite."),
    # Two literal entries rather than one `([Bb])angsat` group. The group works, because the
    # applier uses re.subn, but the run report prints the replacement string verbatim and
    # `\1angsa final` in a log looks like a bug that shipped.
    (r"Bangsat final", "Bangsa final",
     "ep51 1:03:30, interview-ms.md x2. raw.md reads `Bangsa final kot. Bangsa final?` in a "
     "passage about a bandwagon Liverpool fan. `bangsa final` may itself be an ASR garble, "
     "but raw.md is the source and it does not contain an insult."),
    (r"bangsat final", "bangsa final", "ep51, the third occurrence in the same passage, lower case."),
    (r"celaka teruk", "Salawat teruk",
     "ep16, interview.md and interview-ms.md. raw.md reads `Salawat teruk`. The rewrite "
     "turned an Islamic blessing into `celaka`, which means cursed or damned. This is the "
     "most serious of the four, because the substituted word is religious."),
    (r"\"sial, aku dah berbulan-bulan", "\"damn, aku dah berbulan-bulan",
     "ep42, interview-ms.md. raw.md reads `Fadina mesti cakap, damn. Aku dah berbulan-bulan "
     "kena skip`. The speaker used the mild English word; the rewrite replaced it with a "
     "Malay vulgarity."),
    # THREE PUBLISHED SPANS THE 22 RAW ANCHORS ABOVE COULD NOT REACH, and `check_slurs.py`
    # is what found them, on its first run, which is the argument for the checker existing.
    # The rewrite rephrases around the vocative, so an anchor written against raw.md's
    # wording misses the published copy of the same sentence.
    (r"Okay Babi, 2 hours", "Okay YB, 2 hours",
     "ep45 interview-en.md. raw.md 2:52:10 is now `Okey, YB, 2 jam 50 minit`, and the "
     "English file says `2 hours 50 minutes`, so the Malay anchor could not match it."),
    (r"banyak komen tu, babi", "banyak komen tu, YB",
     "ep50 interview.md. raw.md 25:36 reads `komando tu`, the rewrite reads `komen tu`, so "
     "again the raw anchor misses. Wan Afiq is hosting and addressing Rafizi."),
    (r"Okey, babi\. Jadi saya dibetulkan", "Okey, YB. Jadi saya dibetulkan",
     "ep50 interview-ms.md. raw.md 2:17:50 reads `So saya dibetulkan`, the Malay file reads "
     "`Jadi saya dibetulkan`."),

    # And one in the other direction: raw.md itself is misspelled here.
    (r"(?<![Kk])hinzir(?![A-Za-z])", "khinzir",
     "ep55 raw.md: `macam hinzir itu disebut`. `hinzir` is not a word; `khinzir` is the "
     "formal Malay for pig, from Arabic, and all five occurrences in ep55's three published "
     "files spell it correctly. MAI dropped the leading k. The lookbehind is required so "
     "the already-correct `khinzir` is not turned into `kkhinzir`. NOT a slur finding: the "
     "speaker really is discussing a pork issue in a Johor seat, which is also why ep55's "
     "eleven `babi` are left alone."),

    # The show's own moderator, misspelled in the source. OWNER 2026-09-17.
    (r"Haziq Asfar(?![A-Za-z])", "Haziq Azfar",
     "Owner 2026-09-17: `Haziq Azfar is his real spelling, not asfar`. Web-verified: Haziq "
     "Azfar Ishak, moderator of the show, named as Azfar in the show's own promotion. This "
     "repo already agreed with the owner in two places and nothing checked the corpus "
     "against them: normalize_speaker_labels.RENAME and rebuild_roster.HOSTS both map "
     "`Haziq Azfar` to `Haziq`. Three spoken occurrences, all `Haziq Asfar`: ep00 1:50:50, "
     "where an audience member greets him by name, and ep30 2:28:52 twice, where Farhan "
     "says it. ep00's three published files inherited the misspelling. Anchored to the full "
     "two-word form, because `Asfar` alone is a real Arabic given name and could belong to "
     "someone else in a future episode. The speaker label itself is the short `Haziq` in "
     "every episode, so rule 3's verbatim-in-the-body requirement is untouched: this "
     "corrects a NAME the show spells one way, not a form of address."),

    # Rule 1b. Two slurs found 2026-09-17, both fresh: one from today's regeneration,
    # one from ep00's first MAI adoption.
    (r"like being a pariah in the party", "like the party was dying out",
     "ep11 interview-en.md, and the ONLY gate failure check_slurs.py reports today. "
     "raw.md says `Dia macam parti pupus, you know.` `pupus` means extinct or wiped out, "
     "so the sentence is about the party dying, not about a person. The English rewrite "
     "turned it into `like being a pariah in the party`, which calls the speaker an "
     "outcast. interview.md and interview-ms.md both keep `macam parti pupus` and are "
     "clean, so the defect is in the English pass alone. Written here rather than by hand "
     "because ep11 was regenerated at 14:26 TODAY and a hand fix would go the same way. "
     "This is the sixth instance of the rule 1b class where the rewrite changed a benign "
     "word into an insult, after ep15, ep51, ep16 and ep42."),

    (r"Babi Akmal", "YB Akmal",
     "ep00 03:23, Haziq, and it arrived with ep00's first MAI adoption today. MAI wrote "
     "`Oh. Babi Akmal.` while YouTube's own caption track hears `Oh Robi Akmal`, so both "
     "engines agree on the trailing `bi` and disagree on the first consonant. Neither heard "
     "a word: `YB` spoken fast is the documented source of this garble, and 39 spans of it "
     "were found on 2026-09-16. fix_yb_honorific.py lists twelve spellings and not this "
     "one, which is how the original 39 stayed hidden. The reading is also the only one "
     "that makes sense of the line: Haziq is calling people to the front, and this Akmal "
     "is a sitting Deputy Minister and PKR branch chief whom Rafizi later places `dekat "
     "depan ni`. NOT the same person as ep00's other Akmal, Dr Akmal Saleh of the KK Mart "
     "socks case. CONFIRMED BY THE OWNER 2026-09-17 from the caption-derived link "
     "https://youtu.be/2k8hW9hDvGE?t=210 , which puts the phrase at 3:35 inside a block "
     "stamped 03:23. Owner: 'its YB akmal'. Also recorded in "
     "data/speaker_adjudications.json under ep00_owner_ruled_2026_09_17, keyed 03:23 with "
     "text_was and text_now, so check_owner_text.py restores it if a rebuild reverts it. "
     "`Suara wekiat` in the same block is a separate garble and is deliberately left "
     "alone: the owner ruled on the name."),

    (r"Komen Babi\.", "Komen YB.",
     "ep64 1:53:37, Haziq: 'Komen YB.' at the end of a question to Rafizi, asking for his "
     "comment on TNB's monopoly -- the same MAI mishearing as every other 'Babi' for the "
     "honorific YB (36 occurrences found 2026-09-16). `Komen Babi` has no meaning in "
     "context; `Komen YB` is the show's ordinary phrase."),

    ("， 从 bila\\?",
     "Tahun bila?",
     "ep02:berhenti 02:28, Rafizi. MAI hallucinated two stray Chinese characters (a "
     "full-width comma and 'from') in the middle of an otherwise all-Malay/English turn -- "
     "not a name or agency, but the same class of ASR garble this file already corrects "
     "for (see 'barbarunilah' above). CONFIRMED BY THE OWNER 2026-09-18: 'rafizi is saying "
     "\"tahun bila?\" theres no chinese character. thats weird'. Also recorded in "
     "data/speaker_adjudications.json under ep02:berhenti_owner_ruled_2026_09_18, keyed "
     "02:28 with text_was and text_now, so check_owner_text.py restores it if a rebuild "
     "reverts it."),
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

    # Both places the YouTube title appears. The frontmatter `title:` field, and the bold
    # line `write_navigation.py` builds FROM that field at the top of every transcript.
    QUOTED_TITLE = re.compile(r"^(?:title:.*|\*\*.+ episode \d+ — .*\*\*\s*)$", re.M)

    def mask_quoted_titles(src):
        """Hide every line that quotes YouTube's own title, so no rule can rewrite it.

        `title:` is YouTube's video title, copied verbatim. It is a quotation of the source,
        not our prose, and restyling it would make the file disagree with the video it
        cites. This was found when a Felda -> FELDA rule was about to rewrite ep26's title
        from `Azam Baki, UEC & Felda | YBM EP 26`, which is what YouTube actually shows.

        PROTECTING ONLY THE FRONTMATTER LINE WAS NOT ENOUGH, found 2026-09-11.
        `write_navigation.py` writes that same title into a bold header line in the body,
        where the rules could still reach it -- so the two scripts fought over ep26's header
        and whichever ran last won. A manual `fix_proper_nouns --write` left it reading
        FELDA; the next adoption's `write_navigation --write` put it back to Felda. Masking
        both lines ends the oscillation, and it settles on the YouTube spelling, which is
        the one the docstring above says is correct.
        """
        spans = [m.span() for m in QUOTED_TITLE.finditer(src)]
        out, marks, last = [], [], 0
        for i, (a, b) in enumerate(spans):
            out.append(src[last:a])
            out.append(f"\x00TITLE{i}\x00")
            marks.append(src[a:b])
            last = b
        out.append(src[last:])
        return "".join(out), marks

    for path in targets():
        original = path.read_text(encoding="utf-8")
        text, marks = mask_quoted_titles(original)
        hits = {}
        for rx, rep, _ in compiled:
            text, n = rx.subn(rep, text)
            if n:
                hits[rep] = hits.get(rep, 0) + n
                totals[rep] += n
        for i, mark in enumerate(marks):
            text = text.replace(f"\x00TITLE{i}\x00", mark)
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
