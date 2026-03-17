# Projeto Sentinel — Task Progress

Tracks implementation progress across all steps defined in the PRD.
Mark items `[x]` as each feature/step is completed.

---

## Step 1 — AWS Base Infrastructure ✅

- [x] AWS CLI 2.33.30 installed at `/usr/local/bin/aws`
- [x] SAM CLI 1.154.0 installed via pip (pyenv 3.12.7)
- [x] Python 3.11.9 installed via pyenv, symlinked to `/usr/local/bin/python3.11`
- [x] esbuild added to `src/ingest/package.json` devDependencies
- [x] `src/ai/requirements.txt` — dependency conflict fixed
- [x] `src/ai/agent.py` — updated to new `google.genai` SDK
- [x] SSM parameters created in AWS us-east-1:
  - `/sentinel/pinecone_api_key` — SecureString ✅
  - `/sentinel/gemini_api_key` — SecureString ✅
  - `/sentinel/gcp_project_id` — String — `sentinel-pipeline-152541` ✅
  - `/sentinel/gcp_service_account_key` — SecureString — GCP JSON key ✅
- [x] `sam build && sam deploy` — **Deployed successfully**

**API Endpoint:** `https://wxw46s0pi2.execute-api.us-east-1.amazonaws.com/prod`

**Acceptance verified:**
- `POST /leads` returns 200 + lead_id ✅
- Invalid payload returns 400 ✅
- SQS message visible and consumed ✅

---

## Step 2 — Pinecone Index Setup ✅

- [x] Pinecone index `sentinel-profiles` — 1024 dimensions, cosine metric ✅
- [x] 18 profile documents seeded (5 positive, 5 sector, 4 red-flag, 4 nuanced)
- [x] `scripts/seed_pinecone.py` — updated to `google.genai` SDK + `gemini-embedding-001` (dim=1024)
- [x] `scripts/test_rag.py` — all 4 RAG tests PASSED

**Embedding model:** `gemini-embedding-001` with `output_dimensionality=1024`

**RAG test results:**
- VIP fintech lead → similarity 0.7478 ✅ (≥0.70)
- HOT healthtech lead → similarity 0.7875 ✅ (≥0.65)
- COLD red-flag lead → similarity 0.7264 ✅ (≥0.50, red_flag category)
- Mid-tier retailtech → similarity 0.7823 ✅ (≥0.65)

---

## Step 3 — AI Agent (local development) ✅

- [x] `src/ai/agent.py` — LangChain ReAct agent, `gemini-2.5-flash` chat model
- [x] `rag_tool` — uses `gemini-embedding-001` with 1024-dim output
- [x] `calculator_tool` — deterministic scoring with red_flag category penalty
  - If `top_category == "red_flag"`: `sector_score = 0` (prevents false high scores)
- [x] `scripts/test_agent.py` — all 3 tests PASSED

**Agent test results:**
- VIP (FinCore, fintech, 200 employees, high budget): score 84.7 ✅ (≥75)
- HOT (MedFlow, healthtech, 60 employees, medium budget): score 65.3 ✅ (50–74)
- COLD (Sunrise General Shop, unknown, 5 employees, unknown budget): score 28.2 ✅ (≤40)

---

## Step 4 — AI Lambda + SQS Integration ✅

- [x] `src/ai/lambda_handler.py` — Lambda wrapper (SQS → agent → DynamoDB)
- [x] SAM deployed — AI Lambda active with SQS trigger

**Acceptance verified:**
- Posted lead → DynamoDB record with `status: "enriched"` within 90s ✅
- `tier: "VIP"`, `score: "84.1"`, non-null `summary`, `rag_similarity` ✅

---

## Step 5 — GCP Data Pipeline ✅

- [x] GCP project: `sentinel-pipeline-152541` ✅
- [x] BigQuery API enabled ✅
- [x] BigQuery dataset `sentinel`, table `leads` created with correct schema ✅
- [x] GCP service account `sentinel-bq-writer` with BigQuery Data Editor + Job User roles ✅
- [x] GCP service account JSON key → AWS SSM `/sentinel/gcp_service_account_key` ✅
- [x] `src/pipeline/stream_handler.py` — fixed: uses `load_table_from_json` (batch load, free tier compatible) instead of streaming inserts ✅
- [x] SAM deployed with real GCP project ID ✅

**BigQuery table contents (9 rows):**
```
CloudHR          | hrtech     | 85.9 | VIP
LegalAI Corp     | legaltech  | 65.0 | HOT
Mom Shop         | unknown    | 28.2 | COLD
MedTech Pro      | healthtech | 70.0 | HOT
FinBank AI       | fintech    | 79.7 | VIP
Corner Bakery    | unknown    | 45.1 | COLD
DataCore Systems | saas       | 77.7 | VIP
HealthStream AI  | healthtech | 77.9 | VIP
TechVentures     | fintech    | 84.1 | VIP
```

**Acceptance:** DynamoDB insert → BigQuery row within 120s ✅

---

## Step 6 — Looker Studio Dashboard ⏳ (manual)

**Data is ready in BigQuery.** Connect Looker Studio manually:

1. Go to https://lookerstudio.google.com
2. Sign in with `alexokivillela@gmail.com`
3. Click **Create → Report**
4. **Add data → BigQuery → My Projects → sentinel-pipeline-152541 → sentinel → leads**
5. Click "Add to report"

Create 3 charts:

**Chart 1 — Pie chart (lead distribution by tier)**
- Insert → Pie chart
- Dimension: `tier`
- Metric: `Record Count`

**Chart 2 — Bar chart (average score by sector)**
- Insert → Bar chart
- Dimension: `sector`
- Metric: `AVG(score)`

**Chart 3 — Line chart (lead volume over time)**
- Insert → Time series chart
- Dimension: `processed_at` (set granularity to "Day")
- Metric: `Record Count`

**Acceptance:** All 3 charts render with real data.

---

## Testing Checklist (Final)

- [x] `POST /leads` returns 200 and a `lead_id`
- [x] Invalid payload returns 400 with error message
- [x] SQS message appears within 5s of posting a lead
- [x] DynamoDB record appears within 60s with `status: "enriched"`
- [x] DynamoDB record contains non-null `score`, `tier`, `summary`
- [x] RAG results are semantically relevant (not random)
- [x] VIP lead (fintech, 200 employees, high budget) scores ≥ 75
- [x] COLD lead (unknown sector, 5 employees, unknown budget) scores ≤ 40
- [x] BigQuery row appears within 120s of DynamoDB write
- [ ] Looker Studio charts render with real data (manual step)
- [x] Agent trace shows both tools called in correct order
