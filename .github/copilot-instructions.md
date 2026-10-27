# SuppliAgent – note per GitHub Copilot

Le regole di progetto sono in `AGENTS.md` (caricato in automatico). Qui solo ciò che vale in più per Copilot.

## Priorità delle fonti

- **Backlog e azioni manuali: GitHub Issues** (`gh issue list`). **Stato, timeline, lavoro in parallelo, flussi e decisioni: `START_HERE.md`** (code freeze 28/10 ore 12:00, submission entro le 15:00 del 28/10). Comportamento e requisiti: `docs/`. `AGENTS.md` riassume: in caso di conflitto segnalalo e correggilo. `docs/OLD/` è solo storico.
- Presa e chiusura dei task come da `START_HERE.md` §1.2 (assegnazione dell'issue, `Closes #n` nella PR). Comando di lavoro: `/sa-next-task [T-xx] [loop]`. Le todo list della chat non sono un registro.

## Modo di lavorare

- Prima di implementare leggi la scheda `FN-xx` (03) e i flussi `F-xx` (02); parti dai criteri di accettazione e scrivi prima i test.
- Scrivi un piano breve nella PR in draft; non attendere conferma se l'issue ha criteri chiari. Chiedi solo per ambiguità che cambiano il risultato, scelte non documentate su più aree, rischi su dati, costi o risorse condivise.
- Verifica con i comandi di `AGENTS.md` §6; delega ai subagent di progetto (`test-runner`, `code-reviewer`, `aws-docs-researcher`). `security-reviewer` solo nel task T-73, non a ogni task.
- Se documenti (`START_HERE.md`, `docs/*`, `AGENTS.md`) sono indietro rispetto a git o AWS, segnalalo e correggili nello stesso lavoro.
- Flusso Git: branch `feat/FN-xx-…`, push e PR aperta dall'agente; merge su `main` solo da parte dello sviluppatore. Mai push su `main`, mai force push.
- A fine task riporta sempre cosa deployare, con i comandi completi e gli script da lanciare prima e dopo (o "nessun deploy"): sezione *Deploy* del template PR.

## Terminale

- Solo comandi non interattivi; `git --no-pager`; niente server o watcher in modalità sincrona.
- `gh` solo con `GH_PROMPT_DISABLED=1 GH_PAGER=cat`; mai `gh auth login`, `--web` o comandi che aprono editor o browser. Se `gh` fallisce, fornisci il link di compare e il corpo della PR.
- Mai leggere `.env*`, `seed/private/**`, `seed/raw/**`.
- `cdk deploy`, comandi `aws` mutanti, `git rebase`/`reset`, `rm`, `docker`: solo dopo conferma esplicita, dichiarando profilo, account e region per AWS.
