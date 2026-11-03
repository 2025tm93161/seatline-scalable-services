import argparse
from html import escape
from io import BytesIO
from math import hypot
from pathlib import Path
import re

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image, ImageDraw, ImageFont
import reportlab
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, PageBreak, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
GREEN = colors.HexColor("#216b4e")
INK = colors.HexColor("#192c26")
LIGHT = colors.HexColor("#e8f1e9")
PAGE_SIZE = (595.28, 841.89)
LEFT_MARGIN = 45
RIGHT_MARGIN = 45


def box(drawing, x, y, width, height, title, lines=()):
    drawing.add(Rect(x, y, width, height, fillColor=LIGHT, strokeColor=GREEN, strokeWidth=.7))
    drawing.add(String(x + 9, y + height - 18, title, fontName="Helvetica-Bold", fontSize=10, fillColor=INK))
    for index, line in enumerate(lines):
        drawing.add(String(x + 9, y + height - 35 - index * 13, line, fontName="Helvetica", fontSize=8, fillColor=INK))


def arrow(drawing, x1, y1, x2, y2, label=""):
    drawing.add(Line(x1, y1, x2, y2, strokeColor=GREEN, strokeWidth=1))
    direction = 1 if x2 >= x1 else -1
    if y1 == y2:
        drawing.add(Polygon([x2, y2, x2 - 5 * direction, y2 + 3, x2 - 5 * direction, y2 - 3], fillColor=GREEN, strokeColor=GREEN))
    else:
        vertical = 1 if y2 >= y1 else -1
        drawing.add(Polygon([x2, y2, x2 - 3, y2 - 5 * vertical, x2 + 3, y2 - 5 * vertical], fillColor=GREEN, strokeColor=GREEN))
    if label:
        drawing.add(String((x1 + x2) / 2, (y1 + y2) / 2 + 6, label, textAnchor="middle", fontSize=7, fillColor=INK))


def architecture():
    drawing = Drawing(500, 300)
    box(drawing, 160, 250, 180, 42, "Client: console / scripts")
    box(drawing, 160, 165, 180, 42, "Booking: saga owner")
    arrow(drawing, 250, 250, 250, 207, "REST HTTP JSON")
    for x, title, operation in [(5, "Inventory", "reserve / release"), (175, "Payment mock", "charge / refund"), (345, "Notification mock", "deliver")]:
        box(drawing, x, 75, 150, 40, title)
        arrow(drawing, 250, 165, x + 75, 115, "HTTP " + operation)
        box(drawing, x, 0, 150, 35, title.split()[0] + " database")
        arrow(drawing, x + 75, 75, x + 75, 35, "own SQL login")
    box(drawing, 345, 170, 150, 35, "Booking database")
    arrow(drawing, 340, 186, 345, 186)
    return drawing


def sequence():
    drawing = Drawing(500, 430)
    positions = {"Client": 35, "Booking": 140, "Inventory": 250, "Payment": 355, "Notify": 465}
    for name, x in positions.items():
        drawing.add(String(x, 415, name, textAnchor="middle", fontName="Helvetica-Bold", fontSize=9))
        drawing.add(Line(x, 400, x, 12, strokeColor=colors.HexColor("#bdc9c1"), strokeDashArray=[3, 3]))
    messages = [
        ("Client", "Booking", "HTTP create + key / request ID"),
        ("Booking", "Inventory", "HTTP reserve; persist RESERVED"),
        ("Inventory", "Booking", "201 hold + authoritative price"),
        ("Booking", "Payment", "HTTP charge; stable key"),
        ("Payment", "Booking", "201 CHARGED; persist PAID"),
        ("Booking", "Notify", "HTTP deliver; stable key"),
        ("Notify", "Booking", "Success: 201 DELIVERED"),
        ("Booking", "Client", "Success: 201 CONFIRMED"),
        ("Notify", "Booking", "Failure alternative: 503 provider unavailable"),
        ("Booking", "Payment", "HTTP refund; persist COMPENSATING"),
        ("Payment", "Booking", "200 REFUNDED"),
        ("Booking", "Inventory", "HTTP release"),
        ("Inventory", "Booking", "200 RELEASED"),
        ("Booking", "Client", "409 CANCELLED; capacity restored"),
    ]
    for index, (source, target, label) in enumerate(messages):
        y = 390 - index * 27
        arrow(drawing, positions[source], y, positions[target], y, label)
    return drawing


