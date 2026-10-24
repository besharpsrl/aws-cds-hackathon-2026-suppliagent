# SuppliAgent – Da dove partire

> **Documento unico di handoff**: cosa devi fare tu, cosa fa Claude Code e come farglielo fare, quali file esistono e cosa contengono.
> Usalo come scaletta: segui le sezioni in ordine e spunta le caselle.
> Aggiornato al **23/10/2026 pomeriggio** (P0 completata) · Consegna Devpost: **28/10/2026 ore 21:00** (ora italiana) · Obiettivo interno: submission **entro il 28/10 mattina**

---

## 0. A che punto siamo

| Area | Stato |
|---|---|
| Idea, perimetro, documentazione funzionale e tecnica | ✅ pronta (da validare con il team) |
| Architettura AWS e diagramma | ✅ pronti |
| Backlog: 39 task da fare in `docs/04_BACKLOG.md`; il completato è in `docs/DONE.md` | ✅ pronto |
| Contesto per Claude Code (istruzioni, comandi, subagent, hook, MCP) | ✅ attivo |
| Repo GitHub `besharpsrl/aws-cds-hackathon-2026-suppliagent` | ✅ creato e configurato · branch `chore/p0-foundations` **ancora da pushare + PR** (§1.1) |
| Codice | ◐ **P0 fatta** (T-01, T-03, T-02): monorepo, CI, app CDK con Foundation e Data stack, `npm run check` verde · nessun deploy ancora |
| Account AWS | ◐ account dell'hackathon assegnato (24/10), **CDK bootstrap da fare** (§1.2) · tag obbligatori su tutte le risorse: `Project=Hackathon AWS CDS`, `Owner=matteo.goretti@besharp.it` |
| Devpost | ◐ iscritti e team creato |
| Team | Una sola persona (MG): tutti gli stream sono suoi, lavoro con sessioni Claude Code parallele (§3) |
| Canali (WhatsApp, SES, SMS/RCS), dati del cliente, ACE | ⬜ da fare (§1) |

Calendario sintetico (dettaglio in §5):

| Giorno | Tu | Claude Code |
|---|---|---|
| **Ven 23/10** | Repo, account, canali, cliente, Devpost | Fondamenta (P0) e avvio walking skeleton (P1) |
| **Sab 24/10** | Dataset bigliettini, approvazioni | P1 → P2: messaggio WhatsApp end-to-end, lettura e matching |
| **Dom 25/10** | Revisioni, test con il telefono | P2 → P3: ordine completo, copilota, proattività, console |
| **Lun 26/10** | Prova completa degli scenari | P3 e **code freeze** la sera |
| **Mar 27/10** | Video, testi, ACE | Hardening, eval, ambiente `demo`, README giudici |
| **Mer 28/10** | **Submission** al mattino | Solo bugfix |

---

## 1. Cosa devi fare tu

Le cose che Claude Code non può fare: account, accessi, contatti con cliente e Meta, decisioni, approvazioni, video, submission.

### 1.1 Subito – pubblicare la P0 (10 minuti)

```bash
git push -u origin chore/p0-foundations
gh pr create --fill                    # la CI parte sulla PR: deve essere verde prima del merge
```

- [ ] PR della P0 aperta, CI verde (è la prima esecuzione reale del workflow), merge su `main`
- [x] GitHub → *Settings → Branches*: regola su `main` (PR obbligatoria, CI verde, niente force push)
- [x] GitHub → *About*: descrizione e topic (vedi §4.6)
- [x] Membri del team aggiunti al repo

### 1.2 Oggi – account, canali, cliente, gara

**Strumenti sul tuo Mac** → `docs/HANDOFF_CLAUDE_CODE.md` §2–§3
- [ ] Strumenti installati (Node 22, Python 3.12, uv, AWS CLI, gh, CDK, Docker Desktop, Claude Code)
- [ ] Profilo AWS `suppliagent-dev` funzionante (`aws sts get-caller-identity`)

