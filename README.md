# Reiseliv i Akershus — dashbord

Streamlit-dashbord som viser overnattinger, hotellnøkkeltall og
befolkningstall for Akershus og de tre reiselivsregionene
(Asker/Bærum, Follo, Romerike/Hadeland), hentet direkte fra
SSBs Statistikkbank (PxWebApi v2).

## 1. Kjør lokalt

```bash
git clone <din-repo-url>
cd akershus-reiseliv-dashboard
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

Appen åpnes på `http://localhost:8501`. Første gang du bytter filter kan
det ta noen sekunder mens data hentes fra SSB — deretter er svaret
cachet i 6 timer (se `CACHE_TTL_SECONDS` i `data_loader.py`).

## 2. Legg til på GitHub

```bash
git init
git add .
git commit -m "Første versjon av reiselivsdashbord for Akershus"
git branch -M main
git remote add origin <din-repo-url>
git push -u origin main
```

## 3. Publiser på Streamlit Community Cloud (gratis)

1. Gå til [share.streamlit.io](https://share.streamlit.io) og logg inn med GitHub.
2. Velg "New app" → pek på repoet ditt → `app.py` som hovedfil.
3. Deploy. Appen får en offentlig URL du kan dele.

Ingen hemmelige nøkler trengs — SSB sitt API er åpent og krever ikke
autentisering.

## 4. Prosjektstruktur

Alt ligger flatt i rotmappen med vilje — ingen undermapper som kan falle
bort ved opplasting til GitHub via nettleseren:

```
app.py                      Selve Streamlit-dashbordet (UI + filtre + grafer)
config.py                   Geografi- og tabellkoder samlet ett sted
ssb_client.py                Generisk klient mot SSBs PxWebApi v2
data_loader.py                Henter + cacher hver av de 7 SSB-tabellene
verdiskaping.py                Laster og aggregerer verdiskapingstallene
verdiskaping_akershus.csv       Innovasjon Norges verdiskapingstall, filtrert til Akershus
requirements.txt             Pakker som må installeres
```

**Viktig ved opplasting til GitHub:** alle disse filene må ligge synlige
direkte på repoets forside — ikke inni en mappe. Bruk helst
`git add . && git commit && git push` (se punkt 2) fremfor å dra
filer inn via GitHub sitt "Upload files"-vindu i nettleseren, som i praksis
kan hoppe over undermapper og enkeltfiler uten varsel.


## 5. Hva er dekket i denne versjonen

Se fanen **"ℹ️ Om data og forbehold"** inne i selve appen for en full
gjennomgang. Kort oppsummert:

| Ønsket data | Status |
|---|---|
| Overnattinger totalt, norsk/internasjonalt, hotell vs. hytte/camping | ✅ Dekket (tabell 14172) |
| Nøkkeltall hotell (omsetning/gjest, losjiomsetning, kapasitetsutnyttelse) | ✅ Dekket (14176, 14177) — bekreft eksakt indikatornavn i dropdown |
| RevPAR (= losjiomsetning per tilgjengelig rom) | ✅ Beregnes i appen fra 14176. Vises kun når begge nødvendige rader finnes for utvalget — ellers skjules panelet automatisk |
| Antall overnattinger korttidsutleie (Airbnb, Booking.com) | ➖ **Bevisst utelatt** fra omfanget, hentes ikke inn |
| Verdiskaping per innbygger | ✅ Dekket — Innovasjon Norge-tall delt på SSBs befolkningstall |
| Verdiskaping per reiselivsbransje og kommune | ✅ Dekket — `verdiskaping_akershus.csv` (fra Innovasjon Norges verdiskapingsrapport, årlig t.o.m. 2024) |

## 6. Oppdatere verdiskapingstallene senere

Filen `verdiskaping_akershus.csv` er et statisk uttrekk av
arket **"Aggregerte Data"** fra Innovasjon Norges Excel-rapport, filtrert
til Akershus' 21 kommuner. Når du får en ny versjon av rapporten:

1. Åpne den nye Excel-filen og gå til arket "Aggregerte Data".
2. Filtrer/eksporter radene der `Fylke == "Akershus"` til CSV med samme
   kolonner som i dag (`Regnskapsår, Fylke, Kommune, Landsdel, Næring,
   Sektor, Verdiskaping, Ansatte, Årsverk, Foretak, Aktive Foretak`).
3. Erstatt `verdiskaping_akershus.csv` og oppdater
   `VERDISKAPING_MAX_YEAR` i `config.py` til nyeste årstall i filen.

## 7. Neste steg (forslag til v2)

1. Verifiser eksakte indikatornavn i tabell 14176/14177 ved å kjøre appen
   og se hva som faktisk dukker opp i dropdown-menyene.
2. Eksporter til PDF/PowerPoint for rapportering, evt. legg til
   nedlastingsknapp for filtrert data (`st.download_button`).
3. Vurder kart-visualisering av verdiskaping/overnattinger per kommune
   (f.eks. med `plotly.express.choropleth` og SSBs kommune-geojson).
