#!/bin/bash
# Sentinel GCP Infrastructure Setup
# Run AFTER authenticating: gcloud auth login
# This script creates the BigQuery resources, service account, stores the key
# in AWS SSM, and redeploys the SAM stack.
set -euo pipefail

# ── Paths ──────────────────────────────────────────────────────────────────────
GCLOUD_BIN="/tmp/google-cloud-sdk/bin"
export PATH="$GCLOUD_BIN:$PATH"
WORKSPACE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
KEY_FILE="$WORKSPACE_DIR/sentinel-bq-key.json"
SAM_BIN="$(command -v sam || echo sam)"

# ── Config ─────────────────────────────────────────────────────────────────────
PROJECT_NAME="sentinel-pipeline"
DATASET_ID="sentinel"
TABLE_ID="leads"
SA_NAME="sentinel-bq-writer"
REGION="US"
AWS_REGION="us-east-1"
SSM_GCP_KEY_PARAM="/sentinel/gcp_service_account_key"
SSM_GCP_PROJECT_PARAM="/sentinel/gcp_project_id"

echo "=== Sentinel GCP Infrastructure Setup ==="
echo ""

# 1. Check gcloud authentication
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | grep -q "@"; then
  echo "ERROR: Not authenticated. Run: gcloud auth login"
  exit 1
fi
ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -1)
echo "Authenticated as: $ACCOUNT"
echo ""

# 2. Create or select project
EXISTING=$(gcloud projects list --format="value(projectId)" 2>/dev/null | grep "^$PROJECT_NAME" | head -1 || true)
if [ -z "$EXISTING" ]; then
  SUFFIX=$(date +%s | tail -c 7)
  PROJECT_ID="${PROJECT_NAME}-${SUFFIX}"
  echo "Creating project $PROJECT_ID..."
  gcloud projects create "$PROJECT_ID" --name="$PROJECT_NAME"
  echo "Project created."
else
  PROJECT_ID="$EXISTING"
  echo "Using existing project: $PROJECT_ID"
fi
gcloud config set project "$PROJECT_ID" --quiet
echo "Active project: $PROJECT_ID"
echo ""

# 3. Enable BigQuery API
echo "Enabling BigQuery API..."
gcloud services enable bigquery.googleapis.com --quiet
sleep 3
echo "BigQuery API enabled."
echo ""

# 4. Create dataset
echo "Creating dataset '$DATASET_ID'..."
if bq ls "$PROJECT_ID:$DATASET_ID" &>/dev/null; then
  echo "Dataset already exists, skipping."
else
  bq mk --dataset --location="$REGION" "$PROJECT_ID:$DATASET_ID"
  echo "Dataset created."
fi
echo ""

# 5. Create leads table
echo "Creating table '$DATASET_ID.$TABLE_ID'..."
SCHEMA_FILE="/tmp/sentinel_leads_schema.json"
cat > "$SCHEMA_FILE" <<'EOF'
[
  {"name":"lead_id",       "type":"STRING",    "mode":"REQUIRED"},
  {"name":"company_name",  "type":"STRING",    "mode":"REQUIRED"},
  {"name":"sector",        "type":"STRING",    "mode":"NULLABLE"},
  {"name":"company_size",  "type":"INTEGER",   "mode":"NULLABLE"},
  {"name":"budget_signal", "type":"STRING",    "mode":"NULLABLE"},
  {"name":"score",         "type":"FLOAT",     "mode":"NULLABLE"},
  {"name":"tier",          "type":"STRING",    "mode":"NULLABLE"},
  {"name":"rag_similarity","type":"FLOAT",     "mode":"NULLABLE"},
  {"name":"received_at",   "type":"TIMESTAMP", "mode":"NULLABLE"},
  {"name":"processed_at",  "type":"TIMESTAMP", "mode":"REQUIRED"}
]
EOF
if bq show "$PROJECT_ID:$DATASET_ID.$TABLE_ID" &>/dev/null; then
  echo "Table already exists, skipping."
else
  bq mk --table "$PROJECT_ID:$DATASET_ID.$TABLE_ID" "$SCHEMA_FILE"
  echo "Table created."
fi
echo ""

# 6. Create service account
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
echo "Creating service account $SA_EMAIL..."
if gcloud iam service-accounts describe "$SA_EMAIL" --quiet &>/dev/null; then
  echo "Service account already exists, skipping creation."
else
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="Sentinel BigQuery Writer" --quiet
  echo "Service account created."
fi

# Grant BigQuery Data Editor role
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/bigquery.dataEditor" --quiet
# Grant BigQuery Job User role (required for queries)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/bigquery.jobUser" --quiet
echo "IAM roles assigned."
echo ""

# 7. Download service account JSON key
echo "Downloading service account key to $KEY_FILE..."
gcloud iam service-accounts keys create "$KEY_FILE" \
  --iam-account="$SA_EMAIL" --quiet
chmod 600 "$KEY_FILE"
echo "Key saved."
echo ""

# 8. Store in AWS SSM
echo "Storing GCP credentials in AWS SSM..."
aws ssm put-parameter \
  --name "$SSM_GCP_PROJECT_PARAM" \
  --value "$PROJECT_ID" \
  --type String \
  --overwrite \
  --region "$AWS_REGION" \
  --no-cli-pager
aws ssm put-parameter \
  --name "$SSM_GCP_KEY_PARAM" \
  --value "$(cat "$KEY_FILE")" \
  --type SecureString \
  --overwrite \
  --region "$AWS_REGION" \
  --no-cli-pager
echo "SSM parameters stored:"
echo "  $SSM_GCP_PROJECT_PARAM = $PROJECT_ID"
echo "  $SSM_GCP_KEY_PARAM = (SecureString, GCP service account JSON)"
echo ""

# 9. Rebuild and redeploy SAM stack (picks up real GCP_PROJECT_ID)
echo "Rebuilding and redeploying SAM stack..."
cd "$WORKSPACE_DIR"
"$SAM_BIN" build && "$SAM_BIN" deploy --no-confirm-changeset
echo ""

echo "======================================================"
echo "GCP Infrastructure Setup Complete!"
echo ""
echo "Project ID : $PROJECT_ID"
echo "Dataset    : $DATASET_ID"
echo "Table      : $TABLE_ID"
echo "SA email   : $SA_EMAIL"
echo "Key file   : $KEY_FILE  (gitignored)"
echo ""
echo "Next step: post a lead via the API and verify a row"
echo "appears in BigQuery within 60s."
echo ""
echo "BigQuery query:"
echo "  SELECT * FROM \`$PROJECT_ID.$DATASET_ID.$TABLE_ID\`"
echo "  ORDER BY processed_at DESC LIMIT 10;"
echo "======================================================"
