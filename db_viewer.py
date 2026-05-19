"""Propagation Card Reader — DB Viewer

Streamlit app for browsing extraction databases.
Launch: streamlit run db_viewer.py --server.port 8502
"""

import glob
import os
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

# --- Config ---
SCAN_PATHS = [
    "/media/hevek/DeweyRunner",
    "/media/hevek/LACIE SHARE",
    "/media/hevek/LaCie",
    "/home/hevek/projects/propagation-card-reader",
    os.path.expanduser("~"),
]

EXTRACTION_FIELDS = [
    "botanical_name", "family", "geocode", "received_as", "quantity",
    "date_received", "present_location", "wanted_for_area", "source",
    "source_info", "collector_number", "other_number", "labels_requested",
    "max_quantity", "parent_accession", "collection_info", "distribution",
    "accession_number", "propagation_text", "curators_info", "iris_data_entered",
]

# Fields grouped for the card detail view
FIELD_GROUPS = {
    "🌿 Identity": ["botanical_name", "family", "accession_number"],
    "📦 Received": ["received_as", "quantity", "date_received", "source", "source_info"],
    "📍 Location": ["present_location", "wanted_for_area", "geocode"],
    "🔗 References": ["collector_number", "other_number", "parent_accession", "labels_requested", "max_quantity"],
    "📋 Notes": ["collection_info", "distribution", "curators_info"],
    "🌱 Propagation": ["propagation_text"],
    "📊 Meta": ["iris_data_entered"],
}


def find_databases() -> list[str]:
    """Scan known paths for .db files."""
    found = set()
    for base in SCAN_PATHS:
        if not os.path.exists(base):
            continue
        for root, dirs, files in os.walk(base):
            # Limit depth to 3 levels
            depth = root.replace(base, "").count(os.sep)
            if depth > 3:
                dirs.clear()
                continue
            for f in files:
                if f.endswith(".db") and not f.endswith("-shm") and not f.endswith("-wal"):
                    full = os.path.join(root, f)
                    # Quick check: is it a card reader DB?
                    try:
                        conn = sqlite3.connect(full)
                        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
                        conn.close()
                        if "cards" in tables and "extractions" in tables:
                            found.add(full)
                    except Exception:
                        pass
    return sorted(found)


def get_connection(db_path: str) -> sqlite3.Connection:
    """Get a read-only SQLite connection."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def get_status_summary(conn: sqlite3.Connection) -> dict:
    """Get processing status counts."""
    rows = conn.execute("SELECT status, count(*) as n FROM cards GROUP BY status").fetchall()
    return {r["status"]: r["n"] for r in rows}


def get_field_coverage(conn: sqlite3.Connection) -> dict:
    """Check which fields have data."""
    coverage = {}
    total = conn.execute("SELECT count(*) FROM extractions").fetchone()[0]
    if total == 0:
        return coverage
    for f in EXTRACTION_FIELDS:
        try:
            n = conn.execute(
                f'SELECT count(*) FROM extractions WHERE {f} IS NOT NULL AND {f} != ""'
            ).fetchone()[0]
            coverage[f] = (n, total, round(n / total * 100, 1))
        except Exception:
            coverage[f] = (0, total, 0.0)
    return coverage


def get_extractions_df(conn: sqlite3.Connection, limit: int = 500, offset: int = 0,
                        search: str = None, status_filter: str = None) -> pd.DataFrame:
    """Get extractions as a DataFrame with card info."""
    # Check which columns exist
    cols_available = {r[1] for r in conn.execute("PRAGMA table_info(extractions)")}

    select_fields = []
    for f in EXTRACTION_FIELDS:
        if f in cols_available:
            select_fields.append(f"e.{f}")
        else:
            select_fields.append(f"NULL as {f}")

    ext_select = ", ".join(select_fields)

    where_clauses = []
    params = []

    if status_filter and status_filter != "All":
        where_clauses.append("c.status = ?")
        params.append(status_filter)

    if search:
        where_clauses.append(
            "(e.botanical_name LIKE ? OR e.propagation_text LIKE ? OR e.accession_number LIKE ?)"
        )
        params.extend([f"%{search}%"] * 3)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    query = f"""
        SELECT
            c.id as card_id,
            c.pdf_path,
            c.page_num,
            c.status,
            c.error_message,
            c.image_path,
            e.processing_time_s,
            e.model,
            e.dpi,
            {ext_select},
            GROUP_CONCAT(a.accession_number, ' | ') as all_accession_numbers
        FROM cards c
        LEFT JOIN extractions e ON e.card_id = c.id
        LEFT JOIN accession_numbers a ON a.extraction_id = e.id
        {where_sql}
        GROUP BY c.id
        ORDER BY c.id
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    df = pd.read_sql_query(query, conn, params=params)
    return df


