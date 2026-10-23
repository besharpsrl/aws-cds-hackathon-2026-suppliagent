# SuppliAgent – Backlog e piano di lavoro

> Stato: **v0.2** · Aggiornato il 23/10/2026 (ri-ordinato sul calendario reale, perimetro invariato)
> Contiene **solo il lavoro da fare**: a task completato la riga si rimuove e il task va in [DONE.md](./DONE.md) (`/implement-fn` lo fa in automatico). Una dipendenza `T-xx` che non compare più qui è completata.
> Riferimenti: [03 – Specifica funzionale](./03_FUNCTIONAL_SPEC.md) · [02 – Flussi tecnici](./02_TECHNICAL_FLOWS.md) · [Infrastructure Design](./INFRASTRUCTURE_DESIGN.md)

---

## 1. Milestone

| Fase | Periodo | Obiettivo | Uscita verificabile |
|---|---|---|---|
| **P0 – Fondamenta** | **23/10** | Monorepo, CI, CDK skeleton, avvio dati di prova e canali | `cdk synth` verde in CI; template WhatsApp inviati a Meta |
| **P1 – Walking skeleton** | 23–24/10 | Un messaggio WhatsApp attraversa tutta la pipeline e riceve risposta dall'agente | "ciao" su WhatsApp → risposta dell'agente via Notifier, con debounce, in `dev` |
| **P2 – Ordine da foto end-to-end** | 24–25/10 | Scenario S1 completo | S1 eseguibile in `dev` dall'inizio alla fine |
| **P3 – Copilota, proattività, consegne, console** | 25–26/10 | Scenari S2–S7, console operativa | S3, S5, S6 eseguibili; console con inbox ordini e handoff |
| **Code freeze** | **26/10 sera** | Solo bugfix dopo questa data | – |
| **P4 – Hardening e materiali** | 27–28/10 | Eval, KPI, ambiente `demo`, README, video, submission | Submission inviata **entro il 28/10 mattina** (scadenza 21:00) |

Percorso critico: **T-04 dati** → T-20/T-21/T-22 ingestion → T-40/T-41 agente → T-43 lettura → T-44 matching → T-45/T-46/T-47 ordine → T-07 ERP/PDF → T-24/T-26/T-27 conferme → T-10/T-12 demo e video.

## 2. Sequenza consigliata (ondate parallele)

Ogni ondata parte quando le dipendenze sono chiuse; dentro un'ondata i task di stream diversi vanno in parallelo.

| Ondata | Quando | IN | CH | AG | CO |
|---|---|---|---|---|---|
| 1 | 23/10 mattina | – | **T-28** | – | – |
| 2 | 23/10 pomeriggio | T-04 (avvio) | T-20 | T-42 (su dati seed) | – |
| 3 | 23–24/10 | T-04 (completamento), T-05 | T-21, T-23 | T-40 | T-60 |
| 4 | 24/10 | T-06 | T-22, T-24 (base) | T-41 | T-61 |
| 5 | 24–25/10 | T-07 | T-25, T-24 (completo) | T-43, T-44, T-45 | T-62 (con dati mock) |
| 6 | 25/10 | T-09 | T-26, T-27 | T-46, T-47, T-48, T-49, T-53 (avvio) | T-63 |
| 7 | 25–26/10 | T-08 | – | T-50, T-51, T-52 | T-64, T-65 |
| 8 | 27–28/10 | T-10, T-11, T-12 | bugfix | T-53 (report eval), bugfix | T-66, bugfix |

## 3. Task (in ordine di esecuzione per stream)

Legenda stato: ☐ da fare · ◐ in corso · ⛔ bloccato (i task fatti sono in [DONE.md](./DONE.md))

### IN – Infra, Dati & Materiali

