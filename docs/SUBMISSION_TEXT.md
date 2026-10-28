# SuppliAgent – Devpost submission text (draft)

> Draft for the Devpost form (T-11). In English on purpose: it is pasted as is. Diagram: [`architecture.png`](./architecture.png), source [`architecture.drawio`](./architecture.drawio). Written on 28/10 while development continues: check the **Verify before submitting** list at the end and cut or move to "What's next" whatever is not on `dev`.

## Tagline

Devpost "General info" → *Elevator pitch* (max 200 characters; this one is 176):

Restaurants order on WhatsApp the way they always have: a photo of a handwritten list, a voice note or a text. SuppliAgent's AI agent turns it into a verified, confirmed order.

## About the project (Devpost "Project details" → "Project Story")

Paste the content of the block below as is (Devpost Markdown + LaTeX: `$$...$$` for display math). It describes the full scope: before submitting, fill in the `[[...]]` markers with measured values and remove anything not live on `dev` (see **Verify before submitting**). The architecture image is loaded from the public repo on `main`.

````markdown
## Inspiration

One of our customers at beSharp is a food distributor serving hotels, restaurants and cafés. Most of its orders don't come from a portal. They arrive at the end of service as a **photo of a handwritten list**, a **voice note** or a quick WhatsApp message to a sales rep, and someone in the back office retypes each one into the ERP.

That means minutes of data entry per order, misread abbreviations, "the usual" taken to mean the wrong thing, out-of-stock products found only after the order was promised, and nobody noticing when a regular customer quietly stops reordering.

We asked restaurant owners what would help. They didn't want a new app or a B2B portal: they wanted to **keep ordering on WhatsApp**. So we built an agent that meets them where they already are.

## What it does

SuppliAgent is an agentic AI that turns the way restaurants already order into verified, confirmed orders for their distributor. It serves three kinds of users.

**Restaurant owners (on WhatsApp or by email)**
- Send a **photo of a handwritten list**, a **voice note** or a text. The agent reads the handwriting with a vision model, transcribes the voice note and **matches every line to the catalog** using the customer's price list and purchase history.
- It **asks only when it has to**: when a line has several plausible matches, the customer gets a WhatsApp question with interactive buttons (at most three options plus "Other").
- It **checks the business rules** before promising anything: stock, price list, pack multiples, delivery days and cut-off. It proposes substitutes for missing products and makes **at most one** relevant suggestion per order.
- It asks for **explicit confirmation with one tap**. Nothing reaches the ERP before that, and confirmation is idempotent, so a double tap never creates two orders.
- Then the paperwork: the order goes to the ERP, a **confirmation email with the order PDF** and an **SMS/RCS confirmation** go out, followed by delivery notifications with suggested replies (*Received* / *Report a problem*).
- **Proactive reorders**: when a regular reorder is overdue, the agent offers to repeat it with one tap. It only does this with the customer's consent, never at night, and at most once every 7 days.

**Sales reps (copilot on WhatsApp or in the web chat)**
- "What should I pitch to this restaurant?": recommendations based on the customer's history, products they stopped buying, similar customers and current promotions.
- Catalog search and **technical sheet Q&A** (allergens, storage, formats) with citations, plus visit briefings and orders placed on behalf of a customer. Reps only ever see their own portfolio.

**Back office (web console)**
- Orders in real time, with the **original photo of the handwritten list next to the order lines**. Low-confidence lines are highlighted and can be corrected by picking another candidate.
- Live conversations with **take over / release** (human handoff), delivery issues and **impact KPIs**. A read-only `judge` role is available for the hackathon.

## How we built it

