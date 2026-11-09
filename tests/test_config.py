from datetime import date

import pytest

from solar_networks import config
from solar_networks.config import (
    PLANTS,
    fusionsolar_report_url,
    get_plant,
    plant_id_from_fusionsolar_filename,
    plants_for_monthly_export,
)


def test_registry_has_all_solar_networks_plants():
    # 12 plants in the installer account minus Ecorec (external).
    assert len(PLANTS) == 11
    assert "ecorec" not in PLANTS
    ne_ids = [p.fusionsolar_ne_id for p in PLANTS.values()]
    assert len(set(ne_ids)) == len(ne_ids), "duplicate FusionSolar ids"
    names = [p.fusionsolar_name for p in PLANTS.values()]
    assert len(set(names)) == len(names), "duplicate FusionSolar names"
    for plant in PLANTS.values():
        assert plant.plant_id == plant.plant_id.lower()
        assert plant.capacity_kwp > 0
        assert isinstance(plant.grid_connection, date)


def test_monthly_export_covers_customers_and_own_plant():
    ids = {p.plant_id for p in plants_for_monthly_export()}
    assert "tomas-jasso" in ids
    assert "realcorp-rusovska-1" in ids
    assert len(ids) == 11


def test_report_url_points_to_plant():
    url = fusionsolar_report_url(get_plant("decathlon-bory"))
    assert url.startswith("https://uni003eu5.fusionsolar.huawei.com/")
    assert url.endswith("#/view/station/NE=316113746/report")


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("Plant Report_REALCORP RUSOVSKÁ s.r.o._11-2026.xlsx", "realcorp-rusovska-1"),
        ("Plant Report_REALCORP RUSOVSKA s.r.o.2_10-2026.xlsx", "realcorp-rusovska-2"),
        ("Plant Report_PATRIOT real s.r.o. - Telocvičňa_2026-11-01.xlsx", "patriot-telocvicna"),
        ("Plant Report_Tomas Jasso_10-2026.xlsx", "tomas-jasso"),
    ],
)
def test_plant_id_from_portal_filename(filename, expected):
    assert plant_id_from_fusionsolar_filename(filename) == expected


def test_unknown_portal_filename_raises():
    with pytest.raises(KeyError):
        plant_id_from_fusionsolar_filename("Plant Report_Ecorec_10-2026.xlsx")
    with pytest.raises(ValueError):
        plant_id_from_fusionsolar_filename("summary.xlsx")


def test_realcorp_commissioning_matches_grid_connection():
    plant = get_plant("realcorp-rusovska-1")
    assert plant.economics.commissioning == plant.grid_connection == date(2023, 5, 24)
    assert config.TIMEZONE == "Europe/Bratislava"
