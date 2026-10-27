# SuppliAgent – Backlog e piano di lavoro

> Stato: **v0.2** · Aggiornato il 23/10/2026 (ri-ordinato sul calendario reale, perimetro invariato)
> Contiene **solo il lavoro da fare**, con la descrizione completa di ogni task (anche di quelli non ancora assegnati). **Assegnazione alle sessioni, ordine e dipendenze tra sessioni: [START_HERE §3bis](../START_HERE.md)** (fonte unica). A task completato, nella stessa PR: la riga si rimuove da qui, il task va in [DONE.md](./DONE.md) e diventa ✅ in START_HERE §3bis. Una dipendenza `T-xx` che non compare più qui è completata.
> Riferimenti: [03 – Specifica funzionale](./03_FUNCTIONAL_SPEC.md) · [02 – Flussi tecnici](./02_TECHNICAL_FLOWS.md) · [Infrastructure Design](./INFRASTRUCTURE_DESIGN.md)

---

## 1. Milestone

| Fase | Periodo | Obiettivo | Uscita verificabile |
|---|---|---|---|
| **P0 – Fondamenta** | **23/10** | Monorepo, CI, CDK skeleton, avvio dati di prova e canali | `cdk synth` verde in CI; template WhatsApp inviati a Meta |
| **P1 – Walking skeleton** | 23–24/10 | Un messaggio WhatsApp attraversa tutta la pipeline e riceve risposta dall'agente | "ciao" su WhatsApp → risposta dell'agente via Notifier, con debounce, in `dev` |
| **P2 – Ordine da foto end-to-end** | 24–25/10 | Scenario S1 completo | S1 eseguibile in `dev` dall'inizio alla fine |
| **P3 – Copilota, proattività, consegne, console** | 25–26/10 | Scenari S2–S7, console operativa | S3, S5, S6 eseguibili; console con inbox ordini e handoff |
| **Code freeze** | **27/10 ore 18:00** | Solo bugfix dopo questa data | – |
| **P4 – Hardening e materiali** | 27–28/10 | Eval, ambiente `demo`, README, video, submission | Submission inviata **entro le 15:00 del 28/10** (scadenza 21:00) |

Percorso critico: **T-04 dati** → T-20/T-21/T-22 ingestion → T-40/T-41 agente → T-43 lettura → T-44 matching → T-45/T-46/T-47 ordine → T-07 ERP/PDF → T-24/T-26/T-27 conferme → T-10/T-12 demo e video.


## 1bis. Perimetro per un team di una persona (deciso il 24/10)

Le fasi P1–P3 sono riordinate per priorità; sessioni e calendario in [START_HERE §3bis](../START_HERE.md).

| Priorità | Quando | Task |
|---|---|---|
| **Must** – S1 end-to-end | Sab–Dom | T-04 (dati sintetici), T-22, T-24 (base), **T-14**, T-42, T-40, T-41, T-43, T-06, T-44, T-45, T-46, T-47, T-07, T-26 (solo email conferma con PDF), T-60, T-61, T-62 |
| **Should** – rifinitura | Lun–Mar | WhatsApp reale e template approvati (**T-29**), T-25, T-49, T-54 (Memory, Guardrail), T-63, T-48, T-05 + T-53 (eval leggera), T-10, T-11, T-12 |
| **Could** – solo se avanza tempo, altrimenti nel video/slide | – | T-27 (RCS), T-24 completo (fallback RCS→SMS), T-08, T-50, T-51, T-52, T-64, T-09, T-65 |

**PR accorpate** (deciso il 26/10): i task che toccano lo stesso stack e non sono testabili da soli vanno in **una sola PR**, con un commit per task; tutti gli altri task = una PR ciascuno.

| Branch / PR | Task | Perché insieme |
|---|---|---|
| `feat/FN-03-agent-runtime` | T-40 + T-41 | il runtime senza agente non è testabile |
| `feat/FN-12-order-flow` | T-45 + T-46 + T-47 | stato ordine e conversazione d'ordine si testano solo insieme |

## 2. Sequenza e assegnazione

Ordine dei task per sessione e dipendenze tra sessioni: [START_HERE §3bis](../START_HERE.md). Le colonne "Dipende da" qui sotto restano la descrizione completa delle dipendenze di ogni task.

## 3. Task (in ordine di esecuzione per stream)

Legenda stato: ☐ da fare · ◐ in corso · ⛔ bloccato (i task fatti sono in [DONE.md](./DONE.md))

### IN – Infra, Dati & Materiali

