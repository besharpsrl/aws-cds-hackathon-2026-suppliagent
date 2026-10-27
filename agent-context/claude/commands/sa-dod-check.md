---
description: "SuppliAgent: controlla la Definition of Done del branch corrente prima di rendere pronta la PR"
---

Rivedi il lavoro del branch corrente rispetto a `origin/main` (prima `git fetch origin`). Non modificare file.
Serve per il lavoro fatto **senza** `/sa-next-task` (che fa già questi controlli): non lanciarlo dopo `/sa-next-task`.

1. `git --no-pager diff origin/main...HEAD --stat`, lettura delle modifiche e di quelle non committate (`git status --short`).
2. Trova l'issue del task (`Closes #n` nella PR: `GH_PROMPT_DISABLED=1 GH_PAGER=cat gh pr view --json body`, o `T-xx` nel branch) e le `FN-xx` coinvolte; rileggi i criteri di accettazione in `docs/03_FUNCTIONAL_SPEC.md` e la descrizione dell'issue.
3. Per ogni criterio indica se è soddisfatto e con quale test o evidenza.
4. Definition of Done (`AGENTS.md` §9) e regole di dominio (§8):
   - test unitari e di autorizzazione negativa (tool);
   - lint, type check, test e `cdk synth` (eseguili con il subagent `test-runner` o `npm run check`);
   - eventi applicativi (02 §6.4), idempotenza, log senza dati personali;
   - IAM least privilege e cdk-nag;
   - documenti in `docs/` allineati al comportamento; riga di `START_HERE.md` §2 se cambia lo stato di un'area.
5. Corpo della PR secondo `.github/pull_request_template.md`: `Closes #n`, come testare con comandi ed esito, sezione **Deploy** con i comandi completi (stack, script prima e dopo, controlli) o "nessun deploy".
6. Restituisci: problemi in ordine di gravità, cosa manca per chiudere, bozza del corpo della PR.

Niente `security-reviewer` qui: la revisione di sicurezza è T-73, a fine iterazione.
