import os
import sys
import json
import time
import hashlib
import base64
import datetime
import subprocess
import requests as req
from urllib.parse import quote
import re
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import functools
import sys

path = '/home/rsydstore'  # GANTI DENGAN PATH LENGKAP FOLDER ANDA
if path not in sys.path:
    sys.path.append(path)

from app import app as application
# --- Konfigurasi Flask ---
app = Flask(__name__)
# Ganti ini dengan string yang sangat acak dan aman di produksi!
app.secret_key = 'super_secret_key_yang_sangat_kuat_dan_panjang_1234567890' 

# --- Fungsi Pembantu (Disimpan, dengan penyesuaian jika perlu) ---

def dev_id():
    # Di lingkungan web, kami tidak memiliki akses langsung ke 'getprop'
    # seperti di Android/Termux. Untuk demonstrasi, kita akan membuat ID dummy.
    # Di lingkungan nyata (VPS), Anda mungkin ingin ID unik berdasarkan server
    # atau meminta pengguna memasukkannya secara manual (jika itu adalah ID akun mereka).
    # Untuk tujuan ini, kita akan membuat ID berdasarkan waktu atau informasi lingkungan server.
    
    # Contoh: ID dummy berdasarkan hostname dan waktu
    hostname = os.uname().nodename
    current_time_ms = int(time.time() * 1000)
    unique_str = f"{hostname}-{current_time_ms}-{os.getpid()}"
    sha256_hash = hashlib.sha256(unique_str.encode()).hexdigest()
    return sha256_hash[:17]

def exp_date(expiry_date_str):
    try:
        expiry_date = datetime.datetime.strptime(expiry_date_str, "%d-%m-%Y").date()
        current_date = datetime.datetime.now().date()
        return (expiry_date - current_date).days
    except ValueError:
        return -1

def dec_b64(content):
    decoded_bytes = base64.b64decode(content)
    decoded_str = decoded_bytes.decode('utf-8')
    return json.loads(decoded_str)

def fetch_json(url, retries=3, delay=1):
    for attempt in range(retries):
        try:
            response = req.get(url, timeout=20)
            if response.status_code == 200:
                data = response.json()
                if "exit()" in str(data):
                    flash("Lisensi Anda tidak valid. Silakan hubungi administrator.", "danger")
                    return None # Jangan exit(), Flask akan merender
                return data
            # Jika status code bukan 200, coba lagi atau kembalikan None
            # flash(f"Kesalahan HTTP: {response.status_code}", "warning")
        except (req.RequestException, ValueError) as e:
            # flash(f"Kesalahan jaringan atau parsing JSON (Percobaan {attempt + 1}): {e}", "warning")
            pass
        time.sleep(delay)
    # flash("Gagal mengambil data setelah beberapa percobaan.", "danger")
    return None

def send_wa(build_id, nama_user="N/A", pesan_tambahan=""):
    message = f"Assalamualaikum min ini\nNama: {nama_user}\nId  : {build_id}"
    if pesan_tambahan:
        message += f"\n\n{pesan_tambahan}"
    encoded_message = quote(message)
    url = f"https://wa.me/+6282120873066?text={encoded_message}"
    return url # Mengembalikan URL alih-alih membuka langsung

def license_check_internal():
    # Mengambil DEVICE_ID_INFO dari sesi. Jika tidak ada, buat yang baru.
    build_id_hash = session.get('DEVICE_ID_INFO')
    if not build_id_hash:
        build_id_hash = dev_id()
        session['DEVICE_ID_INFO'] = build_id_hash # Simpan ID baru di sesi

    url = f'https://api.github.com/repos/RSYDSTORE/R02/contents/license/{build_id_hash}.json'
    flash("Memeriksa lisensi Anda...", "info")

    file_data = fetch_json(url)
    if file_data:
        content_base64 = file_data.get('content')
        file_data_decoded = {}
        if content_base64:
            try:
                file_data_decoded = dec_b64(content_base64)
            except json.JSONDecodeError:
                flash("Error mendekode data lisensi. Silakan hubungi admin.", "danger")
                session['unregistered_id'] = build_id_hash # Simpan ID untuk halaman daftar
                return 'unregistered'
            except Exception:
                flash("Error memproses data lisensi. Silakan hubungi admin.", "danger")
                session['unregistered_id'] = build_id_hash
                return 'unregistered'
        else:
            # Handle direct JSON if content is not base64 encoded
            file_data_decoded = file_data
            if 'message' in file_data_decoded and file_data_decoded['message'] == 'Not Found':
                flash("File lisensi tidak ditemukan di repositori.", "danger")
                session['unregistered_id'] = build_id_hash
                return 'unregistered'

        name = file_data_decoded.get("name", "Pengguna Tidak Dikenal")
        expiry_date_str = file_data_decoded.get("expiry_date")
        role = file_data_decoded.get("role", "tidak diketahui")
        
        session['USER_LICENSE_NAME'] = name
        flash(f"Hallo {name}!", "success")

        if expiry_date_str:
            days_left = exp_date(expiry_date_str)
            if days_left > 0:
                session['USER_LICENSE_EXPIRY_INFO'] = f"{expiry_date_str} ({days_left} hari tersisa)"
                flash(f"Anda adalah {role.upper()}!", "success")
                return 'valid' # Lisensi valid
            else:
                if days_left == 0:
                    session['USER_LICENSE_EXPIRY_INFO'] = f"Kedaluwarsa hari ini ({expiry_date_str})"
                    flash(f"Lisensi Anda habis hari ini! Silakan perbarui segera.", "warning")
                else:
                    session['USER_LICENSE_EXPIRY_INFO'] = f"Kedaluwarsa pada {expiry_date_str} ({abs(days_left)} hari yang lalu)"
                    flash(f"Lisensi Anda telah kedaluwarsa {abs(days_left)} hari yang lalu!", "danger")
                
                session['expiry_info'] = { # Simpan info untuk halaman expired
                    'build_id_hash': build_id_hash,
                    'tanggal_kedaluwarsa_lengkap': expiry_date_str, # Use original for full string
                    'user_name': session.get('USER_LICENSE_NAME', 'N/A')
                }
                return 'expired' # Lisensi kedaluwarsa
        else:
            session['USER_LICENSE_EXPIRY_INFO'] = "Tanggal kedaluwarsa tidak ditentukan"
            flash("Data lisensi tidak lengkap (tidak ada tanggal kedaluwarsa).", "danger")
            session['unregistered_id'] = build_id_hash
            return 'unregistered'
    else:
        session['USER_LICENSE_NAME'] = "Tidak Terdaftar"
        session['USER_LICENSE_EXPIRY_INFO'] = "Tidak Terdaftar"
        session['unregistered_id'] = build_id_hash
        return 'unregistered'


