# TEARDOWN – spegnere SuppliAgent e non pagare più nulla

Procedura per eliminare l'ambiente `dev` dopo la fine del giudizio e azzerare i costi. **Non eseguirla prima del 13/11/2026 alle 02:00 (ora italiana)** = 12/11 17:00 PT, scadenza di M-10 (#84); la data scelta per lo spegnimento è il **14/11/2026**.

- Account `471112860008` (**condiviso** con altri progetti beSharp), region `eu-west-1`, profilo `default`.
- Tutti i comandi qui sotto **cancellano risorse e dati**: li lancia una persona, con conferma esplicita (AGENTS.md §11).
- Cosa NON toccare: lo stack `CDKToolkit` (bootstrap, serve agli altri progetti) e qualsiasi risorsa senza il tag `Project=Hackathon AWS CDS`.

## 0. Prima di cancellare (10 minuti)

1. Decidi cosa conservare: ordini e conversazioni demo (DynamoDB), file Parquet in S3 (analytics), log. I dati sono sintetici e si rigenerano con `seed/seed.py`, quindi di solito non serve nulla.
2. Se vuoi un'ultima copia dei log o degli ordini, esportali ora: dopo il passo 2 non esistono più (tabelle e bucket `autoDeleteObjects` hanno `RemovalPolicy.DESTROY`).
3. Fotografa i costi di partenza: Cost Explorer, filtro tag `Project=Hackathon AWS CDS`, ultimi 30 giorni (serve a confermare nel passo 6 che la spesa va a zero).

### Controlli preventivi (solo lettura)

Servono a sapere **prima** cosa esiste davvero. Tutti i comandi sono di sola lettura (`AWS_PROFILE=default`, account `471112860008`, `eu-west-1`). Salva l'output: nel passo 5 si confronta con quello.

```bash
export AWS_PROFILE=default AWS_REGION=eu-west-1
aws sts get-caller-identity --query Account --output text            # deve stampare 471112860008

# a) stack CloudFormation reali (nomi esatti e stato)
aws cloudformation list-stacks \
  --query "StackSummaries[?starts_with(StackName,'suppliagent-') && StackStatus!='DELETE_COMPLETE'].[StackName,StackStatus]" --output table
(cd infra && npx cdk list -c env=dev)                                 # i due elenchi devono coincidere

# b) tutto ciò che porta il tag di progetto, per servizio (cattura anche risorse fuori dagli stack)
aws resourcegroupstaggingapi get-resources --tag-filters Key=Project,Values="Hackathon AWS CDS" \
  --query 'ResourceTagMappingList[].ResourceARN' --output text | tr '\t' '\n' | sort > before-tagged.txt
cut -d: -f3 before-tagged.txt | sort | uniq -c                         # riepilogo per servizio

# c) bucket RETAIN o fuori stack
aws s3api list-buckets --query "Buckets[?contains(Name,'suppliagent')].Name" --output text

# d) risorse di messaggistica che possono avere un canone mensile
aws pinpoint-sms-voice-v2 describe-phone-numbers --query 'PhoneNumbers[].[PhoneNumber,Status,MonthlyLeasingPrice]' --output table
aws pinpoint-sms-voice-v2 describe-sender-ids --query 'SenderIds[].[SenderId,IsoCountryCode]' --output table
aws pinpoint-sms-voice-v2 describe-rcs-agents --query 'RcsAgents[].[RcsAgentId,Status]' --output table
aws socialmessaging list-linked-whatsapp-business-accounts --query 'LinkedAccounts[].[id,registrationStatus]' --output table

# e) SES: identità, configuration set e rule set attivo
aws sesv2 list-email-identities --query 'EmailIdentities[].IdentityName' --output text
aws ses describe-active-receipt-rule-set --query 'Metadata.Name'

# f) parametri SSM e log group con il prefisso del progetto
aws ssm get-parameters-by-path --path /suppliagent --recursive --query 'Parameters[].Name' --output text
aws logs describe-log-groups --log-group-name-prefix /aws/lambda/suppliagent --query 'logGroups[].logGroupName' --output text

# g) risorse AgentCore, Knowledge Base e S3 Vectors (di solito dentro gli stack, qui per esserne sicuri)
aws bedrock-agentcore-control list-agent-runtimes --query 'agentRuntimes[].agentRuntimeName' --output text
aws bedrock-agentcore-control list-memories --query 'memories[].id' --output text
aws bedrock-agentcore-control list-gateways --query 'items[].name' --output text
aws bedrock-agent list-knowledge-bases --query 'knowledgeBaseSummaries[?starts_with(name,`suppliagent`)].[name,knowledgeBaseId]' --output text
aws s3vectors list-vector-buckets --query 'vectorBuckets[].vectorBucketName' --output text

# h) DNS: record aggiunti per SES nella zona di dominio (se è su Route 53)
aws route53 list-hosted-zones-by-name --query 'HostedZones[].[Name,Id]' --output text
# poi: aws route53 list-resource-record-sets --hosted-zone-id <id> | cerca _domainkey, MX inbound-smtp, il CNAME `app.suppliagent…` (console) e il CNAME `_…acm-validations.aws`

# i) Certificato ACM della console (CloudFront lo vuole in us-east-1)
aws acm list-certificates --region us-east-1 --query 'CertificateSummaryList[].[DomainName,CertificateArn]' --output text
```

