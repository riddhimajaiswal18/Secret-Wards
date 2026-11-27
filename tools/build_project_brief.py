"""Build the two-page competition brief from the measured rescue snapshot."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageBreak, PageTemplate, Paragraph, Spacer, Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "Project-Brief.pdf"
NAVY = colors.HexColor("#123B55")
TEAL = colors.HexColor("#087E8B")
INK = colors.HexColor("#202B33")
MUTED = colors.HexColor("#586B78")
PALE = colors.HexColor("#EDF4F7")
LINE = colors.HexColor("#D5E0E6")


def page(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(NAVY)
    canvas.rect(0, h - 5 * mm, w, 5 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(LINE)
    canvas.line(15 * mm, 13 * mm, w - 15 * mm, 13 * mm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(15 * mm, 8.5 * mm, "SECRET WARDS  |  TRACK 3  |  PRACTICE-SET EVIDENCE")
    canvas.drawRightString(w - 15 * mm, 8.5 * mm, f"{doc.page} / 2")
    canvas.restoreState()


styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="TitleSW", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=21, leading=25, textColor=NAVY, spaceAfter=2 * mm, alignment=TA_LEFT))
styles.add(ParagraphStyle(name="SubSW", parent=styles["Normal"], fontSize=9, leading=12, textColor=MUTED, spaceAfter=4 * mm))
styles.add(ParagraphStyle(name="HeadSW", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=NAVY, spaceBefore=3 * mm, spaceAfter=1.5 * mm, keepWithNext=True))
styles.add(ParagraphStyle(name="BodySW", parent=styles["BodyText"], fontSize=8.6, leading=12, textColor=INK, spaceAfter=1.5 * mm))
styles.add(ParagraphStyle(name="SmallSW", parent=styles["BodyText"], fontSize=7.4, leading=9.5, textColor=MUTED, spaceAfter=1 * mm))
styles.add(ParagraphStyle(name="CellSW", parent=styles["BodyText"], fontSize=7.5, leading=9.5, textColor=INK))
styles.add(ParagraphStyle(name="CellHeadSW", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7.5, leading=9.5, textColor=NAVY))
styles.add(ParagraphStyle(name="MetricSW", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=15, leading=17, textColor=TEAL, alignment=TA_LEFT))


def P(text, style="BodySW"):
    return Paragraph(text, styles[style])


def section(title):
    return P(title, "HeadSW")


def table(rows, widths, header=True):
    data = []
    for ri, row in enumerate(rows):
        sty = "CellHeadSW" if header and ri == 0 else "CellSW"
        data.append([P(str(v), sty) for v in row])
    t = Table(data, colWidths=widths, hAlign="LEFT")
    cmds = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
    ]
    if header:
        cmds.append(("BACKGROUND", (0, 0), (-1, 0), PALE))
    t.setStyle(TableStyle(cmds))
    return t


story = [
    P("Secret Wards", "TitleSW"),
    P("Offline privacy firewall for multilingual Indian healthcare exports  |  Track 3 submission brief  |  riddhimajaiswal18/Secret-Wards", "SubSW"),
    section("1. Problem and approach"),
    P("Hospital exports mix CSV/TSV, nested JSON, FHIR-shaped bundles, XML and clinical notes. English, Devanagari and Hinglish identity clues appear beside diagnoses, medicines and measurements. Secret Wards uses a deterministic Python pipeline to parse supported files into a common, locator-aware representation, detect selected direct identifiers, apply explicit edits, and quarantine inputs that cannot be safely parsed. It is offline, CPU-oriented and uses no LLM or runtime model download."),
    section("2. Architecture"),
    table([
        ["Pipeline stage", "Current role"],
        ["Read-only enumeration", "Hash inputs for accounting; keep source locations and metadata."],
        ["Routing and parsing", "Decode and parse supported structures under bounds; quarantine failures."],
        ["Common IR", "Carry parsed structure, source locators, annotations and pending edits."],
        ["Understand and detect", "Combine labels, structure, section context and text markers; protect clinical spans."],
        ["Transform and serialize", "Apply edits to supported formats; emit sanitized tree, report and record manifest."],
        ["Pseudonyms", "Emit secret-keyed HMAC tokens only where current identifier evidence is available."],
    ], [34 * mm, 146 * mm]),
    Spacer(1, 2 * mm),
    P("Input tree  ->  bounded ingestion  ->  common IR  ->  contextual detection / clinical protection  ->  explicit edits  ->  sanitized/ + report.json + records.jsonl", "SmallSW"),
    section("3. How it works"),
    table([
        ["Part", "Implementation and boundary"],
        ["Ingestion", "CSV/TSV, JSON, XML and text support; FHIR-shaped JSON uses the shared JSON path. Malformed, empty and over-depth examples are quarantined. PDF/image work depends on optional local tools."],
        ["Detection", "Deterministic identifier patterns, semantic headers/keys, Hindi aliases, contextual names/relatives and structural metadata. Approximate transliteration is normalization only, not identity proof."],
        ["Identity", "HMAC tokens use direct identifiers or an exact patient-name/phone pair with sex/DOB conflict checks. Broad alias, cross-script and homonym resolution remain limited."],
        ["Privacy", "Supported paths use deterministic date shifts, age bands, locality generalization and PIN-prefix masking. Rare-combination suppression and attack-based risk measurement are not implemented."],
        ["Security", "No raw-copy fallback; SHA-256 report accounting avoids source paths; secret is environment-provided. Encryption of persisted intermediates and a blocking independent release gate remain incomplete."],
    ], [29 * mm, 151 * mm]),
    section("4. Security design"),
    P("The input tree is read without intentional modification; hashes support accounting. Locator-based edits remain separate from the authoritative source IR until serialization. Known parse failures are quarantined rather than copied as sanitized output. HMAC tokens use an environment-provided secret, and the pipeline makes no runtime network calls or model downloads."),
    P("Parsed source values remain in memory. Persisted-data encryption, key rotation and automatic blocking by the independent verifier are incomplete. Use synthetic data only."),
    PageBreak(),
    P("Evaluation and readiness", "TitleSW"),
    P("Measured on the organizer's synthetic 200-file development corpus; Linux run, 2026-11-27. This is development evidence, not a hidden-set score or a privacy guarantee.", "SubSW"),
    section("5. Privacy-utility results"),
]
metrics = [
    [P("0 / 3,234", "MetricSW"), P("4,825 / 4,855", "MetricSW"), P("197 / 200", "MetricSW")],
    [P("labeled PII surfaces visible (scorecard; self-check: 0 / 3,230)", "SmallSW"), P("clinical values retained (99.38%)", "SmallSW"), P("exported; 3 quarantined", "SmallSW")],
]
mt = Table(metrics, colWidths=[60 * mm] * 3)
mt.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PALE), ("BOX", (0, 0), (-1, -1), 0.6, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
story += [mt, Spacer(1, 2 * mm), table([
    ["Measure", "Observed result"],
    ["Script and channel results", "0 labeled misses in the measured Latin, Devanagari, Hinglish, content, filename, header, key, metadata and base64 groups."],
    ["Canaries and accounting", "0 / 4 canaries; 200 inputs accounted for: 197 sanitized, 3 quarantined, 0 unaccounted."],
    ["Determinism and key change", "The Toolkit three-run helper confirmed same-secret output equality, changed-secret output, no secret in logs/output, and unchanged input."],
    ["Linkage", "Practice self-check: precision 1.00, recall 0.61, F0.5 0.89, with zero observed false merges. Not a hidden-set guarantee."],
    ["Independent verifier", "Passed: all 200 files inspectable, with no surviving supported identifier candidates. It runs separately, not as an automatic release gate."],
    ["Linux runtime / memory", "Python 3.10, 2 CPUs, 4 GB, offline: 5.44 seconds reported and 58.3 MB peak RSS on staged input. Official helper run A took 27 seconds from OneDrive."],
    ["OCR capability", "Native pdftoppm and Tesseract executables were missing; image-only PDF rendering and pixel OCR were unavailable and reported."],
], [44 * mm, 136 * mm]), section("6. Privacy-utility trade-off"),
    P("No labeled direct-PII misses were observed on this synthetic corpus, and clinical-value retention was 99.38%. The 30 exact-match utility misses still need error review. These scores do not generalize to hidden inputs, and a zero-miss result does not establish anonymity or resistance to auxiliary-data attacks."),
    section("7. Known limitations and next work"),
    P("The Toolkit submission checks passed on Linux, but native OCR tools, full FHIR R4 validation, rare-combination suppression, and attack-based re-identification measurement remain open. Linkage is conservative and does not resolve all aliases or homonyms. Keep those limits visible; do not use real patient data or claim anonymity."),
    P("Reproduce: set KIT to the extracted Toolkit root and RAKSHA_SECRET in the environment; run python main.py --input $KIT/dev/input --output build/practice-output. Validators and truth scorers are in $KIT/.", "SmallSW"),
]

doc = BaseDocTemplate(str(OUT), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=18 * mm, title="Secret Wards - Project Brief", author="Secret Wards")
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
doc.addPageTemplates([PageTemplate(id="brief", frames=[frame], onPage=page)])
doc.build(story)
print(OUT)
