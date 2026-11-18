from datetime import date
from io import BytesIO

import pandas as pd
import pytest
from openpyxl import load_workbook

from history import list_runs, load_run, save_run
from mapping import (
    ORDER_ALIASES,
    PAYMENT_ALIASES,
    apply_business_rules,
    map_export_columns,
    suggest_column,
    suggest_order_rule,
    suggest_payment_rule,
)
from reconciliation import ORDER_COLUMNS, PAYMENT_COLUMNS, DataValidationError, reconcile
from reporting import create_excel_report


def test_vietnamese_exports_with_split_payment_and_positive_refund():
    orders_raw = pd.DataFrame(
        [
            ["A1", "2026-10-01", "An", "100.000", "Đã hủy"],
            ["B1", "2026-10-01", "Bình", "150.000", "Hoàn thành"],
            ["C1", "2026-10-01", "Chi", "90.000", "Hoàn thành"],
        ],
        columns=["Mã đơn", "Ngày đặt", "Tên khách hàng", "Tổng tiền", "Trạng thái"],
    )
    payments_raw = pd.DataFrame(
        [
            ["T1", "A1", "2026-10-01", "100000", "Thành công"],
            ["T2", "A1", "2026-10-02", "100000", "Đã hoàn tiền"],
            ["T3", "B1", "2026-10-01", "100000", "Thành công"],
            ["T4", "B1", "2026-10-02", "50000", "Thành công"],
            ["T5", "C1", "2026-10-02", "90000", "Đang chờ"],
        ],
        columns=["Mã giao dịch", "Mã đơn", "Ngày giao dịch", "Số tiền", "Trạng thái thanh toán"],
    )
    order_selection = {
        field: suggest_column(orders_raw.columns.tolist(), field, ORDER_ALIASES)
        for field in ["order_id", "order_date", "customer_name", "expected_amount", "order_status"]
    }
    payment_selection = {
        field: suggest_column(payments_raw.columns.tolist(), field, PAYMENT_ALIASES)
        for field in ["transaction_id", "order_id", "paid_at", "amount", "payment_status"]
    }
    assert all(order_selection.values())
    assert all(payment_selection.values())

    orders = map_export_columns(orders_raw, order_selection, ORDER_COLUMNS)
    payments = map_export_columns(payments_raw, payment_selection, PAYMENT_COLUMNS)
    order_rules = {value: suggest_order_rule(value) for value in orders["order_status"].unique()}
    payment_rules = {value: suggest_payment_rule(value) for value in payments["payment_status"].unique()}
    normalized_orders, normalized_payments = apply_business_rules(
        orders, payments, order_rules, payment_rules
    )
    result = reconcile(normalized_orders, normalized_payments)

    outcomes = result.summary.set_index("Mã đơn")["Kết quả"].to_dict()
    assert result.matched_orders == 2
    assert outcomes == {"A1": "Khớp", "B1": "Khớp", "C1": "Thiếu thanh toán"}
    assert int(result.summary.set_index("Mã đơn").at["A1", "Đã thu ròng (VND)"]) == 0
    assert int(normalized_payments.loc[1, "amount"]) == -100_000


def test_unmapped_status_and_duplicate_column_selection_are_rejected():
    frame = pd.DataFrame({"order_id": ["A1"], "order_date": ["2026-10-01"]})
    with pytest.raises(DataValidationError, match="nhiều trường"):
        map_export_columns(
            frame,
            {"order_id": "order_id", "order_date": "order_id"},
            {"order_id", "order_date"},
        )

    orders = pd.DataFrame(
        {"order_id": ["A1"], "order_date": ["2026-10-01"], "expected_amount": ["100"], "order_status": ["Đã giao"]}
    )
    payments = pd.DataFrame(
        {"transaction_id": ["T1"], "order_id": ["A1"], "paid_at": ["2026-10-01"], "amount": ["100"], "payment_status": ["success"]}
    )
    with pytest.raises(DataValidationError, match="Chưa chọn quy tắc"):
        apply_business_rules(orders, payments, {}, {"success": "settled"})


def test_history_persists_results_and_excel_report(tmp_path):
    orders = pd.DataFrame(
        {"order_id": ["A1"], "order_date": ["2026-10-01"], "expected_amount": ["100"], "order_status": ["active"]}
    )
    payments = pd.DataFrame(
        {"transaction_id": ["T1"], "order_id": ["A1"], "paid_at": ["2026-10-01"], "amount": ["90"], "payment_status": ["success"]}
    )
    result = reconcile(orders, payments)
    report_bytes = create_excel_report(result)
    db_path = tmp_path / "history.sqlite3"

    run_id = save_run(result, "orders.xlsx", "payments.xlsx", {"status": "success"}, report_bytes, db_path)
    listed = list_runs(db_path)
    loaded = load_run(run_id, db_path)

    assert [item.id for item in listed] == [run_id]
    assert listed[0].issue_count == 1
    assert loaded is not None
    assert loaded.settings == {"status": "success"}
    assert loaded.summary.at[0, "Chênh lệch (VND)"] == -10
    assert loaded.summary.at[0, "Ngày đặt"] == date(2026, 10, 1)
    assert loaded.report_bytes == report_bytes
    workbook = load_workbook(BytesIO(loaded.report_bytes))
    assert workbook["Can_xu_ly"].max_row == 2
