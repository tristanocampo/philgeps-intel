"""
PhilGEPS Intelligence: Conversational AI Assistant for Philippine Public Procurement.
Powered by Schema-Aware Tool-Using Agent with DuckDB SQL & Hybrid Search.
"""
import os
import sys
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.abspath("."))

import streamlit as st
import pandas as pd
from rag.engine import ask_philgeps
from app.monitoring import log_query, record_feedback, get_monitoring_summary, get_all_query_logs_df

# Page Configuration
st.set_page_config(
    page_title="PhilGEPS Intelligence | Public Procurement AI",
    page_icon="🇵🇭",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Header
st.title("🇵🇭 PhilGEPS Intelligence")
st.caption("Conversational AI Assistant over 159,800+ Philippine Government Procurement Contracts (DuckDB Analytical Engine)")

# Initialize Chat History
if "messages" not in st.session_state:
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "👋 **Hello! I am PhilGEPS Intelligence.**\n\n"
                "I am connected to official Philippine public procurement records. Ask me anything about:\n"
                "- **Contractor / Supplier Rankings:** *\"Who was the top supplier for DOH in 2025?\"*\n"
                "- **Procurement Classification:** *\"How much did the government spend on Civil Works vs Goods?\"*\n"
                "- **Procurement Methods:** *\"Compare spending between Public Bidding and Small Value Procurement\"*\n"
                "- **MSME & Small Business:** *\"Which Micro and Small enterprises won the largest contracts?\"*\n"
                "- **Budget Savings (ABC vs Spent):** *\"How much budget was saved compared to Approved Budget (ABC)?\"*\n"
                "- **Agency Spending:** *\"How much did PSA spend on Q1?\"*\n"
                "- **Catalog Discovery:** *\"Find catering services for DOH in NCR\"*"
            ),
            "data_rows": None,
            "sql_query": None,
            "latency_ms": None,
            "log_id": None
        }
    ]

# Sidebar
with st.sidebar:
    st.header("💡 Example Inquiries")
    st.caption("Click any prompt to ask immediately:")
    example_prompts = [
        "Who was the top supplier for DOH in 2025?",
        "How much did the government spend on Civil Works compared to Goods?",
        "Compare spending between Public Bidding and Small Value Procurement",
        "Which Micro and Small enterprises (MSMEs) won the largest contracts?",
        "How much government budget was saved compared to the Approved Budget of the Contract?",
        "How much did PSA spend on Q1?",
        "What was the largest contract awarded in Region VII?",
        "Find catering services for DOH in NCR"
    ]
    for ex in example_prompts:
        if st.button(ex, use_container_width=True):
            st.session_state["queued_prompt"] = ex

    st.markdown("---")
    st.subheader("🛡️ Architecture & Security")
    st.markdown(
        """
        - **Engine:** DuckDB (`read_only=True` C++ Lock)
        - **Records:** 159,819 Contracts (`gold.all_awards`)
        - **Catalog:** 152,352 Unique Items (`gold.unique_items`)
        - **Retrieval:** 98% Hit Rate@5 Hybrid Search
        - **Guardrails:** 4-Layer Injection & AST Parser Shield
        - **Telemetry:** SQLite (`data/metrics.db`)
        """
    )

    st.markdown("---")
    if st.button("🗑️ Clear Conversation", use_container_width=True):
        st.session_state.messages = [st.session_state.messages[0]]
        st.rerun()

# Tabs: Chat Interface and Monitoring Dashboard
tab_chat, tab_telemetry = st.tabs(["💬 Conversational Assistant", "📊 System Telemetry & Monitoring"])

