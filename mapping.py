"""Adapt exports from different sales and payment systems to the app schema."""

from __future__ import annotations

import re
import unicodedata
from typing import Mapping

import pandas as pd

from reconciliation import (
    ORDER_COLUMNS,
    ORDER_STATUSES,
    PAYMENT_COLUMNS,
    PAYMENT_STATUSES,
    DataValidationError,
    parse_vnd,
)


ORDER_FIELDS = (
    ("order_id", "Mã đơn", True),
    ("order_date", "Ngày đặt", True),
    ("customer_name", "Tên khách hàng", False),
    ("expected_amount", "Số tiền phải thu", True),
    ("order_status", "Trạng thái đơn", True),
)

PAYMENT_FIELDS = (
    ("transaction_id", "Mã giao dịch", True),
    ("order_id", "Mã đơn liên quan", True),
    ("paid_at", "Ngày giao dịch", True),
    ("amount", "Số tiền giao dịch", True),
    ("payment_status", "Trạng thái giao dịch", True),
)

ORDER_ALIASES = {
    "order_id": ("mã đơn", "mã đơn hàng", "số đơn hàng", "order code", "order number"),
    "order_date": ("ngày đặt", "ngày tạo đơn", "ngày tạo", "created at", "order time"),
    "customer_name": ("khách hàng", "tên khách hàng", "tên người mua", "customer", "buyer name"),
    "expected_amount": ("thành tiền", "tổng tiền", "giá trị đơn", "total", "total amount", "amount due"),
    "order_status": ("trạng thái", "trạng thái đơn", "order state", "status"),
}

PAYMENT_ALIASES = {
    "transaction_id": ("mã giao dịch", "payment id", "transaction code", "transaction number"),
    "order_id": ("mã đơn", "mã đơn hàng", "order code", "order number"),
    "paid_at": ("ngày thanh toán", "ngày giao dịch", "thời gian thanh toán", "transaction date", "created at"),
    "amount": ("số tiền", "số tiền thanh toán", "giá trị giao dịch", "payment amount", "total amount"),
    "payment_status": ("trạng thái thanh toán", "trạng thái giao dịch", "payment state", "status"),
}

REFUND_STATUSES = {"refund", "refunded", "hoàn tiền", "đã hoàn tiền", "hoàn trả"}


def _normalized_name(value: str) -> str:
    text = str(value).strip().casefold().replace("đ", "d")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def suggest_column(columns: list[str], field: str, aliases: Mapping[str, tuple[str, ...]]) -> str | None:
    """Prefer an exact canonical header, then common English/Vietnamese aliases."""
    normalized_columns = {_normalized_name(column): column for column in columns}
    for candidate in (field, *aliases.get(field, ())):
        found = normalized_columns.get(_normalized_name(candidate))
        if found is not None:
            return found
    return None


def map_export_columns(
    frame: pd.DataFrame,
    selections: Mapping[str, str | None],
    required: set[str],
) -> pd.DataFrame:
    """Build a canonical frame using only the explicitly selected source columns."""
    missing = sorted(field for field in required if not selections.get(field))
    if missing:
        raise DataValidationError(f"Chưa chọn cột cho: {', '.join(missing)}.")

    chosen = [source for source in selections.values() if source]
    if len(chosen) != len(set(chosen)):
        raise DataValidationError("Một cột nguồn đang được ghép cho nhiều trường. Hãy chọn cột khác nhau.")
    unknown = [source for source in chosen if source not in frame.columns]
    if unknown:
        raise DataValidationError(f"Không tìm thấy cột nguồn: {', '.join(unknown)}.")

    mapped = pd.DataFrame(index=frame.index)
    for field, source in selections.items():
        if source:
            mapped[field] = frame[source].copy()
    return mapped


def suggest_order_rule(raw_status: str) -> str | None:
    return ORDER_STATUSES.get(str(raw_status).strip().casefold())


def suggest_payment_rule(raw_status: str) -> str | None:
    normalized = str(raw_status).strip().casefold()
    if normalized in REFUND_STATUSES:
        return "refund"
    status = PAYMENT_STATUSES.get(normalized)
    if status == "success":
        return "settled"
    if status in {"failed", "pending"}:
        return "ignore"
    return None


def apply_business_rules(
    orders: pd.DataFrame,
    payments: pd.DataFrame,
    order_rules: Mapping[str, str],
    payment_rules: Mapping[str, str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Normalize statuses and positive refund exports before reconciliation."""
    if not ORDER_COLUMNS.issubset(orders.columns) or not PAYMENT_COLUMNS.issubset(payments.columns):
        raise DataValidationError("Cần ghép đủ các cột bắt buộc trước khi áp dụng quy tắc.")

    normalized_orders = orders.copy()
    normalized_payments = payments.copy()

    raw_order_statuses = normalized_orders["order_status"].astype(str).str.strip()
    raw_payment_statuses = normalized_payments["payment_status"].astype(str).str.strip()
    missing_orders = sorted(set(raw_order_statuses) - set(order_rules))
    missing_payments = sorted(set(raw_payment_statuses) - set(payment_rules))
    if missing_orders or missing_payments:
        parts = []
        if missing_orders:
            parts.append(f"trạng thái đơn: {', '.join(missing_orders)}")
        if missing_payments:
            parts.append(f"trạng thái giao dịch: {', '.join(missing_payments)}")
        raise DataValidationError("Chưa chọn quy tắc cho " + "; ".join(parts) + ".")

    if any(value not in {"active", "cancelled"} for value in order_rules.values()):
        raise DataValidationError("Quy tắc trạng thái đơn không hợp lệ.")
    if any(value not in {"settled", "refund", "ignore"} for value in payment_rules.values()):
        raise DataValidationError("Quy tắc trạng thái giao dịch không hợp lệ.")

    normalized_orders["order_status"] = raw_order_statuses.map(order_rules)
    actions = raw_payment_statuses.map(payment_rules)
    normalized_payments["payment_status"] = actions.map(
        {"settled": "success", "refund": "success", "ignore": "failed"}
    )
    for index in normalized_payments.index[actions == "refund"]:
        amount = parse_vnd(normalized_payments.at[index, "amount"], int(index) + 2, "amount")
        normalized_payments.at[index, "amount"] = str(-abs(amount))

    return normalized_orders, normalized_payments
