"""Validation and reconciliation logic for order and payment exports."""

from __future__ import annotations

import re
from zipfile import BadZipFile
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import pandas as pd


ORDER_COLUMNS = {"order_id", "order_date", "expected_amount", "order_status"}
PAYMENT_COLUMNS = {"transaction_id", "order_id", "paid_at", "amount", "payment_status"}

ORDER_STATUSES = {
    "active": "active",
    "confirmed": "active",
    "completed": "active",
    "processing": "active",
    "đang xử lý": "active",
    "đã xác nhận": "active",
    "hoàn thành": "active",
    "hoàn tất": "active",
    "cancelled": "cancelled",
    "canceled": "cancelled",
    "đã hủy": "cancelled",
    "hủy": "cancelled",
}

PAYMENT_STATUSES = {
    "success": "success",
    "succeeded": "success",
    "paid": "success",
    "completed": "success",
    "thành công": "success",
    "đã thanh toán": "success",
    "failed": "failed",
    "thất bại": "failed",
    "pending": "pending",
    "đang chờ": "pending",
    "chờ xử lý": "pending",
    "cancelled": "failed",
    "canceled": "failed",
}

SUMMARY_COLUMNS = [
    "Mã đơn",
    "Ngày đặt",
    "Khách hàng",
    "Trạng thái đơn",
    "Phải thu (VND)",
    "Đã thu ròng (VND)",
    "Chênh lệch (VND)",
    "Số giao dịch thành công",
    "Kết quả",
    "Ghi chú",
]


class DataValidationError(ValueError):
    """An uploaded export cannot be safely reconciled."""


@dataclass
class ReconciliationResult:
    summary: pd.DataFrame
    duplicates: pd.DataFrame
    orders: pd.DataFrame
    payments: pd.DataFrame

    @property
    def issues(self) -> pd.DataFrame:
        return self.summary.loc[self.summary["Kết quả"] != "Khớp"].copy()

    @property
    def matched_orders(self) -> int:
        return int((self.summary["Kết quả"] == "Khớp").sum())

    @property
    def absolute_difference(self) -> int:
        return int(self.summary["Chênh lệch (VND)"].abs().sum())


def read_input_file(source: str | Path | BinaryIO | bytes, filename: str) -> pd.DataFrame:
    """Read an Excel/CSV export while preserving IDs that contain leading zeroes."""
    suffix = Path(filename).suffix.lower()
    if suffix not in {".csv", ".xlsx"}:
        raise DataValidationError("Chỉ hỗ trợ file .csv hoặc .xlsx.")

    if isinstance(source, bytes):
        source = BytesIO(source)

    try:
        if suffix == ".xlsx":
            frame = pd.read_excel(source, dtype=str, keep_default_na=False)
        else:
            try:
                frame = pd.read_csv(
                    source,
                    dtype=str,
                    keep_default_na=False,
                    sep=None,
                    engine="python",
                    encoding="utf-8-sig",
                )
            except UnicodeDecodeError:
                if hasattr(source, "seek"):
                    source.seek(0)
                frame = pd.read_csv(
                    source,
                    dtype=str,
                    keep_default_na=False,
                    sep=None,
                    engine="python",
                    encoding="cp1258",
                )
    except (ValueError, OSError, UnicodeError, BadZipFile, pd.errors.ParserError) as exc:
        raise DataValidationError(f"Không đọc được file {filename}: {exc}") from exc

    if frame.empty:
        raise DataValidationError(f"File {filename} không có dòng dữ liệu.")

    normalized_columns = [str(column).strip().lower() for column in frame.columns]
    if len(set(normalized_columns)) != len(normalized_columns):
        raise DataValidationError(f"File {filename} có tên cột trùng nhau.")
    frame.columns = normalized_columns
    for column in frame.columns:
        frame[column] = frame[column].astype(str).str.strip()
    return frame


def _require_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:
    missing = sorted(required - set(frame.columns))
    if missing:
        raise DataValidationError(f"File {label} thiếu cột: {', '.join(missing)}.")


def parse_vnd(value: str, row_number: int, column: str) -> int:
    text = str(value).strip().replace("\u00a0", " ")
    text = re.sub(r"\s*(?:VND|VNĐ|₫)\s*", "", text, flags=re.IGNORECASE).strip()
    if not re.fullmatch(r"-?(?:\d+|\d{1,3}(?:[., ]\d{3})+)", text):
        raise DataValidationError(
            f"Dòng {row_number}: {column} = '{value}' không phải số VND nguyên hợp lệ."
        )
    return int(re.sub(r"[., ]", "", text))


def _parse_date(value: str, row_number: int, column: str) -> date:
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for pattern in ("%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise DataValidationError(
        f"Dòng {row_number}: {column} = '{value}' phải là YYYY-MM-DD hoặc DD/MM/YYYY."
    )


def _parse_status(value: str, statuses: dict[str, str], row_number: int, column: str) -> str:
    normalized = str(value).strip().casefold()
    if normalized not in statuses:
        raise DataValidationError(
            f"Dòng {row_number}: {column} = '{value}' chưa được hỗ trợ. Xem trạng thái trong hướng dẫn."
        )
    return statuses[normalized]


