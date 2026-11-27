"""
Backtest: replay a year of the shop's true demand against an ordering policy.

The year starts from the shop's real state on its first day (stock and the purchase orders already on the way, from
Data-Generator). Every day deliveries arrive, the day's order lines are served first come first served while the stock
lasts (a line that does not fit is lost, as in Data-Generator), and on each supplier's order days the policy orders.
A delivery comes after a lead time drawn from the supplier's true lead time (the "world" of the backtest; the policy
only knows the lead times seen in the purchase order history). True demand is every order line of the year plus the
lines Data-Generator lost to an empty shelf (lost_demand_data), so the backtest is the only place that reads the truth.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from purchase_planner import forecast
from purchase_planner.forecast import TSB
from purchase_planner.history import Catalog, History, build_catalog, build_history, lead_times
from purchase_planner.policy import (
    PRICE_OF_SERVICE,
    VALUE_EXPONENT,
    ByEye,
    Context,
    Oracle,
    Planner,
    PlannerABC,
    abc_classes,
)

VAT = 1.23
LEAD_TIME_SEED = 2024


@dataclass
class World:
    """True demand lines of the backtest year and what is fixed before it starts."""

    start: int  # first day of the year, position in the history calendar
    days: int
    line_day: np.ndarray  # day of the year (0 = start), sorted by day, product and time
    line_product: np.ndarray
    line_quantity: np.ndarray
    line_revenue: np.ndarray  # net revenue of the line, PLN
    line_margin: np.ndarray  # net revenue minus purchase cost, PLN
    day_start: np.ndarray
    opening: np.ndarray  # stock at the end of the day before the year
    arrivals: dict  # day of the year -> list of (product, quantity): orders already on the way and first deliveries
    first_quantity: np.ndarray  # first delivery of products launched in the year
    true_lead_mean: np.ndarray
    true_lead_cv: np.ndarray

    def demand(self) -> np.ndarray:
        """True demand per day of the year and product."""
        out = np.zeros((self.days, len(self.opening)), dtype=np.int64)
        np.add.at(out, (self.line_day, self.line_product), self.line_quantity)
        return out


def build_world(tables: dict[str, pd.DataFrame], catalog: Catalog, history: History, year: int) -> World:
    start = history.day(f"{year}-01-01")
    end = history.day(f"{year}-12-31")
    days = end - start + 1
    first = history.dates[start]
    position = pd.Series(np.arange(catalog.size), index=catalog.product_id)
    cost = pd.Series(catalog.unit_cost, index=catalog.product_id)

    columns = ["order_date", "order_datetime", "product_id", "quantity", "unit_price_gross", "discount_rate"]
    lines = pd.concat([tables["order_data"][columns], tables["lost_demand_data"][columns]], ignore_index=True)
    lines = lines[lines["order_date"].dt.year == year]
    day = (lines["order_date"] - first).dt.days.to_numpy()
    product = position.loc[lines["product_id"]].to_numpy()
    order = np.lexsort((lines["order_datetime"].to_numpy(), product, day))
    revenue = (lines["quantity"] * lines["unit_price_gross"] * (1 - lines["discount_rate"]) / VAT).to_numpy()
    margin = revenue - (lines["quantity"] * lines["product_id"].map(cost)).to_numpy()

    orders = tables["purchase_order_data"]
    launch = orders["product_id"].map(pd.Series(catalog.launch, index=catalog.product_id))
    first_line = ~orders.sort_values("purchase_order_line_id").duplicated("product_id")
    first_line = first_line.reindex(orders.index)
    launched = first_line & (launch >= first) & (launch.dt.year == year)
    open_orders = (orders["order_date"] < first) & ~(orders["received_date"] < first)
    fixed = orders[(launched | open_orders) & (orders["received_date"] >= first)
                   & (orders["received_date"] <= history.dates[end])]
    arrivals: dict = {}
    for row in fixed.itertuples():
        arrivals.setdefault((row.received_date - first).days, []).append(
            (int(position[row.product_id]), int(row.ordered_quantity)))
    first_quantity = np.zeros(catalog.size)
    first_launch = orders[launched]
    first_quantity[position.loc[first_launch["product_id"]].to_numpy()] = first_launch["ordered_quantity"].to_numpy()

    suppliers = tables["supplier_data"].set_index("supplier_id").loc[catalog.supplier_id]
    line_day = day[order]
    return World(start=start, days=days, line_day=line_day, line_product=product[order],
                 line_quantity=lines["quantity"].to_numpy()[order], line_revenue=revenue[order],
                 line_margin=margin[order], day_start=np.searchsorted(line_day, np.arange(days + 1)),
                 opening=history.stock[start - 1].copy(), arrivals=arrivals, first_quantity=first_quantity,
                 true_lead_mean=suppliers["true_lead_time_mean_days"].to_numpy(),
                 true_lead_cv=suppliers["true_lead_time_cv"].to_numpy())


@dataclass
class Result:
    name: str
    served_units: int
    lost_units: int
    lost_revenue: float
    lost_margin: float
    stock_value: np.ndarray  # end-of-day stock at purchase cost, per day
    stock: np.ndarray  # end-of-day units, days x products
    lost_by_day: np.ndarray  # units lost per day
    demand_by_day: np.ndarray
    order_lines: int
    lost_by_product: np.ndarray | None = None

    @property
    def fill_rate(self) -> float:
        return self.served_units / max(self.served_units + self.lost_units, 1)

    @property
    def average_stock_value(self) -> float:
        return float(self.stock_value.mean())

    def summary(self) -> dict:
        return {"policy": self.name, "fill_rate": round(self.fill_rate, 4),
                "average_stock_value": round(self.average_stock_value, 2),
                "end_stock_value": round(float(self.stock_value[-1]), 2),
                "lost_units": self.lost_units, "lost_revenue": round(self.lost_revenue, 2),
                "lost_margin": round(self.lost_margin, 2), "order_lines": self.order_lines}


def draw_lead(world: World, suppliers: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    sigma = np.sqrt(np.log1p(world.true_lead_cv[suppliers] ** 2))
    mu = np.log(world.true_lead_mean[suppliers]) - sigma ** 2 / 2
    return np.maximum(1, np.round(np.exp(mu + sigma * rng.standard_normal(len(suppliers))))).astype(int)


def simulate(world: World, context: Context, policy, catalog: Catalog) -> Result:
    count = catalog.size
    rng = np.random.default_rng(LEAD_TIME_SEED)
    on_hand = world.opening.astype(np.int64).copy()
    on_order = np.zeros(count, dtype=np.int64)
    arrivals = {day: list(items) for day, items in world.arrivals.items()}
    for items in arrivals.values():
        for p, q in items:
            on_order[p] += q
    stock = np.zeros((world.days, count), dtype=np.int64)
    lost_by_day = np.zeros(world.days, dtype=np.int64)
    demand_by_day = np.zeros(world.days, dtype=np.int64)
    served_units = lost_units = order_lines = 0
    lost_by_product = np.zeros(count, dtype=np.int64)
    lost_revenue = lost_margin = 0.0
    launch = context.launch_day - world.start

    for d in range(world.days):
        t = world.start + d
        for p, q in arrivals.pop(d, []):
            on_hand[p] += q
            on_order[p] -= q
        opening = on_hand > 0
        lo, hi = world.day_start[d], world.day_start[d + 1]
        sold = np.zeros(count, dtype=np.int64)
        if hi > lo:
            product, quantity = world.line_product[lo:hi], world.line_quantity[lo:hi]
            np.add.at(sold, product, quantity)
            short = np.flatnonzero(sold > on_hand)
            lost = np.zeros(hi - lo, dtype=bool)
            for p in short:
                sold[p], left = 0, on_hand[p]
                for k in np.flatnonzero(product == p):
                    if quantity[k] <= left:
                        left -= quantity[k]
                        sold[p] += quantity[k]
                    else:
                        lost[k] = True
            on_hand -= sold
            lost_units += int(quantity[lost].sum())
            lost_by_day[d] = int(quantity[lost].sum())
            np.add.at(lost_by_product, product[lost], quantity[lost])
            demand_by_day[d] = int(quantity.sum())
            lost_revenue += float(world.line_revenue[lo:hi][lost].sum())
            lost_margin += float(world.line_margin[lo:hi][lost].sum())
            served_units += int(sold.sum())
        stock[d] = on_hand
        active = (context.launch_day <= t) & (t <= context.stop_day)
        policy.observe(t, sold, active & opening, launch == d, world.first_quantity)

        ordering = context.ordering(t)
        if len(ordering):
            quantity = policy.order(t, ordering, on_hand, on_order)
            products = np.flatnonzero(quantity)
            if len(products):
                lead = dict(zip(ordering, draw_lead(world, ordering, rng), strict=True))
                for p in products:
                    arrive = d + int(lead[catalog.supplier[p]])
                    if (context.dates[0] + pd.Timedelta(days=t + arrive - d)).weekday() == 6:
                        arrive += 1  # no deliveries on Sunday
                    arrivals.setdefault(arrive, []).append((p, int(quantity[p])))
                    on_order[p] += quantity[p]
                order_lines += len(products)

    value = stock @ catalog.unit_cost
    return Result(policy.name, served_units, lost_units, lost_revenue, lost_margin, value, stock, lost_by_day,
                  demand_by_day, order_lines, lost_by_product)


def history_result(tables: dict[str, pd.DataFrame], catalog: Catalog, history: History, world: World) -> Result:
    """What the shop's own buyer achieved in the year, read from Data-Generator's tables."""
    first = history.dates[world.start]
    lines = tables["order_data"]
    lost = tables["lost_demand_data"]
    year_lines = lines[lines["order_date"].dt.year == first.year]
    year_lost = lost[lost["order_date"].dt.year == first.year]
    cost = pd.Series(catalog.unit_cost, index=catalog.product_id)
    revenue = (year_lost["quantity"] * year_lost["unit_price_gross"] * (1 - year_lost["discount_rate"]) / VAT)
    margin = revenue - year_lost["quantity"] * year_lost["product_id"].map(cost)
    stock = history.stock[world.start:world.start + world.days]
    orders = tables["purchase_order_data"]
    placed = orders[(orders["order_date"].dt.year == first.year) & ~orders["is_express"]]
    lost_by_day = np.bincount((year_lost["order_date"] - first).dt.days, weights=year_lost["quantity"],
                              minlength=world.days).astype(np.int64)
    return Result("shop_history", int(year_lines["quantity"].sum()), int(year_lost["quantity"].sum()),
                  float(revenue.sum()), float(margin.sum()), stock @ catalog.unit_cost, stock, lost_by_day,
                  world.demand().sum(axis=1), len(placed))


@dataclass
class Setup:
    tables: dict
    catalog: Catalog
    history: History
    world: World
    context: Context
    classes: np.ndarray
    observed: np.ndarray


def prepare(tables: dict[str, pd.DataFrame], year: int = 2024) -> Setup:
    """Everything the policies need, from the history before the year."""
    catalog = build_catalog(tables)
    history = build_history(tables, catalog)
    world = build_world(tables, catalog, history, year)
    start = world.start
    future = pd.date_range(history.dates[0], history.dates[-1] + pd.Timedelta(days=120), freq="D")
    observed = history.observed
    season = forecast.fit_season(history.sold[:start], observed[:start], catalog.category, history.dates[:start],
                                 future)
    leads = lead_times(tables["purchase_order_data"], catalog, history.dates[start])
    launch = ((catalog.launch - future[0]).days).to_numpy()
    stop = ((catalog.stop - future[0]).days).to_numpy(dtype=float)
    context = Context(catalog=catalog, dates=future, season=season.for_products(catalog.category),
                      lead_mean=leads["mean"].to_numpy(), lead_std=leads["std"].to_numpy(),
                      stop_day=np.where(np.isnan(stop), len(future) + 10_000, stop).astype(int),
                      launch_day=np.clip(launch, 0, None))
    revenue = (history.sold[start - 365:start] * catalog.unit_price).sum(axis=0)
    return Setup(tables, catalog, history, world, context, abc_classes(revenue), observed)


def trained_state(setup: Setup, **alphas) -> TSB:
    start = setup.world.start
    return forecast.run_tsb(TSB.start(setup.catalog.size, **alphas), setup.history.sold[:start],
                            setup.context.season[:start], setup.observed[:start])


POLICIES = ["shop_history", "by_eye", "planner_abc", "planner", "oracle"]
TUNING_GRID = {"value_exponent": [0.0, 0.5, 1.0], "price_of_service": [0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}
TUNING_FLOOR = 0.96  # one point above the 95% goal, so the choice holds on another shop


def run_all(setup: Setup, price_of_service: float = PRICE_OF_SERVICE,
            value_exponent: float = VALUE_EXPONENT) -> dict[str, Result]:
    """The shop's own year and the four policies on the same demand, in the order of POLICIES."""
    start = setup.world.start
    by_eye = ByEye(setup.context, np.random.default_rng(LEAD_TIME_SEED + 1))
    by_eye.seed_history(setup.history.sold[:start])
    policies = [by_eye, PlannerABC(setup.context, trained_state(setup), setup.classes),
                Planner(setup.context, trained_state(setup), price_of_service, value_exponent),
                Oracle(setup.context, trained_state(setup), _future_demand(setup), price_of_service, value_exponent)]
    results = {"shop_history": history_result(setup.tables, setup.catalog, setup.history, setup.world)}
    for policy in policies:
        results[policy.name] = simulate(setup.world, setup.context, policy, setup.catalog)
    return results


