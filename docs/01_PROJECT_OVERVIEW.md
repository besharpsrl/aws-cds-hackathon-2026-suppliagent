# SuppliAgent – Panoramica e concept

> AWS CDS Agentic AI Partner Hackathon · Team beSharp
> Stato: **v1.1 – allineato alla submission** · Data: 28/10/2026 · Caso d'uso di un **cliente reale di beSharp** (il "Distributore")
> Documenti collegati: [02 – Flussi tecnici](./02_TECHNICAL_FLOWS.md) · [03 – Specifica funzionale](./03_FUNCTIONAL_SPEC.md) · [Infrastructure design](./INFRASTRUCTURE_DESIGN.md) · [Diagramma](./architecture.drawio)

---

## 1. Scopo del documento

Unico documento di visione: cosa fa SuppliAgent, chi lo usa, come è fatto, come si comporta nei casi principali, come si misura e come risponde ai criteri di gara (dal 28/10 include l'ex `SUPPLIAGENT_SOLUTION.md`).

## 2. Il problema

Il caso d'uso nasce da un **cliente reale di beSharp**: un distributore di prodotti alimentari per la ristorazione (HoReCa), di seguito "il Distributore".

| Problema | Effetto |
|---|---|
| Gli ordini arrivano in modo informale: foto di bigliettini scritti a mano, vocali, messaggi agli agenti di commercio | Inserimento manuale lento, errori di trascrizione, ordini dimenticati |
| Abbreviazioni, nomi generici, "il solito" | Prodotti sbagliati, resi, rettifiche telefoniche |
| Disponibilità e cut-off verificati a posteriori | Consegne incomplete o in ritardo |
| Agenti di commercio con catalogo vasto e poco tempo | Opportunità perse, risposte lente su schede tecniche e allergeni |
| Nessun presidio sui riordini mancati | Clienti che passano alla concorrenza senza che nessuno se ne accorga |

## 3. La soluzione in breve

**SuppliAgent** è un **agente AI multicanale** al servizio di due tipi di utente:

**Il ristoratore (cliente)**
1. Ordina su **WhatsApp** come fa oggi: **foto del bigliettino**, vocale o testo (oppure via email).
2. L'agente legge l'ordine, **riconosce i prodotti nel catalogo** usando lo storico del cliente, verifica **disponibilità, listino, multipli di confezione, cut-off e giorni di consegna**.
3. Chiede chiarimenti **solo sulle righe incerte**, con pulsanti; propone **sostituti** per i prodotti mancanti e al massimo **un suggerimento** pertinente.
4. Il ristoratore **conferma**; arrivano la conferma via **email con PDF** e via **SMS/RCS**, poi gli avvisi di consegna con la possibilità di **segnalare problemi**.
5. Quando un riordino abituale "salta", l'agente **propone di riordinare con un tap**.

**L'agente di commercio (copilota)**
- Chiede "cosa propongo al ristorante X?", informazioni sul catalogo e sulle **schede tecniche**, riceve un **briefing** prima delle visite e può **inserire ordini per conto del cliente** (foto del bigliettino scattata durante la visita), via WhatsApp o chat web.

**Il back office** supervisiona da una **console web**: ordini e righe a bassa confidenza, conversazioni, problemi di consegna, presa in carico.

### KPI e impatto misurabile

| KPI | Come si misura |
|---|---|
| **Tempo di inserimento ordine** | dalla foto alla conferma (vs inserimento manuale) |
| **% righe abbinate automaticamente** | righe confermate senza correzioni / totale |
| **Accuratezza dell'abbinamento** | correzioni del cliente o del back office |
| **% ordini senza intervento umano** | ordini confermati senza handoff |
| **Scontrino medio e suggerimenti accettati** | valore righe aggiunte da suggerimenti |
| **Riordini recuperati** | ordini nati da proposte proattive |
| **Tempo risparmiato dagli agenti** | briefing e risposte su schede tecniche |
| **Problemi di consegna** | segnalazioni / consegne |

## 4. Attori

| Attore | Ruolo | Canale / interfaccia |
|---|---|---|
| **Ristoratore** (titolare, chef, responsabile acquisti) | Ordina, conferma, riceve conferme e avvisi, segnala problemi | WhatsApp, email, RCS/SMS |
| **Agente di commercio** | Usa il copilota, inserisce ordini per conto dei clienti, riceve notifiche sul suo portafoglio | WhatsApp, chat web (console) |
| **Back office / customer service** | Gestisce eccezioni, ordini da verificare, problemi di consegna, handoff | Console web |
| **Agente SuppliAgent** | Conduce le conversazioni, usa i tool, crea e aggiorna gli ordini | AgentCore Runtime |
| **ERP del Distributore** | Riceve gli ordini confermati (simulato nell'hackathon) | ERP adapter (mock) |
| **Giudice hackathon** | Ordina da cliente di prova e consulta la console | WhatsApp, email, console (ruolo `judge`) |

## 5. Perimetro

**Nel perimetro (MVP)**
- Ordini dei ristoranti da foto, vocale, testo, email; chiarimenti, sostituti, suggerimenti, conferma.
- Conferme via email (PDF) e SMS/RCS; avvisi di consegna e segnalazione problemi.
- Riordino proattivo.
- Copilota per agenti di commercio: suggerimenti, catalogo, schede tecniche, briefing, ordini per conto del cliente.
- Console back office (ordini, correzioni, conversazioni, handoff) con chat web per gli agenti.
- Lingue: italiano e inglese.

**Fuori perimetro**
- Integrazione con l'ERP reale (si usa un **adapter mock** con interfaccia documentata).
- Pagamenti, fatturazione, gestione crediti e fidi.
- Logistica e pianificazione dei giri di consegna (simulati).
- Dashboard KPI e analytics (Firehose, Glue, Athena): tolti il 27/10 (T-09, T-65); restano gli eventi su EventBridge e l'osservabilità di AgentCore e CloudWatch.
- Catalogo e prezzi reali non anonimizzati.

**Perimetro della gara**: flussi utente 1–9 con priorità Must/Should/Could ([`START_HERE.md`](../START_HERE.md) §4.3); stato per funzionalità in [03 §4.1](./03_FUNCTIONAL_SPEC.md).

## 6. Architettura ad alto livello

```mermaid
flowchart LR
    subgraph Utenti
        R[Ristoratore]
        A[Agente di commercio]
        BO[Back office]
    end
    subgraph CDS[AWS CDS]
        WA[EUM Social – WhatsApp]
        SES[Amazon SES]
        EUM[EUM SMS/RCS]
    end
    subgraph Core[SuppliAgent – eu-west-1]
        ING[Ingestion & Routing<br/>SQS + debounce]
        AG[Agente<br/>AgentCore + Strands + Amazon Nova eu.]
        TOOLS[Tool di dominio<br/>clienti · catalogo · matching · listini ·<br/>stock · ordini · raccomandazioni]
        CAT[Catalog intelligence<br/>S3 Vectors + Knowledge Base]
        ORD[Ordini, PDF, ERP adapter]
        OUT[Notifier]
        PRO[Proattività<br/>analisi riordini]
        DATA[(DynamoDB + S3)]
    end
    CON[Console web<br/>back office + chat agenti]

    R <--> WA
    R <--> SES
    R <--> EUM
    A <--> WA
    A <--> CON
    BO <--> CON
    WA --> ING
    SES --> ING
    EUM --> ING
    CON --> ING
    ING --> AG
    AG <--> TOOLS
    TOOLS <--> CAT
    TOOLS <--> DATA
    TOOLS --> ORD
    AG --> OUT
    PRO --> AG
    OUT --> WA
    OUT --> SES
    OUT --> EUM
```

| Blocco | Responsabilità | Tecnologie chiave |
|---|---|---|
| Canali | Ricevere e inviare messaggi | EUM Social, SES v2, EUM SMS/RCS v2 |
| Ingestion & Routing | Normalizzare, identificare contatto e **ruolo**, ordinare per chat, raggruppare messaggi ravvicinati | SNS, SQS, Lambda, DynamoDB |
| Agente | Ragionare, leggere i bigliettini, usare i tool, ricordare | AgentCore, Strands, Bedrock Amazon Nova `eu.`, Guardrails, Transcribe |
| Catalog intelligence | Trovare il prodotto giusto da testo impreciso; rispondere sulle schede tecniche | S3 Vectors, Titan Embeddings, Bedrock Knowledge Base |
| Ordini | Ciclo di vita, validazioni, PDF, invio all'ERP | Lambda, EventBridge, ERP adapter |
| Notifier | Unico punto di uscita, scelta del canale | Lambda + client CDS |
| Proattività | Insight clienti e proposte di riordino | EventBridge Scheduler, Lambda |
| Console | Supervisione, handoff, chat agenti | CloudFront, Cognito, API Gateway |

## 7. Flusso principale ad alto livello (con diramazioni)

```mermaid
flowchart TD
    A([Messaggio in arrivo<br/>WhatsApp · email · RCS/SMS · chat web]) --> B[Ricezione, ordine per chat,<br/>raggruppamento messaggi ravvicinati]
    B --> C{Gestione umana<br/>in corso?}
    C -- Sì --> C1[Inoltro alla console]
    C -- No --> D{Chi scrive?}
    D -- Numero/email sconosciuto --> D1[Identificazione:<br/>nome locale + codice cliente/P.IVA]
    D1 --> D2{Riconosciuto?}
    D2 -- No --> H[Handoff back office]
    D2 -- Sì --> E
    D -- Ristoratore --> E{Intento}
    D -- Agente di commercio --> R{Richiesta agente}
    R -- Consigli / briefing --> R1[Suggerimenti motivati<br/>da storico e insight]
    R -- Catalogo / schede tecniche --> R2[Risposta con citazione<br/>della scheda]
    R -- Ordine per un cliente --> O
    E -- Nuovo ordine --> O[Lettura ordine<br/>foto · vocale · testo · email]
    E -- Stato ordine/consegna --> S[Stato e data di consegna]
    E -- Modifica/annullo --> M{Ordine già<br/>inviato all'ERP?}
    M -- No --> M1[Modifica bozza]
    M -- Sì, entro cut-off --> M2[Modifica + nuovo invio]
    M -- Oltre cut-off --> H
    E -- Problema consegna --> P[Raccolta foto e dettagli<br/>→ segnalazione]
    E -- Domande prodotti --> R2
    E -- Chiede operatore --> H
    O --> F[Abbinamento al catalogo<br/>con storico del cliente]
    F --> G{Righe incerte o<br/>non riconosciute?}
    G -- Sì --> G1[Chiarimenti con pulsanti]
    G1 --> I
    G -- No --> I{Disponibilità OK?}
    I -- No --> I1[Proposta sostituto<br/>o consegna parziale]
    I1 --> J
    I -- Sì --> J{Vincoli rispettati?<br/>multipli · minimo · cut-off}
    J -- No --> J1[Proposta di adeguamento<br/>o nuova data]
    J1 --> K
    J -- Sì --> K[Al massimo 1 suggerimento pertinente]
    K --> L[Riepilogo con data di consegna<br/>Confermo / Modifica]
    L --> L2{Conferma?}
    L2 -- Modifica --> F
    L2 -- Nessuna risposta --> L3[Promemoria, poi bozza scaduta]
    L2 -- Confermo --> N[Ordine confermato → ERP<br/>email con PDF + SMS/RCS]
    N --> Q[Avvisi di consegna<br/>Ricevuto / Segnala problema]
```

### Diramazioni principali

| # | Caso | Comportamento | Dettaglio |
|---|---|---|---|
| D1 | Messaggi ravvicinati (foto + vocale + testo) | Attesa fine raffica, **una sola risposta** | 02 §3.3 |
| D2 | Contatto sconosciuto | Identificazione con nome locale + codice cliente o P.IVA | 02 F-02 |
| D3 | Contatto che gestisce più locali | Chiede per quale locale è l'ordine | 02 F-02 |
| D4 | Chi scrive è un agente di commercio | Modalità copilota, tool dedicati | 02 F-10 |
| D5 | Riga incerta (più prodotti possibili) | Domanda con pulsanti, opzioni ordinate per probabilità | 02 F-05 |
| D6 | Riga non riconosciuta | Richiesta di descrizione o foto del prodotto; altrimenti esclusa e segnalata | 02 F-05 |
| D7 | "Il solito …" / "come la settimana scorsa" | Risolto dallo storico ordini del cliente | 02 F-05 |
| D8 | Prodotto non disponibile | Sostituto, consegna parziale o attesa del riassortimento | 02 F-06 |
| D9 | Quantità non multipla della confezione / sotto il minimo | Proposta di arrotondamento o integrazione | 02 F-06 |
| D10 | Ordine dopo il cut-off | Nuova data di consegna proposta | 02 F-06 |
| D11 | Nessuna conferma | Promemoria a 2h; bozza scaduta a fine giornata | 02 F-07 |
| D12 | Modifica/annullo dopo la conferma | Consentito entro il cut-off; oltre → back office | 02 F-08 |
| D13 | Ordine via email | Stessa pipeline; conferma via email | 02 F-04 |
| D14 | Ordine inserito dall'agente di commercio | Conferma dell'agente; notifica al ristoratore | 02 F-10 |
| D15 | Dispositivo senza RCS | Fallback SMS | 02 F-11 |
| D16 | Finestra WhatsApp 24h chiusa | Template approvato | 02 F-11 |
| D17 | Problema alla consegna | Foto + descrizione → segnalazione in console | 02 F-12 |
| D18 | Riordino abituale mancato | Proposta proattiva con un tap (max 1/settimana) | 02 F-13 |
| D19 | Errori tecnici / ERP non disponibile | Retry, fallback, conferma di presa in carico | 02 §5 |
| D20 | Richiesta operatore / frustrazione / caso fuori ambito | Handoff al back office | 02 F-14 |

## 8. Ruolo di ciascun canale

| Canale | Usato per | Perché |
|---|---|---|
| **WhatsApp** | Ordini (foto, vocali, testo), chiarimenti con pulsanti, riordino proattivo, copilota agenti | È già il canale con cui i ristoratori ordinano |
| **Email (SES)** | Conferma d'ordine con PDF, ordini via email, briefing agenti | Documento formale e tracciabile |
| **RCS / SMS** | Conferma breve, avvisi di consegna con pulsanti, proposte per chi non usa WhatsApp | Raggiunge tutti; RCS con branding e pulsanti |
| **Console / chat web** | Back office, chat copilota da PC per gli agenti | Controllo umano |

## 9. Principi di progetto

1. **Il ristoratore non cambia abitudini**: ordina come oggi, su WhatsApp, anche con un bigliettino.
2. **Chiedere poco e solo quando serve**: chiarimenti mirati, con pulsanti.
3. **Nessun ordine senza conferma esplicita**.
4. **Human in the loop**: back office e agenti di commercio vedono e correggono tutto.
5. **Proattività rispettosa**: niente spam, al massimo un suggerimento per ordine e una proposta di riordino a settimana.
6. **Dati in Europa** e **dati del cliente protetti** (anonimizzati per l'hackathon).
7. **Riproducibile e misurabile**.

## 10. Criteri di valutazione della gara

| Criterio | Peso | Come lo copriamo |
|---|---|---|
| Esecuzione tecnica | 40% | 2 servizi CDS bidirezionali chiamati nel codice (WhatsApp, SES in/out; SMS/RCS se pronto) + AgentCore Runtime e Gateway (Memory e Observability con T-54), vision, ricerca ibrida su S3 Vectors; CDK riproducibile |
| Valore e impatto | 20% | **Cliente reale**, processo quotidiano ad alto volume, KPI misurabili |
| Demo | 20% | Foto del bigliettino → ordine verificato in pochi secondi, conferma con email e PDF; riordino con un tap e consegna con RCS se pronti, altrimenti come prossimi passi nel video |
| Creatività | 10% | Ordine da scrittura a mano, ruoli diversi (cliente, agente di commercio) sullo stesso agente; copilota e proattività se pronti |
| Funzionalità | 10% | Serverless, scalabile; i giudici possono ordinare da soli via WhatsApp |
| **Premio WhatsApp (Meta)** | $10k | Commercio conversazionale su WhatsApp: esattamente lo scenario che Meta promuove |

## 11. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Scrittura a mano poco leggibile | Nova Pro vision (Claude se abilitato sull'account) + domande di chiarimento + storico cliente; dataset di bigliettini veri per i test |
| Dati del cliente riservati | Catalogo **anonimizzato o sintetico** derivato da quello reale; nessun dato personale reale |
| Marchio del cliente nel video | Brand fittizio e dati sintetici (decisione del 27/10) |
| Integrazione ERP reale non fattibile in 2 settimane | ERP adapter con implementazione mock e interfaccia documentata |
| Approvazione template WhatsApp | 8 template `APPROVED` il 28/10; servono solo fuori dalla finestra di 24 h; fallback RCS/SMS ed email |
| Costi | Account condiviso: costi isolati con i tag `Project`/`Owner`/`Env`; serverless e scale-to-zero; spegnimento dopo il judging ([TEARDOWN](./TEARDOWN.md)) |

## 12. Glossario

| Termine | Significato |
|---|---|
| **HoReCa** | Hotel, Restaurant, Café – il canale della ristorazione |
| **Bigliettino** | Lista d'ordine scritta a mano dal ristoratore |
| **SKU** | Codice univoco di prodotto a catalogo |
| **Matching** | Abbinamento di una riga scritta dal cliente a uno SKU del catalogo |
| **Confidenza** | Probabilità stimata che l'abbinamento sia corretto |
| **Listino** | Prezzi applicati a uno specifico cliente |
| **Multiplo di confezione** | Quantità minima vendibile (es. cartone da 6) |
| **Cut-off** | Orario limite per ricevere un ordine in tempo per la consegna successiva |
| **Riordino scaduto** | Prodotto che il cliente compra regolarmente e non ha riordinato nel solito intervallo |
| **Copilota** | Modalità dell'agente dedicata agli agenti di commercio |
| **ERP adapter** | Componente che invia gli ordini al gestionale del Distributore |
| **Debounce** | Attesa della fine della raffica di messaggi prima di rispondere |
| **CDS / EUM / RCS** | AWS Communication Developer Services / End User Messaging / Rich Communication Services |
| **Finestra 24h / Template** | Regole WhatsApp per i messaggi inviati dall'azienda |
