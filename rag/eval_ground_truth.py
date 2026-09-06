"""
Ground truth evaluation set generator for PhilGEPS Intelligence.
Generates a representative sample of test questions mapped to target item_ids,
spanning various procurement categories (UNSPSC categories).
Saves output to data/ground_truth_eval.json.

Usage:
    python rag/eval_ground_truth.py --sample-size 300
"""
import os
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("."))

import json
import time
import random
import argparse
import duckdb

from rag.engine import get_genai_client, DEFAULT_GEMINI_MODEL

DB_PATH = "data/philgeps.duckdb"
OUTPUT_PATH = "data/ground_truth_eval.json"

# Core hand-written domain benchmark queries representing typical user/auditor queries
CORE_BENCHMARKS = [
    {
        "query": "Bond Paper A4 70gsm office supplies",
        "search_term": "Bond Paper",
        "category": "Office Supplies"
    },
    {
        "query": "Catering services meals and snacks for seminar training",
        "search_term": "Catering Services",
        "category": "Food & Catering"
    },
    {
        "query": "Desktop computer Core i7 workstation",
        "search_term": "Desktop Computer",
        "category": "Information Technology"
    },
    {
        "query": "Medical supplies disposable surgical gloves syringes",
        "search_term": "Surgical Gloves",
        "category": "Medical & Healthcare"
    },
    {
        "query": "Heavy equipment asphalt road repair dump truck",
        "search_term": "Dump Truck",
        "category": "Vehicles & Heavy Equipment"
    },
    {
        "query": "Security services licensed security guard outpost",
        "search_term": "Security Services",
        "category": "Security & Defense"
    },
    {
        "query": "Janitorial cleaning supplies floor wax bleach disinfectant",
        "search_term": "Janitorial",
        "category": "Cleaning & Maintenance"
    },
    {
        "query": "Diesel fuel gasoline procurement for government vehicles",
        "search_term": "Fuel",
        "category": "Fuel & Lubricants"
    },
    {
        "query": "Air conditioning unit inverter split type installation",
        "search_term": "Air Conditioning",
        "category": "Appliances & HVAC"
    },
    {
        "query": "Construction materials cement gravel sand rebar",
        "search_term": "Cement",
        "category": "Civil Works & Construction"
    }
]


def clean_text(val: str | None) -> str:
    if not val or val.strip() == "NULL":
        return ""
    return str(val).strip()


def generate_queries_for_item(item: dict) -> list[str]:
    """
    Generates realistic procurement search queries based on an item's fields.
    """
    name = clean_text(item.get("Item Name"))
    title = clean_text(item.get("Notice Title"))
    desc = clean_text(item.get("Item Description"))
    unspsc = clean_text(item.get("UNSPSC Description"))

    queries = []

    if name:
        queries.append(f"Procurement of {name}")
        if unspsc and unspsc.lower() not in name.lower():
            queries.append(f"{name} {unspsc}")

    if title and title.lower() != name.lower():
        words = title.split()
        if len(words) > 3:
            queries.append(" ".join(words[:6]))

    if desc and len(desc.split()) > 3:
        queries.append(f"{name} {desc[:40]}".strip())

    return queries[:2]  # Keep up to 2 distinct queries per item


