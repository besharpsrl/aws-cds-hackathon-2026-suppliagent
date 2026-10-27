# SuppliAgent – Da dove partire

> **Punto di partenza** del progetto: stato, timeline, lavoro in parallelo, flussi utente, decisioni e registro del fatto.
> **Backlog e azioni manuali: [GitHub Issues](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues)** (fonte unica dei task: sotto-issue per flusso, dipendenze, priorità, assegnatario).
> Comportamento e requisiti: [`docs/`](./docs/README.md) · Regole per gli agenti di sviluppo: [`AGENTS.md`](./agent-context/AGENTS.md).
> Aggiornato al **27/10/2026 ore 20:00** · Code freeze **28/10 ore 12:00** · Submission interna **28/10 ore 15:00** · Scadenza Devpost **28/10 ore 21:00** (ora italiana)

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

- **Backlog**: [issue aperte](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues) con etichette `must` / `should` / `could`, `stream:*`, `corsia:A|B|C`, `manual`; issue madri (etichetta `flusso`) con i task come sotto-issue; dipendenze come *blocked by*; milestone `Code freeze 28/10 12:00`.
  ```bash
  gh issue list --label corsia:B --state open --json number,title,assignees,labels   # i task della corsia
  gh issue view <n>                                                                   # descrizione, dipendenze, madre
  ```
  Vista ad albero (madre → task) e board: [GitHub Project](https://github.com/orgs/besharpsrl/projects/1); le issue nuove vanno aggiunte con `--project "SuppliAgent – backlog hackathon"`.
- **Prendere**: un'issue senza assegnatario e senza *blocked by* aperti → `gh issue edit <n> --add-assignee @me`, branch `feat/FN-xx-…`, push e **PR in draft** con `Closes #<n>` nel corpo e il piano. Nessuna modifica a questo file. Le dipendenze di integrazione (scritte nell'issue) non bloccano: si lavora con mock/stub dichiarati nella PR.
- **Chiudere**: PR pronta con la Definition of Done e la sezione **Deploy** compilata (stack, comandi completi, script prima e dopo, oppure "nessun deploy"); al merge l'issue si chiude da sola. Se il lavoro crea o rinvia task, si apre o si modifica un'issue (`gh issue create --parent <madre> --blocked-by …`).
- **Git**: un task = una PR (salvo task accoppiati, §4.5). CI e review automatica di Copilot partono quando la PR esce dalla bozza (`gh pr ready`). Merge su `main` con CI verde e *Create a merge commit*: PR **a basso rischio** (solo `docs/` o file `.md`, solo `console/`, solo test o `agent/evals/`) con CI verde e review automatica di Copilot senza rilievi aperti: chi l'ha aperta può fare merge da solo. Tutte le altre (infra, `services/`, prompt e codice dell'agente, `seed/`, `.github/workflows/`, `agent-context/`): review di un'altra persona del team. Mai push o force push su `main`. `git pull --rebase origin main` prima di iniziare e prima della PR.
- **Deploy**: regole in §1.5. `dev` è l'**unico ambiente** (sviluppo, video e giudici): dopo il code freeze si fa deploy solo con conferma di MG.

### 1.3 Cosa non fare senza chiedere

Deploy dopo il code freeze, modifiche a risorse condivise (numero WhatsApp, dominio SES, template Meta), cambio di region/modello, servizi a costo fisso, cancellazione di dati o bucket, dati reali del cliente. Elenco completo: [AGENTS.md §11](./agent-context/AGENTS.md).

### 1.4 Note operative (problemi già incontrati)

- Dagli agenti di sviluppo il `cdk deploy` va lanciato **fuori dal sandbox** (il proxy interrompe i changeset con `Error: aborted`).
- Se dopo un deploy una Lambda ha `CodeSize` di poche centinaia di byte, l'asset è stato pubblicato vuoto (sintesi concorrente tra worktree): ripubblicare lo zip corretto con la stessa chiave e aggiornare il codice.
- Dopo un deploy di `agent`, le sessioni AgentCore già aperte restano sul codice vecchio: provare con una conversazione nuova.
- `cdk synth` a volte fallisce senza motivo riproducibile: rilanciare.
- Su `dev` il **Notifier è in sandbox** (`notifierSandbox = true` in `infra/config/environments.ts`): le risposte sono registrate ma non inviate. Il simulatore (`scripts/simulate_channel.py`) funziona solo così. T-68 passa a invio reale: da quel momento il simulatore non si usa più (o si riaccende il sandbox per una prova e lo si rispegne). Il valore va cambiato nella config, non solo in SSM: ogni deploy sovrascrive il parametro.

