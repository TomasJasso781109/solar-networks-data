"""Plant registry, client tariffs and economic parameters.

All prices are EUR excl. VAT. Only tariff rates and contract parameters live
here; client identifiers (IČO, EIC, IBAN, addresses) and source documents stay
out of git (data/private/, .env).

Every value is tagged with its provenance in a comment:
  [DATA]        taken from a document (contract annex, supplier invoice, offer)
  [PREDPOKLAD]  assumption to be confirmed by the managing directors
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

TIMEZONE = "Europe/Bratislava"


# --------------------------------------------------------------------------
# Tariffs
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Tariff:
    """Per-kWh and fixed price components the client would pay its supplier.

    Rates mirror "Príloha č. 2 – vzorec výpočtu nájomného" and the supplier
    invoice (MAGNA ENERGIA, Sept 2026, sadzba C2-X3), which agree to the
    sixth decimal.
    """

    name: str
    valid_from: date
    energy_vt_eur_kwh: float  # i.   dodávka elektriny VT
    energy_nt_eur_kwh: float  # ii.  dodávka elektriny NT
    energy_other_eur_kwh: float  # iii. dodávka podľa inej tarify (used for 1T)
    excise_tax_eur_kwh: float  # iv.  spotrebná daň
    distribution_eur_kwh: float  # v.   distribúcia bez strát vr. prenosu
    breaker_fee_eur_month: float  # vi.  zložka tarify za výkon (istič) – contract value
    losses_eur_kwh: float  # vii. tarifa za straty
    system_services_eur_kwh: float  # viii. systémové služby
    system_operation_eur_kwh: float  # ix.  prevádzkovanie systému
    nuclear_fund_eur_kwh: float  # x.   odvod do NJF
    other_eur_kwh: float = 0.0  # xi.  iná položka

    @property
    def variable_eur_kwh(self) -> float:
        """Sum of all per-kWh components (reference price the rent tracks)."""
        return (
            self.energy_vt_eur_kwh
            + self.energy_nt_eur_kwh
            + self.energy_other_eur_kwh
            + self.excise_tax_eur_kwh
            + self.distribution_eur_kwh
            + self.losses_eur_kwh
            + self.system_services_eur_kwh
            + self.system_operation_eur_kwh
            + self.nuclear_fund_eur_kwh
            + self.other_eur_kwh
        )

    @property
    def energy_eur_kwh(self) -> float:
        """Commodity part only (silová elektrina)."""
        return self.energy_vt_eur_kwh + self.energy_nt_eur_kwh + self.energy_other_eur_kwh

    @property
    def grid_eur_kwh(self) -> float:
        """Regulated per-kWh part (distribúcia, straty, TSS, TPS, NJF, daň)."""
        return self.variable_eur_kwh - self.energy_eur_kwh


# [DATA] Príloha č. 2 REALCORP 2026 + faktúra MAGNA ENERGIA 09/2026
TARIFF_REALCORP_2026 = Tariff(
    name="REALCORP 2026 (MAGNA C2-X3, 1T)",
    valid_from=date(2026, 1, 1),
    energy_vt_eur_kwh=0.0,
    energy_nt_eur_kwh=0.0,
    energy_other_eur_kwh=0.13,
    excise_tax_eur_kwh=0.00132,
    distribution_eur_kwh=0.025939,
    breaker_fee_eur_month=30.0,  # contract value; supplier charges client 82.575
    losses_eur_kwh=0.010468,
    system_services_eur_kwh=0.01098,
    system_operation_eur_kwh=0.014071,
    nuclear_fund_eur_kwh=0.00327,
)


# --------------------------------------------------------------------------
# Plants
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Economics:
    """Investment and contract parameters of one plant (Solar Networks' view)."""

    capex_eur: float  # total investment excl. VAT
    capex_inverter_eur: float  # inverter incl. installation (for replacement)
    commissioning: date
    contract_share: float  # Solar Networks' share of the client's avoided cost
    contract_years: int  # remaining PPA / rental term from commissioning
    opex_eur_year: float = 0.0  # service, insurance, monitoring
    tariff: Tariff = TARIFF_REALCORP_2026
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Plant:
    plant_id: str
    name: str
    capacity_kwp: float
    inverter_kw_ac: float = 0.0
    battery_kwh: float = 0.0
    client: str = ""
    economics: Economics | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)


PLANTS: dict[str, Plant] = {
    "realcorp-rusovska-1": Plant(
        plant_id="realcorp-rusovska-1",
        name="REALCORP RUSOVSKÁ 1",
        capacity_kwp=27.6,  # [DATA] 60 × 460 Wp
        inverter_kw_ac=36.0,  # [DATA] Huawei SUN2000-36KTL-M1
        battery_kwh=0.0,  # [DATA] no BESS
        client="REALCORP RUSOVSKÁ s.r.o.",
        aliases=("sample-plant-01",),
        economics=Economics(
            capex_eur=27_900.50,  # [DATA] cenová ponuka 26. 2. 2023, bez DPH
            capex_inverter_eur=3_200.0,  # [DATA] 2 950 + 250 montáž
            commissioning=date(2023, 6, 1),  # [PREDPOKLAD] offer Feb 2023; confirm
            contract_share=0.80,  # [DATA] príloha č. 2
            contract_years=15,  # [PREDPOKLAD] confirm with contract
            opex_eur_year=0.0,  # [PREDPOKLAD] confirm (service, insurance)
            notes=(
                "Dátum spustenia 06/2023 je odhad z dátumu ponuky a kumulatívnej výroby.",
                "Dĺžka zmluvy 15 rokov a OPEX 0 €/rok sú predpoklady na potvrdenie.",
            ),
        ),
    ),
}

# data/samples/ uses the anonymized id; map it to the real plant.
PLANT_ALIASES: dict[str, str] = {
    alias: plant.plant_id for plant in PLANTS.values() for alias in plant.aliases
}


def get_plant(plant_id: str) -> Plant:
    """Look up a plant by id or alias."""
    key = PLANT_ALIASES.get(plant_id, plant_id)
    try:
        return PLANTS[key]
    except KeyError as exc:
        raise KeyError(f"Unknown plant '{plant_id}'. Known: {sorted(PLANTS)}") from exc


def plant_id_from_filename(filename: str) -> str:
    """Derive plant_id from a sample/export filename like
    ``sample-plant-01_hourly_2026-10.xlsx`` -> ``sample-plant-01``."""
    return filename.split("_", 1)[0]
