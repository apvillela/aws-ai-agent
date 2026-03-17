# Sentinel — AI Lead Enrichment Pipeline

Multi-cloud serverless pipeline that scores and classifies sales leads using a LangChain ReAct agent with RAG (Retrieval-Augmented Generation).

```
POST /leads → API Gateway → Ingest Lambda (TypeScript)
  → SQS → AI Lambda (Python/LangChain)
    → RAG via Pinecone + Gemini Embeddings
    → Deterministic scoring
    → DynamoDB → Stream → BigQuery → Looker Studio
```

## Stack

| Layer | Tech |
|---|---|
| Ingest | TypeScript, Node.js 20, esbuild |
| AI Agent | Python 3.11, LangChain ReAct |
| LLM | Gemini 2.5 Flash |
| Embeddings | `gemini-embedding-001` (1024 dims) |
| Vector DB | Pinecone (serverless) |
| Queue | AWS SQS |
| Storage | DynamoDB |
| Analytics | BigQuery + Looker Studio |
| IaC | AWS SAM |

## How it works

1. **Ingest** — TypeScript Lambda validates the lead payload (company name, sector, size, budget, email) and queues it to SQS.
2. **AI Enrichment** — Python Lambda runs a LangChain ReAct agent that:
   - Uses `rag_tool` to search Pinecone for semantically similar ideal customer profiles
   - Uses `calculator_tool` to compute a deterministic score (0-100) with tier classification (VIP/HOT/COLD)
   - Red-flag profiles (bad leads) are penalized: sector score drops to 0
3. **Storage** — Enriched results are written to DynamoDB with score, tier, summary, and RAG context.
4. **Analytics** — DynamoDB Streams trigger a Lambda that loads rows into BigQuery for Looker Studio dashboards.

## Scoring breakdown

| Component | Points | Source |
|---|---|---|
| RAG similarity | 0–40 | Pinecone cosine similarity × 40 |
| Company size | 0–20 | employees / 10, capped at 200 |
| Sector match | 0–25 | similarity × 25 (0 if red_flag) |
| Budget signal | 0–15 | high=15, medium=10, low=5, unknown=0 |

**Tiers:** VIP ≥ 75 | HOT 50–74 | COLD < 50

## Quick start

### Prerequisites

- AWS CLI + SAM CLI configured
- Python 3.11 (pyenv recommended)
- Node.js 20+
- Pinecone account (free tier works)
- Google AI Studio API key (Gemini)
- GCP project with BigQuery enabled

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/sentinel.git
cd sentinel
npm install --prefix src/ingest
```

### 2. Set up secrets in AWS SSM

```bash
aws ssm put-parameter --name /sentinel/pinecone_api_key --value YOUR_KEY --type SecureString
aws ssm put-parameter --name /sentinel/gemini_api_key   --value YOUR_KEY --type SecureString
```

### 3. Seed the Pinecone index

```bash
export PINECONE_API_KEY=your-key
export GEMINI_API_KEY=your-key
python scripts/seed_pinecone.py
```

### 4. Deploy

```bash
sam build && sam deploy --guided
```

### 5. Test

```bash
# Post a lead
curl -X POST https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/prod/leads \
  -H "Content-Type: application/json" \
  -d '{"company_name":"FinCore","sector":"fintech","company_size":200,"budget_signal":"high","contact_email":"cto@fincore.io"}'

# Run local tests
export PINECONE_API_KEY=your-key GEMINI_API_KEY=your-key
python scripts/test_rag.py      # RAG similarity tests
python scripts/test_agent.py    # Full agent tests
```

### 6. GCP setup (BigQuery pipeline)

```bash
bash scripts/setup-gcp-infrastructure.sh
```

This creates the BigQuery dataset/table, service account, and stores the GCP key in AWS SSM.

## Project structure

```
├── src/
│   ├── ingest/
│   │   ├── handler.ts           # API Gateway → SQS
│   │   ├── package.json
│   │   └── tsconfig.json
│   ├── ai/
│   │   ├── agent.py             # LangChain ReAct agent (rag_tool + calculator_tool)
│   │   ├── lambda_handler.py    # SQS → agent → DynamoDB
│   │   └── requirements.txt
│   └── pipeline/
│       ├── stream_handler.py    # DynamoDB Stream → BigQuery
│       └── requirements.txt
├── scripts/
│   ├── seed_pinecone.py         # Seed 18 profile docs
│   ├── test_rag.py              # RAG test suite
│   ├── test_agent.py            # Agent test suite
│   └── setup-gcp-infrastructure.sh
├── template.yaml                # SAM (all AWS resources)
├── samconfig.toml
└── PRD.md                       # Full product spec
```

## License

MIT
