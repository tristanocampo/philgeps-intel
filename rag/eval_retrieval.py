"""
Gate 2: Retrieval Evaluation (Vector-Only vs Keyword-Only vs Hybrid Search).
Measures:
1. Hit Rate@5 (percentage of queries where target item is in top 5)
2. MRR (Mean Reciprocal Rank)
3. Retrieval Latency (ms)

Generates:
1. Console summary table
2. docs/EVALUATION_RESULTS.md markdown table
3. docs/eval_retrieval_metrics.png comparative bar chart (matplotlib)

Usage:
    python rag/eval_retrieval.py
    python rag/eval_retrieval.py --limit 100   # Fast evaluation on subset
"""
import os
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("."))

import json
import time
import argparse
from typing import Any
import duckdb
import matplotlib.pyplot as plt

from pipeline.search import (
    vector_search,
    keyword_search,
    reciprocal_rank_fusion,
    DB_PATH
)
from rag.engine import embed_query

DATASET_PATH = "data/ground_truth_eval.json"
MD_REPORT_PATH = "docs/EVALUATION_RESULTS.md"
CHART_PATH = "docs/eval_retrieval_metrics.png"


def evaluate_query(
    con: duckdb.DuckDBPyConnection,
    question: str,
    target_id: str,
    query_vector: list[float] | None,
    top_k: int = 5
) -> dict[str, dict[str, float]]:
    """
    Runs vector-only, keyword-only, and hybrid search for a query and computes
    Hit@K and Reciprocal Rank (RR) for each.
    """
    scores = {}

    # 1. Keyword-Only (BM25)
    t0 = time.perf_counter()
    kw_results = keyword_search(con, question, top_k=top_k)
    kw_lat = (time.perf_counter() - t0) * 1000

    kw_hit = 0.0
    kw_rr = 0.0
    for r, item in enumerate(kw_results, start=1):
        if item["item_id"] == target_id:
            kw_hit = 1.0
            kw_rr = 1.0 / r
            break
    scores["Keyword (BM25)"] = {"hit": kw_hit, "rr": kw_rr, "lat": kw_lat}

    # 2. Vector-Only (HNSW)
    vec_results = []
    vec_lat = 0.0
    if query_vector is not None:
        t0 = time.perf_counter()
        vec_results = vector_search(con, query_vector, top_k=top_k)
        vec_lat = (time.perf_counter() - t0) * 1000

    vec_hit = 0.0
    vec_rr = 0.0
    for r, item in enumerate(vec_results, start=1):
        if item["item_id"] == target_id:
            vec_hit = 1.0
            vec_rr = 1.0 / r
            break
    scores["Vector (HNSW)"] = {"hit": vec_hit, "rr": vec_rr, "lat": vec_lat}

    # 3. Hybrid Search (RRF)
    t0 = time.perf_counter()
    if vec_results and kw_results:
        fused = reciprocal_rank_fusion(vec_results, kw_results, top_k=top_k)
    elif vec_results:
        fused = vec_results[:top_k]
    else:
        fused = kw_results[:top_k]
    hybrid_lat = (time.perf_counter() - t0) * 1000 + kw_lat + vec_lat

    hyb_hit = 0.0
    hyb_rr = 0.0
    for r, item in enumerate(fused, start=1):
        if item["item_id"] == target_id:
            hyb_hit = 1.0
            hyb_rr = 1.0 / r
            break
    scores["Hybrid (BM25 + HNSW)"] = {"hit": hyb_hit, "rr": hyb_rr, "lat": hybrid_lat}

    return scores


def plot_metrics_chart(results: dict[str, dict[str, float]], output_file: str = CHART_PATH):
    """
    Renders and saves a side-by-side comparative bar chart for Hit Rate@5 and MRR.
    """
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    strategies = list(results.keys())
    hit_rates = [results[s]["hit_rate@5"] * 100 for s in strategies]
    mrrs = [results[s]["mrr"] for s in strategies]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))
    palette = ["#4A90E2", "#50E3C2", "#F5A623"]

    # 1. Hit Rate @ 5
    bars1 = ax1.bar(strategies, hit_rates, color=palette[:len(strategies)], width=0.55, edgecolor="#333", linewidth=1.2)
    ax1.set_title("Hit Rate @ 5 (%)", fontsize=13, fontweight="bold", pad=12)
    ax1.set_ylabel("Hit Rate (%)", fontsize=11)
    ax1.set_ylim(0, 105)
    ax1.grid(axis="y", linestyle="--", alpha=0.6)
    for bar in bars1:
        yval = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width() / 2, yval + 1.8, f"{yval:.1f}%", ha="center", va="bottom", fontweight="bold", fontsize=10)

    # 2. MRR (Mean Reciprocal Rank)
    bars2 = ax2.bar(strategies, mrrs, color=palette[:len(strategies)], width=0.55, edgecolor="#333", linewidth=1.2)
    ax2.set_title("Mean Reciprocal Rank (MRR)", fontsize=13, fontweight="bold", pad=12)
    ax2.set_ylabel("MRR Score (0 to 1.0)", fontsize=11)
    ax2.set_ylim(0, 1.05)
    ax2.grid(axis="y", linestyle="--", alpha=0.6)
    for bar in bars2:
        yval = bar.get_height()
        ax2.text(bar.get_x() + bar.get_width() / 2, yval + 0.02, f"{yval:.3f}", ha="center", va="bottom", fontweight="bold", fontsize=10)

    plt.tight_layout()
    plt.savefig(output_file, dpi=300)
    plt.close()
    print(f"[Gate 2 Evaluation] Comparative chart saved to: {output_file}")


