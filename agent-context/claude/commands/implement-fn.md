---
description: Implementa una funzionalità FN-xx seguendo spec, flussi e Definition of Done
argument-hint: FN-xx [note aggiuntive]
---

Implementa la funzionalità **$ARGUMENTS** di SuppliAgent.

1. Leggi la scheda della funzionalità in `docs/03_FUNCTIONAL_SPEC.md` (criteri di accettazione), i flussi/casi `F-xx.Cn` collegati e gli errori `E-xx` in `docs/02_TECHNICAL_FLOWS.md`, la parte pertinente di `docs/INFRASTRUCTURE_DESIGN.md` e il task corrispondente in `docs/04_BACKLOG.md`.
2. Verifica le dipendenze: quelle tra sessioni sono in `START_HERE.md` §3bis (colonna "Attende"), le altre nel backlog; una dipendenza è completata se è in `docs/DONE.md` e su `main`. Se una dipendenza **bloccante** non è completata, segna il task ⏸ in START_HERE §3bis, fermati e dimmelo; per quelle **di integrazione** procedi con mock/stub dichiarati.
3. Proponi un **piano breve** (file da creare/modificare, test, impatti su CDK e console, assunzioni) e **attendi la mia conferma** prima di scrivere codice, se il lavoro tocca più di un'area.
4. Crea un branch `feat/<FN>-<descrizione-breve>` se non sei già su un branch dedicato.
5. Scrivi prima i test a partire dai criteri di accettazione (inclusi i test di **autorizzazione negativa** per i tool), poi l'implementazione.
6. Esegui lint, type check, test e `cdk synth` (AGENTS.md §6) e correggi finché passano.
7. Verifica la Definition of Done (AGENTS.md §9): eventi applicativi, idempotenza, logging senza PII, documentazione aggiornata.
8. Rimuovi la riga del task da `docs/04_BACKLOG.md`, segnalo ✅ (con il numero di PR) in `START_HERE.md` §3bis e aggiungilo in cima a `docs/DONE.md` con data, cosa è stato fatto, scelte, test e commit. Se hai creato, diviso o rinviato task, aggiorna sia il backlog (descrizione) sia START_HERE §3bis (assegnazione).
9. Fai commit con Conventional Commits e riferimento `(FN-xx)`. Non fare push.
10. Riassumi: cosa hai fatto, come testarlo, assunzioni, eventuali discrepanze con i documenti.
