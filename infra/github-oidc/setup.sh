#!/usr/bin/env bash
# One-time setup: lets GitHub Actions deploy Sentinel via OIDC (no long-lived AWS keys).
# Run once from the repo root: bash infra/github-oidc/setup.sh
set -euo pipefail

ACCOUNT_ID="002259667831"
ROLE_NAME="sentinel-github-actions-deploy"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Creating GitHub OIDC provider (skips if it already exists)"
if ! aws iam get-open-id-connect-provider \
  --open-id-connect-provider-arn "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com" \
  >/dev/null 2>&1; then
  aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 2d74d6dfd96eea55ad7baafa0d3c6552b2dadc37 ab9d0263244dd0326eb67015705a667e79cfe998 \
    --tags Key=Project,Value=sentinel
else
  echo "    already exists, skipping"
fi

echo "==> Creating IAM role ${ROLE_NAME}"
aws iam create-role \
  --role-name "${ROLE_NAME}" \
  --assume-role-policy-document "file://${DIR}/trust-policy.json" \
  --tags Key=Project,Value=sentinel

echo "==> Attaching deploy policy"
aws iam put-role-policy \
  --role-name "${ROLE_NAME}" \
  --policy-name sentinel-deploy \
  --policy-document "file://${DIR}/deploy-policy.json"

echo "==> Done. Role ARN:"
aws iam get-role --role-name "${ROLE_NAME}" --query 'Role.Arn' --output text
