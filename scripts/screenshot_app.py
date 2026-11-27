"""
Start the app on 127.0.0.1, take screenshots in headless Chrome and check the portfolio look in the running page:
the font of the heading, a number and a table cell (Inter, tabular figures) and that no font comes from a service.

    python scripts/screenshot_app.py [output folder]      # default docs/img

Writes app.png (the backtest), app-plan.png, app-product.png, app-phone.png (the hero on a phone) and look.json.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from browser import HIDDEN, Browser, stop_tree, wait_for  # noqa: E402

PORT = int(os.environ.get("PP_SHOT_PORT", 8061))
URL = f"http://127.0.0.1:{PORT}/"
LOOK = """(() => {
  const style = (selector) => { const el = document.querySelector(selector); if (!el) return null;
    const s = getComputedStyle(el); return {font: s.fontFamily, features: s.fontFeatureSettings}; };
  const resources = performance.getEntriesByType('resource').map(r => r.name);
  return {heading: style('h1.dg-h1'), number: style('.dg-stat-value'), cell: style('.dg-table td.pl-num'),
          fonts: resources.filter(n => n.endsWith('.woff2')),
          services: resources.filter(n => n.includes('googleapis') || n.includes('gstatic'))};
})()"""


async def capture(folder: Path) -> dict:
    async with Browser() as page:
        await page.viewport(1280, 900, scale=2)
        await page.open(URL)
        await page.until("document.querySelectorAll('.dg-graph .main-svg').length >= 3 && "
                         "document.fonts.status === 'loaded'")
        await asyncio.sleep(1.5)
        look = await page.js(LOOK)
        await page.shot("#backtest", folder / "app.png", pad=24, full_width=True)
        await page.shot("#plan", folder / "app-plan.png", pad=24, full_width=True)
        await page.shot("#one-product", folder / "app-product.png", pad=24, full_width=True)
        await page.viewport(390, 844, scale=3, mobile=True)
        await page.open(URL)
        await page.until("document.querySelectorAll('.dg-graph .main-svg').length >= 3")
        await asyncio.sleep(1.5)
        await page.shot(".dg-hero", folder / "app-phone.png", pad=0, full_width=True)
    return look


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "img"
    folder.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PP_PORT": str(PORT), "MPLBACKEND": "Agg"}
    app = subprocess.Popen([sys.executable, "-m", "ui.app"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, **HIDDEN)
    try:
        wait_for(URL, 180)
        look = asyncio.run(capture(folder))
    finally:
        stop_tree(app)
    (folder / "look.json").write_text(json.dumps(look, indent=2), encoding="utf-8")
    print(json.dumps(look, indent=2))


if __name__ == "__main__":
    main()
