"""
Unit and integration test for rag.engine.
"""
import os
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("."))

from rag.engine import ask_philgeps


def test_rag_chain_fallback_or_live():
    print("[Test] Running ask_philgeps('Bond Paper A4') ...")
    res = ask_philgeps("Bond Paper A4", top_k=5)
    
    assert "answer" in res, "RAG response should contain 'answer'"
    assert res["answer"] is not None and len(res["answer"]) > 10, "Answer should not be empty"
    assert "search_output" in res
    assert "latency_ms" in res
    assert res["latency_ms"] > 0
    
    print("\n--- RAG Response ---")
    print(res["answer"])
    print(f"\nLatency: {res['latency_ms']:.1f}ms | Used Vector: {res['used_vector']} | Used LLM: {res['used_llm']}")
    print("--- Test Passed Successfully ---")


if __name__ == "__main__":
    test_rag_chain_fallback_or_live()
