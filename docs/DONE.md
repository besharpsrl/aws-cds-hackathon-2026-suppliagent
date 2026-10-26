# SuppliAgent – Registro del lavoro completato

> Qui finisce tutto ciò che è **chiuso**: task del backlog, documenti scritti, punti aperti risolti.
> Regola: quando una voce è completata la si **rimuove** dal documento "da fare" (`04_BACKLOG.md`, `TODO_DOCS.md`, punti aperti di `INFRASTRUCTURE_DESIGN.md` §12, ecc.) e la si aggiunge qui, in cima, con data, riferimenti e come verificarla.
> Un ID `T-xx` citato come dipendenza nel backlog ma assente dalle sue tabelle è completato: lo trovi qui.

---

## 26/10/2026

### T-20 – ChannelsStack: SES + EUM Social · FN-01
- **Cosa**: `ChannelsStack` con 3 topic SNS cifrati con la CMK (`wa-events` per l'event destination della WABA, `mail-inbound`, `email-events`; publish solo dai service principal `social-messaging`/`ses` con `aws:SourceAccount`), configuration set SES `suppliagent-<env>-cs` (TLS obbligatorio, reputation metrics, event destination SNS su send/delivery/bounce/complaint/open/click). Con `-c sesDomain=<dominio>`: identity SES (Easy DKIM), receipt rule set `suppliagent-<env>-inbound` (S3 `inbound-mail/mail/` cifrato KMS + notifica su `mail-inbound`) e sua attivazione. `FoundationStack`: key policy della CMK per `ses`, `social-messaging`, `sns` e bucket policy `inbound-mail` per SES (entrambe con `aws:SourceAccount`).
- **Scelte**: parametri legati a passi manuali da context CDK e pubblicati su SSM (`waPhoneNumberId`, `sesDomain`, `sesFromAddress`, default `UNSET`) più `waEventsTopicArn` e `sesConfigurationSet`: collegare il numero WhatsApp = `-c waPhoneNumberId=<id>`, senza modificare il codice. Senza `sesDomain` nessuna identity né rule set (account senza rule set attivo il 26/10, SES in sandbox). Receipt rule in L1 per non far dipendere Foundation da Channels. **Fuori scope** (spostato in T-27): EUM SMS/RCS v2.
- **Test**: `infra/test/channels-stack.test.ts` (topic e policy, configuration set, con/senza dominio, SSM, grant in Foundation, cdk-nag dev/demo con e senza dominio); `npm run check` verde.
- **Da fare a mano**: vedi README «Manual steps» (event destination della WABA, DNS DKIM/MX, uscita dalla sandbox SES).
- **Commit**: branch `feat/FN-01-channels-stack`.

### T-60 – `ConsoleStack` (versione ridotta) · FN-28, FN-32
- **Cosa**: Cognito (gruppi `backoffice`, `sales_rep`, `judge`; self sign-up off, attributo custom `repId`, client SPA senza secret, SRP); bucket S3 + CloudFront con OAC per la SPA (log su bucket dedicato); API REST `/v1` con authorizer Cognito (`GET /orders`, `GET /orders/{orderId}`) e Lambda `console_api` (`services/console_api/`) **in sola lettura** su `Orders` (+ URL presigned a 5 min per l'immagine del bigliettino). Output: `UserPoolId`, `UserPoolClientId`, `ApiUrl`, `ConsoleUrl`, `SiteBucketName`.
- **Scelte**: ruolo dai claim Cognito, mai dal body; `backoffice`/`judge` vedono tutto, `sales_rep` solo `repId` del proprio claim (`custom:repId`) e un ordine altrui risponde 404; bucket SPA in SSE-S3 (l'OAC non usa la CMK senza toccare la key policy di Foundation); bucket SPA/log `RETAIN` (niente `autoDeleteObjects`, il suo provider crea un log group senza tag); IAM con statement espliciti (GetItem/Query/Scan, `s3:GetObject`, `kms:Decrypt`).
- **Assunzione**: l'ordine porta `imageS3Uri` (`s3://bucket/key`) con la foto del bigliettino; da allineare con T-46/T-22.
- **Rinviati**: WebSocket + broadcaster (T-63), `rep_chat` (T-64), **WAF** (costo fisso, AGENTS §11: decidere prima della demo; ack `AwsSolutions-CFR2`/`APIG3` da rimuovere se lo si aggiunge), correzione righe (scrittura, con T-46), paginazione liste (max 100).
- **Test**: `infra/test/console-stack.test.ts` (gruppi, client, OAC, authorizer su ogni metodo, Orders solo lettura), `services/console_api/tests/test_handler.py` (14, inclusa autorizzazione negativa per ruolo/portafoglio); `npm run check` verde (cdk-nag dev+demo).
- **Deploy**: non eseguito (`cdk deploy suppliagent-dev-console --exclusively -c env=dev` dopo conferma).
- **Commit**: `141a6e0` (branch `feat/FN-28-console-stack`).

### T-28 – Testi dei template WhatsApp · FN-12, FN-19
- **Cosa**: 8 template (IT/EN) in formato `template-definition` di Meta in `services/notifier/whatsapp_templates/`: `order_confirmation`, `order_pending_reminder`, `delivery_update` (UTILITY) e `reorder_suggestion` (MARKETING); revisione e regole di contenuto in [09_CONTENT_AND_TEMPLATES](./09_CONTENT_AND_TEMPLATES.md).
- **Scelte**: nessun pulsante conferma un ordine senza riepilogo; footer "Assistente virtuale ordini"; nessun nome del distributore; *Stop proposte* revoca il consenso proattivo.
- **Test**: `tests/test_whatsapp_templates.py` (regole di Meta, stessa forma IT/EN).
- **Seguito**: l'invio a Meta e l'approvazione sono il task **T-29** (serve la WABA collegata a EUM Social).
- **Commit**: `1bbb767`, `5c00610` (PR `feat/FN-12-whatsapp-templates`).

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