### 1.5 Lavoro in parallelo

**Corsie** (punto di partenza, non un vincolo: chi resta senza lavoro prende un'issue libera di un'altra corsia annunciandolo). Dentro la corsia l'ordine è: prima i `must`, poi `should`, poi `could` (un task che blocca un `must` conta come `must`); le dipendenze *blocked by* fanno saltare i task non ancora pronti.

| Corsia | Chi | Stack di cui fa il deploy | Ordine |
|---|---|---|---|
| **A – Canali ed e2e** | MG | `messaging`, `channels` | T-68 → T-26 → T-25 → T-29 → T-26b → T-67 → *could*: T-24 → T-27 |
| **B – Agente** | MM | `agent`, `catalog` | T-71 → T-49 → T-48 → T-54 → T-05/T-53 → *could*: T-50 → T-51 → T-44b → T-52 |
| **C – Console e materiali** | FZ | `console`, `proactive` | T-62 → T-11 → T-12 → T-63 (dopo T-49) → *could*: T-06b, T-08, T-64 → dopo il freeze T-10, T-72 |

Dipendenze tra corsie: T-63 (C) aspetta T-49 (B); T-50 e T-52 (B) aspettano T-08 (C); T-44b (B) aspetta T-06b (C). `foundation`, `data`, `seed/reset.py`, `notifierSandbox` e T-73 (security review): MG.

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

**Subagent** (Copilot e Claude Code, definiti in `agent-context/claude/agents/`): `test-runner` per lint/test/synth con il solo riassunto degli errori; `aws-docs-researcher` prima di API nuove (Memory, Guardrail, messaggi interattivi, RCS, Knowledge Base); `code-reviewer` a fine task. `security-reviewer` solo in T-73, non a ogni task.

**Comandi** (`.github/prompts/` per Copilot, `agent-context/claude/commands/` per Claude Code): `/sa-next-task [A|B|C] [T-xx] [loop]` (ciclo completo, con un solo controllo completo per task) · `/sa-dod-check` (Definition of Done, solo per lavoro fatto senza `/sa-next-task`) · `/sa-cds-check` (requisiti CDS, prima della submission; le regole sui client e sugli invii sono anche in CI, `tests/test_cds_usage.py`).

### 1.6 Mappa dei documenti

| File | Contenuto |
|---|---|
| `START_HERE.md` | Questo file |
| `README.md` | Presentazione in inglese per GitHub e giudici, setup, passi manuali, "Try it" |
| `SUPPLIAGENT_SOLUTION.md` | Concept: problema, scenario demo, KPI, criteri di gara, rischi |
| [`docs/README.md`](./docs/README.md) | Indice di `docs/` e convenzioni sugli ID |
| `agent-context/` | Regole e strumenti per gli agenti di sviluppo (si modificano solo lì; `install.sh` li collega) |

---

## 2. Stato del progetto (27/10 ore 18:00)

**In sintesi**: la pipeline è completa su `dev` e un ordine va da messaggio a `CONFIRMED` → ERP mock → PDF **col simulatore**. WhatsApp reale riceve testo e foto fino all'agente, ma **la risposta sul telefono non è mai stata provata** (Notifier in sandbox). Mancano per la gara: e2e da telefono, ingresso dei giudici (T-71), email di conferma, console su dati reali, `dev` pronto per i giudici, materiali di submission. Poi, se c'è tempo, i flussi 6–8 (§4.3).

