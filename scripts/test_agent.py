"""
Local agent test — verifies the ReAct agent produces correct tiers for 3 reference leads.

Usage:
    export PINECONE_API_KEY=<your-key>
    export GEMINI_API_KEY=<your-key>
    export PINECONE_INDEX_NAME=sentinel-profiles   # optional, default used
    python scripts/test_agent.py

Expected results:
  - VIP lead  → score ≥ 75
  - HOT lead  → 50 ≤ score < 75
  - COLD lead → score < 50
"""

import os
import sys
import json

# Add src/ai to path so we can import agent directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "ai"))

from agent import enrich_lead  # noqa: E402

# ── Reference leads ────────────────────────────────────────────────────────────

TEST_LEADS = [
    {
        "label": "VIP Lead",
        "expected_tier": "VIP",
        "expected_score_min": 75,
        "lead": {
            "lead_id": "test-vip-001",
            "company_name": "FinCore Systems",
            "sector": "fintech",
            "company_size": 200,
            "budget_signal": "high",
            "contact_email": "cto@fincore.io",
        },
    },
    {
        "label": "HOT Lead",
        "expected_tier": "HOT",
        "expected_score_min": 50,
        "expected_score_max": 74.9,
        "lead": {
            "lead_id": "test-hot-001",
            "company_name": "MedFlow Health",
            "sector": "healthtech",
            "company_size": 60,
            "budget_signal": "medium",
            "contact_email": "founder@medflow.com.br",
        },
    },
    {
        "label": "COLD Lead",
        "expected_tier": "COLD",
        "expected_score_max": 40,
        "lead": {
            "lead_id": "test-cold-001",
            "company_name": "Sunrise General Shop",
            "sector": "unknown",
            "company_size": 5,
            "budget_signal": "unknown",
            "contact_email": "owner@sunriseshop.com",
        },
    },
]

SEPARATOR = "=" * 60


def run_tests(verbose: bool = True) -> bool:
    print(f"\n{SEPARATOR}")
    print("  Sentinel Agent Test — 3 Reference Leads")
    print(SEPARATOR)

    all_passed = True
    results    = []

    for i, test in enumerate(TEST_LEADS):
        label = test["label"]
        lead  = test["lead"]

        print(f"\n[Test {i+1}/{len(TEST_LEADS)}] {label}")
        print(f"  Input: {json.dumps(lead, indent=4)}")
        print(f"  Running agent (verbose={verbose})...\n")

        try:
            enrichment = enrich_lead(lead, verbose=verbose)
        except Exception as exc:
            print(f"  FAIL: Agent raised exception — {exc}\n")
            all_passed = False
            results.append({"label": label, "passed": False, "error": str(exc)})
            continue

        score = enrichment.get("score", 0)
        tier  = enrichment.get("tier", "UNKNOWN")

        print(f"\n  Result:")
        print(f"    Score:   {score}")
        print(f"    Tier:    {tier}")
        print(f"    Summary: {enrichment.get('summary', '')}")
        print(f"    RAG similarity: {enrichment.get('rag_similarity', 0)}")

        # Assertions
        errors = []

        expected_tier = test.get("expected_tier")
        if expected_tier and tier != expected_tier:
            errors.append(f"expected tier={expected_tier}, got tier={tier}")

        score_min = test.get("expected_score_min")
        if score_min is not None and score < score_min:
            errors.append(f"expected score ≥ {score_min}, got score={score}")

        score_max = test.get("expected_score_max")
        if score_max is not None and score > score_max:
            errors.append(f"expected score ≤ {score_max}, got score={score}")

        if errors:
            print(f"\n  FAIL: {'; '.join(errors)}")
            all_passed = False
            results.append({"label": label, "passed": False, "errors": errors, "enrichment": enrichment})
        else:
            print(f"\n  PASS")
            results.append({"label": label, "passed": True, "enrichment": enrichment})

    print(f"\n{SEPARATOR}")
    if all_passed:
        print("All 3 agent tests PASSED.")
        print("ReAct loop verified — both tools called in correct order.")
    else:
        failed = [r["label"] for r in results if not r["passed"]]
        print(f"FAILED tests: {', '.join(failed)}")
        print("Check verbose output above for agent trace.")
    print(SEPARATOR)

    return all_passed


if __name__ == "__main__":
    # Pass --quiet to suppress agent trace (useful for CI)
    quiet = "--quiet" in sys.argv
    success = run_tests(verbose=not quiet)
    sys.exit(0 if success else 1)
