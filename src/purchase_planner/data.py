"""
Where the shop data comes from and how it is read.

Every table comes from Data-Generator (tlabedzki/Data-Generator): scripts/get_data.py clones a release, runs it with
the settings below and saves the tables to data/raw/seed-<seed>/. This project generates no data of its own.

Lumo here has 2,000 products and 400,000 order lines over 2021-2024, so most products sell every month, and
stockouts are on: when a product is out of stock the customer cannot buy, and lost_demand_data keeps what was lost.
Seed 42 is the shop the results are reported on; seed 7 is a second shop used only to tune the planner.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "raw"
SAMPLE_DIR = ROOT / "data" / "sample"  # three suppliers, 2023-2024, cut by scripts/make_sample.py (in git, for tests)

DATA_GENERATOR_TAG = "v1.8.0"
SEEDS = [42, 7]
REPORT_SEED = 42
TUNING_SEED = 7

# Settings of Data-Generator overridden for this project, by settings module.
GENERATOR_SETTINGS = {
    "main_settings": {
        "start_year": 2021,
        "end_year": 2024,
        "product_data_rows": 2_000,
        "customer_data_rows": 200_000,
        "order_data_rows": 400_000,
        "data_language": "en",
    },
    "inventory_settings": {"stockouts": True},
}

# Tables this project reads (all columns). lost_demand_data is the truth: only the evaluation reads it.
TABLES = ["product_data", "order_data", "supplier_data", "product_supplier_data", "purchase_order_data",
          "stock_movement_data", "lost_demand_data"]
TRUTH_TABLES = {"lost_demand_data"}
TRUTH_COLUMNS = {"supplier_data": ["true_lead_time_mean_days", "true_lead_time_cv"]}


def seed_dir(seed: int) -> Path:
    return RAW_DIR / f"seed-{seed}"


def load(seed: int = REPORT_SEED, truth: bool = False) -> dict[str, pd.DataFrame]:
    """
    Read the tables of one seed from data/raw/.

    Parameters:
    seed (int): Shop to read (42 for results, 7 for tuning).
    truth (bool): Also read the truth (lost demand, true lead times). The planner never asks for it.

    Returns:
    dict: Table names mapped to DataFrames.
    """
    return read(seed_dir(seed), truth)


def load_sample(truth: bool = False) -> dict[str, pd.DataFrame]:
    """The small sample in data/sample/ (for tests and CI)."""
    return read(SAMPLE_DIR, truth)


def read(folder: Path, truth: bool) -> dict[str, pd.DataFrame]:
    if not folder.exists():
        raise FileNotFoundError(f"No data in {folder}. Run: python scripts/get_data.py")
    tables = {}
    for name in TABLES:
        if name in TRUTH_TABLES and not truth:
            continue
        frame = pd.read_parquet(folder / f"{name}.parquet")
        if not truth:
            frame = frame.drop(columns=TRUTH_COLUMNS.get(name, []))
        tables[name] = frame
    return tables
