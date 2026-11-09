# solar-networks-data

Data collection, calculations and reports for Solar Networks PV/BESS plants.
Agent context and conventions live in [`CLAUDE.md`](CLAUDE.md).

## Layout

```
src/solar_networks/
  ingest/fusionsolar.py   # load_export(path) -> tidy UTC DataFrame
  model/summary.py        # monthly_summary(df) -> per plant & month totals
  config.py               # plant registry, timezone
scripts/monthly_summary.py  # summarise data/samples/ -> output/summary.xlsx
data/samples/             # small anonymized FusionSolar exports (test fixtures)
tests/                    # pytest, runs against data/samples/
```

Real client data and API tokens are never committed (`data/*` and `.env` are
git-ignored); only anonymized samples are kept in `data/samples/`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
python scripts/monthly_summary.py            # prints summary, writes output/summary.xlsx
python scripts/monthly_summary.py --input path/to/exports --output out.xlsx
pytest
```

## Data notes (FusionSolar plant-report exports)

- Only the first sheet holds data; row 1 is the plant name, row 2 the header.
- Header spelling varies between exports (`kWh/㎡` vs `kWh/m²`, stray spaces,
  `Revenue(€)` vs `Revenue (€)`); the parser matches on normalized prefixes.
- Hourly timestamps carry a ` DST` suffix during summer time. The suffix is
  required to tell the two 02:00 rows apart on the autumn switch-over.
- Daily rows are local midnight; months are grouped in Europe/Bratislava time.
- Some exports lack `Consumption`/`Self-consumption`; those columns are NaN.
- `Total Yield` is cumulative since commissioning and is ignored.

## ROI report (internal)

```bash
python scripts/roi_report.py --plant realcorp-rusovska-1          # -> output/roi_<plant>.pdf
python scripts/roi_report.py --plant realcorp-rusovska-1 --opex 400 --discount-rate 0.08
```

Economics (CAPEX, tariffs, contract share, commissioning) live in
`src/solar_networks/config.py`; every value is tagged `[DATA]` or
`[PREDPOKLAD]`. Rent follows the contract annex formula (`model/rent.py`),
the ROI model and scenarios follow the internal "FVE návratnosť" methodology
(`model/roi.py`). The PDF is for the managing directors only.
