"""
Gold stage: vector embedding generation.
Reads distinct item records from silver.unique_items that don't yet have an
embedding in gold.item_embeddings, generates 768-dimensional dense vectors
using Google Cloud Vertex AI (text-embedding-005), and appends them
to a separate Gold table.

Architecture note: we deliberately DON'T update silver.unique_items in place.
DuckDB is columnar — UPDATE on a DOUBLE[] column across 150K+ rows rewrites
entire column segments and is extremely slow. Instead, gold.item_embeddings
is an append-only table keyed by item_id, and search queries JOIN the two.

Chunked and checkpointed: progress is committed to DuckDB after every chunk,
so interrupted runs resume exactly where they left off without duplicate API calls.

Text Payload:
Uses strictly the 3 core fields that define the unique_items grain:
Notice Title, Item Name, Item Description.

Usage:
    python pipeline/gold.py                # embed all pending items
    python pipeline/gold.py --limit 100    # Stage 1 smoke test (100 items)
    python pipeline/gold.py --limit 5000   # Stage 2 representative sample
"""
import argparse
import os
import time
import duckdb
import pandas as pd
from dotenv import load_dotenv

load_dotenv()


# ─── constants & telemetry ──────────────────────────────────────────────────

MODEL_NAME = "text-embedding-005"            # Google Vertex AI 768-dim model
EMBEDDING_DIM = 768
DB_CHUNK_SIZE = 500                          # items fetched and committed per DB checkpoint
VERTEX_BATCH_SIZE = 100                      # items sent per Vertex AI HTTP request

RATE_PER_MILLION_TOKENS = 0.025              # Official Vertex AI rate: $0.025 per 1M tokens
USD_TO_PHP = 56.0                            # Approximate exchange rate for budget monitoring


def estimate_batch_cost(texts: list[str]) -> tuple[int, float]:
    """
    Estimates token count and cost in USD for a batch of texts.
    Standard Google token heuristic for English/alphanumeric: ~4 chars / token.
    Official Vertex AI text-embedding-005 pricing: $0.025 per 1,000,000 tokens.
    """
    total_chars = sum(len(t) for t in texts)
    tokens = int(total_chars / 4.0)
    cost_usd = (tokens / 1_000_000.0) * RATE_PER_MILLION_TOKENS
    return tokens, cost_usd


# ─── text payload ───────────────────────────────────────────────────────────

def construct_doc_text(
    notice_title: str,
    item_name: str,
    item_desc: str,
) -> str:
    """
    Formats the 3 core item fields into a clean, context-packed text payload
    for embedding, matching the silver.unique_items grain:
    Notice Title, Item Name, Item Description.
    """
    parts = []
    if notice_title and str(notice_title).strip() and str(notice_title).strip() != "NULL":
        parts.append(f"Title: {str(notice_title).strip()}")
    if item_name and str(item_name).strip() and str(item_name).strip() != "NULL":
        parts.append(f"Item: {str(item_name).strip()}")
    if item_desc and str(item_desc).strip() and str(item_desc).strip() != "NULL":
        parts.append(f"Description: {str(item_desc).strip()}")
    return " | ".join(parts) if parts else ""


# ─── embedding engine ──────────────────────────────────────────────────────

def _load_model():
    """
    Initializes Google Cloud Vertex AI and loads the TextEmbeddingModel.
    Reads credentials and project details from environment variables.
    """
    import vertexai
    from vertexai.language_models import TextEmbeddingModel

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    project_id = os.getenv("GCP_PROJECT_ID", "philgeps-prod")
    location = os.getenv("GCP_LOCATION", "us-central1")

    if creds_path and not os.path.exists(creds_path):
        raise FileNotFoundError(f"Google credentials file not found at: {creds_path}")

    print(f"[Gold] Initializing Vertex AI model: {MODEL_NAME} (project: {project_id}, location: {location}) ...")
    t0 = time.perf_counter()
    vertexai.init(project=project_id, location=location)
    model = TextEmbeddingModel.from_pretrained(MODEL_NAME)
    print(f"[Gold] Model initialized in {time.perf_counter() - t0:.1f}s")
    return model


def _embed_batch(model, texts: list[str]) -> list[list[float]]:
    """
    Encodes a list of text strings into 768-dimensional dense vectors
    using Google Vertex AI. Handles micro-batching according to VERTEX_BATCH_SIZE.
    """
    all_vectors = []
    for i in range(0, len(texts), VERTEX_BATCH_SIZE):
        sub_batch = texts[i : i + VERTEX_BATCH_SIZE]
        # TextEmbeddingModel.get_embeddings accepts list[str]
        embeddings = model.get_embeddings(sub_batch)
        for emb in embeddings:
            all_vectors.append(emb.values)
    return all_vectors


# ─── main pipeline ─────────────────────────────────────────────────────────

