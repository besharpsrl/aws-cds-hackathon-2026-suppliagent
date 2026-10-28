# SuppliAgent – Specifica funzionale

> AWS CDS Agentic AI Partner Hackathon · Team beSharp
> Stato: **v1.0 – allineato alla submission** (T-72: solo le funzionalità della gara) · Data: 28/10/2026
> Documenti collegati: [01 – Panoramica](./01_PROJECT_OVERVIEW.md) · [02 – Flussi tecnici](./02_TECHNICAL_FLOWS.md) · [Infrastructure Design](./INFRASTRUCTURE_DESIGN.md)

---

## 1. Scopo e convenzioni

Elenco completo delle funzionalità di SuppliAgent, con priorità, criteri di accettazione e stream responsabile: base per **validare il perimetro** e **dividere il lavoro**.

**Priorità (MoSCoW, scadenza 28/10 ore 21:00)**: **M** Must · **S** Should · **C** Could · **W** Won't.
**Stream**: **AG** Agent & AgentCore · **CH** Canali CDS · **CO** Console & Analytics · **IN** Infra, Dati & Materiali.
**Criteri di gara**: TE (Technical Execution 40%), VI (Value/Impact 20%), DP (Demo 20%), CR (Creativity 10%), FU (Functionality 10%), WA (premio WhatsApp).

## 2. Personas

| Persona | Descrizione | Obiettivo |
|---|---|---|
| **Marco, titolare di trattoria** | Scrive l'ordine a mano a fine servizio e lo manda in foto su WhatsApp | Ordinare in 30 secondi, senza errori, sapendo quando arriva |
| **Sara, chef di pizzeria** | Ordina con vocali mentre lavora | Dettare l'ordine e confermare con un tap |
| **Luca, agente di commercio** | 60 clienti, sempre in auto o in visita | Sapere cosa proporre a ogni cliente, rispondere subito su allergeni e formati |
| **Elena, back office** | Inserisce e controlla gli ordini | Occuparsi solo delle eccezioni, con tutto il contesto davanti |
| **Giudice AWS** | Pochi minuti per valutare | Ordinare da sé e capire subito architettura e impatto |

## 3. Journey principali

| # | Journey | Funzionalità |
|---|---|---|
| J1 | Marco manda la foto del bigliettino + un vocale, chiarisce una riga, accetta un sostituto, conferma; riceve email con PDF e SMS | FN-01, 03, 05–15, 26 |
| J2 | Sara detta l'ordine con un vocale e lo modifica prima del cut-off | FN-06, 16 |
| J3 | Il giorno di consegna Marco riceve l'RCS e segnala un cartone danneggiato con una foto | FN-18 |
| J4 | Una settimana dopo Marco riceve la proposta di riordino e conferma con un tap | FN-19 |
| J5 | Luca chiede su WhatsApp cosa proporre alla trattoria di Marco e se la burrata contiene lattosio | FN-20, 21 |
| J6 | Luca fotografa in visita il bigliettino di un cliente e inserisce l'ordine per lui | FN-22 |
| J7 | Elena vede in console un ordine con una riga non risolta, subentra nella chat e la risolve | FN-24, 28 |
| J8 | Il giudice ordina dal numero WhatsApp di demo e guarda il proprio ordine in console | FN-28, 31 |

## 4. Catalogo delle funzionalità

### 4.1 Tabella riassuntiva

> **Gara**: stato nel perimetro dell'hackathon (✅ fatto · ◐ nel perimetro, task aperto · ⬜ escluso dalla gara). Le priorità restano la visione di prodotto; perimetro e task in [`START_HERE.md`](../START_HERE.md) §4.

