"""
Monitoring & Telemetry Logger for PhilGEPS Intelligence.
Stores query execution history, latencies, spend outputs, and user feedback
in a persistent SQLite database (data/metrics.db).
"""
import os
import sqlite3
import datetime
from typing import Any

METRICS_DB_PATH = "data/metrics.db"


def init_monitoring_db(db_path: str = METRICS_DB_PATH):
    """Initializes the SQLite metrics database and creates the queries table."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS query_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            query TEXT NOT NULL,
            matched_items_count INTEGER,
            total_spend REAL,
            latency_ms REAL,
            used_vector INTEGER,
            used_llm INTEGER,
            feedback TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0
        )
    """)
    # Migration check for existing SQLite databases
    cursor.execute("PRAGMA table_info(query_logs)")
    cols = {row[1] for row in cursor.fetchall()}
    if "prompt_tokens" not in cols:
        cursor.execute("ALTER TABLE query_logs ADD COLUMN prompt_tokens INTEGER DEFAULT 0")
    if "total_tokens" not in cols:
        cursor.execute("ALTER TABLE query_logs ADD COLUMN total_tokens INTEGER DEFAULT 0")
    if "cost_usd" not in cols:
        cursor.execute("ALTER TABLE query_logs ADD COLUMN cost_usd REAL DEFAULT 0.0")

    conn.commit()
    conn.close()


def log_query(
    query: str,
    matched_items_count: int,
    total_spend: float,
    latency_ms: float,
    used_vector: bool,
    used_llm: bool,
    prompt_tokens: int = 0,
    total_tokens: int = 0,
    cost_usd: float = 0.0,
    db_path: str = METRICS_DB_PATH
) -> int:
    """Logs a query execution with token and cost metrics and returns the created log record id."""
    init_monitoring_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    cursor.execute("""
        INSERT INTO query_logs (
            timestamp, query, matched_items_count, total_spend,
            latency_ms, used_vector, used_llm, feedback,
            prompt_tokens, total_tokens, cost_usd
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
    """, (
        now_str, query, matched_items_count, total_spend,
        latency_ms, 1 if used_vector else 0, 1 if used_llm else 0,
        prompt_tokens, total_tokens, cost_usd
    ))
    log_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return log_id


def record_feedback(log_id: int, feedback: str, db_path: str = METRICS_DB_PATH):
    """Updates feedback ('thumbs_up' or 'thumbs_down') for a given query log record."""
    init_monitoring_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    norm_feedback = "thumbs_up" if "up" in feedback.lower() else "thumbs_down"
    cursor.execute("UPDATE query_logs SET feedback = ? WHERE id = ?", (norm_feedback, log_id))
    conn.commit()
    conn.close()


def get_monitoring_summary(db_path: str = METRICS_DB_PATH) -> dict[str, Any]:
    """Returns high-level statistics including token volume and estimated cost from query logs."""
    init_monitoring_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT 
            COUNT(*), 
            AVG(latency_ms), 
            COALESCE(SUM(total_tokens), 0), 
            COALESCE(SUM(cost_usd), 0.0) 
        FROM query_logs
    """)
    row = cursor.fetchone()
    total_queries = row[0] or 0
    avg_lat = row[1] or 0.0
    total_tokens = int(row[2] or 0)
    total_cost_usd = float(row[3] or 0.0)

    cursor.execute("SELECT COUNT(*) FROM query_logs WHERE feedback LIKE '%up%'")
    thumbs_up = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM query_logs WHERE feedback LIKE '%down%'")
    thumbs_down = cursor.fetchone()[0]

    cursor.execute("""
        SELECT id, timestamp, query, prompt_tokens, total_tokens, cost_usd, latency_ms, feedback 
        FROM query_logs 
        ORDER BY id DESC LIMIT 10
    """)
    recent = cursor.fetchall()
    conn.close()

    total_fb = thumbs_up + thumbs_down
    satisfaction_rate = (thumbs_up / total_fb * 100) if total_fb > 0 else 100.0

    return {
        "total_queries": total_queries,
        "avg_latency_ms": avg_lat,
        "total_tokens": total_tokens,
        "total_cost_usd": total_cost_usd,
        "thumbs_up": thumbs_up or 0,
        "thumbs_down": thumbs_down or 0,
        "satisfaction_rate": satisfaction_rate,
        "recent_logs": recent
    }


def get_all_query_logs_df(db_path: str = METRICS_DB_PATH, limit: int = 150):
    """Returns all query logs as a pandas DataFrame for dashboard visualization."""
    import pandas as pd
    init_monitoring_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(f"""
            SELECT 
                id, 
                timestamp, 
                query, 
                ROUND(latency_ms, 0) AS latency_ms, 
                COALESCE(prompt_tokens, 0) AS prompt_tokens,
                COALESCE(total_tokens, 0) AS total_tokens,
                COALESCE(cost_usd, 0.0) AS cost_usd,
                COALESCE(feedback, 'None') AS feedback
            FROM query_logs 
            ORDER BY id DESC 
            LIMIT {limit}
        """, conn)
        return df
    finally:
        conn.close()
