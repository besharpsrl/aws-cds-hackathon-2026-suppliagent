#!/usr/bin/env bash
# Points the console hostname (CNAME) at the CloudFront distribution of suppliagent-<env>-console, in an existing Route 53 public zone.
# Usage: scripts/console-dns-records.sh <console-domain> <hosted-zone-name> [env]
#   e.g. scripts/console-dns-records.sh app.suppliagent.stonecutters.besharp.net stonecutters.besharp.net
# Run after `cdk deploy suppliagent-<env>-console` with consoleDomain/consoleCertificateArn set.
# Only a CREATE action: fails if the record already exists, so shared zones are never overwritten.
# AWS credentials from the environment (e.g. AWS_PROFILE).
set -euo pipefail

DOMAIN="${1:?usage: $0 <console-domain> <hosted-zone-name> [env]}"
ZONE_NAME="${2:?usage: $0 <console-domain> <hosted-zone-name> [env]}"
ENV_NAME="${3:-dev}"
REGION="eu-west-1"
export AWS_PAGER=""

ZONE=$(aws route53 list-hosted-zones-by-name --dns-name "$ZONE_NAME" \
  --query "HostedZones[?Name=='${ZONE_NAME%.}.' && Config.PrivateZone==\`false\`].Id | [0]" --output text)
[ "$ZONE" != "None" ] || { echo "public hosted zone $ZONE_NAME not found" >&2; exit 1; }

TARGET=$(aws cloudformation describe-stacks --stack-name "suppliagent-${ENV_NAME}-console" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='DistributionDomainName'].OutputValue" --output text)
[ -n "$TARGET" ] && [ "$TARGET" != "None" ] || { echo "DistributionDomainName output not found: deploy console first" >&2; exit 1; }

BATCH=$(python3 - "$DOMAIN" "$TARGET" <<'PY'
import json, sys
domain, target = sys.argv[1], sys.argv[2]
print(json.dumps({"Comment": f"SuppliAgent console {domain}", "Changes": [{"Action": "CREATE", "ResourceRecordSet": {
    "Name": domain, "Type": "CNAME", "TTL": 300, "ResourceRecords": [{"Value": target}]}}]}))
PY
)

echo "Account: $(aws sts get-caller-identity --query Account --output text), zone: $ZONE_NAME ($ZONE), $DOMAIN -> $TARGET"
CHANGE=$(aws route53 change-resource-record-sets --hosted-zone-id "$ZONE" --change-batch "$BATCH" \
  --query 'ChangeInfo.Id' --output text)
aws route53 wait resource-record-sets-changed --id "$CHANGE"
echo "done: https://$DOMAIN"
