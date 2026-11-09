"""Generate the internal ROI PDF for one plant.

Usage:
    python scripts/roi_report.py --plant realcorp-rusovska-1
    python scripts/roi_report.py --plant realcorp-rusovska-1 --input data/private/exports \
        --cumulative-yield 111628.72 --as-of 2026-10-31 --output output/roi_realcorp.pdf

Production comes from FusionSolar exports in --input (default data/samples/).
Cumulative yield ("Total Yield" in the daily export) feeds the annual yield
estimate; when omitted, the script reads it from the newest daily export.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from solar_networks.config import get_plant  # noqa: E402
from solar_networks.ingest.fusionsolar import infer_granularity, load_export  # noqa: E402
from solar_networks.model.rent import rent_from_summary  # noqa: E402
from solar_networks.model.roi import Assumptions, roi_analysis  # noqa: E402
from solar_networks.model.summary import monthly_summary  # noqa: E402
from solar_networks.reports.roi_pdf import build_roi_pdf  # noqa: E402

SOURCES = [
    "FusionSolar Plant Report exporty (denný a hodinový export 10/2026, hodinový 1. 11. 2026) – výroba, spotreba, dodávka.",
    "Zmluva o spolupráci, príloha č. 2 – vzorec výpočtu nájomného REALCORP 2026 (sadzby, 80 % podiel, 30 €/mes. istič).",
    "Faktúra MAGNA ENERGIA č. 1526087261 za 09/2026 – potvrdenie jednotkových cien, RK 82,3 kW, max. 86,07 kW, jalová dodávka.",
    "Cenová ponuka FVE 27,6 kWp (26. 2. 2023) – CAPEX 27 900,50 € bez DPH, striedač 2 950 € + 250 € montáž.",
    "Výkon FVE REALCORP RUSOVSKÁ 1 – 60 × 460 Wp, Huawei SUN2000-36KTL-M1, DC/AC 0,77.",
]


def _read_cumulative_yield(paths: list[Path]) -> float | None:
    """Pick the last 'Total Yield' value from the newest daily export, if any."""
    best: tuple[pd.Timestamp, float] | None = None
    for path in paths:
        sheet = pd.read_excel(path, sheet_name=0, header=None, dtype=object)
        header_idx = next(
            (i for i in range(min(len(sheet), 10)) if str(sheet.iat[i, 0]).strip().lower().startswith("statistical")),
            None,
        )
        if header_idx is None:
            continue
        headers = [str(h).strip().lower() for h in sheet.iloc[header_idx]]
        total_cols = [i for i, h in enumerate(headers) if h.startswith("total yield")]
        if not total_cols:
            continue
        body = sheet.iloc[header_idx + 1 :]
        body = body[body.iloc[:, 0].notna()]
        last_ts = pd.to_datetime(str(body.iloc[-1, 0]).replace(" DST", ""))
        value = float(body.iloc[-1, total_cols[0]])
        if best is None or last_ts > best[0]:
            best = (last_ts, value)
    return best[1] if best else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--plant", required=True)
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "samples")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--cumulative-yield", type=float, default=None)
    parser.add_argument("--discount-rate", type=float, default=None)
    parser.add_argument("--opex", type=float, default=None, help="override OPEX EUR/year")
    args = parser.parse_args(argv)

    plant = get_plant(args.plant)
    if plant.economics is None:
        raise SystemExit(f"Plant {plant.plant_id} has no economics in config.py")
    if args.opex is not None:
        from dataclasses import replace

        plant = replace(plant, economics=replace(plant.economics, opex_eur_year=args.opex))

    paths = sorted(args.input.glob("*.xlsx"))
    frames = []
    for path in paths:
        df = load_export(path, plant_id=plant.plant_id)
        # Prefer one source per month: daily exports first, hourly as fallback.
        df["granularity"] = infer_granularity(df)
        frames.append(df)
    if not frames:
        raise SystemExit(f"No exports found in {args.input}")
    data = pd.concat(frames, ignore_index=True)

    # De-duplicate months covered by several exports (daily wins over hourly).
    local_month = data["timestamp"].dt.tz_convert("Europe/Bratislava").dt.strftime("%Y-%m")
    data["month"] = local_month
    chosen = []
    for month, group in data.groupby("month"):
        prefer = "daily" if (group["granularity"] == "daily").any() else group["granularity"].iloc[0]
        chosen.append(group[group["granularity"] == prefer])
    data = pd.concat(chosen, ignore_index=True).drop(columns=["granularity", "month"])

    realized = rent_from_summary(monthly_summary(data), plant.economics.tariff, plant.economics.contract_share)
    # Mark months that are only partially covered by the exports.
    days = data.assign(day=data["timestamp"].dt.tz_convert("Europe/Bratislava").dt.strftime("%Y-%m-%d"))
    days_per_month = days.groupby(days["day"].str[:7])["day"].nunique()
    realized["days_covered"] = realized["month"].map(days_per_month).astype(int)
    realized["month"] = [
        f"{m} ({d} d)" if d < pd.Period(m).days_in_month else m
        for m, d in zip(realized["month"], realized["days_covered"])
    ]

    as_of = args.as_of or data["timestamp"].max().tz_convert("Europe/Bratislava").date()
    cumulative = args.cumulative_yield if args.cumulative_yield is not None else _read_cumulative_yield(paths)

    assumptions = Assumptions()
    if args.discount_rate is not None:
        from dataclasses import replace

        assumptions = replace(assumptions, discount_rate=args.discount_rate, target_irr=args.discount_rate)

    result = roi_analysis(plant, as_of=as_of, cumulative_yield_kwh=cumulative, assumptions=assumptions)

    output = args.output or ROOT / "output" / f"roi_{plant.plant_id}.pdf"
    build_roi_pdf(result, realized, output, SOURCES)

    pd.set_option("display.width", 200)
    print(realized.round(2).to_string(index=False))
    print(f"\nAnnual yield (year 1): {result.annual_yield_year1_kwh:,.0f} kWh  {result.yield_source}")
    for sc in result.scenarios:
        print(f"{sc.scenario.name:13} IRR {sc.irr:6.1%}  NPV {sc.npv_eur:9,.0f} €  payback {sc.payback_years:4.1f} y")
    print(f"Break-even reference price: {result.break_even_price_eur_kwh:.4f} €/kWh")
    print(f"\nWritten: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
