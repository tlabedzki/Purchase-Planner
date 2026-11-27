"""
Purchase Planner: the 30-day purchase plan per supplier and the 2024 backtest against the shop's buyer by eye.

    python main.py            # backtest on seed 42, plan for January 2025, files in output/
    python main.py --check    # the "done" criteria: exit code 1 when one fails
    python main.py --tune     # choose the planner settings on the tuning shop (seed 7)

Run python scripts/get_data.py first (the shop's tables from Data-Generator).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd  # noqa: E402

from purchase_planner import backtest, data, export, plan, policy, report  # noqa: E402

OUTPUT = ROOT / "output"
FILL_RATE_GOAL = 0.95
def print_table(table: pd.DataFrame) -> None:
    view = table.assign(fill_rate=(table["fill_rate"] * 100).map("{:.1f}%".format),
                        average_stock_value=(table["average_stock_value"] / 1e6).map("{:.2f} M".format),
                        lost_margin=(table["lost_margin"] / 1e6).map("{:.2f} M".format),
                        lost_revenue=(table["lost_revenue"] / 1e6).map("{:.2f} M".format))
    print(view[["label", "fill_rate", "average_stock_value", "lost_margin", "lost_revenue", "lost_units",
                "order_lines"]].to_string(index=False))


def run(seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    setup = backtest.prepare(data.load(seed, truth=True))
    table = report.backtest_table(backtest.run_all(setup))
    month = plan.build_plan(data.load(seed))
    return table, month


def save(table: pd.DataFrame, month: pd.DataFrame) -> None:
    OUTPUT.mkdir(exist_ok=True)
    table.to_csv(OUTPUT / "backtest.csv", index=False)
    month.to_csv(OUTPUT / "plan.csv", index=False)
    plan.supplier_summary(month).to_csv(OUTPUT / "plan_by_supplier.csv", index=False)
    paths = export.write_all(month, OUTPUT / "orders")
    print(f"Saved output/backtest.csv, output/plan.csv and {len(paths)} supplier workbooks in output/orders/")


def check(seed: int) -> int:
    """The criteria of done; prints each one and returns the exit code."""
    table, month = run(seed)
    again, _ = run(seed)
    row = table.set_index("policy")
    planner, eye, history = row.loc["planner"], row.loc["by_eye"], row.loc["shop_history"]
    checks = [
        (f"planner fill rate >= {FILL_RATE_GOAL:.0%}", f"{planner['fill_rate']:.2%}",
         planner["fill_rate"] >= FILL_RATE_GOAL),
        ("planner average stock value < buyer by eye (rebuilt)",
         f"{planner['average_stock_value']:,.0f} < {eye['average_stock_value']:,.0f} PLN",
         planner["average_stock_value"] < eye["average_stock_value"]),
        ("planner average stock value < shop's buyer (data)",
         f"{planner['average_stock_value']:,.0f} < {history['average_stock_value']:,.0f} PLN",
         planner["average_stock_value"] < history["average_stock_value"]),
        ("planner lost margin < shop's buyer (data)", f"{planner['lost_margin']:,.0f} < "
         f"{history['lost_margin']:,.0f} PLN", planner["lost_margin"] < history["lost_margin"]),
        ("a second run gives the same numbers", "identical" if table.equals(again) else "different",
         table.equals(again)),
        ("a plan line for every supplier with an order day in 30 days",
         f"{month['supplier_id'].nunique()} suppliers, {len(month):,} lines", month["supplier_id"].nunique() > 0),
    ]
    for label, value, passed in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {label}: {value}")
    passed = sum(c[2] for c in checks)
    print(f"{passed} of {len(checks)} criteria passed")
    return 0 if passed == len(checks) else 1


def tune() -> None:
    setup = backtest.prepare(data.load(data.TUNING_SEED, truth=True))
    choice, table = backtest.tune(setup)
    print(table.assign(fill_rate=table["fill_rate"].round(4),
                       average_stock_value=table["average_stock_value"].round(0),
                       lost_margin=table["lost_margin"].round(0)).to_string(index=False))
    print(f"Chosen on seed {data.TUNING_SEED}: {json.dumps(choice)}; in use: price_of_service="
          f"{policy.PRICE_OF_SERVICE}, value_exponent={policy.VALUE_EXPONENT}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=data.REPORT_SEED, help="shop to report on (default 42)")
    parser.add_argument("--check", action="store_true", help="check the criteria of done")
    parser.add_argument("--tune", action="store_true", help="choose the planner settings on seed 7")
    args = parser.parse_args()
    if args.tune:
        tune()
        return 0
    if args.check:
        return check(args.seed)
    table, month = run(args.seed)
    print_table(table)
    print()
    print(plan.supplier_summary(month).head(10).to_string(index=False))
    save(table, month)
    return 0


if __name__ == "__main__":
    sys.exit(main())
