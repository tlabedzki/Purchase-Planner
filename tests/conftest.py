import pytest

from purchase_planner import backtest, data


@pytest.fixture(scope="session")
def sample():
    """Three suppliers of the shop, 2023-2024 (data/sample/), with the truth for the backtest."""
    return data.load_sample(truth=True)


@pytest.fixture(scope="session")
def setup(sample):
    return backtest.prepare(sample, year=2024)


@pytest.fixture(scope="session")
def results(setup):
    return backtest.run_all(setup)