| # | ID | Task | FN | Fase | Dipende da | Owner | Stato |
|---|---|---|---|---|---|---|---|
| 1 | T-04 | Dati di prova – **resto** (anagrafiche, storico e insight fatti il 26/10, vedi DONE): catalogo anonimizzato/sintetico (sinonimi, unità, multipli; deve contenere gli SKU dello storico), listini, promo, stock con esauriti e sostituti, calendario consegne; `seed/reset.py`. Sessione Agente, con T-06/T-45 | FN-31 | P0–P1 | T-03, dati cliente | MG | ◐ |
| 2 | T-05 | Dataset eval: ≥ 15 bigliettini scritti a mano (grafie diverse), vocali, email d'ordine, conversazioni attese | FN-05, 07 | P1 | T-04 | MG | ☐ |
| 3 | T-06 | `CatalogStack`: S3 Vectors (indice `products`), `catalog_indexer`, Knowledge Base schede tecniche (vector store S3 Vectors) | FN-07, 21 | P1 | T-03, T-04 | MG | ☐ |
| 4 | T-07 | ERP adapter mock (`submit/update/cancel/getStatus`, simulazione pianificazione e consegna) + `order_pdf` + regola EventBridge `order.confirmed` | FN-13, 14 | P2 | T-03 | MG | ☐ |
| 5 | T-09 | `AnalyticsStack`: Firehose → S3 Parquet → Glue → viste Athena KPI; dashboard e allarmi CloudWatch (incluso il target di notifica dell'allarme `suppliagent-<env>-inbound-dlq` creato in T-21) | FN-30, 33 | P2–P3 | T-03 | MG | ☐ |
| 6 | T-08 | `ProactiveStack`: `insights_analyzer` (riordini scaduti, prodotti smessi, gap vs simili), `proactive_trigger`, scheduler | FN-19, 20 | P3 | T-04, T-22 | MG | ☐ |
| 7 | T-10 | Ambiente `demo`, script reset, README sezione giudici, cliente/bigliettino di prova | FN-31 | P4 | tutti | MG | ☐ |
| 8 | T-11 | Opportunità ACE, export PNG del diagramma (aggiornare prima `architecture.drawio`: coda `inbound` standard e niente Lambda Media Fetcher, decisioni T-21/T-23), testi submission (EN), paragrafo WhatsApp | – | P4 (avviabile subito) | – | MG | ☐ |
| 9 | T-12 | Copione e registrazione video (≤ 3 min) | – | P4 (copione da P2) | T-10 | MG | ☐ |

### CH – Canali CDS

| # | ID | Task | FN | Fase | Dipende da | Owner | Stato |
|---|---|---|---|---|---|---|---|
| 2 | T-29 | **Invio dei template WhatsApp a Meta** e approvazione: dopo il collegamento della WABA a EUM Social, invio degli 8 JSON di `services/notifier/whatsapp_templates/` con `aws socialmessaging create-whatsapp-message-template` (comando in [09 §1](./09_CONTENT_AND_TEMPLATES.md)); verifica stato `APPROVED`; se Meta rifiuta o cambia categoria, correzione dei JSON (test verde) e reinvio; aggiornare 09 con l'esito | FN-12, 19 | P1 (appena c'è la WABA) | T-28, WABA collegata (T-20 / azione manuale) | MG | ☐ |
| 6 | T-24 | Completamento del `notifier` (la base — risposte su WhatsApp ed email, sandbox, idempotenza, read receipt — è in DONE): template fuori dalla finestra 24h (F-11.C2, con T-29), fallback di canale e RCS→SMS, fasce orarie, opt-out; dal Router (T-21/T-23): richiesta di reinvio per media non scaricati (E-02) e avviso per allegati rifiutati senza `s3Uri` (E-13); fallimenti di invio: retry ×3 e fallback (E-09) | FN-01, 14, 15 | P2 | T-20 | MG | ☐ |
| 6b | T-67 | Errori del turno nel Dispatcher (E-05, E-12): messaggio di cortesia al cliente al primo errore del Runtime, secondo errore → `handoff_to_human` `LOW_CONFIDENCE` (oggi: solo retry SQS ×3, poi DLQ con i messaggi lasciati nel buffer e nessun avviso); tetto alla lunghezza di `pending` | FN-26, 24 | P2 | T-49 | MG | ☐ |
| 7 | T-25 | Messaggi interattivi WhatsApp (button/list) e parsing delle risposte | FN-08, 12 | P2 | T-24 | MG | ☐ |
| 8 | T-26 | Email: template HTML conferma con PDF allegato; ordini via email (corpo, foto, PDF, Excel; ingresso già nel Router, T-23); F-02.C3 (indirizzo sconosciuto che risponde a `ordine+<id>@`: contatto dall'ordine, associazione in attesa di conferma) | FN-06, 14 | P2 | T-24, T-07 | MG | ☐ |
| 8b | T-14 | **Simulatore canali + test end-to-end**: script che pubblica eventi WhatsApp sintetici (testo, foto, vocale) sul topic SNS di EUM Social e modalità `sandbox` del Notifier che registra le uscite invece di inviarle; permette di testare S1 senza numero WhatsApp e riusarlo per eval e reset demo | FN-31 | P1 | T-21, T-24 | MG | ☐ |
| 9 | T-27 | RCS: **infra EUM SMS v2** (configuration set, event destinations, opt-out list, topic `sms-inbound`, rimasta fuori da T-20) + sottoscrizione del topic alla coda `inbound` e normalizzazione SMS/RCS nel Router (rimaste fuori da T-21) + rich card conferma e consegna con suggested replies; fallback SMS | FN-15, 18 | P2–P3 | T-24 | MG | ☐ |

### AG – Agent & AgentCore

| # | ID | Task | FN | Fase | Dipende da | Owner | Stato |
|---|---|---|---|---|---|---|---|
| 5 | T-44 | Tool `catalog`: `match_products` (semantico + fuzzy + storico + unità), `search_catalog`, `ask_product_sheets` con citazioni | FN-07, 21 | P2 | T-06 | MG | ☐ |
| 6 | T-45 | Tool `inventory_pricing`: `check_availability` (sostituti), `get_prices`, `get_delivery_options` (cut-off, giorni serviti) | FN-09, 10 | P2 | T-04 | MG | ☐ |
| 7 | T-46 | Tool `orders`: draft/update/confirm (idempotente)/cancel/status/issue + macchina a stati ordine e righe; `confirm_order` da pulsante solo se `interactiveReply.contextId` è il messaggio di conferma inviato per quell'ordine (l'id del pulsante si può falsificare) | FN-12, 16, 17, 18 | P2 | T-03, T-07 | MG | ☐ |
| 8 | T-47 | Logica conversazionale ordine: chiarimenti raggruppati, sostituti, vincoli, riepilogo, conferma, promemoria e scadenza bozza | FN-08, 09, 12 | P2 | T-43…T-46, T-25 | MG | ☐ |
| 9 | T-48 | Primo contatto: informativa e consenso proattivo | FN-02 | P2 | T-41 | MG | ☐ |
| 10 | T-49 | `handoff_to_human` e gestione `mode = HUMAN` / release | FN-24 | P2 | T-41, T-22 | MG | ☐ |
| 11 | T-53 | Eval runner + metriche (lettura righe, matching, intento, n. scambi) con **AgentCore Evaluations** (on-demand + evaluator custom) e dataset di progetto; report — avvio in P2, report finale in P4; **inoltre**: ≥ 15 bigliettini e miglioramento della lettura del corsivo (T-43: 62% su 3 note con Nova Pro, `agent/evals/README.md`; da provare altri modelli o pre-elaborazione) | FN-04, 05, 07 | P2–P4 | T-05 | MG | ☐ |
| 11b | T-54 | Completamento dell'agente dopo la versione ridotta di T-40/T-41: AgentCore Memory (`actorId = contactId`, storico e preferenze al posto della memoria di sessione), Bedrock Guardrail (PII, topic negati), prompt e set di tool `sales_rep` completi, Observability/OTel (`aws-opentelemetry-distro`), retention e CMK del log group del Runtime, verifica multilingua con gli eval; testo e allegati dei messaggi passati al modello come **contenuto non fidato** (delimitato), mai come istruzioni (revisione T-21/T-23); se c'è tempo, hardening dai rilievi di T-40/T-41 (INFRASTRUCTURE_DESIGN §12) | FN-03, 04, 25, 27, 32 | P2 | T-40, T-41 | MG | ☐ |
| 12 | T-50 | Tool `reco` + politica suggerimenti (max 1, consenso, motivazione) | FN-11, 20 | P3 | T-08 | MG | ☐ |
| 13 | T-51 | Tool `sales`: briefing, agenda, ordine per conto del cliente (solo portafoglio) | FN-20, 22, 23 | P3 | T-42, T-50 | MG | ☐ |
| 14 | T-52 | Turno proattivo di riordino (template, pulsanti, cooldown) | FN-19 | P3 | T-08, T-24 | MG | ☐ |

