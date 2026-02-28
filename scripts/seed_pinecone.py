"""
One-time script to populate the Pinecone vector index with ideal customer profiles.

Usage:
    export PINECONE_API_KEY=<your-key>
    export GEMINI_API_KEY=<your-key>
    python scripts/seed_pinecone.py

The script:
1. Creates (or reuses) a Pinecone serverless index named 'sentinel-profiles'
2. Embeds each profile document using Google text-embedding-004 (dim=768)
3. Upserts all vectors with metadata
4. Verifies the index stats after upsert
"""

import os
import time
import json
from google import genai
from google.genai import types as genai_types
from pinecone import Pinecone, ServerlessSpec

# ── Config ────────────────────────────────────────────────────────────────────

PINECONE_API_KEY  = os.environ["PINECONE_API_KEY"]
GEMINI_API_KEY    = os.environ["GEMINI_API_KEY"]
INDEX_NAME        = os.environ.get("PINECONE_INDEX_NAME", "sentinel-profiles")
EMBEDDING_MODEL   = "gemini-embedding-001"
EMBEDDING_DIM     = 1024
CLOUD             = "aws"
REGION            = "us-east-1"

# ── Profile documents ─────────────────────────────────────────────────────────
# 5 positive / high-score profiles, 5 sector-specific profiles, 4 red-flag profiles
# These directly influence RAG similarity → scores computed by calculator_tool

