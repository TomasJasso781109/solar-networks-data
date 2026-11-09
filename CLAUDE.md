# Solar Networks – dátový projekt

## O firme a projekte
Solar Networks inštaluje a spravuje fotovoltické elektrárne (FVE) a batériové
úložiská (BESS) pre firemných klientov na Slovensku. Všetky FVE a batérie sú
Huawei a bežia v platforme FusionSolar (máme inštalátorský prístup).
Aktuálne 15 elektrární, počet rastie. Niektoré merače bežia v platforme Enmon.
Distribučné dáta (registrové dáta, rezervovaná kapacita) pochádzajú zo ZSD.

Tento repozitár má tri účely:
1. Zber dát z FusionSolar, Enmon a ZSD na jedno miesto (Google Cloud).
2. Výpočty: výroba, samospotreba, dodávka do siete, návratnosť FVE/BESS,
   analýza rezervovanej kapacity a odchýlok.
3. Reporty: PDF pre klientov (Virtuálny energetik) a interné ROI reporty.

## Technológie a konvencie
- Python 3.12, pandas, openpyxl; závislosti v pyproject.toml.
- Kód a komentáre v angličtine, názvy stĺpcov v dátach v angličtine
  (napr. `timestamp`, `energy_kwh`, `plant_id`). Reporty pre klientov v slovenčine.
- Časové značky vždy s časovou zónou Europe/Bratislava, ukladané ako UTC.
- Energia v kWh, výkon v kW, ceny v EUR bez DPH.
- Každá funkcia v `src/` má test v `tests/`; pred komitom spusti `pytest`.
- Reálne klientske dáta a tokeny nikdy nekomituj. Tokeny sú v `.env`.
  Vzorky v `data/samples/` musia byť malé a anonymizované.

## Zdroje dát
- FusionSolar: export CSV/XLSX z portálu (teraz), Northbound API (neskôr).
- Enmon: export z portálu; API token zatiaľ nie je potvrdený.
- ZSD Distribučný portál: registrové dáta v 15-min intervaloch, export XLSX.
- Ceny energie a parametre klientov: `src/solar_networks/config.py`.

## Ako pracovať
- Pred väčšou zmenou navrhni plán a počkaj na potvrdenie.
- Malé kroky, každý overený testom na vzorových dátach.
- Keď niečo v dátach nesedí (medzery, duplicity, zmena formátu exportu),
  napíš to, nevymýšľaj hodnoty.
