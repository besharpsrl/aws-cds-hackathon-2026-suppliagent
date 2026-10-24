# SuppliAgent – Guida passo passo a Claude Code

> Per chi non ha mai usato Claude Code. Dall'installazione al lavoro in parallelo del team.
> Aggiornata il 23/10/2026 · Fonti: documentazione ufficiale di Claude Code (code.claude.com/docs)

---

## 1. I concetti in 2 minuti

| Concetto | Cos'è | Dove sta nel nostro repo |
|---|---|---|
| **Claude Code** | Un assistente che lavora nel terminale dentro la cartella del progetto: legge file, scrive codice, esegue comandi, fa commit | si lancia con `claude` |
| **Sessione** | Una conversazione con Claude Code. Ha un "contesto" (memoria di lavoro) limitato: un task per sessione | `/clear` per ricominciare pulito |
| **CLAUDE.md / AGENTS.md** | Istruzioni di progetto lette **in automatico** a ogni sessione: regole, vincoli di gara, convenzioni | `CLAUDE.md` → `agent-context/` |
| **Plan mode** | Claude studia e propone un piano **senza modificare file**; tu approvi e poi esegue | `Shift+Tab` o `/plan` |
| **Permessi** | Cosa può fare senza chiedere (lint, test), cosa chiede (deploy, push), cosa è vietato (force push, leggere `.env`) | `.claude/settings.json` |
| **Comandi slash** | Scorciatoie con istruzioni pronte | `/implement-fn`, `/cds-check`, `/dod-check` |
| **Subagent** | "Assistenti specializzati" che Claude chiama per un compito preciso; lavorano in un contesto separato e restituiscono solo il risultato | `.claude/agents/` (vedi §6) |
| **MCP server** | Collegamenti a fonti esterne (per noi: documentazione AWS e AgentCore aggiornata) | `.mcp.json` |
| **Hook** | Comandi automatici: per noi, lint del file appena modificato | `.claude/settings.json` → `agent-context/claude/hooks/` |
| **Worktree** | Una copia di lavoro separata del repo su un altro branch: permette più sessioni in parallelo senza pestarsi i piedi | `claude -w <nome>` |
| **Plugin** | Pacchetti installabili (comandi, subagent, skill, MCP) da un "marketplace" | `/plugin` |

## 2. Installare gli strumenti (macOS, una volta per persona)

```bash
# Strumenti di sviluppo
brew install node@22 python@3.12 uv awscli gh
npm install -g aws-cdk
# Docker Desktop (serve a CDK per costruire l'immagine dell'agente): https://www.docker.com/products/docker-desktop/

# Claude Code (installer nativo, si aggiorna da solo)
curl -fsSL https://claude.ai/install.sh | bash
claude --version
claude doctor          # controllo dell'installazione
```

Alternativa: `brew install --cask claude-code` (poi si aggiorna con `brew upgrade claude-code`).

## 3. Preparare AWS (una volta per persona; il bootstrap una volta per account)

```bash
# Profilo per l'account dell'hackathon (SSO aziendale; in alternativa: aws configure --profile suppliagent-dev)
aws configure sso --profile suppliagent-dev        # region: eu-west-1
aws sso login --profile suppliagent-dev
export AWS_PROFILE=suppliagent-dev
aws sts get-caller-identity                         # deve mostrare l'account giusto

# Modelli disponibili con profilo eu.
aws bedrock list-inference-profiles --region eu-west-1 \
  --query "inferenceProfileSummaries[?starts_with(inferenceProfileId,'eu.')].inferenceProfileId" --output table

# Solo la prima volta sull'account (una persona sola)
npx cdk bootstrap aws://<ACCOUNT_ID>/eu-west-1 \
  --tags Project="Hackathon AWS CDS" --tags Owner=matteo.goretti@besharp.it
```

Copia `.env.example` in `.env` e compila `AWS_PROFILE` (il file `.env` non va mai committato e Claude Code non può leggerlo).

## 4. Collegare il repository a GitHub (una persona sola)

```bash
cd SuppliAgent
bash agent-context/install.sh                       # attiva CLAUDE.md, .claude/, .mcp.json, template PR
git add -A && git commit -m "chore: activate agent context"
gh auth login                                       # login a GitHub dal terminale
gh repo create <org>/suppliagent --private --source=. --remote=origin --push
```

Poi su GitHub: *Settings → Branches → Add rule* su `main`: PR obbligatoria, CI verde, niente force push. Aggiungi i membri del team.

Gli altri membri:

```bash
git clone git@github.com:<org>/suppliagent.git && cd suppliagent
bash agent-context/install.sh                       # se i link non ci sono (es. Windows)
cp .env.example .env
```

## 5. Primo avvio di Claude Code

```bash
cd suppliagent
claude
```

