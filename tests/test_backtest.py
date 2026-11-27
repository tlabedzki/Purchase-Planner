import numpy as np

from purchase_planner import backtest


def test_history_matches_the_tables(setup, sample):
    history = setup.history
    assert (history.stock >= 0).all()
    assert history.sold.sum() == sample["order_data"]["quantity"].sum()
    assert not (history.observed & ~history.active).any()


def test_every_unit_of_demand_is_served_or_lost(setup, results):
    demand = setup.world.demand().sum()
    for name in backtest.POLICIES[1:]:
        result = results[name]
        assert result.served_units + result.lost_units == demand
        assert (result.stock >= 0).all()
        assert result.lost_by_product.sum() == result.lost_units


def test_the_shop_history_is_the_data(setup, results, sample):
    lines = sample["order_data"]
    lost = sample["lost_demand_data"]
    history = results["shop_history"]
    assert history.served_units == lines.loc[lines["order_date"].dt.year == 2024, "quantity"].sum()
    assert history.lost_units == lost.loc[lost["order_date"].dt.year == 2024, "quantity"].sum()


def test_backtest_is_reproducible(setup, results):
    again = backtest.run_all(setup)
    for name in backtest.POLICIES:
        assert again[name].summary() == results[name].summary()
    assert np.array_equal(again["planner"].stock, results["planner"].stock)


def test_oracle_is_a_ceiling(results):
    assert results["oracle"].fill_rate >= results["planner"].fill_rate
