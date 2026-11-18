"""Load the fictional online-store exports through the same mapping rules as uploads."""

from pathlib import Path

import pandas as pd

from mapping import (
    ORDER_ALIASES,
    ORDER_FIELDS,
    PAYMENT_ALIASES,
    PAYMENT_FIELDS,
    apply_business_rules,
    map_export_columns,
    suggest_column,
    suggest_order_rule,
    suggest_payment_rule,
)
from reconciliation import ORDER_COLUMNS, PAYMENT_COLUMNS, DataValidationError, read_input_file


DATA_DIR = Path(__file__).resolve().parent / "data"
DEMO_ORDERS = DATA_DIR / "demo_orders_2026_09.xlsx"
DEMO_PAYMENTS = DATA_DIR / "demo_payments_2026_09.xlsx"


def load_demo_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    orders_raw = read_input_file(DEMO_ORDERS, DEMO_ORDERS.name)
    payments_raw = read_input_file(DEMO_PAYMENTS, DEMO_PAYMENTS.name)

    order_columns = {
        field: suggest_column(orders_raw.columns.tolist(), field, ORDER_ALIASES)
        for field, _, _ in ORDER_FIELDS
    }
    payment_columns = {
        field: suggest_column(payments_raw.columns.tolist(), field, PAYMENT_ALIASES)
        for field, _, _ in PAYMENT_FIELDS
    }
    orders = map_export_columns(orders_raw, order_columns, ORDER_COLUMNS)
    payments = map_export_columns(payments_raw, payment_columns, PAYMENT_COLUMNS)

    order_rules = {status: suggest_order_rule(status) for status in orders["order_status"].unique()}
    payment_rules = {
        status: suggest_payment_rule(status) for status in payments["payment_status"].unique()
    }
    if any(rule is None for rule in (*order_rules.values(), *payment_rules.values())):
        raise DataValidationError("Bộ dữ liệu giả lập có trạng thái chưa được cấu hình.")
    return apply_business_rules(orders, payments, order_rules, payment_rules)