def login_internal(auth_input_val):
    headers = {'Content-Type': 'application/json'}
    
    if len(auth_input_val) > 25: # Heuristic for X-Authorization token
        headers['X-Authorization'] = auth_input_val
        session['auth_headers'] = headers
        return True

    login_data = {
        "AndroidDeviceID": auth_input_val, "TitleId": "4AE9", "CreateAccount": False}
    try:
        response = req.post("https://4AE9.playfabapi.com/Client/LoginWithAndroidDeviceID", headers=headers, json=login_data)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        
        response_data = response.json()
        if "data" in response_data and "SessionTicket" in response_data["data"]:
            auth_token = response_data["data"]["SessionTicket"]
            headers['X-Authorization'] = auth_token
            session['auth_headers'] = headers # Simpan di sesi
            session['auth_input'] = auth_input_val # Simpan juga device id nya
            return True
        else:
            error_message = response_data.get("errorMessage", "Periksa Device ID Anda!")
            flash(f"Login gagal. {error_message}", "danger")
            return False
    except req.exceptions.RequestException as e:
        flash(f"Koneksi gagal saat login. Periksa jaringan Anda. ({e})", "danger")
        return False
    except Exception as e:
        flash(f"Terjadi kesalahan saat login: {e}", "danger")
        return False

def mxx_fetch_info_internal():
    headers = session.get('auth_headers')
    if not headers:
        flash("Sesi login tidak ditemukan.", "danger")
        return None, None

    data = json.dumps({"InfoRequestParameters": {"GetUserAccountInfo": True, "GetUserVirtualCurrency": True}})
    try:
        response = req.post(
            'https://4ae9.playfabapi.com/Client/GetPlayerCombinedInfo',
            headers=headers,
            data=data
        )
        response.raise_for_status()
        parser = response.json()
        if parser.get('code') == 200:
            info = parser['data']['InfoResultPayload']
            money = info['UserVirtualCurrency'].get('RP', 0)
            name = '[ganti nama]'
            try:
                name = info['AccountInfo']['TitleInfo']['DisplayName']
            except KeyError:
                pass
            return name, money
        else:
            error_msg = parser.get('errorMessage', 'Gagal memuat informasi akun.')
            flash(f"Gagal memuat informasi akun: {error_msg}", "danger")
            return None, None
    except req.exceptions.RequestException as e:
        flash(f"Koneksi gagal saat mengambil info akun: {e}", "danger")
        return None, None
    except Exception as e:
        flash(f"Terjadi kesalahan saat mengambil info akun: {e}", "danger")
        return None, None

