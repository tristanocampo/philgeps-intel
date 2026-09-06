"""
Prompt engineering and context builder for PhilGEPS Intelligence RAG.
"""
from typing import Any

SYSTEM_PROMPT = """You are PhilGEPS Intelligence, an authoritative AI analyst specialized in Philippine government procurement and public expenditure transparency.

Your role:
Provide clear, accurate, and data-backed answers to queries regarding Philippine public procurement contracts, spend summaries, procuring entities, and suppliers.

Guidelines:
1. Ground your answer strictly in the provided Context (both the Financial Spend Summary and the Matched Procurement Items).
2. Report all monetary values in Philippine Pesos (₱) formatted cleanly (e.g. ₱1,250,000.00).
3. Explicitly cite specific Procuring Entities (agencies), Awardee suppliers, contract dates, and Award Reference Numbers when available in the context.
4. If the data indicates zero or insufficient matches, state that clearly without fabricating or guessing numbers.
5. Keep answers professional, structured, and informative.
"""

QUERY_PREPROCESSOR_PROMPT = """You are an expert NLP Query Pre-Processor for Philippine public procurement records (PhilGEPS).

Given a user's natural language question:
1. Detect and correct any spelling mistakes or typos (e.g. "catring servces" -> "catering services", "bnd paperr" -> "bond paper").
2. Resolve common Philippine government acronyms to their official, legal uppercase names (e.g. "PSA" -> "PHILIPPINE STATISTICS AUTHORITY", "DepEd" -> "DEPARTMENT OF EDUCATION", "DPWH" -> "DEPARTMENT OF PUBLIC WORKS AND HIGHWAYS", "DOH" -> "DEPARTMENT OF HEALTH", "DOTr" -> "DEPARTMENT OF TRANSPORTATION", "DA" -> "DEPARTMENT OF AGRICULTURE", "PNP" -> "PHILIPPINE NATIONAL POLICE", "DICT" -> "DEPARTMENT OF INFORMATION AND COMMUNICATIONS TECHNOLOGY"). If no agency is mentioned, set to null.
3. Normalize regions if mentioned (e.g. "NCR", "Region IV-A", "Region III", "CAR", "BARMM", "Region VII"). If no region is specified, set to null.
4. Extract and expand product/service search terms with relevant procurement synonyms (e.g. "meals" -> "meals catering food packed snacks", "laptops" -> "laptops computers mobile workstations").
   IMPORTANT: If the user is asking about an agency or region's general or total spending (e.g. "How much did PSA spend?", "How much did PSA spend on Q1?", "What is DepEd's total spend?") and did NOT specify a concrete product or item, set "search_terms" to null!

Respond with ONLY a valid JSON object in this exact schema:
{
  "search_terms": "corrected and expanded item terms for vector and keyword search, or null if asking for general overall spend",
  "agency_formal": "OFFICIAL LEGAL UPPERCASE AGENCY NAME or null",
  "agency_short": "Short acronym or null",
  "region": "Normalized Region string or null"
}
"""


def build_rag_context(search_output: dict[str, Any]) -> str:
    """
    Formats the output from pipeline.search.hybrid_search into a structured,
    compact text context for the LLM prompt.
    """
    items = search_output.get("items", [])
    spend = search_output.get("spend_summary", {})

    lines = []
    lines.append("=== FINANCIAL SPEND SUMMARY ===")
    lines.append(f"- Total Monetary Spend: ₱{spend.get('total_spend', 0.0):,.2f}")
    lines.append(f"- Total Awarded Contracts: {spend.get('award_count', 0):,}")
    lines.append(f"- Average Contract Value: ₱{spend.get('avg_spend', 0.0):,.2f}")

    # Top Agencies
    top_agencies = spend.get("top_agencies", [])
    if top_agencies:
        lines.append("\nTop Procuring Entities (by spend):")
        for a in top_agencies:
            lines.append(f"  * {a['agency']}: ₱{a['spend']:,.2f} across {a['count']:,} award(s)")

    # Top Regions
    top_regions = spend.get("top_regions", [])
    if top_regions:
        lines.append("\nTop Regions (by spend):")
        for r in top_regions:
            lines.append(f"  * {r['region']}: ₱{r['spend']:,.2f} across {r['count']:,} award(s)")

    # Sample Awards
    sample_awards = spend.get("sample_awards", [])
    if sample_awards:
        lines.append("\nSample Notable Contracts:")
        for s in sample_awards:
            lines.append(
                f"  * [Ref: {s['award_ref']}] Agency: {s['agency']} | Awardee: {s['awardee']} | "
                f"Amount: ₱{s['contract_amount']:,.2f} | Date: {s['award_date']} | "
                f"Item: {s['item_name']} (Notice: {s['notice_title']})"
            )

    # Matched Catalog Items
    if items:
        lines.append("\n=== MATCHED CATALOG ITEMS ===")
        for i, item in enumerate(items, start=1):
            lines.append(
                f"{i}. [ID: {item['item_id'][:8]}] {item['item_name']} | "
                f"Notice: {item['notice_title']} | "
                f"Category: {item.get('unspsc_desc', 'N/A')} | "
                f"Description: {item.get('item_desc', 'N/A')}"
            )

    return "\n".join(lines)


def build_user_prompt(query: str, context_str: str) -> str:
    """
    Constructs the final prompt payload for the LLM.
    """
    return f"""Context Data:
{context_str}

User Question:
{query}

Please answer the question based strictly on the context provided above."""
