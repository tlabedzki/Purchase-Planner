"""
Purchase orders as Excel files: one workbook per supplier with every plan line of the next 30 days, the firm order
first, and a total. The buyer can send the firm sheet to the supplier as it is.
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

COLUMNS = [  # (plan column, header, width, number format)
    ("order_date", "Order date", 12, "yyyy-mm-dd"),
    ("expected_delivery", "Expected delivery", 12, "yyyy-mm-dd"),
    ("status", "Status", 10, None),
    ("product_id", "Product", 10, "0"),
    ("product_name", "Product name", 44, None),
    ("quantity", "Units", 8, "#,##0"),
    ("packs", "Packs", 7, "#,##0"),
    ("pack_size", "Pack", 6, "0"),
    ("unit_cost", "Unit cost (PLN, net)", 12, "#,##0.00"),
    ("order_value", "Value (PLN, net)", 13, "#,##0.00"),
    ("reason", "Why", 110, None),
]
HEADER_FILL = PatternFill("solid", fgColor="006E79")  # petrol of the portfolio palette


def file_name(supplier_id: int, supplier_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", supplier_name).strip("-").lower()
    return f"purchase-plan-{supplier_id:02d}-{slug}.xlsx"


def supplier_workbook(plan: pd.DataFrame, supplier_id: int) -> bytes:
    """The plan of one supplier as an .xlsx file (bytes)."""
    lines = plan[plan["supplier_id"] == supplier_id].sort_values(["order_date", "product_id"])
    name = lines["supplier_name"].iloc[0] if len(lines) else str(supplier_id)
    book = Workbook()
    sheet = book.active
    sheet.title = "Purchase plan"
    sheet["A1"] = f"Purchase plan: {name}"
    sheet["A1"].font = Font(bold=True, size=14)
    first = lines["order_date"].min() if len(lines) else None
    sheet["A2"] = (f"{len(lines)} lines over {lines['order_date'].nunique()} order days from {first:%Y-%m-%d}; "
                   "the first order day is firm, the later ones are projected." if len(lines) else "Nothing to order.")
    header_row = 4
    for column, (_, title, width, _) in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=header_row, column=column, value=title)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(column)].width = width
    for offset, (_, row) in enumerate(lines.iterrows(), start=1):
        for column, (key, _, _, number_format) in enumerate(COLUMNS, start=1):
            value = row[key]
            if isinstance(value, pd.Timestamp):
                value = value.to_pydatetime()
            elif hasattr(value, "item"):
                value = value.item()
            cell = sheet.cell(row=header_row + offset, column=column, value=value)
            if number_format:
                cell.number_format = number_format
    total_row = header_row + len(lines) + 1
    sheet.cell(row=total_row, column=1, value="Total").font = Font(bold=True)
    for key in ("quantity", "order_value"):
        column = [c[0] for c in COLUMNS].index(key) + 1
        letter = get_column_letter(column)
        cell = sheet.cell(row=total_row, column=column,
                          value=f"=SUM({letter}{header_row + 1}:{letter}{total_row - 1})" if len(lines) else 0)
        cell.font = Font(bold=True)
        cell.number_format = COLUMNS[column - 1][3]
    sheet.freeze_panes = sheet.cell(row=header_row + 1, column=1)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def write_all(plan: pd.DataFrame, folder: Path) -> list[Path]:
    """One workbook per supplier with a plan line, in `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for supplier_id, name in plan[["supplier_id", "supplier_name"]].drop_duplicates().itertuples(index=False):
        path = folder / file_name(int(supplier_id), name)
        path.write_bytes(supplier_workbook(plan, int(supplier_id)))
        paths.append(path)
    return paths
