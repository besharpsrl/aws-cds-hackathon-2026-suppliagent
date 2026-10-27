# AGENTS.md – SuppliAgent

> Contesto operativo per agenti di sviluppo (Claude Code, Kiro, Codex, Cursor, …) e per gli sviluppatori del team.
> Fonte di verità funzionale e tecnica: la cartella `docs/`. **Tutti i percorsi in questo file sono relativi alla root del repository** (`SuppliAgent/`). Questo file riassume regole e convenzioni; **in caso di conflitto valgono i documenti in `docs/`** e va segnalato.

---

## 1. Cos'è il progetto

**SuppliAgent** è un agente AI per gli **ordini HoReCa**, sviluppato da beSharp per un **cliente reale** (un distributore alimentare per la ristorazione) e per l'**AWS CDS Agentic AI Partner Hackathon** (Devpost).

- I **ristoratori** ordinano su **WhatsApp** (foto del bigliettino scritto a mano, vocale, testo) o via **email**; l'agente legge l'ordine, lo abbina al catalogo, chiede chiarimenti con pulsanti, verifica disponibilità/listino/cut-off, chiede **conferma esplicita**, invia conferma via **email con PDF** e **SMS/RCS**, poi avvisi di consegna; propone **riordini proattivi**.
- Gli **agenti di commercio** usano lo stesso agente come **copilota** (WhatsApp o chat web): consigli per cliente, catalogo e **schede tecniche**, briefing, ordini per conto del cliente.
- Il **back office** supervisiona da una **console web** (ordini, eccezioni, handoff, KPI).

## 2. Vincoli di gara (non negoziabili)

| Vincolo | Implicazione per il codice |
|---|---|
| Consegna **28/10/2026 21:00 (ora italiana)**, submission interna entro le 15:00; code freeze interno **27/10 ore 18:00** (calendario in `START_HERE.md`) | Priorità ai **Must** (03 §4.1); niente refactoring non richiesti |
| Il codice deve **importare e chiamare** almeno un client CDS valido | Usare **solo**: `socialmessaging` (`SendWhatsAppMessage`), `pinpoint-sms-voice-v2` (`SendRcsMessage`, `SendTextMessage`), `sesv2` (`SendEmail`). **Vietati**: `pinpoint` (v1), `pinpoint-email`, EUM Push |
| Lavoro **nuovo** (dal 14/09/2026) | Non copiare codice preesistente senza dichiararlo nel README (sezione "Pre-existing code") |
| Repo con **licenza open source** visibile | Non rimuovere `LICENSE` |
| Progetto **riproducibile** | Tutto in **CDK**; ogni passo manuale va documentato nel README |
| Demo pubblica fino al **12/11/2026** | Non introdurre dipendenze da macchine locali o servizi a pagamento non previsti |
| Materiali in **inglese** | README, commenti di interfaccia pubblica e testi della demo in inglese; documentazione interna in `docs/` in italiano |

## 3. Documentazione di riferimento

Leggi **prima di implementare** la parte che ti riguarda:

| Documento | Quando leggerlo |
|---|---|
| `SUPPLIAGENT_SOLUTION.md` | Visione e scenario demo |
| `docs/01_PROJECT_OVERVIEW.md` | Attori, perimetro, flusso ad alto livello |
| `docs/03_FUNCTIONAL_SPEC.md` | **Cosa** costruire: funzionalità `FN-xx`, priorità, **criteri di accettazione** |
| `docs/02_TECHNICAL_FLOWS.md` | **Come** si comporta: stati, flussi `F-xx`, casi `F-xx.Cn`, errori `E-xx`, contratti JSON, parametri |
| `docs/INFRASTRUCTURE_DESIGN.md` | Stack CDK, tabelle, code, IAM, sicurezza |
| `docs/architecture.drawio` | Diagramma |
| `docs/04_BACKLOG.md` | Task `T-xx` **ancora da fare**: descrizione completa, FN, dipendenze (anche dei task non ancora assegnati) |
| `START_HERE.md` §3bis | **Assegnazione dei task alle sessioni** (fonte unica): ordine, dipendenze tra sessioni (bloccanti o di integrazione), stato |
| `docs/DONE.md` | Lavoro completato: a task chiuso, nella stessa PR, si **rimuove** la riga dal backlog (o da `TODO_DOCS.md`, §12 di INFRASTRUCTURE_DESIGN), si segna ✅ in START_HERE §3bis e si aggiunge qui con data, commit e verifica |
| `docs/HANDOFF_CLAUDE_CODE.md` | Setup, prompt di avvio e prompt per stream |
| `docs/TODO_DOCS.md` | Documenti ancora mancanti (es. agent spec, contratti) |