| Area | Stato | Dettaglio |
|---|---|---|
| Infra di base (CDK, CI, tag, KMS, dati) | ✅ | 9 stack su `dev`, CI verde, cdk-nag |
| WhatsApp (EUM Social) | ◐ | Numero +39 345 246 0472 collegato, ricezione ok; 8 template inviati a Meta, `PENDING` (T-29); invio reale mai provato (T-68) |
| Email (SES) | ◐ | Dominio `suppliagent.stonecutters.besharp.net` verificato, fuori sandbox, ricezione ok; email di conferma con PDF da fare (T-26) |
| SMS/RCS | ☐ | Could (T-27), servono registrazioni con tempi di attesa (M-11) |
| Pipeline (Router, debounce, Dispatcher, Notifier base) | ✅ | Errori del turno senza cortesia/handoff (T-67) |
| Agente (AgentCore Runtime + Gateway, Strands, Nova `eu.`) | ◐ | Versione ridotta: ruoli e tool ok; Memory e Guardrail da fare (T-54); primo contatto (T-48) |
| Identificazione di nuovi contatti | ◐ | Abbinamento ok, ma il contatto resta da verificare e non può ordinare: i giudici sono bloccati (T-71) |
| Lettura bigliettini (`order_intake`) | ✅ | 62% di righe corrette sul corsivo (3 note): da migliorare (T-05, T-53) |
| Matching catalogo (S3 Vectors) | ✅ | Schede tecniche (Knowledge Base) Could (T-06b, T-44b) |
| Ordine (stock, prezzi, consegne, stato, conferma, sweeper) | ✅ | Pulsanti WhatsApp da fare (T-25) |
| ERP mock + PDF ordine | ✅ | |
| Console (Cognito, inbox, dettaglio con bigliettino, ruolo `judge`) | ◐ | Online su `dev` ma con **dati mock** (T-62); live e handoff da fare (T-49, T-63) |
| Copilota agenti, riordino proattivo | ☐ | Could (flussi 6 e 7) |
| Analytics e KPI | – | Tolti (§4.4) |
| `dev` pronto per i giudici, README giudici | ☐ | T-10 |
| Materiali (diagramma, testi, video, ACE, Devpost) | ☐ | T-11, T-12, §5 |

**Limiti noti** (da tenere presenti nella demo):
- il matcher chiede conferma per "farina tipo 00 da 25 kg" (due candidati vicini); Nova a volte non converte "5 kg di farina" in sacchi da 25 kg;
- nessun controllo di stock al momento della conferma (solo prima); `cancel_order` non avvisa l'ERP;
- fuori dalla finestra 24h di WhatsApp niente template né fallback di canale;
- rischi di sicurezza accettati fino alla demo: [INFRASTRUCTURE_DESIGN §12](./docs/INFRASTRUCTURE_DESIGN.md).

---

## 3. Timeline

| Quando | Sviluppo (MG, MM, FZ) | Azioni manuali (§5) |
|---|---|---|
| ✅ 12/10–26/10 | Concept, documenti, P0, pipeline, agente, ordini, console su mock | Devpost, account AWS, SES, WABA |
| **Mar 27/10 sera** | Must: **T-68 per primo** (e2e da telefono), T-71, T-26, T-62, T-11, T-12; poi Should: T-25, T-48, T-49, T-54 | M-01 foto bigliettini, M-02 numeri tester, M-05 ACE, M-11 registrazioni SMS/RCS |
| **Mer 28/10 08:00–12:00** | Should: T-63, T-67, T-26b, T-05 + T-53, T-29; correzioni da T-68; **~10:00 T-73 security review** su `main`. Could (flussi 6–8) solo con i Must chiusi | M-06 utente `judge` |
| **Mer 28/10 ore 12:00** | **Code freeze**: dopo, solo bugfix bloccanti | |
| 12:00–13:00 | T-10: ultimo deploy di `dev` da `main`, reset, prova del flusso 9 | |
| 13:00–14:00 | T-72 (documenti) | M-07 registrazione e upload video |
| 14:00–15:00 | Supporto | M-08 Devpost compilato e **inviato** (PS), M-09 controllo link |
| 28/10 ore 21:00 | | Scadenza Devpost |
| fino al 12/11 17:00 PT | | M-10 ambiente attivo, costi sotto controllo |
| ~19/11 | | Annuncio vincitori |

