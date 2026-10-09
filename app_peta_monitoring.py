import streamlit as st
import cv2
import pytesseract
import re
import numpy as np
from PIL import Image
import io
import zipfile
import pandas as pd
import json
import os
import shutil

# =====================================================================
# PENGATURAN TESSERACT OCR (Cross-platform)
# =====================================================================
tesseract_path = shutil.which("tesseract")
if tesseract_path:
    pytesseract.pytesseract.tesseract_cmd = tesseract_path
else:
    windows_default = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if os.path.exists(windows_default):
        pytesseract.pytesseract.tesseract_cmd = windows_default

st.set_page_config(page_title="Bulk Rename Peta WSS", page_icon="🗺️", layout="wide")

st.title("Bulk Rename Peta WSS")

# --- FILE PENYIMPANAN RIWAYAT LOKAL (Agar tidak hilang saat refresh) ---
PROGRESS_FILE = "progress_scan.json"

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r") as f:
                data = json.load(f)
                return set(data)
        except:
            return set()
    return set()

def save_progress(progress_set):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(list(progress_set), f)

# Inisialisasi Memori (Session State)
if 'telah_diproses' not in st.session_state:
    st.session_state.telah_diproses = False
    st.session_state.data_hasil = []
    st.session_state.file_zip = None

if 'uploader_counter' not in st.session_state:
    st.session_state.uploader_counter = 0

if 'scanned_sls_set' not in st.session_state:
    st.session_state.scanned_sls_set = load_progress()

# Load Master Data SLS (Pastikan SLS_Natuna.xlsx ada di satu folder dengan app.py)
@st.cache_data
def load_master_data():
    return pd.read_excel('SLS_Natuna.xlsx', dtype={'idsubsls': str})

try:
    df_master = load_master_data()
except Exception as e:
    st.error(f"⚠️ File `SLS_Natuna.xlsx` tidak ditemukan di folder project! Error: {e}")
    st.stop()

# Layout Tombol Upload & Clear
col_up1, col_up2 = st.columns([4, 1])
with col_up2:
    st.write("") 
    st.write("")
    if st.button("🗑️ Kosongkan Sesi"):
        st.session_state.telah_diproses = False
        st.session_state.data_hasil = []
        st.session_state.file_zip = None
        st.session_state.uploader_counter += 1
        st.rerun()

# Upload File Peta dengan Key dinamis berbasis counter agar bersih total saat di-reset
uploaded_files = st.file_uploader(
    "Pilih file peta", 
    type=["jpg", "jpeg", "png"], 
    accept_multiple_files=True,
    key=f"uploader_peta_{st.session_state.uploader_counter}"
)