def tampilkan_detail_transaksi_internal(nama_akun_display, nominal_transaksi, saldo_sebelum_rp, saldo_setelah_rp, berhasil, jenis_transaksi_override=None, nama_sebelum_ganti=None, nama_sesudah_ganti=None):
    sekarang = datetime.datetime.now()
    nama_hari_id = {
        'Monday': 'Senin', 'Tuesday': 'Selasa', 'Wednesday': 'Rabu',
        'Thursday': 'Kamis', 'Friday': 'Jumat', 'Saturday': 'Sabtu', 'Sunday': 'Minggu'
    }
    nama_bulan_id = {
        'January': 'Januari', 'February': 'Februari', 'March': 'Maret',
        'April': 'April', 'May': 'Mei', 'June': 'Juni',
        'July': 'Juli', 'August': 'Agustus', 'September': 'September',
        'October': 'Oktober', 'November': 'November', 'December': 'Desember'
    }

    tgl_str = ""
    try:
        import locale
        # locale.setlocale(locale.LC_TIME, 'id_ID.UTF-8') # Removed this as it might cause issues on some systems
        tgl_str_raw = sekarang.strftime('%A, %d %B %Y')
        day_en_check = sekarang.strftime('%A')
        month_en_check = sekarang.strftime('%B')
        if day_en_check in nama_hari_id or month_en_check in nama_bulan_id:
            hari_id_val = nama_hari_id.get(day_en_check, day_en_check)
            bulan_id_val = nama_bulan_id.get(month_en_check, month_en_check)
            tgl_str = f"{hari_id_val}, {sekarang.day} {bulan_id_val} {sekarang.year}"
        else:
            tgl_str = tgl_str_raw
    except (ImportError, AttributeError): # Removed locale.Error, UnicodeEncodeError
        hari_en = sekarang.strftime('%A')
        bulan_en = sekarang.strftime('%B')
        hari_id = nama_hari_id.get(hari_en, hari_en)
        bulan_id = nama_bulan_id.get(bulan_en, bulan_en)
        tgl_str = f"{hari_id}, {sekarang.day} {bulan_id} {sekarang.year}"

    jam_str = sekarang.strftime('%H:%M:%S')
    status_str = "Berhasil" if berhasil else "Gagal"
    pesan_info_penting = ""
    
    transaction_details = {
        "akun": nama_akun_display,
        "jenis": "",
        "nominal": "N/A",
        "saldo_sebelum": "N/A",
        "saldo_sesudah": "N/A",
        "jam": jam_str,
        "tanggal": tgl_str,
        "status": status_str,
        "info_penting": []
    }

    if jenis_transaksi_override == "Ganti Nama Akun":
        akun_display_final = nama_akun_display if nama_akun_display else (nama_sesudah_ganti if nama_sesudah_ganti else "N/A")
        nama_sebelum_final = nama_sebelum_ganti if nama_sebelum_ganti else "N/A"
        nama_sesudah_final = nama_sesudah_ganti if nama_sesudah_ganti else (akun_display_final if berhasil else nama_sebelum_final)

        transaction_details.update({
            "akun": akun_display_final,
            "jenis": "Ganti Nama",
            "nama_sebelum": nama_sebelum_final,
            "nama_sesudah": nama_sesudah_final,
            "info_penting": [
                "Buka Bussid Nya Mas",
                "Cek Apakah Namanya sudah tergantikan?",
                "Jika Akun Bussid nya terputus Login Ke akun Lama(Ganti Akun).",
                "Jangan Sambungkan Biar akun Bussid nya tidak hilang"
            ]
        })
    elif jenis_transaksi_override == "Hapus Akun":
        if berhasil:
            pesan_info_penting = [
                "Akun Anda telah berhasil diproses untuk penghapusan.",
                "Anda tidak akan bisa login lagi dengan akun ini.",
                "Silakan buat akun baru atau login dengan akun lain jika diperlukan."
            ]
        else:
            pesan_info_penting = [
                "Proses penghapusan akun tidak berhasil atau dibatalkan.",
                "Akun Anda seharusnya masih dapat diakses jika tidak dihapus.",
                "Jika Anda membatalkan, tidak ada perubahan pada akun Anda."
            ]
        transaction_details.update({
            "akun": nama_akun_display if nama_akun_display else "N/A",
            "jenis": "Hapus Akun",
            "info_penting": pesan_info_penting
        })
    else:
        nominal_display = "N/A"
        if nominal_transaksi is not None:
            try:
                nominal_display = f"{abs(nominal_transaksi):,}"
            except ValueError:
                 nominal_display = str(nominal_transaksi)

        saldo_sebelum_display = "N/A"
        if saldo_sebelum_rp is not None:
            try:
                saldo_sebelum_display = f"{saldo_sebelum_rp:,}"
            except ValueError:
                saldo_sebelum_display = str(saldo_sebelum_rp)

        saldo_setelah_display = "N/A"
        if saldo_setelah_rp is not None:
            try:
                saldo_setelah_display = f"{saldo_setelah_rp:,}"
            except ValueError:
                saldo_setelah_display = str(saldo_setelah_rp)

        jenis_transaksi_str_default = jenis_transaksi_override
        if jenis_transaksi_str_default is None:
            if nominal_transaksi is not None and isinstance(nominal_transaksi, (int, float)):
                if nominal_transaksi == 0 and not berhasil :
                     jenis_transaksi_str_default = "Cek Saldo (Sudah Habis)"
                elif nominal_transaksi == 0 and berhasil:
                     jenis_transaksi_str_default = "Cek Saldo (Sudah Habis)"
                else:
                     jenis_transaksi_str_default = "Top Up Instan" if nominal_transaksi > 0 else "Kuras Saldo Instan"
            else:
                jenis_transaksi_str_default = "Operasi Akun"

        nama_akun_final = nama_akun_display if nama_akun_display else "User Game (Gagal Deteksi)"
        
        transaction_details.update({
            "akun": nama_akun_final,
            "jenis": jenis_transaksi_str_default,
            "nominal": f"Rp {nominal_display}",
            "saldo_sebelum": f"Rp {saldo_sebelum_display}",
            "saldo_sesudah": f"Rp {saldo_setelah_display}",
            "info_penting": [
                "Buka Bussid Nya Mas",
                "Ss Kan Di Garasi Ketik Done",
                "Jika Akun Bussid nya terputus Login Ke akun Lama(Ganti Akun).",
                "Jangan Sambungkan Biar Uang Bussid nya tidak hilang"
            ]
        })
    
    session['last_transaction_details'] = transaction_details
    return redirect(url_for('display_transaction_details'))

