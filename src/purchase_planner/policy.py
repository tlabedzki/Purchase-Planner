"""
Ordering policies, all with the same interface, so the backtest runs them on the same days and the same demand.

- Planner: a periodic review order-up-to policy, (R, S). On each order day of a supplier the planner orders up to
  S = the quantile of demand over the protection period (lead time + days to the next order day). Demand over the
  period is negative binomial with the TSB x season mean and variance phi x mean, plus the lead time spread. The
  service level comes from sharing one stock budget among all products (a Lagrange allocation): a product may run
  out in a cycle with the chance

      price_of_service x (unit cost / unit margin) x (unit cost / median unit cost) ** value_exponent x cycle / 365

  so a unit of stock goes where it keeps the most margin, and expensive units are held a little more sparingly
  (value_exponent between 0, margin per zloty, and 1, units per zloty). The order is rounded up to whole packs and
  is at least the minimum order.
- PlannerABC: the same forecast with a fixed cycle service level per ABC class (A 97%, B 94%, C 85%), the usual
  textbook rule; kept to show what the allocation adds.
- ByEye: the buyer of Data-Generator, rebuilt: the average daily sales of the last 28 days times the promised lead
  time, the days to the next order day and 10 days of cover.
- Oracle: the planner with a perfect forecast (it knows the true demand of the period); a ceiling, not a policy.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats

from purchase_planner.forecast import TSB
from purchase_planner.history import Catalog

# Chosen on the tuning shop (seed 7, main.py --tune): the lowest average stock with a fill rate of at least 96% and
# no more lost margin than the buyer by eye.
PRICE_OF_SERVICE = 3.0
VALUE_EXPONENT = 0.5
MAX_SERVICE = 0.995
MIN_MARGIN_SHARE = 0.05  # a product sold at or below cost still counts 5% of its cost as margin
SERVICE_LEVEL = {"A": 0.97, "B": 0.94, "C": 0.85}  # PlannerABC only


def abc_classes(value: np.ndarray) -> np.ndarray:
    """A, B or C by share of value: A up to 80% of the cumulative value, B up to 95%, C the rest."""
    order = np.argsort(-value, kind="stable")
    share = np.cumsum(value[order]) / max(value.sum(), 1e-9)
    before = np.r_[0.0, share[:-1]]  # share of the products ranked above
    labels = np.where(before < 0.80, "A", np.where(before < 0.95, "B", "C"))
    classes = np.empty(len(value), dtype=object)
    classes[order] = labels
    classes[value <= 0] = "C"
    return classes


def round_up_to_pack(quantity: np.ndarray, pack: np.ndarray) -> np.ndarray:
    return (np.ceil(np.maximum(quantity, 0) / pack) * pack).astype(np.int64)


def days_to_next_order(order_days: np.ndarray, weekday: int) -> np.ndarray:
    """Days from today to the supplier's next order day (1-7), per supplier."""
    ahead = np.array([[order_days[s, (weekday + k) % 7] for k in range(1, 8)] for s in range(len(order_days))])
    return ahead.argmax(axis=1) + 1


def demand_quantile(mean: np.ndarray, variance: np.ndarray, level: np.ndarray) -> np.ndarray:
    """Quantile of a negative binomial (Poisson when variance <= mean) with the given mean and variance."""
    mean = np.maximum(mean, 0.0)
    out = np.zeros(len(mean))
    positive = mean > 1e-9
    over = positive & (variance > mean * 1.0001)
    poisson = positive & ~over
    n = mean[over] ** 2 / (variance[over] - mean[over])
    out[over] = stats.nbinom.ppf(level[over], n, n / (n + mean[over]))
    out[poisson] = stats.poisson.ppf(level[poisson], mean[poisson])
    return out


