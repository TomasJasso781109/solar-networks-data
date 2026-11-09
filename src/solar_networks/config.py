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
# Distribution (ZSD) – reserved capacity rules for NN sadzba C2-X3
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class DistributionTariff:
    """ZSD 'Cenník za distribúciu elektriny' – items needed for RK analysis.

    [DATA] Západoslovenská distribučná, a.s., Cenník za distribúciu elektriny
    platný od 1. 1. 2026 do 31. 12. 2026 (rozhodnutie ÚRSO č. 0077/2026/E),
    sekcia III a) Sadzba C2-X3. Cross-checked against the MAGNA invoice
    09/2026: 3 × 125 A × 0,2202 = 82,575 €/mes.
    """

    name: str
    valid_from: date
    valid_to: date
    source: str
    capacity_fee_eur_per_a_month: float  # tarifa za výkon, per ampere of main breaker (per phase)
    phases: int  # three-phase: fee = phases × I[A] × rate
    distribution_eur_kwh: float
    losses_eur_kwh: float
    penalty_rk_eur_kw: float  # prekročenie RK za každý prekročený kW / mesiac
    penalty_mrk_eur_kw: float  # prekročenie MRK
    min_rk_share_of_mrk: float  # minimálna RK = 50 % MRK
    rk_lock_months: int  # RK dohodnutá na 12 po sebe nasledujúcich mesiacov
    line_voltage_v: float = 400.0  # Uz for P = √3·Uz·I·cosφ
    cos_phi: float = 0.95  # [PREDPOKLAD] reproduces 125 A -> 82,3 kW on the invoice

    def kw_from_amps(self, amps: float) -> float:
        return (3**0.5) * self.line_voltage_v * amps * self.cos_phi / 1000.0

    def amps_from_kw(self, kw: float) -> float:
        return kw * 1000.0 / ((3**0.5) * self.line_voltage_v * self.cos_phi)

    def monthly_capacity_fee_eur(self, amps: float) -> float:
        return self.phases * amps * self.capacity_fee_eur_per_a_month


ZSD_C2_X3_2026 = DistributionTariff(
    name="ZSD C2-X3 2026",
    valid_from=date(2026, 1, 1),
    valid_to=date(2026, 12, 31),
    source=(
        "Západoslovenská distribučná, a.s. – Cenník za distribúciu elektriny platný "
        "od 1. 1. 2026 do 31. 12. 2026, časť III a) Sadzba C2-X3 "
        "(www.zsdis.sk/documents/96353/ZSD-Cennik-za-distribuciu-A5_0126_final.pdf)"
    ),
    capacity_fee_eur_per_a_month=0.2202,
    phases=3,
    distribution_eur_kwh=0.025939,
    losses_eur_kwh=0.010468,
    penalty_rk_eur_kw=33.1939,
    penalty_mrk_eur_kw=99.5818,
    min_rk_share_of_mrk=0.50,
    rk_lock_months=12,
)


@dataclass(frozen=True)
class SupplyPoint:
    """Odberné miesto (OM) parameters relevant for reserved-capacity analysis."""

    eic: str
    label: str
    main_breaker_a: float  # hlavný istič [A] = MRK on NN
    reserved_capacity_kw: float  # RK as printed on the invoice
    reserved_capacity_a: float  # RK in amperes (contracted)
    distribution: DistributionTariff = ZSD_C2_X3_2026
    metering_type: str = "A"  # A/B = quarter-hour metering (penalties apply)
    rk_valid_from: date | None = None  # [PREDPOKLAD] unknown -> confirm


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
    supply_point: SupplyPoint | None = None
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
        supply_point=SupplyPoint(
            eic="24ZZS4000026959Q",  # [DATA] invoice MAGNA 09/2026
            label="Bojnická 18, Bratislava – hlavné OM",
            main_breaker_a=125.0,  # [DATA]
            reserved_capacity_kw=82.3,  # [DATA]
            reserved_capacity_a=125.0,  # [DATA] RK = istič (82,575 € = 3 × 125 × 0,2202)
            metering_type="A",  # [DATA]
        ),
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
