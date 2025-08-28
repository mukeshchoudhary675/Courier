import streamlit as st
import pdfplumber
import pytesseract
from pdf2image import convert_from_bytes
import pandas as pd
import re
from io import BytesIO

# ---------- Parsing Helpers ----------

def parse_text(text):
    """Extract courier name, consignment no and address from raw text"""
    consignment_no, address, courier = "", "", ""

    # 1. Consignment No (10-13 digit numbers are typical)
    consign_match = re.search(r"\b\d{10,13}\b", text)
    if consign_match:
        consignment_no = consign_match.group(0)

    # 2. Courier Name (basic keyword detection)
    if re.search(r"Delhivery", text, re.I):
        courier = "Delhivery"
    elif re.search(r"Nandan", text, re.I):
        courier = "Nandan"
    elif re.search(r"Trackon", text, re.I):
        courier = "Trackon"
    elif re.search(r"DTDC", text, re.I):
        courier = "DTDC"
    elif re.search(r"Bluedart|Blue Dart", text, re.I):
        courier = "Bluedart"
    else:
        courier = "Unknown"

    # 3. Try Delhivery style (Shipping Address block)
    addr_match = re.search(r"Shipping Address:\s*(.*?)\s*Support Details", text, re.S)
    if addr_match:
        address = addr_match.group(1).strip().replace("\n", " ")

    # 4. If not found, try City + Pincode
    if not address:
        city_pin_match = re.search(r"([A-Za-z]+[A-Za-z ]+)\s*[- ]?\s*(\d{6})", text)
        if city_pin_match:
            address = city_pin_match.group(0)

    # 5. If still not found, fallback to just pincode
    if not address:
        pin_match = re.search(r"\b\d{6}\b", text)
        if pin_match:
            address = pin_match.group(0)

    return courier, consignment_no, address


def extract_from_pdf(uploaded_file):
    """Handle mixed PDF (text + scanned)"""
    data = []
    file_bytes = uploaded_file.read()  # ✅ read once
    with pdfplumber.open(BytesIO(file_bytes)) as pdf:  # ✅ wrap with BytesIO
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text:  # text-based slip
                courier, consignment_no, address = parse_text(text)
            else:     # scanned slip
                images = convert_from_bytes(
                    file_bytes,
                    first_page=i+1,
                    last_page=i+1
                )
                text = pytesseract.image_to_string(images[0])
                courier, consignment_no, address = parse_text(text)

            data.append([courier, consignment_no, address])
    return data

# ---------- Streamlit UI ----------

st.title("📦 Universal Courier Consignment Extractor")
uploaded_file = st.file_uploader("Upload your courier PDF", type="pdf")

if uploaded_file:
    st.info("Processing your PDF... This may take a while ⏳")

    extracted_data = extract_from_pdf(uploaded_file)

    df = pd.DataFrame(extracted_data, columns=["Courier", "Consignment No", "Address"])
    st.success(f"✅ Extracted {len(df)} records!")
    st.dataframe(df)

    # Download button
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Download CSV", csv, "consignments.csv", "text/csv")
