"""
Dash + Mantine app of Purchase Planner, in the portfolio look of Data-Generator: the 2024 backtest against the shop's
buyer, the 30-day plan of one supplier with its Excel order, and one product with its stock, forecast and deliveries.

Run locally (from the repository root):
    python -m ui.app            # http://127.0.0.1:8050

PP_DATA=sample runs it on the small sample in data/sample/ (as the tests do). The server listens on 127.0.0.1 only.
"""
from __future__ import annotations

import contextlib
import os
import sys
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import dash._dash_renderer  # noqa: E402
import dash_mantine_components as dmc  # noqa: E402
import pandas as pd  # noqa: E402
from dash import Dash, Input, Output, State, dcc, html, no_update  # noqa: E402

from purchase_planner import backtest, data, export, figures, plan, report  # noqa: E402
from ui import theme as t  # noqa: E402

dash._dash_renderer._set_react_version("19.2.4")  # Mantine 3 needs React 19; Dash 4.5 still defaults to 18

REPO_URL = "https://github.com/tlabedzki/Purchase-Planner"
PLAN_COLUMNS = [  # column, header, css class
    ("order_date", "Order", ""), ("status", "", ""), ("product_name", "Product and why", "pl-product"),
    ("quantity", "Units", "pl-num"), ("packs", "Packs", "pl-num"), ("order_value", "Value, PLN", "pl-num"),
    ("expected_delivery", "Arrives", ""),
]
POLICY_COLUMNS = [("label", "Policy", ""), ("fill_rate", "Demand served", "pl-num"),
                  ("average_stock_value", "Average stock, PLN", "pl-num"),
                  ("lost_margin", "Lost margin, PLN", "pl-num"),
                  ("lost_revenue", "Lost revenue, PLN", "pl-num"), ("order_lines", "Order lines", "pl-num"),
                  ("note", "What it is", "")]


# ---------------------------------------------------------------------------------------------------------------- #
# Data

def load_tables(truth: bool) -> dict:
    return data.load_sample(truth) if os.environ.get("PP_DATA") == "sample" else data.load(data.REPORT_SEED, truth)


@cache
def prepare():
    """Backtest results, the plan and what it is made of, computed once per process."""
    tables = load_tables(truth=True)
    setup = backtest.prepare(tables)
    results = backtest.run_all(setup)
    planning = plan.prepare(load_tables(truth=False))
    month = plan.build_plan(planning)
    dates = setup.history.dates[setup.world.start:setup.world.start + setup.world.days]
    return results, report.backtest_table(results), dates, planning, month


def start_supplier(month: pd.DataFrame, planning) -> str:
    return report.supplier_options(month, planning.catalog)[0]["value"]


def start_product(month: pd.DataFrame, supplier_id: int) -> int | None:
    lines = report.plan_lines(month, supplier_id)
    return int(lines.sort_values("order_value", ascending=False)["product_id"].iloc[0]) if len(lines) else None


# ---------------------------------------------------------------------------------------------------------------- #
# Building blocks

def section(number, title, lead, body, section_id):
    return html.Section([
        html.Div([html.Span(f"{number:02d}", className="dg-step"), html.H2(title, className="dg-h2")],
                 className="dg-section-head"),
        dmc.Text(lead, className="dg-lead-small"),
        html.Div(body, id=f"{section_id}-body"),
    ], id=section_id, className="dg-section")


def stat(label, value, note="", extra_class=""):
    return html.Div([html.Div(value, className="dg-stat-value"), html.Div(label, className="dg-stat-label"),
                     html.Div(note, className="dg-stat-note")], className=f"dg-stat {extra_class}".strip())


def chart_block(text, figure, extra_class=""):
    title, subtitle = text
    return html.Figure([
        html.Figcaption([html.Div(title, className="dg-chart-title"), html.Div(subtitle, className="dg-chart-sub")]),
        dcc.Graph(figure=figure, config=figures.CONFIG, className="dg-graph",
                  style={"height": f"{figure.layout.height}px"}),
    ], className=f"dg-chart {extra_class}")


def scroll_table(header, rows, label):
    table = html.Table([html.Thead(html.Tr(header)), html.Tbody(rows)], className="dg-table pl-table")
    return html.Div(table, className="dg-table-scroll", tabIndex="0", role="region", **{"aria-label": label})


# ---------------------------------------------------------------------------------------------------------------- #
# Views (pure functions of the data, tested without a browser)

