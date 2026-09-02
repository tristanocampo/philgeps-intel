import duckdb
import pandas as pd

con = duckdb.connect("data/philgeps.duckdb")
con.execute("INSTALL excel; LOAD excel;")

# TABLE CREATION: RAW IMPORT FROM XLSX FILE
# con.execute("""
#     CREATE OR REPLACE TABLE q1_raw AS
#     SELECT * FROM read_xlsx('data/raw/2025/Q1.xlsx', all_varchar=true)
# """)



# print(con.execute("SELECT COUNT(*) FROM q1_raw").fetchone())

# print(con.execute("DESCRIBE q1_raw").fetchdf())
# print(con.execute("SELECT COUNT(*) AS row_count FROM q1_raw").fetchdf())


# result = con.execute("""
#     SELECT 
#         COUNT(*) AS total_rows,
#         COUNT(DISTINCT "Awardee Organization Name") AS distinct_values,
#         COUNT(*) FILTER (WHERE "Awardee Organization Name" IS NULL) AS null_count
#     FROM q1_raw
# """).fetchdf()
# print(result)

# print(con.execute('SELECT DISTINCT "Awardee Organization Name" FROM q1_raw LIMIT 15').fetchdf())

# print(con.execute('SELECT COUNT(*) FILTER (WHERE "Bid Reference No." = 0) FROM q1_raw').fetchdf())
# print(con.execute('SELECT MIN("Line Item No"), MAX("Line Item No"), COUNT(*) FILTER (WHERE "Line Item No"=\'1\') FROM q1_raw').fetchdf())

# result = con.execute("""
#     SELECT 
#         COUNT(*) AS total_rows,
#         COUNT(*) FILTER (WHERE TRY_CAST("Line Item No" AS INTEGER) IS NULL) AS fails_cast,
#         MIN(TRY_CAST("Line Item No" AS INTEGER)) AS true_min,
#         MAX(TRY_CAST("Line Item No" AS INTEGER)) AS true_max
#     FROM q1_raw
# """).fetchdf()
# print(result)

# # See exactly what's breaking the cast
# print(con.execute("""
#     SELECT DISTINCT "Line Item No" 
#     FROM q1_raw 
#     WHERE TRY_CAST("Line Item No" AS INTEGER) IS NULL
#     LIMIT 20
# """).fetchdf())


# Finding Pattern on Line Item No = 0 and NULL values
# result = con.execute("""
#     SELECT 
#         "Bid Notice Status",
#         "Award Notice Status",
#         COUNT(*) AS row_count
#     FROM q1_raw
#     WHERE "Line Item No" = 'NULL'
#     GROUP BY "Bid Notice Status", "Award Notice Status"
#     ORDER BY row_count DESC
#     LIMIT 15
# """).fetchdf()
# print(result)


# Creating table for awarded and quarantine no unawarded bids
# The "real" awarded rows
# con.execute("""
#     CREATE OR REPLACE TABLE all_awards_raw AS
#     SELECT *
#     FROM q1_raw
#     WHERE "Award Notice Status" IS NOT NULL
# """)

# # The parked, unawarded rows — never deleted, just set aside
# con.execute("""
#     CREATE OR REPLACE TABLE quarantine_no_award AS
#     SELECT *
#     FROM q1_raw
#     WHERE "Award Notice Status" IS NULL
# """)

# # Sanity check: do the two splits add up to the original total?
# print(con.execute("""
#     SELECT 
#         (SELECT COUNT(*) FROM all_awards_raw) AS awards_count,
#         (SELECT COUNT(*) FROM quarantine_no_award) AS quarantine_count,
#         (SELECT COUNT(*) FROM q1_raw) AS original_count
# """).fetchdf())


# print(con.execute("""
#     SELECT "Award Notice Status", COUNT(*) AS row_count
#     FROM q1_raw
#     GROUP BY "Award Notice Status"
#     ORDER BY row_count DESC
# """).fetchdf())


# print(con.execute("""
#     SELECT "Bid Notice Status", "Award Notice Status", COUNT(*) AS row_count
#     FROM q1_raw
#     GROUP BY "Bid Notice Status", "Award Notice Status"
#     ORDER BY row_count DESC
# """).fetchdf())



