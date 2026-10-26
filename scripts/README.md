# scripts – utilities (deploy helpers, demo reset, end-to-end checks)

| Script | What it does |
|---|---|
| `deploy-console.sh [dev\|demo]` | Builds the console with the ids from the `suppliagent-<env>-console` outputs, syncs the site bucket and invalidates CloudFront. Prints the console URL. |