def build_ground_truth(
    sample_size: int = 300,
    db_path: str = DB_PATH,
    output_file: str = OUTPUT_PATH
) -> list[dict]:
    print(f"[Ground Truth] Connecting to {db_path} ...")
    con = duckdb.connect(db_path, read_only=True)

    # We sample from items that have embeddings in gold.item_embeddings
    # so they can be evaluated across both Vector and Keyword retrieval.
    print(f"[Ground Truth] Sampling {sample_size} diverse items with vector embeddings ...")
    query = """
        SELECT 
            u.item_id,
            u."Notice Title",
            u."Item Name",
            u."Item Description",
            u."UNSPSC Code",
            u."UNSPSC Description"
        FROM gold.item_embeddings e
        JOIN gold.unique_items u ON e.item_id = u.item_id
        WHERE u."Item Name" IS NOT NULL AND u."Item Name" != 'NULL'
        ORDER BY RANDOM()
        LIMIT $limit;
    """
    rows = con.execute(query, {"limit": sample_size}).fetchall()

    ground_truth_records = []
    item_lookup_map = {}

    for row in rows:
        item = {
            "item_id": row[0],
            "Notice Title": row[1],
            "Item Name": row[2],
            "Item Description": row[3],
            "UNSPSC Code": row[4],
            "UNSPSC Description": row[5]
        }
        item_lookup_map[row[0]] = item

        generated_q_list = generate_queries_for_item(item)
        for q in generated_q_list:
            ground_truth_records.append({
                "question": q,
                "target_item_id": item["item_id"],
                "target_item_name": item["Item Name"],
                "category": item["UNSPSC Description"] or "Uncategorized",
                "source": "auto-generated"
            })

    # Add hand-written benchmark core queries mapped to matching items in the DB
    print("[Ground Truth] Mapping core hand-written benchmarks ...")
    for bench in CORE_BENCHMARKS:
        match = con.execute("""
            SELECT item_id, "Item Name" 
            FROM gold.unique_items 
            WHERE LOWER("Item Name") LIKE LOWER($pat) OR LOWER("Notice Title") LIKE LOWER($pat)
            LIMIT 1;
        """, {"pat": f"%{bench['search_term']}%"}).fetchone()

        if match:
            ground_truth_records.append({
                "question": bench["query"],
                "target_item_id": match[0],
                "target_item_name": match[1],
                "category": bench["category"],
                "source": "hand-written benchmark"
            })

    con.close()

    # Save to disk
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(ground_truth_records, f, indent=2, ensure_ascii=False)

    print(f"[Ground Truth] Generated {len(ground_truth_records)} evaluation questions.")
    print(f"[Ground Truth] Saved dataset to: {output_file}")
    return ground_truth_records


