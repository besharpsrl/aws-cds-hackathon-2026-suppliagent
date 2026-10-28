# SuppliAgent – Da dove partire

> **Punto di partenza** del team: come si lavora, stato, timeline, backlog, azioni manuali e decisioni.
> **Backlog e azioni manuali: [GitHub Issues](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues)** (fonte unica dei task: sotto-issue per flusso, dipendenze, priorità, assegnatario).
> Cosa fa il prodotto e come si comporta: [`docs/`](./docs/README.md) (indice di tutti i documenti) · Regole per gli agenti di sviluppo: [`AGENTS.md`](./agent-context/AGENTS.md).
> Aggiornato al **28/10/2026** · Scadenza Devpost **28/10 ore 21:00** (ora italiana)

**Team**: MG, MM, FZ (sviluppo) · PS (Team Representative su Devpost: invia la submission).

---

## 1. Punto di partenza

### 1.1 Se arrivi adesso (10 minuti)

1. Leggi §2 (stato) e §3 (timeline) di questo file.
2. Setup (una volta): Node 22, Python 3.12, `uv`, AWS CLI, `gh`, CDK v2, Docker Desktop.
   ```bash
   bash agent-context/install.sh          # collega AGENTS.md, CLAUDE.md, .claude/, .mcp.json, .github/
   npm ci && uv sync
   npm run check                          # lint + typecheck + test + cdk synth (come la CI)
   aws sts get-caller-identity            # account 471112860008, region eu-west-1 (profilo usato finora: default)
   ```
3. Apri una sessione del tuo agente di sviluppo in un worktree (§1.5) e lancia **`/sa-next-task B`** (con la lettera della tua corsia; Copilot e Claude Code): sceglie il prossimo task libero della corsia, lo prende, lo implementa e apre la PR. Per un task preciso: `/sa-next-task T-xx`; per più task di fila: `/sa-next-task B loop`.
4. Per capire **cosa** costruire: scheda `FN-xx` in [03](./docs/03_FUNCTIONAL_SPEC.md) e flussi `F-xx` in [02](./docs/02_TECHNICAL_FLOWS.md); architettura in [INFRASTRUCTURE_DESIGN](./docs/INFRASTRUCTURE_DESIGN.md).

### 1.2 Come prendere e chiudere un task

- **Backlog**: [issue aperte](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues) con etichette (§4.1); issue madri (etichetta `flusso`) con i task come sotto-issue; dipendenze come *blocked by*.
  ```bash
  gh issue list --label corsia:B --state open --json number,title,assignees,labels   # i task della corsia
  gh issue view <n>                                                                   # descrizione, dipendenze, madre
  ```
  Vista ad albero (madre → task) e board: [GitHub Project](https://github.com/orgs/besharpsrl/projects/1); le issue nuove vanno aggiunte con `--project "SuppliAgent – backlog hackathon"`.
- **Prendere**: un'issue senza assegnatario e senza *blocked by* aperti → `gh issue edit <n> --add-assignee @me`, branch `feat/FN-xx-…`, push e **PR in draft** con `Closes #<n>` nel corpo e il piano. Nessuna modifica a questo file. Le dipendenze di integrazione (scritte nell'issue) non bloccano: si lavora con mock/stub dichiarati nella PR.
- **Chiudere**: PR pronta con la Definition of Done e la sezione **Deploy** compilata (stack, comandi completi, script prima e dopo, oppure "nessun deploy"); al merge l'issue si chiude da sola. Se il lavoro crea o rinvia task, si apre o si modifica un'issue (`gh issue create --parent <madre> --blocked-by …`).
- **Git**: un task = una PR (salvo task accoppiati, §4.5). CI e review automatica di Copilot partono quando la PR esce dalla bozza (`gh pr ready`). Merge su `main` con CI verde e *Create a merge commit*: PR **a basso rischio** (solo `docs/` o file `.md`, solo `console/`, solo test o `agent/evals/`) con CI verde e review automatica di Copilot senza rilievi aperti: chi l'ha aperta può fare merge da solo. Tutte le altre (infra, `services/`, prompt e codice dell'agente, `seed/`, `.github/workflows/`, `agent-context/`): review di un'altra persona del team. Mai push o force push su `main`. `git pull --rebase origin main` prima di iniziare e prima della PR.
- **Deploy**: regole in §1.5. `dev` è l'**unico ambiente** (sviluppo, video e giudici): dopo l'invio della submission si fa deploy solo con conferma di MG.