# print(con.execute("""
#     SELECT 
#         "Bid Notice Status", 
#         "Award Notice Status",
#         COUNT(*) AS row_count,
#         COUNT(*) FILTER (WHERE "Contract Amount" IS NOT NULL AND "Contract Amount" != 'NULL') AS has_contract_amount
#     FROM q1_raw
#     WHERE "Bid Notice Status" = 'Closed' AND "Award Notice Status" != 'NULL'
#     GROUP BY "Bid Notice Status", "Award Notice Status"
# """).fetchdf())



# TABLE CREATION: ALL AWARDS AND QUARANTINE
# CONTRACT AMOUNT IS THE BASIS FOR AWARDED CONTRACTS THAT CONSTITUTES TO REAL SPENT
# con.execute("""
#     CREATE OR REPLACE TABLE all_awards_raw AS
#     SELECT *
#     FROM q1_raw
#     WHERE "Contract Amount" IS NOT NULL 
#       AND "Contract Amount" != 'NULL'
# """)

# con.execute("""
#     CREATE OR REPLACE TABLE quarantine_no_award AS
#     SELECT *
#     FROM q1_raw
#     WHERE "Contract Amount" IS NULL 
#        OR "Contract Amount" = 'NULL'
# """)

# print(con.execute("""
#     SELECT 
#         (SELECT COUNT(*) FROM all_awards_raw) AS awards_count,
#         (SELECT COUNT(*) FROM quarantine_no_award) AS quarantine_count,
#         (SELECT COUNT(*) FROM q1_raw) AS original_count
# """).fetchdf())





# print(con.execute("""
#     SELECT "Notice Title", "Item Name", "Contract Amount", "Awardee Organization Name", "Award Date"
#     FROM all_awards_raw
#     LIMIT 15
# """).fetchdf())



# pd.set_option('display.max_columns', None)
# pd.set_option('display.width', 200)
# pd.set_option('display.max_colwidth', 40)

# Focus just on Contract Amount for now — that's the column we're deciding how to clean
# print(con.execute("""
#     SELECT "Contract Amount"
#     FROM all_awards_raw
#     LIMIT 20
# """).fetchdf().to_string())

# result = con.execute("""
#     SELECT 
#         COUNT(*) AS total_rows,
#         COUNT(*) FILTER (WHERE TRY_CAST("Contract Amount" AS DOUBLE) IS NULL) AS fails_cast,
#         MIN(TRY_CAST("Contract Amount" AS DOUBLE)) AS true_min,
#         MAX(TRY_CAST("Contract Amount" AS DOUBLE)) AS true_max
#     FROM all_awards_raw
# """).fetchdf()
# print(result)

# pd.set_option('display.max_colwidth', 50)

# print("=== ZERO-VALUE ROWS ===")
# print(con.execute("""
#     SELECT COUNT(*) AS zero_count
#     FROM all_awards_raw
#     WHERE TRY_CAST("Contract Amount" AS DOUBLE) = 0
# """).fetchdf())

# print("\n=== TOP 10 HIGHEST CONTRACTS ===")
# print(con.execute("""
#     SELECT "Notice Title", "Contract Amount", "Awardee Organization Name", "Procuring Entity (PE)"
#     FROM all_awards_raw
#     ORDER BY TRY_CAST("Contract Amount" AS DOUBLE) DESC
#     LIMIT 10
# """).fetchdf().to_string())

# print(con.execute("""
#     SELECT "Notice Title", "Item Name", "Item Description", "Line Item No", "Contract Amount", "Award Reference No."
#     FROM all_awards_raw
#     WHERE "Notice Title" = 'ICT Modernization for Intelligent Campus Development Program'
# """).fetchdf().to_string()) 



# print(con.execute("""
#     SELECT "Award Reference No.", "Line Item No", COUNT(*) AS dupe_count
#     FROM all_awards_raw
#     GROUP BY "Award Reference No.", "Line Item No"
#     HAVING COUNT(*) > 1
#     ORDER BY dupe_count DESC
#     LIMIT 20
# """).fetchdf())

