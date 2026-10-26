# scripts – utilities (deploy helpers, demo reset, end-to-end checks)

| Script | What it does |
|---|---|
| `deploy-console.sh [dev\|demo]` | Builds the console with the ids from the `suppliagent-<env>-console` outputs, syncs the site bucket and invalidates CloudFront. Prints the console URL. |
| `invoke_agent.py` | Sends one message to the deployed agent as the turn dispatcher (T-22) will: resolves the role from `ChannelIdentities`, builds the turn request (TECHNICAL_FLOWS §6.2), prints the reply. Same `--conversation` = same history. |
