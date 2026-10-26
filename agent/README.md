# agent – Strands agent for Amazon Bedrock AgentCore Runtime (Python)

Deployed as a zip (direct code deploy, entrypoint `main.py`). Role-based prompts in `src/suppliagent_agent/prompts/` (`customer.md`, `sales_rep.md`, `shared.md`), role tool sets from the AgentCore Gateway (MCP, SigV4), caller context injected by code into every tool call. Conversation history lives in the Runtime session until AgentCore Memory (`actorId = contactId`, T-54).
Try the deployed agent: `uv run python scripts/invoke_agent.py --env dev --address 'WHATSAPP#+393330000001' --text "ciao"`.
`evals/` holds the evaluation datasets (handwritten order notes, voice notes, conversations) and the runner.
Spec: `docs/02_TECHNICAL_FLOWS.md`, `docs/03_FUNCTIONAL_SPEC.md` · Backlog: T-40…T-53.
