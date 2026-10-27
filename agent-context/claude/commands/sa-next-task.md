---
description: "SuppliAgent: prende il prossimo task libero (GitHub Issues) e lo porta fino alla PR, con le istruzioni di deploy"
argument-hint: "[A|B|C] [T-xx] [loop] [note]"
---

Sei una sessione di sviluppo di SuppliAgent. Argomenti dell'utente: `$ARGUMENTS` (in Copilot: il testo scritto dopo il comando). `A`, `B` o `C` = corsia di questa sessione; un `T-xx` o delle note hanno la precedenza sulla scelta automatica; `loop` = a fine task passa al successivo senza fermarti (punto 9).

## Regole

- Progetto: `AGENTS.md`. Lavoro in team: `START_HERE.md` §1 (presa e chiusura dei task, corsie, sessioni, deploy, file caldi). Backlog: **GitHub Issues** (`besharpsrl/aws-cds-hackathon-2026-suppliagent`).
- Terminale: solo comandi non interattivi; `git --no-pager`; `gh` sempre con il prefisso `GH_PROMPT_DISABLED=1 GH_PAGER=cat`, mai `gh auth login`, `--web` o editor; niente server o watcher in modalità sincrona; mai leggere `.env*`, `seed/private/**`, `seed/raw/**`.
- Mai merge, mai push su `main`, mai force push. Senza conferma esplicita: niente `cdk deploy`, comandi `aws` che modificano risorse, `seed/seed.py`/`seed/reset.py` (scrivono su AWS), `rm`, `git reset`/`rebase` interattivi. Prima di un comando AWS dichiara profilo (`default`), account (`471112860008`) e region (`eu-west-1`).
- Niente `security-reviewer` a fine task: la revisione di sicurezza è T-73.

## 1. Allineamento

1. `git fetch origin` e `git status --short`. Se ci sono modifiche non committate di un altro lavoro, fermati e chiedi.
2. Se il branch corrente ha una PR aperta (`gh pr view --json number,state,isDraft,title,body`) di un task non chiuso: **riprendi quel task** dal punto 4.
3. Altrimenti si parte da `origin/main`.

## 2. Scelta del task

- **Con `T-xx`**: `gh issue list --state open --search "T-xx in:title" --json number,title,assignees,labels`.
- **Senza**: corsia = la lettera negli argomenti, altrimenti quella dell'utente in `START_HERE.md` §1.5 (se non la sai, chiedila una volta: A, B o C). Poi:
  ```bash
  GH_PROMPT_DISABLED=1 GH_PAGER=cat gh issue list --state open --label corsia:<X> --limit 50 --json number,title,assignees,labels,blockedBy \
    --jq '.[] | {number, title, assignees: [.assignees[].login], labels: [.labels[].name], openBlockers: [.blockedBy.nodes[]? | select(.state=="OPEN") | .title]}'
  ```
  Scarta le issue `manual` e `flusso`, quelle già assegnate ad altri e quelle con `openBlockers` non vuoto. Ordine: `must` > `should` > `could`, poi l'ordine della corsia in START_HERE §1.5. Un `could` solo se tutti i `must` aperti hanno un assegnatario (`gh issue list --state open --label must --json number,assignees`).
- Nessuna libera nella corsia: proponi la prima libera di un'altra corsia e chiedi. Un'issue bloccata non si inizia: dillo e indica da cosa dipende.

## 3. Presa

1. `gh issue edit <n> --add-assignee @me`.
2. Branch da `origin/main`: `git switch -c feat/<FN principale>-<breve> origin/main` (`fix/`, `docs/`, `chore/` se più adatto). Se questa sessione è nella checkout principale e ce n'è già un'altra attiva, proponi un worktree (START_HERE §1.5).

## 4. Contesto e piano

1. Leggi l'issue e la sua madre (`gh issue view <n> --comments`), i criteri di accettazione delle `FN-xx` in `docs/03_FUNCTIONAL_SPEC.md`, i flussi/casi `F-xx.Cn` e gli errori `E-xx` in `docs/02_TECHNICAL_FLOWS.md`, la parte di `docs/INFRASTRUCTURE_DESIGN.md`. Per API AWS recenti (AgentCore, Strands, EUM, SES, S3 Vectors, Knowledge Base, CDK) usa il subagent `aws-docs-researcher`.
2. Scrivi un piano breve: file, test, impatti su CDK e console, file caldi toccati (START_HERE §1.5), assunzioni, cosa servirà deployare.
3. **Non attendere conferma** se l'issue ha criteri chiari. Chiedi solo se: un requisito è ambiguo e cambia il risultato, serve una scelta non documentata che tocca più aree, o c'è un rischio su dati, costi o risorse condivise.
4. Al primo commit: push del branch e PR in **draft** con titolo `T-xx: …`, corpo dal template `.github/pull_request_template.md` con `Closes #<n>` e il piano:
   ```bash
   git push -u origin <branch>
   GH_PROMPT_DISABLED=1 GH_PAGER=cat gh pr create --draft --base main --title "T-xx: …" --body-file <file>
   ```

