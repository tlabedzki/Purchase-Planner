"""The app without a browser: the page builds on the sample and every callback returns its views."""
import base64
import io
import os

import pytest
from openpyxl import load_workbook

os.environ["PP_DATA"] = "sample"

from ui import app as ui  # noqa: E402


@pytest.fixture(scope="module")
def prepared():
    ui.prepare.cache_clear()
    return ui.prepare()


def text_of(component) -> str:
    """All text in a Dash component tree."""
    if isinstance(component, str | int | float):
        return str(component)
    if isinstance(component, list | tuple):
        return " ".join(text_of(c) for c in component)
    children = getattr(component, "children", None)
    return text_of(children) if children is not None else ""


def test_page_has_the_three_sections(prepared):
    page = ui.page()
    text = text_of(page)
    for heading in ("2024, replayed", "The plan for the next 30 days", "One product", "Source on GitHub"):
        assert heading in text
    assert "googleapis" not in str(page)


def test_backtest_view_shows_every_policy(prepared):
    results, table, dates, _, _ = prepared
    text = text_of(ui.backtest_view(results, table, dates))
    for label in ("Planner", "Buyer by eye (rebuilt)", "Shop's buyer (data)", "Perfect forecast"):
        assert label in text


def test_supplier_callback_updates_the_plan_and_the_products(prepared):
    _, _, _, planning, month = prepared
    supplier = int(month["supplier_id"].iloc[0])
    view, options, value = ui.update_supplier(str(supplier))
    assert "firm order" in text_of(view)
    assert options and value == options[0]["value"]
    chart = ui.update_product(value)
    assert chart and "Diamonds" in text_of(chart)


def test_download_gives_the_supplier_workbook(prepared):
    _, _, _, _, month = prepared
    supplier = int(month["supplier_id"].iloc[0])
    sent = ui.download(1, str(supplier))
    assert sent["filename"].startswith(f"purchase-plan-{supplier:02d}-") and sent["filename"].endswith(".xlsx")
    book = load_workbook(io.BytesIO(base64.b64decode(sent["content"])))
    assert book["Purchase plan"]["A1"].value.startswith("Purchase plan:")
    assert ui.download(None, str(supplier)) is ui.no_update


def ids_of(component) -> list:
    found = []
    if isinstance(component, list | tuple):
        for child in component:
            found += ids_of(child)
        return found
    if getattr(component, "id", None) is not None:
        found.append(component.id)
    children = getattr(component, "children", None)
    return found + (ids_of(children) if children is not None and not isinstance(children, str) else [])


def test_every_component_id_is_unique(prepared):
    ids = [str(i) for i in ids_of(ui.page())]
    assert len(ids) == len(set(ids)), sorted(ids)
