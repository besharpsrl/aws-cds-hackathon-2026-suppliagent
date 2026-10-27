---
description: Implementa una funzionalità FN-xx seguendo spec, flussi e Definition of Done
argument-hint: FN-xx [note aggiuntive]
---

Implementa la funzionalità **$ARGUMENTS** di SuppliAgent.

1. Leggi la scheda della funzionalità in `docs/03_FUNCTIONAL_SPEC.md` (criteri di accettazione), i flussi/casi `F-xx.Cn` collegati e gli errori `E-xx` in `docs/02_TECHNICAL_FLOWS.md`, la parte pertinente di `docs/INFRASTRUCTURE_DESIGN.md` e il task corrispondente nel backlog di `START_HERE.md` §4 (tabella e dettaglio).
2. Verifica le dipendenze (colonna "Dipende da" di `START_HERE.md` §4.2): una dipendenza è completata se è in `START_HERE.md` §7 e su `main`. Se una dipendenza **bloccante** non è completata, fermati e dimmelo; per quelle **di integrazione** (↺) procedi con mock/stub dichiarati. Prendi il task come da `START_HERE.md` §1.2 (sigla in *Owner*, stato ◐).
3. Proponi un **piano breve** (file da creare/modificare, test, impatti su CDK e console, assunzioni) e **attendi la mia conferma** prima di scrivere codice, se il lavoro tocca più di un'area.
4. Crea un branch `feat/<FN>-<descrizione-breve>` se non sei già su un branch dedicato.
5. Scrivi prima i test a partire dai criteri di accettazione (inclusi i test di **autorizzazione negativa** per i tool), poi l'implementazione.
6. Esegui lint, type check, test e `cdk synth` (AGENTS.md §6) e correggi finché passano.
7. Verifica la Definition of Done (AGENTS.md §9): eventi applicativi, idempotenza, logging senza PII, documentazione aggiornata.
8. In `START_HERE.md`: togli il task da §4.2 (tabella e dettaglio) e aggiungi una riga in cima a §7 (data, task, cosa, PR); aggiorna §2 se cambia lo stato di un'area. Scelte, test e verifica vanno nella descrizione della PR. Se hai creato, diviso o rinviato task, aggiorna §4.
9. Fai commit con Conventional Commits e riferimento `(FN-xx)`. Non fare push.
10. Riassumi: cosa hai fatto, come testarlo, assunzioni, eventuali discrepanze con i documenti.
