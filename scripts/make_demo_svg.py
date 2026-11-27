"""
Build docs/img/app-demo.svg and app-demo-dark.svg, the animated demo at the top of the README, and the README block
<!-- generated:hero --> with its description.

    python scripts/make_demo_svg.py [--shots DIR] [--reuse] [--quality 70] [--res 1.25] [--lang pl|en]

The demo is an illustration made of one full-page screenshot of the real app, not a recording. One loop of 12 s:
the view rests on the backtest (its numbers and the stock chart), glides to the plan of the largest supplier, the
cursor clicks "Download the order (.xlsx)" and a file mark appears, the view glides to the chart of one product (its
stock, forecast and planned deliveries) and back to the backtest, which is again the first frame.

The script starts the Dash app on 127.0.0.1 and takes a screenshot 960 CSS px wide at device scale factor 2
(headless Chrome or Edge, scripts/browser.py). It stops if the app shows other numbers than purchase_planner.report.
The cursor, the click ring, the file mark and the scrollbar are vectors. Only CSS animations of transform and
opacity, no script and no external file: GitHub shows README images through <img>. With prefers-reduced-motion the
image shows the first frame. The two files differ only in the browser frame (light and dark GitHub theme). --shots
keeps the screenshot and geometry in DIR; --reuse builds from them without starting the app; two builds from the same
screenshot give the same bytes.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from browser import HIDDEN, Browser, stop_tree, wait_for  # noqa: E402

from purchase_planner import backtest, data, report  # noqa: E402
from purchase_planner import theme as look  # noqa: E402

OUT_DIR = ROOT / "docs" / "img"
README = ROOT / "README.md"
CSS_W, DSF = 960, 2
VIEW = 600  # CSS px of the page in view
W = 1000
K = W / CSS_W
BAR = 36
LIMIT = 500 * 1024
EASE = "cubic-bezier(.65,0,.35,1)"
EASE_OUT = "cubic-bezier(.22,1,.36,1)"
INK = look.INK
CURSOR = "M0 0V17.2L4.3 13.3L7.2 20.1L10.3 18.8L7.5 12.2H13.2Z"
FRAMES = {
    "light": {"bar": "#f6f8fa", "border": "#d0d7de", "dot": "#d0d7de", "pill": "#ffffff", "pill_text": "#57606a"},
    "dark": {"bar": "#161b22", "border": "#30363d", "dot": "#484f58", "pill": "#0d1117", "pill_text": "#8b949e"},
}

T = 12.0
TO_PLAN = (1.6, 2.9)
CLICK = 4.0
FILE = (4.15, 6.4)
TO_PRODUCT = (6.5, 7.8)
BACK = (9.6, 11.2)

GEOMETRY_JS = """(() => {
  const box = e => { const r = e.getBoundingClientRect(); return {x: r.left, y: r.top + scrollY, w: r.width,
                                                                  h: r.height}; };
  return JSON.stringify({
    backtest: box(document.getElementById('backtest')), plan: box(document.getElementById('plan')),
    button: box(document.getElementById('download-button')),
    product: box(document.querySelector('#product-view .dg-chart')),
    stats: [...document.querySelectorAll('#backtest .dg-stat-value')].map(e => e.textContent),
    page_bg: getComputedStyle(document.querySelector('.dg-page')).backgroundColor,
    height: document.documentElement.scrollHeight});
})()"""


def expected() -> dict:
    """The numbers the app must show: the backtest's headline values, from the same code as the app."""
    table = report.backtest_table(backtest.run_all(backtest.prepare(data.load(data.REPORT_SEED, truth=True))))
    k = report.kpis(table)
    return {"stats": [report.percent(k["fill_planner"]), report.compact(k["cash_freed"]),
                      report.compact(k["margin_planner"]), report.compact(k["revenue_planner"])], "kpis": k}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def capture(port: int, shots: Path) -> None:
    async with Browser() as page:
        await page.viewport(CSS_W, 900, DSF)
        await page.open(f"http://127.0.0.1:{port}/")
        await page.until("document.querySelectorAll('.dg-graph .main-svg').length >= 3 && "
                         "document.fonts.status === 'loaded'")
        await page.js("document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0)")
        await page.send("Input.dispatchMouseEvent", type="mouseMoved", x=2, y=2)
        await asyncio.sleep(1.5)
        geometry = json.loads(await page.js(GEOMETRY_JS))
        end = min(geometry["height"], geometry["product"]["y"] + geometry["product"]["h"] + 40)
        shot = await page.send("Page.captureScreenshot", format="png", captureBeyondViewport=True,
                               clip={"x": 0, "y": 0, "width": CSS_W, "height": end, "scale": 1})
        (shots / "page.png").write_bytes(base64.b64decode(shot["data"]))
        geometry["shot_height"] = end
    (shots / "geometry.json").write_text(json.dumps(geometry, indent=1), encoding="utf-8")