**Account AWS** (eu-west-1)
- [ ] Account dedicato + budget con avvisi
- [ ] Accesso ai modelli Bedrock: Claude con profilo `eu.` e Titan Text Embeddings V2 (`aws bedrock list-inference-profiles --region eu-west-1`)
- [ ] Confermare l'account da usare (oggi il profilo `default` punta a `115908659817`, ruolo `beSharp-BedrockAccessRole`) e lanciare `npx cdk bootstrap aws://<ACCOUNT_ID>/eu-west-1 --tags Project="Hackathon AWS CDS" --tags Owner=matteo.goretti@besharp.it` (una volta sola)
- [ ] Prima del primo deploy: task **T-13** (tag obbligatori in CDK) fatto da Claude Code
- [ ] Risorse create a mano da console (EUM Social/numero WhatsApp, eventuali identità SES, budget): aggiungere gli stessi due tag
- [ ] Primo deploy `dev` (`cd infra && npx cdk deploy --all -c env=dev`), dopo aver letto `cdk diff`
- [ ] Crediti: quelli AWS ($50) probabilmente non arrivano in tempo (3–5 giorni, scadono il 31/10) → confermare un budget interno beSharp

**Canali** → `docs/INFRASTRUCTURE_DESIGN.md` §5.1 e §11
- [ ] **WhatsApp**: account WhatsApp Business collegato ad AWS End User Messaging Social **in eu-west-1**, numero dedicato, messaggio di prova
- [ ] **Template WhatsApp** inviati a Meta (testi da Claude Code, task T-28): `order_confirmation`, `reorder_suggestion`, `delivery_update`, `order_pending_reminder`
- [ ] **SES**: dominio verificato (DNS), **richiesta di uscita dalla sandbox oggi**, record MX per la ricezione
- [ ] **SMS/RCS**: verificare tempi di registrazione mittente per l'Italia e dell'agente RCS di test (telefoni tester); se non pronto entro il 25 → SMS/RCS solo nel video

**Cliente** → `docs/TODO_DOCS.md` §1
- [ ] Catalogo e schede tecniche (anche parziali) → cartella `seed/private/` (esclusa da git, Claude Code non la legge)
- [ ] Regole di consegna: zone, giorni, cut-off, minimi, multipli
- [ ] Qualche esempio reale (anonimizzato) di bigliettino
- [ ] Baseline del processo attuale (ordini/giorno, tempo di inserimento, % errori)
- [ ] Autorizzazione a citare il cliente e usarne il marchio (sì/no)
- [ ] Referente per l'opportunità ACE

**Gara** → `docs/SUBMISSION_CHECKLIST.md`
- [x] Tutti iscritti su Devpost con email @besharp.it, team formato
- [ ] Rappresentante del team scelto
- [ ] **Opportunità ACE** su Partner Central (codice campagna `AWS CDS Agentic AI Hackathon -Sept. 2026`, prodotti EUM, EUM Social, SES) → annotare l'ID

**Team e decisioni** → §6
- [ ] Owner di ogni stream (IN, CH, AG, CO) scritto in `docs/04_BACKLOG.md`
- [ ] Decisioni aperte chiuse (§6)

### 1.3 Sabato–lunedì (24–26/10)
- [ ] **Dataset di prova**: ~15 bigliettini scritti a mano da persone diverse (fotografati) + qualche vocale → li usa Claude Code per lettura ed eval (task T-05)
- [ ] Approvare i deploy su `dev` quando Claude Code li chiede; rivedere e fare merge delle PR
- [ ] Provare gli scenari dal proprio telefono (S1 per primo)
- [ ] Lunedì 26 sera: **code freeze**

### 1.4 Martedì–mercoledì (27–28/10)
- [ ] Deploy sull'ambiente `demo` (una sola persona)
- [ ] Video ≤ 3 minuti (telefono + console), caricato **pubblico** su YouTube
- [ ] Repo pubblico con licenza visibile **oppure** privato condiviso con i contatti dei giudici (vedi regolamento)
- [ ] Il rappresentante compila Devpost: repo, diagramma, descrizione (EN), video, istruzioni per i giudici, ID ACE, paragrafo su WhatsApp (premio Meta) → **invio il 28 mattina**
- [ ] Ambiente `demo` attivo e costi sotto controllo fino al **12/11**

---

## 2. Cosa fa Claude Code

