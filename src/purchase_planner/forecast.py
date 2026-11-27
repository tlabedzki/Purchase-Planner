"""
Daily demand forecast of every product.

forecast(product, day) = base(product) x season(category, day)

- season: a Poisson regression per category on the days of the history, with the number of products in stock as the
  offset (so days a product was out of stock do not lower the season): month, weekday and the trading days of
  calendar.py. The index has a mean of 1 over the history.
- base: the deseasonalized daily demand from TSB (Teunter, Syntetos and Babai, 2011), a Croston-type method that
  smooths the chance of a sale and the size of a sale separately, so it works for products that sell every day and
  for those that sell twice a month. Days on which the product ran out are skipped: their sales are not demand.
- spread: the variance of demand over a period is phi x mean, where phi (at least 1, as for Poisson demand) comes
  from the smoothed squared errors of the one-day-ahead forecast.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from purchase_planner import calendar

RIDGE = 1.0  # small penalty: an event day is seen only once a year


def design(days: pd.DataFrame) -> np.ndarray:
    """Columns: intercept, months Feb-Dec, weekdays Tue-Sun and one column per trading day."""
    columns = [np.ones(len(days))]
    columns += [(days["month"] == m).to_numpy(float) for m in range(2, 13)]
    columns += [(days["weekday"] == w).to_numpy(float) for w in range(1, 7)]
    columns += [(days["event"] == name).to_numpy(float) for name in calendar.EVENTS]
    return np.column_stack(columns)


def poisson_fit(x: np.ndarray, y: np.ndarray, offset: np.ndarray, iterations: int = 25) -> np.ndarray:
    """Coefficients of a Poisson regression (log link) by iteratively reweighted least squares, with a ridge."""
    beta = np.zeros(x.shape[1])
    beta[0] = np.log(max(y.sum(), 1.0) / np.exp(offset).sum())
    penalty = RIDGE * np.eye(x.shape[1])
    penalty[0, 0] = 0.0
    for _ in range(iterations):
        eta = x @ beta + offset
        mu = np.exp(eta)
        z = eta - offset + (y - mu) / mu
        weighted = x * mu[:, None]
        new = np.linalg.solve(x.T @ weighted + penalty, weighted.T @ z)
        if np.max(np.abs(new - beta)) < 1e-8:
            return new
        beta = new
    return beta


@dataclass
class Season:
    """Seasonal index of every category on every day of `dates` (days x categories)."""

    dates: pd.DatetimeIndex
    categories: np.ndarray
    index: np.ndarray
    effects: dict = field(default_factory=dict)  # category -> {name: multiplier}

    def for_products(self, category: np.ndarray) -> np.ndarray:
        """Index per day and product (days x products)."""
        column = pd.Series(np.arange(len(self.categories)), index=self.categories).loc[category].to_numpy()
        return self.index[:, column]


def fit_season(sold: np.ndarray, available: np.ndarray, category: np.ndarray, history_dates: pd.DatetimeIndex,
               dates: pd.DatetimeIndex) -> Season:
    """
    Fit the seasonal index per category on the history and evaluate it on `dates`.

    Parameters:
    sold (days x products): units sold on the history days.
    available (days x products): the product was on sale and in stock all day.
    category (products,): category of every product.
    history_dates: days of `sold`.
    dates: days to evaluate the index on (history and future).
    """
    history_days, all_days = calendar.build(history_dates), calendar.build(dates)
    x_history, x_all = design(history_days), design(all_days)
    categories = np.array(sorted(set(category)))
    index = np.ones((len(dates), len(categories)))
    effects = {}
    names = ([f"month {m}" for m in range(2, 13)] + [f"weekday {w}" for w in range(1, 7)] + list(calendar.EVENTS))
    for k, name in enumerate(categories):
        members = category == name
        y = np.where(available[:, members], sold[:, members], 0).sum(axis=1).astype(float)
        n = available[:, members].sum(axis=1)
        keep = n > 0
        beta = poisson_fit(x_history[keep], y[keep], np.log(n[keep]))
        seasonal = beta.copy()
        seasonal[0] = 0.0
        level = np.exp(x_history @ seasonal).mean()
        index[:, k] = np.exp(x_all @ seasonal) / level
        effects[name] = dict(zip(names, np.exp(beta[1:]), strict=True))
    return Season(dates=pd.DatetimeIndex(dates), categories=categories, index=index, effects=effects)


@dataclass
class TSB:
    """
    TSB state of every product on the deseasonalized scale: chance of a sale (p), size of a sale (z) and the smoothed
    squared error of the one-day-ahead forecast (v).
    """

    p: np.ndarray
    z: np.ndarray
    v: np.ndarray
    alpha_p: float = 0.05
    alpha_z: float = 0.10
    alpha_v: float = 0.05

    @classmethod
    def start(cls, count: int, **alphas) -> TSB:
        return cls(p=np.full(count, np.nan), z=np.full(count, np.nan), v=np.full(count, np.nan), **alphas)

    @property
    def base(self) -> np.ndarray:
        """Deseasonalized expected units a day (0 before the first observed day)."""
        return np.nan_to_num(self.p * self.z)

    @property
    def phi(self) -> np.ndarray:
        """Variance / mean of daily demand, at least 1."""
        base = self.base
        ratio = np.where(base > 0, np.nan_to_num(self.v) / np.maximum(base, 1e-9), 1.0)
        return np.clip(ratio, 1.0, 50.0)

    def update(self, units: np.ndarray, season: np.ndarray, observed: np.ndarray) -> None:
        """
        One day: units sold, the seasonal index of the day and which products were observed (on sale and in stock).
        Products seen for the first time start at the observed value.
        """
        x = units / season
        new = observed & np.isnan(self.p)
        self.p[new] = (x[new] > 0) * 0.5 + 0.25
        self.z[new] = np.where(x[new] > 0, x[new], 1.0)
        self.v[new] = np.maximum(x[new], 1.0)
        seen = observed & ~new
        error = x[seen] - self.base[seen]
        self.v[seen] += self.alpha_v * (error ** 2 - self.v[seen])
        sale = seen & (x > 0)
        self.p[seen] += self.alpha_p * ((x[seen] > 0) - self.p[seen])
        self.z[sale] += self.alpha_z * (x[sale] - self.z[sale])

    def prime(self, base: np.ndarray, products: np.ndarray) -> None:
        """Start products without history (a launch) at a given base, as if they sold every second day."""
        fresh = products & np.isnan(self.p)
        self.p[fresh] = 0.5
        self.z[fresh] = np.maximum(base[fresh] / 0.5, 1e-3)
        self.v[fresh] = np.maximum(base[fresh], 1.0)


def run_tsb(state: TSB, sold: np.ndarray, season: np.ndarray, observed: np.ndarray) -> TSB:
    """Feed a block of days (days x products) to the TSB state."""
    for t in range(len(sold)):
        state.update(sold[t], season[t], observed[t])
    return state


def wape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """Weighted absolute percentage error: sum |actual - predicted| / sum actual."""
    return float(np.abs(actual - predicted).sum() / max(actual.sum(), 1e-9))
