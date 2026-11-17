"""Parser for ZSDIS (ZSD distribution portal) interval-profile exports (.xls).

Sheet "Namerané hodnoty" holds a metadata block (labels in one column, values
in the next) followed by a table ``Dátum | Čas od | Hodnota profilu | Status``.
The header row is located by text, never by a fixed row number.

Values are the mean power of each 15-minute interval in the unit given in the
metadata (kW for active power), so energy in kWh = value / 4.

Daylight-saving time: the spring day has 92 intervals, the autumn day 100.
The repeated autumn hour is exported with one extra second (02:00:01,
02:15:01, ...) and interleaved with the first pass (02:00:00, 02:00:01,
02:15:00, ...). The rows with the extra second are taken as the second pass
(standard time). [PREDPOKLAD] The export itself does not say which pass is
which; daily and longer totals do not depend on it.

The sheet "Nameraná hodinová práca" is deliberately not read: it drops one
hour on the autumn switch-over. Hourly values must be derived from the
15-minute data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from solar_networks.config import TIMEZONE

SHEET_NAME = "Namerané hodnoty"
INTERVAL = pd.Timedelta(minutes=15)

OUTPUT_COLUMNS = [
    "eic",
    "profile_type",
    "unit",
    "timestamp",  # start of the 15-minute interval, UTC
    "value",  # mean power over the interval, in `unit`
    "status",  # as exported, e.g. "Nameraná", "Opravená - nameraná"
    "corrected",  # True when the status is anything but a plain measured value
]

STATUS_MEASURED = "Nameraná"

_META_LABELS = {
    "eic": "eic",
    "obdobie od-do": "period",
    "typ profilu": "profile_type",
    "jednotka": "unit",
}
_TABLE_HEADERS = {
    "dátum": "date",
    "čas od": "time",
    "hodnota profilu": "value",
    "status": "status",
}
_PERIOD = re.compile(r"(\d{2}\.\d{2}\.\d{4})\s*-\s*(\d{2}\.\d{2}\.\d{4})")
_TIME = re.compile(r"^(\d{2}):(\d{2}):(\d{2})$")


class ZsdisFormatError(ValueError):
    """Raised when the file does not look like a ZSDIS profile export."""


@dataclass(frozen=True)
class ZsdisProfile:
    """One parsed export: metadata plus the tidy interval table."""

    eic: str
    profile_type: str
    unit: str
    period_start: date  # first local day covered, as stated in the header
    period_end: date  # last local day covered (inclusive)
    data: pd.DataFrame  # columns = OUTPUT_COLUMNS

    @property
    def energy_kwh(self) -> float:
        """Total energy; only meaningful for power profiles in kW."""
        if self.unit.lower() != "kw":
            raise ValueError(f"Energy is undefined for unit {self.unit!r}")
        return float(self.data["value"].sum() / 4.0)


def _norm(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().rstrip(":").strip().lower()


def _text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _find_table_header(sheet: pd.DataFrame) -> tuple[int, dict[str, int]]:
    """Return (row index, {field: column index}) of the interval table header."""
    for idx in range(len(sheet)):
        cells = {_norm(v): col for col, v in enumerate(sheet.iloc[idx].tolist()) if _norm(v)}
        if all(label in cells for label in _TABLE_HEADERS):
            return idx, {field: cells[label] for label, field in _TABLE_HEADERS.items()}
    raise ZsdisFormatError(
        "Could not find the table header 'Dátum | Čas od | Hodnota profilu | Status'."
    )


def _read_metadata(sheet: pd.DataFrame, header_row: int) -> dict[str, str]:
    meta: dict[str, str] = {}
    for idx in range(header_row):
        row = sheet.iloc[idx].tolist()
        for col, cell in enumerate(row):
            field = _META_LABELS.get(_norm(cell))
            if field is None:
                continue
            following = [_text(v) for v in row[col + 1 :] if _text(v)]
            if following:
                meta[field] = following[0]
    missing = [f for f in _META_LABELS.values() if f not in meta]
    if missing:
        raise ZsdisFormatError(f"Missing metadata in the export header: {', '.join(missing)}")
    return meta


def _to_float(value: object) -> float:
    if isinstance(value, bool):
        raise ZsdisFormatError(f"Unexpected profile value: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    text = _text(value).replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError as exc:
        raise ZsdisFormatError(f"Profile value is not a number: {value!r}") from exc


def _parse_timestamps(dates: list[object], times: list[object]) -> pd.DatetimeIndex:
    """Local 'DD.MM.YYYY' + 'HH:MM:SS' -> UTC.

    A time with seconds == 01 marks the second pass through the repeated hour
    on the autumn switch-over (standard time); every other row on an ambiguous
    wall-clock time is the first pass (daylight-saving time).
    """
    naive: list[datetime] = []
    is_dst: list[bool] = []
    for row, (d, t) in enumerate(zip(dates, times, strict=True)):
        match = _TIME.match(_text(t))
        if match is None:
            raise ZsdisFormatError(f"Unexpected time {t!r} in data row {row + 1}")
        hour, minute, second = (int(g) for g in match.groups())
        if second not in (0, 1):
            raise ZsdisFormatError(f"Unexpected seconds in time {t!r} in data row {row + 1}")
        try:
            day = datetime.strptime(_text(d), "%d.%m.%Y")
        except ValueError as exc:
            raise ZsdisFormatError(f"Unexpected date {d!r} in data row {row + 1}") from exc
        naive.append(day.replace(hour=hour, minute=minute))
        is_dst.append(second == 0)
    index = pd.DatetimeIndex(naive)
    try:
        localized = index.tz_localize(TIMEZONE, ambiguous=is_dst, nonexistent="raise")
    except Exception as exc:  # nonexistent wall-clock time on the spring switch-over
        raise ZsdisFormatError(f"Invalid local time in the export: {exc}") from exc
    return localized.tz_convert("UTC")


def load_profile(path: str | Path) -> ZsdisProfile:
    """Load one ZSDIS interval-profile export.

    Values are returned exactly as exported: nothing is filled in, dropped or
    de-duplicated. Rows are ordered chronologically (the export interleaves
    the repeated autumn hour). Use :func:`interval_issues` to list gaps and
    duplicates.
    """
    path = Path(path)
    try:
        sheet = pd.read_excel(path, sheet_name=SHEET_NAME, header=None, dtype=object)
    except ValueError as exc:
        raise ZsdisFormatError(f"{path.name}: sheet {SHEET_NAME!r} not found") from exc

    header_row, cols = _find_table_header(sheet)
    meta = _read_metadata(sheet, header_row)
    period = _PERIOD.search(meta["period"])
    if period is None:
        raise ZsdisFormatError(f"Cannot read the period from {meta['period']!r}")
    period_start = datetime.strptime(period.group(1), "%d.%m.%Y").date()
    period_end = datetime.strptime(period.group(2), "%d.%m.%Y").date()

    body = sheet.iloc[header_row + 1 :]
    body = body[body[cols["date"]].map(_text) != ""]
    timestamps = _parse_timestamps(body[cols["date"]].tolist(), body[cols["time"]].tolist())
    status = [_text(v) for v in body[cols["status"]].tolist()]
    data = pd.DataFrame(
        {
            "eic": meta["eic"],
            "profile_type": meta["profile_type"],
            "unit": meta["unit"],
            "timestamp": timestamps,
            "value": [_to_float(v) for v in body[cols["value"]].tolist()],
            "status": status,
            "corrected": [s != STATUS_MEASURED for s in status],
        },
        columns=OUTPUT_COLUMNS,
    )
    data = data.sort_values("timestamp", kind="stable").reset_index(drop=True)
    return ZsdisProfile(
        eic=meta["eic"],
        profile_type=meta["profile_type"],
        unit=meta["unit"],
        period_start=period_start,
        period_end=period_end,
        data=data,
    )


def expected_timestamps(period_start: date, period_end: date) -> pd.DatetimeIndex:
    """Every 15-minute interval start (UTC) of the local days start..end inclusive."""
    start = pd.Timestamp(period_start).tz_localize(TIMEZONE)
    end = (pd.Timestamp(period_end) + pd.Timedelta(days=1)).tz_localize(TIMEZONE)
    return pd.date_range(
        start.tz_convert("UTC"), end.tz_convert("UTC"), freq=INTERVAL, inclusive="left"
    )


def interval_issues(profile: ZsdisProfile) -> pd.DataFrame:
    """List missing and duplicated intervals against the period in the header.

    Returns columns ``timestamp`` (UTC) and ``issue`` ("missing" | "duplicate" |
    "outside_period"). An empty frame means the export is complete.
    """
    expected = expected_timestamps(profile.period_start, profile.period_end)
    actual = profile.data["timestamp"]
    rows = [(ts, "missing") for ts in expected.difference(pd.DatetimeIndex(actual))]
    rows += [(ts, "duplicate") for ts in actual[actual.duplicated()]]
    rows += [(ts, "outside_period") for ts in actual[~actual.isin(expected)]]
    out = pd.DataFrame(rows, columns=["timestamp", "issue"])
    return out.sort_values(["timestamp", "issue"]).reset_index(drop=True)
