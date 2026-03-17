"""
LangChain ReAct agent for lead enrichment.

Tools:
  1. rag_tool       — queries Pinecone for semantically similar ideal customer profiles
  2. calculator_tool — deterministic scoring function (never delegated to the LLM)

The agent follows the ReAct loop:
  Thought → Action (rag_tool) → Observation → Thought → Action (calculator_tool) → Final Answer
"""

import json
import os
import re
from typing import Any

from google import genai as google_genai
from langchain.agents import AgentExecutor, create_react_agent
from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from pinecone import Pinecone

# ── Environment ────────────────────────────────────────────────────────────────

PINECONE_API_KEY   = os.environ["PINECONE_API_KEY"]
PINECONE_INDEX     = os.environ.get("PINECONE_INDEX_NAME", "sentinel-profiles")
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
EMBEDDING_MODEL    = "gemini-embedding-001"
EMBEDDING_DIM      = 1024
CHAT_MODEL         = "gemini-2.5-flash"
TOP_K              = 3

# ── Pinecone client (module-level singleton) ────────────────────────────────────

_pinecone_index = None


def _get_index():
    global _pinecone_index
    if _pinecone_index is None:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        _pinecone_index = pc.Index(PINECONE_INDEX)
    return _pinecone_index


# ── Tool 1: RAG Tool ─────────────────────────────────────────────────────────

@tool
def rag_tool(query: str) -> str:
    """
    Searches the knowledge base of ideal customer profiles for the most
    semantically similar entries given the lead's attributes.

    Input: a natural language query describing the lead (sector, size, budget, buyer type).
    Output: top-3 matching profiles with similarity scores and text snippets.

    Use this tool FIRST before the calculator_tool.
    """
    # Embed the query using the new google-genai SDK
    from google.genai import types as _genai_types
    _client = google_genai.Client(api_key=GEMINI_API_KEY)
    result = _client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=query,
        config=_genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=EMBEDDING_DIM,
        ),
    )
    query_vector = list(result.embeddings[0].values)

    # Query Pinecone
    index = _get_index()
    matches = index.query(vector=query_vector, top_k=TOP_K, include_metadata=True)

    if not matches.matches:
        return "No similar profiles found in the knowledge base."

    # Format output for the agent
    lines = []
    for i, match in enumerate(matches.matches):
        similarity = round(match.score, 4)
        category   = match.metadata.get("category", "unknown")
        text       = match.metadata.get("text", "")
        snippet    = text[:200]
        lines.append(
            f"[Result {i+1}] similarity={similarity}, category={category}\n"
            f"  Snippet: {snippet}"
        )

    top_similarity = round(matches.matches[0].score, 4)
    top_snippet    = matches.matches[0].metadata.get("text", "")[:200]
    top_category   = matches.matches[0].metadata.get("category", "unknown")

    output = "\n\n".join(lines)
    output += f"\n\nTOP_SIMILARITY={top_similarity}"
    output += f"\nTOP_CATEGORY={top_category}"
    output += f"\nTOP_SNIPPET={top_snippet}"
    return output


# ── Tool 2: Calculator Tool ──────────────────────────────────────────────────

def _calculate_score(
    company_size: int,
    sector_match: float,
    budget_signal: str,
    rag_similarity: float,
    top_category: str = "unknown",
) -> dict[str, Any]:
    """Deterministic scoring function — never call the LLM for this."""
    base         = rag_similarity * 40           # 0–40 pts: profile similarity
    size_score   = min(company_size / 10, 20)    # 0–20 pts: company size (capped at 200)
    # Red-flag matches indicate the lead resembles a bad profile — no sector credit.
    sector_score = 0.0 if top_category == "red_flag" else sector_match * 25  # 0–25 pts
    budget_map   = {"high": 15, "medium": 10, "low": 5, "unknown": 0}
    budget_score = budget_map.get(budget_signal.lower(), 0)  # 0–15 pts

    total = base + size_score + sector_score + budget_score
    tier  = "VIP" if total >= 75 else ("HOT" if total >= 50 else "COLD")

    return {
        "score": round(total, 1),
        "tier": tier,
        "breakdown": {
            "base_score": round(base, 1),
            "size_score": round(size_score, 1),
            "sector_score": round(sector_score, 1),
            "budget_score": budget_score,
        },
    }


