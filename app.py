import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import gspread
import pandas as pd
import streamlit as st
from google import genai
from PIL import Image


APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
CSV_PATH = DATA_DIR / "monthly_receipts.csv"
DEFAULT_MODEL = "gemini-2.5-flash"

SHEET_COLUMNS = [
    "tanggal_input",
    "tanggal_transaksi",
    "bulan_laporan",
    "nama_toko",
    "alamat_toko",
    "kategori",
    "metode_bayar",
    "subtotal",
    "pajak",
    "diskon",
    "total",
    "mata_uang",
    "item_json",
    "catatan",
]


PROMPT = """
Anda adalah sistem ekstraktor nota belanja Indonesia.
Baca gambar nota, lalu keluarkan JSON valid saja.
Jangan beri markdown, komentar, atau teks tambahan.

Skema JSON:
{
  "tanggal_transaksi": "YYYY-MM-DD atau kosong jika tidak terbaca",
  "nama_toko": "string",
  "alamat_toko": "string",
  "kategori": "makanan|minuman|transportasi|belanja rumah|kesehatan|pendidikan|hiburan|lainnya",
  "metode_bayar": "tunai|kartu|qris|transfer|e-wallet|tidak diketahui",
  "subtotal": number,
  "pajak": number,
  "diskon": number,
  "total": number,
  "mata_uang": "IDR",
  "items": [
    {
      "nama": "string",
      "qty": number,
      "harga_satuan": number,
      "total": number
    }
  ],
  "catatan": "ringkasan singkat jika ada bagian tidak terbaca"
}

Aturan:
- Gunakan angka murni tanpa titik ribuan, contoh 12500.
- Jika total tidak terbaca, hitung dari item/subtotal bila mungkin.
- Jika tanggal tidak ada tahun, gunakan tahun berjalan.
- Jika kolom tidak terbaca, isi string kosong atau 0.
"""


def get_secret(name: str, default: Any = "") -> Any:
    try:
        return st.secrets.get(name, default)
    except Exception:
        return os.getenv(name.upper(), default)


def normalize_number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^0-9,.-]", "", str(value)).replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_json_response(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        cleaned = match.group(0)
    return json.loads(cleaned)


def normalize_receipt(data: dict[str, Any]) -> dict[str, Any]:
    today = date.today()
    transaction_date = str(data.get("tanggal_transaksi") or "").strip()
    month_report = today.strftime("%Y-%m")

    if transaction_date:
        try:
            parsed_date = datetime.fromisoformat(transaction_date).date()
            transaction_date = parsed_date.isoformat()
            month_report = parsed_date.strftime("%Y-%m")
        except ValueError:
            transaction_date = ""

    items = data.get("items") or []
    if not isinstance(items, list):
        items = []

    normalized_items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized_items.append(
            {
                "nama": str(item.get("nama", "")).strip(),
                "qty": normalize_number(item.get("qty")),
                "harga_satuan": normalize_number(item.get("harga_satuan")),
                "total": normalize_number(item.get("total")),
            }
        )

    row = {
        "tanggal_input": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tanggal_transaksi": transaction_date,
        "bulan_laporan": month_report,
        "nama_toko": str(data.get("nama_toko", "")).strip(),
        "alamat_toko": str(data.get("alamat_toko", "")).strip(),
        "kategori": str(data.get("kategori", "lainnya")).strip().lower() or "lainnya",
        "metode_bayar": str(data.get("metode_bayar", "tidak diketahui")).strip().lower()
        or "tidak diketahui",
        "subtotal": normalize_number(data.get("subtotal")),
        "pajak": normalize_number(data.get("pajak")),
        "diskon": normalize_number(data.get("diskon")),
        "total": normalize_number(data.get("total")),
        "mata_uang": str(data.get("mata_uang", "IDR")).strip().upper() or "IDR",
        "item_json": json.dumps(normalized_items, ensure_ascii=False),
        "catatan": str(data.get("catatan", "")).strip(),
    }

    if row["total"] <= 0 and normalized_items:
        row["total"] = sum(item["total"] for item in normalized_items)

    return row


def extract_receipt(image: Image.Image, api_key: str, model: str) -> dict[str, Any]:
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=[PROMPT, image],
        config={"response_mime_type": "application/json"},
    )
    return normalize_receipt(parse_json_response(response.text or "{}"))


def read_local_data() -> pd.DataFrame:
    if not CSV_PATH.exists():
        return pd.DataFrame(columns=SHEET_COLUMNS)
    return pd.read_csv(CSV_PATH)


