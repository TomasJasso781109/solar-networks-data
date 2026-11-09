import numpy as np
import pandas as pd
import pytest

from solar_networks.ingest.fusionsolar import (
    OUTPUT_COLUMNS,
    FusionSolarFormatError,
    infer_granularity,
    load_export,
)

# Control totals for October 2026, verified against the FusionSolar portal
# (daily and hourly exports agree to 0.01 kWh).
OCT_TOTALS = {
    "pv_yield_kwh": 2174.56,
    "consumption_kwh": 7347.98,
    "grid_import_kwh": 5376.33,
    "grid_feed_in_kwh": 202.91,
}


def _assert_schema(df: pd.DataFrame) -> None:
    assert list(df.columns) == OUTPUT_COLUMNS
    assert str(df["timestamp"].dt.tz) == "UTC"
    assert df["timestamp"].is_monotonic_increasing
    assert not df["timestamp"].duplicated().any()
    assert (df["plant_id"] == "sample-plant-01").all()


def test_daily_export_schema_and_totals(daily_oct):
    df = load_export(daily_oct)
    _assert_schema(df)
    assert len(df) == 31
    assert infer_granularity(df) == "daily"
    for column, expected in OCT_TOTALS.items():
        assert df[column].sum() == pytest.approx(expected, abs=0.01)
    # No battery at this plant -> columns present but empty.
    assert df["battery_charge_kwh"].isna().all()
    assert df["battery_discharge_kwh"].isna().all()


def test_hourly_export_schema_and_totals(hourly_oct):
    df = load_export(hourly_oct)
    _assert_schema(df)
    assert len(df) == 745  # 744 h + the repeated 02:00 at the DST switch
    assert infer_granularity(df) == "hourly"
    for column, expected in OCT_TOTALS.items():
        assert df[column].sum() == pytest.approx(expected, abs=0.01)
    assert df["grid_import_kwh"].max() == pytest.approx(50.01, abs=0.01)


def test_dst_transition_is_unambiguous(hourly_oct):
    df = load_export(hourly_oct)
    local = df["timestamp"].dt.tz_convert("Europe/Bratislava")
    two_am = df[(local.dt.month == 10) & (local.dt.day == 25) & (local.dt.hour == 2)]
    # Both 02:00 DST and 02:00 standard time survive as distinct UTC hours.
    assert len(two_am) == 2
    assert two_am["timestamp"].tolist() == [
        pd.Timestamp("2026-10-25 00:00", tz="UTC"),
        pd.Timestamp("2026-10-25 01:00", tz="UTC"),
    ]
    # Local hours are contiguous in UTC: exactly one hour between every row.
    steps = df["timestamp"].diff().dropna().unique()
    assert list(steps) == [pd.Timedelta(hours=1)]


def test_daily_rows_are_local_midnight(daily_oct):
    df = load_export(daily_oct)
    local = df["timestamp"].dt.tz_convert("Europe/Bratislava")
    assert (local.dt.hour == 0).all()
    assert local.iloc[0].date().isoformat() == "2026-10-01"
    # October 1st local midnight is 22:00 UTC the day before (CEST).
    assert df["timestamp"].iloc[0] == pd.Timestamp("2026-09-30 22:00", tz="UTC")


def test_alternate_header_without_consumption(hourly_nov1):
    df = load_export(hourly_nov1)
    _assert_schema(df)
    assert len(df) == 24
    # This export variant lacks Consumption / Self-consumption -> NaN, not 0.
    assert df["consumption_kwh"].isna().all()
    assert df["pv_yield_kwh"].sum() == pytest.approx(39.56, abs=0.01)
    assert df["grid_import_kwh"].sum() == pytest.approx(175.37, abs=0.01)


def test_total_yield_is_not_used(daily_oct):
    df = load_export(daily_oct)
    # Cumulative Total Yield is ~110 000 kWh; daily PV yield must stay small.
    assert df["pv_yield_kwh"].max() < 200


def test_explicit_plant_id_overrides_filename(daily_oct):
    df = load_export(daily_oct, plant_id="custom-id")
    assert (df["plant_id"] == "custom-id").all()


def test_rejects_non_fusionsolar_sheet(tmp_path):
    bogus = tmp_path / "bogus.xlsx"
    pd.DataFrame({"a": [1, 2], "b": [3, 4]}).to_excel(bogus, index=False)
    with pytest.raises(FusionSolarFormatError):
        load_export(bogus)


def test_blank_and_comma_values(tmp_path):
    rows = [
        ["Plant Report_TEST", None, None],
        ["Statistical Period", "PV Yield (kWh)", "Export (kWh)"],
        ["2026-03-01 10:00:00", "1,5", ""],
        ["2026-03-01 11:00:00", 2, "0.25"],
        [None, None, None],  # trailing empty row
    ]
    path = tmp_path / "test-plant_x.xlsx"
    pd.DataFrame(rows).to_excel(path, index=False, header=False)
    df = load_export(path)
    assert len(df) == 2
    assert df["pv_yield_kwh"].tolist() == [1.5, 2.0]
    assert np.isnan(df["grid_feed_in_kwh"].iloc[0])
    assert df["grid_feed_in_kwh"].iloc[1] == 0.25
    assert (df["plant_id"] == "test-plant").all()
