# SuppliAgent – Documenti da fare

> Promemoria dei documenti da scrivere dopo la validazione di 01/02/03.
> Ordinati per urgenza · Aggiornato il 12/10/2026 (nuovo concept SuppliAgent) · I documenti completati si rimuovono da qui e vanno in [DONE.md](./DONE.md)

| # | Documento | File proposto | Priorità | Entro | Owner | Stato |
|---|---|---|---|---|---|---|
| 1 | Richiesta dati e autorizzazioni al cliente | `00_CLIENT_DATA_REQUEST.md` | **Urgentissima** | 13/10 | | ☐ |
| 3 | Testi e template | `09_CONTENT_AND_TEMPLATES.md` | Alta | 14/10 | | ◐ (template WhatsApp fatti, resto da scrivere) |
| 4 | Specifica dell'agente | `05_AGENT_SPEC.md` | Alta | 15/10 | | ☐ |
| 5 | Contratti e modello dati | `06_DATA_AND_CONTRACTS.md` | Alta | 15/10 | | ☐ |
| 6 | Specifica dei dati di prova | `08_MOCK_DATA.md` | Alta | 16/10 | | ☐ |
| 7 | Copione e storyboard del video | `07_DEMO_SCRIPT.md` | Alta | 20/10 | | ☐ |
| 8 | Guida al deploy e guida per i giudici | `../README.md` | Media | 24/10 | | ◐ (README creato) |
| 9 | Registro delle decisioni architetturali | `adr/ADR-xxx.md` | Bassa | continuo | | ☐ |
| 10 | Bozza testi submission Devpost (EN) | `10_SUBMISSION_DRAFT.md` | Media | 25/10 | | ☐ |

---

## 1. Richiesta dati e autorizzazioni al cliente
**Perché**: il valore del progetto dipende dai dati reali del Distributore; servono subito.
**Contenuto**
- Export del catalogo (SKU, nomi, formati, unità di vendita, categorie) e schede tecniche
- Esempi reali (anonimizzati) di bigliettini, vocali, ordini via email
- Regole di consegna: zone, giorni, cut-off, minimi, multipli
- Storico ordini anonimizzato (anche parziale) o regole per generarlo
- Baseline del processo attuale (ordini/giorno, tempo di inserimento, % errori)
- Autorizzazioni: uso dei dati anonimizzati, citazione del nome e del marchio (submission, video, case study), contatto per l'**opportunità ACE**

## 2. Backlog e piano di lavoro
- Task per ogni FN con stream (AG / CH / CO / IN), owner, stima, dipendenze
- Milestone: dati di prova pronti (15/10), MVP ordine da foto (19/10), code freeze (23/10), submission (26/10)
- Percorso critico: dati catalogo → FN-01/26 → FN-05 → FN-07 → FN-08 → FN-09/10 → FN-12 → FN-13 → FN-14/15

## 3. Testi e template
- Informativa e richiesta di consenso proattivo (IT/EN)
- Email HTML di conferma e layout del PDF ordine; messaggi RCS/SMS (conferma, consegna)
- Messaggi di sistema (handoff, errori di cortesia, ordine scaduto)

## 4. Specifica dell'agente
- Prompt di sistema **per ruolo** (cliente / agente di commercio), tono, regole (niente sconti non a listino, niente informazioni di altri clienti)
- Schema di ogni tool (input, output, errori) e autorizzazioni per ruolo
- Prompt e schema di output per la lettura dei bigliettini
- Configurazione Memory e Guardrails
- Set di valutazione: bigliettini, vocali, conversazioni con risultati attesi; metriche (lettura righe, matching, intento, n. scambi)

## 5. Contratti e modello dati
- Schema delle tabelle DynamoDB con esempi di item (Orders con righe e candidati)
- Documento dell'indice prodotti (S3 Vectors) e metadati della Knowledge Base
- API REST e messaggi WebSocket della console (OpenAPI), interfaccia ERP adapter
- Schemi JSON di NormalizedMessage, richiesta di turno, eventi EventBridge

## 6. Specifica dei dati di prova
- Catalogo anonimizzato (o sintetico), listini, stock con esauriti e sostituti, calendario consegne
- Clienti, contatti, agenti di commercio e portafogli; storico ordini con pattern di riordino (per S5)
- Dataset di **bigliettini scritti a mano** (persone e grafie diverse) e vocali per i test
- Script di seed e reset dell'ambiente demo

## 7. Copione e storyboard del video
- 3 minuti scena per scena: telefono del ristoratore, telefono dell'agente di commercio, console
- Scenari S1 + estratti S3, S5, S6; momento "wow": foto del bigliettino → ordine verificato
- Checklist di registrazione (device RCS tester, reset dati, marchio del cliente solo se autorizzato, niente musica non licenziata)

## 8. Guida al deploy e guida per i giudici
- Prerequisiti manuali (WABA, template, dominio SES, RCS, modelli Bedrock, import catalogo)
- `cdk deploy --all`, configurazione, seed e reset
- "Prova SuppliAgent in 5 minuti": numero WhatsApp, cliente di prova, bigliettino di esempio da fotografare, credenziali console `judge`

## 9. Registro delle decisioni architetturali (ADR)
- ADR-001 Region `eu-west-1`, profili `eu.` e modello Amazon Nova (Claude non abilitato sull'account)
- ADR-002 SQS standard + debounce applicativo con lock (SNS standard non consegna a FIFO; decisione del 26/10, INFRASTRUCTURE_DESIGN §5.2)
- ADR-003 S3 Vectors invece di OpenSearch (costi, scale-to-zero)
- ADR-004 Matching ibrido semantico + lessicale + storico
- ADR-005 Un solo agente con ruoli e autorizzazione nei tool
- ADR-006 ERP adapter con implementazione mock
- ADR-007 SES receipt rules per l'inbound

## 10. Bozza testi submission Devpost (EN)
- Descrizione: problema reale del cliente, soluzione, architettura, impatto misurabile
- Paragrafo sull'uso di AWS End User Messaging Social (premio Meta WhatsApp)
- Elenco servizi AWS, link a repo, video, demo