| ID | Funzionalità | Priorità | Stream | Criteri | Flusso | Gara |
|---|---|---|---|---|---|---|
| FN-01 | Messaggistica multicanale bidirezionale (WhatsApp, email, RCS/SMS) | M | CH | TE, FU, WA | §3, F-11 | ◐ T-68, T-26, T-27 |
| FN-02 | Primo contatto, informativa e consenso proattivo | M | AG | VI | F-01 | ✅ T-48 (il blocco dei proattivi senza consenso lo applica T-52) |
| FN-03 | Identificazione contatto e ruolo (cliente / agente di commercio) | M | AG | FU | F-02 | ✅ |
| FN-04 | Comprensione dell'intento | M | AG | FU | F-03 | ✅ |
| FN-05 | **Ordine da foto di bigliettino scritto a mano** | M | AG | CR, DP, WA | F-04 | ✅ |
| FN-06 | Ordine da vocale, testo ed email | M | AG + CH | TE, FU | F-04 | ◐ email testo e foto ✅ T-26b (da provare su `dev`); allegati PDF/Excel no |
| FN-07 | Abbinamento al catalogo con storico del cliente | M | AG | TE, VI | F-05 | ✅ |
| FN-08 | Chiarimenti con pulsanti interattivi | M | AG + CH | DP, WA | F-05 | ✅ T-25 (pulsanti per una domanda alla volta; più domande in un messaggio: opzioni numerate nel testo) |
| FN-09 | Disponibilità, sostituti, multipli e minimi | M | AG | VI | F-06 | ✅ |
| FN-10 | Data di consegna e cut-off | M | AG | FU | F-06 | ✅ |
| FN-11 | Suggerimento contestuale (max 1 per ordine) | S | AG | VI, CR | F-07 | ✓ T-50 |
| FN-12 | Riepilogo e conferma esplicita | M | AG | FU | F-07 | ✅ |
| FN-13 | ERP adapter (mock) e numero d'ordine | M | IN | TE | F-07 | ✅ |
| FN-14 | Email di conferma con PDF | M | CH | TE | F-07, F-11 | ✅ T-26 (da provare su `dev`) |
| FN-15 | Conferma SMS/RCS | M | CH | TE | F-07, F-11 | ◐ T-27 |
| FN-16 | Modifica e annullamento ordine | S | AG | FU | F-08 | ✅ |
| FN-17 | Stato ordine e consegna | S | AG | VI | F-09 | ✅ |
| FN-18 | Avvisi di consegna RCS e segnalazione problemi | S | CH + AG | TE, CR | F-11, F-12 | ◐ T-27 |
| FN-19 | **Riordino proattivo** | M | AG + IN | CR, VI, DP | F-13 | ◐ T-08, T-52 |
| FN-20 | Copilota: consigli e briefing cliente | M | AG | VI, CR | F-10.A | ◐ T-50, T-51 |
| FN-21 | Copilota: catalogo e schede tecniche (Knowledge Base) | M | AG + IN | TE | F-10.B | ◐ T-06b, T-44b |
| FN-22 | Copilota: ordine per conto del cliente | S | AG | VI | F-10.D | ◐ T-51 |
| FN-23 | Copilota: agenda e briefing giornaliero | C | AG + CH | VI | F-10.C, F-10.E | ◐ T-51 |
| FN-24 | Handoff verso back office | M | AG + CO | VI, FU | F-14 | ◐ T-63 ✓, T-54 |
| FN-25 | Continuità cross-canale | M | AG | CR, TE | F-15 | ◐ T-54 |
| FN-26 | Raggruppamento messaggi ravvicinati (risposta unica) | M | CH | FU, DP | §3.3 | ✅ |
| FN-27 | Multilingua (IT/EN) | M | AG | FU, DP | – | ◐ T-54 |
| FN-28 | Console back office in tempo reale | M | CO | DP, VI | – | ◐ T-62 ✓, T-63 ✓ (polling 2 s, senza WebSocket) |
| FN-29 | Chat web per agenti di commercio | S | CO | TE | F-10 | ◐ T-64 |
| FN-30 | Dashboard KPI di impatto | W | – | – | – | tolta il 27/10 (T-65) |
| FN-31 | Accesso giudici e ambiente della demo (`dev`) | M | IN + CO | FU | – | ◐ T-10 |
| FN-32 | Sicurezza, privacy e autorizzazione per ruolo | M | IN + AG | TE | – | ✅ |
| FN-33 | Osservabilità ed eventi | S | IN | TE | §6.4 | ◐ eventi su EventBridge, AgentCore Observability (T-54), allarmi CloudWatch; niente Athena (T-09 tolto) |
| FN-34 | Integrazione con l'ERP reale | W | – | – | – | – |
| FN-35 | Pagamenti, fatturazione, fidi | W | – | – | – | – |

