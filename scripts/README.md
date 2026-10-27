# scripts – utilities (deploy helpers, demo reset, end-to-end checks)

| Script | What it does |
|---|---|
| `deploy-console.sh [dev\|demo]` | Builds the console with the ids from the `suppliagent-<env>-console` outputs, syncs the site bucket and invalidates CloudFront. Prints the console URL. |
| `invoke_agent.py` | Sends one message to the deployed agent as the turn dispatcher (T-22) will: resolves the role from `ChannelIdentities`, builds the turn request (TECHNICAL_FLOWS §6.2), prints the reply. Same `--conversation` = same history. `--image`/`--audio <s3Uri>` attach a file already under `media/<contactId>/…` (to try `extract_order_lines`). |
| `simulate_channel.py` | Simulated WhatsApp customer (T-14): publishes an EUM Social event (`--text`, `--image`, `--audio`) on the `wa-events` topic as a seed contact (`--from`), so Router, debounce, Dispatcher, agent and Notifier run for real. `--wait` prints the replies the Notifier records in `Messages` (status `SANDBOX`). Refuses to run unless SSM `notifierSandbox` is `true`. Files go to `sim/<mediaId>/` in the media bucket and the Router copies them to `media/`. |
| `ses-dns-records.sh <ses-domain> <hosted-zone-name>` | After deploying `channels` with `-c sesDomain`, adds the 3 DKIM CNAMEs, the inbound MX and a DMARC `p=none` TXT to an existing Route 53 public zone. CREATE only: never overwrites records of a shared zone. |
| `ses-production-access.sh <ses-domain> <contact-email>\|--test-only` | Requests SES production access (account-wide) and sends a test mail from `test@` to `ordini@` the domain to check inbound (router log `message stored`). |
