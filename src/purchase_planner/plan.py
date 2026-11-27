"""
The purchase plan for the next 30 days: for every supplier, what to order on each of its order days, how much and
why. The plan starts the day after the data ends, from the stock on hand and the purchase orders still on the way.

The first order day of every supplier is firm: it uses the real stock. Later order days are projected: the stock
falls by the forecast and rises with the planned and open deliveries, so the buyer sees what is coming. The planner
reads only what the shop knows (sales, stock, purchase orders, the catalog), never the truth of Data-Generator.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from purchase_planner import forecast
from purchase_planner.forecast import TSB
from purchase_planner.history import Catalog, History, build_catalog, build_history, lead_times
from purchase_planner.policy import PRICE_OF_SERVICE, VALUE_EXPONENT, Context, Planner, round_up_to_pack

HORIZON_DAYS = 30
PLAN_COLUMNS = ["supplier_id", "supplier_name", "order_date", "status", "expected_delivery", "product_id",
                "product_name", "category", "quantity", "packs", "pack_size", "min_order_quantity", "unit_cost",
                "order_value", "on_hand", "on_order", "daily_forecast", "protection_days", "period_demand",
                "order_up_to", "service_level", "reason"]


def reason(row) -> str:
    """One sentence on why this quantity, from the numbers of the plan line."""
    daily = row["daily_forecast"]
    on_hand, on_order = int(row["on_hand"]), int(row["on_order"])
    position = on_hand + on_order
    cover = f"about {position / daily:.0f} days" if daily > 0 else "a long time"
    if position <= 0:
        stock = "Out of stock with nothing on the way"
    elif on_order > 0:
        stock = f"{on_hand} in stock and {on_order} on the way last {cover}"
    else:
        stock = f"{on_hand} in stock last {cover}"
    risk = 1 - row["service_level"]
    units = f"{row['quantity']} unit" + ("s" if row["quantity"] != 1 else "")
    minimum = row["quantity"] == row["min_order_quantity"] and row["order_up_to"] - position < row["quantity"]
    packs = f"{row['packs']} pack" + ("s" if row["packs"] != 1 else "") + f" of {row['pack_size']}"
    rounding = "the supplier's minimum order" if minimum else packs
    return (f"{stock}; the next {row['protection_days']} days, until the following delivery, need about "
            f"{row['period_demand']:.0f}, so the plan tops up to {row['order_up_to']:.0f} "
            f"({risk:.0%} risk of running out): {units}, {rounding}.")


@dataclass
class Planning:
    """What the plan is made from: the catalog, the history, the forecast state and the calendar after the data."""

    tables: dict
    catalog: Catalog
    history: History
    context: Context
    state: TSB

    @property
    def start(self) -> int:
        """First day of the plan, position in context.dates (the day after the data ends)."""
        return len(self.history.dates)

    def forecast(self, product: int, days: int) -> np.ndarray:
        """Expected units a day of one product (position) for `days` days from the start of the plan."""
        return self.state.base[product] * self.context.season[self.start:self.start + days, product]


def prepare(tables: dict[str, pd.DataFrame], days: int = HORIZON_DAYS) -> Planning:
    catalog = build_catalog(tables)
    history = build_history(tables, catalog)
    first = history.dates[-1] + pd.Timedelta(days=1)
    dates = pd.date_range(history.dates[0], first + pd.Timedelta(days=days + 120), freq="D")
    observed = history.observed
    season = forecast.fit_season(history.sold, observed, catalog.category, history.dates, dates)
    leads = lead_times(tables["purchase_order_data"], catalog, first)
    launch = ((catalog.launch - dates[0]).days).to_numpy()
    stop = ((catalog.stop - dates[0]).days).to_numpy(dtype=float)
    context = Context(catalog=catalog, dates=dates, season=season.for_products(catalog.category),
                      lead_mean=leads["mean"].to_numpy(), lead_std=leads["std"].to_numpy(),
                      stop_day=np.where(np.isnan(stop), len(dates) + 10_000, stop).astype(int),
                      launch_day=np.clip(launch, 0, None))
    state = forecast.run_tsb(TSB.start(catalog.size), history.sold, context.season[:len(history.dates)], observed)
    return Planning(tables, catalog, history, context, state)


def build_plan(source, days: int = HORIZON_DAYS, price_of_service: float = PRICE_OF_SERVICE,
               value_exponent: float = VALUE_EXPONENT) -> pd.DataFrame:
    """
    Plan lines of every supplier for `days` days from the day after the data ends (columns PLAN_COLUMNS).
    `source` is the shop's tables or a Planning from prepare().
    """
    planning = source if isinstance(source, Planning) else prepare(source, days)
    tables, catalog, history = planning.tables, planning.catalog, planning.history
    context, dates = planning.context, planning.context.dates
    state = TSB(planning.state.p.copy(), planning.state.z.copy(), planning.state.v.copy())
    planner = Planner(context, state, price_of_service, value_exponent)

    start = len(history.dates)
    position = pd.Series(np.arange(catalog.size), index=catalog.product_id)
    on_hand = history.stock[-1].astype(float)
    on_order = np.zeros(catalog.size)
    arrivals: dict[int, list] = {}
    orders = tables["purchase_order_data"]
    lead_days = np.ceil(context.lead_mean).astype(int)
    for row in orders[orders["received_date"].isna()].itertuples():
        p = int(position[row.product_id])
        expected = (row.order_date - dates[0]).days + int(lead_days[catalog.supplier[p]])
        arrivals.setdefault(max(expected, start), []).append((p, float(row.ordered_quantity)))
        on_order[p] += row.ordered_quantity

    lines, firm_done = [], set()
    for t in range(start, start + days):
        for p, q in arrivals.pop(t, []):
            on_hand[p] += q
            on_order[p] -= q
        daily = state.base * context.season[t]
        ordering = context.ordering(t)
        if len(ordering):
            goal = planner.targets(t, ordering)
            whole = np.floor(on_hand + 1e-9)  # projected stock in whole units
            stock_position = whole + on_order
            need = np.where(goal.products & (stock_position < goal.target), goal.target - stock_position, 0.0)
            quantity = np.where(need > 0, np.maximum(round_up_to_pack(need, catalog.pack), catalog.moq), 0)
            for p in np.flatnonzero(quantity):
                s = catalog.supplier[p]
                arrive = t + int(lead_days[s])
                if dates[arrive].weekday() == 6:
                    arrive += 1  # no deliveries on Sunday
                lines.append({
                    "supplier_id": catalog.supplier_id[s], "supplier_name": catalog.supplier_name[s],
                    "order_date": dates[t], "status": "projected" if s in firm_done else "firm",
                    "expected_delivery": dates[arrive],
                    "product_id": catalog.product_id[p], "product_name": catalog.name[p],
                    "category": catalog.category[p], "quantity": int(quantity[p]),
                    "packs": int(quantity[p] // catalog.pack[p]), "pack_size": int(catalog.pack[p]),
                    "min_order_quantity": int(catalog.moq[p]), "unit_cost": float(catalog.unit_cost[p]),
                    "order_value": round(float(quantity[p] * catalog.unit_cost[p]), 2),
                    "on_hand": int(whole[p]), "on_order": int(on_order[p]),
                    "daily_forecast": round(float(goal.mean[p] / goal.period[p]), 3),
                    "protection_days": int(goal.period[p]),
                    "period_demand": round(float(goal.mean[p]), 1), "order_up_to": float(goal.target[p]),
                    "service_level": round(float(goal.level[p]), 3),
                })
                arrivals.setdefault(arrive, []).append((p, float(quantity[p])))
                on_order[p] += quantity[p]
            firm_done.update(int(s) for s in ordering)
        on_hand = np.maximum(on_hand - daily * (on_hand > 0), 0.0)  # projected sales

    plan = pd.DataFrame(lines, columns=[c for c in PLAN_COLUMNS if c != "reason"])
    plan["reason"] = [reason(row) for _, row in plan.iterrows()] if len(plan) else []
    return plan[PLAN_COLUMNS].sort_values(["supplier_id", "order_date", "product_id"], kind="stable").reset_index(
        drop=True)


def supplier_summary(plan: pd.DataFrame) -> pd.DataFrame:
    """One row per supplier: order days, lines, units and value of the plan, and the first (firm) order."""
    if plan.empty:
        return pd.DataFrame(columns=["supplier_id", "supplier_name", "order_days", "lines", "units", "value",
                                     "firm_date", "firm_value"])
    firm = plan[plan["status"] == "firm"].groupby("supplier_id").agg(firm_date=("order_date", "min"),
                                                                       firm_value=("order_value", "sum"))
    summary = plan.groupby(["supplier_id", "supplier_name"]).agg(
        order_days=("order_date", "nunique"), lines=("product_id", "size"), units=("quantity", "sum"),
        value=("order_value", "sum")).reset_index()
    return summary.merge(firm, on="supplier_id", how="left").sort_values("value", ascending=False).reset_index(
        drop=True)
