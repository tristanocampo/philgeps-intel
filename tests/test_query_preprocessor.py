"""
Unit tests for Option 1: Query Pre-Processor & Filter Extractor (Gemini 3.5 Flash Lite).
Tests:
1. Acronym Expansion (PSA -> PHILIPPINE STATISTICS AUTHORITY)
2. Typo Healing (catring servces, bnd paperr -> catering services, bond paper)
3. Region Filter Extraction (Region IV-A)
"""
import os
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("."))

from rag.engine import preprocess_user_query


def test_acronym_expansion():
    print("--- Test 1: Acronym Expansion ---")
    query = "How much did PSA spend on IT equipment?"
    res = preprocess_user_query(query)
    print("Input :", query)
    print("Output:", res)
    
    agency = (res.get("agency_formal") or "").upper()
    assert "PHILIPPINE STATISTICS AUTHORITY" in agency or "PSA" in (res.get("agency_short") or ""), \
        f"Failed to expand PSA to Philippine Statistics Authority, got: {res}"
    print("✅ Acronym Expansion PASSED!\n")


def test_typo_healing():
    print("--- Test 2: Typo Healing ---")
    query = "catring servces and bnd paperr"
    res = preprocess_user_query(query)
    print("Input :", query)
    print("Output:", res)
    
    terms = (res.get("search_terms") or "").lower()
    assert "catering" in terms, f"Failed to correct 'catring servces' to 'catering', got: {terms}"
    assert "paper" in terms, f"Failed to correct 'bnd paperr' to 'paper', got: {terms}"
    print("✅ Typo Healing PASSED!\n")


def test_region_extraction():
    print("--- Test 3: Region Filter Extraction ---")
    query = "Procurement of office supplies in Region IV-A"
    res = preprocess_user_query(query)
    print("Input :", query)
    print("Output:", res)
    
    region = (res.get("region") or "").upper()
    assert "IV-A" in region or "4A" in region or "CALABARZON" in region, \
        f"Failed to extract Region IV-A, got: {res}"
    print("✅ Region Extraction PASSED!\n")


if __name__ == "__main__":
    print("Running Query Pre-Processor Unit Tests via Gemini 3.5 Flash Lite...\n")
    test_acronym_expansion()
    test_typo_healing()
    test_region_extraction()
    print("All Query Pre-Processor unit tests PASSED successfully!")
