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


def stock_title(table: pd.DataFrame, language: str = "en") -> tuple[str, list[str]]:
    k = kpis(table)
    if language == "pl":
        return (f"Planer trzyma średnio o {money(k['cash_freed'], 'pl')} zł mniej w magazynie przez cały 2024 rok",
                ["Zapas po cenie zakupu na koniec każdego dnia. Ten sam popyt, ten sam stan na start i ci sami "
                 "dostawcy; kupiec sklepu to prawdziwy rok z Data-Generatora."])
    return (f"The planner keeps {money(k['cash_freed'])} PLN less in stock, on average, through 2024",
            ["Stock at purchase cost at the end of each day. Same demand, same start and the same suppliers for "
             "every line; the shop's buyer is Data-Generator's own year."])


def lost_title(results: dict, dates: pd.DatetimeIndex, language: str = "en") -> tuple[str, list[str]]:
    buyer = monthly_lost_share(results["shop_history"], dates)
    planner = monthly_lost_share(results["planner"], dates)
    worst = int(buyer.to_numpy().argmax())
    month = MONTHS_IN[language][buyer.index[worst] - 1]
    if language == "pl":
        return (f"Kupiec na oko traci najwięcej w szczycie: {share(buyer.iloc[worst], 0, 'pl')} popytu w {month}, "
                f"planer {share(planner.iloc[worst], 0, 'pl')}",
                ["Sztuki, o które pytali klienci, a których nie było na stanie, jako część popytu każdego miesiąca "
                 "2024 roku."])
    return (f"Buying by eye loses the most at the peak: {share(buyer.iloc[worst], 0)} of {month} demand, "
            f"{share(planner.iloc[worst], 0)} with the planner",
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


# ---------------------------------------------------------------------------------------------------------------- #
# Two languages: English for the app and the public README, Polish for the README while the repository is private.

LANGUAGES = ("en", "pl")
MONTHS = {"en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
          "pl": ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]}
MONTHS_IN = {"en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                     "November", "December"],
             "pl": ["styczniu", "lutym", "marcu", "kwietniu", "maju", "czerwcu", "lipcu", "sierpniu", "wrześniu",
                    "październiku", "listopadzie", "grudniu"]}
LABELS_PL = {"shop_history": "Kupiec sklepu (dane)", "by_eye": "Kupiec na oko (odtworzony)",
             "planner_abc": "Planer, stałe progi ABC", "planner": "Planer", "oracle": "Prognoza idealna"}


def label(policy: str, language: str = "en") -> str:
    return (LABELS_PL if language == "pl" else LABELS)[policy]


def number(value: float, decimals: int = 0, language: str = "en") -> str:
    """1,234.5 in English, 1 234,5 in Polish (a non-breaking space between thousands)."""
    text = f"{value:,.{decimals}f}"
    if language == "pl":
        text = text.replace(",", " ").replace(".", ",").replace(" ", "\u00a0")
    return text.replace("-", "−")


def plural_pl(count: int, one: str, few: str, many: str) -> str:
    """Polish noun after a number: 1 linia, 2-4 linie (not 12-14), 5+ linii."""
    if count == 1:
        return one
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return few
    return many


def money(value: float, language: str = "en") -> str:
    """0.92 M / 0,92 mln, 921 k / 921 tys."""
    sign, value = ("−" if value < 0 else ""), abs(value)
    if value >= 1e6:
        text = number(value / 1e6, 2, language) + (" mln" if language == "pl" else " M")
    elif value >= 1e4:
        text = number(value / 1e3, 0, language) + (" tys." if language == "pl" else " k")
    else:
        text = number(value, 0, language)
    return sign + text


def share(value: float, decimals: int = 1, language: str = "en", sign: bool = False) -> str:
    text = number(value * 100, decimals, language)
    if sign and value > 0:
        text = "+" + text
    return text + "%"


def forecast_quality(setup) -> dict:
    """
    Accuracy of the forecast on 2024, one day ahead and summed by product and week, against the true demand (sold
    and lost): WAPE (sum of absolute errors / sum of demand; 0 is perfect) and bias (forecast / demand), next to the
    average of the last 28 days. The forecast learns from the true demand day by day, as if nothing ran out.
    """
    from purchase_planner import backtest  # noqa: PLC0415  (avoid a cycle at import)
    world, context = setup.world, setup.context
    demand = world.demand().astype(float)
    active = setup.history.active[world.start:world.start + world.days]
    state = backtest.trained_state(setup)
    forecast = np.zeros_like(demand)
    naive = np.zeros_like(demand)
    window = setup.history.sold[world.start - 28:world.start].astype(float)
    for d in range(world.days):
        t = world.start + d
        forecast[d] = state.base * context.season[t] * active[d]
        naive[d] = window.mean(axis=0) * active[d]
        state.update(demand[d], context.season[t], active[d])
        window = np.vstack([window[1:], demand[d]])
    week = np.arange(world.days) // 7

    def weekly(values):
        return pd.DataFrame(values).groupby(week).sum().to_numpy()

    actual, ours, simple = weekly(demand), weekly(forecast), weekly(naive)
    first_day = setup.history.dates[world.start]
    peak = np.array([(first_day + pd.Timedelta(days=7 * w)).month >= 11 for w in range(len(actual))])

    def wape(predicted, rows=slice(None)):
        return float(np.abs(predicted[rows] - actual[rows]).sum() / actual[rows].sum())

    return {"wape": wape(ours), "wape_naive": wape(simple), "wape_peak": wape(ours, peak),
            "wape_peak_naive": wape(simple, peak), "bias": float(forecast.sum() / demand.sum()),
            "bias_naive": float(naive.sum() / demand.sum())}
