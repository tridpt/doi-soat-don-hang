"""Streamlit UI for daily order and payment reconciliation."""

from __future__ import annotations

import hashlib
import sqlite3
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from demo import DEMO_ORDERS, DEMO_PAYMENTS, load_demo_frames
from history import list_runs, load_run, save_run
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
from reconciliation import (
    ORDER_COLUMNS,
    PAYMENT_COLUMNS,
    DataValidationError,
    read_input_file,
    reconcile,
)
from reporting import create_excel_report


BASE_DIR = Path(__file__).resolve().parent
SAMPLE_ORDERS = BASE_DIR / "data" / "orders_sample.csv"
SAMPLE_PAYMENTS = BASE_DIR / "data" / "payments_sample.csv"
VIETNAMESE_ORDERS = BASE_DIR / "data" / "orders_vietnamese_sample.csv"
VIETNAMESE_PAYMENTS = BASE_DIR / "data" / "payments_vietnamese_sample.csv"
STYLE_PATH = BASE_DIR / "assets" / "style.css"
SUMMARY_VIEW_COLUMNS = [
    "Mã đơn",
    "Kết quả",
    "Chênh lệch (VND)",
    "Phải thu (VND)",
    "Đã thu ròng (VND)",
    "Ghi chú",
    "Ngày đặt",
    "Trạng thái đơn",
    "Khách hàng",
    "Số giao dịch thành công",
]


def render_issue_breakdown(counts: pd.Series) -> None:
    maximum = int(counts.max())
    rows = []
    for label, count in counts.items():
        width = int(count / maximum * 100)
        rows.append(
            '<div class="issue-row">'
            f'<span class="issue-label">{escape(str(label))}</span>'
            f'<span class="issue-track"><span class="issue-fill" style="width:{width}%"></span></span>'
            f'<strong class="issue-count">{int(count)}</strong>'
            '</div>'
        )
    st.markdown('<div class="issue-list">' + ''.join(rows) + '</div>', unsafe_allow_html=True)


def show_summary(frame: pd.DataFrame) -> None:
    visible = frame.loc[:, SUMMARY_VIEW_COLUMNS].copy()
    visible["Ngày đặt"] = visible["Ngày đặt"].map(lambda value: value.isoformat() if value else "")
    st.dataframe(
        visible,
        hide_index=True,
        width="stretch",
        column_config={
            "Mã đơn": st.column_config.TextColumn(width="small"),
            "Kết quả": st.column_config.TextColumn(width="medium"),
            "Chênh lệch (VND)": st.column_config.NumberColumn(format="%,d ₫"),
            "Phải thu (VND)": st.column_config.NumberColumn(format="%,d ₫"),
            "Đã thu ròng (VND)": st.column_config.NumberColumn(format="%,d ₫"),
            "Ghi chú": st.column_config.TextColumn(width="large"),
            "Ngày đặt": st.column_config.TextColumn(width="small"),
        },
    )


def choose_columns(frame, fields, aliases, key_prefix: str) -> dict[str, str | None]:
    choices = ["— Chọn cột —", *frame.columns.tolist()]
    selections = {}
    for field, label, required in fields:
        suggested = suggest_column(frame.columns.tolist(), field, aliases)
        selected = st.selectbox(
            label + ("" if required else " (không bắt buộc)"),
            choices,
            index=choices.index(suggested) if suggested else 0,
            key=f"{key_prefix}_{field}",
        )
        selections[field] = None if selected == choices[0] else selected
    return selections


