"""
AI Enrichment Lambda — reads lead from SQS, runs the ReAct agent, writes to DynamoDB.

SQS event → parse lead → agent.enrich_lead() → DynamoDB.put_item()
"""

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3

# ── Fetch secrets from SSM on cold start ──────────────────────────────────────

def _init_secrets():
    """Read SecureString parameters from SSM and set as env vars (runs once per cold start)."""
    ssm = boto3.client("ssm")
    pinecone_param = os.environ.get("PINECONE_API_KEY_PARAM", "/sentinel/pinecone_api_key")
    gemini_param = os.environ.get("GEMINI_API_KEY_PARAM", "/sentinel/gemini_api_key")

    response = ssm.get_parameters(
        Names=[pinecone_param, gemini_param],
        WithDecryption=True,
    )
    for param in response["Parameters"]:
        if param["Name"] == pinecone_param:
            os.environ["PINECONE_API_KEY"] = param["Value"]
        elif param["Name"] == gemini_param:
            os.environ["GEMINI_API_KEY"] = param["Value"]

    missing = [
        name
        for name in [pinecone_param, gemini_param]
        if name not in {p["Name"] for p in response["Parameters"]}
    ]
    if missing:
        raise RuntimeError(f"SSM parameters not found: {missing}")


_init_secrets()

# Import agent AFTER env vars are set (agent.py reads them at module level)
from agent import enrich_lead  # noqa: E402

# ── DynamoDB client ────────────────────────────────────────────────────────────

_dynamodb = None


def _get_table():
    global _dynamodb
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb").Table(
            os.environ["DYNAMODB_TABLE_NAME"]
        )
    return _dynamodb


# ── Handler ────────────────────────────────────────────────────────────────────

def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda entry point — processes SQS records one at a time (BatchSize=1 in SAM).
    Returns ReportBatchItemFailures-compatible response for partial failure handling.
    """
    batch_item_failures = []

    for record in event.get("Records", []):
        message_id = record.get("messageId", "unknown")
        lead_id = "unknown"
        try:
            body = json.loads(record.get("body", "{}"))
            lead_id = body.get("lead_id", "unknown")
            _process_record(body)
        except Exception as exc:
            print(f"ERROR processing message {message_id} (lead {lead_id}): {exc}")
            batch_item_failures.append({"itemIdentifier": message_id})

    return {"batchItemFailures": batch_item_failures}


def _process_record(body: dict[str, Any]) -> None:
    """Enrich a single lead and persist to DynamoDB."""
    lead_id = body["lead_id"]
    print(f"Processing lead {lead_id} — {body.get('company_name', 'unknown')}")

    # Run the AI agent
    enrichment = enrich_lead(body, verbose=False)

    # Build the full DynamoDB record
    item = {
        "lead_id":            lead_id,
        "company_name":       body.get("company_name"),
        "sector":             body.get("sector"),
        "company_size":       body.get("company_size"),
        "budget_signal":      body.get("budget_signal"),
        "contact_email":      body.get("contact_email"),
        "received_at":        body.get("received_at"),
        "score":              Decimal(str(enrichment.get("score", 0))),
        "tier":               enrichment.get("tier", "COLD"),
        "summary":            enrichment.get("summary", ""),
        "rag_similarity":     Decimal(str(enrichment.get("rag_similarity", 0))),
        "rag_context_snippet": enrichment.get("rag_context_snippet", ""),
        "processed_at":       datetime.now(timezone.utc).isoformat(),
        "status":             "enriched",
    }

    table = _get_table()
    table.put_item(Item=item)
    print(f"Saved lead {lead_id} to DynamoDB — tier={item['tier']}, score={item['score']}")
