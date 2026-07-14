import fitz


def extract_pdf(pdf_bytes):

    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")

    text = ""

    for page in pdf:
        text += page.get_text()

    pages = pdf.page_count

    pdf.close()

    return text, pages