def get_card_count(conn: sqlite3.Connection, status_filter: str = None, search: str = None) -> int:
    """Get total card count with filters."""
    where_clauses = []
    params = []
    if status_filter and status_filter != "All":
        where_clauses.append("c.status = ?")
        params.append(status_filter)
    if search:
        where_clauses.append(
            "(e.botanical_name LIKE ? OR e.propagation_text LIKE ? OR e.accession_number LIKE ?)"
        )
        params.extend([f"%{search}%"] * 3)
    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    query = f"""
        SELECT count(DISTINCT c.id) FROM cards c
        LEFT JOIN extractions e ON e.card_id = c.id
        {where_sql}
    """
    return conn.execute(query, params).fetchone()[0]


# --- Streamlit App ---

st.set_page_config(
    page_title="🌿 Card Reader DB Viewer",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🌿 Propagation Card Reader — DB Viewer")

# --- Sidebar: DB Selection ---
with st.sidebar:
    st.header("📂 Database")

    # Find databases
    if "db_list" not in st.session_state or st.sidebar.button("🔄 Rescan"):
        with st.spinner("Scanning for databases..."):
            st.session_state.db_list = find_databases()

    db_list = st.session_state.get("db_list", [])

    if not db_list:
        st.warning("No card reader databases found.")
        st.info(f"Scanning: {', '.join(SCAN_PATHS)}")
        st.stop()

    # Display as short names with full path in tooltip
    db_labels = [f"{os.path.basename(p)}  ({os.path.dirname(p)})" for p in db_list]
    selected_idx = st.selectbox("Select database", range(len(db_list)),
                                 format_func=lambda i: db_labels[i])
    db_path = db_list[selected_idx]

    # Manual path entry
    custom_path = st.text_input("Or enter path manually")
    if custom_path and os.path.exists(custom_path):
        db_path = custom_path

    st.caption(f"📍 `{db_path}`")
    st.caption(f"📏 {os.path.getsize(db_path) / 1024:.0f} KB")

# Connect
try:
    conn = get_connection(db_path)
except Exception as e:
    st.error(f"Failed to open database: {e}")
    st.stop()

# --- Sidebar: Status Summary ---
with st.sidebar:
    st.header("📊 Status")
    status = get_status_summary(conn)
    total = sum(status.values())

    cols = st.columns(2)
    cols[0].metric("Total", total)
    cols[1].metric("Success", status.get("success", 0))

    success = status.get("success", 0)
    failed = status.get("failed", 0)
    error = status.get("error", 0)
    completed = success + failed + error
    if completed > 0:
        rate = success / completed * 100
        st.progress(rate / 100, text=f"Success rate: {rate:.1f}%")

    for s, n in sorted(status.items()):
        st.text(f"  {s}: {n}")

# --- Main Content: Tabs ---
tab_cards, tab_coverage, tab_query, tab_compare = st.tabs([
    "🃏 Card Browser", "📊 Field Coverage", "🔍 SQL Query", "⚖️ Compare DBs"
])

# --- Tab 1: Card Browser ---
with tab_cards:
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        search = st.text_input("🔍 Search (name, accession, propagation text)", key="card_search")
    with col2:
        status_options = ["All"] + list(status.keys())
        status_filter = st.selectbox("Status", status_options, key="status_filter")
    with col3:
        per_page = st.selectbox("Per page", [10, 25, 50, 100], index=1, key="per_page")

    total_filtered = get_card_count(conn, status_filter, search or None)
    max_pages = max(1, (total_filtered + per_page - 1) // per_page)
    page = st.number_input("Page", min_value=1, max_value=max_pages, value=1, key="page")
    st.caption(f"Showing page {page} of {max_pages} ({total_filtered} cards)")

    offset = (page - 1) * per_page
    df = get_extractions_df(conn, limit=per_page, offset=offset,
                            search=search or None, status_filter=status_filter)

    if df.empty:
        st.info("No cards match the current filters.")
    else:
        # Card detail view
        view_mode = st.radio("View", ["📋 Table", "🃏 Card Detail"], horizontal=True, key="view_mode")

        if view_mode == "📋 Table":
            # Show compact table
            display_cols = ["card_id", "status", "error_message", "accession_number", "botanical_name",
                          "family", "received_as", "date_received", "all_accession_numbers",
                          "processing_time_s"]
            available_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(df[available_cols], use_container_width=True, hide_index=True)

        else:
            # Card-by-card detail view
            for _, row in df.iterrows():
                if row.get("status") != "success":
                    continue

                card_title = row.get("botanical_name") or "Unknown"
                acc = row.get("accession_number") or "—"
                with st.expander(f"**{card_title}** — `{acc}`", expanded=False):
                    for group_name, fields in FIELD_GROUPS.items():
                        populated = {f: row.get(f) for f in fields
                                    if row.get(f) is not None and str(row.get(f)).strip()}
                        if not populated:
                            continue
                        st.markdown(f"**{group_name}**")
                        for fname, val in populated.items():
                            if fname == "propagation_text":
                                st.text_area(
                                    "Propagation Text",
                                    value=str(val),
                                    height=150,
                                    disabled=True,
                                    key=f"prop_{row['card_id']}",
                                )
                            elif fname == "iris_data_entered":
                                st.write(f"  `{fname}`: {'✅' if val else '❌'}")
                            else:
                                st.write(f"  `{fname}`: {val}")

                    # All accession numbers
                    all_acc = row.get("all_accession_numbers")
                    if all_acc:
                        st.markdown("**🔢 All Accession Numbers**")
                        st.write(f"  {all_acc}")

                    # Meta
                    st.markdown("**⚙️ Processing**")
                    time_s = row.get("processing_time_s")
                    st.write(f"  Model: `{row.get('model')}` | DPI: {row.get('dpi')} | Time: {time_s:.1f}s" if time_s else "  —")

                    pdf_name = os.path.basename(row["pdf_path"]) if row.get("pdf_path") else "—"
                    st.caption(f"PDF: {pdf_name}, page {row.get('page_num')}")

# --- Tab 2: Field Coverage ---
with tab_coverage:
    st.subheader("Field Population Across Extractions")
    coverage = get_field_coverage(conn)
    if not coverage:
        st.info("No extractions yet.")
    else:
        cov_data = []
        for field, (filled, total, pct) in coverage.items():
            cov_data.append({
                "Field": field,
                "Populated": filled,
                "Total": total,
                "Coverage %": pct,
                "Bar": "█" * int(pct / 5) + "░" * (20 - int(pct / 5)),
            })
        cov_df = pd.DataFrame(cov_data)
        st.dataframe(cov_df, use_container_width=True, hide_index=True)

        # Summary stats
        populated_fields = sum(1 for _, (n, _, _) in coverage.items() if n > 0)
        st.metric("Fields with data", f"{populated_fields}/{len(EXTRACTION_FIELDS)}")

# --- Tab 3: SQL Query ---
with tab_query:
    st.subheader("Custom SQL Query")
    st.caption("Read-only. Tables: cards, extractions, accession_numbers, processing_runs, rag_contexts")

    default_query = """SELECT
    e.botanical_name,
    e.accession_number,
    e.family,
    e.received_as,
    e.propagation_text
FROM extractions e
JOIN cards c ON c.id = e.card_id
WHERE c.status = 'success'
LIMIT 20;"""

    query = st.text_area("SQL", value=default_query, height=150, key="sql_query")

    if st.button("▶️ Run Query", key="run_query"):
        try:
            result_df = pd.read_sql_query(query, conn)
            st.success(f"{len(result_df)} rows returned")
            st.dataframe(result_df, use_container_width=True, hide_index=True)

            # Download button
            csv_data = result_df.to_csv(index=False)
            st.download_button("📥 Download CSV", csv_data, "query_results.csv", "text/csv")
        except Exception as e:
            st.error(f"Query error: {e}")

# --- Tab 4: Compare DBs ---
with tab_compare:
    st.subheader("Compare Two Databases")
    st.caption("Select a second database to compare field coverage and success rates.")

    db_labels_2 = ["(none)"] + db_labels
    compare_idx = st.selectbox("Compare with", range(len(db_labels_2)),
                                format_func=lambda i: db_labels_2[i], key="compare_db")

    if compare_idx > 0:
        db_path_2 = db_list[compare_idx - 1]
        try:
            conn2 = get_connection(db_path_2)
            status2 = get_status_summary(conn2)
            coverage2 = get_field_coverage(conn2)

            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**DB 1:** `{os.path.basename(db_path)}`")
                s1 = status.get("success", 0)
                f1 = status.get("failed", 0)
                st.write(f"Success: {s1} | Failed: {f1}")

            with col2:
                st.markdown(f"**DB 2:** `{os.path.basename(db_path_2)}`")
                s2 = status2.get("success", 0)
                f2 = status2.get("failed", 0)
                st.write(f"Success: {s2} | Failed: {f2}")

            # Compare field coverage
            compare_data = []
            coverage1 = get_field_coverage(conn)
            for field in EXTRACTION_FIELDS:
                pct1 = coverage1.get(field, (0, 0, 0.0))[2]
                pct2 = coverage2.get(field, (0, 0, 0.0))[2]
                delta = pct2 - pct1
                compare_data.append({
                    "Field": field,
                    "DB1 %": pct1,
                    "DB2 %": pct2,
                    "Δ": f"{delta:+.1f}%",
                })
            st.dataframe(pd.DataFrame(compare_data), use_container_width=True, hide_index=True)

            # Avg processing time
            avg1 = conn.execute("SELECT AVG(processing_time_s) FROM extractions").fetchone()[0]
            avg2 = conn2.execute("SELECT AVG(processing_time_s) FROM extractions").fetchone()[0]
            tc1, tc2 = st.columns(2)
            tc1.metric("Avg time (DB1)", f"{avg1:.1f}s" if avg1 else "—")
            tc2.metric("Avg time (DB2)", f"{avg2:.1f}s" if avg2 else "—")

            conn2.close()
        except Exception as e:
            st.error(f"Failed to open comparison DB: {e}")

conn.close()