def validate_orders(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, ORDER_COLUMNS, "đơn hàng")
    orders = frame.copy()
    if "customer_name" not in orders:
        orders["customer_name"] = ""

    for index, row in orders.iterrows():
        line = index + 2
        if not row["order_id"]:
            raise DataValidationError(f"Dòng {line}: order_id đang trống.")
        orders.at[index, "order_date"] = _parse_date(row["order_date"], line, "order_date")
        amount = parse_vnd(row["expected_amount"], line, "expected_amount")
        if amount < 0:
            raise DataValidationError(f"Dòng {line}: expected_amount không được âm.")
        orders.at[index, "expected_amount"] = amount
        orders.at[index, "order_status"] = _parse_status(
            row["order_status"], ORDER_STATUSES, line, "order_status"
        )

    duplicated = orders.loc[orders.duplicated("order_id", keep=False), "order_id"].unique()
    if len(duplicated):
        examples = ", ".join(map(str, duplicated[:5]))
        raise DataValidationError(
            f"File đơn hàng có mã đơn trùng ({examples}). Hãy giữ một dòng cho mỗi mã đơn."
        )

    orders["expected_amount"] = orders["expected_amount"].astype("int64")
    return orders


def validate_payments(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(frame, PAYMENT_COLUMNS, "thanh toán")
    payments = frame.copy()
    payments["Dòng nguồn"] = range(2, len(payments) + 2)
    for index, row in payments.iterrows():
        line = index + 2
        if not row["transaction_id"]:
            raise DataValidationError(f"Dòng {line}: transaction_id đang trống.")
        if not row["order_id"]:
            raise DataValidationError(f"Dòng {line}: order_id đang trống.")
        payments.at[index, "paid_at"] = _parse_date(row["paid_at"], line, "paid_at")
        payments.at[index, "amount"] = parse_vnd(row["amount"], line, "amount")
        payments.at[index, "payment_status"] = _parse_status(
            row["payment_status"], PAYMENT_STATUSES, line, "payment_status"
        )
    payments["amount"] = payments["amount"].astype("int64")
    return payments


def reconcile(orders_frame: pd.DataFrame, payments_frame: pd.DataFrame) -> ReconciliationResult:
    """Match settled payments to orders; negative settled payments are refunds."""
    orders = validate_orders(orders_frame)
    payments = validate_payments(payments_frame)

    duplicate_mask = payments.duplicated("transaction_id", keep=False)
    duplicates = payments.loc[duplicate_mask].copy()
    for transaction_id, group in duplicates.groupby("transaction_id"):
        facts = group[["order_id", "amount", "payment_status"]].drop_duplicates()
        if len(facts) > 1:
            raise DataValidationError(
                f"Mã giao dịch {transaction_id} có thông tin mâu thuẫn. "
                "Hãy sửa file thanh toán trước khi đối soát."
            )

    duplicate_order_ids = set(duplicates["order_id"])
    unique_payments = payments.drop_duplicates("transaction_id", keep="first")
    settled = unique_payments.loc[unique_payments["payment_status"] == "success"]
    totals = settled.groupby("order_id")["amount"].agg(["sum", "count"])
    known_order_ids = set(orders["order_id"])

    records = []
    for _, order in orders.iterrows():
        order_id = order["order_id"]
        expected = 0 if order["order_status"] == "cancelled" else int(order["expected_amount"])
        actual = int(totals.at[order_id, "sum"]) if order_id in totals.index else 0
        count = int(totals.at[order_id, "count"]) if order_id in totals.index else 0
        difference = actual - expected

        if order_id in duplicate_order_ids:
            outcome = "Trùng mã giao dịch"
            note = "Mã giao dịch lặp đã được tính một lần; cần kiểm tra file gốc."
        elif order["order_status"] == "cancelled" and actual != 0:
            outcome = "Đơn đã hủy còn tiền"
            note = "Đơn đã hủy phải có số tiền thu ròng bằng 0."
        elif actual == expected:
            outcome = "Khớp"
            note = ""
        elif actual == 0 and expected > 0:
            outcome = "Thiếu thanh toán"
            note = "Không có giao dịch thành công."
        elif actual < expected:
            outcome = "Thanh toán thiếu"
            note = "Số tiền thu ròng thấp hơn số tiền phải thu."
        else:
            outcome = "Thanh toán dư"
            note = "Số tiền thu ròng cao hơn số tiền phải thu."

        records.append(
            {
                "Mã đơn": order_id,
                "Ngày đặt": order["order_date"],
                "Khách hàng": order["customer_name"],
                "Trạng thái đơn": "Đã hủy" if order["order_status"] == "cancelled" else "Đang hiệu lực",
                "Phải thu (VND)": expected,
                "Đã thu ròng (VND)": actual,
                "Chênh lệch (VND)": difference,
                "Số giao dịch thành công": count,
                "Kết quả": outcome,
                "Ghi chú": note,
            }
        )

    for order_id in totals.index:
        if order_id in known_order_ids:
            continue
        actual = int(totals.at[order_id, "sum"])
        count = int(totals.at[order_id, "count"])
        records.append(
            {
                "Mã đơn": order_id,
                "Ngày đặt": None,
                "Khách hàng": "",
                "Trạng thái đơn": "Không tìm thấy đơn",
                "Phải thu (VND)": 0,
                "Đã thu ròng (VND)": actual,
                "Chênh lệch (VND)": actual,
                "Số giao dịch thành công": count,
                "Kết quả": "Thanh toán không có đơn",
                "Ghi chú": "Mã đơn chỉ có trong file thanh toán."
                + (" Có mã giao dịch trùng." if order_id in duplicate_order_ids else ""),
            }
        )

    summary = pd.DataFrame.from_records(records, columns=SUMMARY_COLUMNS)
    return ReconciliationResult(summary, duplicates, orders, payments)
