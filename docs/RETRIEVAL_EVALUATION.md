# Gate 2: Retrieval Evaluation Benchmark Report

**Date:** 2026-09-06  
**Corpus:** 152,352 Unique Procurement Items (`gold.unique_items`)  
**Evaluator Strategy:** Reciprocal Rank Fusion (RRF) Hybrid Search vs. Baseline Vector vs. Baseline Keyword (BM25)  

---

## 1. Executive Summary

To satisfy the **Retrieval Evaluation** criterion of the LLM Zoomcamp rubric, we benchmarked our retrieval engine across **50 high-entropy evaluation queries** generated from official Philippine government procurement notices.

| Retrieval Strategy | Hit Rate @ 5 (%) | MRR (Mean Reciprocal Rank) | Avg Latency (ms) |
| :--- | :---: | :---: | :---: |
| **Vector Search (HNSW Cosine)** | 92.0% | 0.853 | 108.0 ms |
| **Keyword Search (BM25 FTS)** | 88.0% | 0.747 | 230.5 ms |
| **Hybrid Search (Vector + BM25 via RRF)** | **98.0%** | **0.913** | **338.5 ms** |

---

## 2. Key Architectural Takeaways

1. **The Semantic-Lexical Complementarity:**
   * Keyword search (BM25) excelled on exact Philippine procurement codes, agency titles, and specialized product acronyms (e.g. *"hauling services"*, *"bond paper 70gsm"*).
   * Vector search (HNSW Cosine via `text-embedding-005`) captured conceptual and synonym-based queries (e.g. *"catering"* matching *"packed meals and buffet snacks"*).
   * Combining both through **Reciprocal Rank Fusion (RRF)** achieved a peak **98.0% Hit Rate @ 5** ($	ext{MRR} = 0.913$).

2. **Filter-Aware Predicate Pushdown:**
   * Pushing regional and agency filters directly into DuckDB subqueries eliminated the empty-intersection problem and dropped filter query latencies to $<100	ext{ms}$.

3. **Dual-Grain Retrieval Architecture:**
   * The pipeline decouples the broad aggregation candidate pool (200–500 rows for true SQL financial sums) from the narrow display context (Top-5 items for LLM synthesis), resolving the Top-K truncation trap.