Se T-68 non è verde entro le 08:00 del 28/10: si ferma tutto il resto e si lavora solo sull'e2e. Si taglia prima dal Could, poi dal Should; il freeze non si sposta.

---

## 4. Backlog

Il backlog è su **[GitHub Issues](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues)**: ogni task `T-xx` e ogni azione manuale `M-xx` è un'issue (il titolo inizia con l'ID), sotto-issue della madre del suo flusso, con le dipendenze come *blocked by*.

### 4.1 Etichette e priorità

- **`must`**: senza, la demo o la submission non stanno in piedi (flussi 1, 2, 5a, 9 e materiali) · **`should`**: completa i flussi 2–5 e la qualità tecnica · **`could`**: flussi 6–8, si iniziano solo quando tutti i `must` sono presi; quello che non è pronto al code freeze va nel video come "prossimi passi".
- **`stream:CH|AG|CO|IN`**: area (canali, agente, console, infra/dati/materiali) · **`corsia:A|B|C`**: corsia di default (§1.5) · **`manual`**: azione manuale · **`flusso`**: issue madre.
- **Stato**: aperta senza assegnatario = libera · assegnata con PR draft = in corso · chiusa = fatta (PR mergiata).
- **Milestone**: `Code freeze 28/10 12:00` · `Submission 28/10 15:00` · `Judging fino al 12/11`.

### 4.2 Issue madri

