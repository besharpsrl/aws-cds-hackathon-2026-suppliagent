# SuppliAgent – Registro del lavoro completato

> Qui finisce tutto ciò che è **chiuso**: task del backlog, documenti scritti, punti aperti risolti.
> Regola: quando una voce è completata la si **rimuove** dal documento "da fare" (`04_BACKLOG.md`, `TODO_DOCS.md`, punti aperti di `INFRASTRUCTURE_DESIGN.md` §12, ecc.) e la si aggiunge qui, in cima, con data, riferimenti e come verificarla.
> Un ID `T-xx` citato come dipendenza nel backlog ma assente dalle sue tabelle è completato: lo trovi qui.

---

## 23/10/2026 – Fase P0 (branch `chore/p0-foundations`)

### T-01 – Scaffold monorepo · –
- **Cosa**: uv workspace alla root (`agent`, `services/*`, `services/tools/*`) con package `suppliagent_agent` e `suppliagent_shared` (vuoti); npm workspaces (`infra`, `console` placeholder fino a T-61); ruff, mypy strict, pytest, eslint (flat config), prettier; script unici dalla root `npm run lint | typecheck | test | synth | check | format`; hook di lint di Claude Code allineato ai workspaces.
- **Versioni fissate**: `aws-cdk-lib` 2.274.0, CLI `aws-cdk` 2.1146.1, `cdk-nag` 3.0.2, TypeScript 6.0.3 (7.x non supportato da `typescript-eslint`), vitest 5; Python 3.12, `strands-agents` ≥ 1.62, `bedrock-agentcore` ≥ 1.24.2, `aws-lambda-powertools` ≥ 3.37, `pydantic` ≥ 2.14.1, `boto3` ≥ 1.43.118.
- **Commit**: `155c4ae`.

### T-03 – CDK app, construct Lambda, Foundation e Data · FN-32
- **Cosa**: app CDK con config `dev`/`demo` (`infra/config/environments.ts`, parametri 02 §7 pubblicati su SSM `/suppliagent/<env>/<nome>`); construct `PythonLambda` (ARM64, Python 3.12, layer Powertools, X-Ray, KMS su env e log, log retention, DLQ opzionale, role senza managed policy); `FoundationStack` (CMK con rotazione, 5 bucket SSE-KMS + `access-logs` SSE-S3, event bus cifrato, Budget opzionale con `-c budgetAlertEmail`); `DataStack` (18 tabelle §5.7: on-demand, PITR, CMK, Streams su `Orders`/`Messages`, TTL su `TurnBuffer`/`WsConnections`); 7 stack vuoti collegati nell'ordine §4; cdk-nag v3 come plugin di validazione.
- **Scelte**: `RemovalPolicy.DESTROY` ovunque (dati ripopolabili dal seed, T-04); stack env-agnostic sull'account; seed custom resource rinviata a T-04; bundling Lambda + libreria shared rinviato a T-21.
- **Test**: 34 test vitest (cdk-nag pulito su dev/demo e sul construct, chiavi e GSI di ogni tabella, cifratura, SSM, budget, dipendenze tra stack).
- **Commit**: `692f18c`, `dd0d8a6`.

### T-02 – CI GitHub Actions · FN-32
- **Cosa**: `.github/workflows/ci.yml` su PR e push su `main`: job Python (ruff, format, mypy, pytest) e TypeScript (eslint, prettier, tsc, vitest, `cdk synth` dev e demo con cdk-nag), senza credenziali AWS; `setup-uv` fissata a SHA, timeout, telemetria CDK disattivata.
- **Da verificare**: prima esecuzione reale al primo push.
- **Commit**: `f55db76`, `2d89d14`.

**Verifica P0**: `npm ci && uv sync && npm run check`, poi `cd infra && npx cdk synth -c env=demo`.

### Punti aperti chiusi (INFRASTRUCTURE_DESIGN §12)
- Copertura CDK: AgentCore con L2 stabili in `aws-cdk-lib/aws-bedrockagentcore`; S3 Vectors e Knowledge Base (storage `S3_VECTORS`) con L1 (dettagli nella nota di §4).

---

## Prima del 23/10/2026

- **16/10** – `04_BACKLOG.md` scritto (ex TODO_DOCS #2).
- **≤ 12/10** – Region `eu-west-1` e Claude con inference profile `eu.` (ex INFRASTRUCTURE_DESIGN §12).