![SuppliAgent architecture](https://raw.githubusercontent.com/besharpsrl/aws-cds-hackathon-2026-suppliagent/main/docs/architecture.png)

Everything is serverless in `eu-west-1` and deployed with **AWS CDK (TypeScript)**: nine stacks, cdk-nag clean, one AWS KMS key for all data at rest.

| Layer | What we used |
|---|---|
| **Messaging (AWS CDS)** | **AWS End User Messaging Social** (WhatsApp, `SendWhatsAppMessage`), **Amazon SES v2** (`SendEmail` plus inbound email), **AWS End User Messaging SMS/RCS** (`SendRcsMessage`, `SendTextMessage`) |
| **Ingestion** | SNS → SQS (standard + DLQ) → Inbound Router (identity, role, idempotency, media to encrypted S3) → per-conversation turn buffer in DynamoDB → Turn Dispatcher (debounce + lock) |
| **Agent** | **Strands Agents on Amazon Bedrock AgentCore**: Runtime, Memory, Gateway (MCP tools on Lambda, IAM SigV4), Identity, Observability, plus Bedrock Guardrails |
| **Models** | **Amazon Nova Pro** (reasoning and handwriting vision) and **Nova Lite** (fast classification) through the `eu.` inference profile, so data and inference stay in the EU |
| **Knowledge** | **Amazon S3 Vectors** catalog index (Titan Text Embeddings V2), **Bedrock Knowledge Bases** for technical sheets, **Amazon Transcribe** for voice notes |
| **Orders** | DynamoDB, EventBridge `order.confirmed` → ERP adapter (mock) and order PDF, scheduled sweep for draft reminders and expiry |
| **Proactivity** | Nightly EventBridge Scheduler → Insights & Reorder Analyzer → Proactive Trigger |
| **Console** | React on CloudFront, Amazon Cognito (`backoffice`, `sales_rep`, `judge`), API Gateway REST + WebSocket |
| **Analytics** | Firehose → S3 Parquet → Glue → Athena for the KPIs, CloudWatch for operations |

A few design choices shaped the whole system:

- **One writer for all channels.** Only the Notifier is allowed to call the CDS send APIs. Channel policy (the WhatsApp 24-hour window, approved templates outside it, fallback to SMS or email) lives in one place.
- **One answer per burst.** People send three photos and two messages in ten seconds. The Turn Dispatcher waits for the burst to end (3 s for text, 6 s for media, 15 s at most) and holds a per-conversation lock, so the customer gets one coherent reply instead of five.
- **The model proposes, the code decides.** The model reads the list and proposes SKUs and quantities with a confidence score \\(c\\). Prices, totals, pack sizes, order status and permissions are decided in code. Each line is handled like this:

$$
\text{line} \;\rightarrow\;
\begin{cases}
\text{accepted automatically} & c \ge 0.85 \\
\text{clarification question (max 3 options + Other)} & 0.5 \le c < 0.85 \\
\text{flagged as unmatched, never guessed} & c < 0.5
\end{cases}
$$

- **Authorization inside the tools, not in the prompt.** The Dispatcher passes the caller's role and customer ids to the tools, and the model can't change them. A restaurant can only see its own data and a sales rep only their own portfolio, and every tool has negative authorization tests.
- **Proactive, but polite.** A reorder is due when the time since the last order exceeds 1.5 times the customer's average interval: \\(t_{\text{since last}} > 1.5\,\bar{\Delta t}\\). Even then, the agent only proposes it with consent, outside quiet hours and at most once every 7 days.
- **Synthetic data only.** The catalog, price lists, customers and order history are anonymized or synthetic.

## Challenges we ran into

- **Handwriting is hard.** Cursive, strikethroughs, arrows, quantities written as "2 cs" or "the usual" and notes that aren't order lines at all. The hard part isn't reading, it's knowing *when you've read badly*. Our first prototype read 62% of the lines right, and too many wrong lines came back looking valid. That pushed us towards the confidence thresholds above, clarification questions and a mandatory confirmation step instead of trusting the read.
- **Real messaging is messy.** Duplicate deliveries, bursts of messages, media that arrives after the text, the 24-hour window and templates that need Meta approval. We also learned that **SNS standard topics can't deliver to FIFO queues**, so we used standard SQS with idempotency on the provider message id and ordered messages by AWS receive time, and let the debounce do the rest.
- **Trusting a button.** On WhatsApp, an interactive reply id can be forged. A tap on "Confirm" only counts if it answers the summary of *that* order, and the order tool checks the quoted message id.
- **New services, tight deadline.** AgentCore and S3 Vectors are very new. We deployed them entirely with CDK and kept the agent as a zip code deployment (no container) to keep the deploy loop short.
- **Model availability.** We planned for Claude but it wasn't enabled on our account, so we moved to Amazon Nova through the EU inference profile. The model id is configuration, not code.

## Accomplishments that we're proud of

- A restaurant owner can go **from a photo of a handwritten list to a confirmed order in [[XX]] seconds** without installing anything, while the back office retypes nothing.
- **[[XX]]% of handwritten lines read correctly** on our anonymized evaluation set of **[[XX]] real-style notes**, and lines the agent isn't sure about are asked or flagged, never silently guessed.
- **All three AWS CDS channels working together**: WhatsApp for the conversation, email with the PDF for the paperwork, SMS/RCS for confirmations and delivery notices, with automatic fallback between them.
- A **real use case for a real distributor**, designed around how restaurants actually work and not around a demo script.
- **Fully reproducible**: one `cdk deploy`, cdk-nag clean, least-privilege IAM, encrypted everywhere, synthetic data only.

## What we learned

- **Put authorization in the tools.** Enforcing role and customer scope inside every tool made the agent simpler to trust and much simpler to test than prompt rules ever could.
- **Let the model propose and the code decide.** That split is what makes *ordering*, an action with money attached, safe to automate.
- **Conversation design matters as much as the model.** Debounce, short questions with buttons and one clear summary to confirm did more for the experience than any prompt tweak.
- **Measure before you claim.** A small, honest evaluation set of handwritten notes told us more than any demo did, and changed the design.

## What's next for SuppliAgent

- **Pilot with the distributor**: real catalog and ERP integration replacing the mock, and a measured baseline (orders per day, entry time, error rate) to compare against.
- **Better handwriting confidence**: calibration on a larger set of notes and learning from back-office corrections.
- **More channels and languages**: RCS rich cards for reorder proposals and more languages beyond Italian and English.
- **Smarter proactivity**: seasonal patterns, menu-aware suggestions and promotions targeted per segment.
- **Model choice**: an option for Anthropic Claude on Amazon Bedrock as soon as it's enabled on the account, compared with our evaluation suite.
````

## The problem

Food distributors for the HoReCa channel (hotels, restaurants, cafés) receive orders in the most informal ways: photos of handwritten lists, voice notes, short WhatsApp messages and emails to sales reps. Someone at the back office retypes them into the ERP. That means slow data entry, transcription mistakes, abbreviations and "the usual" misread, out-of-stock products discovered after the order, and no one watching for the regular customer who stopped reordering.

We built SuppliAgent with beSharp for a real use case: a food distributor that is a beSharp customer. Restaurant owners do not want an app or a portal: they want to keep using WhatsApp.

## What it does

- **Order from a photo, a voice note or a text on WhatsApp, or by email.** The agent reads the handwritten note (vision), transcribes voice notes, and matches every line to the catalog using the customer's price list and purchase history.
- **Asks only when needed.** Lines the matcher is sure about are accepted and lines with close candidates get a short question with at most three options. The agent is told to flag lines it cannot read instead of guessing, and the customer must confirm the summary before anything is sent.
- **Checks the business rules** before anything is promised: stock, price list, pack sizes, delivery days and cut-off. It proposes substitutes for missing products.
- **Explicit confirmation.** An order reaches the ERP only after the customer clearly confirms the summary. Confirmation is idempotent: a double tap never makes two orders.
- **Then the paperwork.** The ERP adapter (a mock) numbers the order, an order PDF is generated and the customer gets a confirmation in the chat; the email with the PDF follows.
- **Back office console.** Orders refreshed within seconds, with the **original photo of the note next to the order lines**. The back office can correct a line by picking one of the candidates, and a read-only `judge` role is available for the hackathon.
- **Sales rep copilot** (role-based access in the agent): reps get the same assistant, limited to their own portfolio.

Everything the agent does goes through tools that enforce authorization **by role inside the tool**, not only in the prompt: a restaurant can only see its own data and a sales rep only their portfolio. The agent introduces itself as a virtual assistant and never invents prices, discounts or conditions outside the price list.

## How we built it

![Architecture](./architecture.png)

| Layer | AWS services |
|---|---|
| Messaging (AWS CDS) | AWS End User Messaging Social (WhatsApp), Amazon SES v2 (send and receive email) |
| Ingestion | Amazon SNS → Amazon SQS (standard queue + DLQ) → Lambda Inbound Router (identity, role, idempotency, media to S3) → per-conversation turn buffer in DynamoDB with delayed SQS flush → Lambda Turn Dispatcher (debounce and lock: **one answer per burst of messages**) |
| Agent | **Strands Agents on Amazon Bedrock AgentCore Runtime**, tools exposed through **AgentCore Gateway** (MCP, IAM SigV4) on Lambda targets |
| Models | **Amazon Nova Pro** on Amazon Bedrock through the `eu.` inference profile, for reasoning and handwriting vision: data and inference stay in the EU |
| Catalog matching | **Amazon S3 Vectors** index with Amazon Titan Text Embeddings V2, hybrid with fuzzy matching and the customer's history |
| Voice | Amazon Transcribe |
| Orders | DynamoDB, EventBridge (`order.confirmed`), Lambda ERP adapter (mock), Lambda order PDF, scheduled EventBridge sweep (draft reminders and expiry) |
| Console | CloudFront + S3 (React), Amazon Cognito (`backoffice`, `sales_rep`, `judge`), API Gateway REST + Lambda |
| Security and operations | AWS KMS (one CMK for data at rest), IAM least privilege, `cdk-nag`, CloudWatch |
| Infrastructure | **AWS CDK (TypeScript)**, nine stacks, one command to deploy |

Design choices that matter:

- **Standard queues, not FIFO.** SNS standard topics (the ones End User Messaging Social and SES publish to) cannot deliver to FIFO queues. We use idempotency on the provider message id and order messages by their AWS receive time; the debounce does the rest.
- **One writer.** Only the Notifier calls the CDS send APIs, so channel policy (WhatsApp 24-hour window, templates, fallback) lives in one place.
- **The model proposes, the code decides.** The model suggests SKUs and quantities; names, units, prices, totals, status transitions and who may touch an order are decided in code.
- **Synthetic data only.** Catalog, price lists, customers and order history are anonymized or synthetic.

## How SuppliAgent uses AWS End User Messaging Social (WhatsApp)

Devpost field "Describe how AWS End User Messaging Social (EUM - WhatsApp) was used." (plain textarea: paste the block as is; full scope, check **Verify before submitting**):

```text
WhatsApp is the product, not an add-on: it is the channel restaurant owners already use to order from their food distributor, so SuppliAgent lives there.

- Receiving: the distributor's WhatsApp Business number is linked to AWS End User Messaging Social. Every inbound text, photo (the handwritten order list), voice note and button reply arrives as an event on an Amazon SNS topic, then goes through SQS to our Inbound Router. Media is fetched with GetWhatsAppMessageMedia and stored encrypted in S3, so the agent can read the photo (Amazon Nova vision) or transcribe the voice note (Amazon Transcribe), and the back office console can show the original list next to the order lines.
- Conversation design: messages sent in a burst (three photos and two texts in ten seconds) are merged into one turn by a per-conversation debounce and lock, so the customer gets one coherent answer instead of five. Inbound messages are marked as read and processed idempotently on the WhatsApp message id.
- Sending: a single Notifier Lambda is the only component allowed to call SendWhatsAppMessage. It sends free-form answers inside the 24-hour customer service window and interactive messages: reply buttons for clarifications (at most three options plus "Other") and the one-tap "Confirm" on the order summary. A tap only counts if it answers that exact order summary, so a forged or stale button cannot confirm an order.
- Templates: outside the 24-hour window the Notifier uses only Meta-approved message templates (order confirmation, pending-order reminder, delivery update and proactive reorder proposal, in Italian and English), defined as code in the repo. If WhatsApp is not possible, it falls back to SMS/RCS or email.
- Identity and safety: the sender's number identifies the contact and their role (restaurant owner or sales rep). Unknown numbers are asked for their venue and customer code before ordering. Every agent tool enforces that a customer only sees their own data and a rep only their own portfolio.
- Same channel, two audiences: restaurant owners order on WhatsApp, and sales reps use the same number as a copilot (recommendations, technical sheets, orders on behalf of customers).
```

Background notes (not for the form):
WhatsApp is the product, not an add-on: it is the channel restaurants already use to order.

- **Receiving.** A WhatsApp Business number is linked to AWS End User Messaging Social. Inbound text, images (the handwritten notes), voice notes and interactive replies arrive as events on an SNS topic and enter the pipeline described above. Media is downloaded and stored encrypted in S3 so the agent can read the photo and the console can show it next to the order lines.
- **Sending.** The Notifier calls `socialmessaging:SendWhatsAppMessage` for every outgoing WhatsApp message, in the language of the customer. Free-form answers go out inside the 24-hour customer service window. Outside it the Notifier does not send: the message templates and the email fallback are on the roadmap. The WhatsApp **message templates** (order confirmation, pending-order reminder, delivery update, reorder suggestion, in Italian and English) are defined and tested in the repo and submitted to Meta.
- **Conversation design for WhatsApp.** Several photos and messages sent in a burst are merged into one turn, so the customer gets one coherent answer instead of five. Clarifications are short questions with at most three options. A tap on a confirmation button only counts if it answers the summary of that very order (button ids can be forged, so the order tool checks the message id).
- **Identification.** An unknown number is asked for the venue name and customer code and is then linked to the customer, pending the distributor's verification. Authorization by role is enforced inside every tool.
- **Read receipts.** The agent marks inbound WhatsApp messages as read; delivery-status tracking is on the roadmap.

Other CDS services in the code: Amazon SES v2 (`sesv2:SendEmail`, plus inbound email as an ordering channel). Amazon End User Messaging SMS/RCS (`pinpoint-sms-voice-v2`) is on the roadmap.

## Measurable impact

- **Time per order.** The target is seconds of customer time and zero retyping, against minutes of manual entry per order. The demo shows the time from the photo to the confirmed order.
- **Reading handwriting.** We measure the agent against a small set of anonymized handwritten notes (`agent/evals/`). On three notes (29 lines) the first prototype reads 62% of the lines correctly (18 of 29), and 9 of 29 were read wrongly but shown as valid; the weak spot is cursive handwriting. That is why nothing goes to the ERP without the customer's explicit confirmation of the summary, and why the next work is on calibrating confidence and on the clarification questions.
- **No baseline claims.** The distributor's real baseline (orders per day, entry time, error rate) is not part of this submission, so we do not quote percentages we did not measure.

## Challenges

- Handwriting is hard for a general model: cursive, strikethroughs, arrows and notes that are not order lines. Calibrated confidence is the difficult part, so the design leans on clarification questions rather than on trusting the read.
- Real messaging is messy: duplicate deliveries, bursts of messages, a 24-hour window, templates that need approval. The pipeline is built around idempotency, debounce and a single outbound writer.
- AgentCore and S3 Vectors are new: we shipped them with CDK and kept the agent as a zip code deployment (no container).

## What we learned

Putting authorization inside the tools instead of in the prompt made the agent simpler to trust and simpler to test. Treating the model as a proposer and the code as the decision maker is what makes "ordering" safe to automate.

## What's next

Proactive reorder proposals ("you usually reorder olive oil every 10 days"), the sales rep copilot with technical sheet Q&A (Bedrock Knowledge Bases), delivery notices by SMS/RCS, AgentCore Memory and Guardrails, a live conversation view with take over / release, KPI dashboards, and a Claude model option when it becomes available on the account.

## Built with

Devpost "Built with" (max 25 tags; type each one and press Enter). These 25, in this order:

AWS End User Messaging Social, WhatsApp, Amazon SES, AWS End User Messaging SMS, RCS, Amazon Bedrock, Amazon Nova, Amazon Bedrock AgentCore, Strands Agents, Amazon Bedrock Knowledge Bases, Amazon S3 Vectors, Amazon Transcribe, AWS Lambda, Amazon DynamoDB, Amazon SQS, Amazon SNS, Amazon EventBridge, Amazon API Gateway, Amazon Cognito, Amazon CloudFront, Amazon Athena, AWS CDK, Python, TypeScript, React.

Left out to stay within 25 (they are in the story): Amazon S3, AWS KMS, Bedrock Guardrails, MCP, Firehose, Glue, CloudWatch.

## Verify before submitting

Each line is a claim above. Keep it only if it is true on `dev` when submitting:

- [ ] Email confirmation **with the order PDF** is sent (T-26). If not: say "confirmation message" only and move the PDF to What's next.
- [ ] Interactive clarification buttons and the "Confirm" button on WhatsApp (T-25). If not: the questions are plain text (the text above already says "short questions"); drop the sentence about button ids.
- [ ] Reply to a real phone was proven end to end (T-68), in Italian and in English.
- [ ] Console: orders on real data with the photo next to the lines and line correction (T-62, PR #90).
- [ ] WhatsApp templates approved by Meta (T-29): then say "approved" and that the assistant can write first; until then keep the wording above.
- [ ] Voice notes read through Transcribe in the demo.
- [ ] Items faded in the diagram (roadmap): promote to solid and to the text only if deployed (handoff, copilot tools, proactivity, SMS/RCS, Memory, Observability, Guardrails, WAF, WebSocket chat, AgentCore Identity, CloudTrail, Budgets, Secrets Manager, configuration sets). After any change, regenerate `architecture.png` from the `.drawio`.
- [ ] Judges' instructions (number, email, console URL and credentials, sample note) are in the README (T-10) and the text says the same.