### 1.3 Cosa non fare senza chiedere

Deploy dopo l'invio della submission, modifiche a risorse condivise (numero WhatsApp, dominio SES, template Meta), cambio di region/modello, servizi a costo fisso, cancellazione di dati o bucket, dati reali del cliente. Elenco completo: [AGENTS.md §11](./agent-context/AGENTS.md).

### 1.4 Note operative (problemi già incontrati)

- Dagli agenti di sviluppo il `cdk deploy` va lanciato **fuori dal sandbox** (il proxy interrompe i changeset con `Error: aborted`).
- Se dopo un deploy una Lambda ha `CodeSize` di poche centinaia di byte, l'asset è stato pubblicato vuoto (sintesi concorrente tra worktree): ripubblicare lo zip corretto con la stessa chiave e aggiornare il codice.
- Dopo un deploy di `agent`, le sessioni AgentCore già aperte restano sul codice vecchio: provare con una conversazione nuova.
- `cdk synth` a volte fallisce senza motivo riproducibile: rilanciare.
- Su `dev` l'invio è **reale** (`notifierSandbox = false`): il simulatore funziona solo col sandbox acceso, da accendere e rispegnere subito annunciandolo in chat (comandi in [CHANNELS_SETUP §1.4](./docs/CHANNELS_SETUP.md)), perché nel frattempo i telefoni veri non ricevono risposte.

### 1.5 Lavoro in parallelo

**Corsie** (punto di partenza, non un vincolo: chi resta senza lavoro prende un'issue libera di un'altra corsia annunciandolo). Dentro la corsia: prima i `must`, poi `should`, poi `could`.

| Corsia | Chi | Stack di cui fa il deploy |
|---|---|---|
| **A – Canali ed e2e** | MG | `messaging`, `channels` |
| **B – Agente** | MM | `agent`, `catalog` |
| **C – Console e materiali** | FZ | `console`, `proactive` |

`foundation`, `data`, `seed/reset.py`, `notifierSandbox` e T-73 (security review): MG.

**Sessioni**
- Al massimo **2 sessioni agente per persona**, ognuna in un **git worktree** proprio, aperto in una finestra VS Code separata (o `claude -w <nome>`):
  ```bash
  git fetch origin && git worktree add ../sa-<task> -b feat/FN-xx-<breve> origin/main
  code ../sa-<task>                       # poi nella chat: /sa-next-task T-xx
  git worktree remove ../sa-<task>        # dopo il merge
  ```
- Un task per chat: dopo la PR si apre una **chat nuova** (fa le veci di `/clear`).
- L'agente lavora senza fermarsi sul piano quando l'issue ha criteri chiari (il piano va nella PR in draft); chiede solo per ambiguità, deploy, comandi `aws` che modificano risorse, `rm`, push. I comandi sicuri sono approvati in automatico (`.vscode/settings.json`, `agent-context/claude/settings.json`).
- A fine task la sessione apre la PR, riporta **cosa deployare e con quali comandi**, e può passare all'issue successiva libera e non bloccata, su un branch nuovo da `main` (mai sopra lavoro non mergiato).

**File caldi** (più task li toccano): prompt dell'agente e `agent/src/suppliagent_agent/turn.py` (corsia B ne è il riferimento), `infra/lib/stacks/agent-stack.ts` e `tool-schemas.ts` (B), `infra/lib/stacks/messaging-stack.ts` e `services/notifier` (A), `seed/data/*` (chi lo tocca lo dice). Regola: PR piccole, merge rapidi, rebase spesso; chi tocca un file caldo di un'altra corsia cambia solo il pezzo che gli serve e lo scrive nella PR.