Regole:
- Ogni task fa riferimento a uno o più **`FN-xx`** e, se pertinente, a flussi/casi **`F-xx.Cn`**.
- Se il comportamento implementato **differisce** dai documenti, aggiorna il documento nello stesso PR (o segnala la discrepanza) – i documenti non devono restare indietro.
- Se un requisito è ambiguo o mancante, **chiedi** invece di inventare; annota l'assunzione nel PR.

## 4. Architettura in breve

Region **`eu-west-1`** · modello **Amazon Nova via inference profile `eu.`** (`eu.amazon.nova-pro-v1:0` per ragionamento e vision, `eu.amazon.nova-lite-v1:0` per classificazioni veloci; mai `global.` o `us.`). Decisione del 25/10: Claude non è abilitato sull'account (*channel program*); il passaggio a Claude, se sbloccato, sarà un task pianificato. Il codice legge il modello da configurazione (`MODEL_ID`/`FAST_MODEL_ID`), mai hard-coded · IaC **AWS CDK (TypeScript)** · agente **Strands Agents su Amazon Bedrock AgentCore**.

```
Canali CDS (WhatsApp · SES in/out · SMS/RCS) ─► SNS ─► SQS inbound (standard + DLQ) ─► Inbound Router
   ─► TurnBuffer (DynamoDB) + SQS turn-flush (delay) ─► Turn Dispatcher (debounce + lock)
   ─► AgentCore Runtime (Strands, ruoli) ◄─► Memory · Gateway (tool MCP su Lambda) · Identity · Observability
        tool ─► DynamoDB · S3 Vectors (catalogo) · Bedrock Knowledge Base (schede tecniche) · Transcribe
        ─► Orders ─► EventBridge order.confirmed ─► ERP adapter (mock) · Order PDF
   ─► Notifier (unico punto di uscita, policy di canale) ─► WhatsApp · SES · SMS/RCS
Proattività: Scheduler notturno ─► Insights & Reorder Analyzer ─► Proactive Trigger ─► Dispatcher
Console: CloudFront + React · Cognito (backoffice · sales_rep · judge) · API GW REST + WebSocket (anche chat agenti)
Analytics: Firehose ─► S3 Parquet ─► Glue ─► Athena (KPI) · CloudWatch
```

Stack CDK (ordine di dipendenza): `Foundation` → `Data` → `Catalog` → `Channels` → `Agent` → `Messaging` → `Proactive` → `Console` → `Analytics`.

## 5. Struttura del repository

```
SuppliAgent/
├── agent-context/               # contesto per agenti di sviluppo (AGENTS.md, CLAUDE.md, kiro-steering/)
├── SUPPLIAGENT_SOLUTION.md
├── docs/                        # documentazione (fonte di verità)
├── assets/brand/                # logo e icone
├── infra/                       # CDK app (TypeScript)
│   ├── bin/suppliagent.ts
│   ├── lib/stacks/              # un file per stack
│   ├── lib/constructs/          # construct riutilizzabili (es. LambdaFunction con defaults)
│   └── config/                  # config per ambiente (dev, demo)
├── agent/                       # Strands agent (Python) per AgentCore Runtime
│   ├── main.py                  # entrypoint dello zip (code deploy, niente container)
│   ├── src/suppliagent_agent/   # app AgentCore, turno, tool per ruolo, SigV4 verso il Gateway
│   │   └── prompts/             # system prompt: shared.md, customer*.md, sales_rep.md, ordering.md
│   └── evals/                   # dataset (bigliettini, vocali, conversazioni) + runner
├── services/                    # Lambda (Python 3.12) – una cartella per funzione
│   ├── inbound_router/  turn_dispatcher/  notifier/   # media → S3 dentro inbound_router
│   ├── order_pdf/  erp_adapter/  catalog_indexer/  insights_analyzer/  proactive_trigger/
│   ├── console_api/  rep_chat/  broadcaster/
│   ├── tools/                   # target del Gateway: customers, order_intake, catalog,
│   │                            #   inventory_pricing, orders, reco, sales
│   └── shared/                  # libreria comune: modelli, client CDS, auth per ruolo, logging
├── console/                     # React + Vite + TypeScript
├── seed/                        # dati di prova anonimizzati + script seed/reset
├── scripts/                     # utility (deploy, reset demo, test end-to-end)
└── .github/workflows/
```

Non creare nuove cartelle di primo livello senza motivo; se servono, aggiorna questa sezione.

## 6. Stack e comandi

| Area | Scelta |
|---|---|
| IaC | AWS CDK v2 (TypeScript), Node.js 22 LTS, `cdk-nag` (AwsSolutions) |
| Lambda & agent | Python 3.12, ARM64, `boto3`, **AWS Lambda Powertools** (logger, tracer, metrics, idempotency), `pydantic` v2 |
| Agent | Strands Agents + AgentCore SDK; tool esposti via AgentCore Gateway (MCP) |
| Console | React + Vite + TypeScript, Amplify Auth (Cognito) solo lato client |
| Python tooling | `uv` (dipendenze), `ruff` (lint+format), `mypy`, `pytest`, `moto` per i mock AWS |
| TS tooling | `npm` workspaces, `eslint`, `prettier`, `vitest` (anche per le CDK assertions) |