| Issue | Flussi | Task |
|---|---|---|
| [#37](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/37) | 1 e 9 – primo contatto, identificazione, prova dei giudici | T-71, T-48 |
| [#38](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/38) | 2 e 3 – ordine da foto e dopo l'ordine | T-68, T-26, T-25, T-29 |
| [#39](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/39) | 4 – ordine via email | T-26b |
| [#40](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/40) | 5 – supervisione in console | T-62, T-49, T-63, T-67 |
| [#41](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/41) | 6 – copilota per l'agente di commercio | T-08, T-50, T-51, T-06b, T-44b, T-64 |
| [#42](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/42) | 7 – riordino proattivo | T-24, T-52 |
| [#43](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/43) | 8 – consegna SMS/RCS | T-27 |
| [#44](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/44) | Qualità tecnica | T-54, T-05, T-53, T-73 |
| [#45](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/45) | Demo e submission | T-11, T-12, T-10, T-72 |
| [#46](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/46) | Azioni manuali | M-01…M-11 |

### 4.3 I flussi utente

Utenti: **ristoratore** (WhatsApp +39 345 246 0472 o email `ordini@…`), **agente di commercio** (WhatsApp o chat in console), **back office** (console), **giudice** (console in sola lettura + WhatsApp come un ristoratore). Ogni messaggio passa da: raccolta dei messaggi ravvicinati → un turno dell'agente (Amazon Nova su AgentCore) con i suoi tool → una sola risposta, inviata dal Notifier.

| # | Flusso | Passi | Stato oggi |
|---|---|---|---|
| 1 | Primo contatto e identificazione | Numero sconosciuto → l'assistente si presenta, chiede nome del locale e codice cliente → collega il numero al locale; informativa e consenso alle proposte | ◐ abbinamento ok, ma il contatto resta da verificare e non può ordinare (T-71) |
| 2 | Ordine da foto | Foto del bigliettino (+ vocale) → righe lette → abbinamento al catalogo con lo storico → chiarimenti sulle righe incerte → sostituti, multipli, data di consegna e cut-off → riepilogo con totale → *Confermo* → ERP mock, numero d'ordine, PDF → email con PDF | ✅ col simulatore, mai da telefono (T-68); ☐ email (T-26), pulsanti (T-25) |
| 3 | Dopo l'ordine | Stato dell'ordine; modifica o annullo fino al cut-off del giorno prima; promemoria della bozza dopo 2 h, scadenza a mezzanotte | ✅ nei tool, mai da telefono (T-68) |
| 4 | Ordine via email | Email a `ordini@…` con testo o foto → stesso flusso, risposte via email | ◐ ricezione e risposta ok (T-26b) |
| 5 | Supervisione in console | 5a elenco ordini e dettaglio con il bigliettino accanto alle righe · 5b correzione di una riga · 5c handoff: l'operatore prende la conversazione, risponde, la restituisce | ◐ elenco e dettaglio su dati finti (T-62); ☐ handoff (T-49, T-63) |
| 6 | Copilota per l'agente di commercio | "Cosa propongo alla Trattoria X?", briefing prima della visita, domande sulle schede tecniche, ordine per conto del cliente | ☐ (solo il ruolo e i permessi) |
| 7 | Riordino proattivo | L'assistente scrive per primo ("di solito riordinate l'olio ogni 10 giorni…") → riordino con un tap | ☐ |
| 8 | Consegna | Avviso via SMS/RCS il giorno della consegna con *Ricevuto / Segnala problema* | ☐ |
| 9 | Prova dei giudici | Dal README: numero WhatsApp e codice di prova → ordine da foto → console in sola lettura con il proprio ordine | ◐ console e pagina demo ✅; ordine bloccato dal flusso 1 (T-71) |

### 4.4 Tolti dal backlog

Il repo serve solo alla gara (decisione del 27/10): tolti **T-09** `AnalyticsStack` e **T-65** dashboard KPI (lo stack `analytics` vuoto resta per ora), **T-70** hardening (rischi accettati in [INFRASTRUCTURE_DESIGN §12](./docs/INFRASTRUCTURE_DESIGN.md)) e le domande per il cliente reale. Descrizioni originali in [`docs/OLD/04_BACKLOG.md`](./docs/OLD/04_BACKLOG.md).

### 4.5 PR accorpate

Task sullo stesso stack non testabili da soli: una PR, un commit per task. Finora: T-40 + T-41, T-45 + T-46 + T-47. Candidati: T-49 + T-63 (handoff), T-06b + T-44b (schede tecniche).

---

## 5. Azioni manuali

Sono le issue con etichetta **`manual`**, sotto-issue di [#46](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/46): accessi, Meta, AWS Partner Central, registrazioni, video, Devpost. Le più urgenti: [#76](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/76) numeri dei tester (sblocca T-68), [#85](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/85) registrazioni SMS/RCS, [#79](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/79) opportunità ACE, [#75](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/75) foto dei bigliettini. Submission: [#81](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/81) video, [#82](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/82) Devpost (PS), [#83](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues/83) controllo dei link.

```bash
gh issue list --label manual --state open
```

---

## 6. Decisioni

**Aperte**

Nessuna per la gara.

**Prese**

| Data | Decisione |
|---|---|
| 27/10 | Backlog e azioni manuali su GitHub Issues (sotto-issue per flusso, dipendenze *blocked by*); si prende un task assegnandosi l'issue, si chiude con `Closes #n` nella PR |
| 27/10 | Lavoro in parallelo su tre corsie (§1.5), max 2 sessioni per persona in worktree separati; comandi `/sa-next-task`, `/sa-dod-check`, `/sa-cds-check` nel repo |
| 27/10 | Gli agenti non attendono conferma sul piano se l'issue ha criteri chiari; ogni fine task riporta deploy e script con i comandi completi |
| 27/10 | Security review una sola volta a fine iterazione (T-73, 28/10 ~10:00), non a ogni task |
| 28/10 | CI solo su PR pronte e su `main`; review automatica di Copilot sulle PR; merge da soli per le PR a basso rischio (§1.2); un solo controllo completo per task |
| 27/10 | Un solo ambiente, `dev`, per sviluppo, video e giudici: l'ambiente `demo` è stato tolto da codice e documenti; dopo il code freeze `dev` è congelato |
| 27/10 | Il repo serve solo alla gara: niente task o domande per il cliente reale; tolti T-09, T-65 (analytics/KPI) e T-70 (hardening) |
| 27/10 | Perimetro = flussi utente 1–9 (§4.3), con priorità Must/Should/Could; i flussi 6–8 sono Could |
| 27/10 | I giudici entrano con un codice cliente di prova che verifica subito il contatto (T-71); l'email per la conferma, se manca, la chiede l'assistente (T-26) |
| 27/10 | Code freeze spostato al 28/10 ore 12:00 |
| 27/10 | Prezzi mostrati al ristoratore (riepilogo con totale stimato) |
| 27/10 | Pulsanti WhatsApp per chiarimenti e conferma (T-25) |
| 27/10 | Repo pubblico (già pubblico, licenza MIT) |
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

Dal 27/10 sera il fatto sono le [issue chiuse](https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/issues?q=is%3Aissue+is%3Aclosed) con le loro PR. Qui sotto lo storico fino al 27/10 (dettagli in [`docs/OLD/DONE.md`](./docs/OLD/DONE.md)).

| Data | Task | Cosa | PR |
|---|---|---|---|
| 27/10 | T-29 (invio) | 8 template WhatsApp inviati a Meta (`PENDING`); numero ed email d'ordine nel README e nella console | #33 |
| 27/10 | – | WhatsApp reale su `dev`: WABA collegata, testo e foto fino all'agente; fix dimensione media | #31, #32 |
| 27/10 | – | Deploy `dev` e prova e2e del flusso d'ordine col simulatore; fix nomi tool per Nova, prompt per ruolo, `seed/reset.py` | #30 |
| 27/10 | T-45, T-46, T-47, T-04 | Stock, prezzi, consegne e cut-off; stato ordine, conferma idempotente, modifica/annullo, sweeper; catalogo e listini di prova | #29 |
| 27/10 | T-07 | ERP adapter mock, PDF ordine, regola `order.confirmed` | #28 |
| 27/10 | T-44 | Tool `catalog`: `match_products`, `search_catalog` | #27 |
| 27/10 | T-14 | Simulatore canali (solo `dev`, Notifier in sandbox) | #26 |
| 27/10 | T-06 | Indice prodotti S3 Vectors e `catalog_indexer` | #25 |
| 27/10 | T-15 | `sesDomain` e `waPhoneNumberId` nella config per ambiente | #24 |
| 27/10 | – | SES fuori dalla sandbox | #23 |
| 26/10 | T-22, T-24 (base) | Debounce, Turn Dispatcher, Notifier con sandbox e idempotenza | #22 |
| 26/10 | T-43 | Tool `order_intake`: lettura di foto, vocali e testo | #21 |
| 26/10 | – | SES su `dev`: dominio, DNS, ricezione | #20 |
| 26/10 | T-21, T-23 | `MessagingStack`, Inbound Router, media WhatsApp e allegati email su S3 | #16 |
| 26/10 | T-40, T-41 (ridotti) | AgentCore Gateway + Runtime, agente Strands per ruolo | #15 |
| 26/10 | T-66 | Ruolo `judge` in sola lettura, pagina demo | #13 |
| 26/10 | – | Console online su `dev` (script di pubblicazione) | #12 |
| 26/10 | T-62 (UI) | Inbox e dettaglio ordine con bigliettino, su mock | #10 |
| 26/10 | T-61 | Scaffold console React + Vite + Cognito | #9, #11 |
| 26/10 | T-20 | `ChannelsStack`: topic SNS, SES configuration set e rule set | #7 |
| 26/10 | T-60 | `ConsoleStack` ridotto: Cognito, CloudFront, API ordini | #4, #6, #8 |
| 26/10 | T-42 | Tool `customers`: `identify_contact`, `get_customer_profile` | #5 |
| 26/10 | T-04 (parte) | Dati sintetici: clienti, contatti, storico ordini | #3 |
| 26/10 | T-28 | Testi dei template WhatsApp (IT/EN) | #2 |
| 25/10 | – | Primo deploy `dev` (9 stack, 18 tabelle, CMK, event bus, SSM) | – |
| 24/10 | T-13 | Tag obbligatori su tutte le risorse | `2b5d967` |
| 23/10 | T-01, T-03, T-02 | Monorepo, app CDK con Foundation e Data, CI | `chore/p0-foundations` |
| ≤ 16/10 | – | Concept, documenti 01/02/03, Infrastructure Design, backlog | – |
