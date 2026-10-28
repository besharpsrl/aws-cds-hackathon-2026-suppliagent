# SuppliAgent – Documentazione

Progetto: **SuppliAgent** – agente AI per gli ordini HoReCa via WhatsApp, per un cliente reale di beSharp.
Concept: [`../SUPPLIAGENT_SOLUTION.md`](../SUPPLIAGENT_SOLUTION.md)

| # | Documento | Contenuto | Stato |
|---|---|---|---|
| 01 | [Panoramica tecnica](./01_PROJECT_OVERVIEW.md) | Problema, soluzione, attori, perimetro, architettura e flusso ad alto livello con diramazioni | v0.2 – da validare |
| 02 | [Flussi tecnici e casistiche](./02_TECHNICAL_FLOWS.md) | Stati di ordine e righe, pipeline di ingresso, flussi F-01…F-15 con tutti i casi, errori, contratti, parametri | v0.2 – da validare |
| 03 | [Specifica funzionale](./03_FUNCTIONAL_SPEC.md) | Catalogo FN-01…FN-35, priorità MoSCoW, criteri di accettazione, NFR, mappa per stream, scenari demo | v0.2 – da validare |
| – | [Infrastructure Design](./INFRASTRUCTURE_DESIGN.md) | Architettura AWS (eu-west-1), 9 stack CDK, catalog intelligence, dati, sicurezza, costi | v0.2 |
| – | [architecture.drawio](./architecture.drawio) · [PNG](./architecture.png) | Diagramma architetturale (draw.io, in inglese; architettura completa, mock inclusi, senza distinzione roadmap). Il PNG si rigenera dal `.drawio` (aprilo in draw.io: *File → Export as → PNG*, scala 2x) | v0.4 |
| – | [SUBMISSION_TEXT.md](./SUBMISSION_TEXT.md) | Bozza dei testi Devpost in inglese (problema, soluzione, servizi AWS, uso di EUM Social/WhatsApp, impatto) con la lista delle affermazioni da verificare prima dell'invio | bozza |
| 09 | [Testi e template](./09_CONTENT_AND_TEMPLATES.md) | Template WhatsApp (fonte: JSON nel Notifier) e invio a Meta | v0.1 |
| – | [Iscrizione WhatsApp (WABA)](./WABA_SETUP.md) | Procedura di collegamento del numero WhatsApp ad AWS End User Messaging Social | in uso |
| – | [VIDEO_SCRIPT.md](./VIDEO_SCRIPT.md) | Copione del video demo (≤ 3 min), alternative per le scene non pronte alla registrazione e checklist di registrazione | bozza |
| – | [Agente RCS e mittente SMS](./RCS_SMS_SETUP.md) | Agente RCS di test, tester, sender ID SMS per l'Italia e vincoli (M-11) | in uso |
| – | [OLD/](./OLD/) | Documenti superati (backlog, DONE, checklist submission, documenti da fare, handoff Claude Code): solo storico | archivio |

**Punto di partenza, stato, timeline, backlog, azioni manuali e decisioni**: [`../START_HERE.md`](../START_HERE.md) (fonte unica).

**Ordine di lettura consigliato**: concept → 01 → 03 → 02 → Infrastructure Design.

**Convenzioni ID**: `FN-xx` funzionalità · `NFR-xx` requisiti non funzionali · `F-xx(.Cn)` flussi e casi · `E-xx` errori · `S-x` scenari demo · `J-x` journey · `T-xx` task, `M-xx` azioni manuali, `D-xx` decisioni (in `START_HERE.md`).
