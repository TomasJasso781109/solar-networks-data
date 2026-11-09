"""Internal ROI report (PDF) for the managing directors of Solar Networks.

Structure follows the internal "FVE návratnosť" methodology:
 1. Zhrnutie  2. Reálna výkonnosť  3. Porovnanie s plánom  4. Scenáre a
 citlivosť  5. Riziká  6. Opatrenia  7. Predpoklady a zdroje.

Never send this document to a client – it contains margin and ROI.
"""

from __future__ import annotations

import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.enums import TA_LEFT  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from solar_networks.model.roi import RoiResult  # noqa: E402

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
_FONTS_REGISTERED = False

NAVY = colors.HexColor("#1F3A5F")
ACCENT = colors.HexColor("#F2A900")
GREY = colors.HexColor("#5F6B7A")
LIGHT = colors.HexColor("#EEF2F7")


def _register_fonts() -> None:
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Oblique", str(FONT_DIR / "DejaVuSans-Oblique.ttf")))
    pdfmetrics.registerFontFamily(
        "DejaVu", normal="DejaVu", bold="DejaVu-Bold", italic="DejaVu-Oblique", boldItalic="DejaVu-Bold"
    )
    plt.rcParams["font.family"] = "DejaVu Sans"
    _FONTS_REGISTERED = True


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="DejaVu", fontSize=9.5, leading=13, alignment=TA_LEFT)
    return {
        "body": base,
        "small": ParagraphStyle("small", parent=base, fontSize=8, leading=10.5, textColor=GREY),
        "title": ParagraphStyle("title", parent=base, fontName="DejaVu-Bold", fontSize=20, leading=25, textColor=NAVY),
        "subtitle": ParagraphStyle("subtitle", parent=base, fontSize=11, leading=14, textColor=GREY),
        "h1": ParagraphStyle("h1", parent=base, fontName="DejaVu-Bold", fontSize=13.5, leading=17, textColor=NAVY, spaceBefore=10, spaceAfter=5),
        "h2": ParagraphStyle("h2", parent=base, fontName="DejaVu-Bold", fontSize=10.5, leading=14, textColor=NAVY, spaceBefore=6, spaceAfter=3),
        "kpi_label": ParagraphStyle("kpi_label", parent=base, fontSize=8, leading=10, textColor=GREY),
        "kpi_value": ParagraphStyle("kpi_value", parent=base, fontName="DejaVu-Bold", fontSize=15, leading=18, textColor=NAVY),
        "box": ParagraphStyle("box", parent=base, fontSize=9.5, leading=13, backColor=LIGHT, borderPadding=6),
    }


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------
def eur(value: float, decimals: int = 0) -> str:
    text = f"{value:,.{decimals}f}".replace(",", " ").replace(".", ",")
    return f"{text} €"


def kwh(value: float) -> str:
    return f"{value:,.0f}".replace(",", " ") + " kWh"


def pct(value: float, decimals: int = 1) -> str:
    return f"{value * 100:.{decimals}f}".replace(".", ",") + " %"


def years(value: float) -> str:
    return f"{value:.1f}".replace(".", ",") + " r."


def _table(data: list[list], col_widths=None, header=True, zebra=True, align_right_from=1) -> Table:
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (align_right_from, 1), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, -1), (-1, -1), 0.5, GREY),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if header:
        style += [
            ("FONTNAME", (0, 0), (-1, 0), "DejaVu-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (align_right_from, 0), (-1, 0), "RIGHT"),
        ]
    if zebra:
        for i in range(1, len(data)):
            if i % 2 == 0:
                style.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(style))
    return t


def _fig_to_image(fig, width_mm: float) -> Image:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=180, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    img = Image(buf)
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth = width_mm * mm
    img.drawHeight = width_mm * mm * ratio
    return img


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------
def _chart_monthly(realized: pd.DataFrame) -> Image:
    fig, ax1 = plt.subplots(figsize=(7.2, 2.9))
    x = range(len(realized))
    ax1.bar(x, realized["pv_yield_kwh"], color="#1F3A5F", width=0.55, label="Výroba [kWh]")
    ax1.set_ylabel("kWh")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(realized["month"], fontsize=8)
    ax2 = ax1.twinx()
    ax2.plot(list(x), realized["rent_eur"], color="#F2A900", marker="o", label="Nájomné [€]")
    ax2.set_ylabel("€")
    for spine in ("top",):
        ax1.spines[spine].set_visible(False)
        ax2.spines[spine].set_visible(False)
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2, fontsize=8, frameon=False)
    ax1.set_title("Reálna výroba a fakturované nájomné po mesiacoch", fontsize=10, color="#1F3A5F")
    fig.tight_layout()
    return _fig_to_image(fig, 170)