PROFILES = [
    # ── Positive / high-score profiles ────────────────────────────────────────
    {
        "id": "pos-001",
        "text": (
            "Ideal customer profile A: B2B SaaS company operating in fintech, "
            "50-200 employees, monthly recurring revenue above R$500k, technical buyer "
            "(CTO or VP Engineering), sales cycle 30-45 days, already uses at least one "
            "cloud provider (AWS or GCP). High budget signal. Strong digital transformation "
            "maturity. Decision-making process is fast and data-driven."
        ),
        "category": "positive",
        "sector": "fintech",
        "size_range": "50-200",
        "budget": "high",
    },
    {
        "id": "pos-002",
        "text": (
            "Ideal customer profile B: Enterprise healthcare technology company, "
            "200-800 employees, compliance-driven environment (LGPD, HIPAA), "
            "CTO or Chief Digital Officer as decision maker, high budget signal, "
            "looking for AI-powered automation to reduce manual processes. "
            "Series C or beyond. Multiple cloud integrations already in place."
        ),
        "category": "positive",
        "sector": "healthtech",
        "size_range": "200-800",
        "budget": "high",
    },
    {
        "id": "pos-003",
        "text": (
            "Ideal customer profile C: Series B B2B SaaS startup with 100-300 employees, "
            "expansion stage, actively scaling sales and engineering teams. Technical buyer "
            "with VP Product or CTO involvement. Medium to high budget, willing to invest in "
            "tooling that accelerates growth. Cloud-native from inception. "
            "Sales cycle 45-60 days. Strong product-market fit already proven."
        ),
        "category": "positive",
        "sector": "saas",
        "size_range": "100-300",
        "budget": "medium",
    },
    {
        "id": "pos-004",
        "text": (
            "Ideal customer profile D: Logistics and supply-chain technology company, "
            "100-500 employees, undergoing digital transformation with a strong mandate "
            "from C-level. Budget signal high. CTO or VP Technology as sponsor. "
            "Uses data pipelines and real-time analytics. Open to cloud-first vendors. "
            "Interested in predictive analytics and AI-driven route optimization."
        ),
        "category": "positive",
        "sector": "logistics",
        "size_range": "100-500",
        "budget": "high",
    },
    {
        "id": "pos-005",
        "text": (
            "Ideal customer profile E: EdTech platform with 80-250 employees, "
            "growing subscription base, Series A or B funding, Chief Product Officer "
            "or CTO as decision maker. Medium to high budget. Data-driven culture, "
            "uses A/B testing and product analytics. Expanding into B2B corporate "
            "training market. Cloud infrastructure already established."
        ),
        "category": "positive",
        "sector": "edtech",
        "size_range": "80-250",
        "budget": "medium",
    },

    # ── Sector-specific profiles ───────────────────────────────────────────────
    {
        "id": "sec-001",
        "text": (
            "Sector profile — Fintech regulatory compliance: Small to mid-size fintech "
            "company, 20-100 employees, Series A funding, operating under heavy financial "
            "regulation (Banco Central, CVM). High urgency to automate compliance workflows. "
            "Technical founder or CTO buyer. Budget signal medium to high. "
            "Pain point: manual audit trails and KYC processes."
        ),
        "category": "sector",
        "sector": "fintech",
        "size_range": "20-100",
        "budget": "medium",
    },
    {
        "id": "sec-002",
        "text": (
            "Sector profile — Healthtech patient data: Healthtech startup focused on "
            "patient data management and clinical decision support. 30-80 employees, "
            "pre-Series B. Compliance-heavy environment (LGPD, CFM regulations). "
            "Decision maker is founder or CTO. Budget signal medium. "
            "Looking for secure, scalable cloud infrastructure with strong SLAs."
        ),
        "category": "sector",
        "sector": "healthtech",
        "size_range": "30-80",
        "budget": "medium",
    },
    {
        "id": "sec-003",
        "text": (
            "Sector profile — RetailTech e-commerce: Retail technology company powering "
            "mid-to-large e-commerce operations. 50-300 employees, high seasonal traffic "
            "spikes, growing engineering team. VP Engineering or CTO buyer. "
            "Budget signal high during Q4. Uses microservices and event-driven "
            "architecture. Pain point: scalability and real-time inventory management."
        ),
        "category": "sector",
        "sector": "retail",
        "size_range": "50-300",
        "budget": "high",
    },
    {
        "id": "sec-004",
        "text": (
            "Sector profile — LegalTech contract automation: LegalTech company "
            "automating contract lifecycle management for law firms and corporate legal teams. "
            "20-100 employees, professional services focus, budget-conscious but high ROI "
            "awareness. CTO or Head of Product buyer. Medium budget signal. "
            "Interested in NLP, document AI, and workflow automation."
        ),
        "category": "sector",
        "sector": "legaltech",
        "size_range": "20-100",
        "budget": "medium",
    },
    {
        "id": "sec-005",
        "text": (
            "Sector profile — HRTech workforce management: HR technology platform managing "
            "workforce scheduling, payroll, and benefits for enterprise clients. "
            "100-500 employees, serving companies with 1000+ end users. CTO or CPO buyer. "
            "High budget signal. Interested in AI for predictive attrition and "
            "automated onboarding workflows. Strong integration requirements (HRIS, ERP)."
        ),
        "category": "sector",
        "sector": "hrtech",
        "size_range": "100-500",
        "budget": "high",
    },

    # ── Red flag / low-score profiles ─────────────────────────────────────────
    {
        "id": "red-001",
        "text": (
            "Red flag profile: Company with fewer than 10 employees, no clear revenue "
            "model, non-technical buyer (operations or administrative manager). "
            "No budget allocated for technology purchases. Still in ideation or "
            "MVP phase with no paying customers. No cloud infrastructure. "
            "Decision cycle is undefined. High risk of deal stalling."
        ),
        "category": "red_flag",
        "sector": "unknown",
        "size_range": "1-10",
        "budget": "unknown",
    },
    {
        "id": "red-002",
        "text": (
            "Red flag profile: Traditional brick-and-mortar retail company with no "
            "digital transformation initiative. No e-commerce presence, no data strategy, "
            "non-technical buyer (store manager or owner). Budget signal low or unknown. "
            "Under 20 employees. Sector has no meaningful cloud adoption signal. "
            "Very long and unpredictable sales cycle."
        ),
        "category": "red_flag",
        "sector": "retail",
        "size_range": "1-20",
        "budget": "low",
    },
    {
        "id": "red-003",
        "text": (
            "Red flag profile: Early-stage startup with no product-market fit, "
            "in pivot stage. 5-15 employees, pre-seed or bootstrapped. "
            "Non-technical founder. No budget for third-party tooling. "
            "High uncertainty about direction. Unlikely to sign within 6 months. "
            "No existing cloud spend. Risk: ghost after initial contact."
        ),
        "category": "red_flag",
        "sector": "unknown",
        "size_range": "5-15",
        "budget": "unknown",
    },
    {
        "id": "red-004",
        "text": (
            "Red flag profile: Individual consultant or freelancer posing as a company. "
            "Single person operation, no organizational structure, no IT budget. "
            "Looking for free tools only. Not a business entity. No scalability path. "
            "Sector irrelevant. Contact is a personal email. "
            "No decision-making process beyond individual preference."
        ),
        "category": "red_flag",
        "sector": "unknown",
        "size_range": "1",
        "budget": "unknown",
    },

    # ── Additional nuanced profiles ────────────────────────────────────────────
    {
        "id": "nua-001",
        "text": (
            "Nuanced profile — High-growth startup: Hyper-growth B2B startup, 30-80 employees, "
            "Series A, technical leadership (CTO + VP Eng), high velocity hiring. "
            "Budget signal medium but growing. Interested in infrastructure that scales "
            "with them. Cloud-native. Responds well to ROI and time-to-value arguments. "
            "Sales cycle fast (15-30 days) when champion is identified."
        ),
        "category": "positive",
        "sector": "saas",
        "size_range": "30-80",
        "budget": "medium",
    },
    {
        "id": "nua-002",
        "text": (
            "Nuanced profile — Mid-market industrial tech: Industrial automation company "
            "starting IoT and Industry 4.0 adoption. 300-1000 employees, traditional "
            "engineering culture transitioning to software-defined. CDO or VP Digital "
            "as sponsor. Budget signal high. Long sales cycle (90+ days) but high ACV. "
            "Looking for proven cloud and AI vendors with enterprise support."
        ),
        "category": "positive",
        "sector": "industrial",
        "size_range": "300-1000",
        "budget": "high",
    },
    {
        "id": "nua-003",
        "text": (
            "Nuanced profile — Agritech and food supply: Agritech company digitizing "
            "supply chain from farm to retailer. 50-200 employees, Series A/B, "
            "strong government and institutional backing. Technical buyer (CTO or "
            "Data Lead). Medium budget signal. Interested in data pipelines, traceability "
            "and real-time monitoring. Cloud adoption is early but accelerating."
        ),
        "category": "positive",
        "sector": "agritech",
        "size_range": "50-200",
        "budget": "medium",
    },
    {
        "id": "nua-004",
        "text": (
            "Nuanced profile — InsurTech risk platform: Insurance technology startup "
            "building risk assessment and claims automation. 40-150 employees, Series A, "
            "actuarial and engineering teams combined. CTO buyer. High budget signal. "
            "Regulated environment requiring audit trails and explainability in AI decisions. "
            "Values deterministic, auditable scoring models over black-box approaches."
        ),
        "category": "positive",
        "sector": "insurtech",
        "size_range": "40-150",
        "budget": "high",
    },
]


