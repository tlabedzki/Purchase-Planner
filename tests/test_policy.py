import numpy as np
from scipy import stats

from purchase_planner import policy


def test_quantile_is_poisson_or_negative_binomial():
    mean, level = np.array([4.0, 4.0, 0.0]), np.array([0.9, 0.9, 0.9])
    q = policy.demand_quantile(mean, np.array([4.0, 12.0, 0.0]), level)
    assert q[0] == stats.poisson.ppf(0.9, 4.0)
    assert q[1] > q[0]  # more spread, more stock
    assert q[2] == 0


def test_packs_next_order_day_and_abc():
    assert policy.round_up_to_pack(np.array([0.0, 1.0, 5.0, 6.0]), np.array([6, 6, 6, 6])).tolist() == [0, 6, 6, 6]
    order_days = np.array([[True, False, False, True, False, False, False]])  # Mon, Thu
    assert policy.days_to_next_order(order_days, 0).tolist() == [3]  # Monday -> Thursday
    assert policy.days_to_next_order(order_days, 3).tolist() == [4]  # Thursday -> Monday
    classes = policy.abc_classes(np.array([70.0, 20.0, 6.0, 4.0, 0.0]))
    assert classes.tolist() == ["A", "A", "B", "C", "C"]  # the product that crosses 80% is still A


def test_service_level_falls_with_cost_per_margin(setup):
    planner = policy.Planner(setup.context, None)
    level = planner.service_level(np.full(setup.catalog.size, 10), np.full(setup.catalog.size, 3))
    order = np.argsort(planner.weight)
    assert np.all(np.diff(level[order]) <= 1e-12)
    assert level.max() <= policy.MAX_SERVICE