def data_diagrams():
    drawing = Drawing(500, 540)
    box(drawing, 0, 280, 240, 250, "Inventory DB / inventory_user", [
        "events: PK id, name, capacity, available, price_cents",
        "holds: PK id, FK event_id, quantity, state",
        "events 1 --> many holds (local FK)",
        "released_holds: PK id (cancellation fence)",
        "idempotency: PK key, fingerprint, status, response",
        "CHECK 0 <= available <= capacity",
        "All updates and holds commit atomically.",
    ])
    box(drawing, 260, 280, 240, 250, "Booking DB / booking_user", [
        "bookings: PK id, payload, state, amount_cents, reason",
        "transitions: PK sequence, FK booking_id,",
        "state, created_at",
        "bookings 1 --> many transitions (local FK)",
        "idempotency: PK key, fingerprint, status, response",
        "payload includes opaque event ID.",
    ])
    box(drawing, 0, 20, 240, 235, "Payment DB / payment_user", [
        "payments: PK booking_id, amount_cents, state",
        "idempotency: PK key, fingerprint, status, response",
        "booking_id is a remote ID, not a foreign key.",
        "CHARGED / DECLINED / REFUNDED / CANCELLED",
        "Cancellation fence prevents delayed charge.",
    ])
    box(drawing, 260, 20, 240, 235, "Notification DB / notification_user", [
        "deliveries: PK booking_id, recipient, state",
        "idempotency: PK key, fingerprint, status, response",
        "booking_id is a remote ID, not a foreign key.",
        "Only successful delivery is recorded.",
        "No cross-database queries or foreign keys.",
    ])
    return drawing


def markdown_rows(block):
    rows = []
    for line in block.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(not cell.replace(":", "").replace("-", "").strip() for cell in cells):
            continue
        rows.append(cells)
    return rows


def add_markdown_text(paragraph, text):
    for part in re.split(r"(`[^`]+`)", text):
        if part.startswith("`") and part.endswith("`"):
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Courier New"
            run.font.size = Pt(9)
        else:
            paragraph.add_run(part)