### 4.2 Schede di dettaglio

---

#### FN-01 – Messaggistica multicanale · **M** · CH
- [ ] WhatsApp (testo, immagine, audio, documento, risposte a pulsanti e liste) arriva all'agente come `NormalizedMessage`.
- [ ] Email (corpo e allegati) arriva normalizzata; Reply-To `ordine+<id>@` correlato all'ordine.
- [x] Risposte SMS e tap RCS arrivano come messaggi del contatto (T-27).
- [x] Il codice chiama `SendWhatsAppMessage`, `sesv2.SendEmail`, `SendRcsMessage`, `SendTextMessage` (requisito di gara; verificato da `tests/test_cds_usage.py`).
- [ ] Eventi di consegna/lettura registrati per ogni invio.

#### FN-02 – Primo contatto e consenso · **M** · AG
- [ ] L'agente si dichiara assistente virtuale del Distributore.
- [ ] Informativa inviata al primo contatto senza bloccare un ordine in corso.
- [ ] Consenso alle comunicazioni proattive registrato (data, canale, versione); senza consenso nessun messaggio proattivo.

#### FN-03 – Identificazione contatto e ruolo · **M** · AG
- [ ] Numeri noti riconosciuti senza domande, con ruolo corretto.
- [ ] Contatto nuovo identificato con nome locale + codice cliente/P.IVA; ordini di contatti non verificati restano in bozza fino alla verifica.
- [ ] Clienti di prova dei giudici (`autoVerifyContacts`): chi si identifica col loro codice è verificato subito e può ordinare; per gli altri clienti il contatto resta da verificare (F-02.C7).
- [ ] Contatto con più locali: l'agente chiede per quale locale.
- [ ] Un agente di commercio vede solo i clienti del suo portafoglio (verificato nel tool).

#### FN-04 – Comprensione dell'intento · **M** · AG
- [ ] Su un set di test di ≥ 40 messaggi (clienti + agenti), intento corretto ≥ 90%.
- [ ] Con una bozza aperta, nuove righe → domanda "aggiungo all'ordine in corso?".

#### FN-05 – Ordine da foto di bigliettino · **M** · AG
- [ ] Su un set di ≥ 15 bigliettini di test (scritture diverse), **≥ 90% delle righe lette correttamente**.
- [ ] Abbreviazioni e unità comuni gestite ("cs", "ct", "kg", "pz", "fdl", "EVO").
- [ ] Righe illeggibili segnalate con domanda mirata; in console la riga è mostrata accanto al ritaglio dell'immagine.
- [ ] Più foto inviate insieme producono una sola bozza.

#### FN-06 – Ordine da vocale, testo ed email · **M** · AG + CH
- [ ] Un vocale in italiano viene trascritto e trasformato in righe.
- [ ] Un vocale successivo a una foto può aggiungere/togliere righe.
- [ ] Un'email con elenco nel corpo o in allegato (foto, PDF, Excel) produce una bozza e la conferma arriva via email.
- [ ] "Come l'ultima volta" crea una bozza dall'ultimo ordine.

#### FN-07 – Abbinamento al catalogo · **M** · AG
- [ ] Sul set di test, **≥ 85% delle righe abbinate automaticamente** e **≥ 98% di correttezza** sulle righe abbinate automaticamente.
- [ ] "Il solito X" risolto dallo storico del cliente.
- [ ] Tra candidati simili, quello già acquistato dal cliente è proposto per primo.
- [ ] Latenza del matching ≤ 2 s per un ordine di 15 righe.

#### FN-08 – Chiarimenti con pulsanti · **M** · AG + CH
- [ ] Righe incerte proposte con max 3 opzioni + "Altro", raggruppate in un solo messaggio quando possibile.
- [ ] Le risposte a testo libero ("il primo", "quello da 1 kg") vengono interpretate.
- [ ] Il cliente non riceve mai più di 5 domande in un messaggio.