@dataclass
class Context:
    """What every policy may know: the catalog, calendar positions and seasonal index, lead times seen so far."""

    catalog: Catalog
    dates: pd.DatetimeIndex  # global calendar (history and future)
    season: np.ndarray  # days x products, on `dates`
    lead_mean: np.ndarray  # per supplier, days (from the purchase order history)
    lead_std: np.ndarray
    stop_day: np.ndarray  # last day on sale, position in `dates` (large when on sale)
    launch_day: np.ndarray

    def __post_init__(self):
        self.cumulative = np.vstack([np.zeros(self.season.shape[1]), np.cumsum(self.season, axis=0)])

    def ordering(self, t: int) -> np.ndarray:
        """Suppliers that take orders on day t."""
        return np.flatnonzero(self.catalog.order_days[:, self.dates[t].weekday()])

    def window(self, t: int, ordering: np.ndarray):
        """
        Products of the ordering suppliers that can still be ordered, their protection period in days (lead time +
        days to the next order day, cut at the last day on sale) and the lead time.
        """
        catalog = self.catalog
        supplier = catalog.supplier
        review = np.zeros(len(catalog.supplier_id), dtype=int)
        review[ordering] = days_to_next_order(catalog.order_days, self.dates[t].weekday())[ordering]
        lead = np.ceil(self.lead_mean).astype(int)
        products = np.isin(supplier, ordering) & (self.launch_day <= t) & (t + lead[supplier] < self.stop_day)
        period = np.maximum(np.minimum(review[supplier] + lead[supplier], self.stop_day - t), 1)
        return products, period, lead[supplier]


@dataclass
class Targets:
    """The order-up-to level of every product and what it is made of."""

    products: np.ndarray  # can be ordered today
    target: np.ndarray  # order-up-to level, units
    mean: np.ndarray  # expected demand over the protection period
    variance: np.ndarray
    period: np.ndarray  # protection period, days
    lead: np.ndarray  # lead time used, days
    level: np.ndarray  # cycle service level


class Planner:
    name = "planner"

    def __init__(self, context: Context, state: TSB, price_of_service: float = PRICE_OF_SERVICE,
                 value_exponent: float = VALUE_EXPONENT):
        self.context, self.state = context, state
        self.price_of_service, self.value_exponent = price_of_service, value_exponent
        catalog = context.catalog
        margin = np.maximum(catalog.unit_price - catalog.unit_cost, MIN_MARGIN_SHARE * catalog.unit_cost)
        relative_cost = catalog.unit_cost / np.median(catalog.unit_cost)
        self.weight = (catalog.unit_cost / margin) * relative_cost ** value_exponent

    def observe(self, t: int, sold: np.ndarray, observed: np.ndarray, launched: np.ndarray, first_quantity):
        if launched.any():
            self.state.prime(first_quantity / 30.0, launched)
        self.state.update(sold, self.context.season[t], observed)

    def period_mean(self, t: int, period: np.ndarray) -> np.ndarray:
        """Expected demand over days t+1 .. t+period, per product."""
        columns = np.arange(len(period))
        end = np.minimum(t + 1 + period, len(self.context.cumulative) - 1)
        return self.state.base * (self.context.cumulative[end, columns] - self.context.cumulative[t + 1, columns])

    def service_level(self, period: np.ndarray, lead: np.ndarray) -> np.ndarray:
        """Cycle service level of every product: 1 - the chance of running out before the next delivery."""
        cycle_days = np.maximum(period - lead, 1)
        risk = self.price_of_service * self.weight * cycle_days / 365
        return np.clip(1 - risk, 0.0, MAX_SERVICE)

    def targets(self, t: int, ordering: np.ndarray) -> Targets:
        context, catalog = self.context, self.context.catalog
        products, period, lead = context.window(t, ordering)
        mean = self.period_mean(t, period)
        variance = self.state.phi * mean + (mean / period) ** 2 * context.lead_std[catalog.supplier] ** 2
        level = self.service_level(period, lead)
        target = np.where(products, demand_quantile(mean, variance, level), 0.0)
        return Targets(products, target, mean, variance, period, lead, level)

    def order(self, t: int, ordering: np.ndarray, on_hand: np.ndarray, on_order: np.ndarray) -> np.ndarray:
        goal = self.targets(t, ordering)
        position = on_hand + on_order
        catalog = self.context.catalog
        need = np.where(goal.products & (position < goal.target), goal.target - position, 0.0)
        return np.where(need > 0, np.maximum(round_up_to_pack(need, catalog.pack), catalog.moq), 0)


