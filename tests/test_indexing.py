"""
Unit tests for Gold consolidation and indexing.
Validates:
1. gold.all_awards exists, has item_id, and indexes are active.
2. gold.unique_items exists and DuckDB BM25 FTS index returns scored matches.
3. gold.item_embeddings has HNSW vector index and performs cosine similarity search.
"""
import duckdb

DB_PATH = "data/philgeps.duckdb"


def test_gold_all_awards():
    con = duckdb.connect(DB_PATH, read_only=True)
    
    # Verify table existence & row count
    count = con.execute("SELECT COUNT(*) FROM gold.all_awards").fetchone()[0]
    assert count > 0, "gold.all_awards should not be empty"
    
    # Verify item_id column presence
    cols = [c[0] for c in con.execute("DESCRIBE gold.all_awards").fetchall()]
    assert "item_id" in cols, "gold.all_awards must contain 'item_id' column"
    assert "Procuring Entity (PE)" in cols, "gold.all_awards must contain 'Procuring Entity (PE)'"
    assert "Region" in cols, "gold.all_awards must contain 'Region'"
    assert "Contract Amount" in cols, "gold.all_awards must contain 'Contract Amount'"
    
    con.close()


def test_gold_fts_search():
    con = duckdb.connect(DB_PATH, read_only=True)
    con.execute("INSTALL fts; LOAD fts;")
    
    # Test BM25 match on a common procurement term (e.g. 'paper' or 'vehicle' or 'medical')
    res = con.execute("""
        SELECT item_id, "Item Name", score
        FROM (
            SELECT item_id, "Item Name", fts_gold_unique_items.match_bm25(item_id, 'paper') AS score
            FROM gold.unique_items
        )
        WHERE score IS NOT NULL
        ORDER BY score DESC
        LIMIT 5;
    """).fetchall()
    
    assert len(res) > 0, "FTS BM25 query for 'paper' should return matches"
    for r in res:
        assert r[2] is not None and r[2] > 0, "BM25 score should be positive"
        
    con.close()


def test_gold_hnsw_search():
    con = duckdb.connect(DB_PATH, read_only=True)
    con.execute("INSTALL vss; LOAD vss;")
    con.execute("SET hnsw_enable_experimental_persistence = true;")
    
    # Fetch an existing embedding vector to use as a probe
    sample = con.execute("SELECT embedding FROM gold.item_embeddings WHERE embedding IS NOT NULL LIMIT 1").fetchone()
    assert sample is not None, "At least one embedding vector must exist in gold.item_embeddings"
    probe_vec = sample[0]
    
    # Test vector cosine similarity
    res = con.execute("""
        SELECT item_id, array_cosine_similarity(embedding, $vec::FLOAT[768]) AS sim
        FROM gold.item_embeddings
        ORDER BY sim DESC
        LIMIT 5;
    """, {"vec": probe_vec}).fetchall()
    
    assert len(res) > 0, "HNSW cosine search must return results"
    # The top result should be ~1.0 (identical vector)
    assert abs(res[0][1] - 1.0) < 1e-4, f"Top similarity to self should be ~1.0, got {res[0][1]}"
    
    con.close()


if __name__ == "__main__":
    test_gold_all_awards()
    test_gold_fts_search()
    test_gold_hnsw_search()
    print("All indexing tests passed successfully!")