### CO – Console & Analytics

| # | ID | Task | FN | Fase | Dipende da | Owner | Stato |
|---|---|---|---|---|---|---|---|
| 1 | T-62 | **Collegare a API reali** inbox e dettaglio ordine (UI con mock già fatta, vedi DONE): `VITE_ORDERS_SOURCE=api`, `PATCH` correzione riga in `console_api` (oggi `correctLine` lancia errore), `customerName`/`uncertainLines`/`handoff` nel riepilogo, nome prodotto sulla riga, `imageS3Uri` | FN-28 | P2 | T-46 | MG | ☐ |
| 2 | T-63 | Conversazioni live (`broadcaster`) + azioni *Take over / Reply / Release* (`console_api`) | FN-24, 28 | P2–P3 | T-49 | MG | ☐ |
| 3 | T-64 | Chat web agenti di commercio (`rep_chat` + UI con streaming; `NormalizedMessage` con `channel = WEB`) | FN-29 | P3 | T-41, T-60 | MG | ☐ |
| 4 | T-65 | Dashboard KPI (viste Athena) con confronto baseline | FN-30 | P3 | T-09 | MG | ☐ |

## 4. Assegnazione

Vedi [START_HERE §3bis](../START_HERE.md): ogni sessione Claude Code lavora in un **git worktree** separato (`claude -w <nome>`). Lo stream nelle tabelle sopra (IN, CH, AG, CO) indica l'area, non la sessione.
