import openpyxl
import pandas as pd
import pytest

from solar_networks.ingest.enmon import (
    OUTPUT_COLUMNS,
    EnmonFormatError,
    consumption_mismatches,
    load_registers,
)


def _row(df: pd.DataFrame, code: str, register: str) -> pd.Series:
    match = df[(df["meter_code"] == code) & (df["register"] == register)]
    assert len(match) == 1
    return match.iloc[0]


def test_schema(enmon_oct):
    df = load_registers(enmon_oct)
    assert list(df.columns) == OUTPUT_COLUMNS
    assert len(df) == 45
    assert df["meter_code"].nunique() == 12
    assert str(df["start_time"].dt.tz) == "UTC"
    assert str(df["end_time"].dt.tz) == "UTC"


def test_registers_are_mapped_to_quantities_and_units(enmon_oct):
    df = load_registers(enmon_oct)
    pairs = set(zip(df["register"], df["quantity"], df["unit"]))
    assert pairs == {
        ("1-1.8.0", "import", "kWh"),
        ("1-2.8.0", "export", "kWh"),
        ("1-5.8.0", "reactive_q1", "kVArh"),
        ("1-8.8.0", "reactive_q4", "kVArh"),
    }


def test_multiplier_text_and_empty(enmon_oct):
    df = load_registers(enmon_oct)
    main = _row(df, "EE-01", "1-1.8.0")
    assert main["multiplier"] == pytest.approx(8.32)
    assert not main["multiplier_missing"]
    assert _row(df, "EE-01", "1-2.8.0")["multiplier"] == pytest.approx(8.0)
    assert _row(df, "EE-03", "1-1.8.0")["multiplier"] == pytest.approx(0.125)
    tenant = _row(df, "EE-05", "1-1.8.0")
    assert tenant["multiplier"] == 1.0
    assert tenant["multiplier_missing"]


def test_consumption_is_recomputed(enmon_oct):
    df = load_registers(enmon_oct)
    # (284861 - 282830) x 8.32
    assert _row(df, "EE-01", "1-1.8.0")["consumption"] == pytest.approx(16_897.92)
    # (758277.963 - 743180.404) x 0.125
    assert _row(df, "EE-03", "1-1.8.0")["consumption"] == pytest.approx(1_887.194875)
    # PV meter, no multiplier: 100416.45 - 97342.84
    assert _row(df, "EE-02", "1-1.8.0")["consumption"] == pytest.approx(3_073.61)


def test_sample_has_no_mismatch_with_reported_consumption(enmon_oct):
    df = load_registers(enmon_oct)
    assert not df["consumption_mismatch"].any()
    assert consumption_mismatches(df).empty


def test_reading_times_are_kept_as_exported(enmon_oct):
    df = load_registers(enmon_oct)
    local_end = df["end_time"].dt.tz_convert("Europe/Bratislava").dt.strftime("%Y-%m-%d %H:%M")
    assert set(local_end) == {"2026-10-31 23:45", "2026-10-31 23:46", "2026-10-31 23:59"}
    # 30 Sep is summer time (UTC+2), 31 Oct is winter time (UTC+1).
    main = _row(df, "EE-01", "1-1.8.0")
    assert main["start_time"] == pd.Timestamp("2026-09-30 21:45", tz="UTC")
    assert main["end_time"] == pd.Timestamp("2026-10-31 22:45", tz="UTC")


def test_pv_meter_without_serial_number(enmon_oct):
    pv = _row(load_registers(enmon_oct), "EE-02", "1-1.8.0")
    assert pv["meter_name"] == "FVE"
    assert pd.isna(pv["serial_number"])


def test_mismatch_is_flagged_not_corrected(enmon_oct, tmp_path):
    wb = openpyxl.load_workbook(enmon_oct)
    ws = wb["Meters"]
    reported = ws["J2"].value
    ws["J2"] = reported + 10
    edited = tmp_path / "edited.xlsx"
    wb.save(edited)
    bad = consumption_mismatches(load_registers(edited))
    assert len(bad) == 1
    assert bad.iloc[0]["consumption_reported"] == pytest.approx(reported + 10)
    assert bad.iloc[0]["consumption"] == pytest.approx(reported)


def test_wrong_file_is_rejected(zsdis_2026, tmp_path):
    with pytest.raises(EnmonFormatError):
        load_registers(zsdis_2026)
    other = tmp_path / "other.xlsx"
    pd.DataFrame({"a": [1]}).to_excel(other, sheet_name="Meters", index=False)
    with pytest.raises(EnmonFormatError):
        load_registers(other)


def test_non_numeric_reading_is_an_error(enmon_oct, tmp_path):
    wb = openpyxl.load_workbook(enmon_oct)
    wb["Meters"]["H2"] = "n/a"
    edited = tmp_path / "edited.xlsx"
    wb.save(edited)
    with pytest.raises(EnmonFormatError, match="Row 2"):
        load_registers(edited)
