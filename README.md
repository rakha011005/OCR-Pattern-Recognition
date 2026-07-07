# Ekstraktor Nota Belanja ke Spreadsheet Bulanan

Aplikasi Streamlit untuk membaca foto nota belanja memakai Gemini API, mengubah hasilnya menjadi JSON terstruktur, lalu menyimpan laporan bulanan ke CSV lokal dan Google Sheets.

## Fitur

- Upload foto nota dari laptop atau HP.
- Ekstraksi toko, tanggal, kategori, metode bayar, item, pajak, diskon, dan total.
- Edit hasil sebelum disimpan.
- Simpan otomatis ke `data/monthly_receipts.csv`.
- Kirim opsional ke Google Sheets memakai `gspread`.
- Ringkasan total per bulan dan kategori.

## Setup Lokal

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .streamlit\secrets.toml.example .streamlit\secrets.toml
streamlit run app.py
```

Isi `.streamlit/secrets.toml`:

- `gemini_api_key`: API key dari Google AI Studio.
- `spreadsheet_url` atau `spreadsheet_key`: target Google Sheets.
- `[gcp_service_account]`: JSON service account Google Cloud.

Bagikan Google Sheets ke email `client_email` service account dengan akses Editor.

## Deploy Streamlit Community Cloud

1. Push proyek ke GitHub.
2. Buka Streamlit Community Cloud.
3. Pilih repo dan file utama `app.py`.
4. Masukkan isi `.streamlit/secrets.toml` ke menu Secrets.
5. Deploy.

## Alur Kerja

1. User upload foto nota.
2. App kirim gambar ke `gemini-2.5-flash`.
3. Gemini balas JSON sesuai skema.
4. User koreksi hasil bila perlu.
5. App simpan ke CSV lokal dan Google Sheets.

## Sumber API

- Gemini API dan Google Gen AI SDK: https://ai.google.dev/api/generate-content
- gspread: https://docs.gspread.org/