#### FN-09 – Disponibilità, sostituti, multipli e minimi · **M** · AG
- [ ] Prodotto non disponibile → sostituto proposto con motivazione, oppure esclusione/attesa.
- [ ] Quantità non multipla della confezione → proposta di arrotondamento.
- [ ] Ordine sotto il minimo → indicazione di quanto manca.

#### FN-10 – Data di consegna e cut-off · **M** · AG
- [ ] Data di consegna calcolata da zona, giorni serviti e cut-off.
- [ ] Ordine dopo il cut-off → nuova data proposta e confermata dal cliente.

#### FN-11 – Suggerimento contestuale · **S** · AG
- [x] Al massimo 1 suggerimento per ordine, solo con consenso, sempre motivato ("di solito lo ordini", "in promozione questa settimana") (T-50, `recommend_products`).
- [x] Rifiuto registrato; nessuna insistenza (T-50: escluso per 30 giorni).
- [x] Valore dei suggerimenti accettati tracciato per i KPI (T-50: `Orders.suggestion.value`, evento `order.suggestion`).

#### FN-12 – Riepilogo e conferma esplicita · **M** · AG
- [ ] Nessun ordine inviato senza tap/risposta di conferma.
- [ ] Riepilogo con righe, sostituti, data di consegna, note (e totale stimato se abilitato).
- [ ] Bozza non confermata: promemoria a 2h, scadenza a fine giornata.
- [ ] Doppio tap → un solo ordine (idempotenza).

#### FN-13 – ERP adapter (mock) · **M** · IN
- [ ] Interfaccia `submitOrder / updateOrder / cancelOrder / getOrderStatus` documentata.
- [ ] Implementazione mock che restituisce numero d'ordine e simula pianificazione e consegna.
- [ ] ERP non disponibile → retry e cliente informato della presa in carico.

#### FN-14 – Email di conferma con PDF · **M** · CH
- [x] Inviata entro 1 minuto dalla conferma, con PDF dell'ordine (righe, quantità, data consegna, note).
- [x] Rendering corretto su mobile e desktop; bounce gestito.
- [x] Se il contatto non ha un'email, l'assistente la chiede nel riepilogo (facoltativa) e la salva sul contatto, solo per le conferme d'ordine (T-26, F-07.C7).

#### FN-15 – Conferma SMS/RCS · **M** · CH
- [x] Messaggio breve con numero d'ordine e data di consegna; RCS con branding su device tester, SMS altrimenti (T-27: al contatto con identità `SMS#` verificata, una volta per revisione dell'ordine).

#### FN-16 – Modifica e annullamento · **S** · AG
- [ ] Modifiche libere fino alla conferma; dopo la conferma consentite entro il cut-off con nuova conferma email/SMS.
- [ ] Oltre il cut-off → handoff `ORDER_LOCKED`.

#### FN-17 – Stato ordine · **S** · AG
- [ ] "Quando arriva?" restituisce stato, data e fascia di consegna degli ordini aperti.

#### FN-18 – Avvisi di consegna e problemi · **S** · CH + AG
- [x] RCS il giorno di consegna con fascia oraria e pulsanti *Ricevuto / Segnala problema* (fallback SMS) (T-27; senza identità `SMS#`: template WhatsApp, T-52).
- [ ] Segnalazione con tipo, righe e foto → visibile in console con priorità.

#### FN-19 – Riordino proattivo · **M** · AG + IN
- [ ] L'analisi notturna individua i riordini scaduti sui dati di prova (scenario demo deterministico).
- [ ] Proposta via template con *Riordina uguale / Modifica / No grazie*; "Riordina uguale" porta al riepilogo in un solo passaggio.
- [ ] Max 1 proposta ogni 7 giorni per cliente; nessuna in fascia notturna né senza consenso.
- [ ] Conversione delle proposte tracciata.

#### FN-20 – Copilota: consigli e briefing · **M** · AG
- [x] "Cosa propongo al cliente X?" → 3 proposte motivate (riordini scaduti, prodotti smessi, gap vs locali simili, promo) (T-50, `recommend_products` con `customerId`).
- [ ] Il briefing include ultimi ordini, trend e problemi aperti.
- [ ] Cliente fuori portafoglio → rifiuto.

