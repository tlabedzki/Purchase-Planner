"""
The README charts and every number in the README, from one run: the 2024 backtest on seed 42, the tuning on seed 7,
the forecast accuracy and the plan for the next 30 days.

    python scripts/make_charts.py --lang pl      # Polish README while the repository is private
    python scripts/make_charts.py --lang en      # English README for the public release

Charts are the app's own Plotly figures (src/purchase_planner/figures.py) on a white page with Inter from the repo,
saved as PNG by headless Chrome or Edge (scripts/browser.py). README.md marks each generated part with
<!-- generated:<name> --> and <!-- /generated:<name> -->; only the text between a pair is replaced, so two runs on the
same data give the same bytes.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import textwrap
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from browser import Browser  # noqa: E402

from purchase_planner import backtest, data, figures, plan, report  # noqa: E402
from purchase_planner import theme as t  # noqa: E402

IMG = ROOT / "docs" / "img"
README = ROOT / "README.md"
CACHE = ROOT / ".cache" / "charts"
FONTS = ROOT / "ui" / "assets" / "fonts"
CHART_WIDTH, PAD, SCALE = 760, 24, 2
FILL_RATE_GOAL = 0.95


# ---------------------------------------------------------------------------------------------------------------- #
# Numbers

def compute(language: str) -> dict:
    setup = backtest.prepare(data.load(data.REPORT_SEED, truth=True))
    results = backtest.run_all(setup)
    table = report.backtest_table(results)
    tuning = backtest.prepare(data.load(data.TUNING_SEED, truth=True))
    choice, grid = backtest.tune(tuning)
    month = plan.build_plan(data.load(data.REPORT_SEED))
    dates = setup.history.dates[setup.world.start:setup.world.start + setup.world.days]
    return {"language": language, "setup": setup, "results": results, "table": table, "choice": choice,
            "grid": grid, "quality": report.forecast_quality(setup), "plan": month, "dates": dates}


def blocks(n: dict) -> dict[str, str]:
    pl = n["language"] == "pl"
    lang = n["language"]
    k = report.kpis(n["table"])
    row = n["table"].set_index("policy")
    q = n["quality"]
    money = lambda v: report.money(v, lang)  # noqa: E731
    pct = lambda v, d=1, sign=False: report.share(v, d, lang, sign)  # noqa: E731
    num = lambda v, d=0: report.number(v, d, lang)  # noqa: E731
    eye, abc, oracle = row.loc["by_eye"], row.loc["planner_abc"], row.loc["oracle"]
    grid = n["grid"]
    chosen = grid[(grid["price_of_service"] == n["choice"]["price_of_service"])
                  & (grid["value_exponent"] == n["choice"]["value_exponent"])].iloc[0]
    month = n["plan"]
    firm = month[month["status"] == "firm"]
    example = month[month["status"] == "firm"].sort_values("order_value", ascending=False).iloc[0]
    out = {}
    if pl:
        out["result"] = (
            f"**Wynik.** Na całym 2024 roku planer obsłużył {pct(k['fill_planner'])} popytu (kupiec sklepu "
            f"{pct(k['fill_buyer'])}), trzymając średnio o {money(k['cash_freed'])} zł mniej w magazynie "
            f"({pct(k['stock_change'], 0, True)}) i tracąc o {money(k['margin_saved'])} zł mniej marży "
            f"({pct(k['margin_change'], 0, True)}).")
        out["summary"] = (
            f"- **Trafione:** w listopadzie i grudniu prognoza myli się mniej niż średnia z 28 dni (WAPE "
            f"{num(q['wape_peak'], 2)} wobec {num(q['wape_peak_naive'], 2)}), a planer nie gubi szczytu Black Friday.\n"
            f"- **Chybione:** utracony przychód jest wyższy niż u kupca ({money(k['revenue_planner'])} wobec "
            f"{money(k['revenue_buyer'])} zł), bo planer częściej odpuszcza drogie produkty z niską marżą.")
        out["forecast"] = (
            f"Na 2024 roku, w sumach tygodniowych na produkt, błąd WAPE prognozy wynosi {num(q['wape'], 2)}, "
            f"a średniej z 28 dni {num(q['wape_naive'], 2)}; w listopadzie i grudniu {num(q['wape_peak'], 2)} wobec "
            f"{num(q['wape_peak_naive'], 2)}. Suma prognozy to {num(q['bias'], 2)} prawdziwego popytu (1 to brak "
            f"przechyłu).")
        header = "| Polityka | Obsłużony popyt | Średni zapas, zł | Utracona marża, zł | Utracony przychód, zł |"
    else:
        out["result"] = (
            f"**Result.** Over all of 2024 the planner served {pct(k['fill_planner'])} of demand (the shop's buyer "
            f"{pct(k['fill_buyer'])}) with {money(k['cash_freed'])} PLN less stock on average "
            f"({pct(k['stock_change'], 0, True)}) and {money(k['margin_saved'])} PLN less margin lost "
            f"({pct(k['margin_change'], 0, True)}).")
        out["summary"] = (
            f"- **What worked:** in November and December the forecast misses less than the 28-day average (WAPE "
            f"{num(q['wape_peak'], 2)} against {num(q['wape_peak_naive'], 2)}), and the planner keeps up with Black "
            f"Friday.\n"
            f"- **What missed:** lost revenue is higher than the buyer's ({money(k['revenue_planner'])} against "
            f"{money(k['revenue_buyer'])} PLN): the planner lets expensive, low-margin products run out more often.")
        out["forecast"] = (
            f"On 2024, summed by product and week, the forecast has a WAPE of {num(q['wape'], 2)} and the 28-day "
            f"average {num(q['wape_naive'], 2)}; in November and December {num(q['wape_peak'], 2)} against "
            f"{num(q['wape_peak_naive'], 2)}. The forecast adds up to {num(q['bias'], 2)} of the true demand (1 means "
            f"no lean either way).")
        header = "| Policy | Demand served | Average stock, PLN | Lost margin, PLN | Lost revenue, PLN |"
    rows = [header, "|---|---:|---:|---:|---:|"]
    for record in n["table"].to_dict("records"):
        name = report.label(record["policy"], lang)
        name = f"**{name}**" if record["policy"] == "planner" else name
        rows.append(f"| {name} | {pct(record['fill_rate'])} | {money(record['average_stock_value'])} | "
                    f"{money(record['lost_margin'])} | {money(record['lost_revenue'])} |")
    stock_alt, _ = report.stock_title(n["table"], lang)
    lost_alt, _ = report.lost_title(n["results"], n["dates"], lang)
    out["backtest"] = "\n".join([
        *rows, "", f"![{stock_alt}](docs/img/stock-over-year.png)", "", f"![{lost_alt}](docs/img/lost-by-month.png)"])
    if pl:
        out["allocation"] = (
            f"Ta sama prognoza ze stałymi progami ABC obsługuje {pct(abc['fill_rate'])} popytu, ale trzyma średnio "
            f"{money(abc['average_stock_value'])} zł zapasu, więcej niż kupiec na oko "
            f"({money(eye['average_stock_value'])} zł). Z przydziałem jednego budżetu: {pct(k['fill_planner'])} "
            f"przy {money(k['stock_planner'])} zł. "
            f"Na sklepie do strojenia (seed 7) wybrane ustawienie daje {pct(chosen['fill_rate'])} obsługi i "
            f"{money(chosen['average_stock_value'])} zł zapasu; sprawdzono {len(grid)} ustawień, "
            f"{int(grid['allowed'].sum())} spełniło oba warunki.")
        out["plan"] = (
            f"Plan na {plan.HORIZON_DAYS} dni od {month['order_date'].min():%d.%m.%Y} ma {num(len(month))} "
            f"{report.plural_pl(len(month), 'linię', 'linie', 'linii')} u {month['supplier_id'].nunique()} "
            f"dostawców na {money(month['order_value'].sum())} zł; zamówienia pewne (pierwszy dzień zamówień każdego "
            f"dostawcy) to {num(len(firm))} {report.plural_pl(len(firm), 'linia', 'linie', 'linii')} na "
            f"{money(firm['order_value'].sum())} zł. Największa pozycja pewna: {example['product_name']} "
            f"({example['supplier_name']}), {example['quantity']} szt., z powodem w aplikacji (po angielsku): "
            f"„{example['reason']}”\n\n"
            "![Plan dostawcy w aplikacji: liczby planu, pobranie zamówienia do Excela i linie z powodem każdej "
            "ilości](docs/img/app-plan.png)")
        checks = [
            (f"Obsłużony popyt co najmniej {pct(FILL_RATE_GOAL, 0)}", pct(k["fill_planner"]), "tak"),
            ("Średni zapas niższy niż u kupca sklepu",
             f"{money(k['stock_planner'])} wobec {money(k['stock_buyer'])} zł", "tak"),
            ("Średni zapas niższy niż u kupca na oko (odtworzonego)",
             f"{money(k['stock_planner'])} wobec {money(eye['average_stock_value'])} zł", "tak"),
            ("Utracona marża niższa niż u kupca sklepu",
             f"{money(k['margin_planner'])} wobec {money(k['margin_buyer'])} zł", "tak"),
            ("Utracony przychód niższy niż u kupca sklepu",
             f"{money(k['revenue_planner'])} wobec {money(k['revenue_buyer'])} zł", "nie"),
            ("Blisko prognozy idealnej (sufit)",
             f"{pct(k['fill_planner'])} i {money(k['stock_planner'])} zł wobec {pct(oracle['fill_rate'])} i "
             f"{money(oracle['average_stock_value'])} zł", "częściowo"),
        ]
        out["verdicts"] = "\n".join(["| Kryterium | Planer | Ocena |", "|---|---|---|",
                                     *[f"| {a} | {b} | {c} |" for a, b, c in checks]])
    else:
        out["allocation"] = (
            f"The same forecast with fixed ABC levels serves {pct(abc['fill_rate'])} of demand but holds "
            f"{money(abc['average_stock_value'])} PLN of stock on average, more than buying by eye "
            f"({money(eye['average_stock_value'])} PLN). With one shared budget: {pct(k['fill_planner'])} on "
            f"{money(k['stock_planner'])} PLN. On the tuning shop (seed 7) the chosen setting serves "
            f"{pct(chosen['fill_rate'])} on {money(chosen['average_stock_value'])} PLN of stock; {len(grid)} settings "
            f"were tried and {int(grid['allowed'].sum())} met both conditions.")
        out["plan"] = (
            f"The {plan.HORIZON_DAYS}-day plan from {month['order_date'].min():%Y-%m-%d} has {num(len(month))} lines "
            f"at {month['supplier_id'].nunique()} suppliers for {money(month['order_value'].sum())} PLN; the firm "
            f"orders (each supplier's first order day) are {num(len(firm))} lines for "
            f"{money(firm['order_value'].sum())} PLN. The largest firm line: {example['product_name']} "
            f"({example['supplier_name']}), {example['quantity']} units: \"{example['reason']}\"\n\n"
            "![The plan of one supplier in the app: the plan's numbers, the Excel download and every line with the "
            "reason for its quantity](docs/img/app-plan.png)")
        checks = [
            (f"Demand served at least {pct(FILL_RATE_GOAL, 0)}", pct(k["fill_planner"]), "yes"),
            ("Average stock below the shop's buyer",
             f"{money(k['stock_planner'])} against {money(k['stock_buyer'])} PLN", "yes"),
            ("Average stock below buying by eye (rebuilt)",
             f"{money(k['stock_planner'])} against {money(eye['average_stock_value'])} PLN", "yes"),
            ("Lost margin below the shop's buyer",
             f"{money(k['margin_planner'])} against {money(k['margin_buyer'])} PLN", "yes"),
            ("Lost revenue below the shop's buyer",
             f"{money(k['revenue_planner'])} against {money(k['revenue_buyer'])} PLN", "no"),
            ("Close to the perfect forecast (the ceiling)",
             f"{pct(k['fill_planner'])} and {money(k['stock_planner'])} PLN against {pct(oracle['fill_rate'])} and "
             f"{money(oracle['average_stock_value'])} PLN", "partly"),
        ]
        out["verdicts"] = "\n".join(["| Criterion | Planner | Verdict |", "|---|---|---|",
                                     *[f"| {a} | {b} | {c} |" for a, b, c in checks]])
    return out


# ---------------------------------------------------------------------------------------------------------------- #
# README

def wrap(text: str, width: int = 120) -> str:
    """Wrap prose lines and list items at `width` characters; tables and images stay as they are."""
    out = []
    for line in text.splitlines():
        line = re.sub(r"(?<=\d) (?=\d|mln|tys\.|zł|PLN|szt\.)", " ", line)
        if line.lstrip().startswith(("|", "![", "<")) or len(line) <= width:
            out.append(line)
        elif line.startswith("- "):
            out.append(textwrap.fill(line, width, subsequent_indent="  ", break_long_words=False,
                                     break_on_hyphens=False))
        else:
            out.append(textwrap.fill(line, width, break_long_words=False, break_on_hyphens=False))
    return "\n".join(out)


def write_readme(texts: dict[str, str]) -> None:
    readme = README.read_text(encoding="utf-8")
    for name, text in texts.items():
        pattern = re.compile(rf"(<!-- generated:{name} -->\n)(?:.*?\n)?(<!-- /generated:{name} -->)", re.S)
        if not pattern.search(readme):
            raise SystemExit(f"README.md has no block <!-- generated:{name} -->")
        block = wrap(text)
        readme = pattern.sub(lambda match, block=block: match.group(1) + block + "\n" + match.group(2), readme)
    README.write_text(readme, encoding="utf-8", newline="\n")


# ---------------------------------------------------------------------------------------------------------------- #
# Charts

def chart_page(title: str, subtitle: str, figure) -> str:
    fonts = (ROOT / "ui" / "assets" / "fonts.css").read_text(encoding="utf-8")
    fonts = fonts.replace("url('fonts/", f"url('{FONTS.as_uri()}/")
    figure.update_layout(width=CHART_WIDTH, autosize=False)
    body = figure.to_html(full_html=False, include_plotlyjs=True, config={"staticPlot": True})
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{fonts}
html, body {{ margin: 0; background: {t.PAGE}; }}
#chart {{ width: {CHART_WIDTH}px; padding: {PAD}px; background: {t.PAGE}; font-family: {t.SANS_STACK};
         -webkit-font-smoothing: antialiased; }}
.title {{ font-size: 21px; font-weight: 600; letter-spacing: -0.01em; color: {t.INK}; line-height: 1.3; }}
.sub {{ margin-top: 4px; font-size: 14px; color: {t.MUTED}; line-height: 1.45; }}
.graph {{ margin-top: 14px; }}
.graph text {{ font-feature-settings: {t.NUMBER_FEATURES}; }}
</style></head><body><div id="chart"><div class="title">{title}</div><div class="sub">{subtitle}</div>
<div class="graph">{body}</div></div></body></html>"""


