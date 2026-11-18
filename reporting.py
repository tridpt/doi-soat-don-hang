"""Create an Excel workbook that operations staff can act on."""

from __future__ import annotations

from datetime import date
from io import BytesIO

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from reconciliation import ReconciliationResult


HEADER_FILL = PatternFill("solid", fgColor="153B50")
HEADER_FONT = Font(color="FFFFFF", bold=True)
ISSUE_FILL = PatternFill("solid", fgColor="FFF0D9")
MONEY_COLUMNS = {"Phải thu (VND)", "Đã thu ròng (VND)", "Chênh lệch (VND)", "Số tiền (VND)"}


def _write_frame(workbook: Workbook, title: str, frame: pd.DataFrame) -> None:
    sheet = workbook.create_sheet(title)
    columns = list(frame.columns)
    sheet.append(columns)
    for cell in sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    sheet.row_dimensions[1].height = 24

    for row_number, values in enumerate(frame.itertuples(index=False, name=None), start=2):
        for column_number, value in enumerate(values, start=1):
            if pd.isna(value):
                value = None
            cell = sheet.cell(row=row_number, column=column_number, value=value)
            if isinstance(value, str):
                # Keep uploaded IDs and names as literal text, including strings beginning with '='.
                cell.data_type = "s"
            if columns[column_number - 1] in MONEY_COLUMNS and isinstance(value, (int, float)):
                cell.number_format = '#,##0;[Red](#,##0)'
            if isinstance(value, date):
                cell.number_format = "dd/mm/yyyy"
            if columns[column_number - 1] == "Kết quả" and value != "Khớp":
                cell.fill = ISSUE_FILL

    for index, column in enumerate(columns, start=1):
        sample_lengths = [len(str(value)) for value in frame[column].head(200) if pd.notna(value)]
        width = min(max([len(column), *sample_lengths], default=12) + 3, 48)
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions


def create_excel_report(result: ReconciliationResult) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    _write_frame(workbook, "Can_xu_ly", result.issues)
    _write_frame(workbook, "Tat_ca_don", result.summary)

    duplicate_columns = [
        "Dòng nguồn",
        "transaction_id",
        "order_id",
        "paid_at",
        "amount",
        "payment_status",
    ]
    duplicates = result.duplicates[duplicate_columns].rename(
        columns={
            "transaction_id": "Mã giao dịch",
            "order_id": "Mã đơn",
            "paid_at": "Ngày thanh toán",
            "amount": "Số tiền (VND)",
            "payment_status": "Trạng thái thanh toán",
        }
    )
    _write_frame(workbook, "Giao_dich_trung", duplicates)

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()
