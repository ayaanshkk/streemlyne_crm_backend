"""
pdf_helpers.py  - Warm Parchment edition
Drop-in replacement for the existing pdf_helpers.py
"""

from fpdf import FPDF

# ── Palette ────────────────────────────────────────────────────────────────
BROWN_DARK   = (124, 61, 18)    # #7c3d12  affiliation band / headers / grand total
CREAM        = (254, 243, 199)  # #fef3c7  text on dark brown
BROWN_MID    = (168, 113, 74)   # #a8714a  muted labels
BROWN_TEXT   = (28, 16, 8)      # #1c1008  body text
BROWN_BORDER = (232, 213, 192)  # #e8d5c0  hairline dividers
PARCHMENT_1  = (253, 250, 245)  # #fffaf5  item row odd
PARCHMENT_2  = (253, 246, 238)  # #fdf6ee  item row even
BROWN_ACCENT = (90, 58, 26)     # #5a3a1a  secondary text


class PDF(FPDF):
    """Warm Parchment PDF — centered FAI letterhead + brown affiliation band."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.doc_title = ''
        self.contact_line = 'Property No. 630, Survey Number 37/1 to 4/1/1, Pisoli, Pune-411060  \xb7  9833133772  \xb7  8983340496  \xb7  8983340497  \xb7  info@forklift.academy'

    def normalize_text(self, text: str) -> str:
        """Override to sanitize ALL text before it hits the latin-1 encoder."""
        if not text:
            return super().normalize_text('')
        _replacements = {
            '\u20b9': 'Rs.',  # ₹
            '\u2014': '--',   # — em dash
            '\u2013': '-',    # – en dash
            '\u2012': '-',    # figure dash
            '\u2010': '-',    # hyphen
            '\u2019': "'",    # right single quote '
            '\u2018': "'",    # left single quote '
            '\u201c': '"',    # left double quote "
            '\u201d': '"',    # right double quote "
            '\u2026': '...',  # ellipsis …
            '\u00b7': '.',    # middle dot ·
            '\u2022': '-',    # bullet •
            '\u2605': '*',    # star ★
            '\u00a0': ' ',    # non-breaking space
            '\u00ae': '(R)',  # ®
            '\u00a9': '(C)',  # ©
            '\u2122': '(TM)', # ™
        }
        for char, replacement in _replacements.items():
            text = text.replace(char, replacement)
        # Final fallback: replace anything still outside latin-1 with '?'
        text = text.encode('latin-1', errors='replace').decode('latin-1')
        return super().normalize_text(text)

    def header(self):
        import os
        logo_path = os.path.join(os.path.dirname(__file__), '..', 'static', 'images', 'fai-logo.png')

        page_w = self.w
        margin  = self.l_margin

        # ── Logo (centered, no circle — just the image) ──────────────────
        logo_w = 20
        logo_x = (page_w - logo_w) / 2
        try:
            self.image(logo_path, x=logo_x, y=8, w=logo_w)
        except Exception:
            pass
        self.set_y(30)

        # ── Organisation name ────────────────────────────────────────────
        self.set_font('Arial', 'B', 13)
        self.set_text_color(*BROWN_TEXT)
        self.cell(0, 6, 'FORKLIFT ACADEMY OF INDIA', 0, 1, 'C')

        # Tagline
        self.set_font('Arial', 'I', 8)
        self.set_text_color(*BROWN_MID)
        self.cell(0, 5, 'A Journey Towards Zero MHE Accidents', 0, 1, 'C')

        # Address / contact
        self.set_font('Arial', '', 7.5)
        self.set_text_color(*BROWN_MID)
        self.cell(0, 4, self.contact_line, 0, 1, 'C')

        self.ln(3)

        # ── Affiliation band ─────────────────────────────────────────────
        band_x = margin
        band_w = page_w - margin * 2
        band_h = 7
        self.set_fill_color(*BROWN_DARK)
        self.rect(band_x, self.get_y(), band_w, band_h, 'F')
        self.set_font('Arial', 'B', 7)
        self.set_text_color(*CREAM)
        self.cell(0, band_h,
                  '*  Affiliated to Government of India\'s Automotive Skills Development Council  *',
                  0, 1, 'C')

        self.set_text_color(*BROWN_TEXT)
        self.ln(4)

    def footer(self):
        self.set_y(-13)
        self.set_font('Arial', 'I', 7)
        self.set_text_color(*BROWN_MID)
        self.cell(0, 8, f'Page {self.page_no()}/{{nb}}', 0, 0, 'C')
        self.set_text_color(*BROWN_TEXT)


# ── Shared drawing helpers ──────────────────────────────────────────────────

def draw_section_label(pdf, label: str):
    """Gold uppercase section label + brown hairline rule."""
    y = pdf.get_y()
    pdf.set_font('Arial', 'B', 7)
    pdf.set_text_color(*BROWN_DARK)
    lw = pdf.get_string_width(label) + 4
    pdf.cell(lw, 5, label, 0, 0, 'L')
    # hairline rule to right margin
    rule_x = pdf.get_x() + 2
    rule_y = y + 2.5
    rule_end = pdf.w - pdf.r_margin
    pdf.set_draw_color(*BROWN_BORDER)
    pdf.line(rule_x, rule_y, rule_end, rule_y)
    pdf.set_draw_color(*BROWN_TEXT)
    pdf.ln(6)
    pdf.set_text_color(*BROWN_TEXT)


def kv_row(pdf, label: str, value: str, lw=45, full_w=None):
    """Hairline-separated key/value row."""
    full_w = full_w or (pdf.w - pdf.l_margin - pdf.r_margin)
    pdf.set_font('Arial', '', 8)
    pdf.set_text_color(*BROWN_MID)
    pdf.cell(lw, 5.5, label, 0, 0, 'L')
    pdf.set_text_color(*BROWN_TEXT)
    pdf.set_font('Arial', 'B', 8)
    pdf.cell(full_w - lw, 5.5, str(value or '-'), 0, 0, 'R')
    pdf.ln(5.5)
    # hairline
    pdf.set_draw_color(*BROWN_BORDER)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + full_w, pdf.get_y())
    pdf.set_draw_color(*BROWN_TEXT)
    pdf.set_text_color(*BROWN_TEXT)
    pdf.set_font('Arial', '', 8)