Comandi (da mantenere aggiornati quando gli script esistono):

```bash
# Setup (dalla root: npm workspaces infra+console, uv workspace agent+services)
npm ci && uv sync

# Tutti i controlli (gli stessi della CI)
npm run check          # = lint + typecheck + test + synth
npm run lint           # eslint + prettier --check + ruff check + ruff format --check
npm run typecheck      # tsc (workspaces) + mypy services agent tests seed scripts
npm test               # vitest (workspaces) + pytest
npm run synth          # cdk synth -c env=dev (cdk-nag v3: errori = synth fallita; serve `uv`: impacchetta Lambda e agente)
npm run format         # prettier --write + ruff format

# Infra
cd infra && npx cdk synth -c env=demo
npx cdk diff -c env=dev
npx cdk deploy --all -c env=dev                      # solo dev; demo = manuale (vedi §11)

# Console (scaffold in T-61)
npm run dev -w console | npm run build -w console | npm test -w console

# Dati demo
uv run python seed/seed.py --env dev        # carica dati di prova
uv run python seed/reset.py --env dev       # ripristina lo scenario demo

# Agente deployato, saltando la pipeline di ingresso (il Dispatcher T-22 fa lo stesso dai canali)
uv run python scripts/invoke_agent.py --env dev --address 'WHATSAPP#+393330000001' --text "ciao"
```

## 7. Convenzioni di codice

