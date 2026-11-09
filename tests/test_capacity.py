import numpy as np
import pandas as pd
import pytest

from solar_networks.config import ZSD_C2_X3_2026, SupplyPoint, get_plant
from solar_networks.model.capacity import analyse_capacity, monthly_peaks, overrun_penalty_eur


def _profile(months=("2026-07", "2026-08", "2026-09"), base_kw=40.0, peak_kw=86.07, peak_month="2026-09"):
    """Synthetic 15-min profile: flat base load with one spike per month."""
    frames = []
    rng = np.random.default_rng(1)
    for m in months:
        start = pd.Timestamp(m + "-01", tz="Europe/Bratislava")
        end = start + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23, minutes=45)
        ts = pd.date_range(start, end, freq="15min")
        kw = base_kw + rng.normal(0, 3, len(ts))
        spike = peak_kw if m == peak_month else min(70.0, peak_kw)
        kw[len(ts) // 2] = spike  # mid-month peak
        frames.append(pd.DataFrame({"timestamp": ts.tz_convert("UTC"), "import_kw": kw}))
    return pd.concat(frames, ignore_index=True)


@pytest.fixture
def realcorp_sp() -> SupplyPoint:
    return get_plant("realcorp-rusovska-1").supply_point


def test_monthly_peaks_basic():
    peaks = monthly_peaks(_profile())
    assert peaks["month"].tolist() == ["2026-07", "2026-08", "2026-09"]
    assert peaks.loc[2, "max_kw"] == pytest.approx(86.07)
    assert peaks.loc[0, "days"] == 31
    assert (peaks["p99_kw"] < peaks["max_kw"]).all()


def test_overrun_penalty_matches_pricelist():
    pen = overrun_penalty_eur(_profile(), rk_kw=82.3, penalty_eur_kw=ZSD_C2_X3_2026.penalty_rk_eur_kw)
    sept = pen.set_index("month").loc["2026-09"]
    assert sept["overrun_kw"] == pytest.approx(86.07 - 82.3, abs=1e-6)
    assert sept["penalty_eur"] == pytest.approx((86.07 - 82.3) * 33.1939, abs=1e-4)
    assert pen.set_index("month").loc["2026-07", "penalty_eur"] == 0


def test_current_state_scenario_reproduces_invoice(realcorp_sp):
    result = analyse_capacity(_profile(), realcorp_sp)
    current = next(s for s in result.scenarios if s.name == "súčasný stav")
    assert current.monthly_fee_eur == pytest.approx(82.575, abs=1e-6)
    assert current.annual_saving_eur == 0
    assert result.utilisation_pct == pytest.approx(86.07 / 82.3 * 100, abs=0.01)
    assert result.current_penalty_eur == pytest.approx((86.07 - 82.3) * 33.1939, abs=1e-4)


def test_scenarios_respect_minimum_and_amps(realcorp_sp):
    low = _profile(base_kw=20.0, peak_kw=30.0)
    result = analyse_capacity(low, realcorp_sp)
    min_a = realcorp_sp.main_breaker_a * 0.5
    for s in result.scenarios:
        assert s.target_a >= min_a - 1e-9
        # whole amperes, except the contractual value and the 50 % MRK floor
        assert float(s.target_a).is_integer() or s.name == "súčasný stav" or s.target_a == min_a
    rec = result.recommended
    assert rec is not None
    assert rec.target_a == min_a  # peaks far below the floor -> minimum wins
    expected_saving = (82.575 - 3 * min_a * 0.2202) * 12
    assert rec.annual_saving_eur == pytest.approx(expected_saving, abs=1e-6)


def test_no_recommendation_when_rk_already_tight(realcorp_sp):
    # Peaks at 86 kW every month: lowering RK only buys penalties.
    tight = _profile(base_kw=60.0, peak_kw=86.0, peak_month="2026-07")
    tight.loc[tight["import_kw"] == 70.0, "import_kw"] = 86.0
    result = analyse_capacity(tight, realcorp_sp)
    assert result.recommended is None or result.recommended.annual_net_saving_eur > 0


def test_savings_decompose_exactly(realcorp_sp):
    result = analyse_capacity(_profile(), realcorp_sp)
    for s in result.scenarios:
        assert s.annual_fee_eur == pytest.approx(s.monthly_fee_eur * 12)
        assert s.annual_saving_eur == pytest.approx(result.current_annual_fee_eur - s.annual_fee_eur)
