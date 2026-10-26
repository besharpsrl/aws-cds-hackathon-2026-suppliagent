#!/usr/bin/env bash
# Adds the SES records (3 DKIM CNAMEs, inbound MX, DMARC p=none) for a domain to an existing Route 53 public zone.
# Usage: scripts/ses-dns-records.sh <ses-domain> <hosted-zone-name>
#   e.g. scripts/ses-dns-records.sh suppliagent.stonecutters.besharp.net stonecutters.besharp.net
# Run after `cdk deploy suppliagent-<env>-channels -c sesDomain=<ses-domain>` (the SES identity must exist).
# Only CREATE actions: the batch fails as a whole if any record already exists, so shared zones are never overwritten.
# AWS credentials from the environment (e.g. AWS_PROFILE).
set -euo pipefail

DOMAIN="${1:?usage: $0 <ses-domain> <hosted-zone-name>}"
ZONE_NAME="${2:?usage: $0 <ses-domain> <hosted-zone-name>}"
REGION="eu-west-1"
export AWS_PAGER=""

ZONE=$(aws route53 list-hosted-zones-by-name --dns-name "$ZONE_NAME" \
  --query "HostedZones[?Name=='${ZONE_NAME%.}.' && Config.PrivateZone==\`false\`].Id | [0]" --output text)
[ "$ZONE" != "None" ] || { echo "public hosted zone $ZONE_NAME not found" >&2; exit 1; }
count() { aws route53 list-resource-record-sets --hosted-zone-id "$ZONE" --query 'length(ResourceRecordSets)' --output text; }

TOKENS=$(aws sesv2 get-email-identity --email-identity "$DOMAIN" --region "$REGION" \
  --query 'DkimAttributes.Tokens' --output text)
[ "$(echo "$TOKENS" | wc -w | tr -d ' ')" = "3" ] || { echo "expected 3 DKIM tokens, got: $TOKENS" >&2; exit 1; }

BATCH=$(python3 - "$DOMAIN" "$REGION" $TOKENS <<'PY'
import json, sys
domain, region, tokens = sys.argv[1], sys.argv[2], sys.argv[3:]
rec = lambda name, typ, value: {"Action": "CREATE", "ResourceRecordSet": {
    "Name": name, "Type": typ, "TTL": 300, "ResourceRecords": [{"Value": value}]}}
changes = [rec(f"{t}._domainkey.{domain}", "CNAME", f"{t}.dkim.amazonses.com") for t in tokens]
changes.append(rec(domain, "MX", f"10 inbound-smtp.{region}.amazonaws.com"))
changes.append(rec(f"_dmarc.{domain}", "TXT", '"v=DMARC1; p=none;"'))
print(json.dumps({"Comment": f"SuppliAgent SES records for {domain}", "Changes": changes}))
PY
)

echo "Account: $(aws sts get-caller-identity --query Account --output text), zone: $ZONE_NAME ($ZONE), domain: $DOMAIN"
echo "records before: $(count)"
CHANGE=$(aws route53 change-resource-record-sets --hosted-zone-id "$ZONE" --change-batch "$BATCH" \
  --query 'ChangeInfo.Id' --output text)
aws route53 wait resource-record-sets-changed --id "$CHANGE"
echo "records after: $(count) (change $CHANGE INSYNC)"
aws route53 list-resource-record-sets --hosted-zone-id "$ZONE" \
  --query "ResourceRecordSets[?ends_with(Name,'${DOMAIN}.')].[Type,Name]" --output text
echo "DKIM status (SUCCESS within minutes): $(aws sesv2 get-email-identity --email-identity "$DOMAIN" \
  --region "$REGION" --query 'DkimAttributes.Status' --output text)"
