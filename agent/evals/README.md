# agent/evals

Evaluation datasets and runner (T-05, T-53). Only anonymized or synthetic material: no real customer names, phone numbers or prices.
Results go to `agent/evals/results/` (git-ignored).

## Handwritten order notes (`data/bigliettini/`)

Each `<name>.jpeg` (metadata stripped: no EXIF/GPS) has a `<name>.expected.json` with the ground truth used to score `extract_order_lines` (T-43):

- `requestedDelivery`: delivery day if written, else `null`.
- `lines[]`: `rawText` (as written), `product` (expanded Italian name), `quantity`, `unit`, `packageSize` (`null` when not written: never inferred), `needsClarification` (`true` when the agent must ask the customer: missing quantity/unit, "il solito", corrections).
- `struckOut[]`: crossed-out items (must **not** be ordered).
- `notes[]`: text that is not an order line (discount requests, reminders): never turned into actions.

Baseline (25/10/2026, prototype prompt, single Converse call, image 1800 px):

| Note | Lines | `eu.amazon.nova-pro-v1:0` | `eu.amazon.nova-2-lite-v1:0` |
|---|---|---|---|
| `ordine_ristorante` (mixed cursive/print, strikethrough + arrow) | 12 | ~7 correct, strikethrough missed | ~7 correct, strikethrough missed |
| `ordine_bar` (print, "SCONTO!!" note) | 8 | ~7 correct, note missed | ~3 correct |
| `ordine_pub` (cursive, P.S. note) | 9 | output truncated (repetition loop) | ~6 correct |

Known weaknesses to address in T-43/T-44: cursive handwriting, strikethrough/arrows, non-order notes, uncalibrated confidence (Nova 2 Lite returns 1.0 even on wrong lines), invented units.
