# SuppliAgent – Devpost submission text (draft)

> Draft for the Devpost form (T-11). In English on purpose: it is pasted as is. Diagram: [`architecture.png`](./architecture.png), source [`architecture.drawio`](./architecture.drawio). Written on 28/10 before the code freeze: check the **Verify before submitting** list at the end and cut or move to "What's next" whatever is not on `dev`.

## Tagline

Restaurants keep ordering the way they always did, with a photo of a handwritten note on WhatsApp. SuppliAgent turns it into a verified, confirmed order for their food distributor.

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

AWS End User Messaging Social, Amazon SES, Amazon Bedrock (Nova), Amazon Bedrock AgentCore, Strands Agents, Amazon S3 Vectors, Amazon Transcribe, AWS Lambda, Amazon DynamoDB, Amazon SQS, Amazon SNS, Amazon EventBridge, Amazon API Gateway, Amazon Cognito, Amazon CloudFront, Amazon S3, AWS KMS, AWS CDK, Python, TypeScript, React.

## Verify before submitting

Each line is a claim above. Keep it only if it is true on `dev` at the freeze (12:00):

- [ ] Email confirmation **with the order PDF** is sent (T-26). If not: say "confirmation message" only and move the PDF to What's next.
- [ ] Interactive clarification buttons and the "Confirm" button on WhatsApp (T-25). If not: the questions are plain text (the text above already says "short questions"); drop the sentence about button ids.
- [ ] Reply to a real phone was proven end to end (T-68), in Italian and in English.
- [ ] Console: orders on real data with the photo next to the lines and line correction (T-62, PR #90).
- [ ] WhatsApp templates approved by Meta (T-29): then say "approved" and that the assistant can write first; until then keep the wording above.
- [ ] Voice notes read through Transcribe in the demo.
- [ ] Items faded in the diagram (roadmap): promote to solid and to the text only if deployed (handoff, copilot tools, proactivity, SMS/RCS, Memory, Observability, Guardrails, WAF, WebSocket chat, AgentCore Identity, CloudTrail, Budgets, Secrets Manager, configuration sets). After any change, regenerate `architecture.png` from the `.drawio`.
- [ ] Judges' instructions (number, email, console URL and credentials, sample note) are in the README (T-10) and the text says the same.
