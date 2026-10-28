# CLAUDE.md – SuppliAgent

Il contesto completo del progetto è in AGENTS.md (condiviso con gli altri tool):

@AGENTS.md

## Note specifiche per Claude Code

- Prima di implementare una funzionalità, leggi la scheda `FN-xx` in `docs/03_FUNCTIONAL_SPEC.md` e i flussi `F-xx` collegati in `docs/02_TECHNICAL_FLOWS.md`; parti dai criteri di accettazione e scrivi prima i test.
- Lavora con `/sa-next-task [T-xx] [loop]`: piano breve nella PR in draft, senza attendere conferma se l'issue ha criteri chiari; chiedi solo per ambiguità, scelte non documentate su più aree, rischi su dati, costi o risorse condivise. A fine task riporta sempre il deploy con i comandi completi.
- Usa i comandi in AGENTS.md §6 per verificare il lavoro (lint, type check, test, `cdk synth`) prima di dichiararlo concluso.
- Non eseguire `cdk deploy` dopo l'invio della submission (`dev` è l'ambiente dei giudici) né comandi che creano costi o modificano risorse condivise (AGENTS.md §11) senza conferma esplicita.
- Quando cambi un comportamento documentato, aggiorna nello stesso lavoro il documento in `docs/`.
- Messaggi di commit: Conventional Commits con riferimento `FN-xx` (AGENTS.md §10).
