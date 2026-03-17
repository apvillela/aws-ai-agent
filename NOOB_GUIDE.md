# Noob Guide — Como rodar o Projeto Sentinel do zero

Este guia assume que você é um novo desenvolvedor que clonou o repositório
e quer enviar uma requisição e ver o lead aparecer no BigQuery.

---

## O que o projeto faz (em 30 segundos)

Você manda um JSON com dados de uma empresa → o sistema classifica o lead
com IA (VIP / HOT / COLD) → salva no banco → envia para o BigQuery.

```
POST /leads  →  SQS  →  IA (LangChain + Gemini + Pinecone)  →  DynamoDB  →  BigQuery
```

---

## Pré-requisitos — o que você precisa ter instalado

### 1. Node.js 20+
```bash
node --version   # deve mostrar v20.x.x ou superior
```
Se não tiver: https://nodejs.org/en/download

### 2. Python 3.11
```bash
python3.11 --version   # deve mostrar Python 3.11.x
```
Se não tiver (via pyenv):
```bash
pyenv install 3.11.9
pyenv global 3.11.9
```

### 3. AWS CLI
```bash
aws --version   # deve mostrar aws-cli/2.x.x
```
Se não tiver: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html

### 4. SAM CLI
```bash
sam --version   # deve mostrar SAM CLI, version 1.x.x
```
Se não tiver:
```bash
pip install aws-sam-cli
```

### 5. Conta AWS configurada
```bash
aws configure
# AWS Access Key ID: <sua key>
# AWS Secret Access Key: <sua secret>
# Default region: us-east-1
# Default output format: json
```
Para criar as chaves: AWS Console → IAM → Users → seu usuário → Security credentials → Create access key

---

## Passo 1 — Clonar e configurar variáveis de ambiente

```bash
git clone <url-do-repo>
cd aws-ai-agent
cp .env.example .env
```

Abra o `.env` e preencha os valores reais:

```
PINECONE_API_KEY=pcsk_...       # chave da sua conta Pinecone
GEMINI_API_KEY=AIzaSy...        # chave da Google AI Studio
```

### Onde conseguir cada chave

**Pinecone (vector database):**
1. Crie conta em https://app.pinecone.io
2. Menu lateral → API Keys → Create API Key
3. Copie a chave que começa com `pcsk_`

**Gemini (LLM + embeddings):**
1. Acesse https://aistudio.google.com/apikey
2. Clique em "Create API Key"
3. Copie a chave que começa com `AIzaSy`

---

## Passo 2 — Criar os parâmetros secretos na AWS (SSM)

Estes comandos guardam suas chaves de forma segura na AWS,
sem precisar colocá-las diretamente no código.

```bash
# Substitua pelos seus valores reais do .env
export PINECONE_API_KEY="pcsk_SEU_VALOR_AQUI"
export GEMINI_API_KEY="AIzaSy_SEU_VALOR_AQUI"

aws ssm put-parameter \
  --name /sentinel/pinecone_api_key \
  --value "$PINECONE_API_KEY" \
  --type SecureString \
  --region us-east-1

aws ssm put-parameter \
  --name /sentinel/gemini_api_key \
  --value "$GEMINI_API_KEY" \
  --type SecureString \
  --region us-east-1

# Placeholder para o GCP (será atualizado no Passo 5)
aws ssm put-parameter \
  --name /sentinel/gcp_project_id \
  --value "placeholder" \
  --type String \
  --region us-east-1
```

Para verificar que foram criados:
```bash
aws ssm get-parameters \
  --names /sentinel/pinecone_api_key /sentinel/gemini_api_key /sentinel/gcp_project_id \
  --region us-east-1 \
  --query "Parameters[*].{Name:Name,Type:Type}" \
  --output table
```

---

## Passo 3 — Popular o índice Pinecone (uma vez só)

Este passo cria o índice com 18 perfis de clientes ideais que o agente
usa para comparar com os leads.

```bash
# Instalar dependências locais para o script
pip install "google-genai>=1.0" pinecone

# Exportar as chaves
export PINECONE_API_KEY=$(grep "^PINECONE_API_KEY" .env | cut -d= -f2)
export GEMINI_API_KEY=$(grep "^GEMINI_API_KEY" .env | cut -d= -f2)

# Rodar o script de seeding (~20s)
python scripts/seed_pinecone.py
```

Você deve ver algo como:
```
=== Sentinel Pinecone Seeding Script ===
Embedding 18 profiles with gemini-embedding-001...
  Embedded [1/18]: Ideal customer profile A...
  ...
=== Index Stats ===
{"total_vector_count": 18}
Seeding complete!
```

