"""
Shared SQL-expression helper used inside the Silver typing query.
"""


def whitespace_fix_expr(column: str) -> str:
    """
    Returns a SQL expression that trims leading/trailing whitespace and
    collapses multiple internal spaces into one, for the given column name.
    Used directly inside a SELECT, e.g.:

        SELECT {whitespace_fix_expr('Notice Title')} AS "Notice Title"
    """
    return f'TRIM(REGEXP_REPLACE("{column}", \'\\s+\', \' \', \'g\'))'