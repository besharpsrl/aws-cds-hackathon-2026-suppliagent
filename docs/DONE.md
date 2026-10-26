# SuppliAgent – Registro del lavoro completato

> Qui finisce tutto ciò che è **chiuso**: task del backlog, documenti scritti, punti aperti risolti.
> Regola: quando una voce è completata la si **rimuove** dal documento "da fare" (`04_BACKLOG.md`, `TODO_DOCS.md`, punti aperti di `INFRASTRUCTURE_DESIGN.md` §12, ecc.) e la si aggiunge qui, in cima, con data, riferimenti e come verificarla.
> Un ID `T-xx` citato come dipendenza nel backlog ma assente dalle sue tabelle è completato: lo trovi qui.

---

## 26/10/2026

### Email SES su `dev`: dominio, DNS, ricezione · FN-01, FN-06
- **Cosa**: `cdk deploy suppliagent-dev-channels --exclusively -c env=dev -c sesDomain=suppliagent.stonecutters.besharp.net` (identity SES, rule set di ricezione attivato, parametri SSM `sesDomain` e `sesFromAddress` = `ordine@…`). Nella zona Route 53 condivisa `stonecutters.besharp.net` aggiunti **solo** 5 record con `CREATE` (mai sovrascritture; da 20 a 25 record): 3 CNAME DKIM, `MX 10 inbound-smtp.eu-west-1.amazonaws.com` e `_dmarc` TXT `p=none` su `suppliagent.stonecutters.besharp.net`.
- **Verifica**: DKIM `SUCCESS`, identity verificata; mail di prova da `test@` a `ordini@` del dominio (ammessa in sandbox) → oggetto in `inbound-mail/mail/…`, router `message stored` canale `EMAIL`.
- **Uscita dalla sandbox SES** richiesta il 26/10 (`put-account-details`, transazionale, contatto `matteo.goretti@besharp.it`): stato `PENDING`; vale per tutto l'account in `eu-west-1`.
- **Da ricordare**: ogni deploy che tocca `channels` deve ripassare `-c sesDomain=suppliagent.stonecutters.besharp.net` finché T-15 non porta il valore nella config.

### Deploy `dev` allineato a `main` (`a9225ec`: PR #13, #15, #16) · FN-32
- **Cosa**: da `origin/main`, profilo `default` (account `471112860008`, `eu-west-1`): `cdk deploy suppliagent-dev-messaging` con le dipendenze (Foundation e Data solo nuovi export; **primo deploy di `channels`** (T-20): topic `wa-events`/`mail-inbound`/`email-events`, configuration set SES, parametri SSM `UNSET`; `agent`: codice di `tool-customers`; `messaging`: coda inbound + DLQ, allarme, `inbound-router`); `suppliagent-dev-console` (codice di `console_api`); SPA pubblicata con `scripts/deploy-console.sh dev` (senza `VITE_DEMO_*`).
- **Verifica**: evento WhatsApp sintetico su `wa-events` → item in `Messages` (`conv_con001`, `CUSTOMER_CONTACT`), ripubblicazione → `duplicate delivery ignored`, DLQ vuota; `invoke_agent.py` risponde; console e `/demo` 200.
- **Utenti console** creati (invito email di Cognito con password temporanea): un utente per gruppo `backoffice`, `sales_rep`, `judge` sugli alias `+backoffice`, `+salesrep`, `+judge` dell'email dell'owner.
- **Restano**: WABA e `waPhoneNumberId`, dominio SES (`sesDomain`, DNS, uscita dalla sandbox), contatti della pagina demo (README §Manual steps).

### T-66 – Ruolo `judge` in sola lettura e rifiniture demo · FN-28, FN-31
- **Cosa**: (1) `console_api` rifiuta con 403 `read_only` ogni metodo non-GET del `judge` **prima** del routing, così nessun endpoint di scrittura futuro (correzioni, T-46) può dimenticare il controllo; i gruppi sono additivi (un utente `judge`+`backoffice` non è bloccato). (2) Nel dettaglio ordine un avviso spiega al `judge` perché le correzioni sono disabilitate. (3) Pagina **Try the demo** (`/demo`, link nel menu) per i giudici: bigliettino di esempio scaricabile, passi per ordinare, numero WhatsApp ed email da `VITE_DEMO_WHATSAPP` / `VITE_DEMO_ORDER_EMAIL` (altrimenti "to be announced"). (4) Pagina "Page not found" con link di ritorno. (5) README: sezione giudici con il ruolo `judge` e la pagina demo.
- **Test**: `services/console_api/tests` (+6: scrittura negata al `judge` su ogni metodo ed endpoint, gruppi additivi, 405 per gli altri ruoli), `console/src` (+9: avviso read-only, pagina demo con e senza canali configurati, 404, menu); `npm run check` verde.
- **Commit**: `2a1aa9f` (branch `feat/FN-31-judge-demo-polish`). Per applicare il controllo dell'API serve rilanciare `cdk deploy suppliagent-dev-console --exclusively -c env=dev` (cambia il codice della Lambda); la SPA con `scripts/deploy-console.sh dev`.
- **Resta per FN-31** (altri stream/azioni manuali): numero WhatsApp, email ordini, credenziali `judge` e URL nel README, script di reset dei dati demo, ambiente `demo` attivo fino al 12/11.