**Deploy su `dev`** (un solo ambiente)
- Ognuno fa deploy **solo degli stack della propria corsia**, anche dal proprio branch per provarlo, **uno alla volta in tutto il team**: annuncio in chat ("deploy `agent` da `feat/…`"), poi `cd infra && npx cdk deploy suppliagent-dev-<stack> --exclusively -c env=dev`. Dopo il merge si rifà il deploy da `main`.
- Dopo il deploy: `CodeSize` delle Lambda non di poche centinaia di byte (§1.4); dopo `agent`, conversazione nuova.
- Prove: ognuno dal **proprio telefono** registrato (M-02); nessuno lancia `seed/reset.py` tranne MG, su richiesta.

**Subagent** (Copilot e Claude Code, definiti in `agent-context/claude/agents/`): `test-runner` per lint/test/synth con il solo riassunto degli errori; `aws-docs-researcher` prima di API nuove; `code-reviewer` a fine task. `security-reviewer` solo in T-73, non a ogni task.

**Comandi** (`.github/prompts/` per Copilot, `agent-context/claude/commands/` per Claude Code): `/sa-next-task [A|B|C] [T-xx] [loop]` (ciclo completo, con un solo controllo completo per task) · `/sa-dod-check` (Definition of Done, solo per lavoro fatto senza `/sa-next-task`) · `/sa-cds-check` (requisiti CDS, prima della submission; le regole sui client e sugli invii sono anche in CI, `tests/test_cds_usage.py`).

---

## 2. Stato del progetto (28/10)

**In sintesi**: tutti i flussi della gara sono su `dev` e provati da telefono (T-68): un ordine va dalla foto su WhatsApp a `CONFIRMED` → ERP mock → PDF via email, con conferma e avviso di consegna su RCS/SMS. Restano aperti: eval della lettura (T-05, T-53), copilota completo (T-51), chat web degli agenti (T-64), security review (T-73), video e invio Devpost (M-07, M-08). Stato per funzionalità: colonna *Gara* di [03 §4.1](./docs/03_FUNCTIONAL_SPEC.md).

| Area | Stato | Dettaglio |
|---|---|---|
| Infra di base (CDK, CI, tag, KMS, dati) | ✅ | 9 stack su `dev`, CI verde, cdk-nag |
| WhatsApp (EUM Social) | ✅ | Numero +39 345 246 0472, invio reale; pulsanti (T-25); 8 template `APPROVED`, fuori finestra 24h template e fallback su RCS/SMS (T-24, T-29); flussi 2 e 3 da telefono in IT ed EN (T-68). Dettagli: [CHANNELS_SETUP](./docs/CHANNELS_SETUP.md) |
| Email (SES) | ✅ | Dominio `suppliagent.stonecutters.besharp.net` fuori sandbox; conferma con PDF (T-26); ordine via email e risposte nello stesso thread (T-26b); allegati PDF/Excel no |
| SMS/RCS | ✅ | Agente RCS di test con tester Android, sender ID `SUPPLIAGENT` one-way (M-11); conferma breve e avviso di consegna con *Ricevuto / Segnala problema* (T-27); RCS non arriva su iPhone in Italia |
| Pipeline (Router, debounce, Dispatcher, Notifier) | ✅ | Errori del turno: cortesia al primo, handoff `LOW_CONFIDENCE` al secondo (T-67) |
| Agente (AgentCore + Strands, Nova `eu.`) | ✅ | Ruoli e tool; informativa e consenso (T-48); Memory, Guardrail, tracce OTel (T-54) |
| Identificazione e accesso giudici | ✅ | Clienti di prova `C90001`–`C90003` verificati subito (T-71); utente console `judge` (M-06) |
| Lettura bigliettini (`order_intake`) | ◐ | 62% di righe corrette sul corsivo: eval da completare (T-05, T-53) |
| Matching catalogo e schede tecniche | ✅ | S3 Vectors; Knowledge Base con 12 schede sintetiche e citazione (T-06b, T-44b) |
| Ordine, ERP mock, PDF | ✅ | Stock, prezzi, consegne, stato, modifica/annullo, sweeper |
| Console | ◐ | Inbox, dettaglio con bigliettino, correzione riga (T-62); conversazioni e handoff con polling 2 s (T-63); dominio `app.suppliagent.stonecutters.besharp.net`; chat web agenti aperta (T-64) |
| Copilota agenti | ◐ | Suggerimenti `reco` (T-50); briefing, agenda e ordine per conto del cliente aperti (T-51) |
| Riordino proattivo | ✅ | Insight notturni e `reorder.due` (T-08), turno proattivo con template (T-52) |
| Analytics e KPI | – | Tolti (§4.4) |
| Submission | ◐ | README giudici e deploy (T-10), diagramma e testi (T-11), copione (T-12) fatti; video (M-07) e Devpost (M-08) aperti |
| Security review | ☐ | T-73 |

