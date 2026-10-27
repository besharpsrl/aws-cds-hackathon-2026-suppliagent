# SuppliAgent – Da dove partire

> **Documento unico di handoff**: cosa devi fare tu, cosa fa Claude Code e come farglielo fare, quali file esistono e cosa contengono.
> Usalo come scaletta: segui le sezioni in ordine e spunta le caselle.
> Aggiornato al **23/10/2026 pomeriggio** (P0 completata) · Consegna Devpost: **28/10/2026 ore 21:00** (ora italiana) · Obiettivo interno: submission **entro le 15:00 del 28/10** · Code freeze **27/10 ore 18:00**

---

## 0. A che punto siamo

| Area | Stato |
|---|---|
| Idea, perimetro, documentazione funzionale e tecnica | ✅ pronta (da validare con il team) |
| Architettura AWS e diagramma | ✅ pronti |
| Backlog: 39 task da fare in `docs/04_BACKLOG.md`; il completato è in `docs/DONE.md` | ✅ pronto |
| Contesto per Claude Code (istruzioni, comandi, subagent, hook, MCP) | ✅ attivo |
| Repo GitHub `besharpsrl/aws-cds-hackathon-2026-suppliagent` | ✅ creato, pubblico, CI verde su `main` · flusso PR in §1.1 (serve `gh` per far aprire le PR a Claude Code) |
| Codice | ◐ **P0 + T-13 fatti e su `main`**: monorepo, CI, app CDK con Foundation e Data stack, tag obbligatori · primi 3 bigliettini di eval con soluzione attesa (`agent/evals/data/bigliettini/`) · deploy `dev` fatto |
| Account AWS | ◐ account `471112860008` (condiviso con altri progetti beSharp), bootstrap già presente, **primo deploy `dev` fatto il 25/10** (Foundation + Data) · modello **Amazon Nova** (Claude non abilitato sull'account, §1.2) · tag obbligatori: `Project=Hackathon AWS CDS`, `Owner=matteo.goretti@besharp.it` |
| Devpost | ◐ iscritti e team creato |
| Team | Una sola persona (MG): tutti gli stream sono suoi, lavoro con sessioni Claude Code parallele (§3) |
| Canali (WhatsApp, SES, SMS/RCS), dati del cliente, ACE | ⬜ da fare (§1) |

Calendario sintetico (dettaglio in §5):

| Giorno | Tu | Claude Code |
|---|---|---|
| **Ven 23/10** | ✅ Repo, Devpost, account AWS | ✅ P0 (T-01, T-03, T-02) |
| **Sab 24/10** | Merge P0 + T-13, bootstrap, primo deploy `dev`, avvio sessioni (§3bis) | ✅ T-13 · T-28 (testi) · ◐ T-04 (anagrafiche e storico, 26/10) · ✅ T-42 → T-40 + T-41 ridotti (26/10) |
| **Dom 25/10** | Revisione PR e deploy · prove con il simulatore | **h13** walking skeleton via simulatore · **h20** S1 core via simulatore · console T-60/T-61 |
| **Lun 26/10** | Colleghi: cliente, Meta/WhatsApp, DNS SES, bigliettini · template a Meta | WhatsApp reale · T-25, T-49/T-63 · T-62 su API reali · dati cliente |
| **Mar 27/10** | **Code freeze ore 18:00** · deploy `demo` · video | Bugfix · T-10 · eval leggera · README giudici |
| **Mer 28/10** | **Submission entro le 15:00** · controllo link | Solo bugfix |

---

## 1. Cosa devi fare tu

Le cose che Claude Code non può fare: account, accessi, contatti con cliente e Meta, decisioni, approvazioni, video, submission.

### 1.1 Flusso Git di ogni task (deciso il 26/10)

1. **Claude Code** lavora su un branch `feat/FN-xx-…` (un task, o un gruppo di task accoppiati: vedi `docs/04_BACKLOG.md` §1bis), fa push e **apre la PR**.
2. **Tu** revisioni la PR e fai il **merge su `main`** quando la CI è verde, sempre con **"Create a merge commit"** (mantiene gli hash citati in `docs/DONE.md` e un commit per task; niente squash/rebase). Niente push diretti su `main`, anche da admin.
3. **Deploy** da locale, da `main` aggiornato: `git switch main && git pull && cd infra && npx cdk deploy <stack> -c env=dev` (lo può lanciare Claude Code su tua richiesta).
4. I branch già confluiti restano su GitHub (storia tracciata).

- [x] P0 e T-13 su `main` (25/10), CI verde sui push
- [ ] Installare la GitHub CLI perché Claude Code possa aprire le PR: `brew install gh && gh auth login`
- [x] GitHub → *Settings → Branches*: regola su `main` (PR obbligatoria, CI verde, niente force push)
- [x] GitHub → *About*: descrizione e topic (vedi §4.6)
- [x] Membri del team aggiunti al repo

### 1.2 Oggi – account, canali, cliente, gara

**Strumenti sul tuo Mac** → `docs/HANDOFF_CLAUDE_CODE.md` §2–§3
- [ ] Strumenti installati (Node 22, Python 3.12, uv, AWS CLI, gh, CDK, Docker Desktop, Claude Code)
- [ ] Profilo AWS `suppliagent-dev` funzionante (`aws sts get-caller-identity`)

**Account AWS** (eu-west-1)
- [x] Account: `471112860008`, condiviso con altri progetti → nessun AWS Budget creato dal CDK; costi isolati con i tag (attivare `Project` ed `Env` come *cost allocation tags* in Billing)
- [x] Accesso ai modelli Bedrock: **Amazon Nova** Pro/Lite e Titan Text Embeddings V2 funzionanti (25/10) → il progetto usa Nova
- [ ] (Opzionale) Chiedere al distributore/AWS l'abilitazione di Claude: l'account è in *channel program* e risponde `Access to this model is not available for channel program accounts`; se arriva, pianifichiamo il passaggio
- [x] CDK bootstrap: già presente sull'account (`CDKToolkit` v30), non rifatto
- [x] Prima del primo deploy: task **T-13** (tag obbligatori in CDK) fatto da Claude Code (branch `feat/FN-32-mandatory-tags`, vedi `docs/DONE.md`)
- [ ] Risorse create a mano da console (EUM Social/numero WhatsApp, eventuali identità SES): aggiungere gli stessi due tag
- [x] Primo deploy `dev` (25/10, da locale con profilo `default`): 9 stack, 18 tabelle, 6 bucket, CMK, event bus, 16 parametri SSM (dettagli in `docs/DONE.md`)
- [ ] Crediti: quelli AWS ($50) probabilmente non arrivano in tempo (3–5 giorni, scadono il 31/10) → confermare un budget interno beSharp

**Canali** → `docs/INFRASTRUCTURE_DESIGN.md` §5.1 e §11
- [ ] **WhatsApp**: account WhatsApp Business collegato ad AWS End User Messaging Social **in eu-west-1**, numero dedicato, messaggio di prova → procedura passo passo in `docs/WABA_SETUP.md`
- [ ] **Template WhatsApp** inviati a Meta: testi pronti (T-28, `services/notifier/whatsapp_templates/`, revisione in `docs/09_CONTENT_AND_TEMPLATES.md`); appena la WABA è collegata a EUM Social si inviano con il task **T-29** (comando in 09 §1)
- [x] **SES**: dominio verificato (DNS), uscita dalla sandbox (27/10), record MX per la ricezione
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
- [ ] Martedì 27 ore 18:00: **code freeze**

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
| **P0 – Fondamenta** | 23/10 | Monorepo, CI, app CDK con Foundation e Data stack, template WhatsApp | ✅ T-01, T-03, T-02, T-13, T-28 (testi) · invio a Meta → T-29 |
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
| `security-reviewer` | Autorizzazione per ruolo, prompt injection, dati personali, permessi. **Solo su richiesta esplicita** (deciso il 26/10: troppi token) |

I **team di agenti** non servono finché ogni stream ha una persona (guida §11).


## 3bis. Piano per un team di una persona (deciso il 24/10)

**Principio**: nel weekend S1 end-to-end testato **con il simulatore** (T-14), senza dipendere da Meta; lunedì si collega WhatsApp reale e si rifinisce; martedì alle 18:00 code freeze. Perimetro Must/Should/Could in `docs/04_BACKLOG.md` §1bis.

**Sessioni di Claude Code** (massimo 3 in parallelo: il limite è la tua attenzione su piani e PR): **Integrazione** (`claude` nella checkout principale: merge, stack condivisi Foundation/Data, `demo`), **Piattaforma** (`claude -w piattaforma`, stream IN + CH), **Agente** (`claude -w agente`, AG), **Console** (`claude -w console`, CO). Ogni sessione fa deploy solo dei propri stack (`npx cdk deploy <stack> --exclusively -c env=dev`). Si avvia con `/sa-next-task`.

### Assegnazione dei task (fonte unica, deciso il 26/10)

Questa sezione assegna **tutti** i task aperti a una sessione, in ordine, con le dipendenze verso altre sessioni o verso di te. `docs/04_BACKLOG.md` resta la descrizione completa di ogni task (anche di quelli non ancora assegnati), `docs/DONE.md` il registro del fatto.

**Colonna "Attende"** (solo dipendenze esterne alla sessione; quelle interne sono date dall'ordine):
- **T-xx (sessione)** = **bloccante**: finché T-xx non è ✅ qui e su `main`, il task non si inizia.
- ↺ T-xx (sessione) = **di integrazione**: si procede con mock/stub dichiarati nella PR; il collegamento si fa quando T-xx è su `main`.

**Stato**: ☐ da fare · ◐ in corso (branch) · ⏸ in attesa di … · ✅ fatto (PR). Priorità come in `docs/04_BACKLOG.md` §1bis.

**Integrazione** (con te)

| # | Task | Attende | Priorità | Stato |
|---|---|---|---|---|
| 1 | Merge delle PR, deploy degli stack condivisi da `main` | – | – | continuo |
| 1b | **Email SES**: sottodominio, deploy di `channels` con `-c sesDomain`, record DNS (DKIM, MX), prova di ricezione, richiesta di uscita dalla sandbox | dominio e via libera sulla zona DNS (tu) | Must | ✅ 26/10: dominio `suppliagent.stonecutters.besharp.net` verificato, ricezione ok; **uscita dalla sandbox ottenuta il 27/10**. **Ogni deploy di `channels` ora deve passare `-c sesDomain=suppliagent.stonecutters.besharp.net`** |
| 1c | **WhatsApp**: WABA collegata ad AWS (`docs/WABA_SETUP.md` parte 1), poi destinazione eventi, `-c waPhoneNumberId`, prova di ricezione | numero di telefono (tu) | Must | ☐ |
| 2 | T-05 dataset eval (≥ 15 bigliettini, vocali, email, conversazioni attese) | foto e vocali (tu, §1.3) | Should | ☐ |
| 3 | T-11 ACE, PNG del diagramma, testi submission (EN) | – (avviabile subito) | Should | ☐ |
| 4 | T-10 ambiente `demo`, reset, README giudici | code freeze (tutti i Must) | Should | ☐ |
| 5 | T-12 copione e video | T-10 · registrazione (tu) | Should | ☐ |

**Piattaforma** (IN + CH)

| # | Task | Branch / PR | Attende | Priorità | Stato |
|---|---|---|---|---|---|
| 1 | T-21 + T-23 | `feat/FN-01-inbound-pipeline` | – | Must | ✅ PR #16 |
| 2 | T-22 + T-24 base (Notifier con modalità sandbox) | `feat/FN-26-debounce-notifier` | – | Must | ✅ PR #22 |
| 2b | T-15 valori dei canali nella config per ambiente | `feat/FN-01-channel-config` | Email SES (Integrazione 1b) ✅; `waPhoneNumberId` resta da valorizzare con WhatsApp (Integrazione 1c) | Must | ✅ PR #24 |
| 3 | T-14 simulatore canali + test end-to-end | `feat/FN-31-channel-simulator` | ↺ T-41 (Agente) per la risposta reale | Must | ✅ PR #26 |
| 4 | T-07 ERP mock + `order_pdf` + regola `order.confirmed` | `feat/FN-13-erp-mock-order-pdf` | – | Must | ✅ PR #28 |
| 5 | T-25 messaggi interattivi WhatsApp | | – | Should | ☐ |
| 6 | T-26 (solo email di conferma con PDF) | | ↺ T-46 (Agente) per i dati d'ordine reali | Must | ☐ |
| 7 | T-29 invio template a Meta (ID EUM Social sempre da SSM) | | WABA collegata (tu) | Should | ☐ |
| 8 | T-08 `ProactiveStack` | | – | Could | ☐ |
| 9 | T-24 completo, T-27 RCS | | – | Could | ☐ |
| 10 | T-67 errori del turno nel Dispatcher (cortesia E-05, handoff E-12) | | ↺ T-49 (Agente) | Should | ☐ |

**Agente** (AG)

| # | Task | Branch / PR | Attende | Priorità | Stato |
|---|---|---|---|---|---|
| 1 | T-40 + T-41 (versione ridotta) | `feat/FN-03-agent-runtime` | – | Must | ✅ PR #15 |
| 2 | T-43 `order_intake` (lettura bigliettini) | `feat/FN-05-order-intake` | – | Must | ✅ PR #21 |
| 3 | T-06 (**solo** indice prodotti S3 Vectors, niente Knowledge Base; il resto è T-06b, non assegnato) | `feat/FN-07-product-index` | – | Must | ✅ PR #25 |
| 4 | T-44 `catalog` (`match_products`, `search_catalog`; `ask_product_sheets` è T-44b, non assegnato: attende T-06b) | `feat/FN-07-catalog-matching` | – | Must | ✅ PR #27 |
| 5 | T-45 + T-46 + T-47 con il resto di T-04 (catalogo, listini, stock) | `feat/FN-12-order-flow` | ↺ T-07 ✅, ↺ T-25 (Piattaforma: senza, risposte testuali), ↺ T-22 ✅ | Must | ✅ PR da aprire |
| 6 | T-49 `handoff_to_human` | | T-22 ✅ (il controllo `mode = HUMAN` è già nel Router) | Should | ☐ |
| 7 | T-54 (prima Guardrail e Memory) | | – | Should | ☐ |
| 8 | T-53 eval leggera | | ↺ T-05 (Integrazione): si parte dai 3 bigliettini in `agent/evals/` | Should | ☐ |
| 9 | T-48 primo contatto e consenso | | – | Should | ☐ |
| 10 | T-50 `reco` | | **T-08 (Piattaforma)** | Could | ☐ |
| 11 | T-51 `sales` | | – (dopo T-50) | Could | ☐ |
| 12 | T-52 turno proattivo di riordino | | **T-08 (Piattaforma)**, **T-24 (Piattaforma)** | Could | ☐ |

**Console** (CO)

| # | Task | Branch / PR | Attende | Priorità | Stato |
|---|---|---|---|---|---|
| 1 | T-66 ruolo `judge` in sola lettura, rifiniture demo | `feat/FN-31-judge-demo-polish` | – | Could | ✅ PR #13 |
| 2 | T-62 parte API (inbox e dettaglio su dati reali, correzione riga; vista chiave della demo: bigliettino accanto alle righe) | | **T-46 (Agente)** | Must | ☐ |
| 3 | T-63 conversazioni live + take over / release | | **T-49 (Agente)** | Should | ☐ |
| 4 | T-64 chat web agenti di commercio | | **T-41 (Agente)** | Could | ☐ |
| 5 | T-09 `AnalyticsStack` | | – | Could | ☐ |
| 6 | T-65 dashboard KPI | | – (dopo T-09) | Could | ☐ |

**Regole**
- **Scelta del task**: la sessione prende il primo task della propria tabella non ✅ con le dipendenze **bloccanti** soddisfatte. Se il task successivo è bloccato, lo segna ⏸ "in attesa di T-xx (sessione)", lo **segnala** e passa al successivo sbloccato; se non ce ne sono, si ferma e lo dice.
- **Fine task (nella stessa PR)**: qui lo stato diventa ✅ con il numero di PR; in `docs/04_BACKLOG.md` la riga si rimuove; in `docs/DONE.md` si aggiunge la voce. Se il lavoro crea, divide o rinvia task, si aggiornano **entrambi** i file (descrizione nel backlog, assegnazione qui).
- **Task nuovi o liste esaurite**: un task del backlog non presente qui non è assegnato; prima di iniziarlo lo si aggiunge alla tabella della propria sessione (stessa PR del task).
- Ogni sessione fa `git pull --rebase origin main` prima di iniziare un task e prima di ogni deploy.
- Nessuna sessione fa deploy di uno stack di un'altra; gli stack condivisi solo dalla sessione Integrazione.
- Un task = una PR piccola, **tranne i task accoppiati sullo stesso stack**, che vanno in una sola PR con un commit per task (gruppi in `docs/04_BACKLOG.md` §1bis). Claude Code apre la PR, tu revisioni e fai merge appena la CI è verde, così le altre sessioni ripartono da `main` aggiornato.
- Checkpoint: **Dom h13** "ciao" via simulatore → risposta dell'agente; **Dom h20** foto via simulatore → righe, matching, conferma, ERP mock, email PDF; **Lun h18** stesso flusso su WhatsApp reale.
- Se un checkpoint salta di più di 3 ore: si taglia dal Should, non si sposta il freeze.

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
| **Ven 23/10** | ✅ Repo, Devpost, account AWS | ✅ P0 (T-01, T-03, T-02) |
| **Sab 24/10** | Merge P0 + T-13, bootstrap, primo deploy `dev`, avvio sessioni (§3bis) | ✅ T-13 · T-28 (testi) · ◐ T-04 (anagrafiche e storico, 26/10) · ✅ T-42 → T-40 + T-41 ridotti (26/10) |
| **Dom 25/10** | Revisione PR e deploy · prove con il simulatore | **h13** walking skeleton via simulatore · **h20** S1 core via simulatore · console T-60/T-61 |
| **Lun 26/10** | Colleghi: cliente, Meta/WhatsApp, DNS SES, bigliettini · template a Meta | WhatsApp reale · T-25, T-49/T-63 · T-62 su API reali · dati cliente |
| **Mar 27/10** | **Code freeze ore 18:00** · deploy `demo` · video | Bugfix · T-10 · eval leggera · README giudici |
| **Mer 28/10** | **Submission entro le 15:00** · controllo link | Solo bugfix |

---

## 6. Decisioni aperte (da chiudere oggi)

- [ ] Owner di ogni stream (IN, CH, AG, CO)
- [ ] Mostrare o no i prezzi al ristoratore
- [ ] Ordini inseriti dall'agente di commercio: serve anche la conferma del ristoratore?
- [ ] Regole reali di consegna, cut-off, minimi, multipli (dal cliente)
- [ ] Uso del nome e del marchio del cliente (submission, video, case study)
- [ ] Repo pubblico o privato al momento della submission