with tab_chat:
    # Display Chat History
    for idx, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

            # Display metadata tags if available
            if msg.get("tool_used"):
                col_tag, col_lat = st.columns([4, 1])
                tool_label = "⚡ Analytical DuckDB SQL" if msg["tool_used"] == "sql" else "🔍 Hybrid Catalog Search (Vector + BM25)"
                col_tag.caption(f"**Execution Mode:** {tool_label}")
                if msg.get("latency_ms"):
                    col_lat.caption(f"⏱️ **{msg['latency_ms']:.0f} ms**")

            # Display Collapsible Data Table
            if msg.get("data_rows"):
                rows = msg["data_rows"]
                with st.expander(f"📋 View Matching Data Records ({len(rows)} record{'s' if len(rows) != 1 else ''})", expanded=False):
                    if msg.get("sql_query"):
                        st.code(msg["sql_query"], language="sql")
                    df = pd.DataFrame(rows)
                    st.dataframe(df, use_container_width=True)

            # Feedback Buttons for Assistant responses (except greeting)
            if msg["role"] == "assistant" and idx > 0 and msg.get("log_id"):
                col_fb1, col_fb2, _ = st.columns([1, 1, 10])
                with col_fb1:
                    if st.button("👍 Helpful", key=f"thumb_up_{idx}"):
                        record_feedback(msg["log_id"], "thumbs_up")
                        st.toast("Thank you for your feedback! (Logged to metrics.db)")
                with col_fb2:
                    if st.button("👎 Poor", key=f"thumb_down_{idx}"):
                        record_feedback(msg["log_id"], "thumbs_down")
                        st.toast("Feedback recorded. (Logged to metrics.db)")

    # Handle User Input (from text input or sidebar click)
    user_query = st.chat_input("Ask about Philippine government budgets, suppliers, or tenders...")

    if "queued_prompt" in st.session_state and st.session_state["queued_prompt"]:
        user_query = st.session_state.pop("queued_prompt")

    if user_query:
        # 1. Append User Message
        st.session_state.messages.append({
            "role": "user",
            "content": user_query,
            "data_rows": None,
            "sql_query": None,
            "latency_ms": None,
            "log_id": None
        })
        with st.chat_message("user"):
            st.markdown(user_query)

        # 2. Assistant Thinking & Execution
        with st.chat_message("assistant"):
            with st.spinner("Analyzing Philippine government procurement records..."):
                res = ask_philgeps(user_query)

                # Log to SQLite monitoring
                log_id = log_query(
                    query=user_query,
                    matched_items_count=res.get("matched_items_count", 0),
                    total_spend=res.get("total_spend", 0.0),
                    latency_ms=res.get("latency_ms", 0.0),
                    used_vector=res.get("used_vector", False),
                    used_llm=res.get("used_llm", True)
                )

                answer = res.get("answer", "No answer could be generated.")
                data_rows = res.get("data_rows", [])
                sql_query = res.get("sql_query")
                tool_used = res.get("tool_used")
                latency_ms = res.get("latency_ms")

                # Render Answer
                st.markdown(answer)

                # Render Metadata & Data Table
                col_tag, col_lat = st.columns([4, 1])
                tool_label = "⚡ Analytical DuckDB SQL" if tool_used == "sql" else "🔍 Hybrid Catalog Search (Vector + BM25)"
                col_tag.caption(f"**Execution Mode:** {tool_label}")
                if latency_ms:
                    col_lat.caption(f"⏱️ **{latency_ms:.0f} ms**")

                if data_rows:
                    with st.expander(f"📋 View Matching Data Records ({len(data_rows)} record{'s' if len(data_rows) != 1 else ''})", expanded=False):
                        if sql_query:
                            st.code(sql_query, language="sql")
                        df = pd.DataFrame(data_rows)
                        st.dataframe(df, use_container_width=True)

                # Append to session history
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer,
                    "tool_used": tool_used,
                    "data_rows": data_rows,
                    "sql_query": sql_query,
                    "latency_ms": latency_ms,
                    "log_id": log_id
                })

                st.rerun()

with tab_telemetry:
    st.subheader("📊 System Telemetry & Performance Monitoring")
    st.caption("Live operational metrics persisted to SQLite database (`data/metrics.db`)")

    summary = get_monitoring_summary()
    df_logs = get_all_query_logs_df(limit=100)

    # 1. KPI Cards
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.metric("Total Queries Logged", f"{summary['total_queries']:,}")
    with col_m2:
        st.metric("Average Latency", f"{summary['avg_latency_ms']:.0f} ms")
    with col_m3:
        sat_text = f"{summary['satisfaction_rate']:.1f}%" if (summary['thumbs_up'] + summary['thumbs_down']) > 0 else "100%"
        st.metric("User Approval (👍)", sat_text, f"{summary['thumbs_up']} 👍 / {summary['thumbs_down']} 👎")
    with col_m4:
        st.metric("Warehouse Scale", "159,819 awards", "48 columns gold layer")

    st.markdown("---")

    # 2. Charts Row
    if not df_logs.empty and "latency_ms" in df_logs.columns:
        col_c1, col_c2 = st.columns([2, 1])
        with col_c1:
            st.markdown("##### ⏱️ Query Latency Over Time (ms)")
            chart_df = df_logs[["id", "latency_ms"]].sort_values("id")
            chart_df = chart_df.set_index("id")
            st.line_chart(chart_df, color="#1f77b4", height=250)

        with col_c2:
            st.markdown("##### 🗳️ User Feedback Sentiment")
            up = summary["thumbs_up"]
            down = summary["thumbs_down"]
            unrated = max(0, summary["total_queries"] - up - down)
            sentiment_df = pd.DataFrame({
                "Status": ["Helpful (👍)", "Poor (👎)", "Unrated"],
                "Count": [up, down, unrated]
            }).set_index("Status")
            st.bar_chart(sentiment_df, height=250)

    # 3. Interactive Query Audit Log
    st.markdown("##### 📜 Recent Query Audit Log")
    if not df_logs.empty:
        st.dataframe(
            df_logs,
            use_container_width=True,
            hide_index=True,
            column_config={
                "id": "Log ID",
                "timestamp": "Timestamp (UTC)",
                "query": "User Query String",
                "latency_ms": st.column_config.NumberColumn("Latency (ms)", format="%.0f ms"),
                "total_spend": st.column_config.NumberColumn("Reported Spend (₱)", format="₱%,.2f"),
                "matched_items_count": "Records",
                "feedback": "User Feedback"
            }
        )
    else:
        st.info("No query logs recorded yet. Ask a question in the assistant tab to start logging!")
