"""
Silver stage: grain split, deduplication, and full typing/cleaning.
Everything reads from and writes to tables in the same persistent
DuckDB file (data/philgeps.duckdb) - each quarter gets its own set of
quarter-prefixed tables so quarters never overwrite each other.
"""
import duckdb
try:
    import pipeline.utils as utils
    import pipeline.bronze as bronze
    import pipeline.gate1 as gate1
except ModuleNotFoundError:
    import utils as utils
    import bronze as bronze
    import gate1 as gate1


def _nullif_literal_nulls(con, table: str) -> int:
    """
    Convert literal 'NULL' strings to real SQL NULLs in every VARCHAR column
    of the given table. Uses information_schema to discover columns dynamically,
    so it's future-proof against new columns appearing in the source data.

    Returns the number of VARCHAR columns that were processed.
    """
    schema, tname = table.split(".")
    varchar_cols = [row[0] for row in con.execute(f"""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = '{schema}' AND table_name = '{tname}'
          AND data_type = 'VARCHAR'
    """).fetchall()]

    if not varchar_cols:
        return 0

    set_clauses = ", ".join(f'"{c}" = NULLIF("{c}", \'NULL\')' for c in varchar_cols)
    where_clauses = " OR ".join(f'"{c}" = \'NULL\'' for c in varchar_cols)
    con.execute(f"UPDATE {table} SET {set_clauses} WHERE {where_clauses}")

    return len(varchar_cols)

def grain_split(quarter: str, bronze_table: str, db_path: str = "data/philgeps.duckdb") -> tuple[str, str]:
    """
    Splits Bronze data into real awards (has a valid Contract Amount) vs.
    bid-only rows that never reached an award (parked, not deleted).
    """
    con = duckdb.connect(db_path)
    con.execute("CREATE SCHEMA IF NOT EXISTS silver")
    q = bronze.table_prefix(quarter)
    awards_table = f"silver.{q}_awards_raw"
    quarantine_table = f"silver.{q}_quarantine_no_award"

    con.execute(f"""
        CREATE OR REPLACE TABLE {awards_table} AS
        SELECT * FROM {bronze_table}
        WHERE "Contract Amount" IS NOT NULL AND "Contract Amount" != 'NULL'
    """)
    con.execute(f"""
        CREATE OR REPLACE TABLE {quarantine_table} AS
        SELECT * FROM {bronze_table}
        WHERE "Contract Amount" IS NULL OR "Contract Amount" = 'NULL'
    """)

    counts = con.execute(f"""
        SELECT
            (SELECT COUNT(*) FROM {awards_table}) AS awards,
            (SELECT COUNT(*) FROM {quarantine_table}) AS quarantine,
            (SELECT COUNT(*) FROM {bronze_table}) AS original
    """).fetchdf()
    print(f"[Silver: Grain Split] {quarter}:\n{counts.to_string(index=False)}")

    con.close()
    return awards_table, quarantine_table


def deduplicate(quarter: str, awards_raw_table: str, db_path: str = "data/philgeps.duckdb") -> str:
    """Removes exact full-row duplicates (every column matching)."""
    con = duckdb.connect(db_path)
    con.execute("CREATE SCHEMA IF NOT EXISTS silver")
    out_table = f"silver.{bronze.table_prefix(quarter)}_awards_deduped"

    con.execute(f"CREATE OR REPLACE TABLE {out_table} AS SELECT DISTINCT * FROM {awards_raw_table}")

    before = con.execute(f"SELECT COUNT(*) FROM {awards_raw_table}").fetchone()[0]
    after = con.execute(f"SELECT COUNT(*) FROM {out_table}").fetchone()[0]
    print(f"[Silver: Dedup] {quarter}: {before:,} -> {after:,} (removed {before - after:,} exact duplicates)")

    con.close()
    return out_table


