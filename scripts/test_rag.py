"""
Local RAG test script — verifies that Pinecone queries return semantically relevant results.

Usage:
    export PINECONE_API_KEY=<your-key>
    export GEMINI_API_KEY=<your-key>
    python scripts/test_rag.py

Runs 4 test queries covering VIP, HOT, COLD, and ambiguous scenarios.
"""

import os
import json
import time
from google import genai
from google.genai import types as genai_types
from pinecone import Pinecone

# ── Config ────────────────────────────────────────────────────────────────────

PINECONE_API_KEY = os.environ["PINECONE_API_KEY"]
GEMINI_API_KEY   = os.environ["GEMINI_API_KEY"]
INDEX_NAME       = os.environ.get("PINECONE_INDEX_NAME", "sentinel-profiles")
EMBEDDING_MODEL  = "gemini-embedding-001"
EMBEDDING_DIM    = 1024
TOP_K            = 3

# ── Test queries ──────────────────────────────────────────────────────────────

TEST_QUERIES = [
    {
        "label": "VIP Lead — Fintech, 150 employees, high budget",
        "query": "B2B fintech company 150 employees high budget CTO technical buyer cloud infrastructure",
        "expected_category": "positive or sector",
        "expected_min_similarity": 0.70,
    },
    {
        "label": "HOT Lead — HealthTech startup, 60 employees, medium budget",
        "query": "healthtech startup 60 employees Series A compliance patient data medium budget",
        "expected_category": "positive or sector",
        "expected_min_similarity": 0.65,
    },
    {
        "label": "COLD Lead — Unknown sector, 5 employees, no budget",
        "query": "small company 5 employees no budget non-technical buyer no cloud",
        "expected_category": "red_flag",
        "expected_min_similarity": 0.50,
    },
    {
        "label": "Mid-tier Lead — RetailTech, 200 employees, high budget seasonal",
        "query": "retail technology ecommerce company 200 employees high budget VP engineering microservices",
        "expected_category": "sector",
        "expected_min_similarity": 0.65,
    },
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def embed_query(text: str) -> list[float]:
    client = genai.Client(api_key=GEMINI_API_KEY)
    result = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
        config=genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=EMBEDDING_DIM,
        ),
    )
    return list(result.embeddings[0].values)


def run_query(index, query_text: str, top_k: int = TOP_K) -> list[dict]:
    vector = embed_query(query_text)
    results = index.query(
        vector=vector,
        top_k=top_k,
        include_metadata=True,
    )
    return results.matches


def format_match(match) -> dict:
    return {
        "id": match.id,
        "score": round(match.score, 4),
        "category": match.metadata.get("category", "unknown"),
        "sector": match.metadata.get("sector", "unknown"),
        "text_snippet": match.metadata.get("text", "")[:120] + "...",
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=== Sentinel RAG Test Script ===\n")

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(INDEX_NAME)

    stats = index.describe_index_stats()
    print(f"Index '{INDEX_NAME}' — {stats.total_vector_count} vectors indexed\n")

    if stats.total_vector_count == 0:
        print("ERROR: Index is empty. Run scripts/seed_pinecone.py first.")
        return

    all_passed = True

    for i, test in enumerate(TEST_QUERIES):
        print(f"[Test {i+1}/{len(TEST_QUERIES)}] {test['label']}")
        print(f"  Query: {test['query']}")

        matches = run_query(index, test["query"])

        if not matches:
            print("  FAIL: No results returned!\n")
            all_passed = False
            continue

        top_match = matches[0]
        top_score = round(top_match.score, 4)
        top_category = top_match.metadata.get("category", "unknown")

        print(f"  Top {len(matches)} results:")
        for match in matches:
            m = format_match(match)
            print(f"    [{m['score']:.4f}] [{m['category']:10}] {m['id']:10} — {m['text_snippet']}")

        passed = top_score >= test["expected_min_similarity"]
        status = "PASS" if passed else "FAIL"
        print(f"  {status}: top similarity={top_score:.4f} (expected ≥{test['expected_min_similarity']})\n")

        if not passed:
            all_passed = False

        time.sleep(0.5)  # avoid hammering the API

    print("=" * 50)
    if all_passed:
        print("All RAG tests PASSED. Index is semantically meaningful.")
    else:
        print("Some tests FAILED. Review profiles or re-seed the index.")
    print("=" * 50)


if __name__ == "__main__":
    main()
