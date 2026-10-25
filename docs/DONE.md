# SuppliAgent – Registro del lavoro completato

> Qui finisce tutto ciò che è **chiuso**: task del backlog, documenti scritti, punti aperti risolti.
> Regola: quando una voce è completata la si **rimuove** dal documento "da fare" (`04_BACKLOG.md`, `TODO_DOCS.md`, punti aperti di `INFRASTRUCTURE_DESIGN.md` §12, ecc.) e la si aggiunge qui, in cima, con data, riferimenti e come verificarla.
> Un ID `T-xx` citato come dipendenza nel backlog ma assente dalle sue tabelle è completato: lo trovi qui.

---

## 25/10/2026

### Primo deploy `dev` · FN-32
- **Dove**: account `471112860008` (condiviso con altri progetti beSharp), `eu-west-1`, profilo `default`; bootstrap CDK già presente (`CDKToolkit` v30), non rifatto. Deploy **da locale** (`cd infra && npx cdk deploy --all -c env=dev`).
- **Cosa c'è**: 9 stack `suppliagent-dev-*` (Foundation e Data con risorse, gli altri vuoti); 18 tabelle DynamoDB (on-demand, PITR, CMK, Streams su orders/messages); 6 bucket `suppliagent-dev-<nome>-471112860008`; CMK `alias/suppliagent-dev`; event bus `suppliagent-dev-events` cifrato; 16 parametri SSM sotto `/suppliagent/dev/`; 55 risorse con `Project=Hackathon AWS CDS` + `Env=dev`.
- **Scelte**: rimosso l'AWS Budget dal `FoundationStack` (account condiviso: conterebbe la spesa di tutti) – commit `af4536d`.
- **Verifica**: `aws cloudformation list-stacks`, `aws dynamodb list-tables`, `aws ssm get-parameters-by-path --path /suppliagent/dev`, `npx cdk diff -c env=dev` senza differenze.
- **Nota operativa**: da Claude Code il deploy va lanciato fuori dal sandbox (il proxy di rete interrompe le risposte dei changeset CloudFormation con `Error: aborted`).

---

## 24/10/2026

### T-13 – Tag obbligatori su tutte le risorse · FN-32
- **Cosa**: `Project=Hackathon AWS CDS`, `Owner=matteo.goretti@besharp.it` (costante `MANDATORY_TAGS` in `infra/config/environments.ts`) e `Env=<env>` applicati sia con `Tags.of(app)` sia come **tag di stack** espliciti (flag `@aws-cdk/core:explicitStackTags` attivo): CloudFormation li propaga anche alle risorse "raw" che `Tags.of()` non raggiunge (Lambda e ruolo del provider `autoDeleteObjects`).
- **Casi espliciti**: `CfnBudget` non è `ITaggable` → `resourceTags` impostati a mano; il log group della Lambda del provider `autoDeleteObjects` (creato da Lambda a runtime, fuori da CloudFormation e senza tag) è **pre-creato** in CDK con tag, CMK e retention, e i custom resource ne dipendono.
- **Fuori dal CDK**: bootstrap con `--tags` (vedi HANDOFF §3); risorse create a mano da console vanno taggate a mano (START_HERE §1.2).
- **Test**: tag su tutti i 9 stack, su ogni risorsa taggabile, sul budget, log group del provider (37 test vitest); `npm run check` e synth demo verdi.
- **Commit**: `2b5d967`.

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
- Versione del layer Powertools: **v40** (`AWSLambdaPowertoolsPythonV3-python312-arm64:40`), confermata su SSM `/aws/service/powertools/python/arm64/python3.12/latest` in eu-west-1; è quella in `infra/config/environments.ts`.
- Copertura CDK: AgentCore con L2 stabili in `aws-cdk-lib/aws-bedrockagentcore`; S3 Vectors e Knowledge Base (storage `S3_VECTORS`) con L1 (dettagli nella nota di §4).

---

## Prima del 23/10/2026

- **16/10** – `04_BACKLOG.md` scritto (ex TODO_DOCS #2).
- **≤ 12/10** – Region `eu-west-1` e Claude con inference profile `eu.` (ex INFRASTRUCTURE_DESIGN §12).
