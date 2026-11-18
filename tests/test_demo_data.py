from collections import Counter

from demo import DEMO_ORDERS, DEMO_PAYMENTS, load_demo_frames
from reconciliation import read_input_file, reconcile


def test_fictional_store_exports_reconcile_with_expected_cases():
    order_export = read_input_file(DEMO_ORDERS, DEMO_ORDERS.name)
    payment_export = read_input_file(DEMO_PAYMENTS, DEMO_PAYMENTS.name)
    assert len(order_export) == 60
    assert len(payment_export) == 66
    assert all(
        int(row["tiền hàng"]) + int(row["phí giao hàng"]) - int(row["giảm giá"])
        == int(row["tổng tiền"])
        for _, row in order_export.iterrows()
    )

    orders, payments = load_demo_frames()
    result = reconcile(orders, payments)
    outcomes = result.summary.set_index("Mã đơn")["Kết quả"].to_dict()
    counts = Counter(result.summary["Kết quả"])

    assert result.matched_orders == 51
    assert len(result.issues) == 10
    assert len(result.duplicates) == 2
    assert result.absolute_difference == 3_848_000
    assert counts == {
        "Khớp": 51,
        "Thiếu thanh toán": 3,
        "Thanh toán thiếu": 2,
        "Đơn đã hủy còn tiền": 2,
        "Thanh toán dư": 1,
        "Trùng mã giao dịch": 1,
        "Thanh toán không có đơn": 1,
    }
    assert outcomes["DH2609046"] == "Khớp"
    assert outcomes["DH2609050"] == "Khớp"
    assert outcomes["DH2609054"] == "Trùng mã giao dịch"
    assert outcomes["DH2609055"] == "Thanh toán thiếu"
    assert outcomes["DH269999"] == "Thanh toán không có đơn"
    assert result.summary.set_index("Mã đơn").at["DH2609050", "Đã thu ròng (VND)"] == 0
