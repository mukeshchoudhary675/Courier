# Streamlit app: Trackon courier tracker (secure, secrets-based)
# ------------------------------------------------------------
# This version reads your Google service account from Streamlit Secrets,
# so you never upload service_account.json to GitHub.

import streamlit as st
import time
import re
import json
from datetime import datetime
from typing import List, Tuple

import pandas as pd
import json, streamlit as st
from google.oauth2.service_account import Credentials
import gspread
from google.oauth2.service_account import Credentials

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.chrome.options import Options as ChromeOptions
from webdriver_manager.chrome import ChromeDriverManager

# -----------------------
# UI
# -----------------------
st.set_page_config(page_title="Trackon Courier Tracker", layout="wide")
st.title("📦 Trackon Courier Tracking — Secure Updater")

st.markdown(
    "This app reads consignment numbers from **column M** of your Google Sheet,\n"
    "scrapes Trackon for live status, and writes results back to columns **N:Q**\n"
    "(Status, Last Event, Location, Last Checked). Uses **Streamlit Secrets** for security."
)

sheet_id = st.text_input("Google Sheet ID (from Sheet URL)")
worksheet_name = st.text_input("Worksheet/Tab Name", value="Sheet1")
max_rows = st.number_input("Max rows to process this run", min_value=1, max_value=2000, value=200)
run_btn = st.button("🚀 Run Tracking Update Securely")

# -----------------------
# Helpers
# -----------------------

def col_letter_to_index(letter: str) -> int:
    letter = letter.upper()
    result = 0
    for ch in letter:
        result = result * 26 + (ord(ch) - ord('A') + 1)
    return result


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# -----------------------
# Google Sheets (via Secrets)
# -----------------------

def get_gspread_client_from_secrets():
    """Expect Streamlit Secrets key: service_account_json (multiline string)."""
    try:
        # Recommended: paste your entire JSON into Streamlit Secrets as:
        # service_account_json = """
        # { ... full JSON ... }
        # """
        raw = st.secrets["service_account_json"]
        if isinstance(raw, str):
            creds_dict = json.loads(raw)
        else:
            # If user stored it as a TOML table instead of a triple-quoted string
            creds_dict = dict(raw)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(credentials)
    except Exception as e:
        st.error("Failed to load service account from Streamlit Secrets. Make sure you added `service_account_json`.")
        st.stop()


def open_sheet(client: gspread.Client, sid: str, tab: str) -> gspread.Worksheet:
    sh = client.open_by_key(sid)
    return sh.worksheet(tab)


# -----------------------
# Selenium (headless Chrome)
# -----------------------

def make_driver():
    opts = ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,2000")
    service = ChromeService(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(60)
    return driver


STATUS_KEYWORDS = [
    "Delivered", "Out for Delivery", "In Transit", "Booked", "Manifested",
    "Undelivered", "RTO", "Returned", "Hold", "Pending", "Not Picked",
]


def extract_status_location(page_text: str):
    status = "UNKNOWN"
    for kw in STATUS_KEYWORDS:
        if kw.lower() in page_text.lower():
            status = kw
            break
    # Last event: try to capture a key line
    m = re.search(r"(Delivered.*|Out for Delivery.*|In Transit.*|Undelivered.*|Booked.*|Manifested.*)", page_text, re.IGNORECASE)
    last_event = m.group(1).strip()[:250] if m else ""
    # Location heuristics
    location = ""
    m2 = re.search(r"Location\s*[:\-]\s*(.+)", page_text, re.IGNORECASE)
    if m2:
        location = m2.group(1).strip()[:120]
    else:
        m3 = re.search(r"at\s+([A-Za-z][A-Za-z\s,&()-]{2,})", page_text)
        if m3:
            location = m3.group(1).strip()[:120]
    return status, last_event, location


def fetch_single_awb(driver, awb: str):
    url = "https://www.trackon.in/courier-tracking"
    driver.get(url)
    try:
        inp = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='text' or @type='search']"))
        )
        inp.clear()
        inp.send_keys(awb)
        # Track button (button or link)
        try:
            btn = driver.find_element(By.XPATH, "//button[contains(., 'Track')]")
        except Exception:
            btn = driver.find_element(By.XPATH, "//a[contains(., 'Track')]")
        btn.click()
        WebDriverWait(driver, 40).until(
            EC.presence_of_all_elements_located((By.TAG_NAME, "body"))
        )
        body = driver.find_element(By.TAG_NAME, "body").text
        status, last_event, location = extract_status_location(body)
        return status, last_event, location, body
    except Exception as e:
        return "ERROR", str(e)[:250], "", ""


# -----------------------
# Main
# -----------------------
if run_btn:
    if not sheet_id:
        st.warning("Please enter your Google Sheet ID.")
        st.stop()

    gc = get_gspread_client_from_secrets()
    try:
        ws = open_sheet(gc, sheet_id, worksheet_name)
    except Exception as e:
        st.error("Unable to open the Google Sheet. Check Sheet ID and tab name, and ensure you've shared the Sheet with the **service account email** from your JSON (`client_email`).")
        st.stop()

    # Read tracking numbers from column M (skip header if present)
    m_col_idx = col_letter_to_index("M")
    values = ws.col_values(m_col_idx)
    awbs: List[Tuple[int, str]] = []  # (row_index, awb)
    for r_i, val in enumerate(values, start=1):
        v = (val or "").strip()
        if not v:
            continue
        if r_i == 1 and re.search(r"[a-zA-Z]", v):
            # assume header
            continue
        awbs.append((r_i, v))

    if not awbs:
        st.info("No consignment numbers found in column M.")
        st.stop()

    awbs = awbs[:max_rows]
    st.write(f"Found **{len(awbs)}** tracking numbers to process.")

    driver = make_driver()
    progress = st.progress(0)
    results = []

    # target columns N:Q
    cN = col_letter_to_index("N")  # Status
    cO = col_letter_to_index("O")  # Last Event / Detail
    cP = col_letter_to_index("P")  # Location
    cQ = col_letter_to_index("Q")  # Checked at

    for idx, (row_idx, awb) in enumerate(awbs, start=1):
        status, last_event, location, _raw = fetch_single_awb(driver, awb)
        checked = now_str()
        # write back to sheet (individual updates keep things simple)
        try:
            ws.update_cell(row_idx, cN, status)
            ws.update_cell(row_idx, cO, last_event)
            ws.update_cell(row_idx, cP, location)
            ws.update_cell(row_idx, cQ, checked)
        except Exception:
            pass
        results.append({
            "Row": row_idx,
            "AWB": awb,
            "Status": status,
            "Last Event": last_event,
            "Location": location,
            "Checked": checked,
        })
        progress.progress(idx / len(awbs))
        time.sleep(0.8)  # gentle delay

    try:
        driver.quit()
    except Exception:
        pass

    st.success("✅ Update complete. Preview below.")
    st.dataframe(pd.DataFrame(results))

# End of file
