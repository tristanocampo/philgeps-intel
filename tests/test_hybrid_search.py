"""
Unit tests for hybrid search & financial spend aggregation engine.
"""
import os
import sys
sys.path.insert(0, os.path.abspath("."))
import duckdb
from pipeline.search import (
    vector_search,
    keyword_search,
    reciprocal_rank_fusion,
    aggregate_item_spend,
    hybrid_search
)

DB_PATH = "data/philgeps.duckdb"


def test_keyword_search():
    con = duckdb.connect(DB_PATH, read_only=True)
    results = keyword_search(con, "Bond Paper A4", top_k=5)
    con.close()
    
    assert len(results) > 0, "Keyword search should return matches for 'Bond Paper A4'"
    assert "score" in results[0]
    assert "rank" in results[0]
    assert results[0]["rank"] == 1


def test_vector_search():
    con = duckdb.connect(DB_PATH, read_only=True)
    # Grab an existing embedding vector as a probe
    probe = con.execute("SELECT embedding FROM gold.item_embeddings WHERE embedding IS NOT NULL LIMIT 1").fetchone()
    assert probe is not None
    probe_vec = probe[0]
    
    results = vector_search(con, probe_vec, top_k=5)
    con.close()
    
    assert len(results) > 0, "Vector search should return items"
    assert results[0]["score"] > 0.99, "Self similarity should be ~1.0"


def test_reciprocal_rank_fusion():
    con = duckdb.connect(DB_PATH, read_only=True)
    kw_res = keyword_search(con, "medical", top_k=5)
    probe = con.execute("SELECT embedding FROM gold.item_embeddings WHERE embedding IS NOT NULL LIMIT 1").fetchone()[0]
    vec_res = vector_search(con, probe, top_k=5)
    con.close()
    
    fused = reciprocal_rank_fusion(vec_res, kw_res, top_k=5)
    assert len(fused) > 0
    assert "rrf_score" in fused[0]
    assert fused[0]["final_rank"] == 1
    # Check that scores are monotonically non-increasing
    for i in range(len(fused) - 1):
        assert fused[i]["rrf_score"] >= fused[i+1]["rrf_score"]


def test_spend_aggregation():
    con = duckdb.connect(DB_PATH, read_only=True)
    # Get a sample item_id that exists in gold.all_awards
    row = con.execute("SELECT item_id FROM gold.all_awards LIMIT 1").fetchone()
    assert row is not None
    sample_id = row[0]
    
    agg = aggregate_item_spend(con, [sample_id])
    con.close()
    
    assert "total_spend" in agg
    assert "award_count" in agg
    assert agg["award_count"] >= 1
    assert agg["total_spend"] > 0


def test_hybrid_search_end_to_end():
    con = duckdb.connect(DB_PATH, read_only=True)
    probe = con.execute("SELECT embedding FROM gold.item_embeddings WHERE embedding IS NOT NULL LIMIT 1").fetchone()[0]
    con.close()
    
    out = hybrid_search(query_text="catering services", query_vector=probe, top_k=5)
    assert "items" in out
    assert "spend_summary" in out
    assert len(out["items"]) > 0


if __name__ == "__main__":
    test_keyword_search()
    test_vector_search()
    test_reciprocal_rank_fusion()
    test_spend_aggregation()
    test_hybrid_search_end_to_end()
    print("All hybrid search tests passed successfully!")
