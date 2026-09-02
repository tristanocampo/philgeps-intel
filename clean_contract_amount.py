import duckdb
con = duckdb.connect("data/philgeps.duckdb")

# 1. Pull out the 2 zero-amount rows into their own quarantine table
con.execute("""
    CREATE OR REPLACE TABLE all_awards_zero_amount AS
    SELECT *
    FROM all_awards_deduped
    WHERE TRY_CAST("Contract Amount" AS DOUBLE) = 0
""")

# 2. Build the next-stage clean table: real DECIMAL type, zero-rows excluded
con.execute("""
    CREATE OR REPLACE TABLE all_awards_typed AS
    SELECT
        * EXCLUDE ("Contract Amount"),
        CAST("Contract Amount" AS DECIMAL(15,2)) AS "Contract Amount"
    FROM all_awards_deduped
    WHERE TRY_CAST("Contract Amount" AS DOUBLE) != 0
""")

# 3. Sanity checks
print(con.execute("SELECT COUNT(*) FROM all_awards_zero_amount").fetchdf())
print(con.execute("SELECT COUNT(*) FROM all_awards_typed").fetchdf())
print(con.execute("DESCRIBE all_awards_typed").fetchdf())