def build_llm_ground_truth(
    sample_size: int = 50,
    db_path: str = DB_PATH,
    output_file: str = "data/ground_truth_llm_50.json",
    delay_seconds: float = 4.5
) -> list[dict]:
    """
    Generates realistic, high-entropy evaluation questions using Gemini 3.5 Flash Lite.
    Features:
    1. Safe 4.5s pacing (enforcing <= 13 RPM to honor free-tier limits).
    2. Incremental JSON checkpointing (resumes if interrupted).
    3. Multi-field context (Notice Title, Specs, Agency, Region, Awardee).
    """
    client = get_genai_client()
    if not client:
        raise RuntimeError("GEMINI_API_KEY is not set or valid in environment!")

    con = duckdb.connect(db_path, read_only=True)

    # Check for existing checkpoint
    records = []
    processed_ids = set()
    if os.path.exists(output_file):
        try:
            with open(output_file, "r", encoding="utf-8") as f:
                records = json.load(f)
                processed_ids = {r["target_item_id"] for r in records}
                print(f"[Ground Truth LLM] Found existing checkpoint with {len(records)} questions. Resuming...")
        except Exception:
            records = []
            processed_ids = set()

    if len(records) >= sample_size:
        print(f"[Ground Truth LLM] Already completed {len(records)}/{sample_size} questions.")
        con.close()
        return records

    needed = sample_size - len(records)
    print(f"[Ground Truth LLM] Sampling items with vector embeddings and full award context...")

    query = """
        SELECT 
            u.item_id,
            u."Notice Title",
            u."Item Name",
            u."Item Description",
            u."UNSPSC Description",
            a."Procuring Entity (PE)",
            a.Region,
            a."Awardee Organization Name",
            a."Contract Amount"
        FROM gold.item_embeddings e
        JOIN gold.unique_items u ON e.item_id = u.item_id
        JOIN (
            SELECT 
                item_id,
                "Procuring Entity (PE)",
                Region,
                "Awardee Organization Name",
                "Contract Amount",
                ROW_NUMBER() OVER (PARTITION BY item_id ORDER BY "Contract Amount" DESC) as rn
            FROM gold.all_awards
        ) a ON u.item_id = a.item_id AND a.rn = 1
        WHERE u."Item Name" IS NOT NULL 
          AND LENGTH(u."Item Name") > 3
          AND u."Item Name" != 'NULL'
        ORDER BY RANDOM()
        LIMIT $limit;
    """
    rows = con.execute(query, {"limit": needed * 3}).fetchall()
    con.close()

    print(f"[Ground Truth LLM] Generating questions via {DEFAULT_GEMINI_MODEL} (pacing: {delay_seconds}s per query)...")
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    for row in rows:
        if len(records) >= sample_size:
            break

        item_id = row[0]
        if item_id in processed_ids:
            continue

        item_data = {
            "item_id": item_id,
            "notice_title": clean_text(row[1]),
            "item_name": clean_text(row[2]),
            "item_desc": clean_text(row[3]),
            "category": clean_text(row[4]) or "General",
            "agency": clean_text(row[5]),
            "region": clean_text(row[6]),
            "awardee": clean_text(row[7]),
            "amount": float(row[8]) if row[8] is not None else 0.0
        }

        # Skip generic one-word titles without enough detail to identify uniquely
        if len(item_data["item_name"]) < 4 and len(item_data["notice_title"]) < 4:
            continue

        prompt = f"""You are an evaluation benchmark generator for a Philippine public procurement (PhilGEPS) intelligence system.

Given this real tender record:
- Item Name: {item_data['item_name']}
- Notice Title: {item_data['notice_title']}
- Description: {item_data['item_desc']}
- UNSPSC Category: {item_data['category']}
- Procuring Agency: {item_data['agency']}
- Region: {item_data['region']}
- Awardee: {item_data['awardee']}
- Contract Amount: ₱{item_data['amount']:,.2f}

Generate 1 realistic, natural question that a citizen, journalist, or public auditor would ask that should lead specifically to this contract.
Guidelines:
1. Make it natural and conversational.
2. Incorporate distinguishing context (e.g. the specific project or purpose, agency name or acronym, region, or equipment details).
3. Do NOT make it a generic 1-word query like "Procurement of Goods" or "Meals".
4. Output ONLY the question string as plain text with no quotes, preamble, or markdown.
"""
        question = None
        for attempt in range(3):
            try:
                resp = client.models.generate_content(
                    model=DEFAULT_GEMINI_MODEL,
                    contents=prompt
                )
                question = resp.text.strip().strip('"').strip("'")
                break
            except Exception as e:
                print(f"[Ground Truth LLM] Attempt {attempt+1} notice: {e}. Backing off 10s...")
                time.sleep(10)

        if not question:
            continue

        record = {
            "question": question,
            "target_item_id": item_id,
            "target_item_name": item_data["item_name"],
            "category": item_data["category"],
            "agency": item_data["agency"],
            "region": item_data["region"],
            "expected_awardee": item_data["awardee"],
            "expected_amount": item_data["amount"],
            "source": "gemini-llm-ground-truth"
        }
        records.append(record)
        processed_ids.add(item_id)

        # Checkpoint incrementally to disk
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)

        print(f"[{len(records)}/{sample_size}] Q: \"{question}\" -> Item: {item_data['item_name'][:35]}")

        # Rate-limiting pacing shield
        time.sleep(delay_seconds)

    print(f"\n[Ground Truth LLM] Done! Successfully saved {len(records)} evaluation questions to: {output_file}")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate ground truth Q&A evaluation dataset")
    parser.add_argument("--sample-size", type=int, default=50, help="Number of items to sample")
    parser.add_argument("--use-llm", action="store_true", help="Use Gemini 3.5 Flash Lite to generate realistic questions")
    parser.add_argument("--output", type=str, default=None, help="Output JSON file path")
    parser.add_argument("--delay", type=float, default=4.5, help="Pacing delay in seconds between API requests (default 4.5s)")
    args = parser.parse_args()

    if args.use_llm:
        out = args.output or "data/ground_truth_llm_50.json"
        build_llm_ground_truth(sample_size=args.sample_size, output_file=out, delay_seconds=args.delay)
    else:
        out = args.output or OUTPUT_PATH
        build_ground_truth(sample_size=args.sample_size, output_file=out)
