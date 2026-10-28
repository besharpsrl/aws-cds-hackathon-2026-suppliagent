# Iscrizione WhatsApp Business (WABA) e collegamento ad AWS End User Messaging Social

> Procedura operativa per collegare un numero WhatsApp a SuppliAgent in `dev` (account `471112860008`, region **eu-west-1**).
> La parte 1 si fa a mano nel browser; le parti 2–4 le esegue un agente di sviluppo su richiesta.
>
> **Stato al 27/10 (`dev`)**: parti 1–3 completate. WABA `waba-8c2d297ba5154c33b7d0ceac98c7410a` (Meta `2035382963843064`), numero **+39 345 246 0472** (`phone-number-id-79f96a1ea97d47aabfce52eb7b8cf23c`), eventi su `suppliagent-dev-wa-events`; testo e foto reali ricevuti, riconosciuti e passati all'agente. Azioni e task ancora aperti (tag sul numero, approvazione template, invio reale): `START_HERE.md` §4–§5.
>
> Riferimenti: [AWS – Getting started](https://docs.aws.amazon.com/social-messaging/latest/userguide/getting-started-whatsapp.html) · [Meta – numeri di telefono](https://developers.facebook.com/docs/whatsapp/cloud-api/phone-numbers) · [README – Manual steps](../README.md#getting-started).

---

## 0. Prima di iniziare (checklist)

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

---

## 1. Collegamento del numero (console AWS + portale Meta)

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
   - **Two-step verification PIN**: il PIN a 6 cifre del punto 0;
   - **Data localization region**: lasciare vuoto;
   - **Tags**: `Project` = `Hackathon AWS CDS`, `Owner` = `matteo.goretti@besharp.it`, `Env` = `dev` (obbligatori su tutte le risorse dell'account);
   - **Message and event publishing**: attivo, destinazione **Amazon SNS**, topic **`suppliagent-dev-wa-events`** (ARN: `aws ssm get-parameter --name /suppliagent/dev/waEventsTopicArn --query Parameter.Value --output text --region eu-west-1`). Senza questo non arrivano i messaggi in ingresso. Se il campo dà errore, saltalo: lo imposta Claude Code (parte 2).
8. **Add phone number**. Lo stato del numero diventa attivo in pochi minuti; il display name resta *in review* finché Meta non lo approva (non blocca i test).

Annota (non sono segreti): **WABA ID** (`waba-…`) e **phone number ID** (`phone-number-id-…`), visibili nella pagina del business account. Claude Code li recupera comunque da CLI.

---

## 2. Configurazione lato AWS (Claude Code)

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

Il **Router**, il Dispatcher e il Notifier sono invece nello stack **`messaging`**: una correzione al codice del Router si porta su AWS con `npx cdk deploy suppliagent-dev-messaging --exclusively -c env=dev --profile default`. Dopo il deploy controllare che `CodeSize` della Lambda non sia di poche centinaia di byte (zip vuoto, vedi `START_HERE.md` §1.4).

---

## 3. Prova di ricezione

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

---

## 4. Dopo il collegamento

- **Template WhatsApp (T-29)**: ✅ gli 8 template (4 × IT/EN) sono stati inviati a Meta il 27/10 con il comando di [09 §1](./09_CONTENT_AND_TEMPLATES.md) (WABA `waba-8c2d297ba5154c33b7d0ceac98c7410a`), tutti `PENDING`; ancora `PENDING` alla verifica del 28/10 ore 12:00 (dettagli e cause probabili in [09 §1](./09_CONTENT_AND_TEMPLATES.md)). Verifica e reinvio dei rifiutati sono il task T-29 (`START_HERE.md` §4). Servono per scrivere fuori dalla finestra di 24 h (conferme, promemoria, riordino).
- **Pagina demo della console**: `AWS_PROFILE=default VITE_DEMO_WHATSAPP="+393452460472" VITE_DEMO_ORDER_EMAIL="ordini@suppliagent.stonecutters.besharp.net" scripts/deploy-console.sh dev` (i valori sono anche in `console/.env.example`; lo script li legge dalle variabili d'ambiente, non dai file `.env`).
- **README per i giudici**: ✅ numero WhatsApp ed email d'ordine inseriti in "Try it (for judges)" il 27/10; URL console, credenziali `judge` e cliente di prova sono nel task T-10 (`START_HERE.md` §4).
- **Ambiente dei giudici**: è `dev` (unico ambiente, decisione del 27/10), con lo stesso WABA e lo stesso numero.

---

## 5. Limiti e costi da sapere

- **Senza Business Verification** del portfolio: messaggi avviati dall'azienda (template) a max **250 destinatari unici ogni 24 h**; max **2 numeri** per portfolio; display name poco visibile nelle chat. Le risposte entro 24 h dal messaggio del cliente non hanno questo limite: per la demo basta.
- **Display name rifiutato**: il limite di invio si abbassa e il numero può essere scollegato; correggerlo dalla pagina del numero e rinviarlo in revisione.
- **Costi**: AWS 0,005 $ per messaggio in uscita, 0,001 $ in ingresso; Meta per messaggio consegnato, con i **primi 1.000 messaggi di servizio al mese per numero gratuiti**. Per la demo: pochi centesimi.
- Il numero di test gratuito di Meta **non** si collega ad AWS End User Messaging Social: serve un numero reale.

---

## 6. Problemi comuni

| Sintomo | Cosa fare |
|---|---|
| L'SMS con il codice non arriva | Riprova con **Phone call**; controlla che la SIM sia attiva e con segnale |
| "Numero già registrato su WhatsApp" | Sul telefono con quella SIM: WhatsApp → Impostazioni → Account → **Elimina account**, attendi qualche minuto e riprova |
| Il WABA non compare nella console AWS | Region sbagliata: deve essere **eu-west-1** |
| Messaggi inviati ma nessun `message stored` nel log | Destinazione eventi mancante o sul topic sbagliato: parte 2 |
| Foto registrate senza file su S3 | `waPhoneNumberId` ancora `UNSET`: valorizzarlo in config e fare il deploy di `channels` (parte 2) |
| Foto su S3 ma `media dropped: too large` nel log e messaggio senza `s3Uri` | Router precedente alla PR #31 (leggeva `fileSize` in KB, è in byte): deploy di `messaging` da `main` |
| Mittente `UNKNOWN` con il proprio numero | Numero non in `channel-identities` o in formato diverso da `WHATSAPP#+39…` (parte 3, punto 1) |
| L'agente risponde (log `reply sent`) ma sul telefono non arriva nulla | `notifierSandbox` = `true` (parte 3) |
