import numpy as np
import pandas as pd
import pytest

from solar_networks.ingest.fusionsolar import load_export
from solar_networks.model.summary import SUMMARY_COLUMNS, monthly_summary


def test_october_summary_matches_control_totals(hourly_oct):
    summary = monthly_summary(load_export(hourly_oct))
    assert list(summary.columns) == SUMMARY_COLUMNS
    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["plant_id"] == "sample-plant-01"
    assert row["month"] == "2026-10"
    assert row["rows"] == 745
    assert row["pv_yield_kwh"] == pytest.approx(2174.56, abs=0.01)
    assert row["consumption_kwh"] == pytest.approx(7347.98, abs=0.01)
    assert row["grid_import_kwh"] == pytest.approx(5376.33, abs=0.01)
    assert row["grid_feed_in_kwh"] == pytest.approx(202.91, abs=0.01)
    assert row["self_consumption_kwh"] == pytest.approx(1971.65, abs=0.01)
    assert row["self_consumption_rate_pct"] == pytest.approx(90.67, abs=0.01)


def test_daily_and_hourly_exports_agree(daily_oct, hourly_oct):
    daily = monthly_summary(load_export(daily_oct)).drop(columns="rows")
    hourly = monthly_summary(load_export(hourly_oct)).drop(columns="rows")
    pd.testing.assert_frame_equal(daily, hourly, check_exact=False, atol=0.01)


def test_month_is_assigned_in_local_time(daily_oct):
    # Local midnight on 1 Oct is 22:00 UTC on 30 Sep; it must land in 2026-10.
    summary = monthly_summary(load_export(daily_oct))
    assert summary["month"].tolist() == ["2026-10"]


def test_missing_consumption_stays_nan(hourly_nov1):
    summary = monthly_summary(load_export(hourly_nov1))
    assert np.isnan(summary.loc[0, "consumption_kwh"])
    assert summary.loc[0, "pv_yield_kwh"] == pytest.approx(39.56, abs=0.01)


def test_multiple_plants_and_months():
    ts = pd.to_datetime(
        ["2026-01-15 10:00", "2026-02-15 10:00", "2026-01-15 10:00"], utc=True
    )
    df = pd.DataFrame(
        {
            "plant_id": ["a", "a", "b"],
            "timestamp": ts,
            "pv_yield_kwh": [10.0, 20.0, 0.0],
            "consumption_kwh": [8.0, 25.0, 5.0],
            "grid_feed_in_kwh": [4.0, 0.0, 0.0],
            "grid_import_kwh": [2.0, 5.0, 5.0],
            "battery_charge_kwh": [np.nan] * 3,
            "battery_discharge_kwh": [np.nan] * 3,
        }
    )
    summary = monthly_summary(df).set_index(["plant_id", "month"])
    assert summary.loc[("a", "2026-01"), "self_consumption_kwh"] == 6.0
    assert summary.loc[("a", "2026-01"), "self_consumption_rate_pct"] == 60.0
    assert summary.loc[("a", "2026-02"), "self_consumption_rate_pct"] == 100.0
    # Zero yield -> rate undefined, not a division error.
    assert np.isnan(summary.loc[("b", "2026-01"), "self_consumption_rate_pct"])


def test_empty_input():
    summary = monthly_summary(pd.DataFrame(columns=["plant_id", "timestamp"]))
    assert summary.empty
    assert list(summary.columns) == SUMMARY_COLUMNS
