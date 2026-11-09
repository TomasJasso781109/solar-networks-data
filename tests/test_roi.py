from datetime import date

import numpy as np
import pytest

from solar_networks.config import get_plant
from solar_networks.model.roi import (
    Assumptions,
    Scenario,
    estimate_annual_yield_kwh,
    irr,
    npv,
    payback_years,
    roi_analysis,
    with_overrides,
)

AS_OF = date(2026, 10, 31)
CUMULATIVE = 111_628.72  # [DATA] FusionSolar Total Yield 31. 10. 2026


def test_npv_irr_payback_on_textbook_flows():
    cf = np.array([-1000.0, 500.0, 500.0, 500.0])
    assert npv(0.0, cf) == pytest.approx(500.0)
    assert npv(0.1, cf) == pytest.approx(243.43, abs=0.01)
    assert irr(cf) == pytest.approx(0.2338, abs=1e-3)
    assert payback_years(cf) == pytest.approx(2.0)


def test_irr_nan_without_sign_change():
    assert np.isnan(irr(np.array([100.0, 100.0])))
    assert np.isnan(payback_years(np.array([-100.0, 10.0])))


def test_yield_estimate_prefers_measured_cumulative():
    plant = get_plant("realcorp-rusovska-1")
    y, source = estimate_annual_yield_kwh(plant, CUMULATIVE, AS_OF, Assumptions())
    assert source.startswith("[VÝPOČET]")
    years = (AS_OF - plant.economics.commissioning).days / 365.25
    assert y > CUMULATIVE / years  # normalised back to an un-degraded year 1
    y2, source2 = estimate_annual_yield_kwh(plant, None, AS_OF, Assumptions())
    assert source2.startswith("[PREDPOKLAD]")
    assert y2 == pytest.approx(27.6 * 1050)


def test_cash_flow_structure():
    plant = get_plant("realcorp-rusovska-1")
    result = roi_analysis(plant, AS_OF, CUMULATIVE)
    df = result.base.cash_flows
    econ = plant.economics
    assert len(df) == econ.contract_years + 1
    assert df.loc[0, "capex_eur"] == pytest.approx(econ.capex_eur)
    assert df.loc[0, "revenue_eur"] == 0
    assert df.loc[11, "capex_eur"] == pytest.approx(econ.capex_inverter_eur)
    # Degradation: each year 0.5 % less than the previous.
    ratio = df.loc[2, "production_kwh"] / df.loc[1, "production_kwh"]
    assert ratio == pytest.approx(0.995)
    # Year-1 revenue = share × price × production + 12 × breaker fee.
    expected = 0.8 * result.reference_price_eur_kwh * df.loc[1, "production_kwh"] + 12 * 30
    assert df.loc[1, "revenue_eur"] == pytest.approx(expected)


def test_scenarios_are_ordered():
    result = roi_analysis(get_plant("realcorp-rusovska-1"), AS_OF, CUMULATIVE)
    pes, base, opt = (result.by_name(n) for n in ("pesimistický", "základný", "optimistický"))
    assert pes.npv_eur < base.npv_eur < opt.npv_eur
    assert pes.irr < base.irr < opt.irr
    assert pes.payback_years > base.payback_years > opt.payback_years


def test_break_even_price_hits_target_irr():
    plant = get_plant("realcorp-rusovska-1")
    result = roi_analysis(plant, AS_OF, CUMULATIVE)
    flat = Assumptions(scenarios=(Scenario("flat", 0.0, 0.0),))
    check = roi_analysis(
        plant, AS_OF, CUMULATIVE, assumptions=flat,
        reference_price_eur_kwh=result.break_even_price_eur_kwh,
    )
    assert check.scenarios[0].irr == pytest.approx(0.06, abs=1e-3)
    assert result.break_even_price_eur_kwh < result.reference_price_eur_kwh


def test_overrides_change_result():
    plant = get_plant("realcorp-rusovska-1")
    a = Assumptions()
    b = with_overrides(a, discount_rate=0.10)
    assert roi_analysis(plant, AS_OF, CUMULATIVE, a).base.npv_eur > roi_analysis(
        plant, AS_OF, CUMULATIVE, b
    ).base.npv_eur
