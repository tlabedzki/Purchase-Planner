import io

import numpy as np
import pytest
from openpyxl import load_workbook

from purchase_planner import data, export, plan


@pytest.fixture(scope="module")
def month():
    return plan.build_plan(data.load_sample())  # the planner reads no truth


def test_plan_lines_follow_the_supplier_rules(month, sample):
    assert len(month) and list(month.columns) == plan.PLAN_COLUMNS
    supply = sample["product_supplier_data"].set_index("product_id")
    assert (month["quantity"] % month["product_id"].map(supply["pack_size"]) == 0).all()
    assert (month["quantity"] >= month["product_id"].map(supply["min_order_quantity"])).all()
    assert (month["supplier_id"] == month["product_id"].map(supply["supplier_id"])).all()
    days = (month["order_date"] - month["order_date"].min()).dt.days
    assert days.max() < plan.HORIZON_DAYS
    weekday = month["order_date"].dt.strftime("%a")
    allowed = month["supplier_id"].map(sample["supplier_data"].set_index("supplier_id")["order_weekdays"])
    assert all(day in days_ for day, days_ in zip(weekday, allowed, strict=True))


def test_first_order_day_of_each_supplier_is_firm(month):
    first = month.groupby("supplier_id")["order_date"].transform("min")
    assert ((month["order_date"] == first) == (month["status"] == "firm")).all()
    assert month["reason"].str.endswith(".").all()
    assert np.isclose(month["order_value"], month["quantity"] * month["unit_cost"], atol=0.01).all()


def test_workbook_per_supplier(month):
    supplier = int(month["supplier_id"].iloc[0])
    book = load_workbook(io.BytesIO(export.supplier_workbook(month, supplier)))
    sheet = book["Purchase plan"]
    lines = (month["supplier_id"] == supplier).sum()
    assert sheet.cell(row=4, column=1).value == "Order date"
    assert sheet.max_row == 4 + lines + 1
    assert sheet.cell(row=4 + lines + 1, column=1).value == "Total"
    assert str(sheet.cell(row=4 + lines + 1, column=10).value).startswith("=SUM(")


def test_an_order_only_when_the_stock_is_below_the_target(month):
    assert (month["on_hand"] + month["on_order"] < month["order_up_to"]).all()


def test_no_delivery_on_sunday_and_cover_from_the_period(month):
    assert (month["expected_delivery"].dt.weekday != 6).all()
    assert (month["daily_forecast"] * month["protection_days"] - month["period_demand"]).abs().max() < 0.1