Para validar que o índice está semântico:
```bash
python scripts/test_rag.py
# Deve mostrar: All RAG tests PASSED
```

---

## Passo 4 — Fazer o build e deploy na AWS

```bash
cd aws-ai-agent

# Build (compila TypeScript + empacota Python)
sam build

# Deploy (cria todos os recursos na AWS)
sam deploy
# Quando perguntar "Deploy this changeset? [y/N]" → digite y
```

O deploy leva cerca de 2-3 minutos. No final você verá:

```
CloudFormation outputs from deployed stack
--------------------------------------------------
Key         ApiEndpoint
Value       https://xxxxxxxxxx.execute-api.us-east-1.amazonaws.com/prod

Key         LeadsQueueUrl
Value       https://sqs.us-east-1.amazonaws.com/xxxx/sentinel-leads-queue

Key         DynamoDBTableName
Value       sentinel-leads
```

**Guarde a URL do ApiEndpoint — você vai usar no Passo 6.**

---

## Passo 5 — Configurar o GCP (BigQuery)

Este passo conecta o pipeline ao BigQuery para análise de dados.

### 5a. Instalar o gcloud CLI
```bash
# Linux/macOS
curl -O https://dl.google.com/dl/cloudsdk/channels/rapid/downloads/google-cloud-cli-linux-x86_64.tar.gz
tar -xzf google-cloud-cli-linux-x86_64.tar.gz -C /tmp/
/tmp/google-cloud-sdk/install.sh --quiet --path-update=false
export PATH="/tmp/google-cloud-sdk/bin:$PATH"
```

### 5b. Fazer login no Google
```bash
gcloud auth login
# Vai abrir o navegador → faça login com sua conta Google
```

### 5c. Rodar o script de setup automático
```bash
bash scripts/setup-gcp-infrastructure.sh
```

Este script automaticamente:
- Cria o projeto GCP `sentinel-pipeline`
- Ativa a API do BigQuery
- Cria o dataset `sentinel` e tabela `leads` com o schema correto
- Cria a service account `sentinel-bq-writer`
- Salva as credenciais no AWS SSM
- Faz `sam build && sam deploy` de novo com os valores reais

No final você verá o Project ID criado (ex: `sentinel-pipeline-152541`).

---

## Passo 6 — Testar o agente localmente (opcional mas recomendado)

Antes de usar a API, você pode testar o agente diretamente:

```bash
pip install -r src/ai/requirements.txt

export PINECONE_API_KEY=$(grep "^PINECONE_API_KEY" .env | cut -d= -f2)
export GEMINI_API_KEY=$(grep "^GEMINI_API_KEY" .env | cut -d= -f2)
export PINECONE_INDEX_NAME=sentinel-profiles

python scripts/test_agent.py --quiet
```

Resultado esperado:
```
============================================================
  Sentinel Agent Test — 3 Reference Leads
============================================================
[Test 1/3] VIP Lead  → Score: 84.7  Tier: VIP   PASS
[Test 2/3] HOT Lead  → Score: 65.3  Tier: HOT   PASS
[Test 3/3] COLD Lead → Score: 28.2  Tier: COLD  PASS

All 3 agent tests PASSED.
ReAct loop verified — both tools called in correct order.
============================================================
```

---

## Passo 7 — Enviar uma requisição real

Substitua `<API_URL>` pela URL que apareceu no Passo 4.

```bash
API="https://wxw46s0pi2.execute-api.us-east-1.amazonaws.com/prod"

curl -X POST "$API/leads" \
  -H "Content-Type: application/json" \
  --data '{
    "company_name": "FinTech Startup",
    "sector": "fintech",
    "company_size": 150,
    "budget_signal": "high",
    "contact_email": "cto@fintechstartup.com"
  }'
```

Resposta imediata (< 1 segundo):
```json
{
  "lead_id": "884c8548-a7cd-473b-af6d-4ec6f39e0ac3",
  "message": "Lead received and queued for enrichment"
}
```

**Guarde o `lead_id` — você vai usar para verificar o resultado.**

### Exemplos de validação (devem retornar 400):
```bash
# Campos faltando
curl -X POST "$API/leads" -H "Content-Type: application/json" \
  --data '{"company_name": "Só o nome"}'

# budget_signal inválido (só aceita: high, medium, low, unknown)
curl -X POST "$API/leads" -H "Content-Type: application/json" \
  --data '{"company_name":"X","sector":"saas","company_size":10,"budget_signal":"rich","contact_email":"x@x.com"}'

# Email inválido
curl -X POST "$API/leads" -H "Content-Type: application/json" \
  --data '{"company_name":"X","sector":"saas","company_size":10,"budget_signal":"high","contact_email":"nao-e-email"}'
```