| # | ID | Task | FN | Fase | Dipende da | Owner | Stato |
|---|---|---|---|---|---|---|---|
| 1 | T-04 | Dati di prova: catalogo anonimizzato/sintetico (sinonimi, unità, multipli), listini, promo, stock con esauriti e sostituti, calendario consegne, clienti/contatti/agenti, storico ordini con pattern di riordino; `seed/seed.py`, `seed/reset.py` | FN-31 | P0–P1 | T-03, dati cliente | | ☐ |
| 2 | T-05 | Dataset eval: ≥ 15 bigliettini scritti a mano (grafie diverse), vocali, email d'ordine, conversazioni attese | FN-05, 07 | P1 | T-04 | | ☐ |
| 3 | T-06 | `CatalogStack`: S3 Vectors (indice `products`), `catalog_indexer`, Knowledge Base schede tecniche (vector store S3 Vectors) | FN-07, 21 | P1 | T-03, T-04 | | ☐ |
| 4 | T-07 | ERP adapter mock (`submit/update/cancel/getStatus`, simulazione pianificazione e consegna) + `order_pdf` + regola EventBridge `order.confirmed` | FN-13, 14 | P2 | T-03 | | ☐ |
| 5 | T-09 | `AnalyticsStack`: Firehose → S3 Parquet → Glue → viste Athena KPI; dashboard e allarmi CloudWatch | FN-30, 33 | P2–P3 | T-03 | | ☐ |
| 6 | T-08 | `ProactiveStack`: `insights_analyzer` (riordini scaduti, prodotti smessi, gap vs simili), `proactive_trigger`, scheduler | FN-19, 20 | P3 | T-04, T-22 | | ☐ |
| 7 | T-10 | Ambiente `demo`, script reset, README sezione giudici, cliente/bigliettino di prova | FN-31 | P4 | tutti | | ☐ |
| 8 | T-11 | Opportunità ACE, export PNG del diagramma, testi submission (EN), paragrafo WhatsApp | – | P4 (avviabile subito) | – | | ☐ |
| 9 | T-12 | Copione e registrazione video (≤ 3 min) | – | P4 (copione da P2) | T-10 | | ☐ |

### CH – Canali CDS

| # | ID | Task | FN | Fase | Dipende da | Owner | Stato |
|---|---|---|---|---|---|---|---|
| 1 | T-28 | **Testi template WhatsApp** e invio a Meta per approvazione (`order_confirmation`, `reorder_suggestion`, `delivery_update`, `order_pending_reminder`) | FN-12, 19 | **P0 – subito** | – | | ☐ |
| 2 | T-20 | `ChannelsStack`: SES (identity, configuration set, receipt rule → S3 + SNS), EUM SMS/RCS (configuration set, event destinations, opt-out), EUM Social (event destination SNS), topic SNS | FN-01 | P0–P1 | T-03 | | ☐ |
| 3 | T-21 | `MessagingStack` + `inbound_router`: SQS FIFO + DLQ, normalizzazione WhatsApp/email/SMS/web, identità e ruolo, idempotenza, read receipt, check handoff | FN-01, 03, 26 | P1 | T-20, T-03 | | ☐ |
| 4 | T-23 | `media_fetcher` (WhatsApp media → S3) ed estrazione allegati email | FN-05, 06 | P1 | T-21 | | ☐ |
| 5 | T-22 | `TurnBuffer` + coda `turn-flush` + `turn_dispatcher` (debounce, lock, drain, re-flush) | FN-26 | P1 | T-21 | | ☐ |
| 6 | T-24 | `notifier`: unico punto di uscita, policy di canale, finestra 24h/template, fallback RCS→SMS, fasce orarie, opt-out, idempotenza (versione base in P1, completa in P2) | FN-01, 14, 15 | P1–P2 | T-20 | | ☐ |
| 7 | T-25 | Messaggi interattivi WhatsApp (button/list) e parsing delle risposte | FN-08, 12 | P2 | T-24 | | ☐ |
| 8 | T-26 | Email: template HTML conferma con PDF allegato; ordini via email (corpo, foto, PDF, Excel) | FN-06, 14 | P2 | T-24, T-07 | | ☐ |
| 9 | T-27 | RCS: rich card conferma e consegna con suggested replies; fallback SMS | FN-15, 18 | P2–P3 | T-24 | | ☐ |

### AG – Agent & AgentCore

