"""
Get the shop data: clone a release of Data-Generator, run it with this project's settings and save the tables the
planner reads to data/raw/seed-<seed>/. The generator code is not changed; its settings are overridden in the process
that runs it (as the Data-Generator app does).

    python scripts/get_data.py                      # seeds 42 and 7, release in purchase_planner.data
    python scripts/get_data.py --seed 42            # one seed
    python scripts/get_data.py --source ../Data-Generator-1.8.0 --tag feat/1.8.0-inventory --refresh   # local branch
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from purchase_planner.data import DATA_GENERATOR_TAG, GENERATOR_SETTINGS, RAW_DIR, SEEDS, TABLES, seed_dir  # noqa: E402

GITHUB_URL = "https://github.com/tlabedzki/Data-Generator.git"
CACHE_DIR = ROOT / ".cache"

# Runs inside the Data-Generator clone: override the settings, generate, save the tables this project reads.
RUN_SCRIPT = """
import importlib, json, sys
from pathlib import Path
overrides, tables, out = json.loads(sys.argv[1]), json.loads(sys.argv[2]), Path(sys.argv[3])
for module_name, values in overrides.items():
    module = importlib.import_module(f"settings.{module_name}")
    for name, value in values.items():
        setattr(module, name, value)
import settings.main_settings as s
s.generated_files = list(tables)
from func import generator, log
log.configure()
data = generator.run_generation_pipeline()
out.mkdir(parents=True, exist_ok=True)
for table in tables:
    data[table].to_parquet(out / f"{table}.parquet", index=False)
"""


def run(command: list[str], cwd: Path | None = None) -> str:
    env = {**os.environ, "MPLBACKEND": "Agg", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8")
    if result.returncode != 0:
        raise SystemExit(f"Command failed: {' '.join(command[:3])} ...\n{result.stderr[-2000:]}")
    return result.stdout


def clone(source: str, tag: str, refresh: bool) -> Path:
    target = CACHE_DIR / f"data-generator-{re.sub(r'[^A-Za-z0-9._-]', '-', tag)}"
    if refresh or not (target / "main.py").exists():
        shutil.rmtree(target, ignore_errors=True)
        CACHE_DIR.mkdir(exist_ok=True)
        print(f"Cloning Data-Generator {tag} from {source}")
        run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1", "--branch", tag,
             str(source), str(target)])
    return target


def generate(generator_dir: Path, seed: int, source: str, tag: str) -> Path:
    target = seed_dir(seed)
    overrides = json.loads(json.dumps(GENERATOR_SETTINGS))
    overrides["main_settings"]["random_state"] = seed
    lines = overrides["main_settings"]["order_data_rows"]
    print(f"Generating Lumo with seed {seed} ({lines:,} order lines, stockouts on), about half a minute")
    run([sys.executable, "-c", RUN_SCRIPT, json.dumps(overrides), json.dumps(TABLES), str(target)], cwd=generator_dir)
    commit = run(["git", "rev-parse", "HEAD"], cwd=generator_dir).strip()
    source_info = {"repository": str(source), "tag": tag, "commit": commit, "settings": overrides}
    (target / "source.json").write_text(json.dumps(source_info, indent=2), encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, action="append", help=f"seed to generate (default: {SEEDS})")
    parser.add_argument("--tag", default=DATA_GENERATOR_TAG, help="Data-Generator release tag or branch")
    parser.add_argument("--source", default=GITHUB_URL, help="git URL or local path of Data-Generator")
    parser.add_argument("--refresh", action="store_true", help="clone again (for a moving branch)")
    args = parser.parse_args()

    generator_dir = clone(args.source, args.tag, args.refresh)
    for seed in args.seed or SEEDS:
        target = generate(generator_dir, seed, args.source, args.tag)
        print(f"Saved {len(TABLES)} tables to {target.relative_to(ROOT)}")
    print(f"Data ready in {RAW_DIR.relative_to(ROOT)}. Next: python main.py")


if __name__ == "__main__":
    main()
