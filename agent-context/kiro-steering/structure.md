---
inclusion: always
---

# Structure – SuppliAgent

```
SuppliAgent/
├── agent-context/           # contesto per agenti di sviluppo (AGENTS.md, CLAUDE.md, kiro-steering/)
├── SUPPLIAGENT_SOLUTION.md
├── docs/                    # fonte di verità (01 overview, 02 flussi, 03 funzionalità, infra, drawio)
├── assets/brand/            # logo
├── infra/                   # CDK TS: bin/, lib/stacks/ (1 file per stack), lib/constructs/, config/
├── agent/                   # Strands agent (zip, code deploy): main.py, src/suppliagent_agent/ (prompts/: customer, sales_rep, shared), evals/
├── services/                # Lambda Python, 1 cartella per funzione
│   ├── inbound_router/ (anche media → S3) turn_dispatcher/ notifier/ order_pdf/ erp_adapter/
│   ├── catalog_indexer/ insights_analyzer/ proactive_trigger/ console_api/ rep_chat/ broadcaster/
│   ├── tools/               # target Gateway: customers, order_intake, catalog, inventory_pricing, orders, reco, sales
│   └── shared/              # modelli pydantic, client CDS, auth per ruolo, logging, errori
├── console/                 # React + Vite + TS
├── seed/                    # dati anonimizzati + seed/reset
├── scripts/
└── .github/workflows/
```

## Ordine degli stack CDK
`Foundation → Data → Catalog → Channels → Agent → Messaging → Proactive → Console → Analytics`

## Naming
- Risorse AWS: `suppliagent-<env>-<componente>`; tag `Project=SuppliAgent`, `Env`, `Owner=beSharp`, `Hackathon=AWS-CDS-2026`.
- ID: `cus_`, `con_`, `rep_`, `ord_`, `conv_`, `iss_`.
- Branch: `feat/FN-xx-descrizione`, `fix/E-xx-descrizione`; commit Conventional Commits con `(FN-xx)`.

## Definition of Done
Criteri di accettazione FN soddisfatti · casi F-xx.Cn ed errori E-xx gestiti · unit test + test di autorizzazione negativa · lint/type/test/`cdk synth` verdi · eventi emessi · documentazione aggiornata.

## Non fare senza chiedere
Deploy su `demo` · cambio region/modello · servizi a costo fisso · client CDS non ammessi · cancellare dati/risorse · dati reali del cliente o marchi di terzi.

Contesto completo: #[[file:agent-context/AGENTS.md]]
