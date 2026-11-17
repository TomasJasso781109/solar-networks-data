import pandas as pd
import pytest

from solar_networks.config import TIMEZONE
from solar_networks.ingest.zsdis import (
    OUTPUT_COLUMNS,
    ZsdisFormatError,
    ZsdisProfile,
    expected_timestamps,
    interval_issues,
    load_profile,
)
from solar_networks.model.capacity import monthly_peaks

# Control totals computed from the original (non-anonymized) exports.
ENERGY_2025_KWH = 1_296_429.5
ENERGY_2026_KWH = 956_369.7  # 1.1.-13.10.2026
MAX_2025_KW = 357.2
MAX_2025_AT = pd.Timestamp("2025-05-08 12:45", tz=TIMEZONE)


def _local_day_counts(profile: ZsdisProfile) -> pd.Series:
    local = profile.data["timestamp"].dt.tz_convert(TIMEZONE)
    return local.dt.strftime("%Y-%m-%d").value_counts()


def test_metadata_is_read_from_the_header(zsdis_2025):
    profile = load_profile(zsdis_2025)
    assert profile.eic == "24ZZS0000000000X"
    assert profile.profile_type == "Činný výkon so stratami"
    assert profile.unit == "kW"
    assert profile.period_start == pd.Timestamp("2025-01-01").date()
    assert profile.period_end == pd.Timestamp("2025-12-31").date()


def test_schema(zsdis_2025):
    data = load_profile(zsdis_2025).data
    assert list(data.columns) == OUTPUT_COLUMNS
    assert str(data["timestamp"].dt.tz) == "UTC"
    assert data["timestamp"].is_monotonic_increasing
    assert not data["timestamp"].duplicated().any()
    assert data["value"].notna().all()


def test_control_totals_2025(zsdis_2025):
    profile = load_profile(zsdis_2025)
    assert len(profile.data) == 35_040
    assert profile.energy_kwh == pytest.approx(ENERGY_2025_KWH, abs=0.05)
    peak = profile.data.loc[profile.data["value"].idxmax()]
    assert peak["value"] == pytest.approx(MAX_2025_KW)
    assert peak["timestamp"] == MAX_2025_AT.tz_convert("UTC")


def test_control_totals_2026(zsdis_2026):
    profile = load_profile(zsdis_2026)
    assert len(profile.data) == 27_452
    assert profile.energy_kwh == pytest.approx(ENERGY_2026_KWH, abs=0.05)


def test_dst_days_have_92_and_100_intervals(zsdis_2025, zsdis_2026):
    counts = _local_day_counts(load_profile(zsdis_2025))
    assert counts["2025-03-30"] == 92
    assert counts["2025-10-26"] == 100
    assert (counts.drop(["2025-03-30", "2025-10-26"]) == 96).all()
    assert _local_day_counts(load_profile(zsdis_2026))["2026-03-29"] == 92


def test_repeated_autumn_hour_is_two_distinct_utc_hours(zsdis_2025):
    data = load_profile(zsdis_2025).data
    first = pd.Timestamp("2025-10-26 00:00", tz="UTC")  # 02:00 CEST
    hour = data[(data["timestamp"] >= first) & (data["timestamp"] < first + pd.Timedelta(hours=2))]
    assert len(hour) == 8
    assert hour["timestamp"].diff().dropna().eq(pd.Timedelta(minutes=15)).all()


def test_complete_exports_have_no_interval_issues(zsdis_2025, zsdis_2026):
    assert interval_issues(load_profile(zsdis_2025)).empty
    assert interval_issues(load_profile(zsdis_2026)).empty


def test_corrected_values_are_flagged(zsdis_2025):
    data = load_profile(zsdis_2025).data
    corrected = data[data["corrected"]]
    assert len(corrected) == 192
    assert set(corrected["status"]) == {"Opravená - nameraná"}
    days = corrected["timestamp"].dt.tz_convert(TIMEZONE).dt.strftime("%Y-%m-%d").unique()
    assert sorted(days) == ["2025-06-27", "2025-07-23"]
    assert set(data.loc[~data["corrected"], "status"]) == {"Nameraná"}


def test_interval_issues_reports_missing_and_duplicate(zsdis_2026):
    profile = load_profile(zsdis_2026)
    data = profile.data
    missing_ts, dup_ts = data["timestamp"].iloc[100], data["timestamp"].iloc[200]
    broken = pd.concat([data.drop(index=100), data.iloc[[200]]], ignore_index=True)
    issues = interval_issues(
        ZsdisProfile(
            profile.eic, profile.profile_type, profile.unit,
            profile.period_start, profile.period_end, broken,
        )
    )
    assert issues.to_dict("records") == [
        {"timestamp": missing_ts, "issue": "missing"},
        {"timestamp": dup_ts, "issue": "duplicate"},
    ]


def test_expected_timestamps_follow_local_days():
    assert len(expected_timestamps(pd.Timestamp("2025-03-30").date(), pd.Timestamp("2025-03-30").date())) == 92
    assert len(expected_timestamps(pd.Timestamp("2025-10-26").date(), pd.Timestamp("2025-10-26").date())) == 100


def test_energy_is_refused_for_non_kw_profiles(zsdis_2026):
    profile = load_profile(zsdis_2026)
    other = ZsdisProfile(
        profile.eic, "Jalový výkon", "kVAr", profile.period_start, profile.period_end, profile.data
    )
    with pytest.raises(ValueError):
        other.energy_kwh


def test_profile_feeds_existing_capacity_model(zsdis_2025):
    data = load_profile(zsdis_2025).data.rename(columns={"value": "import_kw"})
    peaks = monthly_peaks(data).set_index("month")
    assert len(peaks) == 12
    assert peaks.loc["2025-05", "max_kw"] == pytest.approx(MAX_2025_KW)
    assert peaks.loc["2025-10", "intervals"] == 31 * 96 + 4


def test_wrong_file_is_rejected(enmon_oct, tmp_path):
    with pytest.raises(ZsdisFormatError):
        load_profile(enmon_oct)
    empty = tmp_path / "empty.xlsx"
    pd.DataFrame({"a": [1]}).to_excel(empty, sheet_name="Namerané hodnoty", index=False)
    with pytest.raises(ZsdisFormatError):
        load_profile(empty)