def choose_status_rules(orders, payments, key_prefix: str) -> tuple[dict[str, str], dict[str, str]]:
    order_choices = {
        "— Chọn quy tắc —": None,
        "Đang hiệu lực (cần thu đủ tiền)": "active",
        "Đã hủy (phải thu bằng 0)": "cancelled",
    }
    payment_choices = {
        "— Chọn quy tắc —": None,
        "Giao dịch hợp lệ (giữ dấu số tiền)": "settled",
        "Hoàn tiền (đổi thành số âm)": "refund",
        "Bỏ qua (chưa thành công)": "ignore",
    }
    order_rules = {}
    payment_rules = {}
    left, right = st.columns(2)
    with left:
        st.markdown("**Trạng thái đơn hàng**")
        counts = orders["order_status"].value_counts(dropna=False)
        for raw_status, count in counts.items():
            suggested = suggest_order_rule(raw_status)
            default_label = next((label for label, value in order_choices.items() if value == suggested), None)
            label = st.selectbox(
                f"{raw_status or '(trống)'} · {count} dòng",
                list(order_choices),
                index=list(order_choices).index(default_label) if default_label else 0,
                key=f"{key_prefix}_order_status_{raw_status}",
            )
            if order_choices[label]:
                order_rules[raw_status] = order_choices[label]
    with right:
        st.markdown("**Trạng thái giao dịch**")
        counts = payments["payment_status"].value_counts(dropna=False)
        for raw_status, count in counts.items():
            suggested = suggest_payment_rule(raw_status)
            default_label = next((label for label, value in payment_choices.items() if value == suggested), None)
            label = st.selectbox(
                f"{raw_status or '(trống)'} · {count} dòng",
                list(payment_choices),
                index=list(payment_choices).index(default_label) if default_label else 0,
                key=f"{key_prefix}_payment_status_{raw_status}",
            )
            if payment_choices[label]:
                payment_rules[raw_status] = payment_choices[label]
    return order_rules, payment_rules


