"""
PhilGEPS Intelligence Query Engine & Execution Coordinator.
Orchestrates:
1. Query Pre-Processing via Gemini 3.5 Flash Lite (Acronym expansion, typo healing, synonym bridging, region/agency extraction).
2. Query Vectorization via Vertex AI text-embedding-005.
3. Hybrid Search (DuckDB HNSW + BM25 via Reciprocal Rank Fusion).
4. SQL Financial Spend Aggregation on gold.all_awards.
5. Final Answer Generation via Gemini 3.5 Flash Lite (or deterministic fallback).
"""
import os
import re
import json
import time
from typing import Any
from dotenv import load_dotenv

load_dotenv()

from pipeline.search import hybrid_search, DB_PATH
from rag.prompt import (
    SYSTEM_PROMPT,
    QUERY_PREPROCESSOR_PROMPT,
    build_rag_context,
    build_user_prompt
)

DEFAULT_GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

_EMBED_MODEL = None
_GENAI_CLIENT = None


def get_genai_client():
    """Initializes Google GenAI client for Google AI Studio."""
    global _GENAI_CLIENT
    if _GENAI_CLIENT is None:
        key = os.getenv("GEMINI_API_KEY")
        if key:
            try:
                from google import genai
                _GENAI_CLIENT = genai.Client(api_key=key)
            except Exception as e:
                print(f"[RAG Engine] Notice: Could not initialize GenAI client ({e})")
                _GENAI_CLIENT = False
        else:
            _GENAI_CLIENT = False
    return _GENAI_CLIENT if _GENAI_CLIENT is not False else None


def get_embedding_model():
    """Lazy loads Vertex AI embedding model."""
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        try:
            from pipeline.gold import _load_model
            _EMBED_MODEL = _load_model()
        except Exception as e:
            print(f"[RAG Engine] Notice: Could not load Vertex AI embedding model ({e}). Vector search will be skipped.")
            _EMBED_MODEL = False
    return _EMBED_MODEL if _EMBED_MODEL is not False else None


def embed_query(query: str) -> list[float] | None:
    """Embeds a user query string into a 768-dim float vector."""
    model = get_embedding_model()
    if model is None:
        return None
    try:
        from pipeline.gold import _embed_batch
        vectors = _embed_batch(model, [query])
        return vectors[0] if vectors else None
    except Exception as e:
        print(f"[RAG Engine] Error generating query embedding: {e}")
        return None


def preprocess_user_query(query: str) -> dict[str, Any]:
    """
    Step 1: Analyzes raw user query with Gemini 3.5 Flash Lite to:
    - Heal spelling typos ("catring servces" -> "catering services")
    - Expand common acronyms ("PSA" -> "PHILIPPINE STATISTICS AUTHORITY")
    - Bridge synonyms ("meals" -> "meals catering food packed snacks")
    - Extract region and agency filters
    """
    client = get_genai_client()
    default_res = {
        "search_terms": query,
        "agency_formal": None,
        "agency_short": None,
        "region": None
    }

    if not client:
        return default_res

    prompt = f"{QUERY_PREPROCESSOR_PROMPT}\n\nUser Question:\n\"{query}\"\n\nJSON Output:"
    try:
        response = client.models.generate_content(
            model=DEFAULT_GEMINI_MODEL,
            contents=prompt
        )
        raw_text = response.text.strip()
        # Strip markdown code blocks if present
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)
        
        parsed = json.loads(raw_text)
        raw_terms = parsed.get("search_terms")
        if raw_terms is not None and str(raw_terms).lower() not in ("null", "none", ""):
            search_terms = str(raw_terms).strip()
        else:
            search_terms = None

        return {
            "search_terms": search_terms,
            "agency_formal": parsed.get("agency_formal") if parsed.get("agency_formal") != "null" else None,
            "agency_short": parsed.get("agency_short") if parsed.get("agency_short") != "null" else None,
            "region": parsed.get("region") if parsed.get("region") != "null" else None
        }
    except Exception as e:
        print(f"[RAG Engine] Pre-processor notice: {e}. Using raw query.")
        return default_res


def synthesize_fallback_answer(query: str, search_output: dict[str, Any]) -> str:
    """Deterministic fallback synthesis if LLM API is unavailable."""
    spend = search_output.get("spend_summary", {})
    total = spend.get("total_spend", 0.0)
    count = spend.get("award_count", 0)
    avg = spend.get("avg_spend", 0.0)

    if count == 0:
        return f"No procurement contracts were found matching '{query}'. Please check your search terms or filter criteria."

    lines = [
        f"Based on the PhilGEPS records, here is the procurement summary for '{query}':",
        f"- **Total Spend:** ₱{total:,.2f} across {count:,} awarded contract(s)",
        f"- **Average Contract Value:** ₱{avg:,.2f}"
    ]

    top_agencies = spend.get("top_agencies", [])
    if top_agencies:
        lines.append("\n**Top Procuring Entities:**")
        for a in top_agencies:
            lines.append(f"- {a['agency']}: ₱{a['spend']:,.2f} ({a['count']:,} awards)")

    top_regions = spend.get("top_regions", [])
    if top_regions:
        lines.append("\n**Top Regions:**")
        for r in top_regions:
            lines.append(f"- {r['region']}: ₱{r['spend']:,.2f}")

    samples = spend.get("sample_awards", [])
    if samples:
        lines.append("\n**Notable Contracts:**")
        for s in samples[:3]:
            lines.append(f"- **₱{s['contract_amount']:,.2f}** — *{s['item_name']}* awarded by **{s['agency']}** to **{s['awardee']}** on {s['award_date']} (Ref: {s['award_ref']})")

    return "\n".join(lines)


def ask_philgeps(
    query: str,
    region_filter: str | None = None,
    agency_filter: str | None = None,
    top_k: int = 10,
    db_path: str = DB_PATH
) -> dict[str, Any]:
    """
    Unified entry point for PhilGEPS Intelligence:
    Routes query through the Schema-Aware Tool Agent (rag.agent.PhilGEPSAgent).
    Executes dynamic SQL for analytics or hybrid retrieval for product searches.
    """
    from rag.agent import get_agent

    agent = get_agent()
    agent_res = agent.execute_query(query)

    data_rows = agent_res.get("data_rows", [])
    total_spend = 0.0
    for r in data_rows:
        if isinstance(r, dict):
            for k in ("Contract Amount", "total_spend", "total_awarded", "amount", "spend"):
                if k in r and r[k] is not None:
                    try:
                        total_spend += float(r[k])
                        break
                    except (ValueError, TypeError):
                        pass

    return {
        "query": query,
        "answer": agent_res["answer"],
        "tool_used": agent_res["tool_used"],
        "sql_query": agent_res.get("sql_query"),
        "data_rows": data_rows,
        "matched_items_count": len(data_rows),
        "total_spend": total_spend,
        "latency_ms": agent_res["latency_ms"],
        "prompt_tokens": agent_res.get("prompt_tokens", 0),
        "completion_tokens": agent_res.get("completion_tokens", 0),
        "total_tokens": agent_res.get("total_tokens", 0),
        "cost_usd": agent_res.get("cost_usd", 0.0),
        "used_vector": agent_res["tool_used"] == "catalog_search",
        "used_llm": True,
        # Backward compatibility aliases
        "search_output": {
            "items": data_rows,
            "spend_summary": {
                "total_spend": total_spend,
                "award_count": len(data_rows),
                "avg_spend": (total_spend / len(data_rows)) if data_rows else 0.0,
                "sample_awards": data_rows[:5]
            }
        }
    }