#### FN-21 – Copilota: catalogo e schede tecniche · **M** · AG + IN
- [ ] Risposte su allergeni, ingredienti, conservazione e formati **con citazione della scheda**.
- [ ] Se l'informazione non è presente nelle schede, l'agente lo dice esplicitamente (test con domande senza risposta).
- [ ] Disponibile anche ai clienti, senza informazioni interne.

#### FN-22 – Copilota: ordine per conto del cliente · **S** · AG
- [ ] L'agente di commercio inserisce un ordine da foto/testo per un cliente del suo portafoglio; i chiarimenti arrivano a lui.
- [ ] Il ristoratore riceve email/SMS di conferma; l'ordine riporta `createdBy = repId`.

#### FN-23 – Copilota: agenda e briefing giornaliero · **C** · AG + CH
- [ ] "Chi vedo domani?" con priorità; email/WhatsApp mattutino con le visite del giorno.

#### FN-24 – Handoff · **M** · AG + CO
- [ ] Richiesta di un operatore → handoff entro il turno successivo, con riassunto e motivo in console.
- [ ] Durante `HUMAN` l'agente tace; le risposte del back office arrivano sul canale del contatto.
- [ ] Dopo *Release* l'agente riprende con il contesto completo.

#### FN-25 – Continuità cross-canale · **M** · AG
- [ ] Ordine iniziato su WhatsApp e confermato rispondendo all'email senza ripetere nulla.
- [ ] Tap RCS di consegna collegato all'ordine corretto.
- [ ] Console con conversazione unificata e icona del canale per ogni messaggio.

#### FN-26 – Raggruppamento messaggi ravvicinati · **M** · CH
- [ ] Foto + vocale + testo inviati in 5 s → **una sola** risposta.
- [ ] Messaggi arrivati durante una risposta → un unico turno successivo.
- [ ] Due clienti in contemporanea → risposte indipendenti senza ritardi reciproci.

#### FN-27 – Multilingua · **M** · AG
- [ ] Contatto che scrive in inglese → risposte, email e notifiche in inglese; preferenza memorizzata.
- [ ] Scenari demo eseguibili in inglese (lingua dei giudici).

#### FN-28 – Console back office · **M** · CO
- [ ] Inbox ordini con filtri (stato, righe incerte, problemi, handoff), aggiornata entro 2 s.
- [ ] Dettaglio ordine con **immagine originale del bigliettino affiancata alle righe** e correzioni evidenziate.
- [ ] Conversazioni live, problemi di consegna, scheda cliente.
- [ ] Azioni *Take over / Reply / Release*, correzione righe; ruolo `judge` in sola lettura.

#### FN-29 – Chat web per agenti di commercio · **S** · CO
- [ ] Login `sales_rep`, chat con risposte in streaming, stesse capacità del copilota WhatsApp, cronologia condivisa.

#### FN-30 – Dashboard KPI · **W**
Tolta dal perimetro della gara il 27/10 (T-09 `AnalyticsStack`, T-65 dashboard): gli eventi di 02 §6.4 restano su EventBridge.

#### FN-31 – Accesso giudici e ambiente della demo (`dev`) · **M** · IN + CO
- [ ] README con numero WhatsApp, email ordini, credenziali console `judge`, **cliente di prova e bigliettino di esempio** scaricabile.
- [ ] Script di reset dei dati demo.
- [ ] Ambiente attivo e gratuito per i giudici fino al 12/11/2026.

#### FN-32 – Sicurezza, privacy, autorizzazione · **M** · IN + AG
- [ ] Autorizzazione per ruolo **nei tool** (cliente → solo propri dati; agente → solo portafoglio); test negativi dedicati.
- [ ] Guardrails su input e output; nessuna promessa di sconti o condizioni non a listino.
- [ ] Log senza contenuti né PII; KMS, IAM minimo, cdk-nag pulito.
- [ ] **Dati del cliente anonimizzati**; nessun dato personale reale.