---

## Passo 8 — Verificar o resultado

O agente de IA processa o lead de forma **assíncrona** (leva ~60-90 segundos).

### Verificar no DynamoDB (via terminal):
```bash
LEAD_ID="884c8548-a7cd-473b-af6d-4ec6f39e0ac3"  # substitua pelo seu

aws dynamodb get-item \
  --table-name sentinel-leads \
  --key "{\"lead_id\": {\"S\": \"$LEAD_ID\"}}" \
  --region us-east-1
```

Resultado esperado após ~90s:
```json
{
  "Item": {
    "lead_id":    { "S": "884c8548-..." },
    "status":     { "S": "enriched" },
    "tier":       { "S": "VIP" },
    "score":      { "S": "84.1" },
    "summary":    { "S": "Lead com alta compatibilidade com perfil fintech..." },
    "rag_similarity": { "S": "0.755" }
  }
}
```

### Verificar no AWS Console (visual):
1. Acesse https://console.aws.amazon.com
2. Vá em **DynamoDB** → Tables → **sentinel-leads**
3. Clique em **Explore table items**
4. Seu lead aparece com `status = enriched`

### Verificar no BigQuery (~120s após o POST):
```bash
export PATH="/tmp/google-cloud-sdk/bin:$PATH"
bq query --use_legacy_sql=false \
  "SELECT company_name, sector, score, tier, processed_at
   FROM \`SEU_PROJECT_ID.sentinel.leads\`
   ORDER BY processed_at DESC LIMIT 5"
```

---

## Resumo do tempo de cada passo

| Ação | Tempo |
|---|---|
| POST /leads → resposta 200 | < 1 segundo |
| Mensagem aparece no SQS | < 5 segundos |
| Lambda de IA processa o lead | ~60–90 segundos |
| Registro aparece no DynamoDB | ~90 segundos |
| Registro aparece no BigQuery | ~120 segundos |

---

## Troubleshooting — problemas comuns

### "sam: command not found"
```bash
export PATH="/home/SEU_USUARIO/.pyenv/versions/3.12.7/bin:$PATH"
# ou
pip install aws-sam-cli
```

### Deploy falhou com "SSM parameter not found"
Você esqueceu de criar os parâmetros no Passo 2. Rode os comandos `aws ssm put-parameter` de novo.

### Lead não aparece no DynamoDB depois de 3 minutos
Verifique os logs do Lambda de IA:
```bash
aws logs tail /aws/lambda/sentinel-ai-enrichment --follow --region us-east-1
```

### BigQuery não recebe as linhas
Verifique os logs do Lambda de stream:
```bash
aws logs tail /aws/lambda/sentinel-stream-processor --follow --region us-east-1
```

### "No similar profiles found" no RAG
O índice Pinecone está vazio. Volte ao Passo 3 e rode `seed_pinecone.py`.

### "gemini-2.5-flash not found"
Sua API key do Gemini não tem acesso ao modelo. Teste no aistudio.google.com se o modelo está disponível para sua conta.

---

## Arquitetura resumida

```
[POST /leads]
      │
   API Gateway
      │
Lambda Ingest (TypeScript)      ← valida payload, gera lead_id
      │
     SQS                        ← desacopla ingest do processamento
      │
Lambda AI Enrichment (Python)   ← agente LangChain ReAct
      │    ├─ rag_tool           ← busca no Pinecone (gemini-embedding-001)
      │    └─ calculator_tool   ← score determinístico em Python puro
      │
   DynamoDB                     ← armazena lead enriquecido
      │
DynamoDB Stream
      │
Lambda Stream Processor (Python) ← transforma e envia pro GCP
      │
   BigQuery                     ← análise e dashboard
```

---

## Chaves e onde ficam armazenadas

| Chave | Onde fica | Como é usada |
|---|---|---|
| `PINECONE_API_KEY` | AWS SSM `/sentinel/pinecone_api_key` | Lambda de IA lê no cold start |
| `GEMINI_API_KEY` | AWS SSM `/sentinel/gemini_api_key` | Lambda de IA lê no cold start |
| `GCP_SERVICE_ACCOUNT_KEY` | AWS SSM `/sentinel/gcp_service_account_key` | Lambda de stream lê em runtime |
| `GCP_PROJECT_ID` | AWS SSM `/sentinel/gcp_project_id` | Injetado como env var no Lambda |

**Nunca commite o arquivo `.env` nem arquivos `*-key.json` no git.**
O `.gitignore` já está configurado para ignorá-los.
