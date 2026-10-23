import sqlite3
from datetime import datetime
from typing import List, Dict, Optional, Any

DB_PATH = "affiliate_links.db"


def get_connection() -> sqlite3.Connection:
    """Create and return a SQLite database connection with row factory."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize the SQLite database tables and seed initial sample data if empty."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS affiliate_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_title TEXT NOT NULL,
            tracked_url TEXT NOT NULL,
            primary_link TEXT NOT NULL,
            backup_link TEXT NOT NULL,
            active_link TEXT NOT NULL,
            is_swapped INTEGER DEFAULT 0,
            status TEXT DEFAULT 'Unchecked',
            http_code INTEGER DEFAULT 0,
            response_time_ms INTEGER DEFAULT 0,
            detected_marker TEXT DEFAULT '',
            custom_keywords TEXT DEFAULT '',
            last_checked TEXT DEFAULT 'Never',
            created_at TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS swap_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            link_id INTEGER NOT NULL,
            content_title TEXT NOT NULL,
            previous_url TEXT NOT NULL,
            new_url TEXT NOT NULL,
            reason TEXT NOT NULL,
            triggered_by TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )

    default_settings = {
        "scan_interval_minutes": "60",
        "request_timeout_seconds": "10",
        "auto_hot_swap": "true",
        "notify_email": "ops@creatorstudio.io",
        "notify_webhook_url": "https://hooks.slack.com/services/T000/B000/X000",
        "notify_on_broken": "true",
        "notify_on_oos": "true",
        "global_oos_keywords": "out of stock, currently unavailable, sold out, no longer available, item discontinued",
    }
    for key, val in default_settings.items():
        cursor.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val)
        )

    cursor.execute("SELECT COUNT(*) as count FROM affiliate_links")
    row_count = cursor.fetchone()["count"]
    if row_count == 0:
        now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        seed_links = [
            (
                "Best Ergonomic Office Chairs 2026 Guide",
                "https://gearpatrol-blog.example.com/ergonomic-office-chairs",
                "https://httpstat.us/200",
                "https://example.com/?ref=backup-ergochair-store",
                "https://httpstat.us/200",
                0,
                "Healthy",
                200,
                142,
                "",
                "currently unavailable, backordered",
                now_str,
                now_str,
            ),
            (
                "Top Mirrorless Cameras for Travel Vloggers",
                "https://creatorweekly.example.com/mirrorless-cameras-review",
                "https://httpstat.us/404",
                "https://example.org/?aff=bhphoto-camera-backup",
                "https://httpstat.us/404",
                0,
                "Broken",
                404,
                218,
                "HTTP 404 Not Found",
                "sold out, body only unavailable",
                now_str,
                now_str,
            ),
            (
                "Home Espresso Machine Buyer's Handbook",
                "https://baristacraft.example.com/home-espresso-machines",
                "https://www.iana.org/domains/reserved",
                "https://example.net/?partner=seattlecoffee-backup",
                "https://www.iana.org/domains/reserved",
                0,
                "Healthy",
                200,
                164,
                "",
                "out of stock, discontinued model",
                now_str,
                now_str,
            ),
            (
                "Mechanical Keyboards for Software Engineers",
                "https://devdesk.example.com/best-mechanical-keyboards",
                "https://httpstat.us/503",
                "https://example.com/?aff=keychron-direct-backup",
                "https://example.com/?aff=keychron-direct-backup",
                1,
                "Healthy",
                200,
                119,
                "Auto-swapped from 503 primary",
                "sold out, group buy ended",
                now_str,
                now_str,
            ),
        ]
        cursor.executemany(
            """
            INSERT INTO affiliate_links (
                content_title, tracked_url, primary_link, backup_link,
                active_link, is_swapped, status, http_code, response_time_ms,
                detected_marker, custom_keywords, last_checked, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            seed_links,
        )

    conn.commit()
    conn.close()


def get_all_links() -> List[Dict[str, Any]]:
    """Return all monitored affiliate links ordered by ID descending."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM affiliate_links ORDER BY id DESC")
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_link_by_id(link_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single affiliate link record by its primary key."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM affiliate_links WHERE id = ?", (link_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def add_link(
    content_title: str,
    tracked_url: str,
    primary_link: str,
    backup_link: str,
    custom_keywords: str = "",
) -> int:
    """Insert a new affiliate link entry into the registry and return its new ID."""
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    cursor.execute(
        """
        INSERT INTO affiliate_links (
            content_title, tracked_url, primary_link, backup_link,
            active_link, is_swapped, status, http_code, response_time_ms,
            detected_marker, custom_keywords, last_checked, created_at
        ) VALUES (?, ?, ?, ?, ?, 0, 'Unchecked', 0, 0, '', ?, 'Never', ?)
        """,
        (
            content_title.strip(),
            tracked_url.strip(),
            primary_link.strip(),
            backup_link.strip(),
            primary_link.strip(),
            custom_keywords.strip(),
            now_str,
        ),
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return int(new_id)


def update_link_status(
    link_id: int,
    status: str,
    http_code: int,
    response_time_ms: int,
    detected_marker: str = "",
) -> None:
    """Update the health check status, HTTP response code, latency, and marker for a link."""
    conn = get_connection()
    cursor = conn.cursor()
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    cursor.execute(
        """
        UPDATE affiliate_links
        SET status = ?, http_code = ?, response_time_ms = ?, detected_marker = ?, last_checked = ?
        WHERE id = ?
        """,
        (status, http_code, response_time_ms, detected_marker, now_str, link_id),
    )
    conn.commit()
    conn.close()


def hot_swap_link(
    link_id: int,
    use_backup: bool = True,
    reason: str = "Manual hot-swap",
    triggered_by: str = "Manual",
) -> Optional[Dict[str, Any]]:
    """
    Hot-swap a link's active target between its primary affiliate URL and backup affiliate URL.
    Logs the swap event for audit history.
    """
    link = get_link_by_id(link_id)
    if not link:
        return None

    previous_url = link["active_link"]
    new_url = link["backup_link"] if use_backup else link["primary_link"]
    is_swapped_val = 1 if use_backup else 0
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        UPDATE affiliate_links
        SET active_link = ?, is_swapped = ?, last_checked = ?
        WHERE id = ?
        """,
        (new_url, is_swapped_val, now_str, link_id),
    )

    cursor.execute(
        """
        INSERT INTO swap_events (
            link_id, content_title, previous_url, new_url, reason, triggered_by, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            link_id,
            link["content_title"],
            previous_url,
            new_url,
            reason,
            triggered_by,
            now_str,
        ),
    )
    conn.commit()
    conn.close()
    return get_link_by_id(link_id)


def delete_link(link_id: int) -> bool:
    """Delete a monitored affiliate link by ID."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM affiliate_links WHERE id = ?", (link_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_settings() -> Dict[str, str]:
    """Retrieve all configuration settings as a dictionary."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    settings = {row["key"]: row["value"] for row in cursor.fetchall()}
    conn.close()
    return settings


def update_settings(new_settings: Dict[str, str]) -> None:
    """Persist updated configuration settings into the SQLite database."""
    conn = get_connection()
    cursor = conn.cursor()
    for key, value in new_settings.items():
        cursor.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
    conn.commit()
    conn.close()


def get_swap_events(limit: int = 25) -> List[Dict[str, Any]]:
    """Retrieve the most recent hot-swap events."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM swap_events ORDER BY id DESC LIMIT ?", (limit,)
    )
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events
