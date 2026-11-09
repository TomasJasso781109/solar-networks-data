import pytest

from solar_networks.config import TARIFF_REALCORP_2026, get_plant
from solar_networks.model.rent import monthly_rent_eur, rent_breakdown

# Monthly totals (J14) from "Príloha č. 2" sheets, production in D3.
ANNEX_2026 = [
    (503, 108.8897152),
    (742, 146.3740928),
    (2070, 354.655488),
    (2810, 470.715904),
    (3700, 610.30208),
    (4150, 680.87936),
    (4200, 688.72128),
    (3970, 652.648448),
    (0, 30.0),
]


@pytest.mark.parametrize("production_kwh,expected_rent", ANNEX_2026)
def test_rent_matches_contract_annex(production_kwh, expected_rent):
    rent = monthly_rent_eur(production_kwh, TARIFF_REALCORP_2026, share=0.8)
    assert rent == pytest.approx(expected_rent, abs=1e-6)


def test_variable_rate_matches_supplier_invoice():
    # Sept 2026 MAGNA invoice: per-kWh items sum for 5 743.5 kWh.
    t = TARIFF_REALCORP_2026
    invoiced = 746.66 + 7.58 + 148.98 + 60.12 + 63.06 + 80.82 + 18.78
    assert t.variable_eur_kwh * 5743.5 == pytest.approx(invoiced, abs=0.05)
    assert t.variable_eur_kwh == pytest.approx(0.196048, abs=1e-6)


def test_breakdown_sums_to_rent():
    df = rent_breakdown(4150, TARIFF_REALCORP_2026, share=0.8)
    assert df["rent_eur"].sum() == pytest.approx(680.87936, abs=1e-6)
    assert set(df["item"]) == {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi"}


def test_plant_alias_resolves():
    plant = get_plant("sample-plant-01")
    assert plant.plant_id == "realcorp-rusovska-1"
    assert plant.capacity_kwp == 27.6
    assert plant.economics is not None
    assert plant.economics.capex_eur == pytest.approx(27_900.50)


def test_zsd_tariff_reproduces_invoice():
    from solar_networks.config import ZSD_C2_X3_2026

    t = ZSD_C2_X3_2026
    assert t.monthly_capacity_fee_eur(125) == pytest.approx(82.575, abs=1e-6)
    assert t.kw_from_amps(125) == pytest.approx(82.3, abs=0.1)
    assert t.amps_from_kw(t.kw_from_amps(100)) == pytest.approx(100)
    assert t.distribution_eur_kwh == TARIFF_REALCORP_2026.distribution_eur_kwh
    assert t.losses_eur_kwh == TARIFF_REALCORP_2026.losses_eur_kwh
