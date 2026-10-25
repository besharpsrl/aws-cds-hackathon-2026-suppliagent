---
inclusion: always
---

# Tech – SuppliAgent

## Vincoli
- Region **eu-west-1**; modello **Amazon Nova** (`eu.amazon.nova-pro-v1:0`, `eu.amazon.nova-lite-v1:0`) solo via inference profile **`eu.`** (mai `global.`/`us.`); Claude in futuro se abilitato sull'account.
- IaC **AWS CDK v2 TypeScript**; tutto riproducibile con `cdk deploy --all`; `cdk-nag` (AwsSolutions) deve passare.
- Client CDS ammessi (requisito di gara, devono essere chiamati davvero nel codice): `socialmessaging` (`SendWhatsAppMessage`), `pinpoint-sms-voice-v2` (`SendRcsMessage`, `SendTextMessage`), `sesv2` (`SendEmail`). **Vietati**: `pinpoint` v1, `pinpoint-email`, EUM Push.
- Serverless e scale-to-zero: niente servizi con costo fisso (OpenSearch, NAT, RDS, istanze) senza approvazione. Ricerca vettoriale su **S3 Vectors**; schede tecniche su **Bedrock Knowledge Base** (vector store S3 Vectors).

## Stack
- Lambda e agent: **Python 3.12 ARM64**, boto3, **AWS Lambda Powertools** (logger, tracer, metrics, idempotency), pydantic v2.
- Agent: **Strands Agents su Amazon Bedrock AgentCore** (Runtime, Memory con `actorId = contactId`, Gateway MCP con tool su Lambda, Identity, Observability), Bedrock Guardrails, Transcribe.
- Ingestion: SNS → **SQS FIFO** (`MessageGroupId = chat`) → Inbound Router → TurnBuffer (DynamoDB) + SQS `turn-flush` → Turn Dispatcher (debounce + lock).
- Dati: DynamoDB on-demand (PITR, KMS), S3 (KMS). Console: React + Vite + TypeScript, Cognito, API Gateway REST + WebSocket.
- Tooling: `uv`, `ruff`, `mypy`, `pytest`, `moto`; `npm`, `eslint`, `prettier`, `vitest`.

## Comandi
```bash
npm ci && uv sync                      # dalla root (npm + uv workspaces)
npm run check                          # lint + typecheck + test + cdk synth (cdk-nag)
cd infra && npx cdk deploy --all -c env=dev   # mai su demo senza conferma
uv run python seed/reset.py --env dev
```

## Regole tecniche
- Configurazione da SSM / CDK context; nessun segreto nel codice.
- Log JSON con `correlation_id` (conversationId/orderId); **mai** contenuti dei messaggi, telefoni o email in chiaro.
- Idempotenza su inbound (`providerMessageId`), `confirm_order` e invii del Notifier.
- **Autorizzazione per ruolo nei tool** (cliente → propri dati; agente di commercio → proprio portafoglio), con test negativi.
- IAM least privilege: solo il Notifier può inviare su canali CDS.
- Ogni flusso emette gli eventi applicativi definiti nei documenti.

Dettagli: #[[file:docs/INFRASTRUCTURE_DESIGN.md]]
