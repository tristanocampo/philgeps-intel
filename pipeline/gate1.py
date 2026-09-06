"""
Gate 1 — Data Quality Evaluation.

Runs automated assertion checks on Silver-layer tables for a given quarter
before the pipeline is allowed to proceed to Gold (vector embedding).

Usage:
    run_quality_gate("2025-Q1")          # returns True or raises ValueError
    run_quality_gate("2025-Q1", strict=False)  # returns bool without raising
"""
import duckdb

try:
    import pipeline.bronze as bronze
except ModuleNotFoundError:
    import bronze as bronze


# ─── helpers ────────────────────────────────────────────────────────────────

def _count(con, table: str) -> int:
    """Safe row count — returns 0 if the table does not exist."""
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    except duckdb.CatalogException:
        return 0


def _query_count(con, sql: str) -> int:
    """Run an arbitrary COUNT query and return the scalar result."""
    return con.execute(sql).fetchone()[0]


class _Check:
    """One assertion result."""
    __slots__ = ("name", "category", "expected", "actual", "passed", "detail")

    def __init__(self, name: str, category: str, expected, actual, detail: str = ""):
        self.name = name
        self.category = category
        self.expected = expected
        self.actual = actual
        self.passed = (actual == expected)
        self.detail = detail


# ─── assertion runners ──────────────────────────────────────────────────────

def _row_conservation_checks(con, q: str) -> list[_Check]:
    """Verify no silent row loss at each Silver step."""
    checks = []

    # Bronze → grain split
    bronze_table = f"bronze.{q}_raw"
    awards_raw = f"silver.{q}_awards_raw"
    quarantine = f"silver.{q}_quarantine_no_award"

    bronze_count = _count(con, bronze_table)
    awards_raw_count = _count(con, awards_raw)
    quarantine_count = _count(con, quarantine)

    checks.append(_Check(
        name="Grain split row conservation",
        category="Row Conservation",
        expected=bronze_count,
        actual=awards_raw_count + quarantine_count,
        detail=f"bronze({bronze_count:,}) == awards_raw({awards_raw_count:,}) + quarantine({quarantine_count:,})",
    ))

    # Dedup → type & clean
    deduped = f"silver.{q}_awards_deduped"
    typed = f"silver.{q}_awards_typed"
    zero_amt = f"silver.{q}_awards_zero_amount"

    deduped_count = _count(con, deduped)
    typed_count = _count(con, typed)
    zero_count = _count(con, zero_amt)

    checks.append(_Check(
        name="Type & clean row conservation",
        category="Row Conservation",
        expected=deduped_count,
        actual=typed_count + zero_count,
        detail=f"deduped({deduped_count:,}) == typed({typed_count:,}) + zero_amount({zero_count:,})",
    ))

    return checks


def _null_type_safety_checks(con, typed_table: str) -> list[_Check]:
    """Contract Amount, Line Item No, and date-column sanity."""
    checks = []

    # Contract Amount must never be NULL or <= 0
    bad_amount = _query_count(con, f"""
        SELECT COUNT(*) FROM {typed_table}
        WHERE "Contract Amount" IS NULL OR "Contract Amount" <= 0
    """)
    checks.append(_Check(
        name="Contract Amount NOT NULL and > 0",
        category="Null & Type Safety",
        expected=0, actual=bad_amount,
        detail=f"{bad_amount:,} rows with NULL or non-positive Contract Amount",
    ))

    # Line Item No must never be NULL or <= 0
    bad_lineno = _query_count(con, f"""
        SELECT COUNT(*) FROM {typed_table}
        WHERE "Line Item No" IS NULL OR "Line Item No" <= 0
    """)
    checks.append(_Check(
        name="Line Item No NOT NULL and > 0",
        category="Null & Type Safety",
        expected=0, actual=bad_lineno,
        detail=f"{bad_lineno:,} rows with NULL or non-positive Line Item No",
    ))

    # Date columns: non-null values must be real DATE type with year >= 2000
    date_cols = [
        "Published Date", "Closing Date", "Published Date(Award)",
        "Award Date", "Notice to Proceed Date",
        "Contract Effectivity Date", "Contract End Date",
    ]
    for col in date_cols:
        bad_dates = _query_count(con, f"""
            SELECT COUNT(*) FROM {typed_table}
            WHERE "{col}" IS NOT NULL AND YEAR("{col}") < 2000
        """)
        checks.append(_Check(
            name=f'Date sanity: "{col}"',
            category="Null & Type Safety",
            expected=0, actual=bad_dates,
            detail=f"{bad_dates:,} rows with year < 2000",
        ))

    return checks


def _sentinel_checks(con, typed_table: str) -> list[_Check]:
    """Sentinels that should have been cleaned in Silver."""
    checks = []

    # Item Budget = -1 sentinel must be gone (converted to NULL)
    sentinel_budget = _query_count(con, f"""
        SELECT COUNT(*) FROM {typed_table}
        WHERE "Item Budget" = -1
    """)
    checks.append(_Check(
        name='Item Budget sentinel (-1) removed',
        category="Sentinel Values",
        expected=0, actual=sentinel_budget,
        detail=f"{sentinel_budget:,} rows still have Item Budget = -1",
    ))

    # No string column should contain the literal text "NULL"
    string_cols = [
        "Procuring Entity (PE)", "Notice Title", "Item Name",
        "Item Description", "Award Title", "Awardee Organization Name",
        "UNSPSC Code", "UNSPSC Description",
    ]
    literal_null_clauses = " OR ".join(f'"{c}" = \'NULL\'' for c in string_cols)
    literal_nulls = _query_count(con, f"""
        SELECT COUNT(*) FROM {typed_table}
        WHERE {literal_null_clauses}
    """)
    checks.append(_Check(
        name='No literal "NULL" strings in text columns',
        category="Sentinel Values",
        expected=0, actual=literal_nulls,
        detail=f'{literal_nulls:,} rows contain literal "NULL" text',
    ))

    return checks