def run_gold(db_path: str = "data/philgeps.duckdb", limit: int | None = None) -> int:
    """
    Generates embeddings for all pending items and appends them to
    gold.item_embeddings.

    "Pending" = items in silver.unique_items whose item_id does NOT yet
    appear in gold.item_embeddings (LEFT ANTI JOIN).

    Returns the total number of items embedded in this run.
    """
    con = duckdb.connect(db_path)

    # ── ensure Gold schema + table exist with 768 dimensions ─────────────
    con.execute("CREATE SCHEMA IF NOT EXISTS gold")

    # Check if table exists with incorrect dimensions (e.g., from old 384-dim runs)
    table_info = con.execute("""
        SELECT data_type FROM information_schema.columns
        WHERE table_schema = 'gold' AND table_name = 'item_embeddings' AND column_name = 'embedding'
    """).fetchone()

    if table_info and f"[{EMBEDDING_DIM}]" not in table_info[0]:
        print(f"[Gold] Detected existing table with schema '{table_info[0]}'. Recreating for FLOAT[{EMBEDDING_DIM}]...")
        con.execute("DROP TABLE gold.item_embeddings")

    con.execute(f"""
        CREATE TABLE IF NOT EXISTS gold.item_embeddings (
            item_id VARCHAR PRIMARY KEY,
            embedding FLOAT[{EMBEDDING_DIM}]
        )
    """)

    # ── pre-flight check ────────────────────────────────────────────────
    total_items = con.execute(
        "SELECT COUNT(*) FROM silver.unique_items"
    ).fetchone()[0]
    already_done = con.execute(
        "SELECT COUNT(*) FROM gold.item_embeddings"
    ).fetchone()[0]
    pending = total_items - already_done

    if limit is not None:
        effective_pending = min(pending, limit)
    else:
        effective_pending = pending

    print(f"[Gold] unique_items total: {total_items:,}")
    print(f"[Gold] Already embedded:   {already_done:,}")
    print(f"[Gold] Pending:            {pending:,}")
    if limit is not None:
        print(f"[Gold] --limit applied:     {effective_pending:,}")

    if effective_pending == 0:
        print("[Gold] Nothing to embed — all items already have vectors.")
        con.close()
        return 0

    # ── load model once ─────────────────────────────────────────────────
    model = _load_model()

    # ── chunked embed + checkpoint loop ─────────────────────────────────
    embedded_total = 0
    cumulative_tokens = 0
    cumulative_cost_usd = 0.0
    chunk_num = 0
    t_start = time.perf_counter()

    while embedded_total < effective_pending:
        chunk_num += 1
        fetch_size = min(DB_CHUNK_SIZE, effective_pending - embedded_total)

        # Fetch a chunk of items not yet in gold.item_embeddings
        rows = con.execute(f"""
            SELECT s.item_id, s."Notice Title", s."Item Name", s."Item Description"
            FROM silver.unique_items s
            LEFT JOIN gold.item_embeddings g ON s.item_id = g.item_id
            WHERE g.item_id IS NULL
            LIMIT {fetch_size}
        """).fetchall()

        if not rows:
            break  # safety — nothing left

        # Build text payloads (strictly Notice Title, Item Name, Item Description)
        item_ids = []
        texts = []
        for row in rows:
            item_id, title, name, desc = row
            item_ids.append(item_id)
            doc_text = construct_doc_text(title, name, desc)
            texts.append(doc_text if doc_text else "procurement item")

        # Telemetry & Cost Computation
        batch_tokens, batch_cost = estimate_batch_cost(texts)
        cumulative_tokens += batch_tokens
        cumulative_cost_usd += batch_cost

        # Embed via Vertex AI
        print(f"\n[Gold] Chunk {chunk_num}: embedding {len(texts):,} items via Vertex AI ...", flush=True)
        t_chunk = time.perf_counter()
        vectors = _embed_batch(model, texts)
        embed_secs = time.perf_counter() - t_chunk

        # Append to gold.item_embeddings — bulk INSERT via registered DataFrame
        chunk_df = pd.DataFrame({
            "item_id": item_ids,
            "embedding": vectors,
        })
        con.register("_gold_chunk", chunk_df)
        con.execute("""
            INSERT INTO gold.item_embeddings
            SELECT item_id, embedding FROM _gold_chunk
        """)
        con.unregister("_gold_chunk")

        embedded_total += len(rows)
        elapsed = time.perf_counter() - t_start
        rate = embedded_total / elapsed if elapsed > 0 else 0
        pct = (embedded_total / effective_pending) * 100

        # Formatted terminal telemetry matching COST_AND_BUDGET_MONITORING.md
        print(
            f"[Gold] Chunk {chunk_num}: {len(rows):,} items embedded in {embed_secs:.1f}s | {rate:.0f} items/s\n"
            f"       Batch: {batch_tokens:,} tokens | Cost: ${batch_cost:.5f} USD\n"
            f"       Cumulative: {embedded_total:,}/{effective_pending:,} ({pct:.1f}%) | "
            f"{cumulative_tokens:,} tokens | Est Spend: ${cumulative_cost_usd:.5f} USD (~₱{cumulative_cost_usd * USD_TO_PHP:.2f} PHP)"
        )

    # ── summary ─────────────────────────────────────────────────────────
    total_secs = time.perf_counter() - t_start
    overall_rate = embedded_total / total_secs if total_secs > 0 else 0
    final_count = con.execute(
        "SELECT COUNT(*) FROM gold.item_embeddings"
    ).fetchone()[0]

    print(f"\n[Gold] Done. {embedded_total:,} items embedded in {total_secs:.1f}s ({overall_rate:.0f} items/s overall)")
    print(f"[Gold] Total Tokens: {cumulative_tokens:,} | Total Est Spend: ${cumulative_cost_usd:.5f} USD (~₱{cumulative_cost_usd * USD_TO_PHP:.2f} PHP)")
    print(f"[Gold] gold.item_embeddings now has {final_count:,} vectors")

    con.close()
    return embedded_total


# ─── CLI entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gold: generate embeddings for unique items via Google Vertex AI")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Max items to embed this run (e.g. 100 for smoke test, 5000 for sample)",
    )
    args = parser.parse_args()
    run_gold(limit=args.limit)
