# SuppliAgent – video demo script (≤ 3:00)

> T-12 · Narration in English (the video is for the judges); production notes in Italian. Narration is about 330 words: at a calm pace it fills ~2:20, the rest is screen time. Fallbacks exist for every scene that depends on a task not yet on `dev`: record **only what works on a real phone**, never a simulation presented as real (the rules ask for the project running on a real device).

## Format

- Split screen: **phone** (WhatsApp, screen recording) on the left, **console** (browser) on the right. Same take, one continuous flow.
- Language: English narration (or Italian with English subtitles). The customer writes in Italian, then once in English to show the language switch.
- Customer: a demo venue from the seed (e.g. _Bar Aurora_, `cus_003`) with the sample note `agent/evals/data/bigliettini/ordine_bar.jpeg` (printed, 8 lines, 3 lines to clarify, a "SCONTO!!" note that must **not** be applied). Rerun the three notes on `dev` the day before and use the one that reads best; the cursive one (`ordine_ristorante`) is the sample for the judges, not for the video.
- No music, no third-party logos beyond what the apps show on screen, no real customer or distributor name.

## Script

| Time | On screen | Narration |
|---|---|---|
| 0:00–0:15 | A handwritten order note, then a back-office person retyping it (stock footage is not allowed: use a screen capture of the ERP mock or a simple title card with the note) | "Every day, restaurants order from their food distributor with a photo of a handwritten note on WhatsApp. Someone retypes it, and every mistake costs money." |
| 0:15–0:40 | Phone: the owner sends the photo and a voice note ("add two kilos of butter"). Console: empty inbox | "This is SuppliAgent, built on AWS Communication Developer Services. The owner of a bar sends the photo and a voice note, exactly as they do today." |
| 0:40–1:25 | Phone: the agent's reply with the lines it read, then **short questions** only on the uncertain ones (which milk, which sugar), an out-of-stock product with a substitute. The owner answers (once in English). Cut the waiting time | "The agent reads the handwriting, matches every line with the catalog using this customer's purchase history and price list, and asks only about what it is not sure of. It checks stock and offers a substitute. It never applies the discount scribbled on the note: it has no authority to." |
| 1:25–1:55 | Phone: summary with total and delivery date, tap **Confirm**. Then the confirmation message and, if ready, the **email with the PDF** | "Before anything reaches the ERP, the customer sees a summary with the total and the delivery date and confirms explicitly. Then the order is numbered, the PDF is generated and the confirmation arrives on WhatsApp and by email." |
| 1:55–2:25 | Console: the new order appears in the inbox; open it; **the original photo next to the order lines**; the corrected lines highlighted; correct one line with a click. Show the `judge` login in read-only (buttons disabled) | "In the console the back office sees the same order with the original photo beside the lines. Lines the agent was unsure about are highlighted, and a correction is one click. Judges get a read-only role." |
| 2:25–2:50 | Architecture diagram (`docs/architecture.png`), highlight the CDS services as they are named | "Under the hood: End User Messaging Social for WhatsApp, SES for email, an agent built with Strands on Amazon Bedrock AgentCore running Amazon Nova, tools behind AgentCore Gateway, S3 Vectors for the catalog, all deployed with AWS CDK. Authorization is enforced inside every tool, by role." |
| 2:50–3:00 | Title card: repo URL and the WhatsApp number from the README | "Next: proactive reorders, a sales rep copilot and delivery notices by SMS and RCS. Try it with the number in our README." |

## If a scene is not ready at recording time

| Scene | Depends on | Fallback |
|---|---|---|
| 0:40–1:25 | Phone reply proven end to end (T-68) | **No fallback**: without a reply on the phone the video has no demo. Stop and fix T-68 first |
| 0:40–1:25 clarification "with buttons" | Interactive buttons (T-25) | Say "short questions"; the owner answers with a word. Do not say "buttons" |
| 1:25–1:55 email with PDF | T-26 | Show only the chat confirmation; remove "and by email" and "the PDF is generated" from the narration |
| 1:55–2:25 console on real data | T-62 (PR #90) and the console deployed with `VITE_ORDERS_SOURCE=api` | Never show mock data as real: record the console only after the deploy |
| 1:55–2:25 handoff (take over / reply / release) | T-49 + T-63 | Not in the video; cite it as a next step |
| Flows 6–8 (copilot, proactive reorder, SMS/RCS delivery) | Could tasks | Only the last line of the narration; do not show anything that is not deployed |

## Pre-recording checklist (Italiano)

- [ ] `dev` aggiornato da `main` (T-10) e dati ripristinati: `uv run python seed/reset.py --env dev` (solo MG, su richiesta).
- [ ] SSM `notifierSandbox` = `false`, così le risposte arrivano davvero sul telefono; il numero di prova è registrato come tester (M-02).
- [ ] Il contatto del telefono è **verificato** per il cliente demo (T-71): provare prima l'intero flusso, due volte, con lo stesso bigliettino.
- [ ] Una prova a secco cronometrata: foto → conferma sotto i 60 secondi di video dopo il taglio delle attese.
- [ ] Registrazione: schermo del telefono (QuickTime con cavo o registrazione schermo di iOS) e finestra del browser con la console; 1080p; notifiche disattivate; numeri personali sfocati (il numero della demo è pubblico).
- [ ] Console: account `judge` (M-06) per la scena a sola lettura; account `backoffice` per la correzione.
- [ ] Nessun nome del distributore reale, nessun dato reale (AGENTS §8.10); nessuna musica.
- [ ] Sottotitoli in inglese (file `.srt` o inseriti nel video); durata **≤ 3:00**.
- [ ] Caricamento su YouTube o Vimeo, **pubblico**, titolo "SuppliAgent – AWS CDS Agentic AI Hackathon"; link nel form Devpost (M-07, M-08) e nel README.
- [ ] Il testo del video non promette nulla che non sia su `dev`: stessa lista di `docs/SUBMISSION_TEXT.md` (_Verify before submitting_).