def ProssesUangInternal(brp_value):
    headers = session.get('auth_headers')
    if not headers:
        flash("Sesi tidak valid untuk proses uang.", "danger")
        return False
    data = json.dumps({
        "FunctionName": "AddRp",
        "FunctionParameter": {"addValue": brp_value},
        "RevisionSelection": "Live",
        "GeneratePlayStreamEvent": False
    })
    try:
        response = req.post("https://4ae9.playfabapi.com/Client/ExecuteCloudScript", headers=headers, data=data)
        response.raise_for_status()
        result = response.json()
        if 'Error' not in result and result.get('data', {}).get('FunctionName') == 'AddRp':
            return True
        else:
            flash(f"Gagal memproses uang: {result.get('Error', {}).get('Message', 'Error tidak diketahui')}", "danger")
            return False
    except (req.exceptions.RequestException, Exception) as e:
        flash(f"Kesalahan saat memproses uang: {e}", "danger")
        return False

def Gas_internal(jum, brp_val):
    nama_akun_awal_batch, saldo_awal_batch = mxx_fetch_info_internal()
    if nama_akun_awal_batch is None:
        flash("Gagal mendapatkan info akun sebelum memulai transaksi.", "danger")
        tampilkan_detail_transaksi_internal("Gagal Deteksi", brp_val * jum if isinstance(brp_val, (int, float)) else brp_val, None, None, False,
                                   jenis_transaksi_override="Transaksi Gagal Total")
        return

    if jum == 1:
        flash("Memproses transaksi tunggal...", "info")
        berhasil_tunggal = ProssesUangInternal(brp_val)
        nama_akun_setelah, saldo_setelah = mxx_fetch_info_internal()

        tampilkan_detail_transaksi_internal(
            nama_akun_setelah if nama_akun_setelah else nama_akun_awal_batch,
            brp_val,
            saldo_awal_batch,
            saldo_setelah if saldo_setelah is not None else (saldo_awal_batch + brp_val if berhasil_tunggal and isinstance(brp_val, (int,float)) else saldo_awal_batch),
            berhasil_tunggal
        )
        return

    total_nominal_berhasil = 0
    jumlah_berhasil = 0
    jumlah_gagal = 0

    for i in range(jum):
        flash(f"Memproses {i+1}-{jum}...", "info")
        if ProssesUangInternal(brp_val):
            jumlah_berhasil += 1
            if isinstance(brp_val, (int, float)):
                total_nominal_berhasil += brp_val
        else:
            jumlah_gagal += 1
            flash(f"Sub-proses ke-{i+1} tidak berhasil.", "warning")

    nama_akun_setelah_batch, saldo_setelah_batch = mxx_fetch_info_internal()

    status_keseluruhan_batch = False
    jenis_transaksi_batch_str = "Transaksi Batch"
    if isinstance(brp_val, (int, float)) and brp_val > 0:
        jenis_transaksi_batch_str = "Top Up Batch"
    elif isinstance(brp_val, (int, float)) and brp_val < 0:
        jenis_transaksi_batch_str = "Kuras Saldo Batch"

    if jumlah_berhasil == jum:
        status_keseluruhan_batch = True
        jenis_transaksi_batch_str += f" (Semua Berhasil: {jumlah_berhasil}/{jum})"
    elif jumlah_berhasil > 0:
        status_keseluruhan_batch = True
        jenis_transaksi_batch_str += f" (Sebagian Berhasil: {jumlah_berhasil}/{jum} sukses)"
    else:
        status_keseluruhan_batch = False
        jenis_transaksi_batch_str += " (Gagal Total)"

    tampilkan_detail_transaksi_internal(
        nama_akun_setelah_batch if nama_akun_setelah_batch else nama_akun_awal_batch,
        total_nominal_berhasil,
        saldo_awal_batch,
        saldo_setelah_batch if saldo_setelah_batch is not None else (saldo_awal_batch + total_nominal_berhasil if isinstance(total_nominal_berhasil, (int,float)) else saldo_awal_batch),
        status_keseluruhan_batch,
        jenis_transaksi_override=jenis_transaksi_batch_str
    )

