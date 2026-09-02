import duckdb
import pandas as pd

con = duckdb.connect("data/philgeps.duckdb")
print(con.execute("SELECT table_schema, table_name FROM information_schema.tables").fetchdf())

# print(con.execute("SHOW TABLES").fetchdf())

# result = con.execute("""
#     SELECT 
#         COUNT(*) AS total_rows,
#         COUNT(DISTINCT "Award Notice Status") AS distinct_values,
#         COUNT(*) FILTER (WHERE "Award Notice Status" IS == NULL) AS null_count
#     FROM q1_raw
# """).fetchdf()
# print(result)