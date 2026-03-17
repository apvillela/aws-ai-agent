# Projeto Sentinel — Claude Reference

Multi-cloud serverless lead enrichment pipeline. Portfolio piece, defensible in a technical interview.

## Stack

| Layer | Technology |
|---|---|
| Ingest Lambda | TypeScript (Node.js 20, esbuild) |
| AI Lambda | Python 3.11 (LangChain ReAct) |
| Queue | AWS SQS |
| LLM | Gemini 2.5 Flash (`gemini-2.5-flash`) |
| Embeddings | `gemini-embedding-001` (1024 dims) |
| Vector DB | Pinecone — index `sentinel-profiles` |
| Storage | DynamoDB |
| Streaming | DynamoDB Streams → BigQuery |
| Dashboard | Looker Studio |
| IaC | AWS SAM (`template.yaml`) |

## Architecture

```
POST /leads (API Gateway)
  → Ingest Lambda (TypeScript)
    → validates payload
    → writes to DynamoDB
    → sends to SQS
      → AI Lambda (Python, LangChain ReAct)
        → rag_tool: Pinecone similarity search
        → calculator_tool: deterministic scoring
        → if top_category == "red_flag": sector_score = 0
        → writes enriched result to DynamoDB
          → DynamoDB Streams → BigQuery → Looker Studio
```

## API Endpoint
```
https://wxw46s0pi2.execute-api.us-east-1.amazonaws.com/prod
POST /leads
```

## Environment Variables (SSM, us-east-1)

| Parameter | Type | Value |
|---|---|---|
| `/sentinel/pinecone_api_key` | SecureString | Pinecone key |
| `/sentinel/gemini_api_key` | SecureString | Gemini key |
| `/sentinel/gcp_project_id` | String | `sentinel-pipeline-152541` |
| `/sentinel/gcp_service_account_key` | SecureString | GCP JSON key |

Local overrides in `env.local.json`.

## Key Files

| File | Purpose |
|---|---|
| `src/ingest/` | TypeScript Lambda — receives leads, queues enrichment |
| `src/ai/agent.py` | Python Lambda — LangChain ReAct agent |
| `src/ai/requirements.txt` | Python deps (google.genai SDK) |
| `template.yaml` | SAM template — all AWS resources |
| `samconfig.toml` | SAM deploy config |
| `scripts/seed_pinecone.py` | Seeds 18 profile docs into Pinecone |
| `scripts/test_rag.py` | RAG similarity tests (4 cases) |
| `scripts/test_agent.py` | End-to-end agent tests (3 cases) |
| `PRD.md` | Full product requirements |
| `TaskProgress.md` | Step-by-step completion tracker |
| `NOOB_GUIDE.md` | AWS setup guide (CLI, SAM, pyenv) |

## Common Tasks

| Task | Command |
|---|---|
| Build | `sam build` |
| Deploy | `sam deploy` |
| Test RAG | `python scripts/test_rag.py` |
| Test agent | `python scripts/test_agent.py` |
| Seed Pinecone | `python scripts/seed_pinecone.py` |
| Hit endpoint | `curl -X POST https://wxw46s0pi2.execute-api.us-east-1.amazonaws.com/prod/leads -H "Content-Type: application/json" -d '{"company":"Test","sector":"fintech","employees":50}'` |

## Scoring Logic (calculator_tool)
- If `top_category == "red_flag"`: `sector_score = 0` (prevents false positives)
- VIP threshold: ≥75 | HOT: 50–74 | COLD: ≤40

## Status
All 5 steps complete and verified. See `TaskProgress.md` for details.