def type_and_clean(quarter: str, deduped_table: str, db_path: str = "data/philgeps.duckdb") -> str:
    """
    Casts money/date/numeric columns to real types, applies the known
    sentinel-value fixes (Item Budget -1, Contract Duration 0), trims
    whitespace on the free-text/entity columns, and converts all literal
    'NULL' strings to real SQL NULLs across every VARCHAR column.

    Everything is built fresh from the deduped (still-text) table - never
    layered on top of a previously-typed table - so there's no risk of the
    overwrite bug we hit earlier in the project.
    """
    con = duckdb.connect(db_path)
    con.execute("CREATE SCHEMA IF NOT EXISTS silver")
    q = bronze.table_prefix(quarter)
    typed_table = f"silver.{q}_awards_typed"
    zero_table = f"silver.{q}_awards_zero_amount"

    whitespace_cols = ["Procuring Entity (PE)", "Notice Title", "Item Name",
                        "Item Description", "Award Title", "Awardee Organization Name"]
    whitespace_select = ",\n            ".join(
        f'{utils.whitespace_fix_expr(c)} AS "{c}"' for c in whitespace_cols
    )
    exclude_list = ", ".join(f'"{c}"' for c in [
        "Contract Amount", "Published Date", "Closing Date", "Published Date(Award)",
        "Award Date", "Notice to Proceed Date", "Contract Effectivity Date", "Contract End Date",
        "Approved Budget of the Contract", "Item Budget", "Quantity", "Line Item No",
        "Contract Duration", *whitespace_cols
    ])

    con.execute(f"""
        CREATE OR REPLACE TABLE {typed_table} AS
        SELECT
            * EXCLUDE ({exclude_list}),
            CAST("Contract Amount" AS DECIMAL(15,2)) AS "Contract Amount",
            CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Published Date" AS INTEGER)) DAY AS DATE) AS "Published Date",
            CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Closing Date" AS INTEGER)) DAY AS DATE) AS "Closing Date",
            CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Published Date(Award)" AS INTEGER)) DAY AS DATE) AS "Published Date(Award)",
            CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Award Date" AS INTEGER)) DAY AS DATE) AS "Award Date",
            CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Notice to Proceed Date" AS INTEGER)) DAY AS DATE) AS "Notice to Proceed Date",
            CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Contract Effectivity Date" AS INTEGER)) DAY AS DATE) AS "Contract Effectivity Date",
            CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Contract End Date" AS INTEGER)) DAY AS DATE) AS "Contract End Date",
            CAST("Approved Budget of the Contract" AS DECIMAL(15,2)) AS "Approved Budget of the Contract",
            CASE WHEN TRY_CAST("Item Budget" AS DOUBLE) = -1 THEN NULL
                 ELSE CAST("Item Budget" AS DECIMAL(15,2)) END AS "Item Budget",
            CAST("Quantity" AS DOUBLE) AS "Quantity",
            CAST("Line Item No" AS INTEGER) AS "Line Item No",
            CASE WHEN "Contract Duration" = '0' THEN NULL
                 ELSE TRY_CAST("Contract Duration" AS INTEGER) END AS "Contract Duration",
            {whitespace_select}
        FROM {deduped_table}
        WHERE TRY_CAST("Contract Amount" AS DOUBLE) != 0
    """)

    # Convert literal 'NULL' strings → real NULLs across ALL VARCHAR columns.
    # Done dynamically via information_schema so it's future-proof — any new
    # text column added to the source data is automatically covered.
    nullif_count = _nullif_literal_nulls(con, typed_table)
    if nullif_count > 0:
        print(f"[Silver: Type & Clean] {quarter}: converted literal 'NULL' strings "
              f"to real NULLs in {nullif_count} VARCHAR column(s)")

    con.execute(f"""
        CREATE OR REPLACE TABLE {zero_table} AS
        SELECT * FROM {deduped_table}
        WHERE TRY_CAST("Contract Amount" AS DOUBLE) = 0
    """)

    typed_count = con.execute(f"SELECT COUNT(*) FROM {typed_table}").fetchone()[0]
    zero_count = con.execute(f"SELECT COUNT(*) FROM {zero_table}").fetchone()[0]
    print(f"[Silver: Type & Clean] {quarter}: {typed_count:,} rows -> table '{typed_table}'")
    print(f"[Silver: Type & Clean] {quarter}: {zero_count:,} zero-amount rows parked -> table '{zero_table}'")

    con.close()
    return typed_table


