import duckdb

con = duckdb.connect("data/philgeps.duckdb")

con.execute("""
    CREATE OR REPLACE TABLE all_awards_typed AS
    SELECT
        * EXCLUDE ("Contract Amount", "Published Date", "Closing Date", "Published Date(Award)", 
                   "Award Date", "Notice to Proceed Date", "Contract Effectivity Date", "Contract End Date",
                   "Approved Budget of the Contract", "Item Budget", "Quantity", "Line Item No"),
        CAST("Contract Amount" AS DECIMAL(15,2)) AS "Contract Amount",
        CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Published Date" AS INTEGER)) DAY AS DATE) AS "Published Date",
        CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Closing Date" AS INTEGER)) DAY AS DATE) AS "Closing Date",
        CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Published Date(Award)" AS INTEGER)) DAY AS DATE) AS "Published Date(Award)",
        CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Award Date" AS INTEGER)) DAY AS DATE) AS "Award Date",
        CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Notice to Proceed Date" AS INTEGER)) DAY AS DATE) AS "Notice to Proceed Date",
        CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Contract Effectivity Date" AS INTEGER)) DAY AS DATE) AS "Contract Effectivity Date",
        CAST(DATE '1899-12-30' + INTERVAL (TRY_CAST("Contract End Date" AS INTEGER)) DAY AS DATE) AS "Contract End Date",
        CAST("Approved Budget of the Contract" AS DECIMAL(15,2)) AS "Approved Budget of the Contract",
        CASE 
            WHEN TRY_CAST("Item Budget" AS DOUBLE) = -1 THEN NULL 
            ELSE CAST("Item Budget" AS DECIMAL(15,2)) 
        END AS "Item Budget",
        CAST("Quantity" AS DOUBLE) AS "Quantity",
        CAST("Line Item No" AS INTEGER) AS "Line Item No"
    FROM all_awards_deduped
    WHERE TRY_CAST("Contract Amount" AS DOUBLE) != 0
""")

print(con.execute("SELECT COUNT(*) FROM all_awards_typed").fetchdf())
print(con.execute("DESCRIBE all_awards_typed").fetchdf())

con.close()