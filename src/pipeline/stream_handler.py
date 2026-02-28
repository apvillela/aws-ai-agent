"""
DynamoDB Stream → BigQuery pipeline Lambda.

Reads NEW_IMAGE events from the DynamoDB stream and inserts rows into BigQuery.
GCP credentials are stored in AWS SSM Parameter Store as a SecureString JSON key.
"""

import json
import os
from decimal import Decimal
from typing import Any

import boto3
from google.cloud import bigquery
from google.cloud.bigquery import LoadJobConfig, WriteDisposition
from google.oauth2 import service_account

# ── Config ─────────────────────────────────────────────────────────────────────

GCP_PROJECT_ID     = os.environ["GCP_PROJECT_ID"]
BIGQUERY_DATASET   = os.environ["BIGQUERY_DATASET"]
BIGQUERY_TABLE     = os.environ["BIGQUERY_TABLE"]
SSM_KEY_PARAM      = os.environ["GCP_SERVICE_ACCOUNT_KEY_PARAM"]

TABLE_REF = f"{GCP_PROJECT_ID}.{BIGQUERY_DATASET}.{BIGQUERY_TABLE}"

# ── AWS SSM client ─────────────────────────────────────────────────────────────

_ssm = None


def _get_ssm():
    global _ssm
    if _ssm is None:
        _ssm = boto3.client("ssm")
    return _ssm


def _get_gcp_credentials() -> service_account.Credentials:
    """Fetch the GCP service account JSON key from SSM and build credentials."""
    response = _get_ssm().get_parameter(Name=SSM_KEY_PARAM, WithDecryption=True)
    key_json = json.loads(response["Parameter"]["Value"])

    credentials = service_account.Credentials.from_service_account_info(
        key_json,
        scopes=["https://www.googleapis.com/auth/bigquery"],
    )
    return credentials


# ── BigQuery client (module-level singleton) ────────────────────────────────────

_bq_client = None


def _get_bq_client() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        credentials = _get_gcp_credentials()
        _bq_client = bigquery.Client(
            project=GCP_PROJECT_ID,
            credentials=credentials,
        )
    return _bq_client


# ── DynamoDB type unmarshalling ────────────────────────────────────────────────

def _unmarshal_value(value: dict) -> Any:
    """Convert a single DynamoDB typed value to a Python native type."""
    type_key = list(value.keys())[0]
    raw = value[type_key]

    if type_key == "S":
        return raw
    if type_key == "N":
        n = Decimal(raw)
        return int(n) if n == int(n) else float(n)
    if type_key == "BOOL":
        return raw
    if type_key == "NULL":
        return None
    if type_key == "L":
        return [_unmarshal_value(item) for item in raw]
    if type_key == "M":
        return {k: _unmarshal_value(v) for k, v in raw.items()}
    return raw


def _unmarshal_image(image: dict) -> dict:
    """Unmarshal a full DynamoDB NewImage dict to plain Python dict."""
    return {k: _unmarshal_value(v) for k, v in image.items()}


# ── Row builder ────────────────────────────────────────────────────────────────

def _build_bq_row(item: dict) -> dict:
    """Map a DynamoDB item to a BigQuery row matching the sentinel.leads schema."""
    score = item.get("score")
    rag   = item.get("rag_similarity")

    return {
        "lead_id":       item.get("lead_id"),
        "company_name":  item.get("company_name"),
        "sector":        item.get("sector"),
        "company_size":  int(item["company_size"]) if item.get("company_size") is not None else None,
        "budget_signal": item.get("budget_signal"),
        "score":         float(score) if score is not None else None,
        "tier":          item.get("tier"),
        "rag_similarity": float(rag) if rag is not None else None,
        "processed_at":  item.get("processed_at"),
    }


# ── Handler ────────────────────────────────────────────────────────────────────

def handler(event: dict[str, Any], context: Any) -> None:
    """Process DynamoDB Stream records and insert NEW_IMAGE events into BigQuery."""
    rows_to_insert = []

    for record in event.get("Records", []):
        event_name = record.get("eventName")
        if event_name not in ("INSERT", "MODIFY"):
            # Skip REMOVE events and any other types
            continue

        new_image = record.get("dynamodb", {}).get("NewImage")
        if not new_image:
            continue

        item = _unmarshal_image(new_image)

        # Only process enriched records (skip intermediate states)
        if item.get("status") != "enriched":
            continue

        row = _build_bq_row(item)
        rows_to_insert.append(row)
        print(f"Queued row for BigQuery: lead_id={row['lead_id']}, tier={row['tier']}")

    if not rows_to_insert:
        print("No enriched INSERT/MODIFY events in this batch — nothing to do.")
        return

    # Use batch load instead of streaming insert — streaming is not available on
    # the BigQuery free tier. load_table_from_json uses the batch load API which
    # is always available and free, with latency of a few seconds.
    client = _get_bq_client()
    job_config = LoadJobConfig(
        write_disposition=WriteDisposition.WRITE_APPEND,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        autodetect=False,
    )
    load_job = client.load_table_from_json(rows_to_insert, TABLE_REF, job_config=job_config)
    load_job.result()  # Wait for job to complete (raises on error)

    print(f"Successfully loaded {len(rows_to_insert)} row(s) into {TABLE_REF}")
