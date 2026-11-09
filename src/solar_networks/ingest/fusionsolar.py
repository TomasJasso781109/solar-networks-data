"""Parser for FusionSolar "Plant Report" XLSX exports.

Handles the export variants seen so far:

* daily export (one row per day, 24 columns, includes cumulative Total Yield)
* hourly export (one row per hour, 13-15 columns, header spelling varies)
* timestamps with a trailing `` DST`` marker during summer time; without the
  marker during standard time. The marker is what makes the repeated 02:00
  hour on the autumn switch-over unambiguous, so it is used, not ignored.

Output is a tidy, UTC-indexed frame with fixed column names; columns missing
from an export are present but NaN (never invented).
"""

from __future__ import annotations

import re
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from solar_networks.config import TIMEZONE, plant_id_from_filename

OUTPUT_COLUMNS = [
    "plant_id",
    "timestamp",
    "pv_yield_kwh",
    "consumption_kwh",
    "grid_feed_in_kwh",
    "grid_import_kwh",
    "battery_charge_kwh",
    "battery_discharge_kwh",
]

# Normalized header prefix -> output column. Headers are normalized with
# `_normalize_header` before matching, so spacing/case/unit spelling
# differences ("kWh/㎡" vs "kWh/m²", " Inverter Yield", "Revenue(€)") don't
# matter. Matching is on the *start* of the header so "PV Yield (kWh)" and
# "PV Yield(kWh)" both resolve. "Total Yield" (cumulative since
# commissioning) and "Inverter Yield" are deliberately not mapped.
_HEADER_MAP = {
    "pv yield": "pv_yield_kwh",
    "consumption": "consumption_kwh",
    "export": "grid_feed_in_kwh",
    "import": "grid_import_kwh",
    "charge": "battery_charge_kwh",
    "discharge": "battery_discharge_kwh",
}

_TIME_HEADER = "statistical period"
_DST_SUFFIX = re.compile(r"\s*DST\s*$", re.IGNORECASE)


class FusionSolarFormatError(ValueError):
    """Raised when the sheet does not look like a FusionSolar plant report."""


def _normalize_header(value: object) -> str:
    text = "" if value is None else str(value)
    text = text.strip().lower()
    text = re.sub(r"\s+", " ", text)
    return text


def _to_float(value: object) -> float:
    """FusionSolar exports blanks as '' and numbers as int/float/str."""
    if value is None:
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    text = str(value).strip().replace("\xa0", "").replace(" ", "")
    if text == "":
        return np.nan
    # Slovak locale exports may use a decimal comma.
    text = text.replace(",", ".")
    return float(text)


def _parse_timestamps(raw: pd.Series) -> pd.Series:
    """Convert 'YYYY-MM-DD[ HH:MM:SS][ DST]' strings to UTC timestamps.

    Hours during daylight-saving time carry a ' DST' suffix; the suffix is
    used to disambiguate the repeated hour at the autumn transition.
    Daily rows (date only) are interpreted as local midnight.
    """
    text = raw.astype(str).str.strip()
    is_dst = text.str.contains(_DST_SUFFIX)
    cleaned = text.str.replace(_DST_SUFFIX, "", regex=True)
    naive = pd.to_datetime(cleaned, format="mixed", errors="raise")
    tz = ZoneInfo(TIMEZONE)
    localized = pd.Series(
        [
            ts.tz_localize(tz, ambiguous=bool(dst))
            for ts, dst in zip(naive, is_dst, strict=True)
        ],
        index=raw.index,
    )
    return localized.dt.tz_convert("UTC")


def _find_header_row(sheet: pd.DataFrame) -> int:
    for idx in range(min(len(sheet), 10)):
        first = _normalize_header(sheet.iat[idx, 0])
        if first.startswith(_TIME_HEADER):
            return idx
    raise FusionSolarFormatError(
        "Could not find a 'Statistical Period' header in the first 10 rows."
    )


def load_export(path: str | Path, plant_id: str | None = None) -> pd.DataFrame:
    """Load one FusionSolar plant-report XLSX export.

    Parameters
    ----------
    path:
        Path to the ``.xlsx`` file. Only the first sheet is read.
    plant_id:
        Identifier of the plant. Defaults to the filename prefix before the
        first underscore (``sample-plant-01_hourly_2026-10.xlsx`` ->
        ``sample-plant-01``).

    Returns
    -------
    DataFrame with columns ``plant_id, timestamp (UTC), pv_yield_kwh,
    consumption_kwh, grid_feed_in_kwh, grid_import_kwh, battery_charge_kwh,
    battery_discharge_kwh``, sorted by timestamp. Values missing in the export
    are NaN.
    """
    path = Path(path)
    if plant_id is None:
        plant_id = plant_id_from_filename(path.name)

    sheet = pd.read_excel(path, sheet_name=0, header=None, dtype=object)
    header_idx = _find_header_row(sheet)
    headers = [_normalize_header(h) for h in sheet.iloc[header_idx]]
    body = sheet.iloc[header_idx + 1 :].reset_index(drop=True)
    body.columns = headers

    # Drop fully empty rows and anything without a timestamp (summary rows,
    # trailing notes).
    time_col = next(h for h in headers if h.startswith(_TIME_HEADER))
    body = body[body[time_col].notna() & (body[time_col].astype(str).str.strip() != "")]
    body = body.reset_index(drop=True)

    out = pd.DataFrame({"plant_id": plant_id, "timestamp": _parse_timestamps(body[time_col])})

    for prefix, column in _HEADER_MAP.items():
        matches = [h for h in headers if h.startswith(prefix)]
        if len(matches) > 1:
            raise FusionSolarFormatError(
                f"Ambiguous header match for '{prefix}': {matches}"
            )
        if matches:
            out[column] = body[matches[0]].map(_to_float).astype(float)
        else:
            out[column] = np.nan

    out = out[OUTPUT_COLUMNS].sort_values("timestamp").reset_index(drop=True)

    duplicates = out["timestamp"].duplicated()
    if duplicates.any():
        raise FusionSolarFormatError(
            f"Duplicate timestamps after UTC conversion in {path.name}: "
            f"{out.loc[duplicates, 'timestamp'].tolist()[:5]}"
        )
    return out


def infer_granularity(df: pd.DataFrame) -> str:
    """Return 'hourly', 'daily' or 'unknown' from the timestamp spacing."""
    if len(df) < 2:
        return "unknown"
    step = df["timestamp"].diff().dropna().mode().iloc[0]
    if step == pd.Timedelta(hours=1):
        return "hourly"
    if step == pd.Timedelta(days=1):
        return "daily"
    return "unknown"
