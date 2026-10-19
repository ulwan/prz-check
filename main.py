import json
import os
import time
from datetime import datetime

import gspread
import requests

# --- KONFIGURASI ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TIINGO_API_KEY = os.environ.get("TIINGO_API_KEY")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME")


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        req = requests.post(url, json=payload)
    except Exception as e:
        print(f"Gagal mengirim pesan Telegram: {e}")


def check_prz_zones():
    # 1. Koneksi ke Google Sheets
    # gc = gspread.service_account(filename="credentials.json")
    creds_json_str = os.environ.get("GOOGLE_CREDENTIALS")
    if not creds_json_str:
        raise ValueError("GOOGLE_CREDENTIALS environment variable tidak ditemukan!")

    creds_dict = json.loads(creds_json_str)
    gc = gspread.service_account_from_dict(creds_dict)
    sheet = gc.open(SPREADSHEET_NAME).worksheet("Watchlist")
    data = sheet.get_all_records()  # Mengambil semua baris sebagai dictionary
    print(data)

    if not data:
        print("Watchlist kosong.")
        return

    # 2. Ambil list unique ticker dari Google Sheets
    tickers = list(set([row["Ticker"].strip().lower() for row in data if row["Ticker"]]))
    if not tickers:
        return

    # 3. Request harga terkini dari Tiingo (Multi-ticker sekaligus)
    # Format tiingo fx top endpoint: ?tickers=eurusd,gbpusd&token=...
    tickers_str = ",".join(tickers)
    url = f"https://api.tiingo.com/tiingo/fx/top?tickers={tickers_str}&token={TIINGO_API_KEY}"

    try:
        response = requests.get(url)
        prices_data = response.json()
    except Exception as e:
        print(f"Gagal mengambil data dari Tiingo: {e}")
        return
    print(prices_data)
    # Petakan harga mid/bid/ask ke dalam dictionary
    # Tiingo top endpoint mengembalikan list of dict
    price_map = {}
    for item in prices_data:
        ticker = item["index"].lower()
        # Menggunakan mid price (rata-rata bid dan ask) atau harga last
        bid = item.get("bidPrice", 0)
        ask = item.get("askPrice", 0)
        mid_price = (bid + ask) / 2 if (bid and ask) else item.get("lastPrice", 0)
        price_map[ticker] = mid_price

    # 4. Evaluasi setiap baris PRZ di Google Sheets
    for idx, row in enumerate(data, start=2):  # Mulai dari baris 2 (header di baris 1)
        ticker = str(row["Ticker"]).strip().lower()
        zone_type = str(row["type"]).strip().upper()  # BULLISH / BEARISH
        prz_low = float(row["prz_low"])
        prz_high = float(row["prz_high"])
        status = str(row["status"]).strip().upper()
        probability = str(row["probability"]).strip().upper()
        tf = str(row["timeframe"]).strip().upper()

        current_price = price_map.get(ticker)
        print(f"Checking {ticker.upper()} ...")
        if not current_price:
            continue

        # Update kolom Last_Price di sheet (Kolom F -> index 6)
        sheet.update_cell(idx, 6, current_price)

        # Logika Pengecekan Zona PRZ
        is_in_zone = prz_low <= current_price <= prz_high

        if is_in_zone and status != "TRIGGERED":
            # Harga Masuk Zona! Kirim Alert
            msg = (
                f"🚨 **PRZ ALERT: {ticker.upper()}** 🚨\n\n"
                f"📊 Tipe Zona: *{zone_type}*\n"
                f"📍 Rentang PRZ: `{prz_low} - {prz_high}`\n"
                f"⚡ Harga Saat Ini: `{current_price}`\n"
                f"🎯 Probability : `{probability}`\n"
                f"⏰ TF: `{tf}`\n"
                f"⏰ Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            print("sent telegeram")
            send_telegram_message(msg)

            # Ubah status jadi TRIGGERED agar tidak spam (Kolom E -> index 5)
            sheet.update_cell(idx, 5, "TRIGGERED")
            sheet.update_cell(idx, 7, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        elif not is_in_zone and status == "TRIGGERED":
            # Reset status kembali ke ACTIVE jika harga sudah keluar zona (opsional)
            sheet.update_cell(idx, 5, "ACTIVE")

    print(f"Check selesai dijalankan pada {datetime.now()}")


if __name__ == "__main__":
    check_prz_zones()
