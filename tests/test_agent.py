"""
Automated Verification Suite for Schema-Aware Tool-Using Agent & Security Guardrails.
Tests:
1. Security Guardrails (SQL Injection & Malicious keywords blocked)
2. Top Supplier Ranking (DOH 2025)
3. Date / Quarter Bounded Aggregation (PSA Q1)
4. Extreme / Ordering Query (Largest Contract in Region VII)
5. Catalog Semantic Search (Catering Services for DOH in NCR)
"""
import sys
import os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("."))

from rag.agent import get_agent, validate_sql_security, SecurityException, execute_duckdb_sql


# ==============================================================================
# 1. SECURITY & GUARDRAILS TESTS
# ==============================================================================
def test_security_blocked_keywords():
    """Verify that destructive admin keywords are blocked by Python AST validator."""
    malicious_queries = [
        "DROP TABLE gold.all_awards",
        "DELETE FROM gold.all_awards WHERE 1=1",
        "INSERT INTO gold.all_awards VALUES ('hack')",
        "UPDATE gold.all_awards SET Region = 'Hacked'",
        "ALTER TABLE gold.all_awards DROP COLUMN Region",
        "COPY gold.all_awards TO '/tmp/stolen.csv'",
        "ATTACH 'evil.db' AS evil"
    ]
    for q in malicious_queries:
        try:
            validate_sql_security(q)
            assert False, f"Expected SecurityException for: {q}"
        except SecurityException as e:
            assert "Forbidden" in str(e) or "statement type" in str(e)


def test_security_blocked_semicolon_chaining():
    """Verify that multi-statement SQL injection attacks are rejected."""
    chained = "SELECT * FROM gold.all_awards; DROP TABLE gold.all_awards;"
    try:
        validate_sql_security(chained)
        assert False, "Expected SecurityException for chained SQL statements"
    except SecurityException as e:
        assert "Multi-statement" in str(e)


def test_security_valid_select_allowed():
    """Verify that clean SELECT statements pass validation and get LIMIT capped."""
    clean = 'SELECT "Awardee Organization Name", SUM("Contract Amount") FROM gold.all_awards GROUP BY "Awardee Organization Name"'
    safe = validate_sql_security(clean)
    assert safe.startswith("SELECT")
    assert "LIMIT 100" in safe


# ==============================================================================
# 2. TOP SUPPLIER QUERY TEST
# ==============================================================================
def test_agent_top_supplier_doh():
    agent = get_agent()
    res = agent.execute_query("Who was the top supplier for DOH in 2025?")
    print("\n--- Test: Top Supplier DOH 2025 ---")
    print(f"Tool Used: {res['tool_used']}")
    print(f"SQL Generated: {res.get('sql_query')}")
    print(f"Data Rows: {res['data_rows'][:2]}")
    print(f"Answer:\n{res['answer']}\n")

    assert res["tool_used"] == "sql"
    assert res["sql_query"] is not None
    assert len(res["data_rows"]) > 0
    assert len(res["answer"]) > 20


# ==============================================================================
# 3. DATE / QUARTER TEST
# ==============================================================================
def test_agent_psa_q1():
    agent = get_agent()
    res = agent.execute_query("How much did PSA spend on Q1?")
    print("\n--- Test: PSA Spend Q1 ---")
    print(f"Tool Used: {res['tool_used']}")
    print(f"SQL Generated: {res.get('sql_query')}")
    print(f"Data Rows: {res['data_rows'][:2]}")
    print(f"Answer:\n{res['answer']}\n")

    assert res["tool_used"] == "sql"
    assert res["sql_query"] is not None
    assert len(res["data_rows"]) > 0


# ==============================================================================
# 4. LARGEST CONTRACT TEST
# ==============================================================================
def test_agent_largest_contract_region_vii():
    agent = get_agent()
    res = agent.execute_query("What was the largest contract awarded in Region VII?")
    print("\n--- Test: Largest Contract Region VII ---")
    print(f"Tool Used: {res['tool_used']}")
    print(f"SQL Generated: {res.get('sql_query')}")
    print(f"Data Rows: {res['data_rows'][:2]}")
    print(f"Answer:\n{res['answer']}\n")

    assert res["tool_used"] == "sql"
    assert res["sql_query"] is not None
    assert len(res["data_rows"]) > 0


# ==============================================================================
# 5. CATALOG HYBRID SEARCH TEST
# ==============================================================================
def test_agent_catalog_search():
    agent = get_agent()
    res = agent.execute_query("Find catering services for DOH in NCR")
    print("\n--- Test: Catalog Search Catering DOH NCR ---")
    print(f"Tool Used: {res['tool_used']}")
    print(f"Data Rows: {len(res['data_rows'])} rows")
    print(f"Answer:\n{res['answer']}\n")

    assert res["tool_used"] in ("catalog_search", "sql")
    assert len(res["data_rows"]) > 0


if __name__ == "__main__":
    print("Running Security Guardrail Tests...")
    test_security_blocked_keywords()
    test_security_blocked_semicolon_chaining()
    test_security_valid_select_allowed()
    print("✅ All Security Guardrail Tests Passed!")

    print("\nRunning Dynamic SQL & Tool Agent Tests...")
    test_agent_top_supplier_doh()
    test_agent_psa_q1()
    test_agent_largest_contract_region_vii()
    test_agent_catalog_search()
    print("\n🎉 ALL AGENT VERIFICATION TESTS PASSED SUCCESSFULLY!")
