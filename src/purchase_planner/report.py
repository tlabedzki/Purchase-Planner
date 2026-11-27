"""
Numbers, tables and chart titles shared by main.py, the app and the README, so they never disagree.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from purchase_planner import backtest

LABELS = {"shop_history": "Shop's buyer (data)", "by_eye": "Buyer by eye (rebuilt)",
          "planner_abc": "Planner, fixed ABC service", "planner": "Planner", "oracle": "Perfect forecast"}
NOTES = {"shop_history": "what Data-Generator's buyer did in 2024",
         "by_eye": "the same rule replayed in the backtest",
         "planner_abc": "this forecast, service 97/94/85% by ABC class",
         "planner": "this forecast, service shared by margin per zloty",
         "oracle": "knows the true demand: the ceiling"}


def compact(value: float, unit: str = "") -> str:
    """1.23 M, 456 k, 789 (English notation, as in the README)."""
    sign = "−" if value < 0 else ""
    value = abs(value)
    if value >= 1e6:
        text = f"{value / 1e6:.2f} M"
    elif value >= 1e4:
        text = f"{value / 1e3:.0f} k"
    else:
        text = f"{value:,.0f}"
    return f"{sign}{text}{(' ' + unit) if unit else ''}"


def percent(value: float, decimals: int = 1, sign: bool = False) -> str:
    text = f"{value * 100:+.{decimals}f}%" if sign else f"{value * 100:.{decimals}f}%"
    return text.replace("-", "−")


def backtest_table(results: dict) -> pd.DataFrame:
    """One row per policy, in the order of backtest.POLICIES."""
    table = pd.DataFrame([results[name].summary() for name in backtest.POLICIES])
    table.insert(1, "label", table["policy"].map(LABELS))
    return table


def kpis(table: pd.DataFrame) -> dict:
    """The planner against the shop's buyer (the data): the headline numbers."""
    row = table.set_index("policy")
    planner, buyer = row.loc["planner"], row.loc["shop_history"]
    return {
        "fill_planner": planner["fill_rate"], "fill_buyer": buyer["fill_rate"],
        "fill_gain": planner["fill_rate"] - buyer["fill_rate"],
        "stock_planner": planner["average_stock_value"], "stock_buyer": buyer["average_stock_value"],
        "cash_freed": buyer["average_stock_value"] - planner["average_stock_value"],
        "stock_change": planner["average_stock_value"] / buyer["average_stock_value"] - 1,
        "margin_planner": planner["lost_margin"], "margin_buyer": buyer["lost_margin"],
        "margin_saved": buyer["lost_margin"] - planner["lost_margin"],
        "margin_change": planner["lost_margin"] / buyer["lost_margin"] - 1,
        "revenue_planner": planner["lost_revenue"], "revenue_buyer": buyer["lost_revenue"],
    }


def monthly_lost_share(result: backtest.Result, dates: pd.DatetimeIndex) -> pd.Series:
    """Share of each month's demand lost to an empty shelf."""
    month = dates.month
    lost = pd.Series(result.lost_by_day).groupby(np.asarray(month)).sum()
    demand = pd.Series(result.demand_by_day).groupby(np.asarray(month)).sum()
    return lost / demand.replace(0, np.nan)


def stock_title(table: pd.DataFrame) -> tuple[str, list[str]]:
    k = kpis(table)
    return (f"The planner keeps {compact(k['cash_freed'])} PLN less in stock, on average, through 2024",
            ["Stock at purchase cost at the end of each day. Same demand, same start and the same suppliers for "
             "every line; the shop's buyer is Data-Generator's own year."])


def lost_title(results: dict, dates: pd.DatetimeIndex) -> tuple[str, list[str]]:
    buyer = monthly_lost_share(results["shop_history"], dates)
    planner = monthly_lost_share(results["planner"], dates)
    return (f"Black Friday empties the shelf by eye: {percent(buyer[11], 0)} of November demand lost, "
            f"{percent(planner[11], 0)} with the planner",
            ["Units asked for but not sold because the product was out of stock, as a share of each month's "
             "demand, 2024."])


def plan_lines(plan: pd.DataFrame, supplier_id: int) -> pd.DataFrame:
    return plan[plan["supplier_id"] == supplier_id].sort_values(["order_date", "order_value"],
                                                                 ascending=[True, False])


def supplier_options(plan: pd.DataFrame, catalog) -> list[dict]:
    """Every supplier, those with the largest plan first; the label says the country and the plan value."""
    value = plan.groupby("supplier_id")["order_value"].sum()
    rows = []
    for s, supplier_id in enumerate(catalog.supplier_id):
        rows.append((float(value.get(supplier_id, 0.0)), int(supplier_id),
                     f"{catalog.supplier_name[s]} ({catalog.country[s]}), {compact(value.get(supplier_id, 0.0))} PLN"))
    rows.sort(key=lambda row: (-row[0], row[1]))
    return [{"value": str(supplier_id), "label": label} for _, supplier_id, label in rows]
