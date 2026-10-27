## Cosa cambia

<!-- Breve descrizione -->

## Riferimenti

Closes #<issue del task>

- Task: T-
- Funzionalità: FN-
- Flussi / casi: F-

## Come testare

<!-- Comandi, scenari, screenshot/log per console e canali -->

## Deploy

<!-- "Nessun deploy" oppure i passi in ordine, ognuno con il comando completo:
     stack e quando (da questo branch per provarlo / da main dopo il merge) e chi (corsia; foundation, data, reset e notifierSandbox: MG);
     script prima e dopo (seed, catalog-indexer, deploy-console.sh, parametri SSM), con AWS_PROFILE=default;
     controlli dopo il deploy (CodeSize delle Lambda, conversazione nuova dopo agent) e come provarlo. -->

```bash
```

## Checklist (Definition of Done – AGENTS.md §9)

- [ ] Criteri di accettazione delle FN soddisfatti
- [ ] Casi F-xx.Cn ed errori E-xx pertinenti gestiti
- [ ] Unit test + test di autorizzazione negativa (tool)
- [ ] ruff / mypy / eslint / test / `cdk synth` (cdk-nag) verdi
- [ ] Eventi applicativi emessi, idempotenza, log senza PII
- [ ] Documentazione in `docs/` aggiornata; riga di `START_HERE.md` §2 se cambia lo stato di un'area
- [ ] Sezione **Deploy** compilata
- [ ] Eval dell'agente eseguiti (se cambiano prompt o tool) – risultati:

## Assunzioni / note