def backtest_view(results, table, dates) -> list:
    k = report.kpis(table)
    stats = html.Div([
        stat("of demand served", report.percent(k["fill_planner"]),
             f"shop's buyer {report.percent(k['fill_buyer'])}"),
        stat("less stock on average, PLN", report.compact(k["cash_freed"]),
             f"{report.percent(k['stock_change'], 0, sign=True)} against the shop's buyer"),
        stat("lost margin, PLN", report.compact(k["margin_planner"]),
             f"shop's buyer {report.compact(k['margin_buyer'])}"),
        stat("lost revenue, PLN", report.compact(k["revenue_planner"]),
             f"shop's buyer {report.compact(k['revenue_buyer'])}", "pl-copper"),
    ], className="dg-stats pl-stats-4")
    header = [html.Th(title, className=css or None) for _, title, css in POLICY_COLUMNS]
    rows = []
    for record in table.assign(note=table["policy"].map(report.NOTES)).to_dict("records"):
        cells = []
        for column, _, css in POLICY_COLUMNS:
            value = record[column]
            if column == "fill_rate":
                value = report.percent(value)
            elif column in ("average_stock_value", "lost_margin", "lost_revenue"):
                value = report.compact(value)
            elif column == "order_lines":
                value = f"{value:,}"
            cells.append(html.Td(value, className=css or None))
        rows.append(html.Tr(cells, className="pl-best" if record["policy"] == "planner" else None))
    return [
        stats,
        html.Div(chart_block(report.stock_title(table), figures.stock_over_year(results, dates)), className="pl-gap"),
        html.Div(chart_block(report.lost_title(results, dates), figures.lost_by_month(results, dates)),
                 className="pl-gap"),
        html.Div([html.Div("Every policy on the same 2024", className="dg-chart-title"),
                  html.Div("Lost revenue is higher with the planner: it lets expensive, low-margin products run out "
                           "more often and keeps the cheap, fast and high-margin ones in stock.",
                           className="dg-chart-sub"),
                  scroll_table(header, rows, "Backtest of every policy, scrolls sideways")], className="pl-gap"),
    ]


def supplier_view(month: pd.DataFrame, planning, supplier_id: int) -> list:
    lines = report.plan_lines(month, supplier_id)
    catalog = planning.catalog
    s = int(list(catalog.supplier_id).index(supplier_id))
    days = ", ".join(day for day, on in zip(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                                            catalog.order_days[s], strict=True) if on)
    lead = planning.context.lead_mean[s]
    firm = lines[lines["status"] == "firm"]
    stats = html.Div([
        stat("to order in 30 days, PLN", report.compact(lines["order_value"].sum()),
             f"{len(lines):,} lines, {int(lines['quantity'].sum()):,} units"),
        stat("firm order, PLN", report.compact(firm["order_value"].sum()),
             f"{firm['order_date'].min():%a %d %b}" if len(firm) else "nothing to order now", "pl-copper"),
        stat("order days", days, f"{lines['order_date'].nunique()} of them in the plan"),
        stat("lead time seen, days", f"{lead:.1f}", f"promised {int(catalog.promised[s])}, {catalog.country[s]}"),
    ], className="dg-stats pl-stats-4")
    if lines.empty:
        return [stats, html.P("Nothing to order from this supplier in the next 30 days.", className="dg-placeholder")]
    header = [html.Th(title, className=css or None) for _, title, css in PLAN_COLUMNS]
    rows = []
    for record in lines.to_dict("records"):
        cells = []
        for column, _, css in PLAN_COLUMNS:
            value = record[column]
            if column in ("order_date", "expected_delivery"):
                content = f"{value:%a %d %b}"
            elif column == "status":
                content, css = value, f"pl-{value}"
            elif column == "product_name":
                content = [html.Div([value, html.Span(f" · {record['product_id']}", className="pl-id")]),
                           html.Div(record["reason"], className="pl-why")]
            elif column == "order_value":
                content = f"{value:,.2f}"
            else:
                content = f"{value:,}"
            cells.append(html.Td(content, className=css or None))
        rows.append(html.Tr(cells))
    return [stats, html.Div(scroll_table(header, rows, "Plan lines of the supplier, scrolls sideways"),
                            className="pl-block")]


def product_options(month: pd.DataFrame, supplier_id: int) -> list[dict]:
    lines = report.plan_lines(month, supplier_id)
    totals = lines.groupby(["product_id", "product_name"])["order_value"].sum().sort_values(ascending=False)
    return [{"value": str(int(pid)), "label": f"{name} · {int(pid)}, {report.compact(value)} PLN"}
            for (pid, name), value in totals.items()]


def product_view(planning, month: pd.DataFrame, product_id: int) -> list:
    position = int(list(planning.catalog.product_id).index(product_id))
    return [chart_block(figures.product_title(planning, position, month),
                        figures.product_view(planning, position, month))]


# ---------------------------------------------------------------------------------------------------------------- #
# Page