### Revisione T-21 + T-23 (code-reviewer, security-reviewer) · FN-01, FN-03, FN-05, FN-06
- **Corretto**:
  - **Receipt rule SES senza `kmsKeyArn`** (`ChannelsStack`): con quel parametro SES cifra lato client (S3 encryption client) e il Router avrebbe letto testo cifrato; ora vale la SSE-KMS di default del bucket con la CMK (Foundation concede già la chiave a `ses`). Richiede il deploy di `channels` (solo con `-c sesDomain`). **Da verificare** su una mail reale: `head-object` senza metadati `x-amz-key-v2`.
  - Identità: contatto `PENDING_VERIFICATION` senza `customerIds`, altri stati → `UNKNOWN` (come `caller_scope`); indirizzo identificato con `identify_contact` resta nella conversazione in cui è stato identificato (`ChannelIdentities.conversationId`, scritto ora dal tool `customers`).
  - Email: `From` singolo e uguale a quello valutato da SES, `senderVerified` nel `NormalizedMessage`, conversazione separata per le email non verificate (mai in quella del titolare dell'indirizzo), `orderId` solo da `ordine+<id>@<sesDomain>` (`ORDER_DOMAIN`) e mittente verificato, testo troncato a 4000 caratteri, HTML senza script/stili/commenti e con entità decodificate, chiave S3 della mail verificata (`mail/<messageId>`).
  - Idempotenza (E-01): transazione messaggio + guardia `dedup#<messageId>` con TTL 7 giorni nel TurnBuffer, quindi anche se l'evento torna con un altro timestamp.
  - Allegati (E-13): salvati solo con virus scan SES `PASS`, firma dei primi byte coerente col tipo, niente `.xls` né audio via email, max 10 per mail, estensione dal tipo e mai dal nome file, documenti con `Content-Disposition: attachment`; un allegato rifiutato resta nel messaggio **senza `s3Uri`**. Media WhatsApp oltre 10 MB non passati all'agente.
  - `interactiveReply.contextId` (wamid del messaggio col pulsante) per la verifica in `confirm_order` (riga T-46).
  - CDK: `maxConcurrency` 10 sul Router, allarme `suppliagent-<env>-inbound-dlq` (E-10; notifica con T-09).
  - Documenti: diagramma di 02 §3, contratto `NormalizedMessage` (INFRASTRUCTURE_DESIGN §5.2), E-01/E-13; seguiti nel backlog (T-24 reinvio/avviso/no risposta a email non verificate, T-26 F-02.C3, T-41 contenuto non fidato, T-46 `contextId`, T-09 notifica allarme, T-11 diagramma).
- **Non fatto (rischi accettati dall'utente il 26/10, elencati in INFRASTRUCTURE_DESIGN §12)**: `conversationId` degli sconosciuti = SHA-256 troncato dell'indirizzo, invertibile per forza bruta sui numeri (finisce nei log come correlation id); la correzione è un HMAC con segreto (Secrets Manager, ~0,40 $/mese, costo fisso: AGENTS §11). Parser scelto dal contenuto e non dal `TopicArn`; topic SNS pubblicabili da qualunque regola SES/WABA dell'account; `kms:ViaService` sulle grant KMS; ARN del numero WhatsApp ristretto. Testo nascosto via CSS (`display:none`) non rimosso.
- **Test**: 119 pytest (nuovi: email con due `From` o `From` diverso da SES, `orderId` da dominio estraneo o mittente non verificato, HTML nascosto, troncamento, virus `GRAY`/`PROCESSING_FAILED`, firma falsa, `.xls`, 12 allegati, media WhatsApp troppo grande, chiave S3 della mail diversa, duplicato con nuovo timestamp, contatto pending, email non verificata separata, `contextId`); `infra/test` (receipt rule senza `KmsKeyArn`, concorrenza, allarme); `npm run check` verde.
- **Commit**: branch `feat/FN-01-inbound-pipeline` (commit di fix dopo `6abc34a`).

### T-23 – Media WhatsApp e allegati email su S3 · FN-05, FN-06
- **Cosa**: modulo `inbound_router/media.py`, chiamato dal Router prima di qualsiasi scrittura. WhatsApp: `socialmessaging.get_whatsapp_message_media` con `destinationS3File` (prefisso `media/<contactId|conversationId>/<messageId>/`, il servizio aggiunge `<mediaId>.<ext>`; chiave reale ritrovata con `ListObjectsV2`), ID del numero letto da SSM `/suppliagent/<env>/waPhoneNumberId` a ogni media (finché vale `UNSET` il media resta senza `s3Uri` e il messaggio passa). Email: allegati MIME caricati come `<indice><estensione>` (il nome file non entra mai nella chiave). `attachments[].s3Uri` valorizzato nel `NormalizedMessage`. CDK: `s3:PutObject` su `media/*`, `s3:ListBucket` con `s3:prefix = media/*`, `ssm:GetParameter` sul parametro, `social-messaging:GetWhatsAppMessageMedia` su `phone-number-id/*` dell'account.
- **Scelte**:
  - **Dentro il Router, niente Lambda `media_fetcher`** (deciso il 26/10 con l'utente): il messaggio entra nel TurnBuffer (T-22) solo con i media già su S3, senza coordinamento asincrono col debounce. Aggiornati INFRASTRUCTURE_DESIGN §4/§5.1/§5.2, 02 §3.4 ed E-02, AGENTS §5, steering Kiro, `services/README.md`. `docs/architecture.drawio` mostra ancora la Lambda Media Fetcher (T-11).
  - Ammessi: immagini JPEG/PNG/WebP/GIF/HEIC (niente SVG: la console mostra le immagini inline), audio (solo WhatsApp), PDF, XLSX, CSV; max 10 MB; video e sticker non scaricati (02 §3.4). Regole complete dopo la revisione: voce sopra.
  - Download fallito → eccezione, nessuna scrittura, riconsegna SQS ×3 e DLQ (E-02). La richiesta di reinvio al cliente arriva con il Notifier (T-24).
  - Permessi S3/KMS del download: EUM Social usa le *forward access sessions* (scrive con i permessi del ruolo della Lambda). Dedotto dalla documentazione, **da verificare al primo media reale in `dev`**.
- **Limiti**: il cliente non viene ancora avvisato degli allegati rifiutati (serve il Notifier); boto3 del runtime Lambda deve includere `socialmessaging` (≥ 1.35.38): da verificare al primo deploy.
- **Test**: `services/inbound_router/tests/test_media.py` (foto e vocale WhatsApp con ID da SSM e chiave sotto il contatto, sticker/video/documento non ammesso/SVG non scaricati, numero non configurato, download fallito senza scritture, media di uno sconosciuto sotto la sua conversazione, allegati email ammessi/scartati/oltre limite, nome file con `../` confinato nel prefisso, mail infetta); `infra/test/messaging-stack.test.ts` (permessi media e parametro SSM); `npm run check` verde.
- **Commit**: `6abc34a` (branch `feat/FN-01-inbound-pipeline`).

### T-21 – `MessagingStack` + Inbound Router · FN-01, FN-03, FN-26
- **Cosa**: `services/inbound_router` (`inbound_router`): SNS envelope da SQS → normalizzazione **WhatsApp** (testo, immagine/audio/documento/video/sticker, risposte a pulsanti e liste, quick reply dei template; stati e reaction ignorati) ed **email** (mail letta dal bucket `inbound-mail`, solo prefisso `mail/` del bucket atteso; oggetto + corpo senza parte citata; `ordine+<ord_id>@` → `orderId`) → identità e ruolo da `ChannelIdentities` (F-02.C1/C2/C4/C5, fail-closed) → conversazione (una per contatto su tutti i canali, `conv_<contactId>`; sconosciuti: una per indirizzo; `mode` e `identifyAttempts` mai toccati) → `Messages` (`PutItem` condizionata, sort key `receivedAt#messageId`), evento `conversation.started`. `NormalizedMessage` in `suppliagent_shared.messages`. CDK: coda `suppliagent-<env>-inbound` (SSE-KMS con la CMK, DLQ dopo 3 ricezioni) sottoscritta a `wa-events` e `mail-inbound`, Lambda `inbound-router` (batch 1, timeout 60 s), IAM con statement espliciti (GetItem su identità/contatti/agenti, Query su `Customers/by-repId`, UpdateItem `Conversations`, PutItem `Messages`, PutEvents, GetObject `inbound-mail/mail/*`).
- **Scelte**:
  - **SQS standard invece di FIFO** (deciso il 26/10 con l'utente): SES e EUM Social pubblicano solo su topic SNS standard, che non consegnano a code FIFO. Ordine per chat dal timestamp di ricezione AWS (+1 ms tra i messaggi dello stesso evento), idempotenza su `providerMessageId`, serializzazione dei turni col lock del Dispatcher (T-22). Aggiornati AGENTS §4/§8.6, INFRASTRUCTURE_DESIGN §1/§5.2, 02 §3 ed E-01, README, steering Kiro, ADR-002. `docs/architecture.drawio` riporta ancora `inbound.fifo`: da aggiornare con l'export PNG (T-11).
  - **Email**: identità solo con `dmarcVerdict = PASS` (unico verdetto che verifica l'allineamento con il `From`), altrimenti `UNKNOWN` – requisito di §5.3.2. Un contatto con un dominio senza DMARC viene trattato come sconosciuto.
  - **Packaging Lambda**: allineato a `main` nel merge con T-40/T-41: `uvBundling` (`infra/lib/constructs/uv-bundling.ts`, dipendenze dal `uv.lock` con hash) con `suppliagent_shared` + `inbound_router`; escluso solo Powertools (layer), **boto3 incluso** perché quello del runtime Lambda può non avere `socialmessaging`.
  - Chiave KMS importata per ARN nel `MessagingStack`, così la sottoscrizione SNS non aggiunge statement alla key policy di Foundation (ciclo Foundation → Channels); Foundation concede già la CMK a SNS.
- **Rimandati** (righe aggiornate nel backlog): read receipt (T-24, unico punto di invio), check handoff e append al TurnBuffer (T-22), SMS/RCS (T-27), chat web (T-64).
- **Test**: `services/inbound_router/tests` (normalizzazione, identità per ruolo, locali solo propri, sconosciuto senza accesso, **email con `From` falsificato → `UNKNOWN`**, duplicati, raffica, stato conversazione preservato, bucket estraneo rifiutato, evento non riconosciuto → DLQ); `infra/test/messaging-stack.test.ts` (coda e DLQ, sottoscrizioni con envelope, batch 1, IAM senza wildcard e senza scritture su identità, key policy di Foundation intatta); `npm run check` verde.
- **Commit**: `e8604d5` (branch `feat/FN-01-inbound-pipeline`).

### T-40 + T-41 (versione ridotta) – AgentCore Gateway + Runtime, agente Strands per ruolo · FN-03, FN-04, FN-27, FN-32
- **T-40** (`infra/lib/stacks/agent-stack.ts`): Lambda `tool-customers` (permessi DynamoDB solo sulle chiamate fatte, niente `index/*`); **AgentCore Gateway** MCP con autenticazione in ingresso **AWS IAM** (solo il ruolo del Runtime ha `InvokeGateway`), CMK del progetto, niente ricerca semantica, target `customers` con schemi in `tool-schemas.ts`; **AgentCore Runtime** da zip (code deploy, Python 3.12 ARM64, niente ECR), dipendenze dal `uv.lock` con hash verificati (`infra/lib/constructs/uv-bundling.ts`, serve `uv` al synth, anche in CI); Bedrock limitato al profilo `eu.amazon.nova-pro-v1:0` e ai suoi modelli EU (modello in `config/environments.ts`); ARN su SSM `/suppliagent/<env>/agentRuntimeArn`; Gateway e Runtime creati dopo le policy dei loro ruoli.
- **T-41** (`agent/`): entrypoint AgentCore (`main.py`, `app.py`), contratto di turno 02 §6.2 (pydantic, `INVALID_REQUEST` senza chiamare modello o Gateway); `caller` (`role`, `contactId`, `channelAddress`, `conversationId`) tolto dagli schemi visti dal modello e **sempre sovrascritto dal codice** in un hook `BeforeToolCall`, senza finire nello storico; tool per ruolo con nomi completi `<target>___<tool>`; prompt `shared`/`customer`/`sales_rep` (assistente virtuale, niente prezzi o dati fuori dai tool, risultati dei tool come dati); lingua da `locale`; firma SigV4 delle chiamate MCP; storico nella sessione del Runtime, legato a `conversationId` + `channelAddress` e non toccato da un turno fallito. `scripts/invoke_agent.py` fa da Dispatcher finché T-22 non è su `main`.
- **Rinviato a T-54** (nuovo nel backlog): AgentCore Memory, Guardrail, prompt e tool `sales_rep` completi, Observability/OTel, retention e CMK del log group del Runtime. Altri target del Gateway con i rispettivi tool (T-43…T-47).
- **Revisioni** (subagent `code-reviewer`, `security-reviewer`): corretti storico corrotto su errore, `caller` nello storico, storico condiviso tra mittenti, allowlist per nome breve, bundling senza hash, log DEBUG di Strands; documentati il contratto di errore per il Dispatcher (02 §6.2) e il limite di fiducia a livello di account (INFRASTRUCTURE_DESIGN §5.3.2, da chiudere con T-22).
- **Test**: `agent/tests` (entrypoint, `caller` falsificato dal modello sempre sovrascritto e assente dallo storico, `caller` senza campi nulli, tool per ruolo, storico per conversazione e mittente, turno fallito, `<thinking>` mai inviato, prompt per ruolo/lingua, contratto, firma SigV4); `infra/test/agent-stack.test.ts` (Gateway IAM, Runtime zip, IAM Bedrock/DynamoDB/InvokeGateway, config, SSM, ordine di creazione); `npm run check` verde.
- **Deploy e verifica end-to-end su `dev`** (26/10, `scripts/invoke_agent.py`): contatto con due locali (IT) → elenco locali e giorni di consegna; contatto EN → ultimo ordine in inglese; agente di commercio → riepilogo e insight di un cliente in portafoglio, rifiuto per un cliente fuori portafoglio; mittente sconosciuto → richiesta di codice e nome, `NOT_FOUND` con codice errato, `MATCHED` con codice giusto e spiegazione della bozza. Emersi e corretti in e2e: il Gateway valida l'input contro lo schema (`contactId: null` rifiutato → `caller` senza campi nulli); Nova Pro scrive blocchi `<thinking>` nel testo (rimossi dalla risposta). Il precedente deploy fallito (KMS del Gateway prima della policy) è risolto dall'ordine di creazione.
- **Nota synth**: se `cdk.out` contiene asset di synth precedenti, la validazione di cdk-nag può fallire con `IllegalPluginOperation`; si risolve cancellando `infra/cdk.out` (output generato).
- **Commit**: un commit per task sulla PR `feat/FN-03-agent-runtime` (`feat(agent): … (T-40, FN-32)`, `feat(agent): … (T-41, FN-03)`).

### Console online su `dev` · FN-28
- **Cosa**: `scripts/deploy-console.sh [dev|demo]` (build con gli id letti dagli output di `suppliagent-<env>-console`, sync del bucket sito con cache lunga sugli asset e `no-cache` su `index.html`, invalidazione CloudFront). Eseguito su `dev` (account `471112860008`, `eu-west-1`): console su `https://d3po2gqnlfcxyr.cloudfront.net`, ordini su dati mock (`VITE_ORDERS_SOURCE=mock`).
- **Verifica**: home 200, fallback SPA su `/orders/...` 200, CORS dell'API ok dall'origin CloudFront.
- **Da rifare** per `demo` (deploy manuale, AGENTS §11) e quando T-46 è su `main`, con `VITE_ORDERS_SOURCE=api`.

### T-42 – Tool `customers`: `identify_contact`, `get_customer_profile` · FN-03, FN-32
- **Cosa**: package `services/tools/customers` (`suppliagent_tool_customers`): handler Lambda per il target Gateway (nome tool da `client_context.custom.bedrockAgentCoreToolName`, prefisso `<target>___` rimosso), validazione pydantic, errori come codici. In `suppliagent_shared`: `auth` (`CallerContext`, `caller_scope`), `errors`, `aws` (`table()`, `put_event()`).
- **Comportamento**: chiamante noto → `KNOWN` con i propri locali (o portafoglio); `UNKNOWN` → match per codice cliente o P.IVA **e** nome locale (normalizzato, `difflib` ≥ 0.8 o contenimento ≥ metà lunghezza; stessa risposta `NOT_FOUND` per codice o nome sbagliati), poi `Contact` `PENDING_VERIFICATION` + `ChannelIdentity` non verificata (scrittura condizionata: un indirizzo già registrato non viene mai sovrascritto; un retry restituisce lo stesso contatto) ed evento `contact.identified`; massimo 3 tentativi per conversazione, poi `IDENTIFICATION_FAILED` (F-02.C4). Profilo: contatto → solo propri locali, senza dati interni (ragione sociale, zona, listino, insight: solo agente); agente → solo portafoglio; contatto non verificato → niente storico.
- **Scelte**: contesto chiamante iniettato dal codice dell'agente e scope sempre ricavato da DynamoDB, **fail-closed** (locali di un contatto in attesa di verifica in un insieme separato, da usare solo esplicitamente) – [INFRASTRUCTURE_DESIGN §5.3.2](./INFRASTRUCTURE_DESIGN.md); `channelAddress` aggiunto alla richiesta di turno (02 §6.2); ricerca cliente con Scan filtrato (anagrafica piccola; GSI se cresce).
- **Revisione di sicurezza** (subagent): corretti scope dei contatti non verificati, limite tentativi, scritture condizionate senza rilettura, eccezioni non gestite (`INTERNAL_ERROR`), limiti di lunghezza, dati interni esposti ai contatti. Rinviati: verifica SPF/DKIM delle email in ingresso (**requisito per T-21**, scritto in §5.3.2), merge del `caller` testato in T-41, controllo `channelAddress`↔`contactId` in `caller_scope` (difesa in profondità, una lettura in più).
- **Fuori**: Lambda e target Gateway in CDK (T-40); conferma dal contatto principale o dal back office (T-62/T-63).
- **Seguito**: `lastOrders` legge `OrderHistory` (seed); T-46 deve scriverci gli ordini confermati (o il profilo leggere anche `Orders`), altrimenti "come l'ultima volta" ignora gli ordini fatti con l'agente.
- **Test**: `services/tools/customers/tests` – 32 test: 7 di autorizzazione negativa sul profilo (locale di altro cliente, fuori portafoglio, secondo locale del contatto in portafoglio altrui, `UNKNOWN`, ruolo/ID incoerenti, contatto inesistente, cliente inesistente), stato contatto sconosciuto, indirizzo già registrato mai riassegnato, limite tentativi, campi estranei nel `caller` rifiutati, errori imprevisti nascosti; verificato con mutazione che togliendo il controllo di scope 9 test falliscono.
- **Commit**: `dc77400` (PR `feat/FN-03-customers-tool`).

### T-04 (parte) – Dati di prova: anagrafiche, storico, insight · FN-31
- **Cosa**: dati **sintetici** in `seed/data/` per `Customers` (6 locali), `Contacts` (5), `ChannelIdentities` (10, numeri fittizi), `SalesReps` (2), `OrderHistory` (8 settimane, 99 ordini con pattern di riordino), `CustomerInsights` (riordini attesi, prodotti smessi, ≤ 1 suggerimento); modelli pydantic in `suppliagent_shared.models`; `seed/seed.py --env <env>` valida e scrive (PutItem, idempotente). Dettagli in [seed/README](../seed/README.md).
- **Scelte**: portafoglio dell'agente = `Customers.repId` (nessuna lista duplicata in `SalesReps`); `Contacts.customerId` = locale principale (GSI) + `customerIds` per tutti i locali; indirizzi canale `CANALE#indirizzo` (telefono E.164); numero reale per la demo solo in `seed/private/` (ignorato da git); `mypy_path` alla root per mappare i package sotto `services/`.
- **Resto di T-04** (catalogo, listini, promo, stock, calendario, `reset.py`): resta nel backlog, sessione Agente con T-06/T-45.
- **Test**: `tests/test_seed.py` (validazione, chiavi univoche, riferimenti, scenari demo coperti, scrittura su DynamoDB con moto).
- **Commit**: `218b823` (PR `feat/FN-31-seed-core`).

### T-62 (parte UI con dati mock) – Inbox ordini + dettaglio con bigliettino · FN-28
- **Cosa**: inbox (`/`) con filtri stato, righe incerte, problemi di consegna, handoff, ordinata per ultimo aggiornamento e ricaricata ogni 2 s; dettaglio (`/orders/:orderId`) con la **foto del bigliettino a sinistra e le righe a destra**: un riquadro per riga (da `imageRegion` normalizzata), selezione sincronizzata riga↔riquadro, righe corrette evidenziate ("Corrected by …"), scelta tra i candidati per le righe `AMBIGUOUS`/`UNMATCHED` (disabilitata per `judge`, FN-28/FN-32).
- **Dati mock** (`console/src/orders/fixtures.ts`): 4 ordini sintetici (pub, ristorante, bar, email con handoff e problema di consegna) sulle foto anonimizzate di `agent/evals/data/bigliettini/` con riquadri posizionati a mano; contratti di `02 §2.3/§2.4/§6.3`. Banner "Mock data" nell'inbox; `VITE_ORDERS_SOURCE=api` passa all'API reale (`GET /orders`, `GET /orders/{id}` di T-60).
- **Assunzioni da allineare con T-46**: il riepilogo ordine porta `customerName`, `uncertainLines`, `handoff`; la riga porta il nome prodotto (`name`); `source` sull'ordine; la correzione riga è un'azione lato server (oggi `httpOrdersApi.correctLine` lancia "not available").
- **Test**: `console/src/orders/*.test.ts(x)` (21: filtri, inbox, dettaglio: immagine e righe affiancate, posizione dei riquadri, selezione sincronizzata, righe corrette, ordine senza immagine, scelta candidato, `judge` read-only, errori di caricamento); `npm run check` verde, `vite build` ok.
- **Resta** (riga T-62 nel backlog): collegamento alle API reali e correzione lato server, quando T-46 è su `main`.
- **Commit**: `88e591e` (branch `feat/FN-28-orders-views`).

### T-61 – Scaffold console React + Vite + TS · FN-28
- **Cosa**: `console/` con Vite + React 19 + TypeScript, React Router, React Query, Amplify Auth (solo client). Login Cognito (SRP), `AuthProvider`/`useAuth`, route guard `RequireRole`, layout con logo da `assets/brand/`, email/ruoli e badge *Read-only* per il solo `judge`, client `apiFetch` con ID token verso `VITE_API_URL`. Pagina `Orders` vuota (T-62).
- **Scelte**: token Cognito in `sessionStorage` (non `localStorage`, AGENTS §7); ruoli letti da `cognito:groups`, il guard è solo UI (l'API applica gli stessi ruoli); primo accesso con password temporanea (utente creato da console Cognito) gestito con il passo "nuova password" nel login (fix successivo, PR `fix/FN-28-console-new-password`); niente librerie UI/CSS, solo `styles.css`.
- **Dipendenze aggiunte** (AGENTS §6, ok dell'utente): react, react-dom, react-router-dom, @tanstack/react-query, aws-amplify; dev: vite, @vitejs/plugin-react, vitest, jsdom, @testing-library/{react,jest-dom,user-event}, @types/react{,-dom}.
- **Test**: `console/src/**/*.test.ts(x)` (15: ruoli, guard con loading/signed-out/ruolo mancante/gruppo assente, login, client API); `npm run check` verde, `vite build` ok.
- **Non incluso**: deploy della SPA sul bucket (comandi in `console/README.md`); config via `.env.local` da `.env.example`.
- **Commit**: `94d26a8` (branch `feat/FN-28-console-scaffold`).

### T-20 – ChannelsStack: SES + EUM Social · FN-01
- **Cosa**: `ChannelsStack` con 3 topic SNS cifrati con la CMK (`wa-events` per l'event destination della WABA, `mail-inbound`, `email-events`; publish solo dai service principal `social-messaging`/`ses` con `aws:SourceAccount`), configuration set SES `suppliagent-<env>-cs` (TLS obbligatorio, reputation metrics, event destination SNS su send/delivery/bounce/complaint/open/click). Con `-c sesDomain=<dominio>`: identity SES (Easy DKIM), receipt rule set `suppliagent-<env>-inbound` (S3 `inbound-mail/mail/` cifrato KMS + notifica su `mail-inbound`) e sua attivazione. `FoundationStack`: key policy della CMK per `ses`, `social-messaging`, `sns` e bucket policy `inbound-mail` per SES (entrambe con `aws:SourceAccount`).
- **Scelte**: parametri legati a passi manuali da context CDK e pubblicati su SSM (`waPhoneNumberId`, `sesDomain`, `sesFromAddress`, default `UNSET`) più `waEventsTopicArn` e `sesConfigurationSet`: collegare il numero WhatsApp = `-c waPhoneNumberId=<id>`, senza modificare il codice. Senza `sesDomain` nessuna identity né rule set (account senza rule set attivo il 26/10, SES in sandbox). Receipt rule in L1 per non far dipendere Foundation da Channels. **Fuori scope** (spostato in T-27): EUM SMS/RCS v2.
- **Test**: `infra/test/channels-stack.test.ts` (topic e policy, configuration set, con/senza dominio, SSM, grant in Foundation, cdk-nag dev/demo con e senza dominio); `npm run check` verde.
- **Da fare a mano**: vedi README «Manual steps» (event destination della WABA, DNS DKIM/MX, uscita dalla sandbox SES).
- **Commit**: branch `feat/FN-01-channels-stack`.

### T-60 – `ConsoleStack` (versione ridotta) · FN-28, FN-32
- **Cosa**: Cognito (gruppi `backoffice`, `sales_rep`, `judge`; self sign-up off, attributo custom `repId`, client SPA senza secret, SRP); bucket S3 + CloudFront con OAC per la SPA (log su bucket dedicato); API REST `/v1` con authorizer Cognito (`GET /orders`, `GET /orders/{orderId}`) e Lambda `console_api` (`services/console_api/`) **in sola lettura** su `Orders` (+ URL presigned a 5 min per l'immagine del bigliettino). Output: `UserPoolId`, `UserPoolClientId`, `ApiUrl`, `ConsoleUrl`, `SiteBucketName`.
- **Scelte**: ruolo dai claim Cognito, mai dal body; `backoffice`/`judge` vedono tutto, `sales_rep` solo `repId` del proprio claim (`custom:repId`) e un ordine altrui risponde 404; bucket SPA in SSE-S3 (l'OAC non usa la CMK senza toccare la key policy di Foundation); bucket SPA/log `RETAIN` (niente `autoDeleteObjects`, il suo provider crea un log group senza tag); IAM con statement espliciti (GetItem/Query/Scan, `s3:GetObject`, `kms:Decrypt`).
- **Assunzione**: l'ordine porta `imageS3Uri` (`s3://bucket/key`) con la foto del bigliettino; da allineare con T-46/T-22.
- **Rinviati**: WebSocket + broadcaster (T-63), `rep_chat` (T-64), **WAF** (costo fisso, AGENTS §11: decidere prima della demo; ack `AwsSolutions-CFR2`/`APIG3` da rimuovere se lo si aggiunge), correzione righe (scrittura, con T-46), paginazione liste (max 100).
- **Test**: `infra/test/console-stack.test.ts` (gruppi, client, OAC, authorizer su ogni metodo, Orders solo lettura), `services/console_api/tests/test_handler.py` (14, inclusa autorizzazione negativa per ruolo/portafoglio); `npm run check` verde (cdk-nag dev+demo).
- **Deploy**: non eseguito (`cdk deploy suppliagent-dev-console --exclusively -c env=dev` dopo conferma).
- **Commit**: `141a6e0` (branch `feat/FN-28-console-stack`).

### T-28 – Testi dei template WhatsApp · FN-12, FN-19
- **Cosa**: 8 template (IT/EN) in formato `template-definition` di Meta in `services/notifier/whatsapp_templates/`: `order_confirmation`, `order_pending_reminder`, `delivery_update` (UTILITY) e `reorder_suggestion` (MARKETING); revisione e regole di contenuto in [09_CONTENT_AND_TEMPLATES](./09_CONTENT_AND_TEMPLATES.md).
- **Scelte**: nessun pulsante conferma un ordine senza riepilogo; footer "Assistente virtuale ordini"; nessun nome del distributore; *Stop proposte* revoca il consenso proattivo.
- **Test**: `tests/test_whatsapp_templates.py` (regole di Meta, stessa forma IT/EN).
- **Seguito**: l'invio a Meta e l'approvazione sono il task **T-29** (serve la WABA collegata a EUM Social).
- **Commit**: `1bbb767`, `5c00610` (PR `feat/FN-12-whatsapp-templates`).

---

## 25/10/2026

### Primo deploy `dev` · FN-32
- **Dove**: account `471112860008` (condiviso con altri progetti beSharp), `eu-west-1`, profilo `default`; bootstrap CDK già presente (`CDKToolkit` v30), non rifatto. Deploy **da locale** (`cd infra && npx cdk deploy --all -c env=dev`).
- **Cosa c'è**: 9 stack `suppliagent-dev-*` (Foundation e Data con risorse, gli altri vuoti); 18 tabelle DynamoDB (on-demand, PITR, CMK, Streams su orders/messages); 6 bucket `suppliagent-dev-<nome>-471112860008`; CMK `alias/suppliagent-dev`; event bus `suppliagent-dev-events` cifrato; 16 parametri SSM sotto `/suppliagent/dev/`; 55 risorse con `Project=Hackathon AWS CDS` + `Env=dev`.
- **Scelte**: rimosso l'AWS Budget dal `FoundationStack` (account condiviso: conterebbe la spesa di tutti) – commit `af4536d`.
- **Verifica**: `aws cloudformation list-stacks`, `aws dynamodb list-tables`, `aws ssm get-parameters-by-path --path /suppliagent/dev`, `npx cdk diff -c env=dev` senza differenze.
- **Nota operativa**: da Claude Code il deploy va lanciato fuori dal sandbox (il proxy di rete interrompe le risposte dei changeset CloudFormation con `Error: aborted`).

---

## 24/10/2026

### T-13 – Tag obbligatori su tutte le risorse · FN-32
- **Cosa**: `Project=Hackathon AWS CDS`, `Owner=matteo.goretti@besharp.it` (costante `MANDATORY_TAGS` in `infra/config/environments.ts`) e `Env=<env>` applicati sia con `Tags.of(app)` sia come **tag di stack** espliciti (flag `@aws-cdk/core:explicitStackTags` attivo): CloudFormation li propaga anche alle risorse "raw" che `Tags.of()` non raggiunge (Lambda e ruolo del provider `autoDeleteObjects`).
- **Casi espliciti**: `CfnBudget` non è `ITaggable` → `resourceTags` impostati a mano; il log group della Lambda del provider `autoDeleteObjects` (creato da Lambda a runtime, fuori da CloudFormation e senza tag) è **pre-creato** in CDK con tag, CMK e retention, e i custom resource ne dipendono.
- **Fuori dal CDK**: bootstrap con `--tags` (vedi HANDOFF §3); risorse create a mano da console vanno taggate a mano (START_HERE §1.2).
- **Test**: tag su tutti i 9 stack, su ogni risorsa taggabile, sul budget, log group del provider (37 test vitest); `npm run check` e synth demo verdi.
- **Commit**: `2b5d967`.

---

## 23/10/2026 – Fase P0 (branch `chore/p0-foundations`)

### T-01 – Scaffold monorepo · –
- **Cosa**: uv workspace alla root (`agent`, `services/*`, `services/tools/*`) con package `suppliagent_agent` e `suppliagent_shared` (vuoti); npm workspaces (`infra`, `console` placeholder fino a T-61); ruff, mypy strict, pytest, eslint (flat config), prettier; script unici dalla root `npm run lint | typecheck | test | synth | check | format`; hook di lint di Claude Code allineato ai workspaces.
- **Versioni fissate**: `aws-cdk-lib` 2.274.0, CLI `aws-cdk` 2.1146.1, `cdk-nag` 3.0.2, TypeScript 6.0.3 (7.x non supportato da `typescript-eslint`), vitest 5; Python 3.12, `strands-agents` ≥ 1.62, `bedrock-agentcore` ≥ 1.24.2, `aws-lambda-powertools` ≥ 3.37, `pydantic` ≥ 2.14.1, `boto3` ≥ 1.43.118.
- **Commit**: `155c4ae`.

### T-03 – CDK app, construct Lambda, Foundation e Data · FN-32
- **Cosa**: app CDK con config `dev`/`demo` (`infra/config/environments.ts`, parametri 02 §7 pubblicati su SSM `/suppliagent/<env>/<nome>`); construct `PythonLambda` (ARM64, Python 3.12, layer Powertools, X-Ray, KMS su env e log, log retention, DLQ opzionale, role senza managed policy); `FoundationStack` (CMK con rotazione, 5 bucket SSE-KMS + `access-logs` SSE-S3, event bus cifrato, Budget opzionale con `-c budgetAlertEmail`); `DataStack` (18 tabelle §5.7: on-demand, PITR, CMK, Streams su `Orders`/`Messages`, TTL su `TurnBuffer`/`WsConnections`); 7 stack vuoti collegati nell'ordine §4; cdk-nag v3 come plugin di validazione.
- **Scelte**: `RemovalPolicy.DESTROY` ovunque (dati ripopolabili dal seed, T-04); stack env-agnostic sull'account; seed custom resource rinviata a T-04; bundling Lambda + libreria shared rinviato a T-21.
- **Test**: 34 test vitest (cdk-nag pulito su dev/demo e sul construct, chiavi e GSI di ogni tabella, cifratura, SSM, budget, dipendenze tra stack).
- **Commit**: `692f18c`, `dd0d8a6`.

### T-02 – CI GitHub Actions · FN-32
- **Cosa**: `.github/workflows/ci.yml` su PR e push su `main`: job Python (ruff, format, mypy, pytest) e TypeScript (eslint, prettier, tsc, vitest, `cdk synth` dev e demo con cdk-nag), senza credenziali AWS; `setup-uv` fissata a SHA, timeout, telemetria CDK disattivata.
- **Da verificare**: prima esecuzione reale al primo push.
- **Commit**: `f55db76`, `2d89d14`.

**Verifica P0**: `npm ci && uv sync && npm run check`, poi `cd infra && npx cdk synth -c env=demo`.

### Punti aperti chiusi (INFRASTRUCTURE_DESIGN §12)
- Versione del layer Powertools: **v40** (`AWSLambdaPowertoolsPythonV3-python312-arm64:40`), confermata su SSM `/aws/service/powertools/python/arm64/python3.12/latest` in eu-west-1; è quella in `infra/config/environments.ts`.
- Copertura CDK: AgentCore con L2 stabili in `aws-cdk-lib/aws-bedrockagentcore`; S3 Vectors e Knowledge Base (storage `S3_VECTORS`) con L1 (dettagli nella nota di §4).

---

## Prima del 23/10/2026

- **16/10** – `04_BACKLOG.md` scritto (ex TODO_DOCS #2).
- **≤ 12/10** – Region `eu-west-1` e Claude con inference profile `eu.` (ex INFRASTRUCTURE_DESIGN §12).