1. **Login**: si apre il browser, accedi con l'account Claude aziendale.
2. **Fiducia nella cartella**: conferma che ti fidi del progetto.
3. **Server MCP**: Claude Code chiede di approvare `aws-documentation` e `agentcore` (definiti in `.mcp.json`) → approva. Servono a leggere la documentazione AWS aggiornata invece di andare a memoria.
4. **Plugin consigliati** (scrivili nella sessione, uno alla volta; quando chiede lo *scope* scegli **project** così valgono per tutto il team):

   ```text
   /plugin marketplace add strands-agents/harness-sdk
   /plugin install strands@strands-agents
   /plugin install security-guidance@claude-plugins-official
   ```

   - `strands`: plugin ufficiale di Strands Agents (documentazione e linee guida per l'SDK che usiamo per l'agente).
   - `security-guidance`: avvisi su pattern di codice insicuri mentre Claude scrive.
   - Facoltativi: `code-review@claude-plugins-official`, `commit-commands@claude-plugins-official`. **Non** serve `feature-dev`: il nostro flusso è già in `/implement-fn`.
   - Per esplorare: `/plugin` → scheda *Discover*.
5. **Controlli** (tutti dentro la sessione):

   | Comando | Cosa devi vedere |
   |---|---|
   | `/memory` | `CLAUDE.md` del progetto caricato (che importa `AGENTS.md`) |
   | `/mcp` | `aws-documentation` e `agentcore` connessi |
   | `/hooks` | hook `PostToolUse` per il lint |
   | `/permissions` | regole allow / ask / deny del progetto |
   | Scrivi: "elenca i subagent di progetto disponibili" | `code-reviewer`, `aws-docs-researcher`, `test-runner`, `security-reviewer` |

Non servono altre skill o plugin: il contesto del progetto, i comandi e i subagent sono già nel repo.

## 6. I subagent del progetto

Claude li usa da solo quando servono (la descrizione dice "usalo proattivamente"), oppure li chiami tu per nome, es. *"usa code-reviewer sul branch corrente"*.

| Subagent | Quando entra in gioco | Cosa fa | Modifica file? |
|---|---|---|---|
| `aws-docs-researcher` | Prima di scrivere codice su AgentCore, Strands, S3 Vectors, EUM, SES, CDK | Verifica API, parametri, supporto CDK e region su documentazione ufficiale, con link | No |
| `test-runner` | Dopo modifiche al codice | Esegue lint, type check, test, `cdk synth` e riassume solo gli errori | No |
| `code-reviewer` | A fine task / prima della PR | Controlla criteri di accettazione, Definition of Done, regole di dominio e di gara | No |
| `security-reviewer` | Su tool, prompt, IAM, Notifier, console | Autorizzazione per ruolo, prompt injection, PII nei log, segreti, permessi | No |

Sono definiti in `agent-context/claude/agents/` (collegati in `.claude/agents/` da `install.sh`): si modificano lì.

## 7. Sessione 1 – Fondamenta (una persona, oggi)

1. `cd suppliagent && claude`
2. Premi **`Shift+Tab`** finché in basso vedi **plan mode** (oppure inizia il messaggio con `/plan`).
3. Incolla questo prompt:

```text
Sei lo sviluppatore principale di SuppliAgent. Il contesto del progetto è in CLAUDE.md / AGENTS.md;
la fonte di verità è docs/ (01 overview, 02 flussi, 03 funzionalità, INFRASTRUCTURE_DESIGN, 04_BACKLOG).

Obiettivo di questa sessione: Fase P0 del backlog (T-01, T-03, T-02, in quest'ordine), senza deploy.

1. Leggi AGENTS.md, docs/04_BACKLOG.md, docs/INFRASTRUCTURE_DESIGN.md (§4 stack, §5.7 dati, §7 sicurezza).
   Usa il subagent aws-docs-researcher per verificare versioni e supporto CDK di AgentCore, S3 Vectors
   e Bedrock Knowledge Bases prima di fissare le dipendenze.
2. Proponimi un piano con: file che creerai, versioni delle dipendenze principali, scelte non già decise
   nei documenti. Aspetta la mia approvazione.
3. T-01: scaffold del monorepo come in AGENTS.md §5 e §6 – uv workspace alla root (services/*, agent),
   npm workspaces (infra, console), configurazioni ruff/mypy/pytest/eslint/prettier, script unici
   per lint, test e synth. Aggiungi `.claude/worktrees/` a .gitignore. Aggiorna AGENTS.md §6 se i comandi cambiano.
4. T-03: app CDK in infra/ con config dev/demo, construct comune per le Lambda (ARM64, Python 3.12,
   Powertools, log retention, X-Ray, KMS), FoundationStack e DataStack con le tabelle di
   INFRASTRUCTURE_DESIGN §5.7 (on-demand, PITR, KMS, Streams su Orders e Messages). Gli altri stack
   come classi vuote collegate nell'ordine di dipendenza. Test di assertion CDK.
5. T-02: workflow GitHub Actions su PR e push su main: lint, type check, test Python e TS, cdk synth con cdk-nag.
6. Verifica con il subagent test-runner che tutto passi, poi fai revisionare con code-reviewer.
   Sposta i task completati da docs/04_BACKLOG.md a docs/DONE.md. Commit piccoli (Conventional Commits) sul branch
   chore/p0-foundations. Non fare push e non fare deploy.
7. Alla fine riassumi cosa hai fatto, come verificarlo e cosa resta aperto.

Il codice, i commenti e i nomi sono in inglese; la documentazione in docs/ resta in italiano.
Se un requisito è ambiguo, chiedi invece di inventare.
```