#### FN-33 – Osservabilità ed eventi · **S** · IN + CO
- [ ] Eventi di 02 §6.4 pubblicati su EventBridge; tracce AgentCore per turno; allarmi su DLQ, Notifier, ERP adapter.

## 5. Requisiti non funzionali

| ID | Requisito | Target |
|---|---|---|
| NFR-01 | Latenza prima risposta a un ordine da foto (dopo il debounce) | p50 ≤ 8 s, p95 ≤ 20 s |
| NFR-02 | Latenza risposte conversazionali semplici | p50 ≤ 4 s |
| NFR-03 | Scalabilità | Chat indipendenti in parallelo; nessuna capacità fissa |
| NFR-04 | Residenza dati | `eu-west-1`, modelli Bedrock solo con profilo `eu.` (Amazon Nova) |
| NFR-05 | Riproducibilità | Deploy da zero con README + `cdk deploy --all` |
| NFR-06 | Costi | Entro crediti + budget interno, alert 25/50/80% |
| NFR-07 | Tono | Cordiale, conciso, professionale; messaggi brevi adatti a chi lavora in cucina |
| NFR-08 | Affidabilità degli ordini | Nessun ordine duplicato o perso (idempotenza, DLQ, retry) |

## 6. Fuori perimetro (Won't)

- Integrazione con l'ERP reale (FN-34), pagamenti, fatturazione, fidi (FN-35).
- Dashboard KPI e analytics su Athena (FN-30, parte Firehose/Athena di FN-33).
- Pianificazione logistica reale, tracking GPS dei mezzi.
- App mobile dedicata.

## 7. Mappa funzionalità → stream (base per la divisione del lavoro)

| Stream | Must | Should | Could |
|---|---|---|---|
| **AG – Agent & AgentCore** | FN-02, 03, 04, 05, 06 (logica), 07, 08 (logica), 09, 10, 12, 19 (turno proattivo), 20, 21 (prompt), 24 (logica), 25, 27, 32 (guardrail) | FN-11, 16, 17, 18 (logica), 22 | FN-23 |
| **CH – Canali CDS** | FN-01, 06 (email), 08 (interactive), 14, 15, 26 | FN-18 (RCS) | FN-23 (email) |
| **CO – Console** | FN-24 (UI), 28, 31 (console) | FN-29 | – |
| **IN – Infra, Dati & Materiali** | FN-13, 19 (analyzer), 21 (KB + indice), 31 (ambiente, README), 32 (infra) | FN-33 (infra) | – |

### Dipendenze principali
- **Catalogo anonimizzato e storico ordini di prova** (IN) sbloccano FN-07, 09, 11, 19, 20: **prima priorità della settimana**.
- FN-01 + FN-26 bloccanti per tutti i flussi end-to-end.
- Catena demo: FN-05 → FN-07 → FN-08 → FN-09/10 → FN-12 → FN-13 → FN-14/15.
- FN-28 può partire subito con dati mock.

## 8. Scenari demo di riferimento (test di accettazione end-to-end)

| # | Scenario | Funzionalità verificate |
|---|---|---|
| S1 | Foto bigliettino (12 righe, 2 incerte, 1 illeggibile) + vocale "aggiungi 2 kg di burro", 1 prodotto esaurito con sostituto, suggerimento accettato, conferma → email PDF + RCS | FN-01, 05–15, 26 |
| S2 | Vocale in inglese da chef, ordine dopo il cut-off | FN-06, 10, 27 |
| S3 | Agente di commercio: "cosa propongo alla Trattoria X?" + domanda su allergeni della burrata | FN-20, 21 |
| S4 | Agente di commercio inserisce l'ordine di un cliente da foto | FN-22 |
| S5 | Proposta di riordino proattiva → "Riordina uguale" | FN-19 |
| S6 | Consegna con RCS → "Segnala problema" con foto → back office subentra | FN-18, 24, 28 |
| S7 | Ordine via email (testo o foto), conferma via email | FN-06, 14 |

## 9. Domande aperte

Domande aperte e decisioni prese sono in [`START_HERE.md`](../START_HERE.md) §6 (fonte unica).