**Limiti noti** (da tenere presenti nella demo):
- il matcher chiede conferma per "farina tipo 00 da 25 kg" (due candidati vicini); Nova a volte non converte "5 kg di farina" in sacchi da 25 kg;
- sui bigliettini difficili Nova legge male parte delle righe e può fare più di 5 domande in un messaggio (T-05, T-53); a volte chiude il turno con "ti faccio sapere" senza chiamare i tool (rispondere "ok" lo sblocca);
- nessun controllo di stock al momento della conferma (solo prima); `cancel_order` non avvisa l'ERP;
- fuori dalla finestra 24h di WhatsApp la risposta dell'operatore dalla console non parte (`409 channel_unavailable`, [02 F-14](./docs/02_TECHNICAL_FLOWS.md));
- rischi di sicurezza accettati: [INFRASTRUCTURE_DESIGN §12](./docs/INFRASTRUCTURE_DESIGN.md).

---

## 3. Timeline

| Quando | Cosa |
|---|---|
| ✅ 12/10–27/10 | Concept, documenti, P0, pipeline, agente, ordini, console, canali reali |
| **Mer 28/10** | Sviluppo fino alla scadenza; T-73 security review su `main`; M-07 video, M-08 Devpost compilato e **inviato** (PS) |
| 28/10 ore 21:00 | Scadenza Devpost: da qui deploy su `dev` solo con conferma di MG |
| fino al 12/11 17:00 PT (13/11 02:00 IT) | M-10: `dev` attivo per i giudici, costi sotto controllo |
| dal 14/11 | Spegnimento dell'ambiente: [TEARDOWN](./docs/TEARDOWN.md) |
| ~19/11 | Annuncio vincitori |

---

## 4. Backlog

Il backlog è su **[GitHub Issues](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues)**: ogni task `T-xx` e ogni azione manuale `M-xx` è un'issue (il titolo inizia con l'ID), sotto-issue della madre del suo flusso, con le dipendenze come *blocked by*.

### 4.1 Etichette e priorità

- **`must`**: senza, la demo o la submission non stanno in piedi (flussi 1, 2, 5a, 9 e materiali) · **`should`**: completa i flussi 2–5 e la qualità tecnica · **`could`**: flussi 6–8; quello che non è pronto per il video ci va come "prossimi passi".
- **`stream:CH|AG|CO|IN`**: area (canali, agente, console, infra/dati/materiali) · **`corsia:A|B|C`**: corsia di default (§1.5) · **`manual`**: azione manuale · **`flusso`**: issue madre.
- **Stato**: aperta senza assegnatario = libera · assegnata con PR draft = in corso · chiusa = fatta (PR mergiata).
- **Milestone**: `Sviluppo` · `Submission` · `Judging fino al 12/11`.

### 4.2 Issue madri

