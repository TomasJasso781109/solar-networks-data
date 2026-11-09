"""Load every FusionSolar export in data/samples/ and print/write a monthly summary.

Usage:
    python scripts/monthly_summary.py [--input data/samples] [--output output/summary.xlsx]

Each export is summarised separately (one block per file) because a daily
and an hourly export of the same month describe the same energy and must not
be added together. When two files cover the same plant and month the script
reports whether their totals agree.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from solar_networks.ingest.fusionsolar import infer_granularity, load_export  # noqa: E402
from solar_networks.model.summary import monthly_summary  # noqa: E402


def summarise_directory(input_dir: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(input_dir.glob("*.xlsx")):
        df = load_export(path)
        summary = monthly_summary(df)
        summary.insert(0, "source_file", path.name)
        summary.insert(1, "granularity", infer_granularity(df))
        frames.append(summary)
    if not frames:
        raise SystemExit(f"No .xlsx files found in {input_dir}")
    return pd.concat(frames, ignore_index=True)


def cross_check(summary: pd.DataFrame, tolerance_kwh: float = 0.05) -> list[str]:
    """Compare files that cover the same plant+month; return human-readable notes."""
    notes = []
    for (plant, month), group in summary.groupby(["plant_id", "month"]):
        if len(group) < 2:
            continue
        spread = group["pv_yield_kwh"].max() - group["pv_yield_kwh"].min()
        files = ", ".join(group["source_file"])
        status = "match" if spread <= tolerance_kwh else f"DIFFER by {spread:.2f} kWh"
        notes.append(f"{plant} {month}: {len(group)} files ({files}) -> PV yield {status}")
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--input", type=Path, default=ROOT / "data" / "samples")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "summary.xlsx")
    args = parser.parse_args(argv)

    summary = summarise_directory(args.input)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", None)
    print(summary.round(2).to_string(index=False))
    for note in cross_check(summary):
        print(note)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="monthly_summary", index=False)
        ws = writer.sheets["monthly_summary"]
        for column_cells in ws.columns:
            width = max(len(str(c.value)) if c.value is not None else 0 for c in column_cells)
            ws.column_dimensions[column_cells[0].column_letter].width = min(width + 2, 45)
    print(f"\nWritten: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
