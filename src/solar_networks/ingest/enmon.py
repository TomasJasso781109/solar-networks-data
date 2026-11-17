"""Parser for Enmon register-reading exports (.xlsx, sheet "Meters").

One row is one register of one meter for the selected period: meter code and
name, serial number, register (OBIS), multiplier, reading and reading time at
the start and at the end of the period, consumption and unit. Headers are
Czech.

Consumption is recomputed as (end reading - start reading) x multiplier, where
an empty multiplier means 1. The multiplier is stored as text in the file. The
value from the file is kept next to the recomputed one and any disagreement is
flagged, never silently corrected.

Reading times differ slightly between meters (23:45, 23:46, 23:59); they are
kept as exported.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import pandas as pd

from solar_networks.config import TIMEZONE

SHEET_NAME = "Meters"

# OBIS register -> quantity
REGISTERS = {
    "1-1.8.0": "import",  # active energy taken (kWh)
    "1-2.8.0": "export",  # active energy delivered (kWh)
    "1-5.8.0": "reactive_q1",  # reactive energy, quadrant I (kVArh)
    "1-8.8.0": "reactive_q4",  # reactive energy, quadrant IV (kVArh)
}

OUTPUT_COLUMNS = [
    "meter_code",
    "meter_name",
    "serial_number",
    "register",
    "quantity",  # import | export | reactive_q1 | reactive_q4 | unknown
    "unit",
    "multiplier",  # 1.0 when the file leaves it empty
    "multiplier_missing",  # True when the file leaves it empty
    "start_reading",
    "start_time",  # UTC
    "end_reading",
    "end_time",  # UTC
    "consumption",  # recomputed: (end - start) x multiplier
    "consumption_reported",  # as stated in the file
    "consumption_mismatch",  # True when the two differ by more than the tolerance
]

# Readings carry three decimals; anything beyond rounding noise is a mismatch.
MISMATCH_TOLERANCE = 0.001

_HEADERS = {
    "kód měřidla": "meter_code",
    "název měřidla": "meter_name",
    "výrobní číslo": "serial_number",
    "číslo registru": "register",
    "násobitel": "multiplier",
    "stav na konci předchozího období": "start_reading",
    "čas odečtu na konci předchozího období": "start_time",
    "stav na konci zvoleného období": "end_reading",
    "čas odečtu na konci zvoleného období": "end_time",
    "spotřeba ve zvoleném období": "consumption_reported",
    "jednotka": "unit",
}


class EnmonFormatError(ValueError):
    """Raised when the file does not look like an Enmon register export."""


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value)) or str(value).strip() == ""


def _norm(value: object) -> str:
    return "" if _is_blank(value) else re.sub(r"\s+", " ", str(value)).strip().lower()


def _text(value: object) -> str | None:
    return None if _is_blank(value) else str(value).strip()


def _to_float(value: object, what: str, row: int) -> float:
    if isinstance(value, bool) or _is_blank(value):
        raise EnmonFormatError(f"Row {row}: {what} is empty or not a number ({value!r})")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return float(text)
    except ValueError as exc:
        raise EnmonFormatError(f"Row {row}: {what} is not a number ({value!r})") from exc


def _to_utc(value: object, what: str, row: int) -> pd.Timestamp:
    if _is_blank(value):
        raise EnmonFormatError(f"Row {row}: {what} is empty")
    try:
        naive = pd.Timestamp(value)
        return naive.tz_localize(TIMEZONE, ambiguous="raise", nonexistent="raise").tz_convert("UTC")
    except Exception as exc:
        raise EnmonFormatError(f"Row {row}: cannot read {what} ({value!r}): {exc}") from exc


def load_registers(path: str | Path) -> pd.DataFrame:
    """Load one Enmon register export into a tidy frame (columns = OUTPUT_COLUMNS).

    One file is one building (main meter, PV meter, tenants' sub-meters). Rows
    keep the order of the file.
    """
    path = Path(path)
    try:
        sheet = pd.read_excel(path, sheet_name=SHEET_NAME, header=None, dtype=object)
    except ValueError as exc:
        raise EnmonFormatError(f"{path.name}: sheet {SHEET_NAME!r} not found") from exc
    if sheet.empty:
        raise EnmonFormatError(f"{path.name}: sheet {SHEET_NAME!r} is empty")

    columns = {}
    for col, cell in enumerate(sheet.iloc[0].tolist()):
        field = _HEADERS.get(_norm(cell))
        if field is not None:
            columns[field] = col
    missing = [label for label, field in _HEADERS.items() if field not in columns]
    if missing:
        raise EnmonFormatError(f"{path.name}: missing columns: {', '.join(missing)}")

    records = []
    for idx in range(1, len(sheet)):
        raw = {field: sheet.iat[idx, col] for field, col in columns.items()}
        if all(_is_blank(v) for v in raw.values()):
            continue
        row = idx + 1  # 1-based row number as shown in Excel
        register = _text(raw["register"])
        if register is None or _text(raw["meter_code"]) is None:
            raise EnmonFormatError(f"Row {row}: meter code or register is empty")
        multiplier_missing = _is_blank(raw["multiplier"])
        multiplier = 1.0 if multiplier_missing else _to_float(raw["multiplier"], "multiplier", row)
        start = _to_float(raw["start_reading"], "start reading", row)
        end = _to_float(raw["end_reading"], "end reading", row)
        reported = _to_float(raw["consumption_reported"], "consumption", row)
        consumption = (end - start) * multiplier
        records.append(
            {
                "meter_code": _text(raw["meter_code"]),
                "meter_name": _text(raw["meter_name"]),
                "serial_number": _text(raw["serial_number"]),
                "register": register,
                "quantity": REGISTERS.get(register, "unknown"),
                "unit": _text(raw["unit"]),
                "multiplier": multiplier,
                "multiplier_missing": multiplier_missing,
                "start_reading": start,
                "start_time": _to_utc(raw["start_time"], "start reading time", row),
                "end_reading": end,
                "end_time": _to_utc(raw["end_time"], "end reading time", row),
                "consumption": consumption,
                "consumption_reported": reported,
                "consumption_mismatch": abs(consumption - reported) > MISMATCH_TOLERANCE,
            }
        )
    return pd.DataFrame.from_records(records, columns=OUTPUT_COLUMNS)


def consumption_mismatches(registers: pd.DataFrame) -> pd.DataFrame:
    """Rows where the recomputed consumption disagrees with the file."""
    return registers[registers["consumption_mismatch"]].reset_index(drop=True)
