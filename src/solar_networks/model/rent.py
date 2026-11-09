"""Monthly rent Solar Networks invoices the client for a leased PV plant.

Implements "Príloha č. 2 – vzorec výpočtu nájomného":

    rent = share × Σ_i (unit_price_i × production_kwh)   for per-kWh items
         + breaker_fee                                    (fixed, per month)

The fixed breaker component is charged in full (not multiplied by the share),
exactly as in the contract annex (J8 = H8 = 30 € regardless of share).
"""

from __future__ import annotations

import pandas as pd

from solar_networks.config import Tariff


def monthly_rent_eur(production_kwh: float, tariff: Tariff, share: float) -> float:
    """Rent excl. VAT for one month given PV production in kWh."""
    variable = tariff.variable_eur_kwh * production_kwh * share
    return variable + tariff.breaker_fee_eur_month


def rent_breakdown(production_kwh: float, tariff: Tariff, share: float) -> pd.DataFrame:
    """Line-by-line reproduction of the contract annex table for one month."""
    items = [
        ("i", "dodávka elektriny VT", tariff.energy_vt_eur_kwh),
        ("ii", "dodávka elektriny NT", tariff.energy_nt_eur_kwh),
        ("iii", "dodávka elektriny – iná tarifa", tariff.energy_other_eur_kwh),
        ("iv", "spotrebná daň", tariff.excise_tax_eur_kwh),
        ("v", "distribúcia bez strát vr. prenosu", tariff.distribution_eur_kwh),
        ("vii", "distribúcia – tarifa za straty", tariff.losses_eur_kwh),
        ("viii", "systémové služby", tariff.system_services_eur_kwh),
        ("ix", "prevádzkovanie systému", tariff.system_operation_eur_kwh),
        ("x", "odvod do Národného jadrového fondu", tariff.nuclear_fund_eur_kwh),
        ("xi", "iná položka", tariff.other_eur_kwh),
    ]
    rows = [
        {
            "item": code,
            "name": name,
            "unit": "kWh",
            "unit_price_eur": price,
            "product_eur": price * production_kwh,
            "rent_eur": price * production_kwh * share,
        }
        for code, name, price in items
    ]
    rows.insert(
        5,
        {
            "item": "vi",
            "name": "zložka tarify za výkon (istič)",
            "unit": "mesiac",
            "unit_price_eur": tariff.breaker_fee_eur_month,
            "product_eur": tariff.breaker_fee_eur_month,
            "rent_eur": tariff.breaker_fee_eur_month,
        },
    )
    return pd.DataFrame(rows)


def rent_from_summary(summary: pd.DataFrame, tariff: Tariff, share: float) -> pd.DataFrame:
    """Add a ``rent_eur`` column to a monthly summary (output of monthly_summary)."""
    out = summary.copy()
    out["rent_eur"] = out["pv_yield_kwh"].map(
        lambda kwh: monthly_rent_eur(kwh, tariff, share) if pd.notna(kwh) else float("nan")
    )
    return out