# ── Embedding helper ──────────────────────────────────────────────────────────

def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts using Google text-embedding-004 (dim=768)."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    embeddings = []
    for i, text in enumerate(texts):
        result = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=genai_types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=EMBEDDING_DIM,
            ),
        )
        embeddings.append(list(result.embeddings[0].values))
        print(f"  Embedded [{i+1}/{len(texts)}]: {text[:60]}...")
        time.sleep(0.2)  # stay within free-tier rate limits
    return embeddings


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=== Sentinel Pinecone Seeding Script ===\n")

    # 1. Init Pinecone
    pc = Pinecone(api_key=PINECONE_API_KEY)

    # 2. Create index if it doesn't exist
    existing = [idx.name for idx in pc.list_indexes()]
    if INDEX_NAME not in existing:
        print(f"Creating index '{INDEX_NAME}' (dim={EMBEDDING_DIM}, metric=cosine)...")
        pc.create_index(
            name=INDEX_NAME,
            dimension=EMBEDDING_DIM,
            metric="cosine",
            spec=ServerlessSpec(cloud=CLOUD, region=REGION),
        )
        # Wait for index to be ready
        while not pc.describe_index(INDEX_NAME).status["ready"]:
            print("  Waiting for index to be ready...")
            time.sleep(3)
        print("  Index created and ready.\n")
    else:
        print(f"Index '{INDEX_NAME}' already exists — skipping creation.\n")

    index = pc.Index(INDEX_NAME)

    # 3. Embed all profiles
    print(f"Embedding {len(PROFILES)} profiles with {EMBEDDING_MODEL}...")
    texts = [p["text"] for p in PROFILES]
    vectors = embed_texts(texts)
    print(f"\nAll {len(vectors)} embeddings generated.\n")

    # 4. Build and upsert vectors
    upsert_payload = []
    for profile, vector in zip(PROFILES, vectors):
        upsert_payload.append({
            "id": profile["id"],
            "values": vector,
            "metadata": {
                "text": profile["text"],
                "category": profile["category"],
                "sector": profile["sector"],
                "size_range": profile["size_range"],
                "budget": profile["budget"],
            },
        })

    print(f"Upserting {len(upsert_payload)} vectors to index '{INDEX_NAME}'...")
    # Upsert in batches of 10
    batch_size = 10
    for i in range(0, len(upsert_payload), batch_size):
        batch = upsert_payload[i:i + batch_size]
        index.upsert(vectors=batch)
        print(f"  Upserted batch {i // batch_size + 1} ({len(batch)} vectors)")

    # 5. Wait briefly for index to reflect changes
    time.sleep(2)

    # 6. Verify stats
    stats = index.describe_index_stats()
    print(f"\n=== Index Stats ===")
    print(json.dumps({"total_vector_count": stats.total_vector_count}, indent=2))
    print("\nSeeding complete! Run scripts/test_rag.py to verify results.")


if __name__ == "__main__":
    main()
