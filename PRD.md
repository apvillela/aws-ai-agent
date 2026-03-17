# PRD — Projeto Sentinel
## Serverless Lead Enrichment & Analytics with AI Agent

---

## 1. Purpose of This Document

This PRD is the single source of truth for building Projeto Sentinel. It is intended to be fed to an AI assistant (Claude) to guide implementation. Every architectural decision here was made deliberately — do not suggest alternatives unless there is a concrete technical blocker.

---

## 2. Project Overview

Projeto Sentinel is a multi-cloud serverless pipeline that:
1. Receives a lead payload via HTTP
2. Asynchronously enriches it using an AI agent with real tools (RAG + scoring)
3. Stores the enriched result
4. Streams it to an analytics dashboard

The project is a **proof of concept / portfolio piece**. It must be fully functional, deployable on free/low-cost tiers, and defensible in a technical interview.

---

## 3. Goals

- Build a working async serverless pipeline across AWS and GCP
- Implement a LangChain ReAct agent with two deterministic tools
- Demonstrate RAG with a real vector database (Pinecone)
- Produce a live analytics dashboard (Looker Studio → BigQuery)
- Learn: AWS SAM, LangChain tool use, RAG, async pipelines, multi-cloud data flow

---

## 4. Non-Goals

- This is not a production system — no auth, no multi-tenancy, no SLAs
- No Step Functions — orchestration complexity is not needed at this scale
- No SNS — notifications are out of scope for now
- No multi-agent setup — a single well-equipped agent is the target

---

## 5. Tech Stack

| Layer | Technology |
|---|---|
| Ingest Lambda | TypeScript (Node.js 20) |
| AI Lambda | Python 3.11 |
| Queue | Amazon SQS (Standard) |
| Storage | Amazon DynamoDB |
| Orchestration | AWS SAM (CloudFormation) |
| AI Framework | LangChain (Python) |
| LLM | Gemini API (gemini-1.5-flash — free tier) |
| Vector DB | Pinecone (free tier, serverless index) |
| Analytics DB | Google BigQuery (free tier) |
| Dashboard | Looker Studio (free, connected to BigQuery) |
| Data Pipeline | DynamoDB Streams → Lambda (Python) → BigQuery |

---

## 6. Architecture

```
[POST /leads]
      │
 API Gateway
      │
 Lambda — Ingest (TypeScript)
      │   validates payload, publishes to SQS
      ▼
    SQS
      │   triggers on new message
      ▼
 Lambda — AI Enrichment (Python)
      │
      │   LangChain ReAct Agent
      │   ├── Tool 1: RAG Tool (Pinecone lookup)
      │   └── Tool 2: Calculator Tool (deterministic scoring)
      │
      ▼
  DynamoDB
      │
 DynamoDB Stream
      │
 Lambda — Stream Processor (Python)
      │
      ▼
  BigQuery
      │
 Looker Studio Dashboard
```

---

## 7. Data Model

### 7.1 Input Payload (POST /leads)

```json
{
  "company_name": "Acme Corp",
  "sector": "fintech",
  "company_size": 150,
  "budget_signal": "high",
  "contact_email": "cto@acme.com"
}
```

Field validation rules:
- `company_name`: required, string
- `sector`: required, string (e.g. fintech, healthtech, saas, retail, logistics)
- `company_size`: required, integer > 0
- `budget_signal`: required, enum: `"high" | "medium" | "low" | "unknown"`
- `contact_email`: required, valid email format

### 7.2 DynamoDB Record (after enrichment)

```json
{
  "lead_id": "uuid-v4",
  "company_name": "Acme Corp",
  "sector": "fintech",
  "company_size": 150,
  "budget_signal": "high",
  "contact_email": "cto@acme.com",
  "score": 81.2,
  "tier": "VIP",
  "summary": "Strong match. Fintech sector aligns with ideal profile. Company size and high budget signal indicate readiness.",
  "rag_similarity": 0.87,
  "rag_context_snippet": "Ideal customer: B2B SaaS fintech, 50-200 employees...",
  "processed_at": "2025-01-01T00:00:00Z",
  "status": "enriched"
}
```

Tier logic: `VIP` if score ≥ 75, `HOT` if score ≥ 50, `COLD` otherwise.

