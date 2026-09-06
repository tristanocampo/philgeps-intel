"""
Search & Retrieval Engine for PhilGEPS Intelligence.
Implements:
1. Vector Search: Cosine similarity retrieval over gold.item_embeddings using HNSW.
2. Keyword Search: BM25 Full-Text Search over gold.unique_items using DuckDB FTS.
3. Hybrid Search: Reciprocal Rank Fusion (RRF) combining Vector + Keyword ranks.
4. SQL Financial Spend Aggregator: Joins retrieved item_ids to gold.all_awards
   to compute total spend, contract count, top procuring entities, and top regions.
"""
from typing import Any
import duckdb

DB_PATH = "data/philgeps.duckdb"
RRF_K = 60  # Standard Reciprocal Rank Fusion smoothing constant


def vector_search(
    con: duckdb.DuckDBPyConnection,
    query_vector: list[float],
    top_k: int = 20,
    region_filter: str | None = None,
    agency_filter: str | None = None
) -> list[dict[str, Any]]:
    """
    Retrieves top_k items matching query_vector using DuckDB HNSW cosine similarity.
    Pushes down region_filter and agency_filter when provided to guarantee scoped retrieval.
    """
    where_sub = []
    params: dict[str, Any] = {"vec": query_vector, "k": top_k}
    if region_filter:
        where_sub.append("LOWER(Region) LIKE LOWER($region)")
        params["region"] = f"%{region_filter}%"
    if agency_filter:
        where_sub.append('LOWER("Procuring Entity (PE)") LIKE LOWER($agency)')
        params["agency"] = f"%{agency_filter}%"

    scope_sql = (
        f"AND u.item_id IN (SELECT DISTINCT item_id FROM gold.all_awards WHERE {' AND '.join(where_sub)})"
        if where_sub else ""
    )

    query = f"""
        SELECT 
            u.item_id,
            u."Notice Title",
            u."Item Name",
            u."Item Description",
            u."UNSPSC Code",
            u."UNSPSC Description",
            array_cosine_similarity(e.embedding, $vec::FLOAT[768]) AS score
        FROM gold.item_embeddings e
        JOIN gold.unique_items u ON e.item_id = u.item_id
        WHERE e.embedding IS NOT NULL
        {scope_sql}
        ORDER BY score DESC
        LIMIT $k;
    """
    rows = con.execute(query, params).fetchall()
    
    results = []
    for rank, row in enumerate(rows, start=1):
        results.append({
            "item_id": row[0],
            "notice_title": row[1],
            "item_name": row[2],
            "item_desc": row[3],
            "unspsc_code": row[4],
            "unspsc_desc": row[5],
            "score": float(row[6]),
            "rank": rank,
            "source": "vector"
        })
    return results


def keyword_search(
    con: duckdb.DuckDBPyConnection,
    query_text: str,
    top_k: int = 20,
    region_filter: str | None = None,
    agency_filter: str | None = None
) -> list[dict[str, Any]]:
    """
    Retrieves top_k items matching query_text using BM25 scoring from
    DuckDB Full-Text Search on gold.unique_items.
    Pushes down region_filter and agency_filter when provided to guarantee scoped retrieval.
    """
    con.execute("INSTALL fts; LOAD fts;")

    # Clean query text for BM25: strip special syntax symbols that could break FTS parser
    cleaned_query = "".join(c if c.isalnum() or c.isspace() else " " for c in query_text).strip()
    if not cleaned_query:
        return []

    where_sub = []
    params: dict[str, Any] = {"query": cleaned_query, "k": top_k}
    if region_filter:
        where_sub.append("LOWER(Region) LIKE LOWER($region)")
        params["region"] = f"%{region_filter}%"
    if agency_filter:
        where_sub.append('LOWER("Procuring Entity (PE)") LIKE LOWER($agency)')
        params["agency"] = f"%{agency_filter}%"

    scope_sql = (
        f"AND item_id IN (SELECT DISTINCT item_id FROM gold.all_awards WHERE {' AND '.join(where_sub)})"
        if where_sub else ""
    )

    query = f"""
        SELECT 
            item_id,
            "Notice Title",
            "Item Name",
            "Item Description",
            "UNSPSC Code",
            "UNSPSC Description",
            score
        FROM (
            SELECT 
                item_id,
                "Notice Title",
                "Item Name",
                "Item Description",
                "UNSPSC Code",
                "UNSPSC Description",
                fts_gold_unique_items.match_bm25(item_id, $query) AS score
            FROM gold.unique_items
        )
        WHERE score IS NOT NULL
        {scope_sql}
        ORDER BY score DESC
        LIMIT $k;
    """
    rows = con.execute(query, params).fetchall()
    
    results = []
    for rank, row in enumerate(rows, start=1):
        results.append({
            "item_id": row[0],
            "notice_title": row[1],
            "item_name": row[2],
            "item_desc": row[3],
            "unspsc_code": row[4],
            "unspsc_desc": row[5],
            "score": float(row[6]),
            "rank": rank,
            "source": "keyword"
        })
    return results