Tutto il codice, i test, l'infrastruttura CDK, i dati di prova sintetici, i testi (template, email, README) e le revisioni. Il lavoro è diviso in 42 task, organizzati in 4 stream e 5 fasi: quelli **da fare** sono in `docs/04_BACKLOG.md`, quelli **completati** in `docs/DONE.md` (a task chiuso la riga si sposta dal primo al secondo).

| Fase | Quando | Cosa produce | Task principali |
|---|---|---|---|
| **P0 – Fondamenta** | 23/10 | Monorepo, CI, app CDK con Foundation e Data stack, template WhatsApp | ✅ T-01, T-03, T-02 · ⬜ T-28 |
| **P1 – Walking skeleton** | 23–24/10 | Messaggio WhatsApp → pipeline → agente → risposta | T-04, T-20, T-21, T-22, T-23, T-24, T-40, T-41, T-42, T-60, T-61 |
| **P2 – Ordine da foto** | 24–25/10 | Scenario S1 completo: lettura bigliettino, matching, chiarimenti, conferma, ERP mock, email PDF, SMS/RCS | T-06, T-07, T-25…T-27, T-43…T-49, T-62 |
| **P3 – Copilota, proattività, console** | 25–26/10 | Copilota agenti, riordino proattivo, consegne, console, KPI | T-08, T-09, T-50…T-52, T-63…T-65 |
| **P4 – Hardening e materiali** | 27–28/10 | Eval, ambiente demo, README giudici, testi submission | T-10, T-11, T-53, T-66 |

Gli stream e chi li segue:

| Stream | Contenuto | Prompt di avvio |
|---|---|---|
| **IN** – Infra, Dati & Materiali | CDK di base, dati di prova, catalogo e Knowledge Base, ERP mock, proattività, analytics, demo | `docs/HANDOFF_CLAUDE_CODE.md` §8 – Stream IN |
| **CH** – Canali CDS | WhatsApp, SES, SMS/RCS, ricezione, debounce, Notifier | §8 – Stream CH |
| **AG** – Agent & AgentCore | Agente Strands su AgentCore, tool, lettura bigliettini, matching, ordini, copilota, eval | §8 – Stream AG |
| **CO** – Console & Analytics | Console back office, chat agenti, KPI | §8 – Stream CO |

---

## 3. Come farglielo fare

Guida completa, pensata per chi parte da zero: **`docs/HANDOFF_CLAUDE_CODE.md`**. In sintesi:

1. **Primo avvio** (guida §5): dalla cartella del repo lanci `claude`, fai login, approvi i server MCP `aws-documentation` e `agentcore`, installi i plugin:
   ```text
   /plugin marketplace add strands-agents/harness-sdk
   /plugin install strands@strands-agents
   /plugin install security-guidance@claude-plugins-official
   ```
   Non servono altre skill: istruzioni, comandi e subagent sono già nel repo.
2. **Sessione delle fondamenta** (guida §7): ✅ fatta il 23/10 (dettagli in `docs/DONE.md`); resta push + PR (§1.1).
3. **Sessioni parallele** (guida §8): ogni persona apre la propria copia di lavoro con `claude -w canali` / `agente` / `console` / `dati` e incolla il prompt del proprio stream.
4. **Ciclo di ogni task** (guida §9):
   ```text
   /clear
   Shift+Tab → plan mode
   /implement-fn FN-xx
   /dod-check            (+ /cds-check per i canali)
   ```
   poi `git push` e `gh pr create --fill`.
5. **Regole** (guida §12): un task per sessione, sempre il piano prima, deploy solo su `dev` e approvati a mano, `Esc` per fermare, `/rewind` per tornare indietro.

Claude Code usa da solo i **subagent** del progetto quando servono:

| Subagent | Ruolo |
|---|---|
| `aws-docs-researcher` | Verifica API AWS recenti (AgentCore, Strands, S3 Vectors, canali) sulla documentazione ufficiale |
| `test-runner` | Lint, type check, test, `cdk synth`; riassume solo gli errori |
| `code-reviewer` | Revisione rispetto a criteri di accettazione, Definition of Done e regole di gara |
| `security-reviewer` | Autorizzazione per ruolo, prompt injection, dati personali, permessi |

I **team di agenti** non servono finché ogni stream ha una persona (guida §11).

---

## 4. Mappa dei file

### 4.1 Da leggere per primi