def kuras_semua_uang_internal():
    headers = session.get('auth_headers')
    if not headers:
        flash("Sesi tidak valid untuk kuras semua uang.", "danger")
        return tampilkan_detail_transaksi_internal("Gagal Deteksi", None, None, None, False, jenis_transaksi_override="Kuras Semua Uang")

    nama_akun_awal, saldo_awal = mxx_fetch_info_internal()

    if nama_akun_awal is None:
        flash("Gagal mendapatkan informasi saldo akun sebelum menguras.", "danger")
        return tampilkan_detail_transaksi_internal("Gagal Deteksi", None, None, None, False, jenis_transaksi_override="Kuras Semua Uang")

    if saldo_awal == 0:
        flash("Uang sudah habis (0 RP). Tidak ada yang perlu dikuras.", "info")
        return tampilkan_detail_transaksi_internal(nama_akun_awal, 0, saldo_awal, saldo_awal, True, jenis_transaksi_override="Kuras Semua Uang (Saldo Sudah 0)")

    data_kuras = json.dumps({
        "FunctionName": "AddRp",
        "FunctionParameter": {"addValue": -saldo_awal},
        "RevisionSelection": "Live",
        "GeneratePlayStreamEvent": False
    })
    try:
        response_kuras = req.post("https://4ae9.playfabapi.com/Client/ExecuteCloudScript", headers=headers, data=data_kuras)
        response_kuras.raise_for_status()
        result_kuras = response_kuras.json()

        nama_akun_setelah, saldo_setelah = mxx_fetch_info_internal()

        if 'Error' not in result_kuras:
            flash(f"Semua uang ({saldo_awal:,} RP) berhasil dikuras!", "success")
            return tampilkan_detail_transaksi_internal(nama_akun_setelah if nama_akun_setelah else nama_akun_awal, -saldo_awal, saldo_awal, saldo_setelah if saldo_setelah is not None else 0, True, jenis_transaksi_override="Kuras Semua Uang")
        else:
            error_msg = result_kuras.get('Error', {}).get('Message', 'Error tidak diketahui')
            flash(f"Gagal menguras uang: {error_msg}", "danger")
            return tampilkan_detail_transaksi_internal(nama_akun_awal, -saldo_awal, saldo_awal, saldo_awal, False, jenis_transaksi_override="Kuras Semua Uang")
    except req.exceptions.HTTPError as http_err:
        flash(f"HTTP error saat menguras uang: {http_err}", "danger")
        return tampilkan_detail_transaksi_internal(nama_akun_awal, -saldo_awal, saldo_awal, saldo_awal, False, jenis_transaksi_override="Kuras Semua Uang")
    except Exception as e:
        flash(f"Terjadi kesalahan saat menguras uang: {e}", "danger")
        return tampilkan_detail_transaksi_internal(nama_akun_awal, -saldo_awal, saldo_awal, saldo_awal, False, jenis_transaksi_override="Kuras Semua Uang")

def HapusAkun_internal():
    headers = session.get('auth_headers')
    nama_akun_sebelum_fetch, _ = mxx_fetch_info_internal()

    berhasil = False
    data = json.dumps({
        "FunctionName": "DeleteUsers",
        "FunctionParameter": {},
        "RevisionSelection": "Live",
        "GeneratePlayStreamEvent": False
    })
    try:
        response = req.post("https://4ae9.playfabapi.com/Client/ExecuteCloudScript", headers=headers, data=data)
        response.raise_for_status()
        result = response.json()
        if 'Error' not in result:
            flash("AKUN BERHASIL DIHAPUS (jika CloudScript berhasil)!!", "success")
            berhasil = True
        else:
            error_msg = result.get('Error', {}).get('Message', 'Gagal menghapus akun')
            flash(f"Gagal Menghapus Akun: {error_msg}", "danger")
    except req.exceptions.HTTPError as http_err:
        flash(f"HTTP error saat menghapus akun: {http_err}", "danger")
    except Exception as e:
        flash(f"Terjadi kesalahan saat menghapus akun: {e}", "danger")

    nama_display_final = nama_akun_sebelum_fetch if nama_akun_sebelum_fetch else "N/A"
    if berhasil :
        nama_display_final = f"{nama_akun_sebelum_fetch if nama_akun_sebelum_fetch else 'Akun'} (Telah Dihapus)"

    return tampilkan_detail_transaksi_internal(nama_display_final, None, None, None, berhasil, jenis_transaksi_override="Hapus Akun")

