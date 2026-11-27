"""
Plotly figures shared by the app and the README charts, in the portfolio look: teal for the planner, mist for the
buyer by eye and past sales, one copper mark (a delivery, the worst month), hairline grid, white page.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from purchase_planner import report
from purchase_planner import theme as t

CONFIG = {"displayModeBar": False}


def _num(size: int, color) -> dict:
    return {"family": t.NUM_STACK, "size": size, "color": color}


def _layout(fig: go.Figure, height: int, **extra) -> go.Figure:
    margin = extra.pop("margin", {"l": 8, "r": 8, "t": 12, "b": 8})
    fig.update_layout(
        height=height, margin=margin, paper_bgcolor=t.PAGE, plot_bgcolor=t.PAGE,
        font={"family": t.SANS_STACK, "size": 13, "color": t.TEXT}, showlegend=False,
        hoverlabel={"bgcolor": t.PAGE, "bordercolor": t.LINE,
                    "font": {"family": t.SANS_STACK, "color": t.INK, "size": 13}},
        barcornerradius=4, dragmode=False, **{"bargap": 0.32, **extra},
    )
    fig.update_xaxes(fixedrange=True, showline=False, ticks="", tickfont=_num(12, t.MUTED))
    fig.update_yaxes(fixedrange=True, showline=False, ticks="", tickfont=_num(12, t.MUTED), gridcolor=t.LINE,
                     zeroline=False)
    return fig


def _end_label(fig: go.Figure, x, y, text: str, color: str) -> None:
    fig.add_annotation(x=x, y=y, text=text, showarrow=False, xanchor="left", xshift=8, font=_num(13, color))


def stock_over_year(results: dict, dates: pd.DatetimeIndex, height: int = 340) -> go.Figure:
    """Daily stock value of the shop's buyer (mist) and the planner (teal), M PLN."""
    fig = go.Figure()
    lines = [("shop_history", t.MIST, 2.5), ("planner", t.PRIMARY, 3)]
    for name, color, width in lines:
        value = results[name].stock_value / 1e6
        fig.add_scatter(x=dates, y=value, mode="lines", line={"color": color, "width": width},
                        hovertemplate=f"{report.LABELS[name]}<br>%{{x|%d %b}}: <b>%{{y:.2f}} M PLN</b><extra></extra>")
        _end_label(fig, dates[-1], value[-1], f"{report.LABELS[name]} {value.mean():.2f} M avg",
                   t.TEXT if color == t.MIST else t.PRIMARY)
    _layout(fig, height, margin={"l": 8, "r": 190, "t": 12, "b": 8})
    fig.update_yaxes(ticksuffix=" M", rangemode="tozero")
    fig.update_xaxes(tickformat="%b", dtick="M1", showgrid=False, range=[dates[0], dates[-1]])
    return fig


def lost_by_month(results: dict, dates: pd.DatetimeIndex, height: int = 320) -> go.Figure:
    """Share of each month's demand lost to an empty shelf: the shop's buyer (mist, its worst month copper) and the
    planner (teal)."""
    buyer = report.monthly_lost_share(results["shop_history"], dates)
    planner = report.monthly_lost_share(results["planner"], dates)
    months = [pd.Timestamp(2024, m, 1).strftime("%b") for m in buyer.index]
    worst = int(buyer.to_numpy().argmax())
    fig = go.Figure()
    fig.add_bar(x=months, y=buyer.to_numpy(), name=report.LABELS["shop_history"],
                marker={"color": [t.ACCENT if i == worst else t.MIST for i in range(len(buyer))]},
                hovertemplate="Shop's buyer, %{x}: <b>%{y:.1%}</b> of demand lost<extra></extra>")
    fig.add_bar(x=months, y=planner.to_numpy(), name="Planner", marker={"color": t.PRIMARY},
                hovertemplate="Planner, %{x}: <b>%{y:.1%}</b> of demand lost<extra></extra>")
    _layout(fig, height, barmode="group", bargap=0.28, bargroupgap=0.08)
    fig.update_yaxes(tickformat=".0%")
    fig.update_xaxes(showgrid=False)
    fig.add_annotation(x=months[worst], y=buyer.iloc[worst], text=report.percent(buyer.iloc[worst], 0),
                       showarrow=False, yshift=12, xshift=-10, font=_num(13, t.ACCENT))
    return fig


def product_view(planning, product: int, plan: pd.DataFrame, past_days: int = 90, ahead_days: int = 60,
                 height: int = 340) -> go.Figure:
    """
    One product: sales of the last days (mist bars), its stock (teal line), the forecast ahead (dashed teal) and the
    deliveries of the plan (copper).
    """
    history = planning.history
    dates = history.dates[-past_days:]
    fig = go.Figure()
    fig.add_bar(x=dates, y=history.sold[-past_days:, product], marker={"color": t.MIST}, name="Sold",
                hovertemplate="%{x|%d %b}: sold <b>%{y}</b><extra></extra>")
    fig.add_scatter(x=dates, y=history.stock[-past_days:, product], mode="lines", name="Stock",
                    line={"color": t.PRIMARY, "width": 2.5, "shape": "hv"},
                    hovertemplate="%{x|%d %b}: <b>%{y}</b> in stock<extra></extra>")
    future = planning.context.dates[planning.start:planning.start + ahead_days]
    fig.add_scatter(x=future, y=planning.forecast(product, ahead_days), mode="lines", name="Forecast",
                    line={"color": t.PRIMARY, "width": 2, "dash": "dot"},
                    hovertemplate="%{x|%d %b}: about <b>%{y:.1f}</b> a day<extra></extra>")
    product_id = planning.catalog.product_id[product]
    deliveries = plan[plan["product_id"] == product_id]
    if len(deliveries):
        fig.add_scatter(x=deliveries["expected_delivery"], y=deliveries["quantity"], mode="markers+text",
                        marker={"color": t.ACCENT, "size": 10, "symbol": "diamond"},
                        text=[f"+{q}" for q in deliveries["quantity"]], textposition="top center",
                        textfont=_num(12, t.ACCENT), name="Planned delivery",
                        hovertemplate="Planned delivery %{x|%d %b}: <b>%{y}</b> units<extra></extra>")
    fig.add_vline(x=planning.context.dates[planning.start], line={"color": t.LINE, "width": 1})
    _layout(fig, height, bargap=0.15)
    fig.update_xaxes(tickformat="%d %b", showgrid=False)
    fig.update_yaxes(rangemode="tozero")
    return fig


def product_title(planning, product: int, plan: pd.DataFrame) -> tuple[str, list[str]]:
    catalog = planning.catalog
    stock = int(planning.history.stock[-1, product])
    daily = float(np.mean(planning.forecast(product, 30)))
    cover = f"{stock / daily:.0f} days of stock" if daily > 0 else "no demand expected"
    lines = plan[plan["product_id"] == catalog.product_id[product]]
    if len(lines):
        first = lines.iloc[0]
        nxt = f"next order {first['order_date']:%d %b}: {first['quantity']} units"
    else:
        nxt = "nothing to order in 30 days"
    return (f"{catalog.name[product]}: {cover}, {nxt}",
            ["Bars: units sold a day. Line: stock at the end of the day. Dots: the forecast after the data ends. "
             "Diamonds: deliveries of the plan."])
