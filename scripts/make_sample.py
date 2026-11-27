"""
Cut a small sample of the shop for the tests (data/sample/, in git): three suppliers (one from Poland, Germany and
China, the smallest of each), their products and every table of 2023-2024. The stock at the end of 2022 comes in as
an opening movement on the first day, and only the columns the planner reads are kept. The sample is a cut of the
Data-Generator tables in data/raw/seed-42; nothing is generated.

    python scripts/make_sample.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from purchase_planner import data  # noqa: E402

FIRST = pd.Timestamp("2023-01-01")
LINE_COLUMNS = ["order_date", "order_datetime", "product_id", "quantity", "unit_price_gross", "discount_rate"]


def cut(tables: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    supply = tables["product_supplier_data"]
    suppliers = tables["supplier_data"]
    size = supply["supplier_id"].value_counts()
    chosen = [suppliers.loc[suppliers["country"] == country, "supplier_id"].map(size).idxmin()
              for country in ("PL", "DE", "CN")]
    chosen = suppliers.loc[chosen, "supplier_id"].tolist()
    products = supply.loc[supply["supplier_id"].isin(chosen), "product_id"]

    def mine(frame):
        return frame[frame["product_id"].isin(products)]

    moves = mine(tables["stock_movement_data"]).sort_values("stock_movement_id")
    before = moves[moves["movement_date"] < FIRST].groupby("product_id")["stock_after"].last()
    opening = pd.DataFrame({"product_id": before.index, "movement_date": FIRST, "movement_type": "opening",
                            "quantity": before.to_numpy(), "stock_after": before.to_numpy()})
    later = moves[moves["movement_date"] >= FIRST]
    moves = pd.concat([opening[opening["quantity"] > 0], later], ignore_index=True)
    moves["kind"] = moves["movement_type"].map({"opening": 0, "receipt": 1, "sale": 2})
    moves = moves.sort_values(["movement_date", "product_id", "kind"], kind="stable").drop(columns="kind")
    moves["stock_movement_id"] = range(1, len(moves) + 1)
    # Stock after each movement, again from the opening (receipts and sales of 2023-2024 only).
    moves["stock_after"] = moves.groupby("product_id")["quantity"].cumsum()

    orders = mine(tables["purchase_order_data"])
    orders = orders[(orders["received_date"] >= FIRST) | orders["received_date"].isna()]
    lines = mine(tables["order_data"])
    lost = mine(tables["lost_demand_data"])
    return {
        "product_data": mine(tables["product_data"]),
        "order_data": lines.loc[lines["order_date"] >= FIRST, LINE_COLUMNS],
        "supplier_data": suppliers[suppliers["supplier_id"].isin(chosen)],
        "product_supplier_data": mine(supply),
        "purchase_order_data": orders,
        "stock_movement_data": moves[tables["stock_movement_data"].columns],
        "lost_demand_data": lost.loc[lost["order_date"] >= FIRST, LINE_COLUMNS],
    }


def main() -> None:
    sample = cut(data.load(data.REPORT_SEED, truth=True))
    data.SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    for name, frame in sample.items():
        frame.to_parquet(data.SAMPLE_DIR / f"{name}.parquet", index=False)
    total = sum((data.SAMPLE_DIR / f"{name}.parquet").stat().st_size for name in sample)
    print(f"{len(sample['product_data'])} products of {len(sample['supplier_data'])} suppliers, "
          f"{len(sample['order_data']):,} order lines, {total / 1e6:.2f} MB in {data.SAMPLE_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