def _whitespace_checks(con, typed_table: str) -> list[_Check]:
    """Critical text columns must have no leading/trailing/double whitespace."""
    checks = []
    critical_cols = [
        "Procuring Entity (PE)", "Notice Title",
        "Item Name", "Awardee Organization Name",
    ]

    for col in critical_cols:
        bad_ws = _query_count(con, f"""
            SELECT COUNT(*) FROM {typed_table}
            WHERE "{col}" IS NOT NULL AND (
                "{col}" != TRIM("{col}")
                OR "{col}" LIKE '%  %'
            )
        """)
        checks.append(_Check(
            name=f'Whitespace clean: "{col}"',
            category="Whitespace",
            expected=0, actual=bad_ws,
            detail=f"{bad_ws:,} rows with leading/trailing/double whitespace",
        ))

    return checks


def _unique_items_checks(con) -> list[_Check]:
    """Verify the unique_items catalog is sane."""
    checks = []

    # Table exists and has rows
    ui_count = _count(con, "silver.unique_items")
    checks.append(_Check(
        name="unique_items table exists and non-empty",
        category="Unique Items Catalog",
        expected=True, actual=(ui_count > 0),
        detail=f"{ui_count:,} items in catalog",
    ))

    # Primary key uniqueness (should be guaranteed by PK, but verify)
    if ui_count > 0:
        distinct_ids = _query_count(con, """
            SELECT COUNT(DISTINCT item_id) FROM silver.unique_items
        """)
        checks.append(_Check(
            name="item_id is 100% distinct",
            category="Unique Items Catalog",
            expected=ui_count, actual=distinct_ids,
            detail=f"total({ui_count:,}) vs distinct({distinct_ids:,})",
        ))

    # embedding column exists (schema check)
    has_embedding = _query_count(con, """
        SELECT COUNT(*) FROM information_schema.columns
        WHERE table_schema = 'silver'
          AND table_name = 'unique_items'
          AND column_name = 'embedding'
    """)
    checks.append(_Check(
        name="embedding column exists",
        category="Unique Items Catalog",
        expected=1, actual=has_embedding,
        detail="Column present" if has_embedding else "Column MISSING",
    ))

    return checks


# ─── report ─────────────────────────────────────────────────────────────────

def _print_report(checks: list[_Check], quarter: str) -> None:
    """Print a formatted quality gate summary table."""
    name_w = max(len(c.name) for c in checks)
    cat_w = max(len(c.category) for c in checks)

    header = f"{'Check':<{name_w}}  {'Category':<{cat_w}}  {'Result':>6}  Detail"
    sep = "-" * len(header)

    print()
    print("+" + "=" * (len(header) + 2) + "+")
    print(f"| {'GATE 1 -- DATA QUALITY REPORT':^{len(header)}} |")
    print(f"| {f'Quarter: {quarter}':^{len(header)}} |")
    print("+" + "=" * (len(header) + 2) + "+")
    print()
    print(header)
    print(sep)

    for c in checks:
        status = " PASS " if c.passed else " FAIL "
        marker = "[x]" if c.passed else "[ ]"
        print(f"{c.name:<{name_w}}  {c.category:<{cat_w}}  {marker}{status} {c.detail}")

    passed = sum(1 for c in checks if c.passed)
    total = len(checks)
    print(sep)
    print(f"Result: {passed}/{total} checks passed.")
    print()


# ─── public API ─────────────────────────────────────────────────────────────

def run_quality_gate(
    quarter: str,
    db_path: str = "data/philgeps.duckdb",
    strict: bool = True,
) -> bool:
    """
    Run all Gate 1 quality assertions for the given quarter.

    Returns True if every check passes.
    If strict=True (default), raises ValueError on any failure so that
    the pipeline halts before expensive Gold-layer work.
    """
    con = duckdb.connect(db_path, read_only=True)
    q = bronze.table_prefix(quarter)
    typed_table = f"silver.{q}_awards_typed"

    checks: list[_Check] = []
    checks.extend(_row_conservation_checks(con, q))
    checks.extend(_null_type_safety_checks(con, typed_table))
    checks.extend(_sentinel_checks(con, typed_table))
    checks.extend(_whitespace_checks(con, typed_table))
    checks.extend(_unique_items_checks(con))

    con.close()

    _print_report(checks, quarter)

    all_passed = all(c.passed for c in checks)

    if not all_passed and strict:
        failed = [c.name for c in checks if not c.passed]
        raise ValueError(
            f"Gate 1 Quality Checks Failed! "
            f"{len(failed)} assertion(s) failed: {', '.join(failed)}"
        )

    return all_passed


if __name__ == "__main__":
    run_quality_gate("2025-Q1")
