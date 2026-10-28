# Agente RCS e mittente SMS (M-11)

Procedura manuale (non automatizzabile in CDK) per le identità di AWS End User Messaging SMS v2 usate da T-27: **agente RCS di test** con i telefoni tester e **sender ID SMS** per l'Italia. Account `471112860008`, region `eu-west-1`, profilo `default`.

## Stato (`dev`, 28/10/2026)

| Risorsa | Valore | Stato |
|---|---|---|
| Agente RCS | `rcs-83650561df2543e1942ccb9a500fa736` (`arn:aws:sms-voice:eu-west-1:471112860008:rcs-agent/rcs-83650561df2543e1942ccb9a500fa736`) | `TESTING`, testing agent `ACTIVE` (`suppliagent_wm1yg2rx_agent`) |
| Registrazione di test | `registration-a8d414f7801a465d90b9fe3cc34a28b2` (`TEST_RCS_LAUNCH_REGISTRATION`) | `COMPLETE` (approvata in ~3 min) |
| Tester RCS | 1 telefono Android con Google Messaggi | `VERIFIED`, messaggio di prova **ricevuto** (28/10 11:36) |
| Sender ID SMS | `SUPPLIAGENT` per IT, `TRANSACTIONAL` (`arn:aws:sms-voice:eu-west-1:471112860008:sender-id/SUPPLIAGENT/IT`) | attivo, **solo one-way** |
| Account SMS | `SANDBOX`, spend limit SMS e RCS 1 $/mese | sufficiente per la demo |
| Two-way RCS | non attivo | da collegare al topic `sms-inbound` in T-27 |

I numeri dei tester non si scrivono nel repo né nelle issue.

## Vincoli emersi

- **Niente RCS su iPhone in Italia**: Apple abilita RCS solo con gli operatori che lo supportano e nessun operatore italiano lo fa ([pagina Apple](https://support.apple.com/en-us/108048)). Un iPhone, anche con iOS recente, risulta tester `UNSUPPORTED`. La demo RCS si fa da **Android** con Google Messaggi (*Impostazioni → Chat RCS* = "Connesso").
- **Agente di test**: invia solo ai tester (max 20 inviti al giorno), senza approvazione degli operatori. Il lancio verso tutti i numeri italiani richiede `IT_RCS_LAUNCH_REGISTRATION` con approvazione degli operatori (settimane): fuori dalla gara.
- **Sender ID alfanumerico** in Italia: nessuna registrazione, ma **one-way**. L'SMS di fallback è una notifica: niente "rispondi 1/2" (02 F-11.C4).
- **Fallback RCS → SMS automatico** solo inviando a un **pool** che contiene agente RCS e sender ID; con l'ARN dell'agente come origination identity non c'è fallback ([doc](https://docs.aws.amazon.com/sms-voice/latest/userguide/rcs-sms-fallback.html)).
- **Sandbox SMS**: gli SMS arrivano solo a numeri verificati con OTP; l'uscita dalla sandbox è un caso di supporto (giorni).
- **Esiti di consegna**: visibili solo con un configuration set con event destination; senza, la sola metrica CloudWatch è `AWS/SMSVoice` `RCSMessagesSent`.

## Procedura (riproducibile)

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

## Da fare in T-27

- Topic SNS `sms-inbound` (CDK) e `update-rcs-agent --rcs-agent-id <id> --two-way-enabled --two-way-channel-arn <topic>` per ricevere *Ricevuto / Segnala problema*.
- Pool con agente RCS e sender ID per il fallback; configuration set con event destination per gli esiti.
- Parametri `rcsAgentId` / `smsOriginationIdentity` (INFRASTRUCTURE_DESIGN §11) con i valori della tabella sopra.
