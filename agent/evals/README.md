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

### Runner `run_order_intake.py` (T-43)

`uv run python agent/evals/run_order_intake.py [--model <inference profile>]` chiama Bedrock (solo `InvokeModel`, una chiamata per bigliettino) con il prompt e lo schema del tool `extract_order_lines` e confronta le righe con `*.expected.json`. Una riga è corretta se il testo è simile e la quantità uguale (approssimazione del criterio FN-05, non il criterio). Conta anche `wrongButRead`: righe lette male ma presentate come valide.

Risultato del 26/10/2026 (`eu.amazon.nova-pro-v1:0`, immagini originali, temperature 0; due esecuzioni dello stesso prompt hanno dato 19/29 e 18/29: la variabilità c'è anche a temperatura 0):

| Bigliettino | Righe attese | Corrette | Lette male come valide |
|---|---|---|---|
| `ordine_bar` | 8 | 6 | 2 |
| `ordine_pub` | 9 | 8 | 1 |
| `ordine_ristorante` (corsivo) | 12 | 4 | 6 |
| **Totale** | 29 | **18 (62%)** | 9 |

Rispetto al baseline: nessun troncamento sul pub (tetto `maxTokens`, tool call forzata). Restano: corsivo (il ristorante), note e righe barrate non riportate in `ignoredNotes`/`struckOut` (non finiscono comunque tra le righe), confidenza poco calibrata. Un tentativo di prompt ("lettura non plausibile → `UNREADABLE`") ha peggiorato (41%, il pub ha restituito 19 righe) ed è stato scartato. Criterio FN-05 (≥ 90% su ≥ 15 bigliettini): **non raggiunto né misurabile con 3 note**; resta a T-53.