# print(con.execute("""
#     SELECT COUNT(*) AS total_duplicate_rows
#     FROM (
#         SELECT "Award Reference No.", "Line Item No"
#         FROM all_awards_raw
#         GROUP BY "Award Reference No.", "Line Item No"
#         HAVING COUNT(*) > 1
#     )
# """).fetchdf())


# print(con.execute("""
#     SELECT "Item Name", "Item Description", "Quantity", "UOM", "Contract Amount", "Awardee Organization Name"
#     FROM all_awards_raw
#     WHERE "Award Reference No." = '5391391' AND "Line Item No" = '1'
#     LIMIT 20
# """).fetchdf().to_string())



# print("CHECK HERE")
# 1. What's actually varying in that column?
# print(con.execute("""
#     SELECT "Awardee Joint Venture", COUNT(*) 
#     FROM all_awards_raw
#     WHERE "Award Reference No." = '5391391' AND "Line Item No" = '1'
#     GROUP BY "Awardee Joint Venture"
# """).fetchdf())

# 2. The CORRECT way to test full-row duplication
# total = con.execute("""
#     SELECT COUNT(*) FROM all_awards_raw
#     WHERE "Award Reference No." = '5391391' AND "Line Item No" = '1'
# """).fetchone()[0]

# distinct = con.execute("""
#     SELECT COUNT(*) FROM (
#         SELECT DISTINCT * FROM all_awards_raw
#         WHERE "Award Reference No." = '5391391' AND "Line Item No" = '1'
#     )
# """).fetchone()[0]

# print(f"total: {total}, truly distinct full rows: {distinct}")


# print("Further Checking")
# for award_ref, line_item in [('5391391','1'), ('5482304','1'), ('5421557','1'), ('5454145','1'), ('5562396','5')]:
#     result = con.execute(f"""
#         SELECT "Awardee Joint Venture", COUNT(*) 
#         FROM all_awards_raw
#         WHERE "Award Reference No." = '{award_ref}' AND "Line Item No" = '{line_item}'
#         GROUP BY "Awardee Joint Venture"
#     """).fetchdf()
#     print(f"--- {award_ref} / {line_item} ---")
#     print(result)
#     print()


# 

# total = con.execute("SELECT COUNT(*) FROM all_awards_raw").fetchone()[0]
# distinct = con.execute("SELECT COUNT(*) FROM (SELECT DISTINCT * FROM all_awards_raw)").fetchone()[0]

# print(f"Total rows: {total}")
# print(f"Truly distinct rows: {distinct}")
# print(f"Exact duplicate rows to remove: {total - distinct}")


# TABLE CREATION: DEDUPED
# con.execute("""
#     CREATE OR REPLACE TABLE all_awards_deduped AS
#     SELECT DISTINCT * FROM all_awards_raw
# """)

# print(con.execute("SELECT COUNT(*) FROM all_awards_deduped").fetchdf())
# print(con.execute("SHOW TABLES").fetchdf())

# print(con.execute("""
#     SELECT "Notice Title", "Item Name", "Contract Amount", "Awardee Organization Name", "Bid Notice Status", "Award Notice Status"
#     FROM all_awards_deduped
#     WHERE TRY_CAST("Contract Amount" AS DOUBLE) = 0
# """).fetchdf().to_string())


# print(con.execute("""
#     SELECT 
#         "Published Date", "Closing Date", "Published Date(Award)", 
#         "Award Date", "Notice to Proceed Date", "Contract Effectivity Date", "Contract End Date"
#     FROM all_awards_typed
#     LIMIT 10
# """).fetchdf().to_string())


# 1. Test the conversion theory on a real value
# print(con.execute("""
#     SELECT 45708 AS raw_number,
#            DATE '1899-12-30' + INTERVAL (45708) DAY AS converted_date
# """).fetchdf())



