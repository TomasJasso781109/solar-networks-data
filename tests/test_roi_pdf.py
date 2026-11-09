from datetime import date

import pandas as pd

from solar_networks.config import get_plant
from solar_networks.ingest.fusionsolar import load_export
from solar_networks.model.rent import rent_from_summary
from solar_networks.model.roi import roi_analysis
from solar_networks.model.summary import monthly_summary
from solar_networks.reports.roi_pdf import build_roi_pdf, eur, kwh, pct


def test_slovak_number_formatting():
    assert eur(27900.7) == "27 901 €"
    assert eur(1234.567, 2) == "1 234,57 €"
    assert kwh(2174.56) == "2 175 kWh"
    assert pct(0.1823) == "18,2 %"


def test_pdf_builds_and_has_pages(tmp_path, daily_oct):
    plant = get_plant("realcorp-rusovska-1")
    df = load_export(daily_oct, plant_id=plant.plant_id)
    realized = rent_from_summary(monthly_summary(df), plant.economics.tariff, plant.economics.contract_share)
    result = roi_analysis(plant, as_of=date(2026, 10, 31), cumulative_yield_kwh=111_628.72)
    out = build_roi_pdf(result, realized, tmp_path / "roi.pdf", sources=["test source"])
    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert data.count(b"/Type /Page") >= 3
    assert out.stat().st_size > 50_000  # charts embedded


def test_pdf_builds_without_realized_data(tmp_path):
    plant = get_plant("realcorp-rusovska-1")
    result = roi_analysis(plant, as_of=date(2026, 10, 31), cumulative_yield_kwh=None)
    out = build_roi_pdf(result, pd.DataFrame(), tmp_path / "roi.pdf", sources=[])
    assert out.exists()