| File | Contenuto |
|---|---|
| `START_HERE.md` | Questo documento |
| `README.md` | Presentazione del progetto in inglese (per GitHub e i giudici): cosa fa, uso dei servizi CDS, architettura, struttura, avvio, licenza |
| `SUPPLIAGENT_SOLUTION.md` | Il concept: problema, scenario demo in 11 passi, funzionalità per ristoratore/agente/back office, KPI, mappatura sui criteri di gara, rischi |

### 4.2 Documentazione di progetto (`docs/`, in italiano)

| File | Contenuto |
|---|---|
| `docs/README.md` | Indice della documentazione e convenzioni sugli ID |
| `docs/01_PROJECT_OVERVIEW.md` | Panoramica: problema, attori, perimetro, architettura ad alto livello, **flusso principale con 20 diramazioni**, ruolo dei canali, glossario |
| `docs/02_TECHNICAL_FLOWS.md` | Documento tecnico completo: stati di ordine e righe, ruoli, pipeline di ingresso e debounce, **15 flussi (F-01…F-15) con tutti i casi**, 13 errori, contratti JSON, eventi, tool, parametri |
| `docs/03_FUNCTIONAL_SPEC.md` | **35 funzionalità (FN-01…FN-35)** con priorità e criteri di accettazione, personas, journey, requisiti non funzionali, 7 scenari demo |
| `docs/04_BACKLOG.md` | Task **da fare** (T-xx) per stream, fasi, ondate parallele, dipendenze, owner, stato |
| `docs/DONE.md` | Lavoro **completato**: task, documenti e punti aperti chiusi, con data, commit e come verificarli |
| `docs/INFRASTRUCTURE_DESIGN.md` | Architettura AWS in eu-west-1: 9 stack CDK, canali, ingestion, AgentCore (incl. Evaluations), catalogo con S3 Vectors e Knowledge Base, ordini/ERP, proattività, dati, console, sicurezza, costi, configurazione |
| `docs/architecture.drawio` | Diagramma architetturale (apri con draw.io); da esportare in PNG per la submission |
| `docs/HANDOFF_CLAUDE_CODE.md` | Guida passo passo a Claude Code: concetti, installazione, AWS, GitHub, primo avvio, plugin, subagent, prompt di avvio e per stream, comandi |
| `docs/SUBMISSION_CHECKLIST.md` | Passi per Devpost: iscrizione, crediti, ACE, materiali, invio |
| `docs/TODO_DOCS.md` | Documenti ancora da scrivere (richiesta dati al cliente, specifica dell'agente, contratti, dati di prova, copione video, ADR, testi submission) |

### 4.3 Contesto per Claude Code e altri tool (`agent-context/`)

I file si modificano **solo qui**; `install.sh` li collega dove i tool li cercano.

| File | Contenuto |
|---|---|
| `agent-context/AGENTS.md` | Regole di progetto per tutti gli agenti: vincoli di gara, architettura, struttura, stack e comandi, convenzioni, regole di dominio, Definition of Done, Git, cosa non fare |
| `agent-context/CLAUDE.md` | Istruzioni specifiche per Claude Code (importa `AGENTS.md`) |
| `agent-context/claude/settings.json` | Permessi (consentito / chiede conferma / vietato) e hook di lint |
| `agent-context/claude/commands/` | Comandi `/implement-fn`, `/cds-check`, `/dod-check` |
| `agent-context/claude/agents/` | I 4 subagent di §3 |
| `agent-context/claude/hooks/lint-changed.sh` | Lint e formattazione automatici del file appena modificato |
| `agent-context/claude/mcp.json` | Server MCP: documentazione AWS e AgentCore |
| `agent-context/github/pull_request_template.md` | Template delle PR con la Definition of Done |
| `agent-context/kiro-steering/` | Le stesse regole in formato Kiro |
| `agent-context/install.sh` | Crea i collegamenti: `CLAUDE.md`, `AGENTS.md`, `.claude/`, `.mcp.json`, `.kiro/`, `.github/` |
| `agent-context/README.md` | Spiegazione della cartella |

### 4.4 File generati da `install.sh` (non modificarli direttamente)

`CLAUDE.md`, `AGENTS.md`, `.claude/settings.json`, `.claude/commands`, `.claude/agents`, `.mcp.json`, `.kiro/steering`, `.github/pull_request_template.md`

### 4.5 Codice

Comandi dalla root: `npm ci && uv sync`, poi `npm run check` (lint, type check, test, `cdk synth` con cdk-nag; gli stessi della CI). Dettagli in `agent-context/AGENTS.md` §6.

| Cartella | Cosa conterrà |
|---|---|
| `infra/` | App CDK in TypeScript: config `dev`/`demo`, construct `PythonLambda`, `FoundationStack` e `DataStack` completi, gli altri 7 stack vuoti e collegati; test in `infra/test/` |
| `agent/` | Package `suppliagent_agent` (vuoto); conterrà agente Strands per AgentCore, prompt per ruolo, `evals/` |
| `services/` | Lambda Python (da fare): ricezione, debounce, Notifier, PDF, ERP mock, catalogo, proattività, console; `tools/` (tool dell'agente) e `shared/` (package `suppliagent_shared`, vuoto) |
| `console/` | Console back office e chat agenti (React + Vite); oggi solo `package.json` segnaposto (T-61) |
| `seed/` | Dati di prova anonimizzati/sintetici e script di caricamento/reset; `seed/private/` per i dati grezzi del cliente (esclusa da git) |
| `scripts/` | Utility (deploy, reset demo, test end-to-end) |

### 4.6 Altri file

| File | Contenuto |
|---|---|
| `assets/brand/` | Logo SuppliAgent (icona, versioni chiara e scura, SVG e PNG) |
| `LICENSE` | Licenza MIT (requisito di gara: licenza open source visibile) |
| `.gitignore`, `.gitattributes`, `.editorconfig` | Igiene del repo (esclusi segreti, dati del cliente, build) |
| `.env.example` | Modello del file `.env` locale (che non va mai committato) |

Descrizione per GitHub *About*: *"Agentic AI ordering assistant for HoReCa food distributors: restaurants order on WhatsApp with a photo of a handwritten note, voice or text; the agent matches the catalog, clarifies, confirms via email/SMS/RCS and suggests reorders. Built on Amazon Bedrock AgentCore + AWS End User Messaging for the AWS CDS Agentic AI Hackathon."*
Topic: `aws`, `amazon-bedrock`, `bedrock-agentcore`, `strands-agents`, `whatsapp`, `aws-end-user-messaging`, `amazon-ses`, `rcs`, `agentic-ai`, `aws-cdk`, `hackathon`.

---

## 5. Calendario dettagliato

| Giorno | Tu | Claude Code (backlog) |
|---|---|---|
| **Ven 23/10** | §1.1 push e PR · §1.2 account, canali, cliente, Devpost, ACE · owner degli stream | ✅ T-01, T-03, T-02 · T-28 testi template · avvio T-04, T-20, T-42 |
| **Sab 24/10** | Dataset bigliettini e vocali · approvazioni deploy `dev` · revisione PR | T-04, T-05, T-21, T-23, T-22, T-24, T-40, T-41, T-60, T-61 · T-06 · prototipo lettura bigliettini |
| **Dom 25/10** | Prove S1 dal telefono · revisione PR | T-07, T-25, T-43, T-44, T-45, T-46, T-47, T-48, T-49, T-62 · T-26, T-27, T-09 |
| **Lun 26/10** | Prove S1–S7 · **code freeze la sera** | T-08, T-50, T-51, T-52, T-63, T-64, T-65 · avvio T-53 |
| **Mar 27/10** | Deploy `demo` · video · ACE · testi submission | T-10, T-11, T-53 (report), T-66 · bugfix |
| **Mer 28/10** | **Submission al mattino** · controllo link | Solo bugfix |

---

## 6. Decisioni aperte (da chiudere oggi)

- [ ] Owner di ogni stream (IN, CH, AG, CO)
- [ ] Mostrare o no i prezzi al ristoratore
- [ ] Ordini inseriti dall'agente di commercio: serve anche la conferma del ristoratore?
- [ ] Regole reali di consegna, cut-off, minimi, multipli (dal cliente)
- [ ] Uso del nome e del marchio del cliente (submission, video, case study)
- [ ] Repo pubblico o privato al momento della submission