def ganti_nama_akun_internal(nama_baru):
    headers = session.get('auth_headers')
    nama_akun_sebelum_fetch, _ = mxx_fetch_info_internal()
    nama_untuk_prompt_sebelum = nama_akun_sebelum_fetch if nama_akun_sebelum_fetch else "[Nama Saat Ini Tidak Terdeteksi]"

    if not nama_baru:
        flash("Nama akun tidak boleh kosong.", "danger")
        return tampilkan_detail_transaksi_internal(
            nama_untuk_prompt_sebelum,
            None, None, None, False,
            jenis_transaksi_override="Ganti Nama Akun",
            nama_sebelum_ganti=nama_untuk_prompt_sebelum,
            nama_sesudah_ganti=nama_untuk_prompt_sebelum
        )

    berhasil = False
    nama_aktual_setelah_operasi = nama_untuk_prompt_sebelum

    flash(f"Mengganti nama akun menjadi '{nama_baru}'...", "info")
    payload = json.dumps({"DisplayName": nama_baru})
    try:
        response = req.post(
            "https://4ae9.playfabapi.com/Client/UpdateUserTitleDisplayName",
            headers=headers,
            data=payload
        )
        response.raise_for_status()
        if response.status_code == 200:
            flash(f"Nama akun berhasil diubah menjadi '{nama_baru}'.", "success")
            berhasil = True
            nama_aktual_setelah_operasi = nama_baru
        else:
            error_data = response.json() if response.content else {}
            error_message = error_data.get('errorMessage', f"Gagal mengganti nama. Status: {response.status_code}")
            flash(f"Gagal mengganti nama akun: {error_message}", "danger")
    except req.exceptions.HTTPError as http_err:
        error_body = ""
        try:
            error_body = http_err.response.json()
            error_message = error_body.get('errorMessage', str(http_err))
            flash(f"Gagal mengganti nama akun (HTTP Error): {error_message}", "danger")
        except json.JSONDecodeError:
            flash(f"Gagal mengganti nama akun (HTTP Error): {http_err}", "danger")
    except req.exceptions.RequestException as e:
        flash(f"Koneksi gagal saat mengganti nama akun: {e}", "danger")
    except Exception as e:
        flash(f"Terjadi kesalahan tidak terduga saat mengganti nama: {e}", "danger")

    nama_akun_display_terkini, _ = mxx_fetch_info_internal()

    return tampilkan_detail_transaksi_internal(
        nama_akun_display_terkini if nama_akun_display_terkini else (nama_baru if berhasil else nama_untuk_prompt_sebelum),
        None, None, None, berhasil,
        jenis_transaksi_override="Ganti Nama Akun",
        nama_sebelum_ganti=nama_untuk_prompt_sebelum,
        nama_sesudah_ganti=nama_aktual_setelah_operasi if berhasil else nama_untuk_prompt_sebelum
    )

def format_expiry_for_display(expiry_info):
    try:
        if "(" in expiry_info and expiry_info.endswith(")"):
            parts = expiry_info.rsplit("(", 1)
            date_part = parts[0].strip()
            days_part = "(" + parts[1]
            return date_part, days_part
        else:
            return expiry_info, None
    except Exception:
        return expiry_info, None

# --- Dekorator untuk memerlukan login ---
def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if 'auth_headers' not in session:
            flash("Anda harus login terlebih dahulu.", "warning")
            return redirect(url_for('index'))
        return view(**kwargs)
    return wrapped_view

# --- Rute Flask ---

@app.route('/')
def index():
    # Pastikan DEVICE_ID_INFO selalu ada di sesi
    if 'DEVICE_ID_INFO' not in session:
        session['DEVICE_ID_INFO'] = dev_id()
    
    show_register_prompt = request.args.get('show_register_prompt', 'false').lower() == 'true'
    unregistered_id = session.get('unregistered_id') # Ambil dari sesi

    return render_template('index.html', 
                           device_id=session['DEVICE_ID_INFO'], 
                           show_register_prompt=show_register_prompt,
                           unregistered_id=unregistered_id)

@app.route('/process_login', methods=['POST'])
def process_login():
    auth_input_val = request.form['auth_input'].strip()
    user_name_for_license = request.form.get('user_name_for_license', '').strip() 

    if not auth_input_val:
        flash("Anda harus memasukkan Device ID atau X-Authorization.", "danger")
        return redirect(url_for('index'))
    
    # Simpan auth_input di sesi
    session['auth_input'] = auth_input_val

    # Lakukan pemeriksaan lisensi
    license_status = license_check_internal()

    if license_status == 'expired':
        return redirect(url_for('license_expired_page'))
    elif license_status == 'unregistered':
        if user_name_for_license:
            session['USER_LICENSE_NAME'] = user_name_for_license
        return redirect(url_for('index', show_register_prompt=True))
    elif license_status == 'valid':
        # Jika lisensi valid, lanjutkan dengan login game
        if login_internal(auth_input_val):
            flash("Login Berhasil!", "success")
            return redirect(url_for('menu'))
        else:
            # Login game gagal, tetap di halaman index
            flash("Login Gagal. Mohon coba lagi.", "danger")
            return redirect(url_for('index'))
    else:
        # Status tidak terduga, kembali ke index
        flash("Terjadi masalah saat memeriksa lisensi. Silakan coba lagi.", "danger")
        return redirect(url_for('index'))