def tune(setup: Setup, grid: dict = TUNING_GRID, floor: float = TUNING_FLOOR) -> tuple[dict, pd.DataFrame]:
    """
    Planner settings on the tuning shop: the lowest average stock value among the settings whose fill rate is at
    least `floor` and whose lost margin is at most the buyer by eye's. Returns the choice and the whole grid.
    """
    start = setup.world.start
    by_eye = ByEye(setup.context, np.random.default_rng(LEAD_TIME_SEED + 1))
    by_eye.seed_history(setup.history.sold[:start])
    baseline = simulate(setup.world, setup.context, by_eye, setup.catalog)
    rows = []
    for exponent in grid["value_exponent"]:
        for price in grid["price_of_service"]:
            result = simulate(setup.world, setup.context,
                              Planner(setup.context, trained_state(setup), price, exponent), setup.catalog)
            rows.append({"value_exponent": exponent, "price_of_service": price, "fill_rate": result.fill_rate,
                         "average_stock_value": result.average_stock_value, "lost_margin": result.lost_margin})
    table = pd.DataFrame(rows)
    table["allowed"] = (table["fill_rate"] >= floor) & (table["lost_margin"] <= baseline.lost_margin)
    best = table[table["allowed"]].sort_values("average_stock_value").iloc[0]
    choice = {"price_of_service": float(best["price_of_service"]), "value_exponent": float(best["value_exponent"])}
    return choice, table


def _future_demand(setup: Setup) -> np.ndarray:
    """True demand on the global calendar (zero outside the backtest year)."""
    demand = np.zeros((len(setup.context.dates), setup.catalog.size))
    start = setup.world.start
    demand[start:start + setup.world.days] = setup.world.demand()
    return demand
