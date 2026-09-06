"""
Gold stage: consolidation and indexing pipeline.
1. Consolidates all quarterly silver.*_awards_typed tables into gold.all_awards
   with pre-computed item_id and B-tree/ART indexes on query filtering columns.
2. Synchronizes gold.unique_items from silver.unique_items and builds the DuckDB
   FTS (Full-Text Search) BM25 index over Notice Title, Item Name, and Item Description.
3. Builds the HNSW vector similarity index on gold.item_embeddings(embedding)
   using the DuckDB VSS extension (cosine metric).

Usage:
    python pipeline/indexing.py
"""
import os
import time
import duckdb


def consolidate_gold_awards(con: duckdb.DuckDBPyConnection) -> str:
    """
    Finds all quarterly typed award tables in the silver schema (e.g. y2025_q1_awards_typed),
    unions them into gold.all_awards with item_id precomputed, and builds indexes
    on critical filtering columns (item_id, Region, Award Date, Procuring Entity).
    """
    print("[Gold Indexing] Consolidating quarterly awards into gold.all_awards ...")
    t0 = time.perf_counter()

    # Discover all silver.*_awards_typed tables
    silver_tables = con.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'silver' AND table_name LIKE '%_awards_typed'
        ORDER BY table_name
    """).fetchall()

    if not silver_tables:
        raise RuntimeError("No quarterly typed award tables found in 'silver' schema!")

    table_names = [t[0] for t in silver_tables]
    print(f"       Found {len(table_names)} silver award table(s): {', '.join(table_names)}")

    union_queries = []
    for t in table_names:
        union_queries.append(f"""
            SELECT 
                MD5(LOWER("Notice Title" || "Item Name" || "Item Description")) AS item_id,
                *
            FROM silver.{t}
        """)

    full_union_sql = " UNION ALL ".join(union_queries)

    con.execute("CREATE SCHEMA IF NOT EXISTS gold")
    con.execute(f"""
        CREATE OR REPLACE TABLE gold.all_awards AS
        {full_union_sql}
    """)

    row_count = con.execute("SELECT COUNT(*) FROM gold.all_awards").fetchone()[0]
    print(f"       gold.all_awards populated with {row_count:,} total records ({time.perf_counter() - t0:.2f}s)")

    # Build standard ART / B-Tree indexes for fast SQL joins and filtering
    print("       Building analytical indexes on gold.all_awards ...")
    con.execute("CREATE INDEX IF NOT EXISTS idx_all_awards_item_id ON gold.all_awards (item_id)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_all_awards_region ON gold.all_awards (Region)")
    con.execute('CREATE INDEX IF NOT EXISTS idx_all_awards_award_date ON gold.all_awards ("Award Date")')
    con.execute('CREATE INDEX IF NOT EXISTS idx_all_awards_pe ON gold.all_awards ("Procuring Entity (PE)")')
    con.execute('CREATE INDEX IF NOT EXISTS idx_all_awards_awardee ON gold.all_awards ("Awardee Organization Name")')
    print("       Indexes created on: item_id, Region, Award Date, Procuring Entity (PE), Awardee Organization Name")

    return "gold.all_awards"


def build_fts_index(con: duckdb.DuckDBPyConnection) -> str:
    """
    Synchronizes gold.unique_items from silver.unique_items and creates/replaces
    the Full-Text Search (FTS) index with BM25 scoring over item text fields.
    """
    print("[Gold Indexing] Setting up gold.unique_items and FTS index ...")
    t0 = time.perf_counter()

    con.execute("INSTALL fts; LOAD fts;")

    # Sync gold.unique_items catalog
    con.execute("""
        CREATE OR REPLACE TABLE gold.unique_items AS
        SELECT 
            item_id,
            "Notice Title",
            "Item Name",
            "Item Description",
            "UNSPSC Code",
            "UNSPSC Description"
        FROM silver.unique_items
    """)

    item_count = con.execute("SELECT COUNT(*) FROM gold.unique_items").fetchone()[0]
    print(f"       gold.unique_items synchronized with {item_count:,} unique items")

    # Build FTS index
    print("       Building BM25 Full-Text Search index on gold.unique_items ...")
    t_fts = time.perf_counter()
    con.execute("""
        PRAGMA create_fts_index(
            'gold.unique_items',
            'item_id',
            'Notice Title',
            'Item Name',
            'Item Description',
            overwrite=1
        );
    """)
    print(f"       FTS BM25 index built in {time.perf_counter() - t_fts:.2f}s")
    return "gold.unique_items"


def build_hnsw_index(con: duckdb.DuckDBPyConnection) -> str:
    """
    Ensures DuckDB VSS extension is loaded and builds the HNSW index on
    gold.item_embeddings(embedding) using Cosine similarity metric.
    """
    print("[Gold Indexing] Setting up HNSW vector index on gold.item_embeddings ...")
    t0 = time.perf_counter()

    con.execute("INSTALL vss; LOAD vss;")
    con.execute("SET hnsw_enable_experimental_persistence = true;")

    # Pre-check row count in item_embeddings
    embed_count = con.execute("SELECT COUNT(*) FROM gold.item_embeddings WHERE embedding IS NOT NULL").fetchone()[0]
    if embed_count == 0:
        print("       [Warning] gold.item_embeddings has 0 non-null vectors! Run pipeline/gold.py first.")
        return "gold.item_embeddings"

    print(f"       Found {embed_count:,} embeddings to index with HNSW (metric: cosine) ...")

    # Drop existing index if present to avoid stale state and recreate
    con.execute("DROP INDEX IF EXISTS gold.idx_item_embeddings_hnsw")
    con.execute("""
        CREATE INDEX idx_item_embeddings_hnsw 
        ON gold.item_embeddings USING HNSW (embedding) 
        WITH (metric = 'cosine')
    """)
    print(f"       HNSW vector index built in {time.perf_counter() - t0:.2f}s")
    return "gold.item_embeddings"


def run_indexing(db_path: str = "data/philgeps.duckdb"):
    """
    Runs the full gold indexing sequence:
    1. Consolidate quarterly awards into gold.all_awards with filtering indexes.
    2. Synchronize gold.unique_items and build FTS BM25 keyword index.
    3. Build HNSW vector index on gold.item_embeddings.
    """
    print("=" * 70)
    print("STARTING GOLD CONSOLIDATION & INDEXING")
    print("=" * 70)
    t_total = time.perf_counter()

    con = duckdb.connect(db_path)

    consolidate_gold_awards(con)
    print("-" * 70)
    build_fts_index(con)
    print("-" * 70)
    build_hnsw_index(con)

    con.close()
    print("=" * 70)
    print(f"GOLD INDEXING COMPLETE in {time.perf_counter() - t_total:.2f}s")
    print("=" * 70)


if __name__ == "__main__":
    run_indexing()
