"""
What the shop's systems show: daily sales and stock of every product, the days a product was out of stock, products
with their supplier, pack and minimum order, and suppliers with their order days and the lead times seen so far.

Everything here comes from tables a real shop has (orders, stock movements, purchase orders, the product catalog).
The truth of Data-Generator (lost demand, true lead times) is not read.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class Catalog:
    """Products and suppliers as arrays, product by position."""

    product_id: np.ndarray
    name: np.ndarray
    category: np.ndarray
    supplier: np.ndarray  # position in supplier arrays
    pack: np.ndarray
    moq: np.ndarray
    unit_cost: np.ndarray  # net purchase price, PLN
    unit_price: np.ndarray  # current list price without VAT, PLN
    launch: pd.DatetimeIndex
    stop: pd.DatetimeIndex  # last day on sale (NaT while on sale)
    supplier_id: np.ndarray
    supplier_name: np.ndarray
    country: np.ndarray
    order_days: np.ndarray  # (suppliers, 7) bool: the supplier takes orders on this weekday
    promised: np.ndarray  # promised lead time, days

    @property
    def size(self) -> int:
        return len(self.product_id)


def build_catalog(tables: dict[str, pd.DataFrame]) -> Catalog:
    products = tables["product_data"].sort_values("product_id").reset_index(drop=True)
    supply = tables["product_supplier_data"].set_index("product_id").loc[products["product_id"]]
    suppliers = tables["supplier_data"].sort_values("supplier_id").reset_index(drop=True)
    position = pd.Series(np.arange(len(suppliers)), index=suppliers["supplier_id"])
    order_days = np.array([[day in text.split(",") for day in WEEKDAYS] for text in suppliers["order_weekdays"]])
    return Catalog(
        product_id=products["product_id"].to_numpy(),
        name=products["product_name"].to_numpy(),
        category=products["category"].to_numpy(),
        supplier=position.loc[supply["supplier_id"]].to_numpy(),
        pack=supply["pack_size"].to_numpy(),
        moq=supply["min_order_quantity"].to_numpy(),
        unit_cost=products["net_purchase_price"].to_numpy(dtype=float),
        unit_price=products["sales_price_net"].to_numpy(dtype=float),
        launch=pd.DatetimeIndex(products["launch_date"]),
        stop=pd.DatetimeIndex(products["discontinued_date"]),
        supplier_id=suppliers["supplier_id"].to_numpy(),
        supplier_name=suppliers["supplier_name"].to_numpy(),
        country=suppliers["country"].to_numpy(),
        order_days=order_days,
        promised=suppliers["promised_lead_time_days"].to_numpy(),
    )


@dataclass
class History:
    """Daily panels (days x products) from the first to the last day of the data."""

    dates: pd.DatetimeIndex
    sold: np.ndarray  # units sold (served order lines) by order day
    received: np.ndarray  # units received at the start of the day
    stock: np.ndarray  # units in stock at the end of the day
    active: np.ndarray  # the product is on sale that day

    @property
    def opening_stock(self) -> np.ndarray:
        """Units in stock at the start of the day, after the day's deliveries."""
        return np.vstack([self.received[:1], self.stock[:-1] + self.received[1:]])

    @property
    def observed(self) -> np.ndarray:
        """
        Days on which demand can be seen: the product was on sale and in stock when the day began. A day it sold out
        counts (its sales are close to its demand); a day it started empty does not (its demand was lost unseen).
        """
        return self.active & (self.opening_stock > 0)

    @property
    def out_of_stock(self) -> np.ndarray:
        """The product ran out (no stock at the end of the day): demand that day may have been lost."""
        return self.active & (self.stock == 0)

    def day(self, date) -> int:
        return int(self.dates.get_loc(pd.Timestamp(date)))


def build_history(tables: dict[str, pd.DataFrame], catalog: Catalog) -> History:
    lines = tables["order_data"]
    movements = tables["stock_movement_data"]
    start = min(lines["order_date"].min(), movements["movement_date"].min())
    end = max(lines["order_date"].max(), movements["movement_date"].max())
    dates = pd.date_range(start, end, freq="D")
    position = pd.Series(np.arange(catalog.size), index=catalog.product_id)
    days, count = len(dates), catalog.size

    sold = np.zeros((days, count), dtype=np.int64)
    day = (lines["order_date"] - dates[0]).dt.days.to_numpy()
    np.add.at(sold, (day, position.loc[lines["product_id"]].to_numpy()), lines["quantity"].to_numpy())

    moves = movements.sort_values("stock_movement_id")
    move_day = (moves["movement_date"] - dates[0]).dt.days.to_numpy()
    move_product = position.loc[moves["product_id"]].to_numpy()
    received = np.zeros((days, count), dtype=np.int64)
    receipt = moves["movement_type"].isin(["receipt", "opening"]).to_numpy()
    np.add.at(received, (move_day[receipt], move_product[receipt]), moves["quantity"].to_numpy()[receipt])
    stock = np.full((days, count), np.nan)
    stock[move_day, move_product] = moves["stock_after"].to_numpy()  # the last movement of a day wins
    stock = pd.DataFrame(stock).ffill().fillna(0).to_numpy(dtype=np.int64)

    day_index = np.arange(days)[:, None]
    launch = ((catalog.launch - dates[0]).days).to_numpy()
    stop = ((catalog.stop - dates[0]).days).to_numpy(dtype=float)
    stop = np.where(np.isnan(stop), days + 10_000, stop)
    active = (day_index >= launch[None, :]) & (day_index <= stop[None, :])
    return History(dates=dates, sold=sold, received=received, stock=stock, active=active)


def lead_times(purchase_orders: pd.DataFrame, catalog: Catalog, before) -> pd.DataFrame:
    """
    Lead times seen per supplier on regular orders received before a day: mean, standard deviation and count.
    A supplier with fewer than 5 received orders gets its promised lead time and a spread of a quarter of it.
    """
    orders = purchase_orders[~purchase_orders["is_express"] & (purchase_orders["received_date"] < pd.Timestamp(before))]
    orders = orders.drop_duplicates("purchase_order_id")
    days = (orders["received_date"] - orders["order_date"]).dt.days
    stats = days.groupby(orders["supplier_id"]).agg(["mean", "std", "size"]).reindex(catalog.supplier_id)
    few = stats["size"].fillna(0) < 5
    promised = pd.Series(catalog.promised, index=catalog.supplier_id, dtype=float)
    stats.loc[few, "mean"] = promised[few]
    stats.loc[few, "std"] = promised[few] / 4
    return stats.fillna({"std": 0.0, "size": 0}).rename(columns={"size": "orders"})