# 2. Check how much NULL-ness exists in each date column, full table
# print(con.execute("""
#     SELECT 
#         COUNT(*) FILTER (WHERE "Published Date" = 'NULL') AS published_nulls,
#         COUNT(*) FILTER (WHERE "Closing Date" = 'NULL') AS closing_nulls,
#         COUNT(*) FILTER (WHERE "Published Date(Award)" = 'NULL') AS pub_award_nulls,
#         COUNT(*) FILTER (WHERE "Award Date" = 'NULL') AS award_nulls,
#         COUNT(*) FILTER (WHERE "Notice to Proceed Date" = 'NULL') AS ntp_nulls,
#         COUNT(*) FILTER (WHERE "Contract Effectivity Date" = 'NULL') AS effectivity_nulls,
#         COUNT(*) FILTER (WHERE "Contract End Date" = 'NULL') AS end_nulls,
#         COUNT(*) AS total_rows
#     FROM all_awards_typed
# """).fetchdf())


# for col in ["Approved Budget of the Contract", "Item Budget", "Quantity", "Line Item No"]:
#     result = con.execute(f"""
#         SELECT 
#             COUNT(*) AS total_rows,
#             COUNT(*) FILTER (WHERE TRY_CAST("{col}" AS DOUBLE) IS NULL) AS fails_cast,
#             MIN(TRY_CAST("{col}" AS DOUBLE)) AS true_min,
#             MAX(TRY_CAST("{col}" AS DOUBLE)) AS true_max
#         FROM all_awards_typed
#     """).fetchdf()
#     print(f"--- {col} ---")
#     print(result)
#     print()


# print("=== NEGATIVE Item Budget rows ===")
# print(con.execute("""
#     SELECT "Notice Title", "Item Name", "Item Budget", "Quantity", "Contract Amount"
#     FROM all_awards_typed
#     WHERE TRY_CAST("Item Budget" AS DOUBLE) < 0
#     LIMIT 10
# """).fetchdf().to_string())

# print("\n=== Highest Quantity rows ===")
# print(con.execute("""
#     SELECT "Notice Title", "Item Name", "Quantity", "UOM", "Contract Amount"
#     FROM all_awards_typed
#     ORDER BY TRY_CAST("Quantity" AS DOUBLE) DESC
#     LIMIT 5
# """).fetchdf().to_string())



# print(con.execute("""
#     SELECT "UOM", COUNT(*) AS row_count
#     FROM all_awards_typed
#     WHERE TRY_CAST("Quantity" AS DOUBLE) = 30000000
#     GROUP BY "UOM"
#     ORDER BY row_count DESC
# """).fetchdf())


# print(con.execute("""
#     SELECT COUNT(*) AS total_rows,
#            COUNT(*) FILTER (WHERE TRY_CAST("Item Budget" AS DOUBLE) = -1) AS sentinel_neg1_count
#     FROM all_awards_typed
# """).fetchdf())


# print(con.execute("""
#     SELECT "Procurement Mode", COUNT(*) AS row_count
#     FROM all_awards_typed
#     GROUP BY "Region"
#     ORDER BY row_count DESC
# """).fetchdf().to_string())

# print("=== Procurement Mode ===")
# print(con.execute("""
#     SELECT "Procurement Mode", COUNT(*) AS row_count
#     FROM all_awards_typed
#     GROUP BY "Procurement Mode"
#     ORDER BY row_count DESC
# """).fetchdf().to_string())

# print("\n=== Province ===")
# print(con.execute("""
#     SELECT "Province", COUNT(*) AS row_count
#     FROM all_awards_typed
#     GROUP BY "Province"
#     ORDER BY row_count DESC
# """).fetchdf().to_string())


# 1. Basic shape check
# print(con.execute("""
#     SELECT COUNT(*) AS total_rows, COUNT(DISTINCT "Awardee Organization Name") AS distinct_names
#     FROM all_awards_typed
# """).fetchdf())

# # 2. Look for whitespace/casing issues specifically - the cheap wins first
# print(con.execute("""
#     SELECT "Awardee Organization Name", COUNT(*) AS row_count
#     FROM all_awards_typed
#     WHERE "Awardee Organization Name" != TRIM("Awardee Organization Name")
#        OR "Awardee Organization Name" != UPPER("Awardee Organization Name")
#     GROUP BY "Awardee Organization Name"
#     ORDER BY row_count DESC
#     LIMIT 20
# """).fetchdf().to_string())