if uploaded_files:
    st.info(f"Ada {len(uploaded_files)} file yang dipilih untuk diproses.")

    if st.button("Mulai Proses Identifikasi ;)"):
        zip_buffer = io.BytesIO()
        progress_bar = st.progress(0)
        status_teks = st.empty()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for i, uploaded_file in enumerate(uploaded_files):
                status_teks.text(f"Memproses: {uploaded_file.name} ({i+1}/{len(uploaded_files)})")

                image = Image.open(uploaded_file)
                img_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
                tinggi, lebar = img_cv.shape[:2]

                sn = None

                # Definisikan 4 sisi tepi gambar (Atas, Bawah, Kiri, Kanan)
                # agar aman untuk mendeteksi teks di posisi manapun akibat rotasi peta.
                h_margin = int(tinggi * 0.25)
                w_margin = int(lebar * 0.25)

                regions = [
                    img_cv[0:h_margin, 0:lebar],                  # Sisi Atas
                    img_cv[tinggi - h_margin:tinggi, 0:lebar],      # Sisi Bawah
                    img_cv[0:tinggi, 0:w_margin],                  # Sisi Kiri
                    img_cv[0:tinggi, lebar - w_margin:lebar],      # Sisi Kanan
                ]

                found = False
                for region in regions:
                    if region.size == 0:
                        continue

                    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)

                    # Tambahkan padding putih untuk mengeliminasi gangguan garis kotak hitam
                    gray = cv2.copyMakeBorder(gray, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=[255, 255, 255])

                    # Terapkan Thresholding (Otsu) agar kontras angka dan latar belakang semakin jelas
                    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

                    # Rotasi lengkap 360 derajat (0, 90, 180, 270 derajat)
                    rotasi_list = [
                        thresh, 
                        cv2.rotate(thresh, cv2.ROTATE_90_CLOCKWISE), 
                        cv2.rotate(thresh, cv2.ROTATE_180),
                        cv2.rotate(thresh, cv2.ROTATE_90_COUNTERCLOCKWISE)
                    ]

                    for img_pro in rotasi_list:
                        try:
                            # Coba berbagai konfigurasi PSM untuk pembacaan teks dalam kotak
                            for psm in [6, 11, 3, 7, 8]:
                                teks = pytesseract.image_to_string(img_pro, config=f'--psm {psm}')
                                cocok = re.search(r'\b\d{16}\b', teks)
                                if cocok:
                                    sn = str(cocok.group(0))
                                    found = True
                                    break
                            if found:
                                break
                        except Exception:
                            continue
                    if found:
                        break

                if sn:
                    nama_file_baru = f"{sn}_WSS.jpg"

                    img_byte_arr = io.BytesIO()
                    image.save(img_byte_arr, format='JPEG')
                    img_byte_arr_val = img_byte_arr.getvalue()

                    zip_file.writestr(nama_file_baru, img_byte_arr_val)

                    # Masukkan ke set dan simpan otomatis ke file JSON lokal
                    st.session_state.scanned_sls_set.add(sn)
                    save_progress(st.session_state.scanned_sls_set)

                    st.session_state.data_hasil.append({
                        "file_asli": uploaded_file.name,
                        "status": "Sukses",
                        "sn": sn,
                        "nama_baru": nama_file_baru,
                        "bytes": img_byte_arr_val
                    })
                else:
                    st.session_state.data_hasil.append({
                        "file_asli": uploaded_file.name,
                        "status": "Gagal",
                        "sn": "-",
                        "nama_baru": None,
                        "bytes": None
                    })

                progress_bar.progress((i + 1) / len(uploaded_files))

        st.session_state.file_zip = zip_buffer.getvalue()
        status_teks.empty()
        progress_bar.empty()
        st.session_state.telah_diproses = True
        st.success("Proses identifikasi selesai!")

    # Tampilkan Hasil Sesi Ini
    if st.session_state.telah_diproses:
        st.write("---")
        st.write("### 📄 Hasil Proses File Terbaru")
        for i, hasil in enumerate(st.session_state.data_hasil):
            col1, col2, col3 = st.columns([2, 3, 2])
            col1.write(f"`{hasil['file_asli']}`")
            if hasil['status'] == "Sukses":
                col2.success(f"**{hasil['sn']}**")
                col3.download_button("⬇️ Download Satuan", data=hasil['bytes'], file_name=hasil['nama_baru'], mime="image/jpeg", key=f"dl_{i}")
            else:
                col2.error("Gagal mendeteksi")
                col3.write("-")

        # Tombol Download ZIP
        st.write("---")
        st.subheader("📦 Arsip Download")
        st.download_button(
            label="Download Semua (.zip)",
            data=st.session_state.file_zip,
            file_name="Bulk_Rename_WSS.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True
        )

# =====================================================================
# MASTER MONITORING 784 SLS (DENGAN WARNA FONT MERAH/HIJAU & FILTER DESA)
# =====================================================================
st.write("---")
st.header("📊 Monitoring 784 SLS Natuna")

df_master['idsubsls'] = df_master['idsubsls'].astype(str)
df_master['Status_Scan'] = df_master['idsubsls'].apply(
    lambda x: "Sudah" if x in st.session_state.scanned_sls_set else "Belum"
)

# Metrik Ringkasan
total_sls = len(df_master)
sudah_scan = len(df_master[df_master['Status_Scan'] == "Sudah"])
belum_scan = total_sls - sudah_scan

m1, m2, m3 = st.columns(3)
m1.metric("Total Target SLS", total_sls)
m2.metric("Sudah Discan", sudah_scan)
m3.metric("Belum Discan", belum_scan)

# Tombol Reset
if st.button("🔄 Reset Status Monitoring"):
    st.session_state.scanned_sls_set = set()
    if os.path.exists(PROGRESS_FILE):
