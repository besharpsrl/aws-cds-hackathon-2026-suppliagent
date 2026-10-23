# AWS CDS Agentic AI Partner Hackathon – Checklist submission

> **Team:** beSharp · **Progetto:** SuppliAgent – ordini HoReCa via WhatsApp per un cliente reale di beSharp
> **Deadline:** mercoledì **28/10/2026 ore 21:00** (ora italiana) = 13:00 PDT
> **Deadline interna consigliata:** lunedì **26/10/2026**
> Link: [Overview](https://aws-cds-partner.devpost.com/) · [Rules](https://aws-cds-partner.devpost.com/rules) · [FAQ](https://aws-cds-partner.devpost.com/details/faq) · [Enablement](https://aws-cds-partner.devpost.com/details/enablement) · [Discord](https://discord.gg/558g3B5wS2)

---

## Fase 0 – Azioni immediate (entro lun 12/10) ⏱️ hanno tempi di attesa

- [ ] Ogni membro si iscrive su Devpost ("Join Hackathon") con **email @besharp.it** e organizzazione partner **beSharp**
- [ ] Nominare il **Team Representative** (invia la submission, riceve i premi)
- [ ] Richiedere i **$50 di crediti AWS** (uno per team) → [AWS Promo Credit Request Form](https://app.smartsheet.com/b/form/01a0251b16487292bb4d686ddb725454)
  - Tempi: 3–5 giorni lavorativi · da applicare a un account AWS di beSharp · scadenza **31/10 23:59 PT**
- [ ] Ogni membro richiede il proprio **codice Kiro** → [Kiro Promo Credit Request Form](https://pulse.amazon/promotion/ZES8TZ8M)
  - Scaricare Kiro da `kiro.dev/downloads` e creare l'account (Builder ID o social login)
  - Riscattare su `kiro.dev/redeem/<CODICE>` **con lo stesso login** usato in Kiro
  - Scadenza **30/10 23:59 PT**
- [ ] Creare un **account AWS dedicato** all'hackathon + **budget alert**
- [ ] **WhatsApp (EUM Social):** collegare il Meta Business Portfolio (già verificato) e il numero dedicato a AWS End User Messaging Social; inviare un messaggio di test
- [ ] **Template WhatsApp** da sottomettere a Meta entro il 14/10: `order_confirmation`, `reorder_suggestion`, `delivery_update`, `order_pending_reminder`
- [ ] **Cliente**: richiedere catalogo, schede tecniche, regole di consegna, esempi di bigliettini, baseline del processo e autorizzazioni (uso dati anonimizzati, nome/marchio, ACE) → vedi `docs/TODO_DOCS.md` §1
- [ ] **SMS/RCS (EUM):**
  - [ ] Verificare se l'Italia è tra i 22 paesi supportati da RCS (altrimenti usare un device di test in un paese supportato oppure ripiegare su SMS)
  - [ ] Registrare l'identità mittente per SMS (sender ID / numero) per i paesi necessari
  - [ ] Registrare i device di test come **RCS tester** e accettare l'invito (2–20 min) — altrimenti la demo ricade silenziosamente su SMS
  - [ ] Se serve, richiedere aumento quota → [RCS Quota Increase Form](https://app.smartsheet.com/b/form/01a0ca1c66197f9eb2902b0c05b4a118)
- [ ] **SES:** verificare il dominio (DKIM/SPF/DMARC), richiedere l'**uscita dalla sandbox**, configurare la ricezione email (inbound)
- [ ] Entrare nel **Discord**, segnare gli **office hours** e guardare i webinar registrati (Enablement)

## Fase 1 – Setup (entro mer 14/10)

- [ ] Creare il repo **GitHub** del progetto
  - [ ] README con istruzioni di deploy e di test
  - [ ] **Licenza open source** (MIT o Apache-2.0) visibile nella sezione *About*
  - [ ] Struttura monorepo: `infra/` (CDK TS), `agent/` (Strands), `channels/`, `console/`, `docs/`
- [ ] Se repo **privato**: dare accesso ai **2 contatti dei giudici** (indirizzi nella pagina FAQ/Enablement, link "Email")
- [ ] Creare l'**opportunità ACE** su AWS Partner Central
  - [ ] Opportunità **nuova**, creata dopo il 14/09/2026, in stato almeno **"Created"**
  - [ ] Step 2 → *Opportunity marketing details* → *Sourced from marketing activity* → Marketing campaign: `AWS CDS Agentic AI Hackathon -Sept. 2026`
  - [ ] Step 4 → *Product selection*: **AWS End User Messaging**, **AWS End User Messaging Social**, **Amazon Simple Email Service (SES)**
  - [ ] Opportunità sul **cliente reale** (distribuzione alimentare HoReCa): dati del cliente validati, stima ARR concordata con il team commerciale beSharp
  - [ ] Annotare l'**ID** (`OXXXXXXXX`, in *Sell → Opportunities*)
- [ ] Analizzare i sample AWS: chat orchestrator, email categorization (SES Mail Manager), RCS agent setup, engagement database
- [ ] Assegnare gli stream di lavoro (vedi `SUPPLIAGENT_SOLUTION.md` § Organizzazione del team)

## Fase 2 – Sviluppo (14/10 → 24/10)

- [ ] Infra **CDK TypeScript** con deploy in un solo comando
- [ ] Agente **Strands su Bedrock AgentCore Runtime** (+ Memory, Gateway, Identity, Observability)
- [ ] Uso dei client CDS **realmente chiamato nel codice** (non basta citarlo nel README):
  - [ ] `socialmessaging` → `SendWhatsAppMessage`
  - [ ] `sesv2` → `SendEmail` + inbound
  - [ ] `pinpoint-sms-voice-v2` → `SendRcsMessage` / `SendTextMessage`
  - [ ] ❌ Non usare Pinpoint v1, `pinpoint-email` né EUM Push
- [ ] Console operatore web (live, handoff, KPI)
- [ ] Pipeline eventi CDS → analytics → KPI
- [ ] Dati di prova: catalogo anonimizzato, listini, stock, calendario consegne, clienti, storico ordini, bigliettini di test + seed/reset script
- [ ] Agente **multilingua** (EN per i giudici, IT per la demo)
- [ ] Commit frequenti e incrementali (dimostrano lavoro svolto nel periodo); dichiarare eventuale codice preesistente
- [ ] Code freeze funzionale: **ven 23/10**

## Fase 3 – Materiali (22/10 → 26/10)

- [ ] **Diagramma architetturale** (PNG/SVG nel repo e nella submission)
- [ ] **Descrizione testuale** in inglese: problema, soluzione, feature, servizi AWS usati, impatto misurabile
- [ ] **Descrizione dell'uso di EUM Social (WhatsApp)** → necessaria per il premio Meta ($10k)
- [ ] **Video demo ~3 minuti**
  - [ ] Su **YouTube o Vimeo**, pubblico
  - [ ] Mostra il progetto funzionante su device reale (telefono + console affiancati)
  - [ ] In inglese (o con sottotitoli inglesi)
  - [ ] Niente musica o marchi di terzi senza licenza
- [ ] **Istruzioni di test per i giudici** nel README: numero WhatsApp, indirizzo email, URL della console + credenziali
- [ ] Ambiente attivo e **accesso gratuito fino al 12/11/2026 17:00 PT**

## Fase 4 – Submission (entro lun 26/10)

- [ ] Prova di deploy pulito da zero su un account nuovo seguendo il README
- [ ] Il Representative compila il form Devpost:
  - [ ] URL del repo
  - [ ] Diagramma architetturale
  - [ ] Descrizione testuale
  - [ ] Link al video
  - [ ] URL / istruzioni di test
  - [ ] ID dell'opportunità ACE
  - [ ] Descrizione dell'uso di WhatsApp (premio Meta)
- [ ] Verifica finale di tutti i link (repo accessibile, video pubblico, console raggiungibile)
- [ ] **Submit** ✅

## Dopo la submission

- [ ] Monitorare costi e funzionamento fino al **12/11** (fine valutazione)
- [ ] Rispondere a eventuali richieste dei giudici
- [ ] Annuncio vincitori ~**19/11/2026**; in caso di vittoria, consegnare i moduli entro 10 giorni lavorativi
