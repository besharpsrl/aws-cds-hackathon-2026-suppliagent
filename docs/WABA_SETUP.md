# Iscrizione WhatsApp Business (WABA) e collegamento ad AWS End User Messaging Social

> Procedura operativa per collegare un numero WhatsApp a SuppliAgent in `dev` (account `471112860008`, region **eu-west-1**).
> La parte 1 si fa a mano nel browser; le parti 2–4 le esegue Claude Code su richiesta. Riferimenti: [AWS – Getting started](https://docs.aws.amazon.com/social-messaging/latest/userguide/getting-started-whatsapp.html) · [Meta – numeri di telefono](https://developers.facebook.com/docs/whatsapp/cloud-api/phone-numbers) · [README – Manual steps](../README.md#getting-started).

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

Registrare l'ID del numero nel parametro SSM `waPhoneNumberId` (letto a runtime dal router per scaricare i media), scrivendolo in `infra/config/environments.ts` (`waPhoneNumberId` dell'ambiente) e facendo un deploy di `channels` (mutante, solo dopo conferma). Il dominio SES resta quello della config, senza `-c`:

```bash
cd infra && rm -rf cdk.out
npx cdk deploy suppliagent-dev-channels --exclusively -c env=dev \
  --profile default
aws ssm get-parameter --name /suppliagent/dev/waPhoneNumberId --query Parameter.Value --output text
```

---

## 3. Prova di ricezione

1. Dal tuo telefono personale scrivi `ciao` al nuovo numero.
2. Verifiche (sola lettura):
   - log del router: `aws logs tail /aws/lambda/suppliagent-dev-inbound-router --since 10m` → `message stored`;
   - un item nuovo in `suppliagent-dev-messages` (il mittente sconosciuto risulta `UNKNOWN` finché non si identifica, o lo si registra nel seed);
   - DLQ `suppliagent-dev-inbound-dlq` vuota.
3. Invia una **foto** (es. un bigliettino): l'oggetto deve comparire nel bucket media sotto `media/<contactId|conversationId>/<messageId>/`.

La **risposta** dell'agente su WhatsApp arriva solo quando T-22 + T-24 (Dispatcher e Notifier) sono su `main` e deployati.

Per farti riconoscere come cliente di prova: aggiungi il tuo numero personale in `seed/private/` (escluso da git) come `ChannelIdentity` di un contatto del seed, poi `uv run python seed/seed.py --env dev`.

---

## 4. Dopo il collegamento

- **Template WhatsApp (T-29)**: invio degli 8 template a Meta con il comando di [09 §1](./09_CONTENT_AND_TEMPLATES.md) usando il `<WABA_ID>`; approvazione entro 24 h. Servono per scrivere fuori dalla finestra di 24 h (conferme, promemoria, riordino).
- **Pagina demo della console**: `AWS_PROFILE=default VITE_DEMO_WHATSAPP="+39…" VITE_DEMO_ORDER_EMAIL="ordini@<sesDomain>" scripts/deploy-console.sh dev`.
- **README per i giudici**: numero WhatsApp nelle istruzioni di test (T-10).
- **Ambiente `demo`** (T-10): stesso account, quindi stesso WABA e stesso numero. Da decidere al deploy di `demo` se spostare la destinazione eventi sul topic `suppliagent-demo-wa-events` (da quel momento `dev` non riceve più) o tenere un solo ambiente collegato.

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
