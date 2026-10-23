import streamlit as st
import pandas as pd
from datetime import datetime
import database as db
import checker

st.set_page_config(
    page_title="LinkGuard | Affiliate Link Health-Checker & Hot-Swapper",
    page_icon="🔗",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize database and session state
db.init_db()

if "last_scan_summary" not in st.session_state:
    st.session_state.last_scan_summary = None
if "scan_results_log" not in st.session_state:
    st.session_state.scan_results_log = []
if "status_filter" not in st.session_state:
    st.session_state.status_filter = "All"


def refresh_links() -> list:
    """Fetch fresh link records from SQLite and cache in session_state."""
    st.session_state.links = db.get_all_links()
    return st.session_state.links


links_data = refresh_links()
current_settings = db.get_settings()

# ---------------------------------------------------------------------------
# Sidebar Configuration
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("🔗 LinkGuard Ops")
    st.caption("Affiliate Link Health-Checker & Automated Hot-Swapper")
    st.divider()

    st.subheader("Scan & Automation Settings")
    scan_interval = st.selectbox(
        "Automated Scan Interval",
        options=["15", "30", "60", "180", "360", "720", "1440"],
        index=["15", "30", "60", "180", "360", "720", "1440"].index(
            current_settings.get("scan_interval_minutes", "60")
            if current_settings.get("scan_interval_minutes", "60")
            in ["15", "30", "60", "180", "360", "720", "1440"]
            else "60"
        ),
        format_func=lambda x: f"Every {x} minutes"
        if int(x) < 120
        else f"Every {int(x) // 60} hours",
    )

    request_timeout = st.slider(
        "HTTP Request Timeout (seconds)",
        min_value=3,
        max_value=30,
        value=int(current_settings.get("request_timeout_seconds", "10")),
    )

    auto_hot_swap = st.toggle(
        "Auto Hot-Swap on Failure",
        value=current_settings.get("auto_hot_swap", "true").lower() == "true",
        help="Automatically switch active routing to the Backup Affiliate URL when a Primary URL returns 404/5xx or Out of Stock.",
    )

    global_keywords = st.text_area(
        "Global Out-of-Stock Markers (comma-separated)",
        value=current_settings.get(
            "global_oos_keywords",
            "out of stock, currently unavailable, sold out, no longer available",
        ),
        height=95,
    )

    st.divider()
    st.subheader("Notification Channels")
    notify_email = st.text_input(
        "Alert Email Recipient",
        value=current_settings.get("notify_email", "ops@creatorstudio.io"),
    )
    notify_webhook = st.text_input(
        "Slack / Discord Webhook URL",
        value=current_settings.get("notify_webhook_url", ""),
    )
    col_n1, col_n2 = st.columns(2)
    with col_n1:
        notify_broken = st.checkbox(
            "404 / Dead Links",
            value=current_settings.get("notify_on_broken", "true") == "true",
        )
    with col_n2:
        notify_oos = st.checkbox(
            "Out of Stock",
            value=current_settings.get("notify_on_oos", "true") == "true",
        )

    if st.button("Save Configuration", use_container_width=True, type="primary"):
        db.update_settings(
            {
                "scan_interval_minutes": str(scan_interval),
                "request_timeout_seconds": str(request_timeout),
                "auto_hot_swap": "true" if auto_hot_swap else "false",
                "global_oos_keywords": global_keywords,
                "notify_email": notify_email,
                "notify_webhook_url": notify_webhook,
                "notify_on_broken": "true" if notify_broken else "false",
                "notify_on_oos": "true" if notify_oos else "false",
            }
        )
        st.success("Configuration saved to SQLite database.")

# ---------------------------------------------------------------------------
# Top KPI Overview Row
# ---------------------------------------------------------------------------
st.header("Affiliate Link Health-Checker & Hot-Swapper Dashboard")

total_links = len(links_data)
healthy_count = sum(1 for item in links_data if item["status"] == "Healthy")
broken_count = sum(1 for item in links_data if item["status"] == "Broken")
oos_count = sum(1 for item in links_data if item["status"] == "Out of Stock")
swapped_count = sum(1 for item in links_data if item["is_swapped"] == 1)

kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric("Tracked Links", total_links)
kpi2.metric("Healthy", healthy_count)
kpi3.metric("Broken (4xx/5xx)", broken_count)
kpi4.metric("Out of Stock", oos_count)
kpi5.metric("Active Hot-Swaps", swapped_count)

st.divider()

# ---------------------------------------------------------------------------
# Main Dashboard Tabs
# ---------------------------------------------------------------------------
tab_registry, tab_add, tab_scan = st.tabs(
    ["📋 Link Registry", "➕ Add New Link", "⚡ Run Health Scan"]
)

# ===========================================================================
# TAB 1: LINK REGISTRY
# ===========================================================================
with tab_registry:
    col_filter, col_search = st.columns([1, 2])
    with col_filter:
        selected_status = st.selectbox(
            "Filter by Status",
            options=["All", "Healthy", "Broken", "Out of Stock", "Unchecked"],
            index=0,
        )
    with col_search:
        search_query = st.text_input(
            "Search by Post Title or URL",
            placeholder="Filter by article name, domain, or affiliate tag...",
        )

    filtered_links = links_data
    if selected_status != "All":
        filtered_links = [
            item for item in filtered_links if item["status"] == selected_status
        ]
    if search_query.strip():
        q = search_query.strip().lower()
        filtered_links = [
            item
            for item in filtered_links
            if q in item["content_title"].lower()
            or q in item["tracked_url"].lower()
            or q in item["primary_link"].lower()
            or q in item["backup_link"].lower()
        ]

    if not filtered_links:
        st.info("No affiliate links match your current filter criteria.")
    else:
        df_display = pd.DataFrame(
            [
                {
                    "ID": item["id"],
                    "Associated Content / Post": item["content_title"],
                    "Tracked URL": item["tracked_url"],
                    "Active Target URL": item["active_link"],
                    "Primary Affiliate Link": item["primary_link"],
                    "Backup Affiliate Link": item["backup_link"],
                    "Current Status": item["status"],
                    "Routing Mode": "Backup Active (Swapped)"
                    if item["is_swapped"]
                    else "Primary Active",
                    "HTTP Code": item["http_code"] if item["http_code"] else "—",
                    "Latency (ms)": f"{item['response_time_ms']} ms"
                    if item["response_time_ms"]
                    else "—",
                    "Marker / Detail": item["detected_marker"] or "Nominal",
                    "Last Checked": item["last_checked"],
                }
                for item in filtered_links
            ]
        )

        st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("One-Click Hot-Swap & Link Actions")
        for item in filtered_links:
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([3, 3, 2, 2])
                with c1:
                    st.markdown(f"**{item['content_title']}** (`#{item['id']}`)")
                    st.caption(f"Source Post: {item['tracked_url']}")
                with c2:
                    st.write(f"**Active:** `{item['active_link']}`")
                    st.caption(
                        f"Primary: `{item['primary_link']}`  |  Backup: `{item['backup_link']}`"
                    )
                with c3:
                    status_label = item["status"]
                    if status_label == "Healthy":
                        st.success(f"Healthy ({item['http_code']} · {item['response_time_ms']}ms)")
                    elif status_label == "Broken":
                        st.error(f"Broken ({item['detected_marker'] or item['http_code']})")
                    elif status_label == "Out of Stock":
                        st.warning(f"Out of Stock ({item['detected_marker']})")
                    else:
                        st.info("Unchecked")
                with c4:
                    if item["is_swapped"] == 0:
                        if st.button(
                            "🔥 Hot-Swap to Backup",
                            key=f"swap_{item['id']}",
                            use_container_width=True,
                            type="primary"
                            if item["status"] in ("Broken", "Out of Stock")
                            else "secondary",
                        ):
                            db.hot_swap_link(
                                item["id"],
                                use_backup=True,
                                reason=f"Manual hot-swap from {item['status']} state",
                                triggered_by="User One-Click",
                            )
                            st.toast(
                                f"Swapped '{item['content_title']}' to backup affiliate URL!"
                            )
                            st.rerun()
                    else:
                        if st.button(
                            "↩️ Restore Primary URL",
                            key=f"restore_{item['id']}",
                            use_container_width=True,
                        ):
                            db.hot_swap_link(
                                item["id"],
                                use_backup=False,
                                reason="Manual restore to primary URL",
                                triggered_by="User One-Click",
                            )
                            st.toast(
                                f"Restored '{item['content_title']}' to primary affiliate URL."
                            )
                            st.rerun()

                    if st.button(
                        "🗑️ Delete",
                        key=f"del_{item['id']}",
                        use_container_width=True,
                    ):
                        db.delete_link(item["id"])
                        st.rerun()

# ===========================================================================
# TAB 2: ADD NEW LINK
# ===========================================================================
with tab_add:
    st.subheader("Register New Monitored Affiliate Link")
    st.caption(
        "Add a blog post or landing page along with its primary and backup affiliate destination URLs."
    )

    with st.form("add_affiliate_link_form", clear_on_submit=True):
        f_title = st.text_input(
            "Associated Content / Post Title *",
            placeholder="e.g., Best Noise-Canceling Headphones 2026 Review",
        )
        f_tracked = st.text_input(
            "Tracked Content URL (Blog Post / Page) *",
            placeholder="https://yourblog.com/reviews/best-anc-headphones",
        )
        col_p, col_b = st.columns(2)
        with col_p:
            f_primary = st.text_input(
                "Primary Affiliate Link *",
                placeholder="https://merchant.example.com/product-123?aff=creator01",
            )
        with col_b:
            f_backup = st.text_input(
                "Backup Affiliate Link (Hot-Swap Target) *",
                placeholder="https://alt-merchant.example.com/item-123?ref=creator01",
            )

        f_keywords = st.text_input(
            "Custom Out-of-Stock Keywords (optional, comma-separated)",
            placeholder="backordered, shipping in 4 weeks, discontinued",
        )
        verify_immediately = st.checkbox(
            "Run live HTTP & stock check immediately upon adding", value=True
        )

        submitted = st.form_submit_button(
            "Add Link to Registry", type="primary", use_container_width=True
        )
        if submitted:
            if not (
                f_title.strip()
                and f_tracked.strip()
                and f_primary.strip()
                and f_backup.strip()
            ):
                st.error(
                    "Please fill in all required fields (Content Title, Tracked URL, Primary Affiliate Link, and Backup Affiliate Link)."
                )
            else:
                new_id = db.add_link(
                    content_title=f_title,
                    tracked_url=f_tracked,
                    primary_link=f_primary,
                    backup_link=f_backup,
                    custom_keywords=f_keywords,
                )
                if verify_immediately:
                    res = checker.check_single_url(
                        url=f_primary.strip(),
                        global_keywords=global_keywords,
                        custom_keywords=f_keywords,
                        timeout_seconds=int(request_timeout),
                    )
                    db.update_link_status(
                        link_id=new_id,
                        status=res["status"],
                        http_code=res["http_code"],
                        response_time_ms=res["response_time_ms"],
                        detected_marker=res["detected_marker"],
                    )
                st.success(
                    f"Added '{f_title}' to the Link Registry (ID #{new_id})."
                )
                st.rerun()

# ===========================================================================
# TAB 3: RUN HEALTH SCAN
# ===========================================================================
with tab_scan:
    st.subheader("Batch Affiliate Link Health Scanner")
    st.write(
        "Trigger a real-time asynchronous check across all registered affiliate links. "
        "The scanner verifies HTTP response codes, follows redirect chains, and scrapes page HTML for out-of-stock markers."
    )

    col_btn, col_info = st.columns([1, 2])
    with col_btn:
        run_scan_clicked = st.button(
            "🚀 Run Live Scan Now",
            type="primary",
            use_container_width=True,
        )
    with col_info:
        st.caption(
            f"Auto Hot-Swap is currently **{'ENABLED' if auto_hot_swap else 'DISABLED'}** · "
            f"Timeout: **{request_timeout}s** · "
            f"Monitoring **{len(links_data)}** links"
        )

    if run_scan_clicked:
        if not links_data:
            st.warning("No links in registry to scan. Add a link first.")
        else:
            progress_bar = st.progress(0, text="Initializing asynchronous HTTP scanner...")
            scan_results = checker.run_batch_scan(
                links=links_data,
                global_keywords=global_keywords,
                timeout_seconds=int(request_timeout),
            )

            auto_swapped_records = []
            for idx, res in enumerate(scan_results):
                pct = int(((idx + 1) / len(scan_results)) * 100)
                progress_bar.progress(
                    pct,
                    text=f"Checked ({idx + 1}/{len(scan_results)}): {res['content_title']} -> {res['status']}",
                )
                db.update_link_status(
                    link_id=res["link_id"],
                    status=res["status"],
                    http_code=res["http_code"],
                    response_time_ms=res["response_time_ms"],
                    detected_marker=res["detected_marker"],
                )

                # Perform automated hot-swap if enabled and link failed on primary URL
                link_record = db.get_link_by_id(res["link_id"])
                if (
                    auto_hot_swap
                    and res["status"] in ("Broken", "Out of Stock")
                    and link_record
                    and link_record["is_swapped"] == 0
                ):
                    db.hot_swap_link(
                        link_id=res["link_id"],
                        use_backup=True,
                        reason=f"Auto hot-swap triggered by {res['status']} ({res['detected_marker']})",
                        triggered_by="Automated Scan",
                    )
                    auto_swapped_records.append(res["content_title"])

            st.session_state.scan_results_log = scan_results
            st.session_state.last_scan_summary = {
                "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
                "total": len(scan_results),
                "healthy": sum(1 for r in scan_results if r["status"] == "Healthy"),
                "broken": sum(1 for r in scan_results if r["status"] == "Broken"),
                "oos": sum(1 for r in scan_results if r["status"] == "Out of Stock"),
                "auto_swapped": auto_swapped_records,
            }
            st.rerun()

    if st.session_state.last_scan_summary:
        summary = st.session_state.last_scan_summary
        st.success(
            f"Last Live Scan completed at {summary['timestamp']} — "
            f"{summary['healthy']} Healthy, {summary['broken']} Broken, {summary['oos']} Out of Stock."
        )
        if summary["auto_swapped"]:
            st.warning(
                f"⚡ Auto Hot-Swapped {len(summary['auto_swapped'])} link(s) to backup URLs: "
                + ", ".join(summary["auto_swapped"])
            )

        if st.session_state.scan_results_log:
            st.dataframe(
                pd.DataFrame(st.session_state.scan_results_log),
                use_container_width=True,
                hide_index=True,
            )

    st.divider()
    st.subheader("Recent Hot-Swap Audit Log")
    events = db.get_swap_events(limit=15)
    if not events:
        st.caption("No hot-swap events recorded yet.")
    else:
        st.dataframe(pd.DataFrame(events), use_container_width=True, hide_index=True)
