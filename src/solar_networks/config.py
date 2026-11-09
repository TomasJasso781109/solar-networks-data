"""Plant registry and client parameters.

Real plant/client data is filled in incrementally. Energy prices are EUR
excl. VAT. Keep anything confidential (tokens, contract prices) in `.env`,
not here.
"""

from __future__ import annotations

from dataclasses import dataclass

TIMEZONE = "Europe/Bratislava"


@dataclass(frozen=True)
class Plant:
    plant_id: str
    name: str
    capacity_kwp: float
    battery_kwh: float = 0.0
    client: str = ""


PLANTS: dict[str, Plant] = {
    # Sample plant used by data/samples/ (anonymized export of a 27.6 kWp
    # rooftop PV without battery).
    "sample-plant-01": Plant(
        plant_id="sample-plant-01",
        name="SAMPLE-PLANT-01",
        capacity_kwp=27.6,
        battery_kwh=0.0,
        client="sample",
    ),
}


def plant_id_from_filename(filename: str) -> str:
    """Derive plant_id from a sample/export filename like
    ``sample-plant-01_hourly_2026-10.xlsx`` -> ``sample-plant-01``."""
    return filename.split("_", 1)[0]
