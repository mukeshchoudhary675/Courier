import streamlit as st
import pytesseract
import pandas as pd
import re
from io import BytesIO
import fitz  # PyMuPDF
from PIL import Image

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
    addr_match = re.search(r"Shipping Address:\s*(.*?)\s*(Support Details|Email ID|$)", text, re.S)
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


def pdf_page_to_image(file_bytes, page_number):
    """Convert a PDF page to a PIL image using PyMuPDF"""
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    page = doc[page_number]
    pix = page.get_pixmap()
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return img


def extract_from_pdf(uploaded_file):
    """Extract using OCR (since file is scanned image-based)"""
    data = []
    file_bytes = uploaded_file.read()

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    for i in range(len(doc)):
        img = pdf_page_to_image(file_bytes, i)
        text = pytesseract.image_to_string(img)
        courier, consignment_no, address = parse_text(text)
        data.append([courier, consignment_no, address])

    return data

# ---------- Streamlit UI ----------

st.title("📦 Courier Consignment Extractor (OCR Mode for Scanned PDFs)")
uploaded_file = st.file_uploader("Upload your courier PDF (scanned or mobile photo)", type="pdf")

if uploaded_file:
    st.info("Processing your scanned PDF using OCR... ⏳")

    extracted_data = extract_from_pdf(uploaded_file)

    df = pd.DataFrame(extracted_data, columns=["Courier", "Consignment No", "Address"])
    st.success(f"✅ Extracted {len(df)} records!")
    st.dataframe(df)

    # Download button
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Download CSV", csv, "consignments.csv", "text/csv")
