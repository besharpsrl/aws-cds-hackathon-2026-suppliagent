# SuppliAgent – Documentazione

Progetto: **SuppliAgent** – agente AI per gli ordini HoReCa via WhatsApp, per un cliente reale di beSharp.
Concept: [`../SUPPLIAGENT_SOLUTION.md`](../SUPPLIAGENT_SOLUTION.md)

| # | Documento | Contenuto | Stato |
|---|---|---|---|
| 01 | [Panoramica tecnica](./01_PROJECT_OVERVIEW.md) | Problema, soluzione, attori, perimetro, architettura e flusso ad alto livello con diramazioni | v0.2 – da validare |
| 02 | [Flussi tecnici e casistiche](./02_TECHNICAL_FLOWS.md) | Stati di ordine e righe, pipeline di ingresso, flussi F-01…F-15 con tutti i casi, errori, contratti, parametri | v0.2 – da validare |
| 03 | [Specifica funzionale](./03_FUNCTIONAL_SPEC.md) | Catalogo FN-01…FN-35, priorità MoSCoW, criteri di accettazione, NFR, mappa per stream, scenari demo | v0.2 – da validare |
| – | [Infrastructure Design](./INFRASTRUCTURE_DESIGN.md) | Architettura AWS (eu-west-1), 9 stack CDK, catalog intelligence, dati, sicurezza, costi | v0.2 |
| – | [architecture.drawio](./architecture.drawio) | Diagramma architetturale (draw.io) | v0.2 |
| 04 | [Backlog e piano di lavoro](./04_BACKLOG.md) | Task T-xx per stream, fasi, dipendenze, owner | v0.1 |
| – | [Handoff a Claude Code](./HANDOFF_CLAUDE_CODE.md) | Setup, collegamento a GitHub, prompt di avvio e prompt per stream | v0.1 |
| – | [Checklist submission](./SUBMISSION_CHECKLIST.md) | Passi per iscrizione, crediti, ACE e submission Devpost | in corso |
| 09 | [Testi e template](./09_CONTENT_AND_TEMPLATES.md) | Template WhatsApp (fonte: JSON nel Notifier) e invio a Meta | v0.1 |
| – | [Documenti da fare](./TODO_DOCS.md) | Elenco dei documenti ancora da scrivere | promemoria |
| – | [Lavoro completato](./DONE.md) | Task, documenti e punti aperti chiusi, con data, commit e verifica | vivo |

**Punto di partenza**: [`../START_HERE.md`](../START_HERE.md) – documento unico di handoff (cosa fare, chi lo fa, mappa dei file).

**Ordine di lettura consigliato**: concept → 01 → 03 → 02 → Infrastructure Design.

**Convenzioni ID**: `FN-xx` funzionalità · `NFR-xx` requisiti non funzionali · `F-xx(.Cn)` flussi e casi · `E-xx` errori · `S-x` scenari demo · `J-x` journey.
