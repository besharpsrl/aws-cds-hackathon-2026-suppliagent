# services – Lambda functions (Python 3.12, ARM64)

One folder per function: `inbound_router`, `turn_dispatcher`, `media_fetcher`, `notifier`, `order_pdf`, `erp_adapter`, `catalog_indexer`, `insights_analyzer`, `proactive_trigger`, `console_api`, `rep_chat`, `broadcaster`.
`tools/` contains the AgentCore Gateway targets (`customers`, `order_intake`, `catalog`, `inventory_pricing`, `orders`, `reco`, `sales`); `shared/` the common library (models, CDS clients, role-based auth, logging, errors).
Only `notifier` may call CDS send APIs.