Come leggere i risultati:
- **a)** se `cdk list` ha stack che CloudFormation non ha (o viceversa), fermati e capisci perché prima di distruggere.
- **b)** ogni ARN fuori dagli stack CDK è una risorsa creata a mano: va nella tabella del passo 4.
- **c)** i bucket con `suppliagent` che non sono di `autoDeleteObjects` restano dopo `cdk destroy` (passo 3).
- **d)** un numero di telefono con `MonthlyLeasingPrice` > 0 costa ogni mese finché non lo rilasci; un sender ID senza numero è gratis.
- **e)** il rule set attivo deve essere quello dello stack; se è di un altro progetto **non toccarlo** (ce n'è uno solo attivo per region).
- **g)** un comando che risponde con errore di sintassi o servizio non trovato: aggiorna la CLI (`aws --version`) invece di assumere "non esiste".

## 1. Fermare i flussi in ingresso (evita costi e messaggi durante la cancellazione)

Inbound reale: WhatsApp, email SES, SMS/RCS. Per non ricevere messaggi mentre si cancella basta il passo 2, ma se vuoi spegnere prima i trigger proattivi:

```bash
AWS_PROFILE=default aws events disable-rule --name <regola> --region eu-west-1   # InsightsAnalyzerSchedule, ProactiveTriggerSchedule
```

Le regole sono nello stack `proactive` (cron 01:00 e 08:00 UTC). Il nome esatto: `aws events list-rules --name-prefix suppliagent-dev --region eu-west-1`.

## 2. Cancellare gli stack CDK

CDK calcola da solo l'ordine inverso delle dipendenze (analytics → console → proactive → messaging → agent → channels → catalog → data → foundation).

```bash
git switch main && git pull --ff-only
cd infra
AWS_PROFILE=default npx cdk list -c env=dev                 # controlla che sia l'elenco atteso (9 stack suppliagent-dev-*)
AWS_PROFILE=default npx cdk destroy --all -c env=dev        # chiede conferma per ogni stack
```

Non c'è `terminationProtection` negli stack. Se uno stack va in `DELETE_FAILED`:
- bucket non vuoto → svuotalo (passo 3) e rilancia `cdk destroy`;
- risorsa che dipende da una custom resource già rimossa → `aws cloudformation delete-stack --stack-name <stack> --deletion-mode FORCE_DELETE_STACK --region eu-west-1`, poi cancella a mano la risorsa rimasta (passo 5).

Cosa viene rimosso: tabelle DynamoDB, Lambda, code SQS/SNS, EventBridge, Cognito (user pool e utenti `judge`/`backoffice`/`sales_rep`), API Gateway, CloudFront, AgentCore (runtime, memory, gateway), Guardrail, Knowledge Base e S3 Vectors, Firehose/Glue/Athena, configuration set e identità SES, regole di ricezione (la custom resource disattiva il rule set), configuration set SMS/RCS, bucket con `autoDeleteObjects`. La chiave KMS (`pendingWindow` 7 giorni) passa in "pending deletion" e sparisce dopo 7 giorni: finché è pending non viene fatturata.

## 3. Bucket che CDK lascia (RemovalPolicy.RETAIN)

Nello stack `console` sono `RETAIN`: il bucket del sito (`SiteBucket`) e quello dei log (`LogsBucket`). Costano poco ma vanno eliminati.