def diagram_png(drawing, scale=2):
    width = round(drawing.width * scale)
    height = round(drawing.height * scale)
    image = Image.new("RGB", (width, height), "white")
    canvas = ImageDraw.Draw(image)
    font_directory = Path(reportlab.__file__).parent / "fonts"

    def point(x, y):
        return round(x * scale), round((drawing.height - y) * scale)

    def color(value):
        if value is None:
            return None
        return tuple(round(component * 255) for component in (value.red, value.green, value.blue))

    def line(shape):
        start = point(shape.x1, shape.y1)
        end = point(shape.x2, shape.y2)
        stroke = color(shape.strokeColor)
        width = max(1, round(shape.strokeWidth * scale))
        if not shape.strokeDashArray:
            canvas.line((start, end), fill=stroke, width=width)
            return

        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = hypot(dx, dy)
        pattern = [max(1, value * scale) for value in shape.strokeDashArray]
        offset = 0
        pattern_index = 0
        while offset < length:
            segment = min(pattern[pattern_index % len(pattern)], length - offset)
            if pattern_index % 2 == 0:
                first = (start[0] + dx * offset / length, start[1] + dy * offset / length)
                last_offset = offset + segment
                last = (start[0] + dx * last_offset / length, start[1] + dy * last_offset / length)
                canvas.line((first, last), fill=stroke, width=width)
            offset += segment
            pattern_index += 1

    for shape in drawing.contents:
        if isinstance(shape, Rect):
            left = round(shape.x * scale)
            top = round((drawing.height - shape.y - shape.height) * scale)
            right = round((shape.x + shape.width) * scale)
            bottom = round((drawing.height - shape.y) * scale)
            canvas.rectangle((left, top, right, bottom), fill=color(shape.fillColor), outline=color(shape.strokeColor), width=max(1, round(shape.strokeWidth * scale)))
        elif isinstance(shape, Line):
            line(shape)
        elif isinstance(shape, Polygon):
            coordinates = [point(shape.points[index], shape.points[index + 1]) for index in range(0, len(shape.points), 2)]
            canvas.polygon(coordinates, fill=color(shape.fillColor), outline=color(shape.strokeColor))
        elif isinstance(shape, String):
            bold = "Bold" in shape.fontName
            font_path = font_directory / ("VeraBd.ttf" if bold else "Vera.ttf")
            font = ImageFont.truetype(str(font_path), max(1, round(shape.fontSize * scale)))
            anchor = {"start": "ls", "middle": "ms", "end": "rs"}.get(shape.textAnchor, "ls")
            canvas.text(point(shape.x, shape.y), shape.text, fill=color(shape.fillColor), font=font, anchor=anchor)

    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def build_docx(source, target, document_name):
    document = Document()
    section = document.sections[0]
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    section.left_margin = Inches(.62)
    section.right_margin = Inches(.62)
    section.top_margin = Inches(.62)
    section.bottom_margin = Inches(.62)

    normal = document.styles["Normal"]
    normal.font.name = "Arial"
    normal.font.size = Pt(10)
    normal.font.color.rgb = RGBColor(25, 44, 38)
    for style_name, size in (("Title", 23), ("Heading 1", 17), ("Heading 2", 13), ("Heading 3", 11)):
        style = document.styles[style_name]
        style.font.name = "Arial"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor(33, 107, 78)

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    footer.add_run(f"Seatline | SEZG583 | {document_name.title()}")

    content_width = 8.27 - .62 - .62
    column_weights = {
        2: [.45, .55],
        3: [.18, .17, .65],
        4: [.20, .15, .28, .37],
    }
    for block in re.split(r"\n\s*\n", source.strip()):
        if block.startswith("|"):
            rows = markdown_rows(block)
            if not rows:
                continue
            count = len(rows[0])
            weights = column_weights.get(count, [1 / count] * count)
            table = document.add_table(rows=len(rows), cols=count)
            table.style = "Table Grid"
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = False
            for row_index, cells in enumerate(rows):
                for column_index, value in enumerate(cells):
                    cell = table.cell(row_index, column_index)
                    cell.width = Inches(content_width * weights[column_index])
                    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.TOP
                    paragraph = cell.paragraphs[0]
                    paragraph.paragraph_format.space_after = Pt(2)
                    add_markdown_text(paragraph, value)
                    for run in paragraph.runs:
                        run.font.size = Pt(9)
                        if row_index == 0:
                            run.bold = True
                    if row_index == 0:
                        shading = OxmlElement("w:shd")
                        shading.set(qn("w:fill"), "E8F1E9")
                        cell._tc.get_or_add_tcPr().append(shading)
            document.add_paragraph()
            continue

        text = " ".join(block.splitlines()).strip()
        heading = re.match(r"^(#{1,4})\s+(.*)$", text)
        if heading:
            if heading.group(2) == "1. Problem and Scope":
                document.add_page_break()
            level = len(heading.group(1)) - 1
            paragraph = document.add_heading(level=level)
            add_markdown_text(paragraph, heading.group(2))
        else:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(7)
            add_markdown_text(paragraph, text.replace("**", "").replace("_", ""))

    if document_name == "report":
        diagrams = [
            ("Architecture: Component Diagram", architecture, "Arrows show direction and protocol. Each participant owns a database and a distinct login."),
            ("Architecture: Happy and Failure Sequences", sequence, "Success and failure are alternatives after notification. Compensation reverses the two completed steps."),
            ("Data: Per-Service ER and Ownership", data_diagrams, "PK and local FK relations are labeled. Remote references have no cross-database constraints."),
        ]
        for title, factory, caption in diagrams:
            document.add_page_break()
            document.add_heading(title, level=1)
            image = diagram_png(factory())
            paragraph = document.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.add_run().add_picture(BytesIO(image), width=Inches(content_width))
            caption_paragraph = document.add_paragraph(caption)
            caption_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER

    document.save(target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("document", choices=("report", "submission"), nargs="?", default="report")
    parser.add_argument("--format", choices=("pdf", "docx"), default="pdf")
    arguments = parser.parse_args()

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportBody", fontName="Helvetica", fontSize=9.5, leading=14, spaceAfter=8, textColor=INK))
    styles.add(ParagraphStyle(name="ReportTitle", fontName="Helvetica-Bold", fontSize=23, leading=28, spaceAfter=20, textColor=GREEN))
    styles.add(ParagraphStyle(name="DiagramCaption", fontSize=9, leading=13, alignment=TA_CENTER, spaceAfter=15))
    story = []
    source = (ROOT / "docs" / f"{arguments.document}.md").read_text()
    if arguments.format == "docx":
        target = ROOT / "docs" / f"{arguments.document}.docx"
        build_docx(source, target, arguments.document)
        print(f"Generated {target.relative_to(ROOT)}")
        return

    content_width = PAGE_SIZE[0] - LEFT_MARGIN - RIGHT_MARGIN
    for block in re.split(r"\n\s*\n", source.strip()):
        text_value = " ".join(block.splitlines())
        if block.startswith("|"):
            rows = [[Paragraph(escape(cell.strip()), styles["ReportBody"]) for cell in line.strip().strip("|").split("|")] for line in block.splitlines() if not line.startswith("|---")]
            column_count = len(rows[0])
            weights = {
                2: [0.45, 0.55],
                3: [0.18, 0.17, 0.65],
                4: [0.20, 0.15, 0.28, 0.37],
                5: [0.22, 0.18, 0.18, 0.30, 0.12],
            }.get(column_count, [1 / column_count] * column_count)
            column_widths = [content_width * weight for weight in weights]
            table = Table(rows, colWidths=column_widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#bdc9c1")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
            story.extend([table, Spacer(1, 12)])
        elif text_value.startswith("# "):
            story.append(Paragraph(escape(text_value[2:]), styles["ReportTitle"]))
        elif text_value.startswith("## 1. Problem and Scope"):
            story.extend([PageBreak(), Paragraph(escape(text_value[3:]), styles["Heading2"])])
        elif text_value.startswith("## "):
            story.append(Paragraph(escape(text_value[3:]), styles["Heading2"]))
        elif text_value.startswith("### "):
            story.append(Paragraph(escape(text_value[4:]), styles["Heading3"]))
        else:
            story.append(Paragraph(escape(text_value), styles["ReportBody"]))
    if arguments.document == "report":
        for title, factory, caption in [
            ("Architecture: Component Diagram", architecture, "Arrows show direction and protocol. Each participant owns a database and a distinct login."),
            ("Architecture: Happy and Failure Sequences", sequence, "Success and failure are alternatives after notification. Compensation reverses the two completed steps."),
            ("Data: Per-Service ER and Ownership", data_diagrams, "PK and local FK relations are labeled. Remote references have no cross-database constraints."),
        ]:
            story.extend([PageBreak(), Paragraph(title, styles["Heading1"]), Spacer(1, 16), factory(), Spacer(1, 16), Paragraph(caption, styles["DiagramCaption"])])

    def footer(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(INK)
        footer_label = "Submission" if arguments.document == "submission" else "Assignment 1"
        canvas.drawString(45, 25, f"Seatline | SEZG583 | {footer_label}")
        canvas.drawRightString(550, 25, str(document.page))

    target = ROOT / "docs" / f"{arguments.document}.pdf"
    title = "Seatline Submission" if arguments.document == "submission" else "Seatline: Design and Technical Report"
    document = SimpleDocTemplate(str(target), pagesize=PAGE_SIZE, rightMargin=RIGHT_MARGIN, leftMargin=LEFT_MARGIN, topMargin=40, bottomMargin=42, title=title, author="Seatline Team")
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    assert document.page <= 15, f"Document has {document.page} pages; shorten it before submission"
    print(f"Generated {target.relative_to(ROOT)} ({document.page} pages, within the 15-page limit)")


if __name__ == "__main__":
    main()