def page():
    try:
        results, table, dates, planning, month = prepare()
    except FileNotFoundError as error:
        results, problem = None, str(error)
    header = html.Header(html.Div([
        html.Span(["Purchase Planner", html.Span(".", className="dg-dot")], className="dg-wordmark"),
        html.A("Source on GitHub", href=REPO_URL, target="_blank", className="dg-link"),
    ], className="dg-wrap dg-topline"))
    hero = html.Div([
        html.P("A purchase plan per supplier", className="dg-eyebrow"),
        html.H1(["What to order, how much and ", html.Em("when"), ",", html.Br(), " for the next 30 days."],
                className="dg-h1"),
        html.P("A forecast of daily demand, the stock on hand and what each supplier takes to deliver become one "
               "order list per supplier. A replay of 2024 checks it against the shop's own buyer, who orders by eye.",
               className="dg-lead"),
    ], className="dg-hero")
    if results is None:
        body = [hero, section(1, "Backtest", "The shop data is missing.", html.P(problem, className="dg-placeholder"),
                              "backtest")]
    else:
        supplier = start_supplier(month, planning)
        product = start_product(month, int(supplier))
        body = [
            hero,
            section(1, "2024, replayed", "The true demand of 2024 against the planner and the shop's buyer, from the "
                    "same stock on 1 January.", backtest_view(results, table, dates), "backtest"),
            section(2, "The plan for the next 30 days", "Pick a supplier: every line has a reason, and the order "
                    "downloads as an Excel file.", [
                        html.Div([
                            dmc.Select(id="supplier", data=report.supplier_options(month, planning.catalog),
                                       value=supplier, label="Supplier (largest plan first)", allowDeselect=False,
                                       className="pl-select", size="md", maxDropdownHeight=360),
                            dmc.Button("Download the order (.xlsx)", id="download-button", variant="filled",
                                       color="petrol", size="md"),
                        ], className="pl-controls"),
                        dcc.Download(id="download"),
                        html.Div(supplier_view(month, planning, int(supplier)), id="supplier-view",
                                 className="pl-block"),
                    ], "plan"),
            section(3, "One product", "Its last 90 days, the forecast and the deliveries of the plan.", [
                dmc.Select(id="product", data=product_options(month, int(supplier)),
                           value=str(product) if product else None, label="Product of the supplier's plan",
                           searchable=True, allowDeselect=False, className="pl-select", size="md",
                           maxDropdownHeight=320),
                html.Div(product_view(planning, month, product) if product else [], id="product-view",
                         className="pl-block"),
            ], "one-product"),
        ]
    source = "data/sample" if os.environ.get("PP_DATA") == "sample" else f"Data-Generator {data.DATA_GENERATOR_TAG}"
    footer = html.Footer([
        html.P(f"Lumo is a fictional shop: every product, order, supplier and delivery comes from {source} (seed 42, "
               "stockouts on). Amounts in PLN without VAT."),
        html.A(REPO_URL.removeprefix("https://"), href=REPO_URL, target="_blank", className="dg-link"),
    ], className="dg-footer")
    return dmc.MantineProvider(theme=t.MANTINE_THEME, children=html.Div([
        header, html.Main(html.Div([*body, footer], className="dg-wrap")),
    ], className="dg-page"))


# ---------------------------------------------------------------------------------------------------------------- #
# App and callbacks

app = Dash(__name__, title="Purchase Planner", assets_folder=str(Path(__file__).parent / "assets"),
           suppress_callback_exceptions=True)
app.layout = page


@app.callback(Output("supplier-view", "children"), Output("product", "data"), Output("product", "value"),
              Input("supplier", "value"), prevent_initial_call=True)
def update_supplier(supplier_id):
    if not supplier_id:
        return no_update, no_update, no_update
    _, _, _, planning, month = prepare()
    options = product_options(month, int(supplier_id))
    return supplier_view(month, planning, int(supplier_id)), options, options[0]["value"] if options else None


@app.callback(Output("product-view", "children"), Input("product", "value"), prevent_initial_call=True)
def update_product(product_id):
    if not product_id:
        return []
    _, _, _, planning, month = prepare()
    return product_view(planning, month, int(product_id))


@app.callback(Output("download", "data"), Input("download-button", "n_clicks"), State("supplier", "value"),
              prevent_initial_call=True)
def download(clicks, supplier_id):
    if not clicks or not supplier_id:
        return no_update
    _, _, _, _, month = prepare()
    lines = report.plan_lines(month, int(supplier_id))
    name = lines["supplier_name"].iloc[0] if len(lines) else str(supplier_id)
    return dcc.send_bytes(export.supplier_workbook(month, int(supplier_id)), export.file_name(int(supplier_id), name))


def main():
    with contextlib.suppress(FileNotFoundError):  # without data the page explains how to get it
        prepare()  # the backtest and the plan take about 10 s: once, before the first page is served
    app.run(host="127.0.0.1", port=int(os.environ.get("PP_PORT", 8050)), debug=False)


if __name__ == "__main__":
    main()
