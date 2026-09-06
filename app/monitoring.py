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
            feedback TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_query(
    query: str,
    matched_items_count: int,
    total_spend: float,
    latency_ms: float,
    used_vector: bool,
    used_llm: bool,
    db_path: str = METRICS_DB_PATH
) -> int:
    """Logs a query execution and returns the created log record id."""
    init_monitoring_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    now_str = datetime.datetime.now(datetime.timezone.utc).isoformat()

    cursor.execute("""
        INSERT INTO query_logs (
            timestamp, query, matched_items_count, total_spend,
            latency_ms, used_vector, used_llm, feedback
        ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
    """, (
        now_str, query, matched_items_count, total_spend,
        latency_ms, 1 if used_vector else 0, 1 if used_llm else 0
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
    """Returns high-level statistics from the query logs."""
    init_monitoring_db(db_path)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*), AVG(latency_ms) FROM query_logs")
    total_queries, avg_lat = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) FROM query_logs WHERE feedback LIKE '%up%'")
    thumbs_up = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM query_logs WHERE feedback LIKE '%down%'")
    thumbs_down = cursor.fetchone()[0]

    cursor.execute("""
        SELECT id, timestamp, query, total_spend, latency_ms, feedback 
        FROM query_logs 
        ORDER BY id DESC LIMIT 10
    """)
    recent = cursor.fetchall()
    conn.close()

    total_fb = thumbs_up + thumbs_down
    satisfaction_rate = (thumbs_up / total_fb * 100) if total_fb > 0 else 100.0

    return {
        "total_queries": total_queries or 0,
        "avg_latency_ms": avg_lat or 0.0,
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
                ROUND(latency_ms, 1) AS latency_ms, 
                ROUND(total_spend, 2) AS total_spend,
                matched_items_count,
                COALESCE(feedback, 'None') AS feedback
            FROM query_logs 
            ORDER BY id DESC 
            LIMIT {limit}
        """, conn)
        return df
    finally:
        conn.close()
