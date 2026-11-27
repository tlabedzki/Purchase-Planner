import pytest

from purchase_planner import data


def test_missing_seed_tells_how_to_get_the_data(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "RAW_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="get_data.py"):
        data.load(seed=12345)


def test_planner_never_reads_the_truth_by_default():
    assert "lost_demand_data" in data.TRUTH_TABLES
    assert "true_lead_time_mean_days" in data.TRUTH_COLUMNS["supplier_data"]