4. Quando Claude presenta il piano: leggilo, correggi a parole se serve, poi approvalo. Per la prima sessione scegli l'opzione che ti fa **approvare manualmente le modifiche** (così vedi cosa fa); quando ti fidi puoi passare all'approvazione automatica delle modifiche ai file.
5. A fine lavoro pubblica e apri la PR:

```bash
git push -u origin chore/p0-foundations
gh pr create --fill
```

Dopo la CI verde e la revisione, fai il merge su `main`.

## 8. Sessioni parallele – uno stream per persona

Dopo il merge delle fondamenta, ogni persona aggiorna `main` e apre la propria sessione **in un worktree** (Claude Code crea copia e branch da solo):

```bash
cd suppliagent && git switch main && git pull
claude -w canali       # stream CH
claude -w agente       # stream AG
claude -w console      # stream CO
claude -w dati         # stream IN
```

In ogni sessione: `Shift+Tab` fino a plan mode, incolla il prompt dello stream (sotto), poi lavora un task alla volta con **`/implement-fn FN-xx`**. Quando il task è finito: `/dod-check`, poi `git push` e `gh pr create --fill`.

Nota: il file `.env` non viene copiato nei worktree in automatico; se serve, crea nella root un file `.worktreeinclude` con la riga `.env`.

### Stream CH – Canali CDS

```text
Lavori sullo stream CH (Canali CDS) di SuppliAgent. Leggi CLAUDE.md, docs/04_BACKLOG.md (task T-28, T-20..T-27),
docs/02_TECHNICAL_FLOWS.md §3 e F-11, docs/INFRASTRUCTURE_DESIGN.md §5.1, §5.2, §5.5 (Notifier).

Procedi nell'ordine del backlog (T-20, T-21, T-23, T-22, T-24, poi T-25..T-27), un task alla volta con /implement-fn.
Vincoli chiave: SQS FIFO con MessageGroupId = chat, debounce con TurnBuffer + turn-flush,
idempotenza su providerMessageId, solo il Notifier chiama le API di invio CDS,
client ammessi: socialmessaging, sesv2, pinpoint-sms-voice-v2. Nessun deploy senza chiedere.
Prima di usare un'API CDS verifica parametri e formato con aws-docs-researcher.
Per i test usa moto e payload realistici dei webhook WhatsApp, SES e SMS two-way
(salvali in services/<funzione>/tests/fixtures). Alla fine di ogni task esegui /cds-check.
```

### Stream AG – Agent & AgentCore

```text
Lavori sullo stream AG (Agent & AgentCore) di SuppliAgent. Leggi CLAUDE.md, docs/04_BACKLOG.md (T-40..T-53),
docs/02_TECHNICAL_FLOWS.md (§2, F-02..F-10, §6 contratti), docs/03_FUNCTIONAL_SPEC.md (FN-03..FN-12, FN-19..FN-22),
docs/INFRASTRUCTURE_DESIGN.md §5.3 e §5.4.

Procedi nell'ordine del backlog: T-42, T-40, T-41; in parallelo fai un prototipo di lettura dei bigliettini
(Claude vision, output strutturato con pydantic) sui file di agent/evals/ e riportami precisione e problemi.
Vincoli chiave: modello solo via inference profile eu.; il contesto (contactId, role, customerIds)
è iniettato dal Dispatcher e non è modificabile dal modello; autorizzazione per ruolo dentro ogni tool
con test negativi; i tool restituiscono dati, non testo per l'utente; max 1 suggerimento per ordine;
nessun ordine confermato senza conferma esplicita. Per gli eval (T-53) usa AgentCore Evaluations
(on-demand) oltre al nostro dataset. Prima di scrivere codice AgentCore/Strands verifica le API con
aws-docs-researcher e con il plugin strands. Fai revisionare ogni tool da security-reviewer.
```

### Stream CO – Console & Analytics

