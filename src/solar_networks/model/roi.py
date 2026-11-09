"""Return-on-investment model for a leased PV plant (Solar Networks' view).

Cash flows are yearly from commissioning over the contract term:

    revenue_t = share × ref_price_t × production_t + 12 × breaker_fee
    cost_t    = opex (+ inverter replacement in the replacement year)
    cf_0      = −capex

``ref_price`` is the client's avoided per-kWh cost (commodity + regulated
items) that the rent tracks. Three scenarios follow the internal
"FVE návratnosť" methodology; all percentages are assumptions
([PREDPOKLAD]) and can be overridden.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np
import pandas as pd

from solar_networks.config import Plant


# --------------------------------------------------------------------------
# Assumptions
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Scenario:
    name: str
    price_shift: float  # one-off change vs. today's reference price (0.15 = +15 %)
    price_growth: float  # yearly growth after the shift (0.02 = +2 %/yr)


DEFAULT_SCENARIOS: tuple[Scenario, ...] = (
    Scenario("pesimistický", price_shift=-0.25, price_growth=0.0),
    Scenario("základný", price_shift=0.0, price_growth=0.02),
    Scenario("optimistický", price_shift=0.15, price_growth=0.03),
)


@dataclass(frozen=True)
class Assumptions:
    """Everything tagged [PREDPOKLAD] in the report. Override as needed."""

    degradation_per_year: float = 0.005
    discount_rate: float = 0.06
    inverter_replacement_year: int = 11  # year of operation (1-based)
    specific_yield_kwh_kwp: float = 1050.0  # fallback when no measured yield
    target_irr: float = 0.06  # for break-even price
    scenarios: tuple[Scenario, ...] = DEFAULT_SCENARIOS
    labels: dict[str, str] = field(
        default_factory=lambda: {
            "degradation_per_year": "degradácia panelov 0,5 %/rok (štandard výrobcov)",
            "discount_rate": "diskontná sadzba 6 % (interná metodika, ak konatelia nezadajú inú)",
            "inverter_replacement_year": "výmena striedača v 11. roku prevádzky za cenu z ponuky",
            "specific_yield_kwh_kwp": "merný výnos 1 050 kWh/kWp (Bratislava, plochá strecha)",
        }
    )


# --------------------------------------------------------------------------
# Production estimate
# --------------------------------------------------------------------------
def estimate_annual_yield_kwh(
    plant: Plant,
    cumulative_yield_kwh: float | None,
    as_of: date,
    assumptions: Assumptions,
) -> tuple[float, str]:
    """First-year production estimate and a provenance tag.

    Prefers the plant's own cumulative yield (FusionSolar "Total Yield")
    divided by the operating time; falls back to a specific-yield assumption.
    Returned value is normalised back to year 1 (un-degraded).
    """
    econ = plant.economics
    if cumulative_yield_kwh and econ is not None:
        years = (as_of - econ.commissioning).days / 365.25
        if years >= 0.5:
            avg_per_year = cumulative_yield_kwh / years
            # Average over the elapsed years sits roughly at mid-life degradation.
            mid = years / 2.0
            year1 = avg_per_year / ((1 - assumptions.degradation_per_year) ** mid)
            return year1, (
                f"[VÝPOČET] {cumulative_yield_kwh:,.0f} kWh kumulatívne / {years:.2f} roka "
                f"prevádzky, normalizované na 1. rok"
            )
    return plant.capacity_kwp * assumptions.specific_yield_kwh_kwp, (
        f"[PREDPOKLAD] {plant.capacity_kwp:g} kWp × "
        f"{assumptions.specific_yield_kwh_kwp:g} kWh/kWp"
    )


# --------------------------------------------------------------------------
# Finance helpers
# --------------------------------------------------------------------------
def npv(rate: float, cash_flows: np.ndarray) -> float:
    """Net present value; cash_flows[0] is at t=0 (undiscounted)."""
    t = np.arange(len(cash_flows))
    return float(np.sum(cash_flows / (1 + rate) ** t))


def irr(cash_flows: np.ndarray, low: float = -0.99, high: float = 1.0) -> float:
    """Internal rate of return by bisection; NaN when no sign change."""
    f_low, f_high = npv(low, cash_flows), npv(high, cash_flows)
    if np.isnan(f_low) or np.isnan(f_high) or f_low * f_high > 0:
        return float("nan")
    for _ in range(200):
        mid = (low + high) / 2
        f_mid = npv(mid, cash_flows)
        if abs(f_mid) < 1e-9:
            return mid
        if f_low * f_mid < 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid
    return (low + high) / 2


def payback_years(cash_flows: np.ndarray) -> float:
    """Simple payback with linear interpolation inside the break-even year."""
    cumulative = np.cumsum(cash_flows)
    for year in range(1, len(cumulative)):
        if cumulative[year] >= 0:
            prev = cumulative[year - 1]
            delta = cash_flows[year]
            return (year - 1) + (-prev / delta if delta else 0.0)
    return float("nan")


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
@dataclass
class ScenarioResult:
    scenario: Scenario
    cash_flows: pd.DataFrame
    npv_eur: float
    irr: float
    payback_years: float
    total_revenue_eur: float
    total_net_eur: float


@dataclass
class RoiResult:
    plant: Plant
    as_of: date
    annual_yield_year1_kwh: float
    yield_source: str
    reference_price_eur_kwh: float
    realized_price_eur_kwh: float
    scenarios: list[ScenarioResult]
    break_even_price_eur_kwh: float
    assumptions: Assumptions

    def by_name(self, name: str) -> ScenarioResult:
        return next(s for s in self.scenarios if s.scenario.name == name)

    @property
    def base(self) -> ScenarioResult:
        return self.by_name("základný")


def project_cash_flows(
    plant: Plant,
    annual_yield_year1_kwh: float,
    reference_price_eur_kwh: float,
    scenario: Scenario,
    assumptions: Assumptions,
    as_of: date,
) -> pd.DataFrame:
    econ = plant.economics
    if econ is None:
        raise ValueError(f"Plant {plant.plant_id} has no economics configured")

    years = np.arange(0, econ.contract_years + 1)
    # Operating years run from the commissioning date (year 1 = first 12
    # months of operation); calendar_year labels the year each one starts in.
    calendar_year = econ.commissioning.year + np.maximum(years - 1, 0)
    production = np.where(
        years == 0,
        0.0,
        annual_yield_year1_kwh * (1 - assumptions.degradation_per_year) ** (years - 1),
    )
    # Price path: today's reference price, shifted by the scenario and grown
    # from the as-of year onwards. Past years use today's price [PREDPOKLAD].
    years_from_now = np.maximum(calendar_year - as_of.year, 0)
    price = reference_price_eur_kwh * (1 + scenario.price_shift) * (
        (1 + scenario.price_growth) ** years_from_now
    )
    price = np.where(years == 0, 0.0, price)

    revenue = econ.contract_share * price * production + np.where(
        years == 0, 0.0, 12 * econ.tariff.breaker_fee_eur_month
    )
    opex = np.where(years == 0, 0.0, econ.opex_eur_year)
    capex = np.where(years == 0, econ.capex_eur, 0.0)
    replacement = np.where(
        years == assumptions.inverter_replacement_year, econ.capex_inverter_eur, 0.0
    )
    net = revenue - opex - capex - replacement

    df = pd.DataFrame(
        {
            "year": years,
            "calendar_year": calendar_year,
            "production_kwh": production,
            "reference_price_eur_kwh": price,
            "revenue_eur": revenue,
            "opex_eur": opex,
            "capex_eur": capex + replacement,
            "net_cash_flow_eur": net,
        }
    )
    df["cumulative_eur"] = df["net_cash_flow_eur"].cumsum()
    df["discounted_eur"] = df["net_cash_flow_eur"] / (1 + assumptions.discount_rate) ** df["year"]
    df["cumulative_discounted_eur"] = df["discounted_eur"].cumsum()
    return df


def _evaluate(
    plant: Plant,
    annual_yield: float,
    ref_price: float,
    scenario: Scenario,
    assumptions: Assumptions,
    as_of: date,
) -> ScenarioResult:
    df = project_cash_flows(plant, annual_yield, ref_price, scenario, assumptions, as_of)
    cf = df["net_cash_flow_eur"].to_numpy()
    return ScenarioResult(
        scenario=scenario,
        cash_flows=df,
        npv_eur=npv(assumptions.discount_rate, cf),
        irr=irr(cf),
        payback_years=payback_years(cf),
        total_revenue_eur=float(df["revenue_eur"].sum()),
        total_net_eur=float(cf.sum()),
    )


def break_even_reference_price(
    plant: Plant,
    annual_yield: float,
    assumptions: Assumptions,
    as_of: date,
    target_irr: float | None = None,
) -> float:
    """Flat reference price (EUR/kWh, no growth) at which IRR equals the target."""
    target = assumptions.target_irr if target_irr is None else target_irr
    flat = Scenario("break-even", 0.0, 0.0)

    def irr_at(price: float) -> float:
        return _evaluate(plant, annual_yield, price, flat, assumptions, as_of).irr

    low, high = 0.0, 2.0
    for _ in range(100):
        mid = (low + high) / 2
        value = irr_at(mid)
        if np.isnan(value) or value < target:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def roi_analysis(
    plant: Plant,
    as_of: date,
    cumulative_yield_kwh: float | None = None,
    assumptions: Assumptions | None = None,
    reference_price_eur_kwh: float | None = None,
) -> RoiResult:
    """Run the full ROI analysis for one plant."""
    assumptions = assumptions or Assumptions()
    econ = plant.economics
    if econ is None:
        raise ValueError(f"Plant {plant.plant_id} has no economics configured")

    ref_price = (
        econ.tariff.variable_eur_kwh if reference_price_eur_kwh is None else reference_price_eur_kwh
    )
    annual_yield, source = estimate_annual_yield_kwh(plant, cumulative_yield_kwh, as_of, assumptions)

    results = [
        _evaluate(plant, annual_yield, ref_price, sc, assumptions, as_of)
        for sc in assumptions.scenarios
    ]
    realized = econ.contract_share * ref_price + 12 * econ.tariff.breaker_fee_eur_month / annual_yield
    return RoiResult(
        plant=plant,
        as_of=as_of,
        annual_yield_year1_kwh=annual_yield,
        yield_source=source,
        reference_price_eur_kwh=ref_price,
        realized_price_eur_kwh=realized,
        scenarios=results,
        break_even_price_eur_kwh=break_even_reference_price(plant, annual_yield, assumptions, as_of),
        assumptions=assumptions,
    )


def with_overrides(assumptions: Assumptions, **changes) -> Assumptions:
    """Convenience wrapper so callers can tweak one assumption at a time."""
    return replace(assumptions, **changes)
