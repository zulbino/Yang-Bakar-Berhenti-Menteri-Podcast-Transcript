# Transkrip Podcast YBM

Read in [English](README.md).

Transkrip podcast panjang Rafizi Ramli (*Yang Bakar Menteri* / *Yang Berhenti Menteri* / *YBM*), dibina dengan [pendekatan arkib berstruktur yang sama](https://github.com/ChatPRD/lennys-podcast-transcripts) seperti Lenny's Podcast Transcripts.

Playlist sumber: https://www.youtube.com/playlist?list=PLqJKhYZQ8r9Uz3IPEh0lXpF17w3LQK62N

Hanya episod penuh (1+ jam) disertakan. Teaser pendek, klip sorotan, snippet kad-quote, dan episod format ringkas daripada playlist yang sama tidak disertakan.

> Transkrip dan tulisan semula dijana oleh model AI, disemak pada bahagian-bahagian terpilih berbanding rakaman asal tetapi tidak disahkan baris demi baris. Lihat [Nota ketepatan](#nota-ketepatan) sebelum memetik apa-apa daripada arkib ini.

Lihat [ARCHITECTURE.md](ARCHITECTURE.md) (dalam Bahasa Inggeris) untuk rajah aliran kerja penuh, model-model yang telah diuji, dan sebab di sebalik pilihan teknologi yang digunakan.

## Kenapa arkib ini wujud

Podcast Rafizi Ramli membincangkan bagaimana sesuatu cadangan reformasi kerajaan dikemukakan, siapa menghalangnya, kenapa, dan apa yang dia akan buat secara berbeza pada masa depan: butiran yang biasanya hanya wujud dalam video sepanjang 2-3 jam yang jarang orang sempat semak semula. Saya bina arkib ini supaya rekod itu wujud sebagai teks; seorang wartawan boleh memetiknya, seorang penulis biografi boleh merujuknya, dan sesiapa yang cuba memahami kenapa sesuatu reformasi gagal boleh mencarinya tanpa perlu semak balik video berjam-jam lamanya.

## Struktur

```
episodes/
├── yang-bakar-menteri/                  # siri 2024, 6 episod
│   └── 2024-01-08-ep01-.../
│       ├── raw.md                       # transkrip hampir-verbatim
│       ├── interview.md                 # tulisan semula gaya Tanya-Jawab, bahasa campuran
│       ├── interview-en.md              # terjemahan Bahasa Inggeris
│       └── interview-ms.md              # terjemahan Bahasa Melayu
└── yang-berhenti-menteri/               # selepas penukaran nama 2025, 61 episod
    └── 2025-09-12-ep13-.../             # empat fail yang sama setiap episod
data/
└── manifest.json                        # indeks episod (metadata sahaja, tiada teks transkrip)
scripts/                                 # kod pipeline, lihat ARCHITECTURE.md
ARCHITECTURE.md                          # teknologi: persediaan, arahan, pengesahan
ENGINEERING_LOG.md                       # setiap kegagalan, puncanya dan pembetulannya
QA_CHECKLIST.md                          # dijana oleh scripts/qa_check.py
```

Setiap episod berada dalam `episodes/<nama-rancangan>/<tarikh-siaran>-<slug-tajuk>/` dengan empat fail. `<nama-rancangan>` ialah `yang-bakar-menteri` untuk siri asal 2024, atau `yang-berhenti-menteri` untuk semua episod selepas penukaran nama pada 2025:

- `raw.md`: transkrip hampir-verbatim terus daripada audio, lengkap dengan cap masa dan label penutur. Perkataan pengisi (filler) dibersihkan sedikit tetapi tiada apa-apa diparafrasa atau diringkaskan. Episod yang ditranskrip melalui alternatif ASR tempatan mendapat label penutur daripada satu pusingan pengesanan penutur (diarization) berasingan berdasarkan bunyi suara, bukan daripada model transkripsi itu sendiri (lihat [ARCHITECTURE.md](ARCHITECTURE.md)).
- `interview.md`: tulisan semula gaya Tanya-Jawab akhbar yang dikemas, dikekalkan dalam bahasa campuran Inggeris/Bahasa Melayu asal, paling hampir dengan cara perbualan itu sebenarnya dituturkan.
- `interview-en.md`: tulisan semula yang sama, diterjemah penuh ke Bahasa Inggeris.
- `interview-ms.md`: tulisan semula yang sama, diterjemah penuh ke Bahasa Melayu.

Kesemua empat fail berkongsi frontmatter YAML yang sama (tajuk, ID video, URL YouTube, tarikh siaran, tempoh, jumlah tontonan, hos, tetamu); tiga versi interview turut membawa ringkasan janaan-AI dan tag topik. Pilih versi yang paling sesuai dengan keperluan anda.

`data/manifest.json` ialah indeks episod penuh (metadata sahaja, tiada teks transkrip) yang menggerakkan aliran kerja ini.

## Nota ketepatan

Transkrip dan tulisan semula dijana oleh model AI yang mendengar terus daripada audio sumber. Setiap episod diaudit secara automatik (lihat di bawah), dan bahagian yang memerlukan pertimbangan manusia -- label penutur yang diragui, kandungan yang disyaki hilang, nama yang luar biasa -- disemak dengan telinga berbanding rakaman asal. **Tiada episod yang disahkan baris demi baris**, jadi kesilapan, salah dengar, atau salah kaitan penutur masih mungkin berlaku, terutamanya semasa pertindihan suara (cross-talk). Percampuran bahasa (code-switching) antara Bahasa Melayu dan Inggeris dikekalkan, bukan diterjemah. Anggap `raw.md` sebagai rujukan paling hampir dengan sumber asal, dan `interview.md` sebagai tulisan semula editorial yang dibina di atasnya.

Episod yang ditranskrip melalui alternatif ASR tempatan (lihat [ARCHITECTURE.md](ARCHITECTURE.md#known-limitations), dalam Bahasa Inggeris) mendapat label penutur `raw.md` daripada satu pusingan pengesanan penutur (diarization) berasingan berdasarkan bunyi suara (pyannote.audio), bukan daripada diarization Gemini sendiri. Label ini bermula sebagai "Speaker N" tanpa nama, yang kemudiannya dipetakan secara manual kepada nama sebenar semasa semakan, sama seperti label umum Gemini. Anggap label mana-mana episod yang belum disemak sebagai belum disahkan, terutamanya dalam pertukaran cepat antara pelbagai penutur.

`python scripts/qa_check.py` mengaudit setiap episod untuk kesan kegagalan yang diketahui (tulisan semula terpotong, cap masa yang berhalusinasi, penaakulan model yang tertinggal dalam teks, dan lain-lain) dan menulis hasilnya ke `QA_CHECKLIST.md`. Jalankan skrip ini selepas mana-mana kumpulan pemprosesan dan semak hasilnya sebelum mempercayai kod keluar (exit code) yang bersih: beberapa kegagalan ini tidak menghasilkan sebarang ralat atau kod keluar bukan-sifar, hanya kandungan fail yang rosak atau terpotong.

Nama khas (nama orang, ejaan luar biasa) yang ditranskrip oleh enjin ASR tempatan belum disemak berbanding mana-mana kamus rujukan. Satu pusingan pembetulan secara manual dirancang, menyemak perkataan yang disyaki berbanding kamus PRPM Dewan Bahasa dan Pustaka melalui pustaka `malaya` (lihat [ARCHITECTURE.md](ARCHITECTURE.md#known-limitations), dalam Bahasa Inggeris, untuk butiran alat tersebut).

## Lesen dan penafian

Kod aliran kerja dalam repositori ini (segala-galanya di bawah `scripts/`) dikeluarkan di bawah [CC0 1.0](LICENSE): domain awam, tiada kebenaran atau atribusi diperlukan untuk menggunakan, mengubah suai, atau mengedarkannya semula.

Transkrip episod di bawah `episodes/` merupakan transkripsi dan terjemahan podcast milik Rafizi Ramli sendiri, disumberkan daripada saluran YouTube awamnya. Projek ini tidak mengenakan sebarang sekatan sendiri ke atas penggunaan semula fail-fail ini: tiada kebenaran diperlukan, tiada kredit diwajibkan. Walau bagaimanapun, kandungan pertuturan asal (rancangan itu sendiri, dan apa jua yang dituturkan oleh Rafizi Ramli atau tetamunya) adalah kepunyaan mereka, bukan projek ini, dan tiada apa di sini yang mengubah hakikat tersebut. Gunakan arkib ini untuk penyelidikan, laporan, atau membina alat anda sendiri di atasnya; sebarang pertikaian mengenai kandungan asal hendaklah dirujuk kepada pencipta asal, bukan repositori ini.

Arkib ini tiada kaitan rasmi dengan Rafizi Ramli, pejabatnya, atau produksi *Yang Bakar Menteri* / *Yang Berhenti Menteri*.

## Menghasilkan semula arkib ini

Keseluruhan pipeline ada dalam `scripts/`, dan segala yang diperlukan untuk
menjalankannya -- teknologi yang digunakan, persediaan sekali sahaja, arahan, dan cara
hasilnya disahkan -- ada dalam [ARCHITECTURE.md](ARCHITECTURE.md) (dalam Bahasa
Inggeris). Setiap kegagalan yang membentuk pipeline ini direkodkan dalam
[ENGINEERING_LOG.md](ENGINEERING_LOG.md) (dalam Bahasa Inggeris).