def reciprocal_rank_fusion(
    vector_results: list[dict[str, Any]],
    keyword_results: list[dict[str, Any]],
    k_constant: int = RRF_K,
    top_k: int = 10
) -> list[dict[str, Any]]:
    """
    Combines ranked items from vector and keyword search using Reciprocal Rank Fusion (RRF).
    RRF Score = sum(1 / (k_constant + rank)) across available retrieval lists.
    """
    fused_scores: dict[str, float] = {}
    item_metadata: dict[str, dict[str, Any]] = {}

    for item in vector_results:
        iid = item["item_id"]
        fused_scores[iid] = fused_scores.get(iid, 0.0) + (1.0 / (k_constant + item["rank"]))
        if iid not in item_metadata:
            item_metadata[iid] = item

    for item in keyword_results:
        iid = item["item_id"]
        fused_scores[iid] = fused_scores.get(iid, 0.0) + (1.0 / (k_constant + item["rank"]))
        if iid not in item_metadata:
            item_metadata[iid] = item

    # Sort descending by RRF fused score
    sorted_items = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)[:top_k]

    final_results = []
    for rank, (iid, score) in enumerate(sorted_items, start=1):
        meta = item_metadata[iid].copy()
        meta["rrf_score"] = score
        meta["final_rank"] = rank
        final_results.append(meta)

    return final_results


def aggregate_item_spend(
    con: duckdb.DuckDBPyConnection,
    item_ids: list[str] | None = None,
    region_filter: str | None = None,
    agency_filter: str | None = None,
    sample_item_ids: list[str] | None = None
) -> dict[str, Any]:
    """
    Joins retrieved item_ids back to gold.all_awards to compute real financial metrics.
    If item_ids is empty or None, but agency_filter or region_filter is specified,
    computes the agency's / region's total overall expenditure across all items!
    """
    where_clauses = []
    params: dict[str, Any] = {}

    if item_ids:
        where_clauses.append("item_id IN (SELECT UNNEST($iids))")
        params["iids"] = item_ids

    if region_filter:
        where_clauses.append("LOWER(Region) LIKE LOWER($region)")
        params["region"] = f"%{region_filter}%"

    if agency_filter:
        where_clauses.append('LOWER("Procuring Entity (PE)") LIKE LOWER($agency)')
        params["agency"] = f"%{agency_filter}%"

    # If neither items nor filters were provided, return empty
    if not where_clauses:
        return {
            "total_spend": 0.0,
            "award_count": 0,
            "avg_spend": 0.0,
            "top_agencies": [],
            "top_regions": [],
            "sample_awards": []
        }

    where_sql = " AND ".join(where_clauses)

    # 1. High-level summary
    summary_sql = f"""
        SELECT 
            COALESCE(SUM("Contract Amount"), 0) AS total_spend,
            COUNT(*) AS award_count,
            COALESCE(AVG("Contract Amount"), 0) AS avg_spend
        FROM gold.all_awards
        WHERE {where_sql}
    """
    total_spend, award_count, avg_spend = con.execute(summary_sql, params).fetchone()

    # 2. Top Procuring Entities
    agencies_sql = f"""
        SELECT 
            "Procuring Entity (PE)",
            COUNT(*) AS count,
            SUM("Contract Amount") AS spend
        FROM gold.all_awards
        WHERE {where_sql}
        GROUP BY "Procuring Entity (PE)"
        ORDER BY spend DESC
        LIMIT 5
    """
    top_agencies = [
        {"agency": r[0], "count": r[1], "spend": float(r[2])}
        for r in con.execute(agencies_sql, params).fetchall()
    ]

    # 3. Top Regions
    regions_sql = f"""
        SELECT 
            Region,
            COUNT(*) AS count,
            SUM("Contract Amount") AS spend
        FROM gold.all_awards
        WHERE {where_sql}
        GROUP BY Region
        ORDER BY spend DESC
        LIMIT 5
    """
    top_regions = [
        {"region": r[0], "count": r[1], "spend": float(r[2])}
        for r in con.execute(regions_sql, params).fetchall()
    ]

    # 4. Sample award line items
    # If sample_item_ids is provided (the top-k retrieved items), scope sample contracts strictly to those items
    sample_where = list(where_clauses)
    sample_params = dict(params)
    if sample_item_ids:
        sample_where = [c for c in sample_where if not c.startswith("item_id IN")]
        sample_where.append("item_id IN (SELECT UNNEST($sample_iids))")
        sample_params.pop("iids", None)
        sample_params["sample_iids"] = sample_item_ids

    sample_where_sql = " AND ".join(sample_where)
    sample_sql = f"""
        SELECT 
            "Award Reference No.",
            "Procuring Entity (PE)",
            "Awardee Organization Name",
            "Contract Amount",
            "Award Date",
            Region,
            "Notice Title",
            "Item Name"
        FROM gold.all_awards
        WHERE {sample_where_sql}
        ORDER BY "Contract Amount" DESC
        LIMIT 5
    """
    samples = [
        {
            "award_ref": r[0],
            "agency": r[1],
            "awardee": r[2],
            "contract_amount": float(r[3]),
            "award_date": str(r[4]),
            "region": r[5],
            "notice_title": r[6],
            "item_name": r[7]
        }
        for r in con.execute(sample_sql, sample_params).fetchall()
    ]

    return {
        "total_spend": float(total_spend),
        "award_count": int(award_count),
        "avg_spend": float(avg_spend),
        "top_agencies": top_agencies,
        "top_regions": top_regions,
        "sample_awards": samples
    }


