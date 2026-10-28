<p align="center">
  <img src="assets/brand/suppliagent_logo_light.png" alt="SuppliAgent" width="480">
</p>

# SuppliAgent – Guide for judges

This page explains what SuppliAgent does, how it is built and **how to test it yourself** in a few minutes. Developer setup and deploy from scratch are in the main [`README.md`](README.md).

## 1. Why SuppliAgent

Restaurants order from their food distributor the way they always have: a **photo of a handwritten list**, a voice note or a short message on **WhatsApp**, sometimes an email. Someone at the distributor retypes every order into the ERP: slow, error-prone, with abbreviations and "the usual" misread, missing products discovered too late and nobody noticing the regular customer who stopped ordering.

SuppliAgent is an **agentic AI assistant** that takes those messages as they are and turns them into **verified, explicitly confirmed orders**. It was built by [beSharp](https://www.besharp.it) for a real use case of a beSharp customer, a food distributor serving the HoReCa channel (hotels, restaurants, cafés). All data in the demo is **synthetic** and the brand is fictional.

**What a restaurant owner gets**
- Order on WhatsApp with a photo, a voice note or text, or by email; Italian and English.
- The agent reads the note, **matches every line to the catalog** using the customer's purchase history, checks **stock, price list, pack sizes, delivery days and cut-off**, and asks **only about uncertain lines** (interactive buttons).
- A summary with estimated total and delivery date; nothing reaches the ERP without an explicit **Confirm**.
- After confirmation: order number, **email with the order PDF**, order status, changes or cancellation until the cut-off.

**What the distributor gets**
- A **back-office console** with every order next to the original handwritten note, live conversations and **human handoff** (take over, reply, release).
- A **copilot for sales reps** (product suggestions, technical sheet Q&A with citations), **proactive reorder** proposals and **delivery notices** over RCS/SMS.

## 2. How it is built

<p align="center"><img src="docs/architecture.png" alt="SuppliAgent architecture"></p>

| Layer | What we used |
|---|---|
| **Channels (AWS CDS)** | **AWS End User Messaging Social** for WhatsApp (`SendWhatsAppMessage`: text, interactive buttons, templates, read receipts, media download), **Amazon SES v2** for outbound email with PDF and inbound email orders (`SendEmail`, receipt rules), **AWS End User Messaging SMS** for RCS with SMS fallback (`SendRcsMessage`, `SendTextMessage`) |
| **Ingestion** | SNS → SQS (idempotent on the provider message id) → Inbound Router (normalization, identity and role, media to S3) → per-conversation **debounce with a lock**: a photo, a voice note and a text sent together get **one** answer |
| **Agent** | **Strands Agents on Amazon Bedrock AgentCore**: Runtime, Gateway (domain tools on Lambda exposed over MCP), Memory, Observability; **Amazon Nova Pro / Nova Lite** via the `eu.` inference profile (vision for handwritten notes), Bedrock Guardrails, Amazon Transcribe for voice notes |
| **Catalog intelligence** | Product index on **Amazon S3 Vectors** with hybrid matching boosted by purchase history; **Bedrock Knowledge Base** (on S3 Vectors) for technical sheets |
| **Orders** | DynamoDB, EventBridge `order.confirmed` → ERP adapter (mock) and order PDF; a sweeper for reminders and expiry |
| **Outbound** | One **Notifier** is the only component allowed to send: channel policy, WhatsApp 24-hour window and approved templates, RCS → SMS fallback, idempotent sends |
| **Proactive** | EventBridge Scheduler → nightly reorder analysis → template proposal, only with the customer's consent |
| **Console** | React on CloudFront, Cognito roles (`backoffice`, `sales_rep`, read-only `judge`), API Gateway |

Everything is serverless in **eu-west-1** (data and inference stay in the EU), deployed with **AWS CDK (TypeScript)** in 9 stacks with cdk-nag. Authorization is enforced **inside the tools**: a customer only sees their own orders and prices, a sales rep only their portfolio, whatever the model asks. Full design (Italian): [`docs/INFRASTRUCTURE_DESIGN.md`](docs/INFRASTRUCTURE_DESIGN.md).

## 3. Test it yourself

The demo runs on the live `dev` environment until **12 November 2026**. You need WhatsApp on your phone (or an email client) and a browser.

### Access

| What | Value |
|---|---|
| WhatsApp number | **+39 345 246 0472** (display name "SuppliAgent") |
| Order email | **ordini@suppliagent.stonecutters.besharp.net** |
| Console | https://app.suppliagent.stonecutters.besharp.net (fallback: https://d3po2gqnlfcxyr.cloudfront.net) |
| Console user (read-only) | `matteo.goretti+judge@besharp.it` / `judgeAWSCDShackathon2026!` |

**Test customers** – the agent recognizes you by phone number or email address. The first time, it asks for your venue name and customer code: give one of these (pick one at random, judges using the same code share the venue and its orders). They are verified at once, so you can order right away.

| Venue name | Customer code | VAT number |
|---|---|---|
| Demo Bistro 1 | C90001 | IT90000000901 |
| Demo Bistro 2 | C90002 | IT90000000902 |
| Demo Bistro 3 | C90003 | IT90000000903 |

**Sample handwritten orders** to send as a photo (open one on your computer and photograph the screen, or forward the image): [`ordine_ristorante.jpeg`](agent/evals/data/bigliettini/ordine_ristorante.jpeg), [`ordine_bar.jpeg`](agent/evals/data/bigliettini/ordine_bar.jpeg), [`ordine_pub.jpeg`](agent/evals/data/bigliettini/ordine_pub.jpeg). The console's **Try the demo** page offers one for download too.

### Scenario 1 – Order from a handwritten note on WhatsApp (5 minutes)

1. Write `hi` (or `ciao`) to **+39 345 246 0472**. The assistant introduces itself as a virtual assistant and asks who you are.
2. Reply with a venue name and code from the table, e.g. `Demo Bistro 2, code C90002`.
3. Send the **photo** of a handwritten order. Optionally add, right after it, a **voice note** or a text such as `add 2 kg of butter`: messages sent together are answered once.
4. The agent lists the lines it read and asks only about the uncertain ones: answer with the **buttons** or in your own words ("the first one", "the 1 kg one").
5. You get a **summary** with quantities, estimated total and delivery date. Tap **Confirm** (or **Modify** to change something).
6. You receive the **order number**. If you give an email address when asked, the **confirmation email with the PDF** follows within a minute.
7. Then try: `when does my order arrive?`, `add 2 cans of peeled tomatoes`, `cancel the order`. Changes are allowed until the cut-off (18:00 Europe/Rome the day before delivery).

Write in English and the agent answers in English; write in Italian and it switches.

### Scenario 2 – Order by email (3 minutes)

Send an email to **ordini@suppliagent.stonecutters.besharp.net** with the order in the body or the photo attached. The first time, the agent replies asking for venue and code, like on WhatsApp. Replies stay in the same email thread; answering the confirmation email lets you change the order.

### Scenario 3 – Product questions (1 minute)

Ask on WhatsApp about a product: allergens, storage, pack formats (e.g. `does the burrata contain lactose?`). Answers come from the technical sheets with a citation; if a sheet does not cover it, the agent says so instead of guessing.

### Scenario 4 – The back-office console (3 minutes)

1. Sign in at https://app.suppliagent.stonecutters.besharp.net with the judge user.
2. **Orders**: find your order (by venue name). Open it to see the **handwritten note next to the lines** the agent read, with status and price.
3. **Conversations**: follow your chat as the back office sees it, including handoffs. When a customer asks for a human, or the agent cannot proceed, the conversation moves to an operator who can take over, reply on the customer's channel and hand it back.

The `judge` role is **read-only**, enforced by the API: you can look at everything, change nothing.

### Good to know

- **Handwriting**: on hard-to-read notes the agent may misread some lines. By design it asks rather than guesses, and nothing is ordered without your confirmation.
- **WhatsApp 24-hour window**: free-form replies are possible within 24 hours of your last message; after that the system can only send Meta-approved templates (e.g. order reminders).
- **RCS/SMS** delivery notices and the **sales rep copilot** are live but reach only registered test devices and sales rep numbers (RCS test agent and SMS sandbox), so they are shown in the video rather than open to judges.
- **Proactive reorder** runs on a nightly schedule over the order history, so it is not something you can trigger during a short test.
- Demo data may be reset during the judging period: your phone number stays registered, past orders may disappear.

## 4. More

- Code and setup: [`README.md`](README.md) · design documents (Italian): [`docs/`](docs/README.md)
- License: [MIT](LICENSE)
