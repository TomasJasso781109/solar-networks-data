"""Reserved-capacity (RK) analysis from quarter-hour load profiles.

Input is a tidy frame with ``timestamp`` (UTC) and ``import_kw`` – the mean
active power of each 15-minute interval as metered by the DSO (ZSD). On NN
with sadzba C2-X3 the DSO bills the main breaker in amperes; kW values on the
invoice are derived with P = √3·Uz·I·cosφ, so scenarios are expressed in both
units and the fee is always computed from amperes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from solar_networks.config import TIMEZONE, SupplyPoint


# --------------------------------------------------------------------------
# Monthly statistics
# --------------------------------------------------------------------------
def monthly_peaks(profile: pd.DataFrame) -> pd.DataFrame:
    """Per local month: days covered, max kW, time of max, mean, P99, P95."""
    if profile.empty:
        return pd.DataFrame(
            columns=["month", "days", "max_kw", "max_at", "mean_kw", "p99_kw", "p95_kw", "intervals"]
        )
    local = profile["timestamp"].dt.tz_convert(TIMEZONE)
    data = profile.assign(month=local.dt.strftime("%Y-%m"), day=local.dt.strftime("%Y-%m-%d"), local=local)
    rows = []
    for month, g in data.groupby("month", sort=True):
        idx = g["import_kw"].idxmax()
        rows.append(
            {
                "month": month,
                "days": g["day"].nunique(),
                "max_kw": float(g["import_kw"].max()),
                "max_at": g.loc[idx, "local"].tz_localize(None),
                "mean_kw": float(g["import_kw"].mean()),
                "p99_kw": float(g["import_kw"].quantile(0.99)),
                "p95_kw": float(g["import_kw"].quantile(0.95)),
                "intervals": int(len(g)),
            }
        )
    return pd.DataFrame(rows)


def overrun_penalty_eur(profile: pd.DataFrame, rk_kw: float, penalty_eur_kw: float) -> pd.DataFrame:
    """Monthly penalty the DSO would bill for exceeding ``rk_kw``.

    ZSD evaluates the highest quarter-hour value per month; the penalty is
    (max − RK) × rate for the months where max > RK.
    """
    peaks = monthly_peaks(profile)
    peaks["overrun_kw"] = (peaks["max_kw"] - rk_kw).clip(lower=0.0)
    peaks["penalty_eur"] = peaks["overrun_kw"] * penalty_eur_kw
    return peaks[["month", "max_kw", "overrun_kw", "penalty_eur"]]


# --------------------------------------------------------------------------
# Scenarios
# --------------------------------------------------------------------------
@dataclass
class CapacityScenario:
    name: str
    description: str
    target_kw: float
    target_a: float
    monthly_fee_eur: float
    annual_fee_eur: float
    annual_saving_eur: float  # vs current contracted RK
    months_exceeded: int  # months in the sample where max > target
    expected_penalty_eur: float  # penalties over the sample period
    annual_net_saving_eur: float  # saving − penalties scaled to 12 months
    recommended: bool = False
    feasible: bool = True
    note: str = ""


@dataclass
class CapacityAnalysis:
    supply_point: SupplyPoint
    period_start: pd.Timestamp
    period_end: pd.Timestamp
    days: int
    peaks: pd.DataFrame
    overall_max_kw: float
    overall_max_at: pd.Timestamp
    p99_kw: float
    utilisation_pct: float  # overall max / RK
    current_monthly_fee_eur: float
    current_annual_fee_eur: float
    current_penalty_eur: float  # penalties in the sample at current RK
    scenarios: list[CapacityScenario]

    @property
    def recommended(self) -> CapacityScenario | None:
        return next((s for s in self.scenarios if s.recommended), None)


def _ceil_amps(amps: float, step: float = 1.0) -> float:
    return float(np.ceil(amps / step) * step)


def analyse_capacity(
    profile: pd.DataFrame,
    supply_point: SupplyPoint,
    headroom: float = 0.05,
    extra_targets_kw: dict[str, float] | None = None,
) -> CapacityAnalysis:
    """Evaluate the current RK against the measured profile and propose targets.

    Scenarios (all expressed as whole amperes, fee = phases × A × rate):
      * ``súčasný stav`` – contracted RK as is
      * ``max + rezerva`` – measured maximum plus ``headroom`` (default 5 %)
      * ``P99`` – 99th percentile of quarter-hours (accepts rare overruns, cost
        of the penalties is netted against the saving)
      * ``minimum`` – 50 % MRK floor from the price list
      * any ``extra_targets_kw`` supplied by the caller (e.g. after BESS peak
        shaving).
    The recommended scenario is the cheapest one with a positive net saving
    whose target is feasible (≥ minimum RK) and whose penalties, if any, are
    smaller than the saving.
    """
    if profile.empty:
        raise ValueError("Empty load profile")
    tariff = supply_point.distribution
    peaks = monthly_peaks(profile)

    overall_idx = profile["import_kw"].idxmax()
    overall_max = float(profile.loc[overall_idx, "import_kw"])
    overall_at = profile.loc[overall_idx, "timestamp"].tz_convert(TIMEZONE).tz_localize(None)
    p99 = float(profile["import_kw"].quantile(0.99))

    local = profile["timestamp"].dt.tz_convert(TIMEZONE)
    days = int(local.dt.strftime("%Y-%m-%d").nunique())
    months_in_sample = max(len(peaks), 1)

    current_a = supply_point.reserved_capacity_a
    current_fee_m = tariff.monthly_capacity_fee_eur(current_a)
    current_fee_y = current_fee_m * 12
    current_pen = float(
        overrun_penalty_eur(profile, supply_point.reserved_capacity_kw, tariff.penalty_rk_eur_kw)["penalty_eur"].sum()
    )

    min_a = supply_point.main_breaker_a * tariff.min_rk_share_of_mrk
    candidates: list[tuple[str, str, float]] = [
        ("súčasný stav", f"RK {supply_point.reserved_capacity_kw:g} kW / {current_a:g} A podľa zmluvy", supply_point.reserved_capacity_kw),
        ("max + rezerva", f"namerané maximum {overall_max:.1f} kW + {headroom:.0%} rezerva", overall_max * (1 + headroom)),
        ("P99", f"99. percentil štvrťhodín ({p99:.1f} kW), zriedkavé prekročenia sa zaplatia sankciou", p99),
        ("minimum", f"{tariff.min_rk_share_of_mrk:.0%} MRK – spodná hranica podľa cenníka", tariff.kw_from_amps(min_a)),
    ]
    for name, kw in (extra_targets_kw or {}).items():
        candidates.append((name, "cieľ zadaný analytikom", kw))

    scenarios: list[CapacityScenario] = []
    for name, desc, target_kw in candidates:
        if name == "súčasný stav":
            target_a = current_a
        else:
            target_a = max(_ceil_amps(tariff.amps_from_kw(target_kw)), min_a)
        target_kw_eff = tariff.kw_from_amps(target_a) if name != "súčasný stav" else supply_point.reserved_capacity_kw
        fee_m = tariff.monthly_capacity_fee_eur(target_a)
        fee_y = fee_m * 12
        saving = current_fee_y - fee_y
        pen = overrun_penalty_eur(profile, target_kw_eff, tariff.penalty_rk_eur_kw)
        months_exceeded = int((pen["overrun_kw"] > 0).sum())
        pen_total = float(pen["penalty_eur"].sum())
        pen_annual = pen_total / months_in_sample * 12
        feasible = target_a >= min_a - 1e-9 and target_a <= supply_point.main_breaker_a + 1e-9
        note = ""
        if target_a > current_a:
            note = "vyššia než súčasná RK – zvýšenie odstráni sankcie, ale zvýši poplatok"
        scenarios.append(
            CapacityScenario(
                name=name,
                description=desc,
                target_kw=target_kw_eff,
                target_a=target_a,
                monthly_fee_eur=fee_m,
                annual_fee_eur=fee_y,
                annual_saving_eur=saving,
                months_exceeded=months_exceeded,
                expected_penalty_eur=pen_total,
                annual_net_saving_eur=saving - pen_annual,
                feasible=feasible,
                note=note,
            )
        )

    # Recommendation: best net saving among feasible scenarios with no more
    # than occasional overruns (penalties must stay below 20 % of the saving).
    eligible = [
        s for s in scenarios
        if s.feasible and s.name != "súčasný stav" and s.annual_net_saving_eur > 0
        and (s.expected_penalty_eur <= 0.2 * max(s.annual_saving_eur, 1e-9))
    ]
    if eligible:
        best = max(eligible, key=lambda s: s.annual_net_saving_eur)
        best.recommended = True

    return CapacityAnalysis(
        supply_point=supply_point,
        period_start=local.min().tz_localize(None),
        period_end=local.max().tz_localize(None),
        days=days,
        peaks=peaks,
        overall_max_kw=overall_max,
        overall_max_at=overall_at,
        p99_kw=p99,
        utilisation_pct=overall_max / supply_point.reserved_capacity_kw * 100.0,
        current_monthly_fee_eur=current_fee_m,
        current_annual_fee_eur=current_fee_y,
        current_penalty_eur=current_pen,
        scenarios=scenarios,
    )