def save_markdown_report(results: dict[str, dict[str, float]], total_queries: int, output_file: str = MD_REPORT_PATH):
    """
    Saves the evaluation benchmark report in GitHub Markdown format.
    """
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    lines = [
        "# Gate 2: Retrieval Evaluation Results (LLM Zoomcamp Rubric)",
        f"\n**Benchmark Dataset:** `{total_queries}` Ground Truth Queries evaluated across DuckDB persistent storage.",
        "\n### Summary Comparison Table\n",
        "| Retrieval Strategy | Hit Rate @ 5 (%) | MRR (Mean Reciprocal Rank) | Avg Latency (ms) |",
        "| :--- | :---: | :---: | :---: |"
    ]
    for s, m in results.items():
        lines.append(f"| **{s}** | {m['hit_rate@5'] * 100:.1f}% | {m['mrr']:.3f} | {m['avg_latency_ms']:.1f} ms |")

    lines.append("\n### Visual Performance Chart\n")
    lines.append("![Retrieval Evaluation Comparison](eval_retrieval_metrics.png)\n")
    lines.append("### Key Takeaways")
    lines.append("- **Hybrid Search (BM25 + HNSW with RRF)** combines lexical precision with semantic embeddings.")
    lines.append("- Exact tender codes and brand names are successfully captured by DuckDB FTS BM25.")
    lines.append("- Conceptual/semantic variations are retrieved by Vertex AI text-embedding-005 embeddings with DuckDB HNSW vector index.")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[Gate 2 Evaluation] Markdown report saved to: {output_file}")


def run_evaluation(
    dataset_path: str = DATASET_PATH,
    limit: int | None = None,
    db_path: str = DB_PATH
):
    print("=" * 75)
    print("GATE 2: RETRIEVAL EVALUATION (VECTOR vs KEYWORD vs HYBRID)")
    print("=" * 75)

    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"Evaluation dataset not found at: {dataset_path}. Run rag/eval_ground_truth.py first.")

    with open(dataset_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if limit is not None:
        data = data[:limit]

    total_queries = len(data)
    print(f"[Gate 2 Evaluation] Evaluating {total_queries} queries ...")

    con = duckdb.connect(db_path, read_only=True)

    totals = {
        "Vector (HNSW)": {"hits": 0.0, "rr_sum": 0.0, "lat_sum": 0.0},
        "Keyword (BM25)": {"hits": 0.0, "rr_sum": 0.0, "lat_sum": 0.0},
        "Hybrid (BM25 + HNSW)": {"hits": 0.0, "rr_sum": 0.0, "lat_sum": 0.0}
    }

    t_start = time.perf_counter()

    for idx, item in enumerate(data, start=1):
        q = item["question"]
        target_id = item["target_item_id"]

        # Note: In evaluation, we attempt query embedding if available
        # To avoid rate-limiting or high latency across hundreds of queries,
        # we can embed or fall back to keyword + existing catalog vector lookup
        q_vec = embed_query(q)

        eval_result = evaluate_query(con, q, target_id, q_vec, top_k=5)

        for strat, scores in eval_result.items():
            totals[strat]["hits"] += scores["hit"]
            totals[strat]["rr_sum"] += scores["rr"]
            totals[strat]["lat_sum"] += scores["lat"]

        if idx % 25 == 0 or idx == total_queries:
            print(f"  Processed {idx}/{total_queries} queries ({(idx/total_queries)*100:.1f}%) ...", flush=True)

    con.close()

    # Aggregate final metrics
    metrics = {}
    for strat, v in totals.items():
        metrics[strat] = {
            "hit_rate@5": v["hits"] / total_queries,
            "mrr": v["rr_sum"] / total_queries,
            "avg_latency_ms": v["lat_sum"] / total_queries
        }

    # Print summary table
    print("\n" + "=" * 75)
    print("FINAL EVALUATION RESULTS")
    print("=" * 75)
    print(f"{'Strategy':<25} | {'Hit Rate@5':<12} | {'MRR':<10} | {'Avg Latency (ms)':<15}")
    print("-" * 75)
    for s, m in metrics.items():
        print(f"{s:<25} | {m['hit_rate@5']*100:>10.1f}% | {m['mrr']:>10.3f} | {m['avg_latency_ms']:>15.1f}")
    print("=" * 75)

    # Save Markdown report and Matplotlib chart
    save_markdown_report(metrics, total_queries)
    plot_metrics_chart(metrics)

    print(f"\n[Gate 2 Evaluation] Total evaluation runtime: {time.perf_counter() - t_start:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Gate 2 Retrieval Evaluation")
    parser.add_argument("--dataset", type=str, default=DATASET_PATH, help="Path to ground truth JSON dataset")
    parser.add_argument("--limit", type=int, default=50, help="Subset limit for quick benchmarking")
    args = parser.parse_args()
    run_evaluation(dataset_path=args.dataset, limit=args.limit)
