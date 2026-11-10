# NAWA.AI — Landing Page Copy (Versi Pitching ke Klien, Draft v2)

Bahasa: Indonesia. Audiens: pemilik bisnis, direktur operasional, kepala IT, dan tim compliance di perusahaan menengah.
Perubahan dari v1: fokus ke hasil bisnis dan pengurangan risiko, bukan fitur teknis. Detail teknis dipindah ke satu bagian untuk tim IT. CTA berubah dari "coba demo" menjadi "jadwalkan demo dan pilot".
Aturan: angka bertanda `[ISI]` harus berasal dari evaluation report atau pilot nyata. Jangan tulis target sebagai hasil.

---

## 1. Hero

**Eyebrow:** AI untuk perusahaan, berjalan di server Anda sendiri

**Headline:** Tanyakan apa saja ke data dan dokumen perusahaan Anda. Datanya tidak pernah keluar.

**Subheadline:** NAWA.AI menjawab pertanyaan dari SOP dan kontrak, membaca database dengan bahasa sehari-hari, dan menyusun laporan lewat AI agent. Setiap tindakan penting menunggu persetujuan orang Anda. Semuanya berjalan di infrastruktur milik perusahaan.

**CTA utama:** Jadwalkan demo 30 menit
**CTA kedua:** Lihat demo 3 menit

**Garis kepercayaan:** Data tetap di server Anda · Bisa berjalan tanpa internet · Setiap jawaban ada sumbernya

---

## 2. Masalah (bahasa pemilik bisnis)

**Judul:** Informasinya ada. Menemukannya yang lama.

- Karyawan menghabiskan waktu mencari SOP, kebijakan, atau kontrak yang sebenarnya sudah ada.
- Pemilik bisnis menunggu analis untuk pertanyaan sederhana seperti "outlet mana yang paling lemah bulan ini?"
- Laporan bulanan disusun manual, berulang, dan sering terlambat.
- Tim mulai memakai AI di luar pengawasan, dan dokumen perusahaan ikut terkirim ke layanan pihak ketiga.

**Kalimat penutup:** Anda butuh AI yang membantu, tanpa memaksa Anda menyerahkan data.

---

## 3. Solusi dalam satu kalimat

**Judul:** Satu asisten untuk dokumen, data, dan pekerjaan rutin, di dalam perusahaan Anda.

---

## 4. Hasil yang didapat

Format: hasil bisnis dulu, fitur sebagai pendukung.

### Jawaban dalam detik, bukan jam
Tanyakan prosedur, kebijakan, atau isi kontrak. Jawaban datang dengan kutipan ke halaman dokumen asli. Jika informasinya tidak ada, NAWA.AI bilang tidak ada, bukan mengarang.
*Contoh: "Apa prosedur jika pelanggan komplain makanannya tidak layak?"*

### Keputusan tanpa menunggu analis
Pemilik bisnis bertanya dalam bahasa biasa. NAWA.AI menampilkan angka, grafik, dan penjelasan, plus query yang dipakai sehingga bisa diperiksa.
*Contoh: "Outlet mana dengan penjualan terendah bulan Agustus?"*

### Laporan lengkap dari satu instruksi
Beberapa AI agent membagi tugas: menarik data penjualan, mencari konteks di dokumen, lalu menulis laporan dengan rekomendasi. Setiap langkah bisa ditelusuri.
*Contoh: "Kenapa penjualan Bandung turun dan apa rekomendasinya?"*

### Pekerjaan rutin jalan sendiri, tetap di bawah kendali
Jadwalkan laporan bulanan atau peringatan stok menipis. Tindakan berisiko, misalnya mengirim email, menunggu persetujuan manusia dulu.

**Strip hasil pilot** (isi setelah pilot pertama, jangan dikarang):
Waktu cari informasi turun `[ISI]%` · Laporan bulanan dari `[ISI]` jam menjadi `[ISI]` menit · `[ISI]` pertanyaan data dijawab tanpa analis

---

## 5. Kenapa self-hosted (pembeda utama)

**Judul:** Kecerdasan AI tanpa menitipkan data perusahaan.

Kebanyakan produk AI mengirim dokumen Anda ke cloud pihak ketiga. NAWA.AI dipasang di server Anda sendiri.

| Kekhawatiran | Jawaban NAWA.AI |
|---|---|
| "Dokumen kami tidak boleh keluar." | Dokumen, database, dan log tetap di infrastruktur Anda. |
| "Kami terikat regulasi dan kerahasiaan klien." | Model AI berjalan lokal secara default. Penyedia eksternal hanya aktif jika admin mengizinkan. |
| "Server kami tidak terhubung ke internet." | Mode offline memblokir semua koneksi keluar. |
| "Kami tidak mau bergantung pada satu vendor." | Seluruh komponen open source. Tidak ada telemetry yang dikirim keluar. |
| "Siapa yang boleh melihat apa?" | Akses per peran dan per tim. Tim A tidak bisa membaca data tim B. |

---

## 6. Kendali penuh atas AI

**Judul:** AI yang bisa diperiksa, dibatasi, dan diaudit.

- **Selalu ada sumber.** Jawaban dilengkapi kutipan, atau dinyatakan tidak ditemukan.
- **AI tidak bisa mengubah data Anda.** Pertanyaan data hanya membaca. Query berbahaya diblokir dan dicatat.
- **Tindakan berisiko perlu persetujuan.** Kirim email, panggil layanan luar, atau tulis data menunggu di Approval Center.
- **Semua tercatat.** Siapa bertanya apa, kapan, dan apa hasilnya. Siap untuk audit internal.
- **Kualitas diukur, bukan diklaim.** Setiap fitur diuji dengan kumpulan soal baku, termasuk kasus yang gagal. Laporan evaluasi dibuka untuk klien.

