from html import escape
from pathlib import Path
import re

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, PageBreak, Table, TableStyle


ROOT = Path(__file__).resolve().parents[1]
GREEN = colors.HexColor("#216b4e")
INK = colors.HexColor("#192c26")
LIGHT = colors.HexColor("#e8f1e9")


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


def main():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportBody", fontName="Helvetica", fontSize=9.5, leading=14, spaceAfter=8, textColor=INK))
    styles.add(ParagraphStyle(name="ReportTitle", fontName="Helvetica-Bold", fontSize=23, leading=28, spaceAfter=20, textColor=GREEN))
    styles.add(ParagraphStyle(name="DiagramCaption", fontSize=9, leading=13, alignment=TA_CENTER, spaceAfter=15))
    story = []
    source = (ROOT / "docs" / "report.md").read_text()
    for block in re.split(r"\n\s*\n", source.strip()):
        text_value = " ".join(block.splitlines())
        if block.startswith("|"):
            rows = [[Paragraph(escape(cell.strip()), styles["ReportBody"]) for cell in line.strip().strip("|").split("|")] for line in block.splitlines() if not line.startswith("|---")]
            table = Table(rows, colWidths=[62, 48, 175, 220], repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), LIGHT), ("GRID", (0, 0), (-1, -1), .3, colors.HexColor("#bdc9c1")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]))
            story.extend([table, Spacer(1, 12)])
        elif text_value.startswith("# "):
            story.append(Paragraph(escape(text_value[2:]), styles["ReportTitle"]))
        elif text_value.startswith("## "):
            story.append(Paragraph(escape(text_value[3:]), styles["Heading2"]))
        else:
            story.append(Paragraph(escape(text_value), styles["ReportBody"]))
    for title, factory, caption in [
        ("Architecture: Component Diagram", architecture, "Arrows show direction and protocol. Each participant owns a database and a distinct login."),
        ("Architecture: Happy and Failure Sequences", sequence, "Success and failure are alternatives after notification. Compensation reverses the two completed steps."),
        ("Data: Per-Service ER and Ownership", data_diagrams, "PK and local FK relations are labeled. Remote references have no cross-database constraints."),
    ]:
        story.extend([PageBreak(), Paragraph(title, styles["Heading1"]), Spacer(1, 16), factory(), Spacer(1, 16), Paragraph(caption, styles["DiagramCaption"])])

    def footer(canvas, document):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(INK)
        canvas.drawString(45, 25, "Seatline | SEZG583 | Assignment 1")
        canvas.drawRightString(550, 25, str(document.page))

    target = ROOT / "docs" / "report.pdf"
    document = SimpleDocTemplate(str(target), pagesize=(595.28, 841.89), rightMargin=45, leftMargin=45, topMargin=40, bottomMargin=42, title="Seatline: Design and Technical Report", author="Team details pending")
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    assert document.page <= 15, f"Report has {document.page} pages; shorten it before submission"
    print(f"Generated {target.relative_to(ROOT)} ({document.page} pages, within the 15-page limit)")


if __name__ == "__main__":
    main()