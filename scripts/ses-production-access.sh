#!/usr/bin/env bash
# Requests SES production access (account-wide, eu-west-1) and/or sends an inbound test mail to the SES domain.
# Usage: scripts/ses-production-access.sh <ses-domain> <contact-email>   request production access, then test mail
#        scripts/ses-production-access.sh <ses-domain> --test-only        only the inbound test mail
# The test mail goes from test@<domain> to ordini@<domain>: allowed in the sandbox once the domain is verified.
# Check it with: aws logs tail /aws/lambda/suppliagent-<env>-inbound-router --since 5m  ("message stored", channel EMAIL)
# AWS credentials from the environment (e.g. AWS_PROFILE).
set -euo pipefail

DOMAIN="${1:?usage: $0 <ses-domain> <contact-email>|--test-only}"
CONTACT="${2:?usage: $0 <ses-domain> <contact-email>|--test-only}"
REGION="eu-west-1"
export AWS_PAGER=""

echo "Account: $(aws sts get-caller-identity --query Account --output text), region: $REGION, domain: $DOMAIN"
[ "$(aws sesv2 get-email-identity --email-identity "$DOMAIN" --region "$REGION" \
  --query VerifiedForSendingStatus --output text)" = "True" ] || { echo "$DOMAIN is not verified yet" >&2; exit 1; }

if [ "$CONTACT" != "--test-only" ]; then
  USE_CASE="SuppliAgent is an AI ordering assistant for a food distributor serving restaurants (B2B), built by beSharp (AWS Partner) for the AWS CDS Agentic AI Partner Hackathon. We send only transactional email from ${DOMAIN} (DKIM and DMARC configured): order confirmations with a PDF summary, delivery updates and replies to orders that customers send to our inbound address. Recipients are restaurant staff who placed an order or wrote to us first, plus hackathon judges testing the demo. No marketing, no purchased lists. Expected volume is under 200 emails per day. Bounces and complaints are tracked through an SES configuration set with event destinations to SNS, and addresses that bounce or complain are suppressed."
  aws sesv2 put-account-details --region "$REGION" --production-access-enabled --mail-type TRANSACTIONAL \
    --website-url "https://github.com/besharpsrl/aws-cds-hackathon-2026-suppliagent" \
    --contact-language EN --additional-contact-email-addresses "$CONTACT" \
    --use-case-description "$USE_CASE"
  echo "production access requested"
fi
aws sesv2 get-account --region "$REGION" \
  --query '{productionAccess:ProductionAccessEnabled,review:Details.ReviewDetails.Status}' --output json

aws sesv2 send-email --region "$REGION" --from-email-address "test@${DOMAIN}" \
  --destination "ToAddresses=ordini@${DOMAIN}" \
  --content "Simple={Subject={Data='Ordine di prova'},Body={Text={Data='Buongiorno, vorrei ordinare 2 casse di acqua naturale. Grazie'}}}" \
  --query MessageId --output text
echo "test mail sent to ordini@${DOMAIN}"