def append_local(row: dict[str, Any]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    df = pd.DataFrame([row], columns=SHEET_COLUMNS)
    df.to_csv(CSV_PATH, mode="a", index=False, header=not CSV_PATH.exists())


def get_google_sheet():
    spreadsheet_url = get_secret("spreadsheet_url")
    spreadsheet_key = get_secret("spreadsheet_key")
    worksheet_name = get_secret("worksheet_name", "Laporan Bulanan")
    service_account = get_secret("gcp_service_account")

    if not service_account or not (spreadsheet_url or spreadsheet_key):
        return None

    credentials = dict(service_account)
    gc = gspread.service_account_from_dict(credentials)
    spreadsheet = gc.open_by_url(spreadsheet_url) if spreadsheet_url else gc.open_by_key(spreadsheet_key)

    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=worksheet_name, rows=1000, cols=len(SHEET_COLUMNS))

    values = worksheet.get_all_values()
    if not values:
        worksheet.append_row(SHEET_COLUMNS)

    return worksheet


def append_sheet(row: dict[str, Any]) -> None:
    worksheet = get_google_sheet()
    if worksheet is None:
        return
    worksheet.append_row([row.get(column, "") for column in SHEET_COLUMNS], value_input_option="USER_ENTERED")


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["bulan_laporan", "kategori", "total"])
    clean = df.copy()
    clean["total"] = pd.to_numeric(clean["total"], errors="coerce").fillna(0)
    return (
        clean.groupby(["bulan_laporan", "kategori"], as_index=False)["total"]
        .sum()
        .sort_values(["bulan_laporan", "total"], ascending=[False, False])
    )


st.set_page_config(page_title="Ekstraktor Nota Belanja", page_icon="🧾", layout="wide")

st.markdown(
    """
    <style>
    .block-container { padding-top: 1.5rem; max-width: 1180px; }
    [data-testid="stMetricValue"] { font-size: 1.6rem; }
    div[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 8px; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Ekstraktor Nota Belanja")

api_key = get_secret("gemini_api_key") or get_secret("GOOGLE_API_KEY")
model = st.sidebar.text_input("Model Gemini", value=get_secret("gemini_model", DEFAULT_MODEL))
send_to_sheet = st.sidebar.toggle("Kirim ke Google Sheets", value=True)

uploaded_file = st.file_uploader("Upload foto nota", type=["png", "jpg", "jpeg", "webp"])

left, right = st.columns([0.9, 1.1], vertical_alignment="top")

with left:
    if uploaded_file:
        image = Image.open(uploaded_file).convert("RGB")
        st.image(image, use_container_width=True)
    else:
        image = None
        st.info("Upload foto nota untuk mulai ekstraksi.")

with right:
    if not api_key:
        st.warning("Isi `gemini_api_key` di Streamlit secrets atau env `GEMINI_API_KEY`.")

    extract_clicked = st.button("Ekstrak Nota", type="primary", disabled=not uploaded_file or not api_key)

    if extract_clicked and image is not None and api_key:
        with st.spinner("Membaca nota dan menyusun JSON..."):
            try:
                receipt = extract_receipt(image, api_key, model)
                st.session_state["receipt"] = receipt
            except Exception as exc:
                st.error(f"Gagal ekstraksi: {exc}")

    receipt = st.session_state.get("receipt")
    if receipt:
        edited = st.data_editor(
            pd.DataFrame([receipt], columns=SHEET_COLUMNS),
            hide_index=True,
            use_container_width=True,
            num_rows="fixed",
        )

        col_save, col_total = st.columns([0.35, 0.65], vertical_alignment="center")
        with col_save:
            if st.button("Simpan Laporan", type="primary"):
                row = edited.iloc[0].to_dict()
                append_local(row)
                if send_to_sheet:
                    append_sheet(row)
                st.success("Data tersimpan.")
                st.session_state.pop("receipt", None)
                st.rerun()
        with col_total:
            st.metric("Total nota", f"Rp {normalize_number(edited.iloc[0]['total']):,.0f}".replace(",", "."))

st.divider()

data = read_local_data()
summary = build_summary(data)

metric_a, metric_b, metric_c = st.columns(3)
total_spend = pd.to_numeric(data.get("total", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()
metric_a.metric("Total tersimpan", f"Rp {total_spend:,.0f}".replace(",", "."))
metric_b.metric("Jumlah nota", len(data))
metric_c.metric("Bulan aktif", data["bulan_laporan"].nunique() if not data.empty else 0)

tab_data, tab_summary = st.tabs(["Data Nota", "Ringkasan Bulanan"])

with tab_data:
    st.dataframe(data, use_container_width=True, hide_index=True)
    if not data.empty:
        st.download_button(
            "Download CSV",
            data.to_csv(index=False).encode("utf-8"),
            file_name="laporan_nota_bulanan.csv",
            mime="text/csv",
        )

with tab_summary:
    st.dataframe(summary, use_container_width=True, hide_index=True)
    if not summary.empty:
        st.bar_chart(summary, x="kategori", y="total", color="bulan_laporan")
