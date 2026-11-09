"""Monthly energy summary per plant."""

from __future__ import annotations

import numpy as np
import pandas as pd

from solar_networks.config import TIMEZONE

SUMMARY_COLUMNS = [
    "plant_id",
    "month",
    "pv_yield_kwh",
    "consumption_kwh",
    "grid_feed_in_kwh",
    "grid_import_kwh",
    "self_consumption_kwh",
    "self_consumption_rate_pct",
    "rows",
]

_ENERGY_COLUMNS = [
    "pv_yield_kwh",
    "consumption_kwh",
    "grid_feed_in_kwh",
    "grid_import_kwh",
]


def _sum_or_nan(series: pd.Series) -> float:
    """Sum that stays NaN when every value is missing (pandas would give 0)."""
    return series.sum() if series.notna().any() else np.nan


def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate a tidy ingest frame into one row per plant and month.

    Months are determined in local time (Europe/Bratislava), not UTC, so a
    daily row for 1 October (local midnight = 22:00 UTC on 30 September) is
    counted in October.

    Columns:
        plant_id, month (YYYY-MM), pv_yield_kwh, consumption_kwh,
        grid_feed_in_kwh, grid_import_kwh, self_consumption_kwh,
        self_consumption_rate_pct, rows

    ``self_consumption_kwh`` is PV yield minus grid feed-in. The rate is
    self-consumption divided by PV yield in percent; NaN when yield is zero.
    """
    if df.empty:
        return pd.DataFrame(columns=SUMMARY_COLUMNS)

    data = df.copy()
    local = data["timestamp"].dt.tz_convert(TIMEZONE)
    data["month"] = local.dt.strftime("%Y-%m")

    grouped = data.groupby(["plant_id", "month"], sort=True)
    out = grouped[_ENERGY_COLUMNS].agg(_sum_or_nan)
    out["rows"] = grouped.size()
    out = out.reset_index()

    out["self_consumption_kwh"] = out["pv_yield_kwh"] - out["grid_feed_in_kwh"]
    out["self_consumption_rate_pct"] = np.where(
        out["pv_yield_kwh"] > 0,
        out["self_consumption_kwh"] / out["pv_yield_kwh"] * 100.0,
        np.nan,
    )
    return out[SUMMARY_COLUMNS]