def charts(n: dict) -> list[tuple[str, str]]:
    lang, results, dates, table = n["language"], n["results"], n["dates"], n["table"]
    stock_title, stock_sub = report.stock_title(table, lang)
    lost_title, lost_sub = report.lost_title(results, dates, lang)
    return [
        ("stock-over-year", chart_page(stock_title, " ".join(stock_sub),
                                       figures.stock_over_year(results, dates, language=lang))),
        ("lost-by-month", chart_page(lost_title, " ".join(lost_sub),
                                     figures.lost_by_month(results, dates, language=lang))),
    ]


async def draw(pages: list[tuple[str, str]]) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    async with Browser() as page:
        await page.viewport(CHART_WIDTH + 2 * PAD, 900, SCALE)
        for name, html in pages:
            path = CACHE / f"{name}.html"
            path.write_text(html, encoding="utf-8")
            await page.open(path.as_uri())
            await page.until("document.fonts.status === 'loaded' && !!document.querySelector('.main-svg')")
            await asyncio.sleep(0.5)
            await page.shot("#chart", IMG / f"{name}.png")
            print(f"Saved docs/img/{name}.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lang", choices=report.LANGUAGES, default="en", help="language of README.md")
    parser.add_argument("--no-charts", action="store_true", help="only the README blocks")
    args = parser.parse_args()
    IMG.mkdir(parents=True, exist_ok=True)
    numbers = compute(args.lang)
    if not args.no_charts:
        asyncio.run(draw(charts(numbers)))
    write_readme(blocks(numbers))
    print("Updated the generated blocks of README.md")


if __name__ == "__main__":
    main()
