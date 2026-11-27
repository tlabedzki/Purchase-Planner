import numpy as np
import pandas as pd

from purchase_planner import forecast


def test_poisson_fit_recovers_known_effects():
    days = pd.DataFrame({"month": np.tile(np.arange(1, 13), 40), "weekday": np.tile(np.arange(7), 69)[:480],
                         "event": [""] * 480})
    x = forecast.design(days)
    truth = np.zeros(x.shape[1])
    truth[0], truth[11] = np.log(20), np.log(2.0)  # December doubles
    y = np.exp(x @ truth)  # expected counts: the fit should give the same effects back
    beta = forecast.poisson_fit(x, y, np.zeros(len(y)))
    assert abs(np.exp(beta[11]) - 2.0) < 0.02 and abs(np.exp(beta[0]) - 20) < 0.5


def test_tsb_learns_rate_and_skips_days_out_of_stock():
    state = forecast.TSB.start(2, alpha_p=0.2, alpha_z=0.2)
    season = np.ones(2)
    for day in range(200):
        units = np.array([2.0 if day % 2 == 0 else 0.0, 3.0])
        state.update(units, season, np.array([True, True]))
    assert abs(state.base[0] - 1.0) < 0.15  # sells 2 every second day
    assert abs(state.base[1] - 3.0) < 0.01
    before = state.base.copy()
    state.update(np.array([0.0, 0.0]), season, np.array([False, False]))  # empty shelf: not demand
    assert np.allclose(state.base, before)


def test_wape():
    assert forecast.wape(np.array([10, 10]), np.array([12, 8])) == 0.2