Ogni flusso utente ha la sua issue madre (colonna *Madre* di §4.3). Le altre: [#44](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/44) qualità tecnica (T-54, T-05, T-53, T-73) · [#45](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/45) demo e submission (T-11, T-12, T-10, T-72) · [#46](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/46) azioni manuali (M-01…M-12).

### 4.3 I flussi utente (perimetro della gara)

Utenti: **ristoratore** (WhatsApp +39 345 246 0472 o email `ordini@…`), **agente di commercio** (WhatsApp o chat in console), **back office** (console), **giudice** (console in sola lettura + WhatsApp come un ristoratore). Ogni messaggio passa da: raccolta dei messaggi ravvicinati → un turno dell'agente (Amazon Nova su AgentCore) con i suoi tool → una sola risposta, inviata dal Notifier. Lo stato è in §2.

| # | Flusso | Passi | Madre | Task |
|---|---|---|---|---|
| 1 | Primo contatto e identificazione | Numero sconosciuto → l'assistente si presenta, chiede nome del locale e codice cliente → collega il numero al locale; informativa e consenso alle proposte | [#37](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/37) | T-71, T-48 |
| 2 | Ordine da foto | Foto del bigliettino (+ vocale) → righe lette → abbinamento al catalogo con lo storico → chiarimenti sulle righe incerte → sostituti, multipli, data di consegna e cut-off → riepilogo con totale → *Confermo* → ERP mock, numero d'ordine, PDF → email con PDF | [#38](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/38) | T-68, T-26, T-25, T-29 |
| 3 | Dopo l'ordine | Stato dell'ordine; modifica o annullo fino al cut-off del giorno prima; promemoria della bozza dopo 2 h, scadenza a mezzanotte | [#38](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/38) | T-68 |
| 4 | Ordine via email | Email a `ordini@…` con testo o foto → stesso flusso, risposte via email nello stesso thread | [#39](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/39) | T-26b |
| 5 | Supervisione in console | 5a elenco ordini e dettaglio con il bigliettino accanto alle righe · 5b correzione di una riga · 5c handoff: l'operatore prende la conversazione, risponde, la restituisce | [#40](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/40) | T-62, T-49, T-63, T-67 |
| 6 | Copilota per l'agente di commercio | "Cosa propongo alla Trattoria X?", briefing prima della visita, domande sulle schede tecniche, ordine per conto del cliente | [#41](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/41) | T-08, T-50, T-51, T-06b, T-44b, T-64 |
| 7 | Riordino proattivo | L'assistente scrive per primo ("di solito riordinate l'olio ogni 10 giorni…") → riordino con un tap | [#42](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/42) | T-24, T-52 |
| 8 | Consegna | Avviso il giorno della consegna (RCS con fallback SMS, oppure template WhatsApp) con *Ricevuto / Segnala problema* | [#43](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/43) | T-27 |
| 9 | Prova dei giudici | Dal README: numero WhatsApp e codice di prova → ordine da foto → console in sola lettura con il proprio ordine | [#37](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/37) | T-71, T-10 |

### 4.4 Tolti dal backlog

Il repo serve solo alla gara (decisione del 27/10): tolti **T-09** `AnalyticsStack` e **T-65** dashboard KPI (lo stack `analytics` vuoto resta per ora), **T-70** hardening (rischi accettati in [INFRASTRUCTURE_DESIGN §12](./docs/INFRASTRUCTURE_DESIGN.md)) e le domande per il cliente reale. Descrizioni originali in [`docs/OLD/04_BACKLOG.md`](./docs/OLD/04_BACKLOG.md).

### 4.5 PR accorpate

Task sullo stesso stack non testabili da soli: una PR, un commit per task. Finora: T-40 + T-41, T-45 + T-46 + T-47. Candidati: T-49 + T-63 (handoff), T-06b + T-44b (schede tecniche).

---

## 5. Azioni manuali

Sono le issue con etichetta **`manual`**, sotto-issue di [#46](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/46). Aperte al 28/10: [#81](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/81) M-07 video, [#82](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/82) M-08 Devpost (PS), [#84](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/84) M-10 ambiente per i giudici, [#75](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/75) M-01 foto dei bigliettini (per T-05), [#95](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/95) M-12 URL dell'informativa privacy.

```bash
gh issue list --label manual --state open
```

---

## 6. Decisioni

**Aperte**: nessuna per la gara.

**Prese**

| Data | Decisione |
|---|---|
| 28/10 | Documentazione consolidata: concept in `docs/01`, setup dei canali in `docs/CHANNELS_SETUP.md`, parametri solo in `docs/02` §7, mappa dei documenti solo in `docs/README.md` |
| 28/10 | CI solo su PR pronte e su `main`; review automatica di Copilot sulle PR; merge da soli per le PR a basso rischio (§1.2); un solo controllo completo per task |
| 28/10 | Si sviluppa fino alla scadenza Devpost; T-10 (ultimo deploy di `dev`) e la submission chiudono la giornata |
| 27/10 | Backlog e azioni manuali su GitHub Issues (sotto-issue per flusso, dipendenze *blocked by*); si prende un task assegnandosi l'issue, si chiude con `Closes #n` nella PR |
| 27/10 | Lavoro in parallelo su tre corsie (§1.5), max 2 sessioni per persona in worktree separati; comandi `/sa-next-task`, `/sa-dod-check`, `/sa-cds-check` nel repo |
| 27/10 | Gli agenti non attendono conferma sul piano se l'issue ha criteri chiari; ogni fine task riporta deploy e script con i comandi completi |
| 27/10 | Security review una sola volta a fine iterazione (T-73), non a ogni task |
| 27/10 | Un solo ambiente, `dev`, per sviluppo, video e giudici: l'ambiente `demo` è stato tolto da codice e documenti |
| 27/10 | Il repo serve solo alla gara: niente task o domande per il cliente reale; tolti T-09, T-65 (analytics/KPI) e T-70 (hardening) |
| 27/10 | Perimetro = flussi utente 1–9 (§4.3), con priorità Must/Should/Could; i flussi 6–8 sono Could |
| 27/10 | I giudici entrano con un codice cliente di prova che verifica subito il contatto (T-71); l'email per la conferma, se manca, la chiede l'assistente (T-26) |
| 27/10 | Prezzi mostrati al ristoratore (riepilogo con totale stimato) |
| 27/10 | Pulsanti WhatsApp per chiarimenti e conferma (T-25) |
| 27/10 | Repo pubblico (licenza MIT) |
| 27/10 | Regole di consegna, cut-off (18:00), minimi e multipli: quelle sintetiche del seed |
| 27/10 | Marchio del cliente non usato: brand fittizio, dati sintetici |
| 27/10 | Ordine inserito dall'agente di commercio: basta la sua conferma |
| 27/10 | Modello: Amazon Nova (`eu.`) per la gara; Claude non abilitato sull'account (*channel program*) |
| 27/10 | Crediti AWS dell'hackathon non richiesti (scaduti): costi su budget beSharp |
| 27/10 | Team: MG, MM, FZ sviluppo; PS Team Representative. Task non assegnati a priori: li prende chi è libero (§1.2) |
| 26/10 | Flusso Git: PR aperta dall'agente, merge commit da chi revisiona, deploy da locale |
| 26/10 | `security-reviewer` solo su richiesta esplicita |
| 26/10 | Coda `inbound` SQS standard + debounce applicativo con lock (SNS standard non consegna a FIFO) |
| 25/10 | Account `471112860008` condiviso: nessun AWS Budget nel CDK, costi isolati con i tag |

---

## 7. Fatto

Il fatto sono le [issue chiuse](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues?q=is%3Aissue+is%3Aclosed) con le loro PR (`git log --merges --oneline`). Storico dettagliato fino al 27/10: [`docs/OLD/DONE.md`](./docs/OLD/DONE.md).
