"""Order confirmation email (FN-14, F-07 step 4): subject, HTML and plain text, IT and EN.

One column, inline styles, max 600 px: readable on mobile and desktop mail clients. Every value
from the order is escaped. Only the order data: no prices other than the listed ones, no contact
data.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from html import escape
from typing import Any

from suppliagent_shared.orders import ACTIVE_LINES

WEEKDAYS = {
    "it": ("lun", "mar", "mer", "gio", "ven", "sab", "dom"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
}
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
TEXTS = {
    "it": {
        "subject": "Conferma ordine {order} - consegna {date}",
        "subject_updated": "Ordine aggiornato {order} - consegna {date}",
        "title": "Ordine confermato",
        "title_updated": "Ordine aggiornato",
        "intro": "Abbiamo ricevuto l'ordine per {venue}. Ecco il riepilogo.",
        "intro_updated": "L'ordine per {venue} è stato modificato. Ecco il riepilogo aggiornato.",
        "order": "Ordine",
        "erp": "Numero d'ordine",
        "delivery": "Consegna",
        "notes": "Note",
        "product": "Prodotto",
        "quantity": "Quantità",
        "amount": "Importo",
        "total": "Totale stimato (IVA esclusa)",
        "attached": "In allegato il PDF dell'ordine.",
        "changes": "Per modifiche rispondi a questa email o scrivici su WhatsApp, entro il "
        "cut-off del giorno prima della consegna.",
        "footer": "Messaggio dell'assistente virtuale del tuo distributore, inviato per la "
        "conferma d'ordine.",
    },
    "en": {
        "subject": "Order confirmation {order} - delivery {date}",
        "subject_updated": "Order updated {order} - delivery {date}",
        "title": "Order confirmed",
        "title_updated": "Order updated",
        "intro": "We have received the order for {venue}. Here is the summary.",
        "intro_updated": "The order for {venue} was changed. Here is the updated summary.",
        "order": "Order",
        "erp": "Order number",
        "delivery": "Delivery",
        "notes": "Notes",
        "product": "Product",
        "quantity": "Quantity",
        "amount": "Amount",
        "total": "Estimated total (VAT excluded)",
        "attached": "The order PDF is attached.",
        "changes": "To change it, reply to this email or message us on WhatsApp, before the "
        "cut-off on the day before the delivery.",
        "footer": "Message from your distributor's virtual assistant, sent to confirm your order.",
    },
}


@dataclass(frozen=True)
class Email:
    subject: str
    html: str
    text: str


def _language(language: str | None) -> str:
    return "en" if (language or "").lower().startswith("en") else "it"


def format_date(value: str | None, language: str) -> str:
    if not value:
        return "-"
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return value
    weekday = WEEKDAYS[language][day.weekday()]
    if language == "en":
        return f"{weekday} {day.day} {MONTHS_EN[day.month - 1]} {day.year}"
    return f"{weekday} {day:%d/%m/%Y}"


def _money(value: object, language: str) -> str:
    amount = f"{Decimal(str(value)).quantize(Decimal('0.01')):,.2f}"
    if language == "it":
        amount = amount.replace(",", "_").replace(".", ",").replace("_", ".")
    return f"€ {amount}"


def _quantity(line: dict[str, Any]) -> str:
    quantity = line.get("quantity", "")
    shown = f"{quantity:g}" if isinstance(quantity, int | float | Decimal) else str(quantity)
    return f"{shown} {line.get('unit', '')}".strip()


def _product(line: dict[str, Any]) -> str:
    name = str(line.get("name") or line.get("rawText") or line.get("description") or "")
    return f"{name} ({line['format']})" if line.get("format") else name


def order_lines(order: dict[str, Any]) -> list[dict[str, Any]]:
    """The lines that are part of the order: not the removed or unresolved ones."""
    lines: list[dict[str, Any]] = order.get("lines", [])
    return [line for line in lines if line.get("status", "CONFIRMED") in ACTIVE_LINES]


def render(
    order: dict[str, Any], venue: str, language: str | None, *, updated: bool = False
) -> Email:
    lang = _language(language)
    t = TEXTS[lang]
    suffix = "_updated" if updated else ""
    when = format_date(order.get("deliveryDate"), lang)
    subject = t["subject" + suffix].format(order=order["orderId"], date=when)
    lines = order_lines(order)
    facts = [(t["order"], order["orderId"])]
    if order.get("erpOrderNumber"):
        facts.append((t["erp"], str(order["erpOrderNumber"])))
    facts.append((t["delivery"], when))
    if order.get("deliveryNotes"):
        facts.append((t["notes"], str(order["deliveryNotes"])))
    total = _money(order.get("total", 0), lang)
    intro = t["intro" + suffix].format(venue=venue)

    text_rows = [
        f"- {_quantity(ln)} {_product(ln)}"
        + (f"  {_money(ln['lineTotal'], lang)}" if "lineTotal" in ln else "")
        for ln in lines
    ]
    text = "\n".join(
        [
            t["title" + suffix],
            "",
            intro,
            "",
            *(f"{k}: {v}" for k, v in facts),
            "",
            *text_rows,
            "",
            f"{t['total']}: {total}",
            "",
            t["attached"],
            t["changes"],
            "",
            "--",
            t["footer"],
        ]
    )

    cell = "padding:8px 6px;border-bottom:1px solid #e5e7eb;vertical-align:top"
    rows = "".join(
        f'<tr><td style="{cell}">{escape(_product(ln))}</td>'
        f'<td style="{cell};white-space:nowrap">{escape(_quantity(ln))}</td>'
        f'<td style="{cell};text-align:right;white-space:nowrap">'
        f"{escape(_money(ln['lineTotal'], lang)) if 'lineTotal' in ln else '-'}</td></tr>"
        for ln in lines
    )
    fact_rows = "".join(
        f'<tr><td style="padding:2px 12px 2px 0;color:#6b7280">{escape(k)}</td>'
        f'<td style="padding:2px 0;font-weight:600">{escape(v)}</td></tr>'
        for k, v in facts
    )
    head = "padding:8px 6px;border-bottom:2px solid #111827;text-align:left;font-size:13px"
    html = f"""<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f3f4f6">
<div style="max-width:600px;margin:0 auto;padding:16px;font-family:Arial,Helvetica,sans-serif;\
color:#111827;font-size:15px;line-height:1.45">
<div style="background:#ffffff;border-radius:8px;padding:20px">
<h1 style="margin:0 0 12px;font-size:22px;color:#0f766e">{escape(t["title" + suffix])}</h1>
<p style="margin:0 0 16px">{escape(intro)}</p>
<table role="presentation" style="border-collapse:collapse;margin:0 0 16px">{fact_rows}</table>
<table style="width:100%;border-collapse:collapse;font-size:14px">
<thead><tr><th style="{head}">{escape(t["product"])}</th>
<th style="{head}">{escape(t["quantity"])}</th>
<th style="{head};text-align:right">{escape(t["amount"])}</th></tr></thead>
<tbody>{rows}</tbody></table>
<p style="margin:16px 0;text-align:right;font-size:16px"><strong>{escape(t["total"])}: \
{escape(total)}</strong></p>
<p style="margin:0 0 8px">{escape(t["attached"])}</p>
<p style="margin:0;color:#4b5563;font-size:13px">{escape(t["changes"])}</p>
</div>
<p style="margin:12px 4px 0;color:#6b7280;font-size:12px">{escape(t["footer"])}</p>
</div></body></html>
"""
    return Email(subject=subject, html=html, text=text)