def take_screenshot(shots: Path) -> None:
    port = free_port()
    env = {**os.environ, "MPLBACKEND": "Agg", "PP_PORT": str(port)}
    app = subprocess.Popen([sys.executable, "-m", "ui.app"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, **HIDDEN)
    try:
        wait_for(f"http://127.0.0.1:{port}/", 240)
        asyncio.run(capture(port, shots))
    finally:
        stop_tree(app)


class Motion:
    """CSS keyframes on one timeline. Each track: (seconds, value, easing to the next stop)."""

    def __init__(self, total: float):
        self.total, self.css, self.count = total, [], 0

    def track(self, prop: str, stops: list, rest) -> str:
        self.count += 1
        name = f"m{self.count}"
        stops = sorted(stops, key=lambda s: s[0])
        if stops[0][0] > 0:
            stops.insert(0, (0, stops[0][1], "linear"))
        if stops[-1][0] < self.total:
            stops.append((self.total, stops[-1][1], "linear"))
        frames = "".join(f"{s / self.total * 100:.3f}%{{{prop}:{value};animation-timing-function:{ease}}}"
                         for s, value, ease in stops)
        self.css.append(f"@keyframes {name}{{{frames}}}.{name}{{{prop}:{rest};"
                        f"animation:{name} {self.total:g}s linear 0s infinite both}}")
        return name


def tr(x: float, y: float) -> str:
    return f"translate({x:.1f}px,{y:.1f}px)"


def css_color(value: str) -> str:
    parts = [int(float(p)) for p in value[value.index("(") + 1:value.index(")")].split(",")[:3]]
    return "#{:02x}{:02x}{:02x}".format(*parts)


def alt_text(k: dict, language: str) -> str:
    if language == "pl":
        served = report.share(k["fill_planner"], 1, "pl")
        return (f"Aplikacja Purchase Planner w ilustracji: wynik testu wstecznego 2024 ({served} "
                f"obsłużonego popytu, {report.money(k['cash_freed'], 'pl')} zł mniej zapasu niż u kupca sklepu), "
                "przewinięcie do planu największego dostawcy, kliknięcie pobrania zamówienia do Excela i wykres "
                "jednego produktu ze stanem, prognozą i planowanymi dostawami.")
    return (f"Purchase Planner app, illustrated: the 2024 backtest ({report.share(k['fill_planner'])} of demand "
            f"served, {report.money(k['cash_freed'])} PLN less stock than the shop's buyer), a scroll to the plan of "
            "the largest supplier, a click on the Excel download and the chart of one product with its stock, forecast "
            "and planned deliveries.")


def build(shots: Path, quality: int, res: float, language: str) -> tuple[dict[str, str], str]:
    geo = json.loads((shots / "geometry.json").read_text(encoding="utf-8"))
    values = expected()
    if geo["stats"] != values["stats"]:
        sys.exit(f"The app shows {geo['stats']}, the model gives {values['stats']}: retake the screenshot.")
    height = geo["shot_height"]
    top = geo["backtest"]["y"] - 8  # the demo starts at the backtest's numbers; the page above it is cut
    image = Image.open(shots / "page.png").convert("RGB").crop((0, round(top * DSF), CSS_W * DSF, height * DSF))
    page_bg = css_color(geo["page_bg"])
    size = (round(CSS_W * K * res), round((height - top) * K * res))
    buffer = io.BytesIO()
    image.resize(size, Image.LANCZOS).save(buffer, "WEBP", quality=quality, method=6)
    encoded = base64.b64encode(buffer.getvalue()).decode()
    page = (f'<rect y="{top * K:.2f}" width="{CSS_W * K:.2f}" height="{(height - top) * K:.2f}" fill="{page_bg}"/>'
            f'<image y="{top * K:.2f}" width="{CSS_W * K:.2f}" height="{(height - top) * K:.2f}" '
            f'preserveAspectRatio="none" href="data:image/webp;base64,{encoded}"/>')

    y = {"start": top, "plan": geo["plan"]["y"] - 8,
         "product": min(height - VIEW, geo["product"]["y"] + geo["product"]["h"] + 24 - VIEW)}
    m = Motion(T)
    scroll = [(0, y["start"]), (TO_PLAN[0], y["start"]), (TO_PLAN[1], y["plan"]), (TO_PRODUCT[0], y["plan"]),
              (TO_PRODUCT[1], y["product"]), (BACK[0], y["product"]), (BACK[1], y["start"]), (T, y["start"])]
    stops = [(t, v, EASE if i + 1 < len(scroll) and scroll[i + 1][1] != v else "linear")
             for i, (t, v) in enumerate(scroll)]
    scrolling = m.track("transform", [(t, tr(0, -v * K), e) for t, v, e in stops], tr(0, -top * K))
    view = []
    thumb_h = VIEW * VIEW / height
    room = VIEW - thumb_h - 6
    bar = m.track("transform", [(t, tr(0, v / (height - VIEW) * room * K), e) for t, v, e in stops],
                  tr(0, top / (height - VIEW) * room * K))
    view.append(f'<rect class="{bar}" x="{(CSS_W - 7) * K:.2f}" y="{3 * K:.2f}" width="{4 * K:.2f}" '
                f'height="{thumb_h * K:.2f}" rx="{2 * K:.2f}" fill="{INK}" opacity="0.28"/>')

    # the cursor: rests, moves to the download button and clicks it, rests
    b = geo["button"]
    target = (b["x"] + b["w"] * 0.55, b["y"] + b["h"] / 2 - y["plan"])
    rest = (760, 520)
    path = [(0, rest, "linear"), (TO_PLAN[1], rest, EASE), (CLICK - 0.12, target, "linear"),
            (FILE[0] + 0.6, target, EASE), (TO_PRODUCT[1], rest, "linear")]
    move = m.track("transform", [(t, tr(px * K, py * K), e) for t, (px, py), e in path], tr(rest[0] * K, rest[1] * K))
    press = m.track("transform", [(0, "scale(1)", "linear"), (CLICK - 0.08, "scale(1)", EASE_OUT),
                                  (CLICK, "scale(.88)", "linear"), (CLICK + 0.12, "scale(.88)", EASE_OUT),
                                  (CLICK + 0.3, "scale(1)", "linear")], "scale(1)")
    accent = look.PRIMARY
    ring = m.track("transform", [(CLICK, "scale(.2)", EASE_OUT), (CLICK + 0.5, "scale(1)", "linear"),
                                 (CLICK + 0.51, "scale(.2)", "linear")], "scale(1)")
    fade = m.track("opacity", [(CLICK - 0.01, 0, "linear"), (CLICK, 0.45, EASE_OUT), (CLICK + 0.5, 0, "linear")], 0)
    view.append(f'<g transform="translate({target[0] * K:.1f} {target[1] * K:.1f})"><g class="{fade}">'
                f'<circle class="{ring}" r="18" fill="{accent}" fill-opacity="0.35"/></g></g>')
    # the file mark: a sheet with a grid and a tick, next to the button, while the download "arrives"
    fx, fy = (b["x"] + b["w"] + 22) * K, (b["y"] - y["plan"] - 6) * K
    show = m.track("opacity", [(FILE[0] - 0.01, 0, "linear"), (FILE[0], 0, EASE_OUT), (FILE[0] + 0.3, 1, "linear"),
                               (FILE[1] - 0.3, 1, EASE), (FILE[1], 0, "linear")], 0)
    rise = m.track("transform", [(FILE[0], tr(0, 10), EASE_OUT), (FILE[0] + 0.4, tr(0, 0), "linear")], tr(0, 0))
    grid = "".join(f'<line x1="9" y1="{y0}" x2="33" y2="{y0}" stroke="{accent}" stroke-width="1.4"/>'
                   for y0 in (20, 27, 34))
    grid += f'<line x1="18" y1="14" x2="18" y2="40" stroke="{accent}" stroke-width="1.4"/>'
    view.append(f'<g class="{show}"><g class="{rise}"><g transform="translate({fx:.1f} {fy:.1f})">'
                f'<rect x="0" y="0" width="42" height="50" rx="5" fill="#ffffff" stroke="{accent}" stroke-width="2"/>'
                f'<rect x="0" y="0" width="42" height="11" rx="5" fill="{accent}"/>{grid}'
                f'<circle cx="38" cy="44" r="10" fill="{look.ACCENT}"/>'
                f'<path d="M33.5 44.2l3 3 6-6.2" fill="none" stroke="#ffffff" stroke-width="2.2" '
                f'stroke-linecap="round" stroke-linejoin="round"/></g></g></g>')
    view.append(f'<g class="{move}"><g class="{press}"><path d="{CURSOR}" transform="scale(1.15)" fill="{INK}" '
                f'stroke="#ffffff" stroke-width="1.3" stroke-linejoin="round" filter="url(#shadow)"/></g></g>')

    alt = alt_text(values["kpis"], language)
    vh = VIEW * K
    H = BAR + vh
    css = "".join(m.css) + "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
    content = (f'<g clip-path="url(#view)"><g transform="translate(0 {BAR})"><g class="{scrolling}">{page}</g>'
               f'{"".join(view)}</g></g>')
    out = {}
    for theme, colors in FRAMES.items():
        dots = "".join(f'<circle cx="{18 + i * 16}" cy="{BAR / 2}" r="5" fill="{colors["dot"]}"/>' for i in range(3))
        host, pill_w = "127.0.0.1:8050", 150
        out[theme] = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H:.0f}" width="{W}" height="{H:.0f}" '
            f'role="img" aria-label="{alt}"><title>{alt}</title><defs><style>{css}</style>'
            f'<clipPath id="frame"><rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1:.1f}" rx="10"/></clipPath>'
            f'<clipPath id="view"><rect x="0" y="{BAR}" width="{W}" height="{vh:.1f}"/></clipPath>'
            f'<filter id="shadow" x="-50%" y="-50%" width="200%" height="200%"><feDropShadow dx="0" dy="1.2" '
            f'stdDeviation="1.4" flood-color="#000" flood-opacity="0.35"/></filter></defs>'
            f'<g clip-path="url(#frame)"><rect width="{W}" height="{H:.1f}" fill="{page_bg}"/>{content}'
            f'<rect width="{W}" height="{BAR}" fill="{colors["bar"]}"/>'
            f'<line x1="0" y1="{BAR - 0.5}" x2="{W}" y2="{BAR - 0.5}" stroke="{colors["border"]}"/>{dots}'
            f'<rect x="{W / 2 - pill_w / 2}" y="{BAR / 2 - 11}" width="{pill_w}" height="22" rx="11" '
            f'fill="{colors["pill"]}" stroke="{colors["border"]}"/>'
            f'<text x="{W / 2}" y="{BAR / 2 + 4.3}" text-anchor="middle" font-size="12.5" '
            f'fill="{colors["pill_text"]}" style="font-family:ui-monospace,SFMono-Regular,Consolas,monospace">'
            f'{host}</text></g>'
            f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1:.1f}" rx="10" fill="none" '
            f'stroke="{colors["border"]}"/></svg>')
    return out, alt


