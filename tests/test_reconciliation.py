from datetime import date
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import load_workbook

from reconciliation import DataValidationError, read_input_file, reconcile
from reporting import create_excel_report


DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def sample_result():
    orders = read_input_file(DATA_DIR / "orders_sample.csv", "orders_sample.csv")
    payments = read_input_file(DATA_DIR / "payments_sample.csv", "payments_sample.csv")
    return reconcile(orders, payments)


def test_sample_reconciliation_covers_business_cases():
    result = sample_result()
    outcomes = result.summary.set_index("Mã đơn")["Kết quả"].to_dict()

    assert len(result.orders) == 12
    assert result.matched_orders == 7
    assert len(result.issues) == 6
    assert result.absolute_difference == 789_000
    assert outcomes["DH002"] == "Khớp"  # two partial payments
    assert outcomes["DH003"] == "Thanh toán thiếu"
    assert outcomes["DH004"] == "Thanh toán dư"
    assert outcomes["DH005"] == "Thiếu thanh toán"
    assert outcomes["DH006"] == "Khớp"  # cancelled, then refunded
    assert outcomes["DH007"] == "Trùng mã giao dịch"
    assert outcomes["DH008"] == "Thiếu thanh toán"  # failed payment is excluded
    assert outcomes["DH999"] == "Thanh toán không có đơn"
    assert result.summary.set_index("Mã đơn").at["DH007", "Đã thu ròng (VND)"] == 720_000


def test_conflicting_duplicate_transaction_is_rejected():
    orders = read_input_file(DATA_DIR / "orders_sample.csv", "orders_sample.csv")
    payments = read_input_file(DATA_DIR / "payments_sample.csv", "payments_sample.csv")
    payments.loc[payments["transaction_id"] == "GD007", "amount"] = ["720000", "700000"]

    with pytest.raises(DataValidationError, match="thông tin mâu thuẫn"):
        reconcile(orders, payments)


def test_duplicate_order_id_is_rejected():
    orders = read_input_file(DATA_DIR / "orders_sample.csv", "orders_sample.csv")
    payments = read_input_file(DATA_DIR / "payments_sample.csv", "payments_sample.csv")
    orders = pd.concat([orders, orders.iloc[[0]]], ignore_index=True)

    with pytest.raises(DataValidationError, match="mã đơn trùng"):
        reconcile(orders, payments)


def test_reader_preserves_leading_zero_ids_and_semicolon_csv():
    csv = b"order_id;order_date;expected_amount;order_status\n0007;2026-10-01;250000;active\n"
    frame = read_input_file(csv, "orders.csv")
    assert frame.at[0, "order_id"] == "0007"


def test_xlsx_import_accepts_excel_dates_and_grouped_vnd_amounts():
    orders = pd.DataFrame(
        [
            {
                "order_id": "0007",
                "order_date": date(2026, 10, 1),
                "expected_amount": "1.250.000",
                "order_status": "active",
            }
        ]
    )
    payments = pd.DataFrame(
        [
            {
                "transaction_id": "TX-7",
                "order_id": "0007",
                "paid_at": date(2026, 10, 1),
                "amount": "1,250,000",
                "payment_status": "success",
            }
        ]
    )
    order_bytes = BytesIO()
    payment_bytes = BytesIO()
    orders.to_excel(order_bytes, index=False)
    payments.to_excel(payment_bytes, index=False)

    result = reconcile(
        read_input_file(order_bytes.getvalue(), "orders.xlsx"),
        read_input_file(payment_bytes.getvalue(), "payments.xlsx"),
    )
    assert result.matched_orders == 1
    assert result.absolute_difference == 0


def test_excel_report_has_action_sheets_and_literal_uploaded_text():
    result = sample_result()
    result.summary.loc[result.summary["Mã đơn"] == "DH003", "Khách hàng"] = '=HYPERLINK("bad")'
    workbook = load_workbook(BytesIO(create_excel_report(result)))

    assert workbook.sheetnames == ["Can_xu_ly", "Tat_ca_don", "Giao_dich_trung"]
    assert workbook["Can_xu_ly"].max_row == 7
    assert workbook["Giao_dich_trung"].max_row == 3
    assert workbook["Can_xu_ly"]["C2"].value == '=HYPERLINK("bad")'
    assert workbook["Can_xu_ly"]["C2"].data_type == "s"