# print(con.execute("""
#     SELECT COUNT(*) AS affected_rows
#     FROM all_awards_typed
#     WHERE "Awardee Organization Name" != TRIM("Awardee Organization Name")
#        OR "Awardee Organization Name" LIKE '%  %'
# """).fetchdf())



# result = con.execute("""
#     UPDATE all_awards_typed
#     SET "Awardee Organization Name" = TRIM(REGEXP_REPLACE("Awardee Organization Name", '\\s+', ' ', 'g'))
# """)
# print("Update result:", result)

# print(con.execute("""
#     SELECT COUNT(*) AS still_affected
#     FROM all_awards_typed
#     WHERE "Awardee Organization Name" != TRIM("Awardee Organization Name")
#        OR "Awardee Organization Name" LIKE '%  %'
# """).fetchdf())

# print(con.execute("""
#     SELECT COUNT(*) AS total_rows, COUNT(DISTINCT "Awardee Organization Name") AS distinct_names
#     FROM all_awards_typed
# """).fetchdf())


# columns_to_check = [
#     "Procuring Entity (PE)", "City/Municipality", "Government Branch",
#     "PE Organization Type", "PE Organization Type (Grouped)", "Notice Title",
#     "Classification", "Business Category", "Funding Source", "Funding Instrument",
#     "Trade Agreement", "Area of Delivery", "Contract Duration", "Calendar Type",
#     "Item Name", "Item Description", "UOM", "Award Reference No.", "Award Title",
#     "UNSPSC Description", "Country of Awardee", "Region of Awardee",
#     "Province of Awardee", "City/Municipality of Awardee", "Awardee Size"
# ]

# results = []
# for col in columns_to_check:
#     r = con.execute(f"""
#         SELECT 
#             COUNT(DISTINCT "{col}") AS distinct_count,
#             COUNT(*) FILTER (WHERE "{col}" = 'NULL' OR "{col}" IS NULL) AS null_like_count,
#             COUNT(*) FILTER (WHERE "{col}" != TRIM("{col}") OR "{col}" LIKE '%  %') AS whitespace_issues
#         FROM all_awards_typed
#         ORDER BY null_like_count, whitespace_issues
#     """).fetchone()
#     results.append((col, *r))

# import pandas as pd
# df = pd.DataFrame(results, columns=["column", "distinct_count", "null_like_count", "whitespace_issues"])
# print(df.to_string())


# def clean_whitespace(con, table, column):
#     """
#     Trims leading/trailing whitespace and collapses multiple internal spaces
#     into one, for a given column in a given table. Modifies the table in place.
#     Returns a before/after distinct-value count so you can see the impact.
#     """
#     before = con.execute(f'SELECT COUNT(DISTINCT "{column}") FROM {table}').fetchone()[0]
    
#     con.execute(f"""
#         UPDATE {table}
#         SET "{column}" = TRIM(REGEXP_REPLACE("{column}", '\\s+', ' ', 'g'))
#     """)
    
#     after = con.execute(f'SELECT COUNT(DISTINCT "{column}") FROM {table}').fetchone()[0]
#     remaining_issues = con.execute(f"""
#         SELECT COUNT(*) FROM {table}
#         WHERE "{column}" != TRIM("{column}") OR "{column}" LIKE '%  %'
#     """).fetchone()[0]
    
#     print(f'{column}: distinct {before} -> {after} (merged {before - after}), remaining issues: {remaining_issues}')


# # Apply to all Group 2 columns
# for col in ["Procuring Entity (PE)", "Notice Title", "Item Name", "Item Description", "Award Title"]:
#     clean_whitespace(con, "all_awards_typed", col)



# print("=== Calendar Type nulls vs Closing Date nulls ===")
# print(con.execute("""
#     SELECT 
#         COUNT(*) FILTER (WHERE "Calendar Type" = 'NULL') AS calendar_nulls,
#         COUNT(*) FILTER (WHERE "Closing Date" IS NULL) AS closing_date_nulls,
#         COUNT(*) FILTER (WHERE "Calendar Type" = 'NULL' AND "Closing Date" IS NULL) AS both_null
#     FROM all_awards_typed
# """).fetchdf())