@app.route('/menu')
@login_required
def menu():
    user_license_name = session.get('USER_LICENSE_NAME', 'N/A')
    user_license_expiry_info = session.get('USER_LICENSE_EXPIRY_INFO', 'N/A')
    device_id_info = session.get('DEVICE_ID_INFO', 'N/A')

    expiry_date_part, expiry_days_part_raw = format_expiry_for_display(user_license_expiry_info)

    # Fetch MXX info for display
    nama_akun, saldo_akun = mxx_fetch_info_internal()
    if nama_akun is None:
        flash("Gagal memuat informasi akun game. Silakan coba lagi.", "danger")
        nama_akun = "Gagal Memuat"
        saldo_akun = 0

    # Dapatkan waktu saat ini dan lewatkan ke template
    current_time = datetime.datetime.now() 

    return render_template('menu.html',
                           user_license_name=user_license_name,
                           expiry_date_part=expiry_date_part,
                           expiry_days_part_raw=expiry_days_part_raw,
                           device_id_info=device_id_info,
                           nama_akun_mxx=nama_akun,
                           saldo_akun_mxx=saldo_akun,
                           now=current_time)
@app.route('/process_action', methods=['POST'])
@login_required
def process_action():
    pilihan = request.form['pilihan'].strip()
    Brp = 0
    jum = 1 # Default jumlah proses adalah 1

    options_map = {
        "1": 50000000, "2": 70000000, "3": 150000000, "4": 250000000,
        "5": 350000000, "6": 500000000, "7": 600000000, "8": 700000000,
        "9": 800000000, "10": 900000000, "11": 1000000000, "12": 1300000000,
        "13": 1600000000, "14": 1800000000, "15": 2147483647,
        "17": -5000000, "18": -10000000, "19": -50000000, "20": -100000000,
        "21": -1000000000, "22": -1500000000, "23": -2147483647
    }

    # Opsi-opsi yang memiliki input jumlah terpisah di menu.html
    # Ini akan secara eksplisit diambil dari form
    options_with_explicit_jumlah_input = [str(i) for i in range(1, 16)] + [str(i) for i in range(17, 24)]

    if pilihan == "0":
        flash("Terima kasih telah menggunakan script ini. Sampai jumpa!", "info")
        session.clear() # Clear session on exit
        return redirect(url_for('index'))

    elif pilihan in options_map:
        Brp = options_map[pilihan]
        
        # Jika pilihan ini memiliki input jumlah eksplisit di form
        if pilihan in options_with_explicit_jumlah_input:
            try:
                # Ambil jumlah dari request.form atau default ke 1 jika kosong/tidak ada
                jum_input = request.form.get(f'jumlah_{pilihan}', '1').strip()
                if not jum_input.isdigit():
                    raise ValueError("Jumlah proses harus berupa angka.")
                jum = int(jum_input)
                if jum <= 0:
                    raise ValueError("Jumlah proses harus lebih besar dari 0.")
            except ValueError as e:
                flash(f"Kesalahan input jumlah: {e}", "danger")
                return redirect(url_for('menu'))
        else:
            # Untuk opsi seperti 11-15, 21-23 yang nominalnya sangat besar, jumlah defaultnya 1
            # dan tidak ada input jumlah terpisah di HTML (sesuai no_input_jumlah_values di kode asli)
            jum = 1 # Ini sudah diatur di awal fungsi, jadi tidak perlu diulang

        Gas_internal(jum, Brp)

    elif pilihan == "16": # CUSTOM TOPUP
        try:
            nominal_str = request.form.get('nominal_16', '').strip()
            jumlah_str = request.form.get('jumlah_16', '').strip()

            if not nominal_str.isdigit() or not jumlah_str.isdigit():
                raise ValueError("Nominal dan jumlah harus berupa angka.")
            
            Brp = int(nominal_str)
            jum = int(jumlah_str)
            
            if Brp <= 0:
                raise ValueError("Nominal top up harus lebih besar dari 0.")
            if jum <= 0:
                raise ValueError("Jumlah proses harus lebih besar dari 0.")
        except ValueError as e:
            flash(f"Kesalahan input custom top up: {e}", "danger")
            return redirect(url_for('menu'))
        Gas_internal(jum, Brp)

    elif pilihan == "24": # CUSTOM KURAS
        try:
            nominal_str = request.form.get('nominal_24', '').strip()
            jumlah_str = request.form.get('jumlah_24', '').strip()

            if not nominal_str.isdigit() or not jumlah_str.isdigit():
                raise ValueError("Nominal dan jumlah harus berupa angka.")

            Brp = -int(nominal_str) # Nominal kuras adalah negatif
            jum = int(jumlah_str)

            if abs(Brp) <= 0:
                raise ValueError("Nominal kuras harus lebih besar dari 0.")
            if jum <= 0:
                raise ValueError("Jumlah proses harus lebih besar dari 0.")
        except ValueError as e:
            flash(f"Kesalahan input custom kuras: {e}", "danger")
            return redirect(url_for('menu'))
        Gas_internal(jum, Brp)

    elif pilihan == "25": # Kuras Semua
        kuras_semua_uang_internal()
    elif pilihan == "26": # Hapus Akun
        return HapusAkun_internal() 
    elif pilihan == "27": # Ganti Nama Akun
        nama_baru = request.form.get('nama_baru', '').strip()
        if not nama_baru:
            flash("Nama baru tidak boleh kosong.", "danger")
            return redirect(url_for('menu'))
        return ganti_nama_akun_internal(nama_baru) 
    else:
        flash("Pilihan tidak valid! Silakan coba lagi.", "danger")
        return redirect(url_for('menu'))
    
    # Setelah processing, redirect to show transaction details
    return redirect(url_for('display_transaction_details'))

