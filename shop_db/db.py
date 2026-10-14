"""Connection handling, schema extensions and reset for the working database."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SOURCE_DB = DATA_DIR / "campus_customs.db"
WORKING_DB = DATA_DIR / "campus_customs_new.db"

# Tables we add on top of the shipped schema.  They live only in the working
# copy, so resetting the shop also wipes them clean.
EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    id            INTEGER PRIMARY KEY,
    kind          TEXT NOT NULL,
    ref_id        INTEGER,
    ticket_id     INTEGER,
    amount        REAL NOT NULL,
    account       TEXT NOT NULL,
    memo          TEXT,
    payload       TEXT,
    status        TEXT NOT NULL,
    requested_by  TEXT NOT NULL,
    requested_at  TEXT NOT NULL,
    decided_by    TEXT,
    decided_at    TEXT,
    decision_note TEXT,
    result        TEXT
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id            INTEGER PRIMARY KEY,
    vendor_id     INTEGER NOT NULL,
    sku           TEXT NOT NULL,
    size          TEXT NOT NULL,
    qty           INTEGER NOT NULL,
    unit_cost     REAL NOT NULL,
    total         REAL NOT NULL,
    status        TEXT NOT NULL,
    expected_date TEXT NOT NULL,
    invoice_id    INTEGER,
    ticket_id     INTEGER,
    approval_id   INTEGER,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (vendor_id) REFERENCES vendors(id)
);

CREATE TABLE IF NOT EXISTS drafts (
    id         INTEGER PRIMARY KEY,
    ticket_id  INTEGER,
    channel    TEXT NOT NULL,
    recipient  TEXT NOT NULL,
    subject    TEXT NOT NULL,
    body       TEXT NOT NULL,
    author     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_log (
    id        INTEGER PRIMARY KEY,
    run_id    TEXT,
    ts        TEXT NOT NULL,
    kind      TEXT NOT NULL,
    agent     TEXT,
    ticket_id INTEGER,
    summary   TEXT,
    detail    TEXT
);
"""

# Columns added to the shipped ``tickets`` table.
TICKET_COLUMNS = {
    "assigned_to": "TEXT",
    "resolution": "TEXT",
    "updated_at": "TEXT",
}


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Open the working database with foreign keys and dict-style rows.

    ``sqlite3``'s own context manager commits but does *not* close, which leaks
    a file handle per call and leaves Windows unable to delete the database on
    reset.  This wrapper always closes.
    """
    conn = sqlite3.connect(db_path or WORKING_DB, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _apply_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(EXTRA_SCHEMA)
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(tickets)")}
    for column, decl in TICKET_COLUMNS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE tickets ADD COLUMN {column} {decl}")
    conn.commit()


def ensure_working_db() -> Path:
    """Create the working copy from the pristine database if it is missing."""
    if not SOURCE_DB.exists():
        raise FileNotFoundError(
            f"Pristine database not found at {SOURCE_DB}. Extract data.zip first."
        )
    if not WORKING_DB.exists():
        shutil.copyfile(SOURCE_DB, WORKING_DB)
    with connect() as conn:
        _apply_schema(conn)
    return WORKING_DB


def reset_working_db() -> Path:
    """Restore the working copy from the pristine database, dropping all work."""
    if not SOURCE_DB.exists():
        raise FileNotFoundError(f"Pristine database not found at {SOURCE_DB}.")
    # Fold any leftover write-ahead log back in so the sidecar files can go.
    if WORKING_DB.exists():
        try:
            with connect() as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("PRAGMA journal_mode = DELETE")
        except sqlite3.DatabaseError:
            pass
    for suffix in ("-wal", "-shm"):
        stale = WORKING_DB.with_name(WORKING_DB.name + suffix)
        if stale.exists():
            stale.unlink(missing_ok=True)
    shutil.copyfile(SOURCE_DB, WORKING_DB)
    with connect() as conn:
        _apply_schema(conn)
    return WORKING_DB


def shop_today(conn: sqlite3.Connection) -> date:
    """The shop's own clock, from ``desk.date_today`` -- not the wall clock."""
    row = conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
    return date.fromisoformat(row["date_today"])


def days_overdue(conn: sqlite3.Connection, due: str) -> int:
    """Positive when ``due`` is in the past relative to the shop's date."""
    return (shop_today(conn) - date.fromisoformat(due)).days


def add_days(day: date, n: int) -> str:
    return (day + timedelta(n)).isoformat()


def rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params)]


def one(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> dict[str, Any] | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"