# print("\n=== Area of Delivery nulls - any pattern? ===")
# print(con.execute("""
#     SELECT "Bid Notice Status", COUNT(*) AS row_count
#     FROM all_awards_typed
#     WHERE "Area of Delivery" = 'NULL'
#     GROUP BY "Bid Notice Status"
#     ORDER BY row_count DESC
# """).fetchdf())

# print("\n=== Awardee Size nulls - any pattern? ===")
# print(con.execute("""
#     SELECT "Awardee Joint Venture" IS NOT NULL AS has_jv, COUNT(*) AS row_count
#     FROM all_awards_typed
#     WHERE "Awardee Size" = 'NULL'
#     GROUP BY 1
# """).fetchdf())



# print("=== Contract Duration nulls - any pattern? ===")
# print(con.execute("""
#     SELECT "Bid Notice Status", "Award Notice Status", COUNT(*) AS row_count
#     FROM all_awards_typed
#     WHERE "Contract Duration" = 'NULL'
#     GROUP BY "Bid Notice Status", "Award Notice Status"
#     ORDER BY row_count DESC
# """).fetchdf())

# print("\n=== What do actual values look like? ===")
# print(con.execute("""
#     SELECT "Contract Duration", COUNT(*) AS row_count
#     FROM all_awards_typed
#     WHERE "Contract Duration" != 'NULL'
#     GROUP BY "Contract Duration"
#     ORDER BY row_count DESC
#     LIMIT 15
# """).fetchdf())


# print(con.execute("""
#     SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE "Contract Duration" = '0') AS zero_count
#     FROM all_awards_typed
# """).fetchdf())

# print(con.execute("""
#     SELECT "Bid Notice Status", "Award Notice Status", COUNT(*) AS row_count
#     FROM all_awards_typed
#     WHERE "Contract Duration" = '0'
#     GROUP BY "Bid Notice Status", "Award Notice Status"
#     ORDER BY row_count DESC
# """).fetchdf())

# print(con.execute("""
#     SELECT 
#         COUNT(*) FILTER (WHERE "Contract Duration" = '0') AS duration_zero,
#         COUNT(*) FILTER (WHERE "Notice to Proceed Date" IS NULL) AS ntp_null,
#         COUNT(*) FILTER (WHERE "Contract Duration" = '0' AND "Notice to Proceed Date" IS NULL) AS both_duration_and_ntp,
#         COUNT(*) FILTER (WHERE "Contract Duration" = '0' AND "Notice to Proceed Date" IS NOT NULL) AS duration_zero_but_ntp_exists
#     FROM all_awards_typed
# """).fetchdf())

# result = con.execute("""
#     SELECT 
#         COUNT(*) FILTER (WHERE "Contract Duration" = '0') AS duration_zero,
#         COUNT(*) FILTER (WHERE "Contract Duration" = '0' AND "Notice to Proceed Date" IS NULL) AS both_duration_and_ntp,
#         COUNT(*) FILTER (WHERE "Contract Duration" = '0' AND "Notice to Proceed Date" IS NOT NULL) AS duration_zero_but_ntp_exists,
#         COUNT(*) FILTER (WHERE "Contract Duration" = '0' AND "Contract End Date" IS NULL) AS both_duration_and_end,
#         COUNT(*) FILTER (WHERE "Contract Duration" = '0' AND "Contract End Date" IS NOT NULL) AS duration_zero_but_end_exists
#     FROM all_awards_typed
# """).fetchdf()
# print(result.to_string())


con.execute("""
    UPDATE all_awards_typed
    SET "Contract Duration" = CASE 
        WHEN "Contract Duration" = '0' THEN NULL 
        ELSE "Contract Duration" 
    END
""")

con.execute("""
    ALTER TABLE all_awards_typed 
    ALTER COLUMN "Contract Duration" TYPE INTEGER 
    USING TRY_CAST("Contract Duration" AS INTEGER)
""")

print(con.execute("""
    SELECT COUNT(*) AS total,
           COUNT(*) FILTER (WHERE "Contract Duration" IS NULL) AS null_count,
           MIN("Contract Duration") AS min_val,
           MAX("Contract Duration") AS max_val
    FROM all_awards_typed
""").fetchdf())