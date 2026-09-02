"""
Bronze stage: raw ingestion.
Reads a quarterly xlsx file, tags it with a quarter label, and writes it
untouched (all text, no type guessing) to a persistent DuckDB table.
"""
import duckdb


def table_prefix(quarter: str) -> str:
    """
    Converts a human-readable quarter label like "2025-Q1" into a safe,
    collision-proof table-name prefix like "y2025_q1".

    Table names need to start with a letter, and "2025-Q1" (with a dash)
    isn't a safe identifier either - this normalizes both issues at once.
    Used by both bronze.py and silver.py so every stage names its tables
    the same consistent way for a given quarter.
    """
    return "y" + quarter.lower().replace("-", "_")


def build_bronze(quarter: str, xlsx_path: str, db_path: str = "data/philgeps.duckdb") -> str:
    """
    Ingests one quarter's raw xlsx into a Bronze table.

    quarter: full label like "2025-Q1" - stored as-is in its own "quarter"
             column (so filtering later stays human-readable), and also
             used (via table_prefix) to build a safe table name, so each
             quarter - including future years - gets its own table without
             overwriting a previous quarter's data.
    xlsx_path: path to the raw .xlsx file for this quarter.
    db_path: the one persistent DuckDB file used across the whole pipeline.

    Returns the name of the Bronze table that was created.
    """
    con = duckdb.connect(db_path)
    con.execute("INSTALL excel; LOAD excel;")
    con.execute("CREATE SCHEMA IF NOT EXISTS bronze")

    table_name = f"bronze.{table_prefix(quarter)}_raw"

    con.execute(f"""
        CREATE OR REPLACE TABLE {table_name} AS
        SELECT *, '{quarter}' AS quarter
        FROM read_xlsx('{xlsx_path}', all_varchar=true)
    """)

    row_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
    print(f"[Bronze] {quarter}: {row_count:,} rows -> table '{table_name}'")

    con.close()
    return table_name


if __name__ == "__main__":
    build_bronze("2025-Q1", "data/raw/2025/Q1.xlsx")