@tool
def calculator_tool(input_json: str) -> str:
    """
    Computes a deterministic numeric lead score based on company attributes and RAG results.

    Input: JSON string with fields:
      - company_size (int): number of employees
      - sector_match (float): RAG similarity score from rag_tool (0.0–1.0)
      - budget_signal (str): "high" | "medium" | "low" | "unknown"
      - rag_similarity (float): same as sector_match
      - top_category (str, optional): category of the top RAG result (e.g. "positive", "sector", "red_flag")
        Pass the value from TOP_CATEGORY in the rag_tool output. If the top match is "red_flag",
        no sector credit is awarded — this prevents bad leads from scoring high due to red-flag similarity.

    Output: JSON string with score (float), tier ("VIP"|"HOT"|"COLD"), and breakdown.

    IMPORTANT: Use this tool SECOND, after rag_tool. Do NOT compute the score yourself.
    """
    try:
        # Handle both raw JSON and markdown code-fenced JSON
        clean = re.sub(r"```(?:json)?|```", "", input_json).strip()
        data = json.loads(clean)
    except json.JSONDecodeError as exc:
        return f"ERROR: Invalid JSON input — {exc}. Expected: {{\"company_size\": int, \"sector_match\": float, \"budget_signal\": str, \"rag_similarity\": float, \"top_category\": str}}"

    try:
        result = _calculate_score(
            company_size=int(data["company_size"]),
            sector_match=float(data["sector_match"]),
            budget_signal=str(data["budget_signal"]),
            rag_similarity=float(data["rag_similarity"]),
            top_category=str(data.get("top_category", "unknown")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        return f"ERROR: {exc}. Required fields: company_size, sector_match, budget_signal, rag_similarity"

    return json.dumps(result)


# ── System Prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a lead scoring agent. Your job is to evaluate a potential customer lead and produce a score and summary.

You have two tools:
1. rag_tool: searches a knowledge base of ideal customer profiles. Use it first.
2. calculator_tool: computes a numeric score based on lead data and RAG results. Use it second.

Always use both tools in order. Do not guess the score — use the calculator_tool.
After using both tools, write a 2-3 sentence summary explaining the score.

When calling calculator_tool, always include "top_category" from the TOP_CATEGORY field of the rag_tool output.
This is critical for correct scoring — red_flag matches must be flagged so the calculator applies the right penalty.

Return your final answer as JSON:
{{
  "score": <float>,
  "tier": <"VIP"|"HOT"|"COLD">,
  "summary": <string>,
  "rag_similarity": <float>,
  "rag_context_snippet": <string — first 200 chars of top RAG result>
}}

{tools}

Use the following format:

Question: the lead data you must evaluate
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Question: {input}
Thought:{agent_scratchpad}"""


# ── Agent builder ─────────────────────────────────────────────────────────────

def build_agent(verbose: bool = False) -> AgentExecutor:
    """Build and return the ReAct AgentExecutor."""
    llm = ChatGoogleGenerativeAI(
        model=CHAT_MODEL,
        google_api_key=GEMINI_API_KEY,
        temperature=0,
    )

    tools = [rag_tool, calculator_tool]

    prompt = PromptTemplate.from_template(SYSTEM_PROMPT)

    agent = create_react_agent(llm=llm, tools=tools, prompt=prompt)

    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=verbose,
        max_iterations=6,
        handle_parsing_errors=True,
        return_intermediate_steps=True,
    )


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_lead(lead: dict[str, Any], verbose: bool = False) -> dict[str, Any]:
    """
    Run the ReAct agent on a lead dict and return the enriched result.

    Args:
        lead: dict with keys company_name, sector, company_size, budget_signal, contact_email
        verbose: if True, prints the full agent trace

    Returns:
        dict with score, tier, summary, rag_similarity, rag_context_snippet
    """
    query = (
        f"Lead to evaluate:\n"
        f"  Company: {lead['company_name']}\n"
        f"  Sector: {lead['sector']}\n"
        f"  Employees: {lead['company_size']}\n"
        f"  Budget signal: {lead['budget_signal']}\n"
        f"  Contact: {lead['contact_email']}\n\n"
        f"Evaluate this lead using rag_tool then calculator_tool."
    )

    executor = build_agent(verbose=verbose)
    result   = executor.invoke({"input": query})
    output   = result.get("output", "")

    # Extract JSON from Final Answer — handle markdown fences
    json_str = re.sub(r"```(?:json)?|```", "", output).strip()

    # Try direct parse first (cleanest case)
    try:
        parsed = json.loads(json_str)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # Fallback: find JSON object using raw_decode from last { backwards
    # This handles preamble text like "Here is the result:" before the JSON
    decoder = json.JSONDecoder()
    brace_positions = [i for i, c in enumerate(json_str) if c == "{"]
    for pos in reversed(brace_positions):
        try:
            obj, _ = decoder.raw_decode(json_str, pos)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Agent did not return valid JSON.\nRaw output:\n{output}")
