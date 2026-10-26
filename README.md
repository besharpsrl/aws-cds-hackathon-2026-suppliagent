<p align="center">
  <img src="assets/brand/suppliagent_logo_light.png" alt="SuppliAgent" width="560">
</p>

# SuppliAgent

**An agentic AI that turns the way restaurants already order – a photo of a handwritten note, a voice message, a quick text on WhatsApp – into verified, confirmed orders for their food distributor.**

Built by [beSharp](https://www.besharp.it) for the **AWS Communication Developer Services (CDS) Agentic AI Partner Hackathon**, on a real use case of a beSharp customer: a food distributor serving the HoReCa channel (hotels, restaurants, cafés).

> Status: 🚧 in development – submission deadline 28 Oct 2026.
>
> **Team: start from [`START_HERE.md`](START_HERE.md)** (Italian) – single handoff document with tasks, Claude Code workflow and file map.

---

## What it does

**For restaurant owners (customers)**
- Order on **WhatsApp** with a photo of a handwritten list, a voice note or free text – or by **email**.
- The agent reads the order, **matches each line to the catalog** using the customer's purchase history, checks **stock, price list, pack sizes, cut-off and delivery days**, asks for clarification **only where needed** (interactive buttons), proposes substitutes and at most one relevant suggestion.
- Explicit **confirmation with one tap**, then confirmation by **email (PDF)** and **SMS/RCS**, delivery notifications with *Received / Report a problem*.
- **Proactive reorder**: when a regular reorder is overdue, the agent offers to repeat it with one tap.

**For sales reps (copilot, WhatsApp or web chat)**
- "What should I pitch to restaurant X?" – recommendations from history, lapsed products, peers and promotions.
- Catalog search and **technical sheet Q&A** (allergens, storage, formats) with citations.
- Visit briefings and orders placed on behalf of customers.

**For the back office** – a real-time console with orders, low-confidence lines next to the original photo, conversations, delivery issues, handoff and impact KPIs.

## AWS CDS usage

| Service | API | Used for |
|---|---|---|
| AWS End User Messaging Social (WhatsApp) | `socialmessaging:SendWhatsAppMessage` | Ordering conversations, interactive clarifications, reorder proposals, sales copilot |
| Amazon SES v2 | `sesv2:SendEmail` + email receiving | Order confirmation with PDF, orders received by email, rep briefings |
| AWS End User Messaging SMS (RCS/SMS) | `pinpoint-sms-voice-v2:SendRcsMessage`, `SendTextMessage` | Order confirmations, delivery notifications with suggested replies, SMS fallback |

## Architecture

<p align="center"><a href="docs/architecture.drawio">docs/architecture.drawio</a></p>

- Region **eu-west-1**; **Amazon Nova** (Nova Pro for reasoning and handwritten-note vision, Nova Lite for fast classification) on Amazon Bedrock via the **`eu.` inference profiles** (data and inference stay in the EU).
- **Strands Agents on Amazon Bedrock AgentCore** (Runtime, Memory, Gateway, Identity, Observability), Bedrock Guardrails, Bedrock Knowledge Bases, **Amazon S3 Vectors**, Amazon Transcribe.
- Serverless ingestion: SNS → SQS (idempotent per provider message, parallel across chats) → debounce with a per-conversation lock (one answer per burst of messages, in arrival order).
- DynamoDB, S3, EventBridge, Lambda (Python 3.12), API Gateway (REST + WebSocket), Cognito, CloudFront, Firehose, Glue, Athena.
- Infrastructure as code with **AWS CDK (TypeScript)**.

Full design: [`docs/INFRASTRUCTURE_DESIGN.md`](docs/INFRASTRUCTURE_DESIGN.md) (Italian).

## Repository layout

```
├── agent-context/   # context for AI coding agents (AGENTS.md, CLAUDE.md, Kiro steering)
├── docs/            # functional & technical documentation (Italian) – source of truth
├── assets/brand/    # logo
├── infra/           # AWS CDK app (TypeScript)
├── agent/           # Strands agent for AgentCore Runtime (Python) + evals
├── services/        # Lambda functions and Gateway tools (Python)
├── console/         # back-office console & sales rep web chat (React + Vite)
├── seed/            # anonymized / synthetic demo data + seed/reset scripts
└── scripts/         # utilities
```

## Getting started

> Commands will be finalized as the code lands; see [`agent-context/AGENTS.md`](agent-context/AGENTS.md) §6.

**Prerequisites**: AWS account with access to Amazon Bedrock models in `eu-west-1`, Node.js 22, Python 3.12, [`uv`](https://docs.astral.sh/uv/), AWS CDK v2, Docker.

**Manual prerequisites** (cannot be automated): WhatsApp Business Account linked to AWS End User Messaging Social and approved message templates; SES domain verification, production access and MX record; RCS agent registration and test devices; SMS origination identity.

**Manual steps** (after `cdk deploy suppliagent-<env>-channels`):
1. *WhatsApp* (step by step, in Italian: [docs/WABA_SETUP.md](docs/WABA_SETUP.md)): link the WABA to AWS End User Messaging Social, then add an event destination pointing at the SNS topic `suppliagent-<env>-wa-events` (ARN in SSM `/suppliagent/<env>/waEventsTopicArn`); redeploy with `-c waPhoneNumberId=<phone-number-id>`.
2. *Email*: deploy with `-c sesDomain=<domain>`, add the DKIM CNAME records shown by the SES identity and an `MX 10 inbound-smtp.eu-west-1.amazonaws.com` record, request SES production access (sandbox: verified recipients only). Only one SES receipt rule set can be active per region; the stack activates its own.
3. **Every later deploy that touches `channels`** (directly, or through a stack that depends on it such as `messaging` without `--exclusively`) must pass the same `-c sesDomain=…` and `-c waPhoneNumberId=…` again: without them the SSM parameters go back to `UNSET` and the SES identity and receipt rule set are removed. Current values: `aws ssm get-parameters --names /suppliagent/<env>/sesDomain /suppliagent/<env>/waPhoneNumberId`.
4. *Console users*: self sign-up is off. Create each user in the Cognito user pool of `suppliagent-<env>-console` (`admin-create-user` with `--desired-delivery-mediums EMAIL`, Cognito emails a temporary password) and add it to one group: `backoffice`, `sales_rep` or `judge`.
5. *Demo page*: once the WhatsApp number and the order mailbox exist, republish the console with `VITE_DEMO_WHATSAPP="+39…" VITE_DEMO_ORDER_EMAIL="ordini@<sesDomain>" scripts/deploy-console.sh <env>`.

```bash
uv sync
cd infra && npm ci && npx cdk synth -c env=dev
npx cdk deploy --all -c env=dev
uv run python seed/seed.py --env dev
```

## Try it (for judges)

The console has a read-only `judge` role: judges can browse orders and see each handwritten ticket next to the lines the agent read, but cannot change anything (enforced by the API, not only by the UI). After signing in, the **Try the demo** page walks through ordering and offers a sample handwritten order to download.

_Coming soon_: console URL and `judge` credentials, WhatsApp number, test customer and order email address.

## Pre-existing code

None so far. Any third-party or pre-existing code will be listed here.

## License

[MIT](LICENSE)
