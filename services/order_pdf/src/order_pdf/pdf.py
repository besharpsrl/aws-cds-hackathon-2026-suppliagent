"""Minimal PDF writer for the order confirmation (FN-14): Helvetica text on A4, no dependencies.

ponytail: no word wrap (long text is cut), no logo or boxes; a lib such as reportlab if the demo
needs a branded document. Text is WinAnsi (cp1252); other characters become `?`.
"""

from decimal import Decimal
from typing import Any

PAGE_W, PAGE_H = 595, 842
MARGIN = 50
LINE_H = 16
LINES_PER_PAGE = 40  # table rows per page: the first page's table starts at y=700, ends above 60
COLUMNS = ((MARGIN, 14), (130, 44), (460, 12))  # x, max characters: SKU, description, quantity


def _text(value: object, limit: int) -> str:
    raw = str(value)[:limit].encode("cp1252", "replace").decode("cp1252")
    return raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _show(x: int, y: int, value: object, limit: int, size: int = 10, bold: bool = False) -> str:
    font = "F2" if bold else "F1"
    return f"BT /{font} {size} Tf {x} {y} Td ({_text(value, limit)}) Tj ET\n"


def _row(y: int, cells: tuple[object, ...], bold: bool = False) -> str:
    return "".join(
        _show(x, y, cell, limit, bold=bold) for (x, limit), cell in zip(COLUMNS, cells, strict=True)
    )


def _quantity(line: dict[str, Any]) -> str:
    quantity = line.get("quantity", "")
    shown = f"{quantity:g}" if isinstance(quantity, int | float | Decimal) else quantity
    return f"{shown} {line.get('unit', '')}".strip()


def _pages(order: dict[str, Any]) -> list[str]:
    first = [
        _show(MARGIN, 790, "Order confirmation", 60, size=18, bold=True),
        _show(MARGIN, 765, f"Order {order['orderId']}", 80, size=11),
        _show(MARGIN, 749, f"Delivery date: {order.get('deliveryDate', '-')}", 80, size=11),
    ]
    if notes := order.get("deliveryNotes"):
        first.append(_show(MARGIN, 733, f"Notes: {notes}", 90, size=11))
    lines = order.get("lines", [])
    chunks = [lines[i : i + LINES_PER_PAGE] for i in range(0, len(lines), LINES_PER_PAGE)] or [[]]
    pages = []
    for number, chunk in enumerate(chunks):
        out, top = ("".join(first), 700) if number == 0 else ("", 790)
        if number:
            out = _show(MARGIN, 810, f"Order {order['orderId']} (continued)", 80, size=11)
        out += _row(top, ("SKU", "Description", "Quantity"), bold=True)
        for index, line in enumerate(chunk, start=1):
            name = line.get("name") or line.get("rawText") or line.get("description", "")
            out += _row(top - index * LINE_H, (line.get("sku", ""), name, _quantity(line)))
        pages.append(out)
    return pages


def render_order_pdf(order: dict[str, Any]) -> bytes:
    pages = _pages(order)
    # Objects: 1 catalog, 2 page tree, 3-4 fonts, then (page, content stream) per page.
    kids = " ".join(f"{5 + 2 * i} 0 R" for i in range(len(pages)))
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    for i, content in enumerate(pages):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {6 + 2 * i} 0 R >>"
        )
        objects.append(f"<< /Length {len(content.encode('cp1252'))} >>\nstream\n{content}endstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode("cp1252")
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    trailer = f"<< /Size {len(objects) + 1} /Root 1 0 R >>"
    out += f"trailer\n{trailer}\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)