```bash
AWS_PROFILE=default aws s3api list-buckets --query "Buckets[?contains(Name,'suppliagent-dev')].Name" --output text
# per ciascun bucket rimasto:
AWS_PROFILE=default aws s3 rm s3://<bucket> --recursive
AWS_PROFILE=default aws s3api delete-bucket --bucket <bucket> --region eu-west-1
```

Bucket con versioning: se `rm` non basta, svuota anche le versioni (`aws s3api list-object-versions` + `delete-objects`).

## 4. Risorse fuori da CloudFormation (cancellazione manuale)

Queste NON spariscono con `cdk destroy` e alcune hanno un costo fisso mensile.

| Risorsa | Dove | Costo | Come |
|---|---|---|---|
| Numero WhatsApp / WABA collegato a End User Messaging Social | console AWS + Meta Business | numero Meta, non AWS | Scollega il WABA da AWS (`disassociate-whatsapp-business-account`) solo se non serve ad altri; il numero e i 8 template restano in Meta (`delete-whatsapp-message-template` se vuoi) |
| Agente RCS e dispositivi di test | End User Messaging SMS/Voice | gratis in test | `aws pinpoint-sms-voice-v2 delete-rcs-agent` (e `delete-registration` per la `TEST_RCS_LAUNCH_REGISTRATION`) |
| Sender ID `SuppliAgent` (IT), eventuali numeri di origine | End User Messaging SMS | **canone mensile** se c'è un numero | `release-phone-number` / `release-sender-id` |
| Record DNS (DKIM CNAME, MX `inbound-smtp`) per `suppliagent.stonecutters.besharp.net`, CNAME `app.suppliagent…` verso CloudFront e CNAME di validazione ACM | zona Route 53 beSharp | zona condivisa | Rimuovi i record aggiunti; **non** cancellare la zona se è usata da altro |
| Certificato ACM `app.suppliagent.stonecutters.besharp.net` (us-east-1) | ACM | gratis | Dopo `cdk destroy` della console (il certificato è in uso finché esiste la distribution): `aws acm delete-certificate --region us-east-1 --certificate-arn <arn>` |
| Richiesta SES production access | account | — | Nulla da fare (resta, è a livello di account) |
| Parametri SSM `/suppliagent/dev/*` creati a mano (`notifierSandbox`, `waPhoneNumberId`, `sesDomain`) | Parameter Store | gratis | `aws ssm delete-parameters` se rimasti (`aws ssm get-parameters-by-path --path /suppliagent/dev --recursive`) |
| CloudWatch Log Group `/aws/lambda/suppliagent-dev-*`, AgentCore, Transaction Search | CloudWatch | storage | Se rimasti dopo lo stack: `aws logs delete-log-group` per ognuno |
| Transaction Search / `xray` destination | account | — | Lascia com'è (è a livello di account, usato da altri) |
| Eventi/memoria AgentCore | spariscono con lo stack `agent` | — | Verifica in console AgentCore che non resti nulla |

## 5. Ricerca di risorse orfane (con costo)

```bash
AWS_PROFILE=default aws resourcegroupstaggingapi get-resources --region eu-west-1 \
  --tag-filters Key=Project,Values="Hackathon AWS CDS" \
  --query 'ResourceTagMappingList[].ResourceARN' --output text | tr '\t' '\n'
```

La lista deve essere vuota o contenere solo risorse in cancellazione (la chiave KMS `pending deletion`). Controlla anche, nella stessa region, quelle senza tag che iniziano per `suppliagent-`:

```bash
AWS_PROFILE=default aws cloudformation list-stacks --region eu-west-1 \
  --query "StackSummaries[?contains(StackName,'suppliagent') && StackStatus!='DELETE_COMPLETE'].[StackName,StackStatus]" --output table
```

## 6. Verifica che non si paghi più

1. Cost Explorer, stesso filtro del passo 0: il giorno dopo la cancellazione il costo giornaliero del tag deve tendere a 0 (dati con 24-48 h di ritardo).
2. Dopo 7 giorni controlla che la chiave KMS risulti `PendingDeletion` o già cancellata (`aws kms list-keys` / console KMS).
3. Dopo la fine del mese controlla la fattura: deve restare solo la quota di Bedrock/Transcribe già consumata.

## 7. Se serve rimettere in piedi tutto

La procedura da zero è nel README, sezione *Getting started*: `cdk deploy --all`, `seed/seed.py`, `scripts/deploy-console.sh dev`. I passi manuali (WhatsApp, SES, RCS, utenti Cognito) vanno rifatti.