**Generali**
- Naming risorse: `suppliagent-<env>-<componente>`; tag `Project=Hackathon AWS CDS`, `Owner=matteo.goretti@besharp.it`, `Env=<env>` (decisione del 24/10: i primi due sono obbligatori su **tutte** le risorse dell'account).
  - Applicarli sia come `Tags.of(app)` sia come **tag di stack** espliciti (`tags` nelle props di ogni Stack): con il flag `@aws-cdk/core:explicitStackTags` i tag dell'app non diventano tag di stack.
  - Le risorse create fuori da CloudFormation (custom resource, chiamate SDK, AgentCore se non via CDK) devono ricevere gli stessi tag in modo esplicito.
  - Un test di assertion CDK verifica che ogni risorsa taggabile abbia `Project` e `Owner`.
- Configurazione da **SSM Parameter Store** / CDK context; nessun valore hard-coded (soglie, tempi, ID canale). Parametri e default: 02 §7.
- **Nessun segreto nel codice o nel repo**; Secrets Manager; `.env.example` per lo sviluppo locale.
- Identificatori con prefisso: `cus_`, `con_`, `rep_`, `ord_`, `conv_`, `iss_`.
- Date/ore in **UTC ISO-8601** nei dati; conversione a `Europe/Rome` solo in presentazione.

**Python (Lambda, tool, agent)**
- Handler sottili: parsing → validazione `pydantic` → logica in moduli testabili → risposta.
- Powertools Logger con `correlation_id = conversationId` (+ `orderId`); **mai loggare contenuti dei messaggi, numeri di telefono o email in chiaro**.
- Idempotenza con Powertools Idempotency (o conditional write) su: elaborazione inbound (`providerMessageId`), `confirm_order` (`idempotencyKey`), invii del Notifier.
- Errori: eccezioni tipizzate in `services/shared/errors.py`; retry con backoff solo su errori transitori.
- Type hints ovunque; `mypy` senza errori.

**Tool dell'agente (Gateway)**
- Input/output con schema `pydantic` → JSON Schema esposto al Gateway; descrizioni chiare e brevi (sono lette dal modello).
- **Autorizzazione per ruolo dentro il tool** (non solo nel prompt): un `CUSTOMER_CONTACT` accede solo ai propri `customerIds`; un `SALES_REP` solo al suo portafoglio. Contesto (`contactId`, `role`, `customerIds`) propagato dal Dispatcher e **non modificabile dal modello**.
- I tool restituiscono dati, non testo per l'utente; la formulazione la fa l'agente.

**CDK (TypeScript)**
- Un file per stack; dipendenze tra stack via proprietà tipizzate, non `Fn.importValue` sparsi.
- Construct comune per Lambda (ARM64, Python 3.12, Powertools layer, log retention, X-Ray, KMS, DLQ dove serve).
- IAM **least privilege**: grant specifici; solo il **Notifier** ha permessi di invio CDS.
- `cdk-nag` deve passare; soppressioni solo con motivazione scritta.
- Tutti i dati a riposo cifrati con la KMS CMK del `FoundationStack`.

**Console**
- Componenti funzionali + hooks; stato server con React Query; nessun dato sensibile in `localStorage`.

## 8. Regole di dominio da rispettare sempre

1. **Nessun ordine inviato all'ERP senza conferma esplicita** (tap *Confermo* o risposta inequivocabile) – FN-12.
2. Chiarimenti solo per righe con confidenza tra `matchAskThreshold` e `matchAutoThreshold`; max 3 opzioni + "Altro" – FN-07/08.
3. **Massimo 1 suggerimento per ordine**, solo con consenso proattivo – FN-11.
4. Riordino proattivo: max **1 proposta ogni 7 giorni** per cliente, mai in fascia notturna, mai senza consenso – FN-19.
5. WhatsApp: fuori dalla finestra di 24h **solo template approvati**; fallback SMS/email – F-11.
6. Coda `inbound` **standard** (SNS standard non consegna a code FIFO, decisione del 26/10): idempotenza su `providerMessageId`, ordine per chat dal timestamp di ricezione AWS; tutte le risposte passano dal **debounce** (una risposta per raffica, lock per conversazione) – FN-26.
7. Tutti gli invii passano dal **Notifier**; nessun altro componente chiama le API di invio CDS.
8. L'agente si dichiara **assistente virtuale**; niente sconti, prezzi o condizioni fuori listino; niente dati di altri clienti.
9. Lingua: quella del contatto (IT/EN), memorizzata come preferenza.
10. **Solo dati anonimizzati o sintetici**; mai dati reali del cliente nel repo, nei log, nei test o nel video senza autorizzazione.

## 9. Test e Definition of Done

Un task è "fatto" quando:
- [ ] soddisfa i **criteri di accettazione** delle `FN-xx` collegate (03);
- [ ] gestisce i casi `F-xx.Cn` pertinenti e gli errori `E-xx` applicabili (02);
- [ ] ha **unit test** (logica) e, per i tool, test di **autorizzazione negativa** (accesso a dati di un altro cliente → negato);
- [ ] `ruff`, `mypy`, `eslint`, test e `cdk synth` (con `cdk-nag`) passano;
- [ ] emette gli **eventi applicativi** previsti (02 §6.4);
- [ ] aggiorna documentazione, `.env.example`, README se cambiano comandi o prerequisiti.

Per l'agente: ogni modifica a prompt o tool va verificata con gli **eval** in `agent/evals/` (lettura bigliettini, matching, intento, numero di scambi) e i risultati riportati nel PR.

## 10. Git e PR

- Branch: `feat/FN-07-catalog-matching`, `fix/E-08-erp-retry`, `chore/...`, `docs/...`.
- Commit **Conventional Commits** con riferimento: `feat(catalog): hybrid matching with history boost (FN-07)`.
- PR piccole, con: FN/flussi coinvolti, come testare, screenshot/log per la console o i canali, assunzioni fatte. Un task = una PR, tranne i gruppi di task accoppiati elencati in `docs/04_BACKLOG.md` §1bis (una PR, un commit per task).
- Flusso: l'agente di sviluppo fa push del branch e **apre la PR**; lo sviluppatore revisiona e fa **merge su `main`** con CI verde, sempre con *merge commit* (niente squash/rebase: gli hash citati in `docs/DONE.md` devono restare validi); il deploy si fa da locale da `main` aggiornato. Mai push diretti su `main`. I branch confluiti non si cancellano.
- Non fare force-push su `main`. Non committare file generati (`cdk.out/`, `node_modules/`, `.venv/`, build della console).

## 11. Cosa NON fare senza chiedere

- Deploy sull'ambiente **`demo`** o modifiche a risorse condivise (numero WhatsApp, dominio SES, agente RCS, template Meta).
- Cambiare **region**, modello o inference profile (deve restare `eu.`).
- Aggiungere servizi con **costo fisso** (OpenSearch, NAT Gateway, RDS, istanze sempre accese) o fuori dai crediti.
- Usare client CDS non ammessi o rimuovere l'uso reale di quelli ammessi.
- Cancellare dati, tabelle o bucket; disattivare cifratura, cdk-nag o test.
- Introdurre dati reali del cliente, marchi di terzi o testi non verificati nei template.

## 12. Glossario minimo

HoReCa (ristorazione) · **bigliettino** (lista d'ordine scritta a mano) · **SKU** (codice prodotto) · **matching** (abbinamento riga → SKU) · **listino** (prezzi del cliente) · **multiplo di confezione** · **cut-off** (orario limite per la consegna successiva) · **riordino scaduto** · **copilota** (modalità per agenti di commercio) · **debounce** (attesa fine raffica) · **handoff** (passaggio a un umano) · **CDS/EUM/RCS** (servizi di messaggistica AWS).