### 7.3 BigQuery Schema

Table: `sentinel.leads`

| Field | Type |
|---|---|
| lead_id | STRING |
| company_name | STRING |
| sector | STRING |
| company_size | INTEGER |
| budget_signal | STRING |
| score | FLOAT |
| tier | STRING |
| rag_similarity | FLOAT |
| processed_at | TIMESTAMP |

---

## 8. The AI Agent (Core of the Project)

### 8.1 Framework

LangChain with a ReAct agent (`create_react_agent` or `AgentExecutor`). The agent receives the lead payload as a string and must decide which tools to call and in what order.

### 8.2 Tool 1 — RAG Tool

**Purpose:** Query Pinecone for the most similar ideal customer profiles given the lead's attributes.

**Input:** a query string constructed from the lead (e.g. `"B2B fintech company, 150 employees, high budget"`)

**Output:** top-3 matching document snippets with similarity scores

**Implementation notes:**
- Use `langchain_pinecone` or direct Pinecone Python SDK
- Embed the query using Google's `text-embedding-004` model (free) or `text-embedding-ada-002` (OpenAI) — choose based on what's free
- The tool must return a structured string the agent can read, including the top similarity score (this is passed to the Calculator Tool)

**Pinecone index content (seed with these 15-20 documents):**

Each document should be a paragraph describing an ideal customer profile. Examples:
- "Ideal customer profile A: B2B SaaS company in fintech, 50-200 employees, monthly recurring revenue R$500k+, technical buyer (CTO or VP Eng), sales cycle 30-45 days, already uses at least one cloud provider."
- "Ideal customer profile B: healthtech startup, 20-80 employees, pre-Series B, compliance-heavy environment, budget signal medium to high, decision maker is founder or CTO."
- "Red flag profile: companies under 10 employees, no clear budget, non-technical buyer, sector with no digital transformation signal (e.g. traditional brick-and-mortar retail)."

Write at least 5 positive profiles, 5 sector-specific profiles, and 3-4 red flag / low-score profiles so the RAG has meaningful variance.

### 8.3 Tool 2 — Calculator Tool

**Purpose:** Compute a deterministic numeric score. This is NOT an LLM call — it is a pure Python function exposed as a LangChain tool.

