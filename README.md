# solar-networks-data

Data collection, calculations and reports for Solar Networks PV/BESS plants.
Agent context and conventions live in [`CLAUDE.md`](CLAUDE.md).

## Layout

```
src/solar_networks/
  ingest/fusionsolar.py   # load_export(path) -> tidy UTC DataFrame
  ingest/zsdis.py         # load_profile(path) -> 15-min DSO profile (.xls), gaps/duplicates check
  ingest/enmon.py         # load_registers(path) -> meter register readings, recomputed consumption
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

## Data notes (ZSDIS interval profiles, Enmon registers)

- ZSDIS `.xls`: sheet "Namerané hodnoty"; metadata and the table header are
  found by text. Values are mean kW per 15 minutes (kWh = value / 4).
- Spring switch-over day has 92 intervals, autumn 100. The repeated autumn
  hour carries one extra second (`02:00:01`) and is taken as the second pass.
- The sheet "Nameraná hodinová práca" is not used (drops an hour in autumn).
- Enmon `.xlsx`: sheet "Meters", Czech headers, multiplier stored as text and
  empty when 1. Consumption is recomputed and compared with the file.
- Sample files are anonymized (EIC, names, serial numbers); values are real.

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