---

## 7. Cara memulai (menurunkan rasa risiko)

**Judul:** Mulai kecil, buktikan dulu, baru perluas.

1. **Demo 30 menit.** Kami tunjukkan dengan data contoh. Lalu Anda uji dengan pertanyaan Anda sendiri.
2. **Pilot satu tim.** Pasang di server Anda. Muat dokumen dan satu database dari satu departemen. Pilot dibatasi `[ISI]` minggu.
3. **Evaluasi bersama.** Kita ukur hasil pilot dengan indikator yang disepakati sebelumnya.
4. **Perluas bertahap.** Tambah departemen, sumber data, dan alur otomatis sesuai hasil.

**CTA:** Jadwalkan demo dan diskusi pilot

---

## 8. Untuk setiap peran

| Peran | Yang didapat |
|---|---|
| **Pemilik bisnis / direktur** | Memahami performa bisnis tanpa menunggu laporan. |
| **Manajer operasional** | Menemukan SOP dan kebijakan dalam hitungan detik. |
| **Analis bisnis** | Laporan lengkap dengan sumber dari satu instruksi. |
| **Tim IT dan keamanan** | Kontrol akses, audit log, mode offline, dan kendali atas penyedia AI. |
| **Compliance / legal** | Data tidak meninggalkan perusahaan dan setiap tindakan tercatat. |

---

## 9. Untuk tim IT (ringkas)

**Judul:** Dipasang dengan satu perintah.

```bash
git clone https://github.com/<user>/nawa-ai && cd nawa-ai
cp .env.example .env
docker compose --profile local-llm up -d
```

- Docker Compose di server on-premise, VPS, atau private cloud.
- Minimum: 4 vCPU, 16 GB RAM, 50 GB disk. Disarankan: 8 vCPU, 32 GB RAM, GPU 16–24 GB.
- Model lokal via Ollama atau vLLM. Penyedia eksternal opsional lewat satu gateway.
- Stack: FastAPI, Next.js, PostgreSQL + pgvector, Redis, LangGraph, Langfuse. Semua open source.
- Backup, restore, dan upgrade dengan migrasi otomatis.

---

## 10. FAQ klien

**Apakah ini layanan langganan (SaaS)?** Bukan. NAWA.AI dipasang dan dijalankan di server Anda.

**Apakah data kami dikirim ke penyedia AI?** Tidak secara default. Model lokal adalah pengaturan awal. Penyedia eksternal hanya aktif jika admin mengizinkan, dan tidak pernah aktif di mode offline.

**Bagaimana jika jawabannya tidak ada di dokumen kami?** NAWA.AI menyatakan tidak menemukannya. Ia tidak mengarang.

**Bisakah AI mengubah atau menghapus data kami?** Tidak. Akses data bersifat baca saja. Tindakan lain yang berisiko menunggu persetujuan orang.

**Seberapa akurat?** Kami ukur dengan kumpulan soal baku dan membuka hasilnya, termasuk kegagalan. Angka untuk data Anda didapat dari pilot. `[ISI setelah evaluation report]`

**Butuh GPU?** Disarankan agar nyaman dipakai tim. Untuk skala kecil, server tanpa GPU dengan model kecil atau penyedia eksternal opsional tetap bisa.

**Berapa lama sampai berjalan?** Pemasangan dalam hitungan jam. Pilot pada satu tim berjalan `[ISI]` minggu.

**Siapa yang mengoperasikan?** Admin di tim Anda. Dukungan pemasangan dan pelatihan `[ISI: sesuai model layanan]`.

**Ada integrasi dengan sistem kami?** Saat ini PostgreSQL, dokumen PDF/DOCX/TXT/MD, email via SMTP, dan webhook. Integrasi lain dibahas per kebutuhan.

---

## 11. CTA penutup

**Judul:** Coba dengan pertanyaan dan dokumen Anda sendiri.

**Subjudul:** Demo 30 menit, tanpa komitmen. Datanya tetap milik Anda dari menit pertama.

**CTA utama:** Jadwalkan demo
**CTA kedua:** Hubungi kami lewat email

---

## Footer / meta

**Tagline:** NAWA.AI. From Business Knowledge to Intelligent Execution.

**Meta title:** NAWA.AI — AI self-hosted untuk dokumen, data, dan otomasi perusahaan
**Meta description:** Tanya dokumen, analisis database dengan bahasa biasa, dan jalankan laporan lewat AI agent. Dipasang di server Anda, data tidak keluar, tindakan penting perlu persetujuan.

---

## Catatan untuk pemilik

1. **Model layanan belum ada di rencana.** Master plan menyatakan bukan SaaS dan tanpa billing. Bagian harga, dukungan, dan SLA sengaja dikosongkan (`[ISI]`). Putuskan: lisensi, jasa pemasangan, atau retainer.
2. **Klaim hasil bisnis** (hemat waktu, dan seterusnya) belum punya data. Jangan dipublikasikan sebelum pilot atau studi kasus nyata.
3. **Bukti sosial belum ada.** Tambahkan testimoni, logo klien, atau studi kasus setelah pilot pertama. Sementara itu, demo Resto Noesantara adalah satu-satunya contoh.
4. **Kontak dan jadwal demo** butuh form atau alamat email nyata.
5. **Klaim "dukungan regulasi"** sengaja tidak menyebut aturan tertentu (UU PDP, OJK, dan lainnya). Konfirmasi dengan legal sebelum menambahkannya.
6. **Evaluation report terbuka untuk klien** dijanjikan di bagian 6. Pastikan laporan itu memang dibuat dan boleh dibagikan.