```text
Lavori sullo stream CO (Console & Analytics) di SuppliAgent. Leggi CLAUDE.md, docs/04_BACKLOG.md (T-60..T-66),
docs/03_FUNCTIONAL_SPEC.md (FN-24, FN-28..FN-31), docs/INFRASTRUCTURE_DESIGN.md §5.8 e §5.9.

Inizia da T-60 e T-61; finché le API non sono pronte usa dati mock tipizzati secondo i contratti
di docs/02_TECHNICAL_FLOWS.md §6 (Orders con righe e candidati). Brand: assets/brand/
(blu #1F2A44, arancio #E3812B, verde acqua #19C29A). La vista più importante per la demo è il dettaglio
ordine con l'immagine del bigliettino affiancata alle righe e le righe incerte evidenziate.
Ruoli Cognito: backoffice, sales_rep, judge (sola lettura). Nessun dato sensibile in localStorage.
Autorizzazione per gruppo anche lato API; fai revisionare da security-reviewer.
```

### Stream IN – Infra, Dati & Materiali

```text
Lavori sullo stream IN (Infra, Dati & Materiali) di SuppliAgent. Leggi CLAUDE.md, docs/04_BACKLOG.md
(T-04..T-12), docs/INFRASTRUCTURE_DESIGN.md (§4, §5.4, §5.5, §5.6, §5.7, §9) e docs/03_FUNCTIONAL_SPEC.md §8 (scenari).

Inizia da T-04: genera dati di prova sintetici e deterministici che coprano gli scenari S1–S7
(catalogo con sinonimi e abbreviazioni, unità e multipli, esauriti con sostituti, cut-off e giorni di consegna
per zona, clienti con storico ordini che produca riordini scaduti per S5). Se in seed/private/ ci sono
export del cliente, NON leggerli: preparami uno script di anonimizzazione che io eseguirò in locale.
Poi T-06 (S3 Vectors + Knowledge Base) e T-07 (ERP adapter mock + PDF).
Niente servizi a costo fisso; verifica con aws-docs-researcher il supporto CDK/CloudFormation
per S3 Vectors e Knowledge Base con S3 Vectors prima di scegliere L1 o custom resource.
```

## 9. Il ciclo di ogni task

```text
/clear                          ← contesto pulito
Shift+Tab → plan mode
/implement-fn FN-07             ← legge spec, flussi, backlog e propone un piano
  … approvi il piano, Claude scrive test e codice, test-runner verifica …
/dod-check                      ← controllo finale (usa code-reviewer)
/cds-check                      ← solo per lavori sui canali
```

```bash
git push -u origin <branch> && gh pr create --fill
```

## 10. Comandi e tasti utili

| Comando / tasto | A cosa serve |
|---|---|
| `Shift+Tab` | Cambia modalità: normale → accetta modifiche automaticamente → plan mode |
| `Esc` | Interrompe Claude mentre lavora |
| `Esc Esc` (con prompt vuoto) o `/rewind` | Torna indietro a un punto precedente (conversazione e/o codice) |
| `/clear` | Nuova conversazione con contesto vuoto (tra un task e l'altro) |
| `/compact` | Riassume la conversazione per liberare contesto senza perdere il filo |
| `/resume` | Riprende una sessione precedente |
| `@percorso/file` | Cita un file nel messaggio |
| `!comando` | Esegue un comando di shell e ne mostra l'output a Claude |
| `/usage` | Consumi e limiti |
| `/model` | Cambia modello |
| `/help` | Tutti i comandi |

## 11. E i "team di agenti"?

Claude Code ha anche i **team di agenti** (sperimentali): una sessione capo coordina 3–5 sessioni collaboratrici con una lista di task condivisa. **Per noi non servono** finché ogni stream ha una persona: le sessioni parallele nei worktree (§8) sono più controllabili e consumano meno. Se a un certo punto lavori da solo su più stream:

```bash
CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 claude
```

e chiedi: *"Crea un team con 3 teammate: canali (stream CH), agente (stream AG), console (stream CO). Ognuno lavora sui task del proprio stream in docs/04_BACKLOG.md, in un worktree separato, e mi chiede conferma prima di ogni deploy."* Limiti: consumano molti più token, non si ripristinano con `/resume`, un solo team per sessione.

## 12. Regole d'oro

- **Un task per sessione**, `/clear` tra un task e l'altro.
- **Sempre il piano prima** per lavori che toccano più aree.
- **Deploy**: solo su `dev` e approvati a mano; `demo` solo dal responsabile dello stream IN.
- **Dati del cliente** solo in `seed/private/` (ignorata da git e non leggibile da Claude Code).
- Se Claude trova differenze tra codice e documenti, aggiornare i documenti fa parte del task.
- Se qualcosa va storto: `Esc` per fermare, `/rewind` per tornare indietro.