class PlannerABC(Planner):
    """The planner's forecast with a fixed cycle service level per ABC class (by revenue)."""

    name = "planner_abc"

    def __init__(self, context: Context, state: TSB, classes: np.ndarray, service_level: dict | None = None):
        super().__init__(context, state)
        levels = SERVICE_LEVEL if service_level is None else service_level
        self.level = np.array([levels[c] for c in classes])

    def service_level(self, period, lead):
        return self.level


class Oracle(Planner):
    """The planner with the true demand of the period instead of the forecast: only the lead time is uncertain."""

    name = "oracle"

    def __init__(self, context: Context, state: TSB, demand: np.ndarray, price_of_service: float = PRICE_OF_SERVICE,
                 value_exponent: float = VALUE_EXPONENT):
        super().__init__(context, state, price_of_service, value_exponent)
        self.cumulative_demand = np.vstack([np.zeros(demand.shape[1]), np.cumsum(demand, axis=0)])

    def targets(self, t: int, ordering: np.ndarray) -> Targets:
        context, catalog = self.context, self.context.catalog
        products, period, lead = context.window(t, ordering)
        columns = np.arange(len(period))
        end = np.minimum(t + 1 + period, len(self.cumulative_demand) - 1)
        mean = self.cumulative_demand[end, columns] - self.cumulative_demand[t + 1, columns]
        spread = mean / period * context.lead_std[catalog.supplier]
        level = self.service_level(period, lead)
        safety = np.where(spread > 0, stats.norm.ppf(np.clip(level, 0.5, MAX_SERVICE)) * spread, 0.0)
        target = np.where(products, np.ceil(mean + safety), 0.0)
        return Targets(products, target, mean, spread ** 2, period, lead, level)


@dataclass
class ByEye:
    """The buyer of Data-Generator 1.8.0 (settings/inventory_settings.py), rebuilt on the backtest's sales."""

    context: Context
    rng: np.random.Generator
    history_days: int = 28
    cover_days: int = 10
    sigma: float = 0.20
    notice_rate: float = 0.5
    name: str = "by_eye"
    window_sales: np.ndarray = field(init=False)

    def __post_init__(self):
        self.window_sales = np.zeros((self.history_days, self.context.catalog.size))

    def seed_history(self, sold: np.ndarray) -> None:
        """The last history_days of sales before the backtest, each day in the row observe() gives it."""
        start = len(sold)
        for day in range(start - self.history_days, start):
            self.window_sales[day % self.history_days] = sold[day]

    def observe(self, t, sold, observed, launched, first_quantity):
        self.window_sales[t % self.history_days] = sold

    def order(self, t, ordering, on_hand, on_order):
        context, catalog = self.context, self.context.catalog
        supplier = catalog.supplier
        review = np.zeros(len(catalog.supplier_id))
        review[ordering] = 7 / catalog.order_days[ordering].sum(axis=1)
        promised = catalog.promised[supplier]
        products = (np.isin(supplier, ordering) & (context.launch_day <= t)
                    & (t + promised + review[supplier] < context.stop_day))
        seen = np.clip(np.minimum(self.history_days, t - context.launch_day + 1), 1, None)
        average = self.window_sales.sum(axis=0) / seen
        noise = np.exp(self.rng.normal(0, self.sigma, size=catalog.size))
        target = average * (promised + review[supplier] + self.cover_days) * noise
        position = on_hand + on_order
        need = np.where(products & (average > 0) & (position < target), target - position, 0)
        empty = products & (average == 0) & (position == 0) & (self.rng.random(catalog.size) < self.notice_rate)
        quantity = np.where(need > 0, np.maximum(round_up_to_pack(need, catalog.pack), catalog.moq), 0)
        return np.where(empty, catalog.moq, quantity)