def write_hero(alt: str) -> None:
    block = "\n".join(["<picture>",
                       '  <source media="(prefers-color-scheme: dark)" srcset="docs/img/app-demo-dark.svg">',
                       f'  <img alt="{alt}" src="docs/img/app-demo.svg">', "</picture>"])
    readme = README.read_text(encoding="utf-8")
    pattern = re.compile(r"(<!-- generated:hero -->\n)(?:.*?\n)?(<!-- /generated:hero -->)", re.S)
    if not pattern.search(readme):
        raise SystemExit("README.md has no block <!-- generated:hero -->")
    README.write_text(pattern.sub(lambda match: match.group(1) + block + "\n" + match.group(2), readme),
                      encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shots", type=Path, default=ROOT / "output" / "demo-shots", help="screenshot folder")
    parser.add_argument("--reuse", action="store_true", help="build from --shots without starting the app")
    parser.add_argument("--quality", type=int, default=70, help="WebP quality of the screenshot")
    parser.add_argument("--res", type=float, default=1.25, help="image pixels per SVG pixel")
    parser.add_argument("--lang", choices=report.LANGUAGES, default="en", help="language of the description")
    args = parser.parse_args()
    args.shots.mkdir(parents=True, exist_ok=True)
    if not (args.reuse and (args.shots / "geometry.json").exists()):
        take_screenshot(args.shots)
    svgs, alt = build(args.shots, args.quality, args.res, args.lang)
    for theme, svg in svgs.items():
        path = OUT_DIR / ("app-demo.svg" if theme == "light" else "app-demo-dark.svg")
        path.write_text(svg, encoding="utf-8", newline="\n")
        print(f"{path.name}: {path.stat().st_size / 1024:.0f} KB, loop {T:g} s")
        if path.stat().st_size > LIMIT:
            sys.exit(f"{path.name} is over {LIMIT // 1024} KB: lower --quality or --res.")
    write_hero(alt)
    print("Updated the hero block of README.md")


if __name__ == "__main__":
    main()
