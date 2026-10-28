#!/usr/bin/env bash
# Builds the console and publishes it to the site bucket of suppliagent-<env>-console.
# Usage: scripts/deploy-console.sh [dev]   (AWS credentials from the environment, e.g. AWS_PROFILE)
# Needs the ConsoleStack already deployed; no secrets involved (Cognito/API ids come from stack outputs).
set -euo pipefail

ENV_NAME="${1:-dev}"
REGION="eu-west-1"
STACK="suppliagent-${ENV_NAME}-console"
cd "$(dirname "$0")/.."

output() {
  aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}

echo "Account: $(aws sts get-caller-identity --query Account --output text), region: $REGION, stack: $STACK"

BUCKET="$(output SiteBucketName)"
export VITE_USER_POOL_ID="$(output UserPoolId)"
export VITE_USER_POOL_CLIENT_ID="$(output UserPoolClientId)"
export VITE_API_URL="$(output ApiUrl)"
# Published console on real orders; pass VITE_ORDERS_SOURCE=mock for a demo without data.
export VITE_ORDERS_SOURCE="${VITE_ORDERS_SOURCE:-api}"
DISTRIBUTION="$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Comment=='suppliagent-${ENV_NAME} console'].Id | [0]" --output text)"
[ -n "$BUCKET" ] && [ "$DISTRIBUTION" != "None" ] || { echo "Stack outputs or distribution not found" >&2; exit 1; }

npm run build -w console

# Hashed assets are immutable; index.html must always be revalidated.
aws s3 sync console/dist "s3://${BUCKET}" --delete --exclude index.html \
  --cache-control "public,max-age=31536000,immutable" --region "$REGION"
aws s3 cp console/dist/index.html "s3://${BUCKET}/index.html" \
  --cache-control "no-cache" --content-type "text/html" --region "$REGION"
aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION" --paths "/*" >/dev/null

echo "Console: $(output ConsoleUrl)"
