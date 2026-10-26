# SuppliAgent – Registro del lavoro completato

> Qui finisce tutto ciò che è **chiuso**: task del backlog, documenti scritti, punti aperti risolti.
> Regola: quando una voce è completata la si **rimuove** dal documento "da fare" (`04_BACKLOG.md`, `TODO_DOCS.md`, punti aperti di `INFRASTRUCTURE_DESIGN.md` §12, ecc.) e la si aggiunge qui, in cima, con data, riferimenti e come verificarla.
> Un ID `T-xx` citato come dipendenza nel backlog ma assente dalle sue tabelle è completato: lo trovi qui.

---

## 26/10/2026

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
- **Scelte**: token Cognito in `sessionStorage` (non `localStorage`, AGENTS §7); ruoli letti da `cognito:groups`, il guard è solo UI (l'API applica gli stessi ruoli); nessuna UI per il cambio password (l'admin imposta password permanente, `ponytail` in `AuthContext`); niente librerie UI/CSS, solo `styles.css`.
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
