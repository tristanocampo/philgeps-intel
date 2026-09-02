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
except ModuleNotFoundError:
    import utils as utils
    import bronze as bronze


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
    Casts money/date/numeric columns to real types, applies the two known
    sentinel-value fixes (Item Budget -1, Contract Duration 0), and trims
    whitespace on the free-text/entity columns known to need it.

    Everything happens in ONE pass, built fresh from the deduped (still-text)
    table - never layered on top of a previously-typed table - so there's
    no risk of the overwrite bug we hit earlier in the project.
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


def run_silver(quarter: str, bronze_table: str, db_path: str = "data/philgeps.duckdb") -> str:
    """Runs the full Silver stage for one quarter, in order. Returns the final typed table name."""
    awards_raw_table, _ = grain_split(quarter, bronze_table, db_path)
    deduped_table = deduplicate(quarter, awards_raw_table, db_path)
    typed_table = type_and_clean(quarter, deduped_table, db_path)
    return typed_table


if __name__ == "__main__":
    bronze_table = bronze.build_bronze("2025-Q1", "data/raw/2025/Q1.xlsx")
    run_silver("2025-Q1", bronze_table)