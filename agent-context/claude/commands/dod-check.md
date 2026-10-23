---
description: Controlla la Definition of Done sul branch corrente prima di aprire una PR
---

Esegui la revisione del lavoro sul branch corrente rispetto a `main`.

1. `git diff main...HEAD --stat` e lettura delle modifiche.
2. Identifica le `FN-xx` coinvolte (commit, nome del branch, backlog) e rileggi i criteri di accettazione in `docs/03_FUNCTIONAL_SPEC.md`.
3. Per ogni criterio indica se è soddisfatto e con quale test o evidenza.
4. Controlla la Definition of Done di `agent-context/AGENTS.md` §9 e le regole di dominio §8:
   - test unitari e di autorizzazione negativa;
   - lint, type check, test e `cdk synth` (eseguili);
   - eventi applicativi (02 §6.4), idempotenza, logging senza PII;
   - IAM least privilege e cdk-nag;
   - documentazione e backlog aggiornati.
5. Restituisci: elenco dei problemi in ordine di gravità, cosa manca per chiudere il task e una bozza della descrizione della PR (FN, come testare, assunzioni).
