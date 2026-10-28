# seed – demo data

Only **anonymized or synthetic** data is committed here, plus `seed.py` and `reset.py`.
Raw customer exports go to `seed/private/` or `seed/raw/`: both are git-ignored and not readable by Claude Code.
Backlog: T-04.

## Contents (`data/`)

One JSON file per DynamoDB table; the file name is the table suffix (`suppliagent-<env>-<file>`). Every item is validated against `suppliagent_shared.models` before writing.

| File | Items | Notes |
|---|---|---|
| `customers.json` | 6 venues in Milan, 2 sales reps' portfolios | pizzerias, trattoria, bar, pub, osteria |
| `contacts.json` | 5 contacts | `con_001` orders for 2 venues in different portfolios (F-02.C5); `con_003` has no privacy notice yet (F-01); `con_004` speaks English |
| `channel-identities.json` | WhatsApp/email → contact or rep | fictitious numbers `+3933300000xx`, `example.com` emails |
| `sales-reps.json` | 2 reps | portfolio = customers with that `repId` |
| `order-history.json` | 8 weeks of orders | weekly/biweekly reorder patterns |
| `products.json` | 26 products | synonyms, `multiple` (butter in packs of 8), a retired SKU (`BURRO-PAN-500`); contains every SKU of the history |
| `price-lists.json` | `LIST_STD` and `LIST_BEVERAGE` | one price per SKU and list |
| `promotions.json` | 3 promotions valid 19/10–15/11/2026 | e.g. Parmigiano Reggiano, fior di latte 2 kg |
| `stock.json` | stock per SKU | out of stock with substitutes (`MOZZ-BUF-250`, restock 03/11), partial stock (`GRANA-GRAT-1KG`: 6) |
| `delivery-calendar.json` | closures 08/12 and 25/12 per zone | exceptions to `Customers.deliveryDays` only |
| `customer-insights.json` | expected reorders, dropped products, ≤ 1 suggestion | e.g. `cus_001` flour overdue, `cus_002` stopped buying ham |


## Usage

```bash
uv run python seed/seed.py --env dev [--profile NAME]   # idempotent PutItem, does not delete items; uploads data/sheets and starts the KB ingestion (--skip-sheets)
uv run python seed/reset.py --env dev [--profile NAME]  # clears Orders/Deliveries/Issues, reseeds, rebuilds the product index
```

To map a real phone to a demo contact (e.g. for WhatsApp tests), add items to `seed/private/channel-identities.json` (git-ignored), same shape as `data/channel-identities.json`.
