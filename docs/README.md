# SuppliAgent – Documentazione

Progetto: **SuppliAgent** – agente AI per gli ordini HoReCa via WhatsApp, per un cliente reale di beSharp. Questo file è l'**unica mappa** dei documenti.

| Documento | Contenuto | Stato |
|---|---|---|
| [`../README.md`](../README.md) | Presentazione in inglese per GitHub e giudici: setup, deploy da zero, passi manuali, "Try it" | v1.0 |
| [`../START_HERE.md`](../START_HERE.md) | Punto di partenza del team: come si lavora, stato, timeline, backlog, azioni manuali, decisioni | aggiornato al 28/10 |
| [01 – Panoramica e concept](./01_PROJECT_OVERVIEW.md) | Problema, soluzione, KPI, attori, perimetro, architettura e flusso ad alto livello, criteri di gara, rischi, glossario | v1.1 |
| [02 – Flussi tecnici e casistiche](./02_TECHNICAL_FLOWS.md) | Stati di ordine e righe, pipeline di ingresso, flussi F-01…F-15 con i casi, errori, contratti, **parametri (unica fonte)** | v1.0 |
| [03 – Specifica funzionale](./03_FUNCTIONAL_SPEC.md) | Funzionalità FN-01…FN-35 con priorità, criteri di accettazione e **stato nella gara**, NFR, scenari demo | v1.0 |
| [Infrastructure Design](./INFRASTRUCTURE_DESIGN.md) | Architettura AWS (eu-west-1), 9 stack CDK, componenti, dati, sicurezza, costi, configurazione | v1.0 |
| [architecture.drawio](./architecture.drawio) · [PNG](./architecture.png) | Diagramma architetturale (in inglese). Il PNG si rigenera dal `.drawio` (draw.io: *File → Export as → PNG*, scala 2x) | v0.4 |
| [Setup dei canali](./CHANNELS_SETUP.md) | Passi manuali di WhatsApp (WABA), template Meta, agente RCS e sender ID SMS, con stato e ID di `dev` | in uso |
| [TEARDOWN](./TEARDOWN.md) | Spegnimento dell'ambiente dopo il judging e verifica dei costi | da usare dal 14/11 |
| [SUBMISSION_TEXT.md](./SUBMISSION_TEXT.md) | Testi Devpost in inglese | submission |
| [VIDEO_SCRIPT.md](./VIDEO_SCRIPT.md) | Copione del video demo (≤ 3 min) | submission |
| [OLD/](./OLD/) | Documenti superati (backlog, DONE, checklist, handoff): solo storico, non si aggiornano | archivio |

Regole per gli agenti di sviluppo: [`../agent-context/AGENTS.md`](../agent-context/AGENTS.md).

**Ordine di lettura consigliato**: 01 → 03 → 02 → Infrastructure Design.

**Dove sta cosa** (una sola fonte per ogni informazione):
- stato per funzionalità: colonna *Gara* di 03 §4.1; stato per area e limiti noti: `START_HERE.md` §2;
- parametri di runtime (soglie, debounce, tempi): 02 §7; configurazione di deploy (dominio, numero, modelli): Infrastructure Design §11;
- decisioni: `START_HERE.md` §6; rischi di sicurezza accettati: Infrastructure Design §12;
- template WhatsApp: JSON in `services/notifier/whatsapp_templates/` (regole in Setup dei canali §2).

**Convenzioni ID**: `FN-xx` funzionalità · `NFR-xx` requisiti non funzionali · `F-xx(.Cn)` flussi e casi · `E-xx` errori · `S-x` scenari demo · `J-x` journey · `T-xx` task e `M-xx` azioni manuali (GitHub Issues).