def _chart_cashflow(result: RoiResult) -> Image:
    fig, ax = plt.subplots(figsize=(7.2, 3.2))
    palette = {"pesimistický": "#C0392B", "základný": "#1F3A5F", "optimistický": "#2E8B57"}
    for sc in result.scenarios:
        df = sc.cash_flows
        ax.plot(df["year"], df["cumulative_eur"], marker="o", markersize=3,
                color=palette.get(sc.scenario.name, "#555"), label=sc.scenario.name)
    ax.axhline(0, color="#999", linewidth=0.8)
    as_of_year = result.as_of.year - result.plant.economics.commissioning.year + 1
    ax.axvline(as_of_year, color="#F2A900", linestyle="--", linewidth=1)
    ax.text(as_of_year + 0.1, ax.get_ylim()[0] * 0.9, "dnes", color="#F2A900", fontsize=8)
    ax.set_xlabel("rok prevádzky")
    ax.set_ylabel("kumulatívny cash flow [€]")
    ax.set_title("Kumulatívny cash flow – 3 scenáre", fontsize=10, color="#1F3A5F")
    ax.legend(fontsize=8, frameon=False)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    return _fig_to_image(fig, 170)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def build_roi_pdf(
    result: RoiResult,
    realized: pd.DataFrame,
    output: str | Path,
    sources: list[str],
    plan_comparison: str | None = None,
) -> Path:
    """Render the PDF. ``realized`` is a monthly summary with ``rent_eur``."""
    _register_fonts()
    st = _styles()
    plant = result.plant
    econ = plant.economics
    a = result.assumptions
    base, pes, opt = result.base, result.by_name("pesimistický"), result.by_name("optimistický")

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"ROI – {plant.name}", author="Solar Networks – interný report",
    )

    def footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont("DejaVu", 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(18 * mm, 9 * mm, "SOLAR NETWORKS – INTERNÉ – neposielať klientovi")
        canvas.drawRightString(A4[0] - 18 * mm, 9 * mm, f"strana {_doc.page}")
        canvas.restoreState()

    story = []
    P = lambda text, style="body": Paragraph(text, st[style])  # noqa: E731

    # ---- 1. Zhrnutie ------------------------------------------------------
    story += [
        P(f"Návratnosť FVE – {plant.name}", "title"),
        P(f"Interný report pre konateľov · stav k {result.as_of.strftime('%d. %m. %Y')} · "
          f"{plant.capacity_kwp:g} kWp DC / {plant.inverter_kw_ac:g} kW AC · bez BESS", "subtitle"),
        Spacer(1, 6),
        P("1. Zhrnutie", "h1"),
    ]
    kpis = [
        ("IRR (základný)", pct(base.irr)),
        ("NPV 6 % (základný)", eur(base.npv_eur)),
        ("Návratnosť (základný)", years(base.payback_years)),
        ("Break-even cena", f"{result.break_even_price_eur_kwh:.3f}".replace(".", ",") + " €/kWh"),
    ]
    kpi_table = Table(
        [[Paragraph(l, st["kpi_label"]) for l, _ in kpis], [Paragraph(v, st["kpi_value"]) for _, v in kpis]],
        colWidths=[43 * mm] * 4,
    )
    kpi_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.white),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story += [kpi_table, Spacer(1, 6)]

    scen_rows = [["Scenár", "Vývoj referenčnej ceny", "IRR", "NPV (6 %)", "Návratnosť", "Čistý CF spolu"]]
    for sc in (pes, base, opt):
        s = sc.scenario
        def _pct_label(v: float, suffix: str) -> str:
            return ("0\u00a0%" if abs(v) < 1e-9 else f"{v:+.0%}".replace("%", "\u00a0%")) + suffix
        path = f"{_pct_label(s.price_shift, ' dnes')}, {_pct_label(s.price_growth, '/rok')}"
        scen_rows.append([s.name, path, pct(sc.irr), eur(sc.npv_eur), years(sc.payback_years), eur(sc.total_net_eur)])
    story += [_table(scen_rows, col_widths=[26 * mm, 48 * mm, 20 * mm, 28 * mm, 24 * mm, 28 * mm], align_right_from=2)]

    verdict = (
        "držať a replikovať" if pes.irr > a.discount_rate else "držať, ale preveriť ceny"
    )
    elapsed_years = int((result.as_of - econ.commissioning).days // 365.25)
    revenue_to_date = base.cash_flows.loc[1:elapsed_years, "revenue_eur"].sum()
    story += [
        Spacer(1, 6),
        P(f"<b>Odporúčanie: {verdict}.</b> Investícia {eur(econ.capex_eur)} [DATA] sa pri dnešnej referenčnej "
          f"cene {result.reference_price_eur_kwh:.4f} €/kWh [DATA] a 80 % zmluvnom podiele [DATA] vráti "
          f"za {years(base.payback_years)} [VÝPOČET]; aj v pesimistickom scenári (−25 % ceny) ostáva IRR "
          f"{pct(pes.irr)} nad diskontom {pct(a.discount_rate, 0)}. Výsledok je najcitlivejší na dátum spustenia "
          f"a z neho odvodený ročný výnos (časť 7). Odhad doterajších tržieb za {elapsed_years} celé roky prevádzky: "
          f"{eur(revenue_to_date)} [VÝPOČET, pri dnešnej cene] – ostáva splatiť približne "
          f"{eur(max(econ.capex_eur - revenue_to_date, 0))}.", "box"),
    ]

    # ---- 2. Reálna výkonnosť -------------------------------------------
    story += [P("2. Reálna výkonnosť", "h1")]
    if not realized.empty:
        hdr = ParagraphStyle("hdr", parent=st["body"], fontName="DejaVu-Bold", fontSize=8, leading=10, textColor=colors.white)
        rows = [[Paragraph(h, hdr) for h in ["Mesiac", "Výroba", "Spotreba", "Dodávka do siete", "Samospotreba", "Nájomné bez DPH", "€/kWh"]]]
        for _, r in realized.iterrows():
            cons = kwh(r["consumption_kwh"]) if pd.notna(r["consumption_kwh"]) else "n/a"
            sc_rate = pct(r["self_consumption_rate_pct"] / 100) if pd.notna(r["self_consumption_rate_pct"]) else "n/a"
            rows.append([r["month"], kwh(r["pv_yield_kwh"]), cons, kwh(r["grid_feed_in_kwh"]), sc_rate,
                         eur(r["rent_eur"], 2), f"{r['rent_eur'] / r['pv_yield_kwh']:.3f}".replace(".", ",")])
        story += [_table(rows, col_widths=[24 * mm, 22 * mm, 22 * mm, 28 * mm, 28 * mm, 30 * mm, 18 * mm]),
                  Spacer(1, 4), _chart_monthly(realized), Spacer(1, 4)]
    story += [
        P(f"Realizovaná cena pre Solar Networks: <b>{result.realized_price_eur_kwh:.4f} €/kWh</b> výroby [VÝPOČET] "
          f"= 80 % × {result.reference_price_eur_kwh:.4f} €/kWh + 30 €/mes. za istič rozpočítané na ročnú výrobu. "
          f"Odhad výroby v 1. roku: <b>{kwh(result.annual_yield_year1_kwh)}</b> "
          f"({result.annual_yield_year1_kwh / plant.capacity_kwp:,.0f} kWh/kWp) – {result.yield_source}. "
          f"Mesačné dáta pochádzajú z exportov FusionSolar [DATA]; mesiace bez exportu nie sú v tabuľke."),
    ]

    # ---- 3. Porovnanie s plánom ----------------------------------------
    story += [P("3. Porovnanie s pôvodným plánom", "h1"),
              P(plan_comparison or
                "Pôvodný investičný plán (očakávaná výroba a výnos pri podpise zmluvy) nebol k dispozícii. "
                "V prílohe č. 2 sú pre rok 2026 odhadované mesačné výroby (napr. jún 4 150 kWh, júl 4 200 kWh) "
                "[DATA]; po doplnení reálnych mesiacov z FusionSolar sa porovnanie plán/skutočnosť doplní automaticky.")]

    # ---- 4. Scenáre a citlivosť ----------------------------------------
    story += [PageBreak(), P("4. Scenáre a citlivosť", "h1"), _chart_cashflow(result), Spacer(1, 6)]
    cf_rows = [["Rok", "Kal. rok", "Výroba", "Ref. cena", "Tržby", "Náklady", "Čistý CF", "Kumulatívne"]]
    for _, r in base.cash_flows.iterrows():
        cf_rows.append([
            int(r["year"]), int(r["calendar_year"]), kwh(r["production_kwh"]) if r["year"] else "–",
            f"{r['reference_price_eur_kwh']:.3f}".replace(".", ",") if r["year"] else "–",
            eur(r["revenue_eur"]), eur(r["opex_eur"] + r["capex_eur"]), eur(r["net_cash_flow_eur"]), eur(r["cumulative_eur"]),
        ])
    story += [P("Základný scenár – ročný cash flow [VÝPOČET]", "h2"),
              _table(cf_rows, col_widths=[10 * mm, 16 * mm, 24 * mm, 18 * mm, 24 * mm, 24 * mm, 26 * mm, 30 * mm])]
    story += [
        Spacer(1, 6),
        P("Citlivosť", "h2"),
        P(f"• Break-even: pri konštantnej referenčnej cene <b>{result.break_even_price_eur_kwh:.3f} €/kWh</b> "
          f"[VÝPOČET] klesne IRR na cieľových {pct(a.target_irr, 0)}; to je "
          f"{(1 - result.break_even_price_eur_kwh / result.reference_price_eur_kwh):.0%} pod dnešnou cenou.".replace("%", " %")),
        P(f"• Výnos: každých −10 % ročnej výroby (zatienenie, porucha, nižší reálny výnos pri skoršom spustení) "
          f"posúva návratnosť v základnom scenári približne o {years(base.payback_years * 0.11)} [VÝPOČET, lineárny odhad]."),
        P(f"• Výmena striedača v {a.inverter_replacement_year}. roku za {eur(econ.capex_inverter_eur)} [PREDPOKLAD] "
          f"je už v cash flow; bez nej by NPV bolo o {eur(econ.capex_inverter_eur / (1 + a.discount_rate) ** a.inverter_replacement_year)} vyššie."),
    ]

    # ---- 5. Riziká ---------------------------------------------------------
    story += [PageBreak(), P("5. Riziká – diablov advokát", "h1")]
    risks = [
        ("Pokles cien elektriny", "Nájomné kopíruje referenčnú cenu; −25 % je pesimistický scenár, ale 2020 ukázal aj hlbšie prepady silovej zložky. Regulovaná časť (≈ 0,066 €/kWh) je stabilnejšia ako silová (0,13 €/kWh)."),
        ("Zmena taríf ÚRSO", "Položky v.–x. sú regulované ročne; zmena štruktúry (napr. presun do fixnej zložky) by znížila per-kWh základ vzorca."),
        ("Zmena dodávateľa klientom", "Vzorec viaže ceny na zmluvu klienta s dodávateľom; lacnejší dodávateľ = nižšie nájomné. Faktúra MAGNA 09/2026 potvrdzuje dnešné sadzby [DATA]."),
        ("Skryté náklady", "OPEX je v modeli 0 € [PREDPOKLAD]. Servis, poistenie, monitoring a výjazdy môžu reálne stáť 1–2 % CAPEX ročne (≈ 280–560 €), čo zníži IRR o ~1–2 p. b."),
        ("Úverové riziko klienta", "Celý výnos závisí od jedného odberateľa; pri jeho insolvencii ostáva aktívum na cudzej streche."),
        ("Technické", "DC/AC pomer 0,77 (27,6 kWp / 36 kW) – striedač je predimenzovaný, mierne horšia účinnosť pri nízkom výkone; jalová dodávka 414 kVArh/mes. sa klientovi účtuje (6,87 €) [DATA] a kazí vzťah."),
        ("Prekročenie RK", "Klient prekročil rezervovanú kapacitu 82,3 kW (max 86,07 kW 17. 9. 2026 12:15) [DATA] – nie je naše riziko, ale príležitosť (časť 6)."),
    ]
    story += [_table([["Riziko", "Komentár"]] + [[P(f"<b>{t}</b>"), P(d)] for t, d in risks],
                     col_widths=[40 * mm, 134 * mm], align_right_from=5, zebra=True)]

    # ---- 6. Opatrenia ----------------------------------------------------
    story += [P("6. Opatrenia", "h1"),
              P("Quick Win (do 3 mesiacov)", "h2"),
              P("• Nastaviť cos φ / kompenzáciu na striedači – odstráni poplatok za jalovú dodávku (≈ 80 €/rok pre klienta) a zlepší vnímanie FVE."),
              P("• Overiť dátum spustenia a reálny ročný výnos z FusionSolar (Total Yield po rokoch) – spresní IRR o niekoľko p. b."),
              P("• Automatizovať prílohu č. 2: výroba z FusionSolar → nájomné; odstráni odhady (okt. 2026 = 0 kWh v hárku, reálne 2 174,6 kWh [DATA])."),
              P("Systémové riešenie (6–18 mesiacov)", "h2"),
              P("• Analýza rezervovanej kapacity (Virtuálny energetik): klient platí 82,58 €/mes. za istič a prekračuje RK; batéria 20–30 kWh na peak shaving by znížila RK aj pokuty – nový výnosový kanál pre SN (BESS prenájom)."),
              P("• Dostavba DC: striedač 36 kW AC unesie ~45 kWp DC; dostavba ~17 kWp pri CAPEX ~600 €/kWp [PREDPOKLAD] zvýši výrobu o ~60 % pri rovnakom fixnom základe."),
              P("• Zdieľanie prebytkov (130 €/MWh [DATA]) je zanedbateľné (0,2 MWh/mes.) – prebytky radšej do batérie alebo posun spotreby."),
              P("• ESG/záruka pôvodu: pri 30 MWh/rok len symbolické; zmysel má až agregovane za všetkých 15 elektrární.")]

    # ---- 7. Predpoklady a zdroje -----------------------------------------
    story += [P("7. Predpoklady a zdroje", "h1"), P("Predpoklady [PREDPOKLAD]", "h2")]
    assumptions_rows = [["Parameter", "Hodnota", "Z čoho vychádza"]]
    assumptions_rows += [
        ["Dátum spustenia", econ.commissioning.strftime("%m/%Y"), "odhad z dátumu ponuky (02/2023) a kumulatívnej výroby – POTVRDIŤ"],
        ["Dĺžka zmluvy", f"{econ.contract_years} rokov", "štandard SN – POTVRDIŤ podľa zmluvy"],
        ["OPEX", eur(econ.opex_eur_year) + "/rok", "zatiaľ nezadané – POTVRDIŤ"],
        ["Degradácia", pct(a.degradation_per_year), a.labels["degradation_per_year"]],
        ["Diskont", pct(a.discount_rate, 0), a.labels["discount_rate"]],
        ["Výmena striedača", f"{a.inverter_replacement_year}. rok, {eur(econ.capex_inverter_eur)}", a.labels["inverter_replacement_year"]],
        ["Scenáre ceny", "−25 % / +2 %/rok / +15 % & +3 %/rok", "interná metodika FVE návratnosť"],
        ["Ceny v rokoch 2023–2025", "dnešná sadzba", "historické faktúry neboli k dispozícii"],
    ]
    cell = ParagraphStyle("cell", parent=st["body"], fontSize=8.5, leading=11)
    assumptions_rows = [assumptions_rows[0]] + [[Paragraph(str(c), cell) for c in r] for r in assumptions_rows[1:]]
    story += [_table(assumptions_rows, col_widths=[36 * mm, 46 * mm, 92 * mm], align_right_from=5),
              Spacer(1, 6), P("Zdroje [DATA]", "h2")]
    story += [P(f"• {s}") for s in sources]
    story += [Spacer(1, 8),
              P("Označenie čísel: [DATA] = z dokumentu alebo exportu, [VÝPOČET] = odvodené modelom, "
                "[PREDPOKLAD] = predpoklad na potvrdenie konateľmi. Všetky sumy bez DPH.", "small")]

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return output