**Input (structured, parsed from agent's tool call):**
```python
{
  "company_size": int,
  "sector_match": float,      # rag_similarity from Tool 1 (0.0–1.0)
  "budget_signal": str,       # "high" | "medium" | "low" | "unknown"
  "rag_similarity": float     # same as sector_match, used for base score
}
```

**Scoring logic:**
```python
def calculate_score(company_size: int, sector_match: float,
                    budget_signal: str, rag_similarity: float) -> dict:
    base        = rag_similarity * 40          # 0–40 pts: profile similarity
    size_score  = min(company_size / 10, 20)   # 0–20 pts: company size
    sector_score = sector_match * 25           # 0–25 pts: sector match
    budget_map  = {"high": 15, "medium": 10, "low": 5, "unknown": 0}
    budget_score = budget_map.get(budget_signal, 0)  # 0–15 pts

    total = base + size_score + sector_score + budget_score
    tier  = "VIP" if total >= 75 else "HOT" if total >= 50 else "COLD"
    return {"score": round(total, 1), "tier": tier}
```

**Why deterministic:** The LLM should never compute the score directly — it hallucinates numbers. The Calculator Tool ensures the score is always reproducible and auditable.

### 8.4 Agent System Prompt

```
You are a lead scoring agent. Your job is to evaluate a potential customer lead and produce a score and summary.

You have two tools:
1. rag_tool: searches a knowledge base of ideal customer profiles. Use it first.
2. calculator_tool: computes a numeric score based on lead data and RAG results. Use it second.

Always use both tools in order. Do not guess the score — use the calculator_tool.
After using both tools, write a 2-3 sentence summary explaining the score.

Return your final answer as JSON:
{
  "score": <float>,
  "tier": <"VIP"|"HOT"|"COLD">,
  "summary": <string>,
  "rag_similarity": <float>,
  "rag_context_snippet": <string — first 200 chars of top RAG result>
}
```

### 8.5 Expected Agent ReAct Loop

```
Thought: I need to find similar profiles for this fintech lead with 150 employees.
Action: rag_tool
Action Input: "B2B fintech company 150 employees high budget"
Observation: [doc1, similarity: 0.87] "Ideal customer: B2B SaaS fintech, 50-200 employees..."
Thought: I have the RAG context. Now I'll calculate the score.
Action: calculator_tool
Action Input: {"company_size": 150, "sector_match": 0.87, "budget_signal": "high", "rag_similarity": 0.87}
Observation: {"score": 81.2, "tier": "VIP"}
Thought: Score is 81.2, VIP tier. I'll write the summary now.
Final Answer: {"score": 81.2, "tier": "VIP", "summary": "...", ...}
```

---

## 9. Implementation Steps

Follow these steps in strict order. Do not move to the next step until the current one is working and tested.

### Step 1 — AWS Base Infrastructure

**Goal:** API Gateway → Lambda (TypeScript) → SQS working end-to-end.

Files to create:
- `template.yaml` (AWS SAM) defining: DynamoDB table, SQS queue, Ingest Lambda, API Gateway
- `src/ingest/handler.ts` — validates payload, generates `lead_id` (uuid), publishes to SQS

Test: `curl -X POST <api-url>/leads -d '<payload>'` → message appears in SQS console.

DynamoDB table config:
- Table name: `sentinel-leads`
- Partition key: `lead_id` (String)
- Billing: PAY_PER_REQUEST

SQS queue config:
- Queue name: `sentinel-leads-queue`
- Visibility timeout: 300s (enough for AI processing)
- Dead-letter queue: `sentinel-leads-dlq` (maxReceiveCount: 3)

### Step 2 — Pinecone Index Setup

**Goal:** Pinecone index populated and queryable locally.

Tasks:
1. Create a Pinecone account (free tier)
2. Create a serverless index named `sentinel-profiles` (dimension: 768 for Google embeddings or 1536 for OpenAI)
3. Write a one-time script `scripts/seed_pinecone.py` that embeds and upserts 15-20 profile documents
4. Write a test script `scripts/test_rag.py` that queries the index with a sample lead and prints results

Do not proceed until RAG results look semantically meaningful.

### Step 3 — AI Agent (local development)

**Goal:** Agent runs correctly on a hardcoded lead before being deployed to Lambda.

File: `src/ai/agent.py`

Steps:
1. Implement `rag_tool` as a LangChain `Tool` or `@tool` function
2. Implement `calculator_tool` as a LangChain `Tool` wrapping the `calculate_score` function
3. Create the ReAct agent with the system prompt from section 8.4
4. Test with 3 hardcoded leads covering all three tiers (VIP, HOT, COLD)
5. Print the full agent trace (set `verbose=True`) and confirm the ReAct loop matches section 8.5

Do not deploy to Lambda until local tests pass consistently.

### Step 4 — AI Lambda + SQS Integration

**Goal:** SQS message triggers AI Lambda, result saved to DynamoDB.

File: `src/ai/lambda_handler.py`

Steps:
1. Wrap `agent.py` in a Lambda handler that reads from SQS event
2. Parse the lead from the SQS message body
3. Run the agent
4. Parse the agent's JSON final answer
5. Write the full enriched record to DynamoDB

Add the Lambda + SQS trigger to `template.yaml`.

Test: post a lead via API → wait ~30s → check DynamoDB console for enriched record.

### Step 5 — GCP Data Pipeline

**Goal:** DynamoDB Stream → Lambda → BigQuery working.

Steps:
1. Create GCP project, enable BigQuery API
2. Create dataset `sentinel`, table `leads` with schema from section 7.3
3. Create a service account with BigQuery Data Editor role, download JSON key
4. Store the key in AWS SSM Parameter Store (SecureString)
5. Write `src/pipeline/stream_handler.py` — reads DynamoDB Stream NEW_IMAGE events, inserts to BigQuery via `google-cloud-bigquery` Python SDK
6. Add the Lambda + DynamoDB Stream trigger to `template.yaml`

Test: insert a record manually into DynamoDB → verify it appears in BigQuery within 60s.

### Step 6 — Dashboard

**Goal:** Looker Studio dashboard connected to BigQuery with 3 charts.

Charts:
1. **Pie chart** — distribution of leads by tier (VIP / HOT / COLD)
2. **Bar chart** — average score by sector
3. **Line chart** — lead volume over time (processed_at by day)

Steps:
1. Go to lookerstudio.google.com
2. Create new report → Add data → BigQuery → select `sentinel.leads`
3. Create the 3 charts above

---

## 10. Environment Variables

| Variable | Used by | Description |
|---|---|---|
| `SQS_QUEUE_URL` | Ingest Lambda | SQS queue URL |
| `DYNAMODB_TABLE_NAME` | AI Lambda | DynamoDB table name |
| `PINECONE_API_KEY` | AI Lambda | Pinecone API key |
| `PINECONE_INDEX_NAME` | AI Lambda | Pinecone index name |
| `GEMINI_API_KEY` | AI Lambda | Google Gemini API key |
| `GCP_PROJECT_ID` | Stream Lambda | GCP project ID |
| `BIGQUERY_DATASET` | Stream Lambda | BigQuery dataset name |
| `BIGQUERY_TABLE` | Stream Lambda | BigQuery table name |
| `GCP_SERVICE_ACCOUNT_KEY_PARAM` | Stream Lambda | SSM param name for GCP JSON key |

Store all secrets in AWS SSM Parameter Store. Reference them in `template.yaml` using `{{resolve:ssm:...}}`.

---

## 11. Project Structure

```
sentinel/
├── template.yaml                  # AWS SAM — all infrastructure
├── samconfig.toml                 # SAM deploy config
├── package.json                   # root (workspaces if needed)
│
├── src/
│   ├── ingest/
│   │   ├── handler.ts             # Ingest Lambda
│   │   ├── package.json
│   │   └── tsconfig.json
│   │
│   ├── ai/
│   │   ├── agent.py               # LangChain agent + tools
│   │   ├── lambda_handler.py      # Lambda wrapper
│   │   └── requirements.txt
│   │
│   └── pipeline/
│       ├── stream_handler.py      # DynamoDB Stream → BigQuery
│       └── requirements.txt
│
└── scripts/
    ├── seed_pinecone.py           # One-time: populate vector index
    ├── test_rag.py                # Local RAG test
    └── test_agent.py              # Local agent test with sample leads
```

---

## 12. Testing Checklist

Before considering the project done, verify each item:

- [ ] `POST /leads` returns 200 and a `lead_id`
- [ ] Invalid payload (missing field) returns 400 with error message
- [ ] SQS message appears within 5s of posting a lead
- [ ] DynamoDB record appears within 60s with `status: "enriched"`
- [ ] DynamoDB record contains non-null `score`, `tier`, `summary`
- [ ] RAG results are semantically relevant (not random)
- [ ] VIP lead (fintech, 200 employees, high budget) scores ≥ 75
- [ ] COLD lead (unknown sector, 5 employees, unknown budget) scores ≤ 40
- [ ] BigQuery row appears within 120s of DynamoDB write
- [ ] Looker Studio charts render with real data
- [ ] Agent trace shows both tools were called in correct order

---

## 13. Key Interview Talking Points

When presenting this project, be ready to answer:

**On architecture:**
- Why SQS between ingest and enrichment? Decouples the two lambdas — if the AI call fails or times out, the message stays in the queue and retries. The ingest Lambda always returns fast.
- Why not Step Functions? Overkill for a linear two-step flow. Step Functions add value when you have branching, parallel steps, or human-in-the-loop. Adding it here would be complexity theatre.

**On the AI layer:**
- Why a single agent instead of multi-agent? Easier to reason about, debug, and test. Multi-agent makes sense when agents need to work in parallel or when the task scope genuinely requires specialization.
- Why a deterministic Calculator Tool instead of asking the LLM to score? LLMs are inconsistent with arithmetic and numeric reasoning. A deterministic function ensures the score is reproducible, auditable, and explainable.
- How does RAG affect the score? Change the Pinecone documents and observe the score change. The RAG similarity directly weights 40% of the final score.

**On multi-cloud:**
- Why AWS for transactional, GCP for analytics? This mirrors how many real companies are structured — they use AWS for operational workloads and GCP/BigQuery for data warehousing because BigQuery's pricing model and SQL analytics capabilities are superior for that use case.