## 5. Implementazione

- Prima i test dai criteri di accettazione (per i tool anche **autorizzazione negativa**), poi il codice. Commit piccoli in Conventional Commits con `(FN-xx)`.
- Durante lo sviluppo lancia **solo i controlli mirati** sui file toccati: `uv run pytest services/<pacchetto>` (o `agent`), `uv run ruff check <path>`, `uv run mypy <path>`, `npx vitest run <file>` nel workspace, `npx cdk synth -q -c env=dev` solo se tocchi `infra/`. Il controllo completo si fa **una volta** al punto 6.
- File caldi di un'altra corsia: cambia solo il pezzo che ti serve e scrivilo nella PR.
- Se il comportamento differisce dai documenti in `docs/`, aggiornali. Se cambia lo stato di un'area, aggiorna la riga in `START_HERE.md` §2. Non toccare il backlog in START_HERE (è sulle issue).
- Lavoro nuovo o rinviato: `gh issue create --title "T-xx: …" --parent <madre> --label <priorità> --label stream:<…> --label corsia:<…> --milestone "Code freeze 28/10 12:00" --project "SuppliAgent – backlog hackathon" [--blocked-by <n>]`.

## 6. Verifica

- `git pull --rebase origin main`, poi **un solo** controllo completo (lint, type check, test, `cdk synth`: AGENTS.md §6) con il subagent `test-runner` (o `npm run check`); correggi e rilancia solo le parti fallite, poi il completo una volta sola alla fine.
- Subagent `code-reviewer` sul diff rispetto a `origin/main` (legge e basta, non rilancia i controlli); correggi i rilievi gravi.
- Non serve `/sa-dod-check`: questo punto e il 7 lo coprono. In CI girano di nuovo tutti i controlli e il test CDS (`tests/test_cds_usage.py`) quando la PR esce dalla bozza.
- Per prompt o tool dell'agente: eval in `agent/evals/` se esistono per l'area, con i risultati nella PR.

## 7. PR pronta

Completa il corpo della PR secondo il template (FN, come testare con i comandi e l'esito, Definition of Done, **Deploy**, assunzioni), push, poi `gh pr ready` (parte la CI e la review automatica di Copilot). Mai merge: se la PR è a basso rischio (START_HERE §1.2) dillo nel rapporto, così l'autore può fare merge da solo con CI verde.

## 8. Rapporto finale (sempre, in quest'ordine)

1. **Fatto**: link della PR, cosa cambia, test eseguiti con l'esito.
2. **Deploy**: "nessun deploy" oppure i passi **in ordine**, ciascuno con il **comando completo** pronto da copiare:
   - stack da deployare e quando (da questo branch per provarlo, o da `main` dopo il merge) e chi (corsia; `foundation`, `data`, `seed/reset.py`, `notifierSandbox` solo MG);
   - script **prima** del deploy (es. `uv run python seed/seed.py --env dev`) e **dopo** (es. invocazione di `suppliagent-dev-catalog-indexer`, `scripts/deploy-console.sh dev`, parametri SSM), con `AWS_PROFILE=default`;
   - controlli dopo il deploy (`CodeSize` delle Lambda, conversazione nuova dopo `agent`) e come provarlo (messaggio dal telefono, URL della console, simulatore solo con il sandbox acceso).
   Esempio:
   ```bash
   git switch main && git pull --ff-only
   cd infra && AWS_PROFILE=default npx cdk deploy suppliagent-dev-agent --exclusively -c env=dev
   AWS_PROFILE=default aws lambda get-function --function-name <nome> --query 'Configuration.CodeSize'
   ```
3. **Azioni manuali** necessarie (issue `M-xx`) e issue create o modificate.
4. **Prossimo task**: la prossima issue libera della corsia.

## 9. Loop

Con `loop` negli argomenti: dopo il rapporto passa al prossimo task libero (punto 2) su un **nuovo branch da `origin/main`**, senza attendere il merge, purché non dipenda dalla PR appena aperta. Fermati se non ci sono task liberi, se serve una conferma (deploy, AWS, ambiguità) o dopo 3 task. Senza `loop`: fermati e suggerisci di aprire una chat nuova.
