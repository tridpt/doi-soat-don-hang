"""Local SQLite history for completed reconciliation runs."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from reconciliation import SUMMARY_COLUMNS, ReconciliationResult


DEFAULT_DB_PATH = Path(__file__).resolve().parent / "data" / "history.sqlite3"


@dataclass(frozen=True)
class HistoryItem:
    id: int
    created_at: str
    order_filename: str
    payment_filename: str
    order_count: int
    matched_count: int
    issue_count: int
    absolute_difference: int


@dataclass
class SavedRun:
    item: HistoryItem
    summary: pd.DataFrame
    report_bytes: bytes
    settings: dict


def initialize_history(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS reconciliation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                order_filename TEXT NOT NULL,
                payment_filename TEXT NOT NULL,
                order_count INTEGER NOT NULL,
                matched_count INTEGER NOT NULL,
                issue_count INTEGER NOT NULL,
                absolute_difference INTEGER NOT NULL,
                summary_json TEXT NOT NULL,
                settings_json TEXT NOT NULL,
                report_blob BLOB NOT NULL
            )
            """
        )
        connection.commit()


def save_run(
    result: ReconciliationResult,
    order_filename: str,
    payment_filename: str,
    settings: dict,
    report_bytes: bytes,
    db_path: Path = DEFAULT_DB_PATH,
) -> int:
    initialize_history(db_path)
    timestamp = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d %H:%M:%S")
    summary_json = result.summary.to_json(orient="records", date_format="iso", force_ascii=False)
    settings_json = json.dumps(settings, ensure_ascii=False, sort_keys=True)
    with closing(sqlite3.connect(db_path)) as connection:
        cursor = connection.execute(
            """
            INSERT INTO reconciliation_runs (
                created_at, order_filename, payment_filename, order_count,
                matched_count, issue_count, absolute_difference,
                summary_json, settings_json, report_blob
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                order_filename,
                payment_filename,
                len(result.orders),
                result.matched_orders,
                len(result.issues),
                result.absolute_difference,
                summary_json,
                settings_json,
                sqlite3.Binary(report_bytes),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def _item_from_row(row: sqlite3.Row) -> HistoryItem:
    return HistoryItem(
        id=int(row["id"]),
        created_at=row["created_at"],
        order_filename=row["order_filename"],
        payment_filename=row["payment_filename"],
        order_count=int(row["order_count"]),
        matched_count=int(row["matched_count"]),
        issue_count=int(row["issue_count"]),
        absolute_difference=int(row["absolute_difference"]),
    )


def list_runs(db_path: Path = DEFAULT_DB_PATH) -> list[HistoryItem]:
    initialize_history(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT id, created_at, order_filename, payment_filename, order_count,
                   matched_count, issue_count, absolute_difference
            FROM reconciliation_runs ORDER BY id DESC
            """
        ).fetchall()
    return [_item_from_row(row) for row in rows]


def load_run(run_id: int, db_path: Path = DEFAULT_DB_PATH) -> SavedRun | None:
    initialize_history(db_path)
    with closing(sqlite3.connect(db_path)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT * FROM reconciliation_runs WHERE id = ?", (run_id,)
        ).fetchone()
    if row is None:
        return None
    summary = pd.DataFrame.from_records(json.loads(row["summary_json"]), columns=SUMMARY_COLUMNS)
    parsed_dates = pd.to_datetime(summary["Ngày đặt"], errors="coerce")
    summary["Ngày đặt"] = [value.date() if pd.notna(value) else None for value in parsed_dates]
    return SavedRun(
        item=_item_from_row(row),
        summary=summary,
        report_bytes=bytes(row["report_blob"]),
        settings=json.loads(row["settings_json"]),
    )