def render_history() -> None:
    st.subheader("Lịch sử đối soát")
    st.caption("Chỉ lưu kết quả và báo cáo Excel trên máy này. File tải lên không được lưu lại.")
    try:
        items = list_runs()
    except sqlite3.Error as exc:
        st.error(f"Không đọc được lịch sử: {exc}")
        return
    if not items:
        st.info("Chưa có lần đối soát nào được lưu. Hãy tải file, đối soát rồi bấm “Lưu kết quả vào lịch sử”.")
        return

    table = pd.DataFrame(
        [
            {
                "Lần lưu": item.id,
                "Thời gian": item.created_at,
                "File đơn hàng": item.order_filename,
                "File thanh toán": item.payment_filename,
                "Tổng đơn": item.order_count,
                "Cần xử lý": item.issue_count,
                "Tiền lệch tuyệt đối (VND)": item.absolute_difference,
            }
            for item in items
        ]
    )
    st.dataframe(table, hide_index=True, width="stretch")
    by_id = {item.id: item for item in items}
    selected_id = st.selectbox(
        "Mở lần đối soát",
        list(by_id),
        format_func=lambda run_id: f"#{run_id} · {by_id[run_id].created_at} · {by_id[run_id].issue_count} cần xử lý",
    )
    try:
        saved = load_run(selected_id)
    except sqlite3.Error as exc:
        st.error(f"Không mở được lần đối soát: {exc}")
        return
    if saved is None:
        st.error("Không tìm thấy lần đối soát này.")
        return

    st.markdown(f"**{saved.item.order_filename}** ↔ **{saved.item.payment_filename}**")
    st.caption(
        f"{saved.item.order_count} đơn · {saved.item.matched_count} khớp · "
        f"{saved.item.issue_count} cần xử lý · {saved.item.absolute_difference:,.0f} ₫ lệch tuyệt đối"
    )
    issues = saved.summary.loc[saved.summary["Kết quả"] != "Khớp"]
    show_summary(issues)
    st.download_button(
        "Tải lại báo cáo Excel",
        saved.report_bytes,
        file_name=f"bao-cao-doi-soat-{saved.item.id}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    with st.expander("Xem cấu hình cột và trạng thái đã dùng"):
        st.json(saved.settings)

st.set_page_config(page_title="Đối soát đơn hàng", page_icon="🧾", layout="wide")
st.markdown(f"<style>{STYLE_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

st.title("Đối soát đơn hàng & thanh toán")
st.caption("Đối chiếu dữ liệu, tìm sai lệch và xuất báo cáo.")

mode_labels = {
    "Cửa hàng giả lập": "Cửa hàng giả lập",
    "Xem dữ liệu mẫu": "Mẫu nhanh",
    "Tải file của bạn": "Tải file",
    "Lịch sử": "Lịch sử",
}
mode = st.selectbox(
    "Nguồn dữ liệu",
    list(mode_labels),
    format_func=mode_labels.get,
    width=320,
)

if mode == "Lịch sử":
    render_history()
    st.stop()

try:
    if mode == "Cửa hàng giả lập":
        orders_name = DEMO_ORDERS.name
        payments_name = DEMO_PAYMENTS.name
        orders_frame, payments_frame = load_demo_frames()
        settings = {"nguon": "cua_hang_gia_lap", "ky": "2026-09"}
        with st.container(border=True):
            st.markdown("**Dữ liệu cửa hàng giả lập · tháng 9/2026**")
            st.caption("60 đơn · 66 giao dịch · dữ liệu hoàn toàn giả lập.")
            demo_a, demo_b = st.columns(2)
            demo_a.download_button(
                "Tải file đơn hàng",
                DEMO_ORDERS.read_bytes(),
                DEMO_ORDERS.name,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
            demo_b.download_button(
                "Tải file giao dịch",
                DEMO_PAYMENTS.read_bytes(),
                DEMO_PAYMENTS.name,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
        with st.expander("Xem các tình huống trong bộ dữ liệu"):
            st.markdown(
                """
                - `DH2609046`, `DH2609059`: một đơn được thanh toán qua nhiều giao dịch.
                - `DH2609047`, `DH2609052`, `DH2609053`: không có giao dịch thành công.
                - `DH2609048`, `DH2609049`: thanh toán thiếu hoặc dư.
                - `DH2609050`, `DH2609051`, `DH2609056`: đơn hủy với các mức hoàn tiền khác nhau.
                - `DH2609054`: mã giao dịch trùng; `DH269999`: thanh toán không có đơn.
                - `DH2609055`: đơn đang hiệu lực nhưng bị hoàn tiền một phần.
                """
            )
    elif mode == "Xem dữ liệu mẫu":
        orders_name = SAMPLE_ORDERS.name
        payments_name = SAMPLE_PAYMENTS.name
        orders_frame = read_input_file(SAMPLE_ORDERS, orders_name)
        payments_frame = read_input_file(SAMPLE_PAYMENTS, payments_name)
        settings = {"nguon": "du_lieu_mau"}
        with st.container(border=True):
            st.markdown("**Mẫu nhanh**")
            st.caption("Bộ dữ liệu ngắn để xem các trường hợp khớp, thiếu, dư, trùng và thanh toán không có đơn.")
    else:
        left, right = st.columns(2)
        with left:
            orders_file = st.file_uploader("File đơn hàng", type=["csv", "xlsx"], key="orders")
        with right:
            payments_file = st.file_uploader("File thanh toán", type=["csv", "xlsx"], key="payments")
        if not orders_file or not payments_file:
            st.info("Tải đủ hai file để bắt đầu đối soát. Có thể tải file mẫu bên dưới để xem cấu trúc cột.")
            with st.expander("Xem cấu trúc file và tải dữ liệu mẫu"):
                st.markdown(
                    "**Đơn hàng:** `order_id`, `order_date`, `customer_name` (không bắt buộc), "
                    "`expected_amount`, `order_status`.  "
                    "\n**Thanh toán:** `transaction_id`, `order_id`, `paid_at`, `amount`, `payment_status`."
                )
                a, b = st.columns(2)
                a.download_button("Tải mẫu đơn hàng", SAMPLE_ORDERS.read_bytes(), "orders_sample.csv", "text/csv")
                b.download_button("Tải mẫu thanh toán", SAMPLE_PAYMENTS.read_bytes(), "payments_sample.csv", "text/csv")
                c, d = st.columns(2)
                c.download_button("Tải mẫu đơn hàng tiếng Việt", VIETNAMESE_ORDERS.read_bytes(), VIETNAMESE_ORDERS.name, "text/csv")
                d.download_button("Tải mẫu thanh toán tiếng Việt", VIETNAMESE_PAYMENTS.read_bytes(), VIETNAMESE_PAYMENTS.name, "text/csv")
            st.stop()

        orders_source = orders_file.getvalue()
        payments_source = payments_file.getvalue()
        orders_name = orders_file.name
        payments_name = payments_file.name
        orders_raw = read_input_file(orders_source, orders_name)
        payments_raw = read_input_file(payments_source, payments_name)
        order_key = hashlib.sha256(orders_source).hexdigest()[:12]
        payment_key = hashlib.sha256(payments_source).hexdigest()[:12]

        st.caption("Ứng dụng gợi ý cột và quy tắc trạng thái. Hãy kiểm tra các mục bên dưới trước khi dùng kết quả.")
        with st.expander("Xem trước dữ liệu gốc (5 dòng)"):
            preview_left, preview_right = st.columns(2)
            preview_left.dataframe(orders_raw.head(), hide_index=True, width="stretch")
            preview_right.dataframe(payments_raw.head(), hide_index=True, width="stretch")
        all_order_columns_found = all(
            suggest_column(orders_raw.columns.tolist(), field, ORDER_ALIASES)
            for field, _, required in ORDER_FIELDS if required
        )
        all_payment_columns_found = all(
            suggest_column(payments_raw.columns.tolist(), field, PAYMENT_ALIASES)
            for field, _, required in PAYMENT_FIELDS if required
        )
        with st.expander("1. Ghép cột từ hai file", expanded=not (all_order_columns_found and all_payment_columns_found)):
            column_left, column_right = st.columns(2)
            with column_left:
                st.markdown("**File đơn hàng**")
                order_columns = choose_columns(orders_raw, ORDER_FIELDS, ORDER_ALIASES, f"order_{order_key}")
            with column_right:
                st.markdown("**File thanh toán**")
                payment_columns = choose_columns(
                    payments_raw, PAYMENT_FIELDS, PAYMENT_ALIASES, f"payment_{payment_key}"
                )
        orders_mapped = map_export_columns(orders_raw, order_columns, ORDER_COLUMNS)
        payments_mapped = map_export_columns(payments_raw, payment_columns, PAYMENT_COLUMNS)

        known_order_statuses = all(
            suggest_order_rule(value) is not None for value in orders_mapped["order_status"].unique()
        )
        known_payment_statuses = all(
            suggest_payment_rule(value) is not None for value in payments_mapped["payment_status"].unique()
        )
        with st.expander("2. Quy tắc trạng thái", expanded=not (known_order_statuses and known_payment_statuses)):
            st.caption("Giao dịch hoàn tiền được đổi thành số âm; giao dịch bỏ qua không cộng vào tiền đã thu.")
            order_rules, payment_rules = choose_status_rules(
                orders_mapped, payments_mapped, f"rules_{order_key}_{payment_key}"
            )
        orders_frame, payments_frame = apply_business_rules(
            orders_mapped, payments_mapped, order_rules, payment_rules
        )
        settings = {
            "cot_don_hang": order_columns,
            "cot_thanh_toan": payment_columns,
            "trang_thai_don": order_rules,
            "trang_thai_giao_dich": payment_rules,
        }

    result = reconcile(orders_frame, payments_frame)
except DataValidationError as exc:
    st.error(str(exc))
    st.stop()

st.subheader("Tổng quan")
metric_a, metric_b, metric_c, metric_d = st.columns(4)
metric_a.metric("Tổng đơn hàng", f"{len(result.orders):,}")
metric_b.metric("Đã khớp", f"{result.matched_orders:,}")
metric_c.metric("Cần xử lý", f"{len(result.issues):,}")
metric_d.metric("Tổng lệch tuyệt đối", f"{result.absolute_difference:,.0f} ₫")

st.caption(
    "Tiền lệch tuyệt đối là tổng độ lệch của từng đơn và khoản thanh toán không có đơn; "
    "mã giao dịch trùng chỉ tính một lần."
)

report_bytes = create_excel_report(result)
chart_col, action_col = st.columns([3, 2], gap="large")
with chart_col:
    st.subheader("Cơ cấu vấn đề")
    counts = result.issues["Kết quả"].value_counts()
    if counts.empty:
        st.success("Không có trường hợp cần xử lý.")
    else:
        render_issue_breakdown(counts)
with action_col:
    st.subheader("Xuất báo cáo")
    st.caption("File Excel gồm các trường hợp cần xử lý, toàn bộ đơn và giao dịch trùng.")
    st.download_button(
        "Tải báo cáo đối soát",
        data=report_bytes,
        file_name="bao-cao-doi-soat.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        width="stretch",
    )
    if st.button("Lưu kết quả vào lịch sử", width="stretch"):
        try:
            run_id = save_run(result, orders_name, payments_name, settings, report_bytes)
        except sqlite3.Error as exc:
            st.error(f"Không lưu được lịch sử: {exc}")
        else:
            st.success(f"Đã lưu lần đối soát #{run_id}. Mở mục “Lịch sử” để xem lại.")
    st.caption("Chỉ lưu khi bạn bấm nút. File nguồn không được lưu lại.")

st.subheader("Chi tiết đối soát")
issues_tab, all_tab, duplicate_tab = st.tabs(
    [f"Cần xử lý ({len(result.issues)})", "Tất cả đơn", f"Giao dịch trùng ({len(result.duplicates)})"]
)

with issues_tab:
    filter_col, search_col = st.columns([2, 2])
    issue_types = sorted(result.issues["Kết quả"].unique())
    with filter_col.popover("Lọc vấn đề", width="stretch"):
        selected_types = [
            issue_type
            for issue_type in issue_types
            if st.checkbox(issue_type, value=True, key=f"issue_type_{issue_type}")
        ]
    filter_col.caption(f"Đang chọn {len(selected_types)} / {len(issue_types)} loại vấn đề")
    search = search_col.text_input("Tìm mã đơn", placeholder="Ví dụ: DH003")
    filtered = result.issues.loc[result.issues["Kết quả"].isin(selected_types)]
    if search.strip():
        filtered = filtered.loc[
            filtered["Mã đơn"].astype(str).str.contains(search.strip(), case=False, regex=False)
        ]
    show_summary(filtered)
    st.caption(f"Hiển thị {len(filtered)} / {len(result.issues)} trường hợp cần xử lý.")

with all_tab:
    show_summary(result.summary)

with duplicate_tab:
    if result.duplicates.empty:
        st.success("Không có mã giao dịch trùng.")
    else:
        st.warning("Các dòng có cùng mã giao dịch được tính một lần. Hãy xác minh với file gốc.")
        st.dataframe(
            result.duplicates[
                ["Dòng nguồn", "transaction_id", "order_id", "paid_at", "amount", "payment_status"]
            ],
            hide_index=True,
            width="stretch",
        )

with st.expander("Cấu trúc file và quy tắc đối soát"):
    st.markdown(
        """
        - Ở chế độ tải file, hãy ghép các cột của file gốc với mã đơn, ngày đặt,
          số tiền phải thu, trạng thái đơn; và mã giao dịch, mã đơn liên quan,
          ngày giao dịch, số tiền, trạng thái giao dịch. Tên khách hàng là tùy chọn.
          Mỗi mã đơn chỉ xuất hiện một lần trong file đơn hàng.
        - Ngày dùng `YYYY-MM-DD` hoặc `DD/MM/YYYY`. Tiền là số VND nguyên;
          có thể có dấu phân cách hàng nghìn (`250000`, `250.000`, `250,000`).
        - Chọn cách hiểu cho từng trạng thái đơn: đang hiệu lực hoặc đã hủy.
          Đơn đã hủy phải có số tiền thu ròng bằng 0.
        - Chọn cách hiểu cho từng trạng thái giao dịch: hợp lệ (giữ dấu tiền),
          hoàn tiền (đổi thành số âm), hoặc bỏ qua. Một đơn có thể có nhiều giao dịch.
        - Nếu mã giao dịch lặp nhưng nội dung mâu thuẫn, ứng dụng dừng đối soát
          để tránh báo cáo sai.
        - Nút **Lưu kết quả vào lịch sử** lưu bảng kết quả và báo cáo Excel trong
          SQLite trên máy này. File CSV/XLSX gốc không được lưu lại.
        """
    )
    sample_a, sample_b = st.columns(2)
    sample_a.download_button("Tải file đơn hàng mẫu", SAMPLE_ORDERS.read_bytes(), "orders_sample.csv", "text/csv")
    sample_b.download_button("Tải file thanh toán mẫu", SAMPLE_PAYMENTS.read_bytes(), "payments_sample.csv", "text/csv")
    sample_c, sample_d = st.columns(2)
    sample_c.download_button("Tải mẫu đơn hàng tiếng Việt", VIETNAMESE_ORDERS.read_bytes(), VIETNAMESE_ORDERS.name, "text/csv")
    sample_d.download_button("Tải mẫu thanh toán tiếng Việt", VIETNAMESE_PAYMENTS.read_bytes(), VIETNAMESE_PAYMENTS.name, "text/csv")