| # | ID | Task | FN | Fase | Dipende da | Owner | Stato |
|---|---|---|---|---|---|---|---|
| 1 | T-42 | Tool `customers`: `identify_contact`, `get_customer_profile` + autorizzazione per ruolo + test negativi | FN-03, 32 | P0–P1 | T-04 (seed) | | ☐ |
| 2 | T-40 | `AgentStack`: ECR, AgentCore Runtime/Endpoint, Memory, Gateway (auth OAuth), Identity, Guardrail | FN-32 | P1 | T-03 | | ☐ |
| 3 | T-41 | Agente Strands: entrypoint, contesto iniettato non modificabile (`contactId`, `role`, `customerIds`), prompt per ruolo (`customer`, `sales_rep`, `shared`), set di tool per ruolo, multilingua | FN-03, 04, 27 | P1 | T-40, T-22 | | ☐ |
| 4 | T-43 | Tool `order_intake`: `extract_order_lines` (Claude vision, output strutturato, `imageRegion`) + trascrizione vocali — **prototipo di lettura da avviare già in P1** su bigliettini reali | FN-05, 06 | P1–P2 | T-23, T-41 | | ☐ |
| 5 | T-44 | Tool `catalog`: `match_products` (semantico + fuzzy + storico + unità), `search_catalog`, `ask_product_sheets` con citazioni | FN-07, 21 | P2 | T-06 | | ☐ |
| 6 | T-45 | Tool `inventory_pricing`: `check_availability` (sostituti), `get_prices`, `get_delivery_options` (cut-off, giorni serviti) | FN-09, 10 | P2 | T-04 | | ☐ |
| 7 | T-46 | Tool `orders`: draft/update/confirm (idempotente)/cancel/status/issue + macchina a stati ordine e righe | FN-12, 16, 17, 18 | P2 | T-03, T-07 | | ☐ |
| 8 | T-47 | Logica conversazionale ordine: chiarimenti raggruppati, sostituti, vincoli, riepilogo, conferma, promemoria e scadenza bozza | FN-08, 09, 12 | P2 | T-43…T-46, T-25 | | ☐ |
| 9 | T-48 | Primo contatto: informativa e consenso proattivo | FN-02 | P2 | T-41 | | ☐ |
| 10 | T-49 | `handoff_to_human` e gestione `mode = HUMAN` / release | FN-24 | P2 | T-41, T-21 | | ☐ |
| 11 | T-53 | Eval runner + metriche (lettura righe, matching, intento, n. scambi) con **AgentCore Evaluations** (on-demand + evaluator custom) e dataset di progetto; report — avvio in P2, report finale in P4 | FN-04, 05, 07 | P2–P4 | T-05 | | ☐ |
| 12 | T-50 | Tool `reco` + politica suggerimenti (max 1, consenso, motivazione) | FN-11, 20 | P3 | T-08 | | ☐ |
| 13 | T-51 | Tool `sales`: briefing, agenda, ordine per conto del cliente (solo portafoglio) | FN-20, 22, 23 | P3 | T-42, T-50 | | ☐ |
| 14 | T-52 | Turno proattivo di riordino (template, pulsanti, cooldown) | FN-19 | P3 | T-08, T-24 | | ☐ |

### CO – Console & Analytics

| # | ID | Task | FN | Fase | Dipende da | Owner | Stato |
|---|---|---|---|---|---|---|---|
| 1 | T-60 | `ConsoleStack`: Cognito (gruppi `backoffice`, `sales_rep`, `judge`), API REST + WebSocket, S3 + CloudFront (OAC) + WAF | FN-28, 32 | P1 | T-03 | | ☐ |
| 2 | T-61 | Scaffold console React + Vite + TS: auth, layout, brand (`assets/brand/`) | FN-28 | P1 | T-60 | | ☐ |
| 3 | T-62 | Inbox ordini + dettaglio con **immagine del bigliettino affiancata alle righe** e correzione righe (parte con dati mock, poi API reali) | FN-28 | P2 | T-46 | | ☐ |
| 4 | T-63 | Conversazioni live (`broadcaster`) + azioni *Take over / Reply / Release* (`console_api`) | FN-24, 28 | P2–P3 | T-49 | | ☐ |
| 5 | T-64 | Chat web agenti di commercio (`rep_chat` + UI con streaming) | FN-29 | P3 | T-41, T-60 | | ☐ |
| 6 | T-65 | Dashboard KPI (viste Athena) con confronto baseline | FN-30 | P3 | T-09 | | ☐ |
| 7 | T-66 | Ruolo `judge` in sola lettura, rifiniture demo | FN-31 | P4 | T-62 | | ☐ |

## 4. Suggerimento di assegnazione

| Stream | Persone | Primi task |
|---|---|---|
| IN | 1 | T-01 → T-03 → T-04 (con il cliente) → T-06; T-11 in parallelo appena possibile |
| CH | 1 | T-28 subito, poi T-20 → T-21 → T-23 → T-22 → T-24 |
| AG | 1–2 | T-42 (su dati seed) → T-40 → T-41; in parallelo prototipo di T-43 su bigliettini reali |
| CO | 1 | T-60 → T-61 con dati mock, poi T-62 |

Ogni stream lavora in un **git worktree** separato (`claude -w <nome>`) con una propria sessione di Claude Code (vedi [HANDOFF_CLAUDE_CODE.md](./HANDOFF_CLAUDE_CODE.md)).
