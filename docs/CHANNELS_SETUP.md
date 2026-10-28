# SuppliAgent – Setup dei canali (WhatsApp, template, RCS/SMS)

> Passi manuali non automatizzabili in CDK per i canali di `dev` (account `471112860008`, region **eu-west-1**, profilo `default`). Il dominio SES (identità, DNS, uscita dalla sandbox) è nel [README](../README.md#getting-started), *Manual steps* passo 2.
> Le parti nel browser (console AWS, portale Meta) si fanno a mano; i comandi CLI li esegue un agente di sviluppo su richiesta, solo dopo conferma quelli che modificano risorse.
> Riferimenti: [AWS – WhatsApp getting started](https://docs.aws.amazon.com/social-messaging/latest/userguide/getting-started-whatsapp.html) · [Meta – numeri di telefono](https://developers.facebook.com/docs/whatsapp/cloud-api/phone-numbers) · [AWS – Testing RCS](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-testing.html).

## Stato (`dev`, 28/10/2026)

| Risorsa | Valore | Stato |
|---|---|---|
| WABA | `waba-8c2d297ba5154c33b7d0ceac98c7410a` (Meta `2035382963843064`) | collegata, eventi su `suppliagent-dev-wa-events` |
| Numero WhatsApp | **+39 345 246 0472** (`phone-number-id-79f96a1ea97d47aabfce52eb7b8cf23c`) | ricezione e invio reali (`notifierSandbox = false`) |
| Template WhatsApp | 8 (4 × IT/EN, §2) | tutti **`APPROVED`** (28/10) |
| Agente RCS | `rcs-83650561df2543e1942ccb9a500fa736` (`arn:aws:sms-voice:eu-west-1:471112860008:rcs-agent/rcs-83650561df2543e1942ccb9a500fa736`) | `TESTING`, testing agent `ACTIVE` (`suppliagent_wm1yg2rx_agent`) |
| Registrazione di test | `registration-a8d414f7801a465d90b9fe3cc34a28b2` (`TEST_RCS_LAUNCH_REGISTRATION`) | `COMPLETE` (approvata in ~3 min) |
| Tester RCS | 1 telefono Android con Google Messaggi | `VERIFIED`, messaggio di prova **ricevuto** (28/10 11:36) |
| Sender ID SMS | `SUPPLIAGENT` per IT, `TRANSACTIONAL` (`arn:aws:sms-voice:eu-west-1:471112860008:sender-id/SUPPLIAGENT/IT`) | attivo, **solo one-way** |
| Account SMS | `SANDBOX`, spend limit SMS e RCS 1 $/mese | sufficiente per la demo |
| Two-way RCS | topic `suppliagent-dev-sms-inbound` | attivato dal `ChannelsStack` (T-27, §3.3) |

I numeri dei tester non si scrivono nel repo né nelle issue.

## 1. WhatsApp (WABA)

### 1.1 Prima di iniziare (checklist)

- [ ] **Numero di telefono** (SIM o eSIM nuova):
  - mai registrato su WhatsApp né su WhatsApp Business (se lo è: cancellare prima l'account WhatsApp da quel numero);
  - riceve **SMS o chiamate**: serve solo per il codice di verifica (OTP);
  - dopo il collegamento **non installarlo su WhatsApp**: i messaggi passano da AWS. Chiamate e SMS normali restano.
- [ ] **Account Facebook personale** con cui fare login nel portale Meta.
- [ ] **Meta Business Portfolio** (ex Business Manager): usare quello di beSharp se esiste (chiedere a chi lo gestisce di darti accesso come amministratore), altrimenti se ne crea uno durante la procedura.
- [ ] **Display name** scelto, es. `SuppliAgent Demo`: deve rispettare le [linee guida Meta](https://www.facebook.com/business/help/757569725593362) (niente parole generiche da sole, coerente con l'azienda). Meta lo revisiona.
- [ ] **PIN a 6 cifre** per la verifica in due passaggi: sceglilo e conservalo in un password manager. Non va scritto nel repo né condiviso in chat.
- [ ] Accesso alla **console AWS** sull'account `471112860008` (SSO AdministratorAccess).
- [ ] Già pronto (fatto il 26/10, non serve altro): topic SNS **`suppliagent-dev-wa-events`** con la policy che autorizza `social-messaging.amazonaws.com` a pubblicare, chiave KMS del progetto che lo permette.

Tempo stimato: 15–20 minuti.

### 1.2 Collegamento del numero (console AWS + portale Meta)

1. Apri <https://console.aws.amazon.com/social-messaging/> e imposta la region in alto a destra su **Europe (Ireland) eu-west-1**. Il WABA vive in una sola region: se sbagli region va rifatto.
2. Menu **Business accounts** → **Link business account** → **Launch Facebook portal**. Si apre una finestra Meta: fai login con Facebook.
3. **Meta Business Portfolio**: seleziona quello di beSharp oppure crea un portfolio nuovo (nome azienda, sito, paese Italia).
4. **WhatsApp Business Account**: crea un nuovo WABA:
   - nome del WABA (interno, es. `SuppliAgent dev`);
   - **display name** (visibile ai clienti);
   - fuso orario `Europe/Rome`, categoria (es. *Food & Grocery*), descrizione breve, sito.
5. **Numero**: inserisci il numero con prefisso `+39`, scegli la verifica **SMS** (o **Phone call** se l'SMS non arriva), inserisci il codice ricevuto.
6. Conferma i permessi richiesti da Meta e chiudi la finestra: torni alla console AWS.
7. Nella console AWS completa la pagina del numero:
   - **Two-step verification PIN**: il PIN a 6 cifre di §1.1;
   - **Data localization region**: lasciare vuoto;
   - **Tags**: `Project` = `Hackathon AWS CDS`, `Owner` = `matteo.goretti@besharp.it`, `Env` = `dev` (obbligatori su tutte le risorse dell'account);
   - **Message and event publishing**: attivo, destinazione **Amazon SNS**, topic **`suppliagent-dev-wa-events`** (ARN: `aws ssm get-parameter --name /suppliagent/dev/waEventsTopicArn --query Parameter.Value --output text --region eu-west-1`). Senza questo non arrivano i messaggi in ingresso. Se il campo dà errore, saltalo: lo imposta Claude Code (§1.3).
8. **Add phone number**. Lo stato del numero diventa attivo in pochi minuti; il display name resta *in review* finché Meta non lo approva (non blocca i test).

Annota (non sono segreti): **WABA ID** (`waba-…`) e **phone number ID** (`phone-number-id-…`), visibili nella pagina del business account. Claude Code li recupera comunque da CLI.

### 1.3 Configurazione lato AWS (Claude Code)

Profilo `default`, account `471112860008`, region `eu-west-1`. Comandi in sola lettura salvo dove indicato.

```bash
export AWS_PROFILE=default AWS_REGION=eu-west-1 AWS_PAGER=""
# ID del WABA e del numero
aws socialmessaging list-linked-whatsapp-business-accounts
aws socialmessaging get-linked-whatsapp-business-account --id <WABA_ID> \
  --query 'account.{waba:id,events:eventDestinations,phones:phoneNumbers[].{id:phoneNumberId,number:displayPhoneNumber,name:displayPhoneNumberName}}'
```

Se `eventDestinations` è vuoto (mutante, solo dopo conferma):

```bash
TOPIC=$(aws ssm get-parameter --name /suppliagent/dev/waEventsTopicArn --query Parameter.Value --output text)
aws socialmessaging put-whatsapp-business-account-event-destinations --id <WABA_ID> \
  --event-destinations eventDestinationArn="$TOPIC"
```

Registrare l'ID del numero nel parametro SSM `waPhoneNumberId` (creato dallo stack **`channels`**, letto a runtime dal Router per scaricare i media): scriverlo in `infra/config/environments.ts` (`waPhoneNumberId` dell'ambiente) e fare un deploy di `channels` (mutante, solo dopo conferma). Il dominio SES resta quello della config, senza `-c`:

```bash
cd infra && rm -rf cdk.out
npx cdk deploy suppliagent-dev-channels --exclusively -c env=dev \
  --profile default
aws ssm get-parameter --name /suppliagent/dev/waPhoneNumberId --query Parameter.Value --output text
```

Il **Router**, il Dispatcher e il Notifier sono invece nello stack **`messaging`**: una correzione al codice del Router si porta su AWS con `npx cdk deploy suppliagent-dev-messaging --exclusively -c env=dev --profile default`. Dopo il deploy controllare che `CodeSize` della Lambda non sia di poche centinaia di byte (zip vuoto, vedi [`START_HERE.md`](../START_HERE.md) §1.4).

### 1.4 Prova di ricezione

1. **Farsi riconoscere come cliente di prova** (altrimenti il mittente risulta `UNKNOWN` e l'agente chiede codice cliente e nome del locale; un contatto identificato così resta *in attesa di verifica* e non può ordinare). Aggiungere il proprio numero in `seed/private/channel-identities.json` (escluso da git; gli agenti di sviluppo non leggono `seed/private/`), stessa forma di `seed/data/channel-identities.json`:

   ```json
   [{ "channelAddress": "WHATSAPP#+39XXXXXXXXXX", "channel": "WHATSAPP",
      "contactId": "con_003", "role": "CUSTOMER_CONTACT", "verified": true }]
   ```

   Poi `uv run python seed/seed.py --env dev` (riscrive **tutti** gli item del seed) oppure, meno invasivo, `PutItem` del solo item nella tabella `suppliagent-dev-channel-identities`. Il contatto scelto condivide la conversazione (`conv_con003`) con le prove del simulatore: ripulirla con `seed/reset.py` prima della demo.
2. Dal tuo telefono scrivi `ciao` al numero e invia una **foto** (es. un bigliettino).
3. Verifiche (sola lettura):
   - log del Router: `aws logs tail /aws/lambda/suppliagent-dev-inbound-router --since 10m` → `message stored` con `role` del contatto, nessun `media dropped`;
   - item nuovi in `suppliagent-dev-messages`; quello della foto ha l'attachment con `s3Uri`;
   - oggetto nel bucket media sotto `media/<contactId|conversationId>/<messageId>/<mediaId>.jpeg`;
   - Dispatcher `turn done`, Notifier `reply sent`;
   - DLQ `suppliagent-dev-inbound-dlq` vuota.

**Risposta sul telefono**: da T-68 su `dev` l'invio è **reale** (`notifierSandbox: 'false'` in `infra/config/environments.ts`, scritto in SSM dal deploy di `foundation`), anche per i giudici. Con il sandbox acceso (`true`) la risposta dell'agente viene solo registrata (log `reply sent` con `sandbox: true` e item `OUTBOUND` con stato `SANDBOX`). Il simulatore (`scripts/simulate_channel.py`) funziona solo col sandbox acceso: per una prova col simulatore accenderlo in SSM (letto a ogni invio, nessun deploy) e spegnerlo subito dopo, avvisando chi lavora in parallelo, perché nel frattempo le risposte ai telefoni veri non partono:

```bash
aws ssm put-parameter --name /suppliagent/dev/notifierSandbox --value true --overwrite
# ... prova col simulatore ...
aws ssm put-parameter --name /suppliagent/dev/notifierSandbox --value false --overwrite
```

Un deploy di `foundation` riporta comunque il parametro al valore della config (`false`).

### 1.5 Dopo il collegamento

- **Template WhatsApp**: §2. Servono per scrivere fuori dalla finestra di 24 h (conferme, promemoria, riordino).
- **Pagina demo della console**: `AWS_PROFILE=default VITE_DEMO_WHATSAPP="+393452460472" VITE_DEMO_ORDER_EMAIL="ordini@suppliagent.stonecutters.besharp.net" scripts/deploy-console.sh dev` (i valori sono anche in `console/.env.example`; lo script li legge dalle variabili d'ambiente, non dai file `.env`).
- **Ambiente dei giudici**: è `dev` (unico ambiente, decisione del 27/10), con lo stesso WABA e lo stesso numero.

### 1.6 Limiti e costi da sapere

- **Senza Business Verification** del portfolio: messaggi avviati dall'azienda (template) a max **250 destinatari unici ogni 24 h**; max **2 numeri** per portfolio; display name poco visibile nelle chat. Le risposte entro 24 h dal messaggio del cliente non hanno questo limite: per la demo basta.
- **Display name rifiutato**: il limite di invio si abbassa e il numero può essere scollegato; correggerlo dalla pagina del numero e rinviarlo in revisione.
- **Costi**: AWS 0,005 $ per messaggio in uscita, 0,001 $ in ingresso; Meta per messaggio consegnato, con i **primi 1.000 messaggi di servizio al mese per numero gratuiti**. Per la demo: pochi centesimi.
- Il numero di test gratuito di Meta **non** si collega ad AWS End User Messaging Social: serve un numero reale.

### 1.7 Problemi comuni

| Sintomo | Cosa fare |
|---|---|
| L'SMS con il codice non arriva | Riprova con **Phone call**; controlla che la SIM sia attiva e con segnale |
| "Numero già registrato su WhatsApp" | Sul telefono con quella SIM: WhatsApp → Impostazioni → Account → **Elimina account**, attendi qualche minuto e riprova |
| Il WABA non compare nella console AWS | Region sbagliata: deve essere **eu-west-1** |
| Messaggi inviati ma nessun `message stored` nel log | Destinazione eventi mancante o sul topic sbagliato: §1.3 |
| Foto registrate senza file su S3 | `waPhoneNumberId` ancora `UNSET`: valorizzarlo in config e fare il deploy di `channels` (§1.3) |
| Foto su S3 ma `media dropped: too large` nel log e messaggio senza `s3Uri` | Router precedente alla PR #31 (leggeva `fileSize` in KB, è in byte): deploy di `messaging` da `main` |
| Mittente `UNKNOWN` con il proprio numero | Numero non in `channel-identities` o in formato diverso da `WHATSAPP#+39…` (§1.4, punto 1) |
| L'agente risponde (log `reply sent`) ma sul telefono non arriva nulla | `notifierSandbox` = `true` (§1.4) |

## 2. Template WhatsApp

**Fonte unica**: i JSON in [`services/notifier/whatsapp_templates/`](../services/notifier/whatsapp_templates/) (`<nome>.<lingua>.json`, formato `template-definition` di Meta). Si usano sia per l'invio a Meta sia dal Notifier: i testi si cambiano solo lì. `tests/test_whatsapp_templates.py` verifica le regole di Meta (nomi, variabili `{{1}}…{{n}}` in ordine, corpo che non inizia né finisce con una variabile, esempi, lunghezze di header/footer/pulsanti, stessa forma IT/EN).

Servono **solo fuori dalla finestra di 24 ore** (F-11.C2): dentro la finestra il Notifier manda messaggi liberi o interattivi.

| Template | Categoria | Quando (flusso) | Variabili | Pulsanti (quick reply) |
|---|---|---|---|---|
| `order_confirmation` | UTILITY | Ordine confermato (F-07, FN-12/14), insieme all'email con PDF | 1 nome · 2 numero ordine · 3 data consegna · 4 n. righe · 5 limite per le modifiche (cut-off) | *Modifica ordine* |
| `order_pending_reminder` | UTILITY | Bozza non confermata dopo `pendingReminderHours` (FN-12) | 1 nome · 2 n. righe · 3 data consegna · 4 limite per confermare | *Vedi riepilogo* · *Annulla bozza* |
| `delivery_update` | UTILITY | Giorno di consegna (F-12, FN-18), se il contatto usa WhatsApp | 1 nome · 2 numero ordine · 3–4 fascia oraria | *Ricevuto* · *Segnala problema* |
| `reorder_suggestion` | MARKETING | Riordino proattivo (F-13, FN-19), solo con consenso | 1 nome · 2 prodotti abituali · 3 data ultimo ordine · 4 prossima consegna | *Riordina uguale* · *Modifica* · *No grazie* · *Stop proposte* |

Scelte di contenuto:
- Nessun pulsante conferma un ordine "alla cieca": *Vedi riepilogo* e *Riordina uguale* portano al riepilogo, la conferma esplicita arriva dopo (FN-12, AGENTS §8.1).
- Footer "Assistente virtuale ordini · messaggio automatico" su tutti: l'agente si dichiara assistente virtuale (AGENTS §8.8). Nessun nome del distributore né marchi di terzi (AGENTS §11).
- `reorder_suggestion` è MARKETING: *Stop proposte* revoca il consenso proattivo (FN-19, F-13). Meta può comunque riclassificare la categoria.
- Nessun prezzo, sconto o promessa commerciale nei testi.

### 2.1 Invio a Meta (una volta per WABA)

Prerequisito: WABA collegata (§1). Con l'ID della WABA (`aws socialmessaging list-linked-whatsapp-business-accounts`):

```bash
export AWS_PROFILE=default AWS_REGION=eu-west-1
for f in services/notifier/whatsapp_templates/*.json; do
  aws socialmessaging create-whatsapp-message-template --id <WABA_ID> --template-definition "fileb://$f"
done
aws socialmessaging list-whatsapp-message-templates --id <WABA_ID>   # stato: PENDING → APPROVED/REJECTED
```

In alternativa: console AWS End User Messaging Social → *Message templates* → *Create template*, copiando i testi dai JSON. Se Meta rifiuta un template, si corregge il JSON (il test deve restare verde) e lo si reinvia.

## 3. RCS e SMS (M-11, T-27)

Identità di AWS End User Messaging SMS v2: **agente RCS di test** con i telefoni tester e **sender ID SMS** per l'Italia.

### 3.1 Vincoli

- **Niente RCS su iPhone in Italia**: Apple abilita RCS solo con gli operatori che lo supportano e nessun operatore italiano lo fa ([pagina Apple](https://support.apple.com/en-us/108048)). Un iPhone, anche con iOS recente, risulta tester `UNSUPPORTED`. La demo RCS si fa da **Android** con Google Messaggi (*Impostazioni → Chat RCS* = "Connesso").
- **Agente di test**: invia solo ai tester (max 20 inviti al giorno), senza approvazione degli operatori. Il lancio verso tutti i numeri italiani richiede `IT_RCS_LAUNCH_REGISTRATION` con approvazione degli operatori (settimane): fuori dalla gara.
- **Sender ID alfanumerico** in Italia: nessuna registrazione, ma **one-way**. L'SMS di fallback è una notifica: niente "rispondi 1/2" ([02](./02_TECHNICAL_FLOWS.md) F-11.C4).
- **Fallback RCS → SMS automatico** solo inviando a un **pool** che contiene agente RCS e sender ID; con l'ARN dell'agente come origination identity non c'è fallback ([doc](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-sms-fallback.html)).
- **Sandbox SMS**: gli SMS arrivano solo a numeri verificati con OTP; l'uscita dalla sandbox è un caso di supporto (giorni).
- **Esiti di consegna**: visibili solo con un configuration set con event destination; senza, la sola metrica CloudWatch è `AWS/SMSVoice` `RCSMessagesSent`.

### 3.2 Procedura (riproducibile)

Riferimenti: [Testing RCS](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-testing.html), [walkthrough CLI di AWS](https://aws.amazon.com/blogs/messaging-and-targeting/creating-and-testing-an-end-user-messaging-rcs-agent-with-aws-cli/). Serve AWS CLI ≥ 2.35.12. Ogni risorsa riceve i tag `Project`, `Owner`, `Env` (AGENTS.md §7).

```bash
export AWS_PROFILE=default AWS_REGION=eu-west-1 AWS_PAGER=""
TAGS=("Key=Project,Value=Hackathon AWS CDS" "Key=Owner,Value=matteo.goretti@besharp.it" "Key=Env,Value=dev")
sms() { aws pinpoint-sms-voice-v2 "$@"; }

# 1. Agente RCS e registrazione di test
AGENT=$(sms create-rcs-agent --opt-out-list-name Default --tags "${TAGS[@]}" --query RcsAgentId --output text)
REG=$(sms create-registration --registration-type TEST_RCS_LAUNCH_REGISTRATION --tags "${TAGS[@]}" --query RegistrationId --output text)
sms create-registration-association --registration-id "$REG" --resource-id "$AGENT"
LOGO=$(sms create-registration-attachment --attachment-body fileb://logo.png --tags "${TAGS[@]}" --query RegistrationAttachmentId --output text)
BANNER=$(sms create-registration-attachment --attachment-body fileb://banner.png --tags "${TAGS[@]}" --query RegistrationAttachmentId --output text)
```

Asset: `logo.png` 224×224 (< 50 KB) e `banner.png` 1440×448 (< 200 KB), ricavati da `assets/brand/suppliagent_icon_1024.png` e `suppliagent_logo_dark.png` su sfondo `#1F2A44`. Campi della registrazione (`put-registration-field-value --field-path agentDetails.<campo>`, con `--text-value`, `--select-choices` o `--registration-attachment-id`):

| Campo | Valore |
|---|---|
| `brandName` / `senderDisplayName` | `SuppliAgent` |
| `serviceName` | `SuppliAgent HoReCa orders` |
| `agentDescription` | `Virtual assistant for HoReCa orders: order confirmations, delivery updates and reorders.` |
| `useCase` / `billingCategory` | `MULTI_USE` / `CONVERSATIONAL` |
| `logoImage` / `bannerImage` | `$LOGO` / `$BANNER` |
| `accentColor` | `#1F2A44` (contrasto ≥ 4.5:1 sul bianco) |
| `contactPhoneNumber` / `contactPhoneLabel` | numero WhatsApp di `dev` / `WhatsApp orders` |
| `contactEmailAddress` / `contactEmailLabel` | `ordini@<sesDomain>` / `Email orders` |
| `contactWebsite` / `contactWebsiteLabel` | `https://www.besharp.it` / `Website` |
| `privacyPolicyUrl` / `privacyPolicyLabel` | `https://www.besharp.it/privacy-policy/` / `Privacy policy` |
| `termsAndConditionsUrl` / `termsAndConditionsLabel` | `LICENSE` del repo su GitHub / `Terms` |
| `averageMonthlyRcsFrequency` / `monthlyRcsVolume` | `10` / `1000` |

```bash
# 2. Invio e attesa (registrazione COMPLETE e TestingAgent.Status ACTIVE in pochi minuti)
sms submit-registration-version --registration-id "$REG"
sms describe-rcs-agents --rcs-agent-ids "$AGENT" --query 'RcsAgents[0].TestingAgent.Status' --output text

# 3. Tester (almeno 120 s dopo la creazione dell'agente): invito "Make me a tester" da "RBM Tester Management"
sms create-verified-destination-number --destination-phone-number +39<android> --rcs-agent-id "$AGENT" --tags "${TAGS[@]}"
sms describe-verified-destination-numbers --filters "Name=rcs-agent-id,Values=$AGENT" --query 'VerifiedDestinationNumbers[].Status'   # VERIFIED

# 4. Messaggio di prova (arriva in una chat "SuppliAgent" separata dall'invito)
AGENT_ARN=$(sms describe-rcs-agents --rcs-agent-ids "$AGENT" --query 'RcsAgents[0].RcsAgentArn' --output text)
sms send-text-message --destination-phone-number +39<android> --origination-identity "$AGENT_ARN" --message-type TRANSACTIONAL --message-body "SuppliAgent: RCS test"

# 5. Sender ID SMS per l'Italia
sms request-sender-id --sender-id SuppliAgent --iso-country-code IT --message-types TRANSACTIONAL --tags "${TAGS[@]}"
```

Se il tester non riceve il messaggio subito dopo l'accettazione, attendere qualche minuto e reinviare: il primo invio, pochi secondi dopo il `VERIFIED`, non è arrivato; il secondo, 10 minuti dopo, sì. Se la registrazione va in `REQUIRES_UPDATES`, `describe-registration-field-values` mostra i campi con `DeniedReason`; una nuova versione (`create-registration-version`) non eredita i valori.

### 3.3 Cablaggio (T-27)

- `rcsAgentId` e `smsSenderId` (`SUPPLIAGENT/IT`) in `infra/config/environments.ts`; il `ChannelsStack` pubblica `rcsAgentArn`, `smsSenderId` (ARN) e `smsConfigurationSet` in SSM.
- Topic `suppliagent-<env>-sms-inbound` sottoscritto alla coda `inbound`; il two-way dell'agente (`UpdateRcsAgent`, `TwoWayEnabled`, `TwoWayChannelArn`) lo attiva una custom resource del `ChannelsStack` (lo spegne alla cancellazione; se cambia `rcsAgentId`, il two-way del vecchio agente va spento a mano con `update-rcs-agent --no-two-way-enabled`). Serve `sms-voice.amazonaws.com` nella key policy della CMK (`FoundationStack`).
- Configuration set `suppliagent-<env>-sms-cs` con tutti gli eventi su `suppliagent-<env>-sms-events`.
- Niente pool: il fallback è per messaggio (`SendRcsMessage` con `FallbackConfiguration` SMS dal sender ID).
- **Passo manuale per la demo**: il telefono Android del tester riceve RCS solo se il suo contatto ha un'identità `SMS#` verificata (mai il numero WhatsApp: l'agente di test invia solo ai tester e gli SMS in sandbox solo ai numeri verificati). Il numero non va nel repo:

```bash
aws dynamodb put-item --table-name suppliagent-dev-channel-identities --item '{
  "channelAddress": {"S": "SMS#+39<android>"}, "channel": {"S": "SMS"},
  "contactId": {"S": "con_<tester>"}, "role": {"S": "CUSTOMER_CONTACT"}, "verified": {"BOOL": true}}'
```