def build_unique_items(quarter: str, typed_table: str, db_path: str = "data/philgeps.duckdb") -> str:
    """
    Builds/extends the item-level table used for embeddings later.
 
    This is different from the row-level dedup already done in
    deduplicate() - that step removed accidental exact-copy rows.
    This step groups DIFFERENT, legitimate award transactions that
    happen to describe the same real-world item (e.g. "Bond Paper A4"
    bought by two different agencies in two different real purchases),
    so each distinct item only needs to be embedded once.
 
    item_id = MD5 hash of the lowercased Notice Title + Item Name +
    Item Description, per the original project design. Lowercasing
    first means casing differences don't create false-different items.
 
    Unlike every other Silver table, unique_items is NOT quarter-prefixed
    - it's one single table that accumulates across all quarters. Only
    item_ids not already present get inserted, so re-running a quarter,
    or running a new one, never creates duplicate item entries.
 
    The "embedding" column is created here as an empty placeholder
    (NULL for every row). Filling it in is Gold's job, not Silver's -
    this function never touches that column's values, only its existence.
    """
    con = duckdb.connect(db_path)
    con.execute("CREATE SCHEMA IF NOT EXISTS silver")
    con.execute("""
        CREATE TABLE IF NOT EXISTS silver.unique_items (
            item_id VARCHAR PRIMARY KEY,
            "Notice Title" VARCHAR,
            "Item Name" VARCHAR,
            "Item Description" VARCHAR,
            "UNSPSC Code" VARCHAR,
            "UNSPSC Description" VARCHAR,
            embedding DOUBLE[]
        )
    """)
 
    before = con.execute("SELECT COUNT(*) FROM silver.unique_items").fetchone()[0]
 
    con.execute(f"""
        INSERT INTO silver.unique_items
        SELECT DISTINCT ON (item_id)
            item_id, "Notice Title", "Item Name", "Item Description",
            "UNSPSC Code", "UNSPSC Description", NULL AS embedding
        FROM (
            SELECT
                MD5(LOWER("Notice Title" || "Item Name" || "Item Description")) AS item_id,
                "Notice Title", "Item Name", "Item Description",
                "UNSPSC Code", "UNSPSC Description"
            FROM {typed_table}
        ) src
        WHERE item_id NOT IN (SELECT item_id FROM silver.unique_items)
    """)
 
    after = con.execute("SELECT COUNT(*) FROM silver.unique_items").fetchone()[0]
    print(f"[Silver: Unique Items] {quarter}: {after - before:,} new items added "
          f"(total items so far: {after:,})")
 
    con.close()
    return "silver.unique_items"



def run_silver(quarter: str, bronze_table: str, db_path: str = "data/philgeps.duckdb") -> str:
    """Runs the full Silver stage for one quarter, in order. Returns the final typed table name."""
    awards_raw_table, _ = grain_split(quarter, bronze_table, db_path)
    deduped_table = deduplicate(quarter, awards_raw_table, db_path)
    typed_table = type_and_clean(quarter, deduped_table, db_path)
    build_unique_items(quarter, typed_table, db_path)
    gate1.run_quality_gate(quarter, db_path)
    return typed_table


if __name__ == "__main__":
    bronze_table = bronze.build_bronze("2025-Q1", "data/raw/2025/Q1.xlsx")
    run_silver("2025-Q1", bronze_table)