def hybrid_search(
    query_text: str | None,
    query_vector: list[float] | None = None,
    top_k: int = 10,
    region_filter: str | None = None,
    agency_filter: str | None = None,
    db_path: str = DB_PATH
) -> dict[str, Any]:
    """
    Main unified retrieval & aggregation function:
    1. If query_text is present, runs Keyword BM25 and Vector Cosine search, blending via RRF.
    2. If query_text is None (general agency/region spend query), aggregates spend directly.
    """
    con = duckdb.connect(db_path, read_only=True)

    fused_items = []
    aggregation_item_ids = None

    if query_text and query_text.strip():
        # Retrieve a broader candidate pool (up to 200 items) for true spend aggregation
        candidate_limit = max(top_k * 10, 200)

        keyword_results = keyword_search(
            con,
            query_text,
            top_k=candidate_limit,
            region_filter=region_filter,
            agency_filter=agency_filter
        )

        vector_results = []
        if query_vector is not None:
            vector_results = vector_search(
                con,
                query_vector,
                top_k=candidate_limit,
                region_filter=region_filter,
                agency_filter=agency_filter
            )

        # 1. Top-K Representative items for LLM context & UI display
        if vector_results and keyword_results:
            fused_items = reciprocal_rank_fusion(vector_results, keyword_results, top_k=top_k)
        elif vector_results:
            fused_items = vector_results[:top_k]
        else:
            fused_items = keyword_results[:top_k]

        # 2. Broad candidate pool for complete financial spend analytics
        all_candidate_ids = {item["item_id"] for item in (keyword_results + vector_results)}
        aggregation_item_ids = list(all_candidate_ids) if all_candidate_ids else None

    # Step 3: Compute financial metrics across all matching candidates
    sample_ids = [item["item_id"] for item in fused_items] if fused_items else None
    financial_aggregates = aggregate_item_spend(
        con,
        aggregation_item_ids,
        region_filter=region_filter,
        agency_filter=agency_filter,
        sample_item_ids=sample_ids
    )

    con.close()

    return {
        "query": query_text or "general spend",
        "items": fused_items,
        "spend_summary": financial_aggregates
    }
