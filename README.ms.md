# Transkrip Podcast YBM

Read in [English](README.md).

Transkrip podcast panjang Rafizi Ramli (*Yang Bakar Menteri* / *Yang Berhenti Menteri* / *YBM*), dibina dengan [pendekatan arkib berstruktur yang sama](https://github.com/ChatPRD/lennys-podcast-transcripts) seperti Lenny's Podcast Transcripts.

Playlist sumber: https://www.youtube.com/playlist?list=PLqJKhYZQ8r9Uz3IPEh0lXpF17w3LQK62N

Transkrip ini disemak dengan dua sumber lain. Pertama, sari kata automatik YouTube bagi setiap episod, yang digunakan di seluruh arkib untuk mengesahkan cap masa dan mencari kandungan yang hilang. Kedua, [@mediarakyat](https://www.youtube.com/@mediarakyat), yang memuat naik semula episod yang sama dengan sari kata yang dijana secara berasingan, jadi sesuatu penemuan boleh disahkan berbanding rakaman yang berlainan. Kedua-dua sumber tidak meliputi setiap episod.

Arkib ini merangkumi episod penuh sepanjang satu jam atau lebih. Ia meninggalkan teaser pendek, klip sorotan, snippet kad-quote, dan episod format ringkas dalam playlist yang sama.

> Transkrip dan tulisan semula ini dihasilkan oleh model AI. Saya menyemaknya pada bahagian-bahagian terpilih berbanding rakaman asal, tetapi saya tidak menyemak mana-mana episod baris demi baris. Sila baca [nota ketepatan](#nota-ketepatan) sebelum anda memetik apa-apa daripada arkib ini.

Untuk aliran kerja itu sendiri, lihat [ARCHITECTURE.md](ARCHITECTURE.md) (dalam Bahasa Inggeris). Untuk setiap kegagalan yang saya hadapi semasa membinanya, lihat [ENGINEERING_LOG.md](ENGINEERING_LOG.md) (dalam Bahasa Inggeris).

## Kenapa arkib ini wujud

Podcast Rafizi Ramli membincangkan bagaimana sesuatu cadangan reformasi kerajaan dikemukakan, siapa menghalangnya, kenapa, dan apa yang dia akan buat secara berbeza pada masa depan. Butiran itu biasanya hanya wujud dalam video sepanjang 2-3 jam yang jarang orang sempat semak semula. Saya bina arkib ini supaya rekod itu wujud sebagai teks, supaya seorang wartawan boleh memetiknya, seorang penulis biografi boleh merujuknya, dan sesiapa yang cuba memahami kenapa sesuatu reformasi gagal boleh mencarinya.

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
CREDITS.md                               # model pihak ketiga, lesen, petikan
QA_CHECKLIST.md                          # dijana oleh scripts/qa_check.py
```

Setiap episod berada dalam `episodes/<nama-rancangan>/<tarikh-siaran>-<slug-tajuk>/` dengan empat fail. `<nama-rancangan>` ialah `yang-bakar-menteri` untuk siri asal 2024, atau `yang-berhenti-menteri` untuk semua episod selepas penukaran nama pada 2025:

- `raw.md`: transkrip hampir-verbatim terus daripada audio, lengkap dengan cap masa dan label penutur. Perkataan pengisi (filler) dibersihkan sedikit sahaja, dan tiada apa-apa diparafrasa atau diringkaskan. Bagi episod yang ditranskrip melalui alternatif ASR tempatan, label penutur datang daripada satu pusingan pengesanan penutur (diarization) berasingan berdasarkan bunyi suara, bukan daripada model transkripsi itu sendiri (lihat [ARCHITECTURE.md](ARCHITECTURE.md)).
- `interview.md`: tulisan semula gaya Tanya-Jawab akhbar yang dikemas, dikekalkan dalam bahasa campuran Inggeris dan Bahasa Melayu asal, paling hampir dengan cara perbualan itu sebenarnya dituturkan.
- `interview-en.md`: tulisan semula yang sama, diterjemah penuh ke Bahasa Inggeris.
- `interview-ms.md`: tulisan semula yang sama, diterjemah penuh ke Bahasa Melayu.

Kesemua empat fail berkongsi frontmatter YAML yang sama (tajuk, ID video, URL YouTube, tarikh siaran, tempoh, jumlah tontonan, hos, tetamu). Tiga versi interview turut membawa ringkasan janaan-AI dan tag topik. Pilih versi yang paling sesuai dengan keperluan anda.

`data/manifest.json` ialah indeks episod penuh, metadata sahaja tanpa teks transkrip, dan ia menggerakkan aliran kerja ini.

## Nota ketepatan

Model AI menghasilkan transkrip dan tulisan semula ini dengan mendengar audio sumber. Setiap episod diaudit secara automatik (lihat di bawah), dan saya mendengar rakaman asal pada mana-mana bahagian yang memerlukan pertimbangan manusia: label penutur yang diragui, kandungan yang kelihatan hilang, atau nama yang luar biasa. **Saya tidak menyemak mana-mana episod baris demi baris**, jadi kesilapan, salah dengar, dan salah kaitan penutur masih mungkin berlaku, terutamanya semasa pertindihan suara (cross-talk). Percampuran bahasa (code-switching) antara Bahasa Melayu dan Inggeris dikekalkan, dan tidak diterjemahkan. Anggap `raw.md` sebagai rujukan paling hampir dengan sumber asal, dan `interview.md` sebagai tulisan semula editorial yang dibina di atasnya.

Bagi episod yang ditranskrip melalui alternatif ASR tempatan (lihat [ARCHITECTURE.md](ARCHITECTURE.md#known-limitations), dalam Bahasa Inggeris), label penutur `raw.md` datang daripada satu pusingan pengesanan penutur (diarization) berasingan dengan pyannote.audio, bukan daripada diarization Gemini sendiri. Label itu bermula sebagai "Speaker N" tanpa nama, dan saya memetakannya kepada nama sebenar secara manual semasa semakan, sama seperti label umum Gemini. Anggap label mana-mana episod yang belum saya semak sebagai belum disahkan, terutamanya dalam pertukaran cepat antara pelbagai penutur.

`python scripts/qa_check.py` mengaudit setiap episod untuk kesan kegagalan yang saya tahu: tulisan semula terpotong, cap masa yang berhalusinasi, penaakulan model yang tertinggal dalam teks, kandungan yang hilang dari tengah episod, dan lain-lain. Skrip ini menulis hasilnya ke `QA_CHECKLIST.md`. Jalankan skrip ini selepas mana-mana kumpulan pemprosesan, dan baca hasilnya dan bukan hanya kod keluar (exit code). Beberapa kegagalan ini tidak menghasilkan sebarang ralat atau kod keluar bukan-sifar, hanya kandungan fail yang rosak atau terpotong. Baris yang bersih bermakna tiada kesan kegagalan *yang diketahui* dikesan, dan bukan bermakna saya telah mengesahkan episod itu. Dua episod kelihatan bersih selama beberapa bulan sedangkan 41% dan 80% kandungannya hilang, sehingga saya menambah pemeriksaan untuk kesan tersebut.

Nama khas daripada enjin ASR tempatan belum disemak berbanding mana-mana kamus rujukan, jadi nama orang dan ejaan luar biasa mungkin salah. Saya merancang satu pusingan pembetulan manual menggunakan kamus PRPM Dewan Bahasa dan Pustaka melalui pustaka `malaya` (lihat [ARCHITECTURE.md](ARCHITECTURE.md#known-limitations), dalam Bahasa Inggeris, untuk butiran alat tersebut).

## Lesen dan penafian

Saya telah meletakkan kod aliran kerja dalam repositori ini, segala-galanya di bawah `scripts/`, ke dalam domain awam di bawah [CC0 1.0](LICENSE). Anda tidak perlu kebenaran dan tidak terhutang atribusi untuk menggunakan, mengubah suai, atau mengedarkannya semula.

Itu meliputi kod saya sendiri. Aliran kerja ini bergantung kepada model dan alat yang mempunyai terma masing-masing, dan dua daripada terma itu terpakai kepada sesiapa yang menjalankannya semula: penjajar paksa MMS oleh Meta adalah **CC-BY-NC 4.0, bukan komersial sahaja**, dan model embedding WeSpeaker adalah CC-BY-4.0 dan memerlukan atribusi. Penggunaan semula transkrip yang sudah siap tidak terjejas, kerana ia tidak melibatkan model tersebut. [CREDITS.md](CREDITS.md) (dalam Bahasa Inggeris) mengandungi senarai penuh, petikan yang diminta oleh penulisnya, dan hasil kerja yang menjadi asas kepada projek ini.

Transkrip episod di bawah `episodes/` merupakan transkripsi dan terjemahan podcast milik Rafizi Ramli sendiri, diambil daripada saluran YouTube awamnya. Saya tidak mengenakan sebarang sekatan sendiri ke atas penggunaan semula fail-fail ini: tiada kebenaran diperlukan, tiada kredit diwajibkan. Kandungan pertuturan asal, iaitu rancangan itu sendiri dan apa jua yang dituturkan oleh Rafizi Ramli atau tetamunya, adalah kepunyaan mereka dan bukan saya, dan tiada apa di sini yang mengubah hakikat tersebut. Gunakan arkib ini untuk penyelidikan, laporan, atau membina alat anda sendiri di atasnya. Sila bawa sebarang pertikaian mengenai kandungan asal kepada pencipta asal, bukan kepada repositori ini.

Saya tiada kaitan rasmi dengan Rafizi Ramli, pejabatnya, atau produksi *Yang Bakar Menteri* / *Yang Berhenti Menteri*.

## Menghasilkan semula arkib ini

Keseluruhan aliran kerja ada dalam `scripts/`. [ARCHITECTURE.md](ARCHITECTURE.md) (dalam Bahasa Inggeris) merangkumi teknologi yang digunakan, persediaan sekali sahaja, arahan, dan cara hasilnya disahkan. [ENGINEERING_LOG.md](ENGINEERING_LOG.md) (dalam Bahasa Inggeris) merekodkan setiap kegagalan yang saya hadapi.