@app.route('/display_transaction_details')
@login_required
def display_transaction_details():
    details = session.pop('last_transaction_details', None)
    if not details:
        flash("Tidak ada detail transaksi untuk ditampilkan.", "warning")
        return redirect(url_for('menu'))
    return render_template('transaction_details.html', details=details)

@app.route('/license_expired')
def license_expired_page():
    expiry_info = session.get('expiry_info')
    if not expiry_info:
        flash("Informasi lisensi kedaluwarsa tidak ditemukan.", "danger")
        return redirect(url_for('index'))
    return render_template('license_expired.html', expiry_info=expiry_info)

@app.route('/process_renewal', methods=['POST'])
def process_renewal():
    pilihan = request.form['pilihan_paket'].strip()
    build_id_hash = session.get('expiry_info', {}).get('build_id_hash')
    user_name = session.get('expiry_info', {}).get('user_name')

    if not build_id_hash:
        flash("ID Lisensi tidak ditemukan. Silakan coba lagi.", "danger")
        return redirect(url_for('index'))

    qris_links = {
        "1": "https://www.mediafire.com/view/ninqzls4vilj3w0/10K.png/file",
        "2": "https://www.mediafire.com/view/adf4esz29wpwjd7/20k.png/file",
        "3": "https://www.mediafire.com/view/5usi40to2yt1mbw/30k.png/file",
        "4": "https://www.mediafire.com/view/t5v1ysc5rxbbx3h/40k.png/file",
        "5": "https://www.mediafire.com/view/lwibozqtdvus0af/50k.png/file",
        "6": "https://www.mediafire.com/view/i6x35d6wjtrz1oe/70k.png/file"
    }
    paket_info = {
        "1": "1 MINGGU (10K)", "2": "2 MINGGU (20K)", "3": "1 BULAN (30K)",
        "4": "2 BULAN (40K)", "5": "3 BULAN (50K)", "6": "PERMANEN (70K)"
    }

    selected_link = qris_links.get(pilihan)
    selected_paket = paket_info.get(pilihan)

    if not selected_link:
        flash("Pilihan paket tidak valid. Silakan coba lagi.", "danger")
        return redirect(url_for('license_expired_page'))

    flash(f"Anda telah memilih paket perpanjangan: {selected_paket}", "info")
    flash("Anda akan segera diarahkan ke tautan pembayaran (QRIS) dan WhatsApp untuk konfirmasi.", "info")
    
    session['renewal_info'] = {
        'selected_link': selected_link,
        'selected_paket': selected_paket,
        'build_id_hash': build_id_hash,
        'user_name': user_name
    }
    return redirect(url_for('show_qris'))

@app.route('/show_qris')
def show_qris():
    renewal_info = session.pop('renewal_info', None) # Pop to ensure it's used once
    if not renewal_info:
        flash("Informasi pembayaran tidak ditemukan.", "danger")
        return redirect(url_for('license_expired_page'))
    
    selected_link = renewal_info['selected_link']
    selected_paket = renewal_info['selected_paket']
    build_id_hash = renewal_info['build_id_hash']
    user_name = renewal_info['user_name']

    wa_message_content = f"Saya ingin konfirmasi perpanjangan lisensi dengan detail:\nPaket: {selected_paket}"
    wa_link = send_wa(build_id_hash, user_name, wa_message_content)

    return render_template('show_qris.html', 
                           qris_link=selected_link, 
                           paket_nama=selected_paket,
                           wa_link=wa_link)

@app.route('/contact_admin_from_unregistered', methods=['POST'])
def contact_admin_from_unregistered():
    build_id_hash = session.get('unregistered_id')
    nama_pengguna_lisensi = request.form['user_name_for_license'].strip()

    if not build_id_hash:
        flash("UserID tidak ditemukan. Silakan kembali ke halaman utama.", "danger")
        return redirect(url_for('index'))
    
    if not nama_pengguna_lisensi:
        flash("Nama Anda tidak boleh kosong.", "danger")
        return redirect(url_for('index', show_register_prompt=True))
    
    session['USER_LICENSE_NAME'] = nama_pengguna_lisensi # Simpan nama
    wa_link = send_wa(build_id_hash, nama_pengguna_lisensi, "Saya ingin membeli lisensi baru.")
    flash("Anda akan dialihkan ke WhatsApp untuk menghubungi admin.", "info")
    return render_template('contact_admin.html', wa_link=wa_link)

@app.route('/logout')
def logout():
    session.clear()
    flash("Anda telah berhasil logout.", "success")
    return redirect(url_for('index'))

#if __name__ == '__main__':
    # Untuk lingkungan produksi, gunakan Gunicorn atau sejenisnya
    # contoh: gunicorn -w 4 -b 0.0.0.0:5000 app:app
  #  app.run(debug=True, host='0.0.0.0', port=5000)