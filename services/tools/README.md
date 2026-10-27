# services/tools – AgentCore Gateway targets

Role-based authorization is enforced **inside each tool** (with negative tests). Tools return data, never user-facing text. See `docs/02_TECHNICAL_FLOWS.md` §6.5.

Every tool receives a `caller` argument set by the agent code, never by the model; the scope is read from DynamoDB (`suppliagent_shared.auth.caller_scope`). Contract: `docs/INFRASTRUCTURE_DESIGN.md` §5.3.2.

| Package | Tools | Task |
|---|---|---|
| `customers/` | `identify_contact`, `get_customer_profile` | T-42 |
| `catalog/` | `match_products`, `search_catalog` (Gateway target `catalog`) | T-44 |
| `order_intake/` | `extract_order_lines` (foto, vocale, testo → righe grezze; Gateway target `order-intake`) | T-43 |
