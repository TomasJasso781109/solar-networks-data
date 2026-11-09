from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples"


@pytest.fixture
def daily_oct() -> Path:
    return SAMPLES / "sample-plant-01_daily_2026-10.xlsx"


@pytest.fixture
def hourly_oct() -> Path:
    return SAMPLES / "sample-plant-01_hourly_2026-10.xlsx"


@pytest.fixture
def hourly_nov1() -> Path:
    return SAMPLES / "sample-plant-01_hourly_2026-11-01.xlsx"
